import asyncio
import logging
import os
import pickle
import pprint
import time
from random import random

import gevent
import matplotlib.pyplot as plt
import numpy as np
import numpy.typing as npt
import redis
from bluesky_queueserver_api import BPlan
from bluesky_queueserver_api.comm_base import RequestError, RequestFailedError
from bluesky_queueserver_api.http.aio import REManagerAPI

from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor


class State(object):
    """
    Class used to mimic the PyTango state object referenced in the
    GenericWorkflowQueueEntry class located in the queue_entry.py file.

    Attributes
    ----------
    _value : str
        State of the hardware object, e.g. ON, RUNNING or OPEN
    parent : HardwareObject
        Parent class, e.g. BlueskyWorkflow
    """

    def __init__(self, parent: HardwareObject) -> None:
        """
        Parameters
        ----------
        parent : HardwareObject
            Parent class, e.g. BlueskyWorkflow

        Returns
        -------
        None
        """
        self._value = "ON"
        self._parent = parent

    @property
    def value(self) -> str:
        """
        Gets the state of the hardware object.

        Returns
        -------
        self._value: str
            The state of the HO
        """
        return self._value

    @value.setter
    def value(self, value: str) -> None:
        """
        Sets the state of the hardware object. Three states are accepted:
        ON, RUNNING and OPEN

        Returns
        -------
        None
        """
        self._value = value
        self._parent.state_changed(value)


