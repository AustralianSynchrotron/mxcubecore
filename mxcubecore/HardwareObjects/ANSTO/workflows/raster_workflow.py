import asyncio
import logging
import time
from typing import Union

import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import redis
from bluesky_queueserver_api import BPlan

from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor
from mxcubecore.HardwareObjects.SampleView import Grid, SampleView

from .base_workflow import AbstractBlueskyWorflow


class RasterWorflow(AbstractBlueskyWorflow):
    def __init__(
        self,
        motor_dict: dict[str, OphydEpicsMotor],
        state,
        REST: str,
        redis_connection: redis.StrictRedis,
        sample_view: SampleView,
    ) -> None:
        """
        Parameters
        ----------
        motor_dict : dict[str, OphydEpicsMotor]
            A dictionary containing OphydEpicsMotors
        state : State
            The state of the BlueskyWorkflow class. See the State class in
            BlueskyWorflow for details
        REST : str
            The URL of the bluesky-queueserver-api
        redis_connection : redis.StrictRedis
            The redis connection
        sample_view : SampleView
            The SampleView hardware object
        """
        super().__init__(motor_dict, state, REST)

        self.motor_dict = motor_dict
        self.sample_view = sample_view
        self._state = state
        self.redis_connection = redis_connection
        self.REST = REST

    def run(self, metadata: dict) -> None:
        """
        Executes a raster workflow. First a dialog box is opened, then a
        bluesky plan is executed and finally the data produced by the
        Sim-plon API is analysed and converted to a heatmap containing RGBA values.
        The heatmap is displayed in MXCuBE.

        Parameteres
        -----------
        metadata : dict
            A metadata dictionary sent from mxcube to the bluesky queueserver

        Returns
        -------
        None
        """

        self._state.value = "RUNNING"

        grid_list: list[Grid] = self.sample_view.get_grids()
        logging.getLogger("HWR").info(f"Number of grids: {len(grid_list)}")

        for grid in grid_list:
            sid = grid.id
            num_cols = grid.num_cols
            num_rows = grid.num_rows
            beam_position = grid.beam_pos
            # pixels_per_mm = grid.pixels_per_mm
            pixels_per_mm = [292.87, 292.87]
            screen_coordinate = grid.screen_coord
            width = grid.width
            height = grid.height

            current_motor_x_value = self.motor_dict["motor_x"].get_value()
            current_motor_z_value = self.motor_dict["motor_z"].get_value()

            initial_motor_x_grid_value = (
                current_motor_x_value
                + (screen_coordinate[0] - beam_position[0]) / pixels_per_mm[0]
            )
            final_motor_x_grid_value = (
                initial_motor_x_grid_value + width / pixels_per_mm[0]
            )

            initial_motor_z_grid_value = (
                current_motor_z_value
                + (screen_coordinate[1] - beam_position[1]) / pixels_per_mm[1]
            )
            final_motor_z_grid_value = (
                initial_motor_z_grid_value + height / pixels_per_mm[1]
            )

            item = BPlan(
                "grid_scan",
                ["dectris_detector"],
                "mxcube_motor_z",
                initial_motor_z_grid_value,
                final_motor_z_grid_value,
                num_rows,
                "mxcube_motor_x",
                initial_motor_x_grid_value,
                final_motor_x_grid_value,
                num_cols,
                md=metadata,
            )

            # Run bluesky plan
            asyncio.run(self.run_bluesky_plan(item))

            logging.getLogger("HWR").info(f"grid id: {sid}")
            logging.getLogger("HWR").info(
                f"number of columns and rows: {num_cols}, {num_rows}"
            )

            # Move back the motors to inital position.
            # This step can be added as as part of the grid_scan plan, which will make
            # the execution of the raster worflow faster
            item = BPlan(
                "mv",
                "mxcube_motor_z",
                current_motor_z_value,
                "mxcube_motor_x",
                current_motor_x_value,
            )
            asyncio.run(self.run_bluesky_plan(item))

            if not self.mxcubecore_workflow_aborted:
                number_of_spots_list = []
                count = 0
                last_id = 0
                grid_size = num_cols * num_rows
                logging.getLogger("user_level_log").warning("Processing data...")
                while count < grid_size:
                    try:
                        data, last_id = self.read_and_delete_message_from_redis_streams(
                            topic=metadata["sample_id"], id=last_id
                        )
                        count += 1
                        logging.getLogger("HWR").info(data)
                        number_of_spots_list.append(int(data[b"number_of_spots"]))
                    except IndexError:
                        pass
                    time.sleep(0.05)

                logging.getLogger("user_level_log").warning("Data processing finished")

                logging.getLogger("HWR").debug(
                    f"number_of_spots_list {number_of_spots_list}"
                )

                heatmap_array = self.create_heatmap(
                    num_cols, num_rows, number_of_spots_list
                )

                heatmap = {}
                crystalmap = {}

                if grid:
                    for i in range(1, num_rows * num_cols + 1):
                        heatmap[i] = [i, list(heatmap_array[i - 1])]

                        crystalmap[i] = [
                            i,
                            [
                                int(np.random.random() * 255),
                                int(np.random.random() * 255),
                                int(np.random.random() * 255),
                                1,
                            ],
                        ]

                heat_and_crystal_map = {"heatmap": heatmap, "crystalmap": crystalmap}
                self.sample_view.set_grid_data(sid, heat_and_crystal_map)

        self._state.value = "ON"
        self.mxcubecore_workflow_aborted = False

    def read_and_delete_message_from_redis_streams(
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
        response = self.redis_connection.xread({topic: id}, count=1)

        # Extract key and messages from the response
        _, messages = response[0]

        # Update last_id and store messages data
        last_id, data = messages[0]

        # Remove dataset from redis
        self.redis_connection.xdel(topic, last_id)
        return data, last_id

    def create_heatmap(
        self, num_cols: int, num_rows: int, number_of_spots_list: list[int]
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
        number_of_spots_list : list[int]
            List containing number of spots

        Returns
        -------
        result : npt.NDArray
            An array containing a heatmap with rbga values
        """

        x = np.arange(num_cols)
        y = np.arange(num_rows)

        y, x = np.meshgrid(x, y)
        z = np.array([number_of_spots_list]).reshape(num_rows, num_cols)

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
                "name": {
                    "title": "Task name",
                    "type": "string",
                    "minLength": 2,
                    "default": "Test",
                },
                "description": {
                    "title": "Description",
                    "type": "string",
                    "widget": "textarea",
                },
                "parameterA": {
                    "title": "parameterA",
                    "type": "number",
                    "minimum": 0,
                    "exclusiveMaximum": 100,
                    "default": 20,
                    "widget": "textarea",
                },
            },
            "required": ["name", "parameterA"],
            "dialogName": "Raster parameters",
        }

        return dialog
