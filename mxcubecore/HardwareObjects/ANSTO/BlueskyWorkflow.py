import asyncio
import binascii
import logging
import os
import pprint
import time
from random import random
from typing import List

import gevent
import redis
import requests
from requests.exceptions import ConnectionError

from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor
from mxcubecore.HardwareObjects.SecureXMLRpcRequestHandler import (
    SecureXMLRpcRequestHandler,
)


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
    token : str
        Random generated token
    REST : str
        URL address of the bluesky REST server
    workflow_name : str
        Name of the workflow, e.g. Screen
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
        self.bes_workflow_id = None
        self.gevent_event = None
        self.token = None
        self.REST = "http://bluesky-queueserver-rest:8080"
        self.workflow_name = None
        self.redis_port = 6379
        self.redis_host = "redis"

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

        # Open RunEngine
        try:
            requests.post(f"{self.REST}/environment/open")
        except ConnectionError:
            logging.getLogger("HWR").info(
                "Could not connect to the bluesky Run Engine,"
                " bluesky plans will not be available."
            )

        self.redis = redis.StrictRedis(self.redis_host, self.redis_port)

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

    def open_dialog(self, dict_dialog):
        # TODO: This method is currently not used by start_bluesky_workflow
        # If necessary unblock dialog
        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.params_dict = dict()
        if "reviewData" in dict_dialog and "inputMap" in dict_dialog:
            review_data = dict_dialog["reviewData"]
            for dict_entry in dict_dialog["inputMap"]:
                if "value" in dict_entry:
                    value = dict_entry["value"]
                else:
                    value = dict_entry["defaultValue"]
                self.params_dict[dict_entry["variableName"]] = str(value)
            self.emit("parametersNeeded", (review_data,))
            self.state.value = "OPEN"
            self.gevent_event.clear()
            while not self.gevent_event.is_set():
                self.gevent_event.wait()
                time.sleep(0.1)
        return self.params_dict

    def get_values_map(self):
        # TODO: this method is currently not used by start_bluesky_workflow

        return self.params_dict

    def set_values_map(self, params):
        # TODO: this method is currently not used by start_bluesky_workflow
        self.params_dict = params
        self.gevent_event.set()

    def get_available_workflows(self) -> List[dict]:
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
        self.generate_new_token()
        logging.getLogger("HWR").info("Aborting current workflow")
        # If necessary unblock dialog
        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.command_failed = False
        if self.bes_workflow_id is not None:
            abort_URL = f"{self.REST}/re/abort"
            response = requests.get(abort_URL)
            if response.status_code == 200:
                response.text
        self.state.value = "ON"

    def generate_new_token(self) -> None:
        """
        Generates a new Token.
        This method is currently not used by the BlueskyWorflow.

        Returns
        -------
        None
        """

        self.token = binascii.hexlify(os.urandom(5)).decode("utf-8")
        SecureXMLRpcRequestHandler.setReferenceToken(self.token)

    def get_token(self) -> str:
        """
        This method is currently not used by BlueskyWorflow.
        Updates the value of self.token

        Returns
        -------
        self.token : str
            The token value
        """
        return self.token

    def start(self, list_arguments: List[str]) -> None:
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

        self.generate_new_token()
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

        if self.workflow_name == "Screen":
            # Run bluesky screening plan, we set the frame_time to 4 s
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            sample_id = self.list_arguments[3].split("RAW_DATA/")[1]

            payload = {
                "item": {
                    "name": "scan_plan",
                    "args": ["dectris_detector"],
                    "kwargs": {
                        "detector_configuration": {"frame_time": 4, "nimages": 2},
                        "metadata": {"username": "Jane Doe", "sample_id": sample_id},
                    },
                    "item_type": "plan",
                }
            }
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.screen_and_collect_worklow(payload)

        elif self.workflow_name == "Collect":
            sample_id = self.list_arguments[3].split("RAW_DATA/")[1]
            payload = {
                "item": {
                    "name": "scan_plan",
                    "args": ["dectris_detector"],
                    "kwargs": {
                        "detector_configuration": {"frame_time": 8, "nimages": 2},
                        "metadata": {"username": "Jane Doe", "sample_id": sample_id},
                    },
                    "item_type": "plan",
                }
            }
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.screen_and_collect_worklow(payload)

        elif self.workflow_name == "Raster":
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.raster_workflow()

        else:
            logging.getLogger("HWR").error(
                f"Workflow {self.workflow_name} not supported"
            )
            self.state.value = "ON"

    def screen_and_collect_worklow(self, payload: dict) -> None:
        """
        Executes a screen and collect worflow by calling the bluesky queueserver

        Parameters
        ----------
        payload : dict
            A dictionary containing information about a bluesky plan

        Returns
        -------
        None
        """
        start_URL = f"{self.REST}/queue/item/execute"
        response = requests.post(start_URL, json=payload)

        logging.getLogger("HWR").info(f"server response: {response.status_code}")
        if response.status_code == 200:
            self.state.value = "RUNNING"

            # Sleep for 1 seconds until the RE state
            # changes from "idle" to "running"
            time.sleep(1)

            request_id = response.text
            logging.getLogger("HWR").info(
                f"starting Bluesky plan, request id: {request_id}"
            )

            # Update frontend values with ophyd and asyncio
            loop = asyncio.get_event_loop()
            loop.run_until_complete(
                self.asyncio_gather(
                    self.update_frontend_values(self.motor_z),
                    self.update_frontend_values(self.motor_x),
                )
            )

            logging.getLogger("HWR").info("Plan executed successfully")

            # Display score of the sample
            # score = pickle.loads(self.redis.get("sequence_id_47:score"))["score"]
            # logging.getLogger("user_level_log").warning(f"sample id score: {score}")

            self.state.value = "ON"
        else:
            logging.getLogger("HWR").error("Plan didn't start!")
            request_id = None
            self.state.value = "ON"

    def raster_workflow(self) -> None:
        """
        Generates random RBGA data and passes that data to the mxcube3 frontend

        Returns
        -------
        None
        """
        self.state.value = "RUNNING"
        grid_list = self.sample_view.get_grids()
        logging.getLogger("HWR").info(f"Number of grids: {len(grid_list)}")

        for grid in grid_list:
            sid = grid.id
            num_cols = grid.num_cols
            num_rows = grid.num_rows
            logging.getLogger("HWR").info(f"grid id: {sid}")
            logging.getLogger("HWR").info(
                f"number of columns and rows: {num_cols}, {num_rows}"
            )

            heatmap = {}
            crystalmap = {}

            if grid:
                for i in range(1, num_rows * num_cols + 1):
                    heatmap[i] = [
                        i,
                        [
                            int(random() * 255),
                            int(random() * 255),
                            int(random() * 255),
                            1,
                        ],
                    ]

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

    async def update_frontend_values(self, motor: OphydEpicsMotor) -> None:
        """
        Asynchronously updates the motor values in the Web UI

        Parameters
        ----------
        motor : OphydEpicsMotor
            An OphydEpicsMotor object

        Returns
        -------
        None
        """
        motor.update_specific_state(motor.SPECIFIC_STATES.MOVING)
        re_state = requests.get(f"{self.REST}/status").json()["re_state"]
        logging.getLogger("HWR").info(f"Run Engine state: {re_state}")

        while re_state == "running":
            re_state = requests.get(f"{self.REST}/status").json()["re_state"]
            time.sleep(0.2)
            motor.update_state(motor.STATES.BUSY)
            current_value = motor.get_value()
            motor.update_value(current_value)
            await asyncio.sleep(0.01)

        motor.update_state(motor.STATES.READY)

    async def asyncio_gather(
        self, motor_1: OphydEpicsMotor, motor_2: OphydEpicsMotor
    ) -> None:
        """
        Gathers two OphydEpicsMotors

        Parameters
        ----------
        motor_1 : OphydEpicsMotor
            An OphydEpicsMotor object
        motor_2 : OphydEpicsMotor
            An OphydEpicsMotor object

        Returns
        -------
        None
        """
        await asyncio.gather(motor_1, motor_2)
