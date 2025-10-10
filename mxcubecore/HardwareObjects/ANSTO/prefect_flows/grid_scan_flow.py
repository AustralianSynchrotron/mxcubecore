import logging
from typing import Union

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import redis
from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.SampleView import (
    Grid,
    SampleView,
)
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.grid_scan import (
    GridScanDialogBox,
    GridScanParams,
)
from .sync_prefect_client import MX3SyncPrefectClient


class GridScanFlow(AbstractPrefectWorkflow):
    """Prefect Raster Workflow"""

    def __init__(
        self,
        state,
        resolution: Resolution,
        redis_connection: redis.StrictRedis,
        sample_view: SampleView,
    ) -> None:
        super().__init__(state, resolution)

        self.redis_connection = redis_connection
        self.sample_view = sample_view
        self._collection_type = "grid_scan"

    def run(self, dialog_box_parameters: dict) -> None:
        """
        Executes a raster workflow. First a dialog box is opened, then a
        bluesky plan is executed and finally the data produced by the
        Simplon API is analysed and converted to a heatmap containing RGBA values.
        The heatmap is displayed in MXCuBE.

        Parameters
        ----------
        metadata : dict
            A metadata dictionary sent from mxcube to the bluesky queueserver

        Returns
        -------
        None
        """

        self._state.value = "RUNNING"

        grid_list: list[Grid] = self.sample_view.get_grids()
        logging.getLogger("HWR").info(f"Number of grids: {len(grid_list)}")
        grid = grid_list[-1]

        sid = grid.id
        num_cols = grid.num_cols
        num_rows = grid.num_rows
        beam_position = grid.beam_pos
        screen_coordinate = [round(grid.screen_coord[0]), round(grid.screen_coord[1])]
        width = round(grid.width)
        height = round(grid.height)

        dialog_box_model = GridScanDialogBox.model_validate(dialog_box_parameters)
        head_type = self.get_head_type()

        if not settings.ADD_DUMMY_PIN_TO_DB:
            logging.getLogger("HWR").info("Getting sample from the data layer...")
            sample_id = self.get_sample_id_of_mounted_sample(dialog_box_model)
            logging.getLogger("HWR").info(f"Mounted sample id: {sample_id}")

        else:
            logging.getLogger("HWR").warning(
                "SIM mode! The sample id will not be obtained from the data layer. "
                "Setting sample id to 1. "
                "Ensure that this sample id exists in the db before launching the flow"
            )
            sample_id = 1

        photon_energy = energy_master.get()

        default_resolution = float(self.redis_connection.get("grid_scan:resolution"))
        detector_distance = self._resolution_to_distance(
            default_resolution,
            energy=photon_energy,
        )
        logging.getLogger("HWR").info(
            f"Detector distance corresponding to {default_resolution} A: {detector_distance} [m]"
        )

        if head_type == "Plate":
            use_centring_table = False
        else:
            use_centring_table = True

        prefect_parameters = GridScanParams(
            sample_id=sample_id,
            grid_top_left_coordinate=screen_coordinate,
            grid_height=height,
            grid_width=width,
            beam_position=beam_position,
            number_of_columns=num_cols,
            number_of_rows=num_rows,
            detector_distance=detector_distance,
            photon_energy=photon_energy,
            omega_range=float(self._get_dialog_box_param("omega_range")),
            md3_alignment_y_speed=dialog_box_model.md3_alignment_y_speed,
            hardware_trigger=True,
            number_of_processes=settings.GRID_SCAN_NUMBER_OF_PROCESSES,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
            use_centring_table=use_centring_table,
        )

        logging.getLogger("HWR").info(
            f"Parameters sent to prefect flow: {prefect_parameters}"
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)
        self.start_prefect_flow_and_get_results_from_redis(
            prefect_parameters=prefect_parameters,
            num_cols=num_cols,
            num_rows=num_rows,
            grid_id=sid,
        )
        logging.getLogger("user_level_log").info("Grid scan completed successfully.")

    def start_prefect_flow_and_get_results_from_redis(
        self,
        prefect_parameters: GridScanParams,
        num_cols: int,
        num_rows: int,
        grid_id: int,
    ) -> None:
        """
        Starts a grid scan  prefect flow using the prefect client and gets spotfinder results
        from redis as soon as the prefect flow changes its state from `SCHEDULED` to
        `RUNNING`

        Parameters
        ----------
        prefect_parameters : GridScanParams
            The prefect grid scan parameters
        num_cols : int
            The number of columns of the grid
        num_rows : int
            The number of rows of the grid
        grid_id : int
            The MXCuBE grid id

        Returns
        -------
        None

        Raises
        ------
        QueueExecutionException
            If an exception occurs, we first check if the flow state is `FAILED`
            and in this case we raise a QueueExecutionException with the flow run error message
            (this will most likely occur because of hardware errors).
            However if the flow is not `FAILED`, and an exception still occurs,
            then we raise a QueueExecutionException
            with the exception message.
        """

        grid_scan_flow = MX3SyncPrefectClient(
            name=settings.GRID_SCAN_DEPLOYMENT_NAME,
            parameters=prefect_parameters.model_dump(exclude_none=True),
        )
        try:
            flow_run_uuid = grid_scan_flow.trigger_grid_scan()

            logging.getLogger("HWR").info("Getting spotfinder results from redis...")
            logging.getLogger("HWR").info(
                f"Expected number of columns and rows: {num_cols}, {num_rows}"
            )

            if not self.mxcubecore_workflow_aborted:
                last_id = 0
                number_of_frames = num_cols * num_rows
                score_array = np.zeros((num_rows, num_cols))
                with redis.StrictRedis(
                    host=settings.MXCUBE_REDIS_HOST,
                    port=settings.MXCUBE_REDIS_PORT,
                    username=settings.MXCUBE_REDIS_USERNAME,
                    password=settings.MXCUBE_REDIS_PASSWORD,
                    db=settings.MXCUBE_REDIS_DB,
                ) as redis_client:
                    for _ in range(number_of_frames):
                        data, last_id = self.read_message_from_redis_streams(
                            topic=f"spotfinder_results:{flow_run_uuid}",
                            id=last_id,
                            redis_client=redis_client,
                        )
                        heatmap_coordinate = (
                            int(data[b"heatmap_coordinate_x"]),
                            int(data[b"heatmap_coordinate_y"]),
                        )
                        score_array[heatmap_coordinate[1], heatmap_coordinate[0]] = (
                            float(data[b"score"])
                        )

                logging.getLogger("HWR").debug(f"score_list: {score_array}")
                logging.getLogger("HWR").info(f"Creating heatmap...")

                heatmap_array = self.create_heatmap(
                    num_cols=num_cols,
                    num_rows=num_rows,
                    score_array=score_array,
                )

                heatmap = {
                    i: [i, list(heatmap_array[i - 1])]
                    for i in range(1, num_rows * num_cols + 1)
                }

                heatmap_dict = {"heatmap": heatmap}

                self.sample_view.set_grid_data(
                    grid_id, heatmap_dict, data_file_path=None
                )

            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False

        except Exception as ex:
            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False

            grid_scan_flow.check_flow_state()

            logging.getLogger("user_level_log").error(
                f"Grid scan flow was not successful: {str(ex)}"
            )
            raise QueueExecutionException(str(ex), self) from ex

    def read_message_from_redis_streams(
        self, topic: str, id: Union[bytes, int], redis_client: redis.StrictRedis
    ) -> tuple[dict, bytes]:
        """
        Reads pickled messages from a redis stream

        Parameters
        ----------
        topic : str
            Name of the topic of the redis stream, aka, the sample_id
        id : Union[bytes, int]
            id of the topic in bytes or int format
        redis_client : redis.StrictRedis
            A redis client

        Returns
        -------
        data, last_id : tuple[dict, bytes]
            A tuple containing a dictionary and the last id.
            The diction ary has the following keys:
            b'type', b'number_of_spots', b'image_id', and b'sequence_id'
        """

        response = redis_client.xread(
            {topic: id}, count=1, block=30000
        )  # Wait 30 seconds
        if not response:
            raise QueueExecutionException(
                message=f"Results not found for id {id} after 30 seconds", origin=self
            )

        # Extract key and messages from the response
        _, messages = response[0]

        # Update last_id and store messages data
        last_id, data = messages[0]

        return data, last_id

    def create_heatmap(
        self, num_cols: int, num_rows: int, score_array: npt.NDArray
    ) -> npt.NDArray:
        """
        Creates a heatmap from the number of spots, number of columns
        and number of rows of a grid.

        Parameters
        ----------
        num_cols : int
            Number of columns
        num_rows : int
            Number of rows
        number_of_spots_array : npt.NDArray
            List containing number of spots

        Returns
        -------
        result : npt.NDArray
            An array containing a heatmap with rbga values
        """
        z = score_array

        z_min = np.min(z)
        z_max = np.max(z)

        # Normalise the array
        norm_z = (z - z_min) / (z_max - z_min)

        cmap = plt.get_cmap("seismic")
        heatmap = cmap(norm_z) * 255

        return heatmap.reshape(num_rows * num_cols, 4)

    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary following the JSON schema.
        """
        properties = {
            "md3_alignment_y_speed": {
                "title": "Alignment Y Speed [mm/s]",
                "type": "number",
                "minimum": 0.1,
                "maximum": 14.8,
                "default": float(self._get_dialog_box_param("md3_alignment_y_speed")),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "default": float(self._get_dialog_box_param("transmission")),
                "widget": "textarea",
            },
        }
        sample_properties, sample_conditional = self.build_auto_add_sample_schema()
        properties.update(sample_properties)

        dialog = {
            "properties": properties,
            "required": [
                "md3_alignment_y_speed",
                "transmission",
            ],
            "dialogName": "Grid Scan Parameters",
        }

        dialog.update(sample_conditional)

        return dialog