class BlueskyWorkflow(HardwareObject):
    """
    This hardware object executes a bluesky plan using
    the bluesky queueserver

    Attributes
    ----------
    _state : State
        State of a Hardware Object
    command_failed : bool
        The command_failed state
    REST : str
        URL address of the bluesky REST server
    workflow_name : str
        Name of the workflow, e.g. Screen
    redis_port : int
        Redis port
    redis_host : str
        Redis host
    bluesky_plan_aborted : bool
        True if a bluesky plan has been aborted, False otherwise
    mxcubecore_workflow_aborted : bool
        True if a mxcubecore workflow has been aborted, False otherwise
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name: str
            Name of the Hardware object, e.g. '/edna_params'

        Returns
        -------
        None
        """
        HardwareObject.__init__(self, name)
        self._state = State(self)
        self.command_failed = False
        self.gevent_event = None
        self.REST = "http://bluesky-queueserver-rest:8080"
        self.workflow_name = None
        self.redis_port = int(os.environ.get("DATA_PROCESSING_REDIS_PORT", "6379"))
        self.redis_host = os.environ.get("DATA_PROCESSING_REDIS_HOST", "redis")
        self.bluesky_plan_aborted = False
        self.mxcubecore_workflow_aborted = False

    def _init(self) -> None:
        """
        Object initialisation - executed *before* loading contents

        Returns
        -------
        None
        """

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents

        Returns
        -------
        None
        """
        self.gevent_event = gevent.event.Event()
        self._state.value = "ON"
        self.count = 0

        hwr = HWR.get_hardware_repository()
        _diffractometer = hwr.get_hardware_object("/diffractometer")
        self.motor_x = _diffractometer.alignment_x
        self.motor_z = _diffractometer.alignment_z

        self.sample_view = hwr.get_hardware_object("/sample_view")

        self.beamline = HWR.beamline

        self.redis_con = redis.StrictRedis(self.redis_host, self.redis_port)

    @property
    def state(self) -> State:
        """
        Gets the state of the workflow

        Returns
        -------
        _state : State
            The state of the workflow
        """
        return self._state

    @state.setter
    def state(self, new_state: State) -> None:
        """
        Sets the state of the workflow

        Parameters
        ----------
        new_state : State
            The state of the workflow

        Returns
        -------
        None
        """
        self._state = new_state

    def command_failure(self) -> bool:
        """
        Returns the state of self.command_failed

        Returns
        -------
        command_failed : bool
            The command_failed state
        """

        return self.command_failed

    def set_command_failed(self, *args) -> None:
        """
        Sets command_failed to True

        Returns
        -------
        None
        """

        logging.getLogger("HWR").error("Workflow '%s' Tango command failed!" % args[1])
        self.command_failed = True

    def state_changed(self, new_value: str) -> None:
        """
        Emits a stateChanged message

        Parameters
        ----------
        new_value : str
            A new_value to emit

        Returns
        -------
        None
        """
        new_value = str(new_value)
        logging.getLogger("HWR").debug(f"{self.name()}: state changed to {new_value}")
        self.emit("stateChanged", (new_value,))

    def workflow_end(self) -> None:
        """
        The workflow has finished, sets the state to 'ON'

        Returns
        -------
        None
        """
        # If necessary unblock dialog
        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.state.value = "ON"

    def open_dialog(self, dict_dialog: dict):
        """Opens a dialog in the mxcube3 front end.

        A dict_dialog example is defined in the test_workflow_dialog
        method.

        Parameters
        ----------
        dict_dialog : dict
            A dictionary following the JSON schems

        Returns
        -------
        dict
            An updated dictionaty containing parameters passed by the user from
            the mxcube3 frontend
        """
        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.emit("parametersNeeded", (dict_dialog,))
        self.params_dict = dict_dialog

        self.state.value = "OPEN"
        self.gevent_event.clear()

        while not self.gevent_event.is_set():
            self.gevent_event.wait()
            time.sleep(0.1)
        return self.params_dict

    def test_workflow_dialog(self):
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

    def get_values_map(self):
        # TODO: this method is currently not used by start_bluesky_workflow

        return self.params_dict

    def set_values_map(self, params):
        # TODO: this method is currently not used by start_bluesky_workflow
        self.params_dict = params
        self.gevent_event.set()

    def get_available_workflows(self) -> list[dict]:
        """
        Gets the available workflows specified in the edna_params.xml file

        Returns
        -------
        workflow_list : str
            A list containing all available workflows
        """
        workflow_list = list()
        no_wf = len(self["workflow"])
        for wf_i in range(no_wf):
            wf = self["workflow"][wf_i]
            dict_workflow = dict()
            dict_workflow["name"] = str(wf.title)
            dict_workflow["path"] = str(wf.path)
            try:
                req = [r.strip() for r in wf.get_property("requires").split(",")]
                dict_workflow["requires"] = req
            except (AttributeError, TypeError):
                dict_workflow["requires"] = []
            dict_workflow["doc"] = ""
            workflow_list.append(dict_workflow)
        return workflow_list

    def abort(self) -> None:
        """
        Aborts a bluesky plan

        Returns
        -------
        None
        """
        logging.getLogger("HWR").info("Aborting current workflow")
        # If necessary unblock dialog
        if not self.gevent_event.is_set():
            self.gevent_event.set()

        self.bluesky_plan_aborted = True
        self.mxcubecore_workflow_aborted = True

    def start(self, list_arguments: list[str]) -> None:
        """
        Starts a workflow in mxcube

        Parameters
        ----------
        list_arguments: list
            A list of arguments containing information about the current
            mounted sample. It includes the model path, the workflow name,
            id of the sample, sample prefix,
            run number, collection software, sample_node_id, sample_lims_id,
            beamline, shape and directory.

        Returns
        -------
        None
        """
        self.list_arguments = list_arguments
        logging.getLogger("HWR").debug(f"LIST ARGUMETS: {self.list_arguments}")

        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.state.value = "ON"

        self.dict_parameters = {}
        index = 0
        if len(list_arguments) == 0:
            self.error_stream("ERROR! No input arguments!")
            return
        elif len(list_arguments) % 2 != 0:
            self.error_stream("ERROR! Odd number of input arguments!")
            return
        while index < len(list_arguments):
            self.dict_parameters[list_arguments[index]] = list_arguments[index + 1]
            index += 2
        logging.info("Input arguments:")
        logging.info(pprint.pformat(self.dict_parameters))

        if "modelpath" in self.dict_parameters:
            modelpath = self.dict_parameters["modelpath"]
            if "." in modelpath:
                modelpath = modelpath.split(".")[0]
            self.workflow_name = os.path.basename(modelpath)
        else:
            self.error_stream("ERROR! No modelpath in input arguments!")
            return

        if self.workflow_name is not None:
            self.state.value = "RUNNING"
            time0 = time.time()
            self.start_bluesky_workflow()
            time1 = time.time()
            logging.getLogger("HWR").info(
                f"Time to execute workflow (s): {time1 - time0}"
            )

    def start_bluesky_workflow(self) -> None:
        """
        Executes a bluesky plan using the bluesky queueserver

        Returns
        -------
        None
        """
        # NOTE: we are not using self.dict_parameters because
        # we do not need it (see the original implementation
        # of the BES workflow for more details)
        self.list_arguments[3].split("RAW_DATA/")[1]

        if self.workflow_name == "Screen":
            # Run bluesky screening plan, we set the frame_time to 4 s
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")

            item = BPlan(
                "scan_plan",
                detector="dectris_detector",
                detector_configuration={"frame_time": 4, "nimages": 2},
                metadata={"username": "Jane Doe", "sample_id": "test"},
            )

            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")

            self.screen_and_collect_worklow(item)

        elif self.workflow_name == "Collect":
            item = BPlan(
                "scan_plan",
                detector="dectris_detector",
                detector_configuration={"frame_time": 8, "nimages": 2},
                metadata={"username": "Jane Doe", "sample_id": "test"},
            )

            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")

            self.screen_and_collect_worklow(item)

        elif self.workflow_name == "Raster":
            acquisition_parameters = self.beamline.get_default_acquisition_parameters(
                acquisition_type="default_ansto"
            ).as_dict()
            acquisition_parameters["wavelenght"] = self.beamline.energy.get_wavelength()

            acquisition_parameters["sample_id"] = "test"

            # Bluesky does not like empty strigs
            if not acquisition_parameters["comments"]:
                acquisition_parameters["comments"] = None

            logging.getLogger("HWR").debug(f"ACQ params: {acquisition_parameters}")

            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.raster_workflow(metadata=acquisition_parameters)

        else:
            logging.getLogger("HWR").error(
                f"Workflow {self.workflow_name} not supported"
            )
            self.state.value = "ON"

    def screen_and_collect_worklow(self, item: BPlan) -> None:
        """
        Executes a screen and collect worflow by calling the bluesky queueserver

        Parameters
        ----------
        item : Bplan
            A Bplan object containing information about a bluesky plan

        Returns
        -------
        None
        """
        self.state.value = "RUNNING"

        # Run bluesky plan
        asyncio.run(self.run_bluesky_plan(item))

        self.state.value = "ON"
        self.mxcubecore_workflow_aborted = False

    def raster_workflow(self, metadata: dict) -> None:
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

        # Open a workflow dialog box
        test_dialog = self.test_workflow_dialog()
        result = self.open_dialog(test_dialog)
        logging.getLogger("HWR").debug(f"new parameters: {result}")

        self.state.value = "RUNNING"

        grid_list = self.sample_view.get_grids()
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

            current_motor_x_value = self.motor_x.get_value()
            current_motor_z_value = self.motor_z.get_value()

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
                "motor_z",
                initial_motor_z_grid_value,
                final_motor_z_grid_value,
                num_rows,
                "motor_x",
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
                "mv", "motor_z", current_motor_z_value, "motor_x", current_motor_x_value
            )
            asyncio.run(self.run_bluesky_plan(item))

            if not self.mxcubecore_workflow_aborted:
                sequence_id = pickle.loads(
                    self.redis_con.get(
                        f"sample_id_{metadata['sample_id']}_bluesky_doc:start"
                    )
                )["sequence_id"]

                number_of_spots_list = []

                logging.getLogger("user_level_log").warning("Processing data...")
                for i in range(1, num_rows * num_cols + 1):
                    while True:
                        time.sleep(0.01)
                        try:
                            number_of_spots = pickle.loads(
                                self.redis_con.get(
                                    f"sequence_id_{sequence_id}"
                                    f"_sequence_number_{i}_zmq_stream"
                                    ":number_of_spots"
                                )
                            )["number_of_spots"]
                            number_of_spots_list.append(number_of_spots)
                        except TypeError:
                            continue
                        break

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
                                int(random() * 255),
                                int(random() * 255),
                                int(random() * 255),
                                1,
                            ],
                        ]

                heat_and_crystal_map = {"heatmap": heatmap, "crystalmap": crystalmap}
                self.sample_view.set_grid_data(sid, heat_and_crystal_map)
                logging.getLogger("HWR").info("grid set successfully")

        self.state.value = "ON"
        self.mxcubecore_workflow_aborted = False

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

    async def run_bluesky_plan(self, item: BPlan) -> None:
        """Asynchronously run a bluesky plan

        Parameters
        ----------
        item : BPlan
            A Bplan object containing information about a bluesky plan

        Returns
        -------
        None
        """
        self.RM = REManagerAPI(http_server_uri=self.REST)

        await self.RM.item_add(item)

        await self.RM.environment_open()
        await self.RM.wait_for_idle()

        await self.RM.queue_start()

        # Sleep for 1 second until the RM changes the status to executing_plan
        time.sleep(1)
        RM_status = await self.RM.status()
        while RM_status["worker_environment_state"] == "executing_plan":
            if not self.bluesky_plan_aborted:
                time.sleep(0.2)
                await asyncio.gather(
                    self.update_frontend_values(self.motor_z),
                    self.update_frontend_values(self.motor_x),
                )

                RM_status = await self.RM.status()
            else:
                # Abort bluesky plan
                self.bluesky_plan_aborted = False

                try:
                    await self.RM.re_pause()
                    await self.RM.wait_for_idle_or_paused()

                    await self.RM.re_abort()
                    await self.RM.wait_for_idle()
                except (RequestFailedError, RequestError) as e:
                    logging.getLogger("HWR").info(f"Abort error: {e}")

                await self.RM.queue_clear()
                await self.RM.wait_for_idle()

                await asyncio.gather(
                    self.update_frontend_values(self.motor_z),
                    self.update_frontend_values(self.motor_x),
                )

                self.motor_x.update_state(self.motor_x.STATES.READY)
                self.motor_z.update_state(self.motor_z.STATES.READY)
                break
        else:
            self.motor_x.update_state(self.motor_x.STATES.READY)
            self.motor_z.update_state(self.motor_z.STATES.READY)

        await self.RM.wait_for_idle()

        await self.RM.environment_close()
        await self.RM.wait_for_idle()

    async def update_frontend_values(self, motor: OphydEpicsMotor) -> None:
        """
        Update the motor values in the Web UI

        Parameters
        ----------
        motor : OphydEpicsMotor
            An OphydEpicsMotor object

        Returns
        -------
        None
        """
        motor.update_specific_state(motor.SPECIFIC_STATES.MOVING)

        motor.update_state(motor.STATES.BUSY)
        current_value = motor.get_value()
        motor.update_value(current_value)
        await asyncio.sleep(0.01)
