import asyncio
import logging
import pickle
import time
from os import environ
from typing import Union

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import redis
from mx3_beamline_library.devices.beam import energy_master
from mx3_beamline_library.devices.motors import actual_sample_detector_distance

from mxcubecore.HardwareObjects.SampleView import (
    Grid,
    SampleView,
)
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

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
        redis_connection: redis.StrictRedis,
        sample_view: SampleView,
    ) -> None:
        super().__init__(state)

        self.redis_connection = redis_connection
        self.sample_view = sample_view

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
            sample_id = "test_sample"

        # TODO: sample_id should be obtained from the database!
        redis_grid_scan_id = self.redis_connection.get(
            f"mxcube_grid_scan_id:{sample_id}"
        )
        if redis_grid_scan_id is None:
            grid_scan_id = 0
        else:
            grid_scan_id = int(redis_grid_scan_id) + 1

        prefect_parameters = GridScanParams(
            sample_id=sample_id,
            grid_scan_id=grid_scan_id,
            grid_top_left_coordinate=screen_coordinate,
            grid_height=height,
            grid_width=width,
            beam_position=beam_position,
            number_of_columns=num_cols,
            number_of_rows=num_rows,
            detector_distance=dialog_box_model.detector_distance / 1000,
            photon_energy=dialog_box_model.photon_energy,
            omega_range=dialog_box_model.omega_range,
            md3_alignment_y_speed=dialog_box_model.md3_alignment_y_speed,
            hardware_trigger=dialog_box_model.hardware_trigger,
            number_of_processes=GRID_SCAN_NUMBER_OF_PROCESSES,
        )

        self.redis_connection.set(
            f"mxcube_grid_scan_id:{sample_id}", grid_scan_id, ex=86400
        )
        logging.getLogger("HWR").info(
            f"Parameters sent to prefect flow: {prefect_parameters}"
        )
        grid_scan_flow = MX3PrefectClient(
            name=GRID_SCAN_DEPLOYMENT_NAME,
            parameters=prefect_parameters.model_dump(exclude_none=True),
        )

        try:
            loop = asyncio.get_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(grid_scan_flow.trigger_flow(wait=True))
            success = True
        except Exception as ex:
            logging.getLogger("HWR").info(f"Failed to execute raster flow: {ex}")
            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False
            success = False
            logging.getLogger("user_level_log").warning(
                "Grid scan flow was not successful"
            )
            raise QueueExecutionException(str(ex), self) from ex

        if success:
            logging.getLogger("HWR").info(f"grid id: {sid}")
            logging.getLogger("HWR").info(
                f"number of columns and rows: {num_cols}, {num_rows}"
            )

            if not self.mxcubecore_workflow_aborted:
                number_of_spots_list = []
                last_id = 0
                grid_size = num_cols * num_rows
                logging.getLogger("user_level_log").warning("Processing data...")
                number_of_spots_array = np.zeros((num_rows, num_cols))
                resolution_array = np.zeros((num_rows, num_cols))
                for _ in range(grid_size):
                    data, last_id = self.read_message_from_redis_streams(
                        topic=f"number_of_spots_{prefect_parameters.grid_scan_id}:{prefect_parameters.sample_id}",
                        id=last_id,
                    )
                    number_of_spots = float(data[b"number_of_spots"])
                    resolution = float(data[b"resolution"])
                    heatmap_coordinate = pickle.loads(data[b"heatmap_coordinate"])
                    logging.getLogger("HWR").info(
                        f"heatmap coordinate: {heatmap_coordinate}, "
                        f"resolution: {resolution}, "
                        f"number of spots {number_of_spots}"
                    )
                    number_of_spots_array[
                        heatmap_coordinate[1], heatmap_coordinate[0]
                    ] = number_of_spots
                    resolution_array[heatmap_coordinate[1], heatmap_coordinate[0]] = (
                        resolution
                    )

                logging.getLogger("user_level_log").warning("Data processing finished")

                logging.getLogger("HWR").debug(
                    f"number_of_spots_list {number_of_spots_list}"
                )

                heatmap_array = self.create_heatmap(
                    num_cols=num_cols,
                    num_rows=num_rows,
                    number_of_spots_array=number_of_spots_array,
                )
                crystalmap_array = self.create_heatmap(
                    num_cols=num_cols,
                    num_rows=num_rows,
                    number_of_spots_array=resolution_array,
                )

                heatmap = {}
                crystalmap = {}

                if grid:
                    for i in range(1, num_rows * num_cols + 1):
                        heatmap[i] = [i, list(heatmap_array[i - 1])]
                        crystalmap[i] = [i, list(crystalmap_array[i - 1])]

                heat_and_crystal_map = {"heatmap": heatmap, "crystalmap": crystalmap}
                self.sample_view.set_grid_data(
                    sid, heat_and_crystal_map, data_file_path="this_is_not_used"
                )

            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False

    def read_message_from_redis_streams(
        self, topic: str, id: Union[bytes, int]
    ) -> tuple[dict, bytes]:
        """
        Reads pickled messages from a redis stream

        Parameters
        ----------
        topic : str
            Name of the topic of the redis stream, aka, the sample_id
        id : Union[bytes, int]
            id of the topic in bytes or int format

        Returns
        -------
        data, last_id : tuple[dict, bytes]
            A tuple containing a dictionary and the last id.
            The diction ary has the following keys:
            b'type', b'number_of_spots', b'image_id', and b'sequence_id'
        """
        response_length = 0
        timeout = time.perf_counter() + 30  # wait for 30 seconds
        while response_length == 0:
            response = self.redis_connection.xread({topic: id}, count=1)
            response_length = len(response)
            if time.perf_counter() > timeout:
                raise ValueError(
                    f"Frames not found for id: {topic}. "
                    "Check that frames are being buffered by the ZMQ stream consumer"
                )
            time.sleep(0.01)

        # Extract key and messages from the response
        _, messages = response[0]

        # Update last_id and store messages data
        last_id, data = messages[0]

        # Remove dataset from redis
        # self.redis_connection.xdel(topic, last_id)
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

        x = np.arange(num_cols)
        y = np.arange(num_rows)

        y, x = np.meshgrid(x, y)
        z = number_of_spots_array

        z_min = np.min(z)
        z_max = np.max(z)

        _, ax = plt.subplots()

        heatmap = ax.pcolormesh(x, y, z, cmap="seismic", vmin=z_min, vmax=z_max)
        heatmap = heatmap.to_rgba(z, norm=True).reshape(num_cols * num_rows, 4)

        # The following could probably be done more efficiently without using for loops
        result = np.ones(heatmap.shape)
        for i in range(num_rows * num_cols):
            for j in range(4):
                if heatmap[i][j] != 1.0:
                    result[i][j] = int(heatmap[i][j] * 255)

        return result

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
                    "default": 1,
                    "widget": "textarea",
                },
                "omega_range": {
                    "title": "Omega Range [degrees]",
                    "type": "number",
                    "minimum": 0,
                    "maximum": 360,
                    "default": 0,
                    "widget": "textarea",
                },
                "detector_distance": {
                    "title": "Detector Distance [mm]",
                    "type": "number",
                    "minimum": 0,  # TODO: get limits from distance PV
                    "maximum": 3000,  # TODO: get limits from distance PV
                    "default": round(actual_sample_detector_distance.get(), 2),
                    "widget": "textarea",
                },
                "photon_energy": {
                    "title": "Photon Energy [keV]",
                    "type": "number",
                    "minimum": 5,  # TODO: get limits from PV?
                    "maximum": 25,
                    "default": round(energy_master.get(), 2),
                    "widget": "textarea",
                },
            },
            "required": [
                "md3_alignment_y_speed",
                "omega_range",
                "detector_distance",
                "photon_energy",
            ],
            "dialogName": "Grid Scan Parameters",
        }

        return dialog
