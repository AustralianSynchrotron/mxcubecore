import asyncio
import logging
import pickle
from os import environ
from typing import Union

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import redis
import redis.asyncio
from mx3_beamline_library.devices.beam import (
    energy_master,
    transmission,
)
from mx3_beamline_library.devices.motors import actual_sample_detector_distance

from mxcubecore.HardwareObjects.SampleView import (
    Grid,
    SampleView,
)
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.grid_scan import (
    GridScanDialogBox,
    GridScanParams,
)

GRID_SCAN_DEPLOYMENT_NAME = environ.get(
    "GRID_SCAN_DEPLOYMENT_NAME", "mxcube-grid-scan/plans"
)
_number_of_processes = environ.get("GRID_SCAN_NUMBER_OF_PROCESSES", None)
if _number_of_processes is not None:
    GRID_SCAN_NUMBER_OF_PROCESSES = int(_number_of_processes)
else:
    GRID_SCAN_NUMBER_OF_PROCESSES = None

ADD_DUMMY_PIN_TO_DB = environ.get("ADD_DUMMY_PIN_TO_DB", "false").lower() == "true"


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

        if not ADD_DUMMY_PIN_TO_DB:
            logging.getLogger("HWR").info("Getting pin from the data layer...")
            pin = self.get_pin_model_of_mounted_sample_from_db()
            logging.getLogger("HWR").info(f"Mounted pin: {pin}")
            sample_id = str(pin.id)  # Could also be sample name
        else:
            logging.getLogger("HWR").warning(
                "The sample id will not be obtained from the data layer. "
                "Setting sample id to `test_sample`. "
                "This should only be used for development"
            )
            sample_id = "1"

        redis_grid_scan_id = self.redis_connection.get(
            f"mxcube_grid_scan_id:{sample_id}"
        )
        if redis_grid_scan_id is None:
            grid_scan_id = 0
        else:
            grid_scan_id = int(redis_grid_scan_id) + 1

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=dialog_box_model.photon_energy,
            roi_mode="4M",
        )

        prefect_parameters = GridScanParams(
            sample_id=sample_id,
            grid_scan_id=grid_scan_id,
            grid_top_left_coordinate=screen_coordinate,
            grid_height=height,
            grid_width=width,
            beam_position=beam_position,
            number_of_columns=num_cols,
            number_of_rows=num_rows,
            detector_distance=detector_distance,
            photon_energy=dialog_box_model.photon_energy,
            omega_range=dialog_box_model.omega_range,
            md3_alignment_y_speed=dialog_box_model.md3_alignment_y_speed,
            hardware_trigger=True,
            number_of_processes=GRID_SCAN_NUMBER_OF_PROCESSES,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
        )

        self.redis_connection.set(
            f"mxcube_grid_scan_id:{sample_id}", grid_scan_id, ex=86400
        )
        logging.getLogger("HWR").info(
            f"Parameters sent to prefect flow: {prefect_parameters}"
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            loop = self._get_asyncio_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.start_prefect_flow_and_get_results_from_redis(
                    prefect_parameters=prefect_parameters,
                    num_cols=num_cols,
                    num_rows=num_rows,
                    grid_id=sid,
                )
            )
        except Exception as ex:
            logging.getLogger("HWR").info(f"Failed to execute raster flow: {ex}")
            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False
            logging.getLogger("user_level_log").warning(
                "Grid scan flow was not successful"
            )
            raise QueueExecutionException(str(ex), self) from ex

    async def start_prefect_flow_and_get_results_from_redis(
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
        num_cols : int)
            The number of columns of the grid
        num_rows : int
            The number of rows of the grid
        grid_id : int
            The MXCuBE grid id

        Returns
        -------
        None
        """

        grid_scan_flow = MX3PrefectClient(
            name=GRID_SCAN_DEPLOYMENT_NAME,
            parameters=prefect_parameters.model_dump(exclude_none=True),
        )

        await grid_scan_flow.trigger_grid_scan()

        logging.getLogger("HWR").info("Getting spotfinder results from redis...")
        logging.getLogger("HWR").info(
            f"Expected number of columns and rows: {num_cols}, {num_rows}"
        )

        if not self.mxcubecore_workflow_aborted:
            last_id = 0
            grid_size = num_cols * num_rows
            number_of_spots_array = np.zeros((num_rows, num_cols))
            resolution_array = np.zeros((num_rows, num_cols))
            async with redis.asyncio.StrictRedis(
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                username=self.REDIS_USERNAME,
                password=self.REDIS_PASSWORD,
                db=self.REDIS_DB,
            ) as async_redis_client:
                for _ in range(grid_size):
                    data, last_id = await self.read_message_from_redis_streams(
                        topic=f"number_of_spots_{prefect_parameters.grid_scan_id}:{prefect_parameters.sample_id}",
                        id=last_id,
                        redis_client=async_redis_client,
                    )
                    number_of_spots = float(data[b"number_of_spots"])
                    resolution = float(data[b"resolution"])
                    heatmap_coordinate = pickle.loads(data[b"heatmap_coordinate"])
                    number_of_spots_array[
                        heatmap_coordinate[1], heatmap_coordinate[0]
                    ] = number_of_spots
                    resolution_array[heatmap_coordinate[1], heatmap_coordinate[0]] = (
                        resolution
                    )

            logging.getLogger("HWR").debug(
                f"number_of_spots_list {number_of_spots_array}"
            )
            logging.getLogger("HWR").info(f"Creating heatmap...")

            heatmap_array = self.create_heatmap(
                num_cols=num_cols,
                num_rows=num_rows,
                number_of_spots_array=number_of_spots_array,
            )

            heatmap = {
                i: [i, list(heatmap_array[i - 1])]
                for i in range(1, num_rows * num_cols + 1)
            }

            heatmap_dict = {"heatmap": heatmap}

            self.sample_view.set_grid_data(grid_id, heatmap_dict, data_file_path=None)

        self._state.value = "ON"
        self.mxcubecore_workflow_aborted = False

    async def read_message_from_redis_streams(
        self, topic: str, id: Union[bytes, int], redis_client: redis.asyncio.StrictRedis
    ) -> tuple[dict, bytes]:
        """
        Reads pickled messages from a redis stream

        Parameters
        ----------
        topic : str
            Name of the topic of the redis stream, aka, the sample_id
        id : Union[bytes, int]
            id of the topic in bytes or int format
        redis_client : redis.asyncio.StrictRedis
            An async redis client

        Returns
        -------
        data, last_id : tuple[dict, bytes]
            A tuple containing a dictionary and the last id.
            The diction ary has the following keys:
            b'type', b'number_of_spots', b'image_id', and b'sequence_id'
        """

        response = await redis_client.xread(
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
        self, num_cols: int, num_rows: int, number_of_spots_array: npt.NDArray
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
        z = number_of_spots_array

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
        dialog = {
            "properties": {
                "md3_alignment_y_speed": {
                    "title": "Alignment Y Speed [mm/s]",
                    "type": "number",
                    "minimum": 0,
                    "maximum": 14.8,
                    "default": float(
                        self._get_dialog_box_param("md3_alignment_y_speed")
                    ),
                    "widget": "textarea",
                },
                "omega_range": {
                    "title": "Omega Range [degrees]",
                    "type": "number",
                    "minimum": 0,
                    "maximum": 360,
                    "default": float(self._get_dialog_box_param("omega_range")),
                    "widget": "textarea",
                },
                "resolution": {
                    "title": "Resolution [Å]",
                    "type": "number",
                    "minimum": 0,  # TODO: get limits from distance PV
                    "maximum": 3000,  # TODO: get limits from distance PV
                    "default": float(self._get_dialog_box_param("resolution")),
                    "widget": "textarea",
                },
                "photon_energy": {
                    "title": "Photon Energy [keV]",
                    "type": "number",
                    "minimum": 5,  # TODO: get limits from PV?
                    "maximum": 25,
                    "default": float(self._get_dialog_box_param("photon_energy")),
                    "widget": "textarea",
                },
                "transmission": {
                    "title": "Transmission [%]",
                    "type": "number",
                    "minimum": 0,  # TODO: get limits from PV?
                    "maximum": 100,
                    "default": float(self._get_dialog_box_param("transmission")),
                    "widget": "textarea",
                },
            },
            "required": [
                "md3_alignment_y_speed",
                "omega_range",
                "resolution",
                "photon_energy",
                "transmission",
            ],
            "dialogName": "Grid Scan Parameters",
        }

        return dialog
