import asyncio
import logging
import os
import pprint
import time
from time import perf_counter

import gevent
import redis
from gevent.event import Event
import yaml
from os import path


from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.SampleView import SampleView
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from .prefect_flows.full_dataset_collection_flow import FullDatasetFlow
from .prefect_flows.grid_scan_flow import GridScanFlow
from .prefect_flows.schemas.prefect_workflow import PrefectFlows
from .prefect_flows.screening_flow import ScreeningFlow


class State(object):
    """
    Class used to mimic the PyTango state object referenced in the
    GenericWorkflowQueueEntry class located in the queue_entry.py file.

    Attributes
    ----------
    _value : str
        State of the hardware object, e.g. ON, RUNNING or OPEN
    parent : HardwareObject
        Parent class, e.g. PrefectWorkflow
    """

    def __init__(self, parent: HardwareObject) -> None:
        """
        Parameters
        ----------
        parent : HardwareObject
            Parent class, e.g. PrefectWorkflow

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


class PrefectWorkflow(HardwareObject):
    """
    This hardware object executes a prefect flow

    Attributes
    ----------
    _state : State
        State of a Hardware Object
    command_failed : bool
        The command_failed state
    workflow_name : str
        Name of the workflow, e.g. Screen
    redis_port : int
        Redis port
    redis_host : str
        Redis host
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
        self.workflow_name = None

        self.REDIS_HOST = os.environ.get("MXCUBE_REDIS_HOST", "localhost")
        self.REDIS_PORT = int(os.environ.get("MXCUBE_REDIS_PORT", "6379"))
        self.REDIS_USERNAME = os.environ.get("MXCUBE_REDIS_USERNAME", None)
        self.REDIS_PASSWORD = os.environ.get("MXCUBE_REDIS_PASSWORD", None)
        self.REDIS_DB = int(os.environ.get("MXCUBE_REDIS_DB", "0"))

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
        self.gevent_event = Event()
        self._state.value = "ON"

        hwr = HWR.get_hardware_repository()
        self.sample_view: SampleView = hwr.get_hardware_object("/sample_view")

        self.redis_connection = redis.StrictRedis(
            host=self.REDIS_HOST,
            port=self.REDIS_PORT,
            username=self.REDIS_USERNAME,
            password=self.REDIS_PASSWORD,
            db=self.REDIS_DB,
        )

        self._save_default_collection_params_to_redis()


        self.raster_flow = None

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
        logging.getLogger("HWR").info(f"{self.name()}: state changed to {new_value}")
        self.emit("stateChanged", (new_value,))

    def open_dialog(self, dict_dialog: dict) -> dict:
        """Opens a dialog in the mxcube3 front end.

        A dict_dialog example is defined in the workflow_dialog
        method.

        Parameters
        ----------
        dict_dialog : dict
            A dictionary following the JSON schema

        Returns
        -------
        dict
            An updated dictionary containing parameters passed by the user from
            the mxcube3 frontend
        """
        logging.getLogger("HWR").info("Dialog box opened")
        if not self.gevent_event.is_set():
            self.gevent_event.set()
        self.emit("parametersNeeded", (dict_dialog,))
        self.params_dict = dict_dialog

        self.state.value = "OPEN"
        self.gevent_event.clear()
        logging.getLogger("HWR").debug(f"Opening {self._state.value}")
        while not self.gevent_event.is_set():
            self.gevent_event.wait()
            time.sleep(0.1)

        self.state.value = "ON"
        return self.params_dict

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

    def get_values_map(self):
        # TODO: this method is currently not used

        return self.params_dict

    def set_values_map(self, params):
        # TODO: this method is currently not used
        self.params_dict = params
        self.gevent_event.set()

    def get_available_workflows(self) -> list[dict]:
        """
        Gets the available workflows specified in the prefect_flow.xml file

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
        logging.getLogger("HWR").info(f"Available workflows: {workflow_list}")
        return workflow_list

    def abort(self) -> None:
        """
        Aborts a prefect flow plan

        Returns
        -------
        None
        """
        logging.getLogger("HWR").info("Aborting current workflow")
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # TODO: MXcube takes some significant time to cancel workflows (investigate why)
            timeout = 30
            logging.getLogger("HWR").warning(
                f"Loop is still running, waiting for {timeout} s to complete"
            )
            t = perf_counter()
            while loop.is_running():
                gevent.sleep(1)
                logging.getLogger("HWR").warning(f"Loop is still running")
                if perf_counter() > t + timeout:
                    raise QueueExecutionException("Asyncio Loop is still running", self)

        # If necessary unblock dialog
        if not self.gevent_event.is_set():
            self.gevent_event.set()

        if self.workflow_name == PrefectFlows.grid_scan:
            self.raster_flow.prefect_flow_aborted = True
            self.raster_flow.mxcubecore_workflow_aborted = True

        self.state.value = "ON"

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
        logging.getLogger("HWR").info("Start workflow......")
        logging.getLogger("HWR").info(f"workflow name: {self.workflow_name}")
        logging.getLogger("HWR").info(f"list_arguments: {list_arguments}")
        self.list_arguments = list_arguments

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
            logging.getLogger("HWR").info("Starting prefect flow")
            self.start_prefect_workflow()
            time1 = time.time()
            logging.getLogger("HWR").info(
                f"Time to execute workflow (s): {time1 - time0}"
            )
        self.state.value = "ON"

    def start_prefect_workflow(self) -> None:
        """
        Executes a prefect flow

        Returns
        -------
        None
        """
        # NOTE: we are not using self.dict_parameters because
        # we do not need it (see the original implementation
        # of the BES workflow for more details)
        # self.list_arguments[3].split("RAW_DATA/")[1]

        if self.workflow_name == PrefectFlows.screen_sample:
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.screening_flow = ScreeningFlow(state=self._state)
            dialog_box_parameters = self.open_dialog(self.screening_flow.dialog_box())
            if dialog_box_parameters:
                logging.getLogger("HWR").info(
                    f"Dialog box parameters: {dialog_box_parameters}"
                )
                self.state.value = "ON"
                self.screening_flow.run(dialog_box_parameters=dialog_box_parameters)
            else:
                self.state.value = "ON"
                raise QueueExecutionException("dialog_box_parameters is empty", self)

        elif self.workflow_name == PrefectFlows.collect_dataset:
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.full_dataset_flow = FullDatasetFlow(state=self._state)
            dialog_box_parameters = self.open_dialog(
                self.full_dataset_flow.dialog_box()
            )
            if dialog_box_parameters:
                logging.getLogger("HWR").info(
                    f"Dialog box parameters: {dialog_box_parameters}"
                )
                self.full_dataset_flow.run(dialog_box_parameters=dialog_box_parameters)
            else:
                self.state.value = "ON"
                raise QueueExecutionException("dialog_box_parameters is empty", self)

        elif self.workflow_name == PrefectFlows.grid_scan:
            logging.getLogger("HWR").info(f"Starting workflow: {self.workflow_name}")
            self.raster_flow = GridScanFlow(
                sample_view=self.sample_view,
                state=self._state,
                redis_connection=self.redis_connection,
            )
            dialog_box_parameters = self.open_dialog(self.raster_flow.dialog_box())
            if dialog_box_parameters:
                logging.getLogger("HWR").info(
                    f"Dialog box parameters: {dialog_box_parameters}"
                )

                self.raster_flow.run(dialog_box_parameters=dialog_box_parameters)
            else:
                self.state.value = "ON"
                raise QueueExecutionException("dialog_box_parameters is empty", self)

        else:
            logging.getLogger("HWR").error(
                f"Workflow {self.workflow_name} not supported"
            )
            self.state.value = "ON"

    def _save_default_collection_params_to_redis(self) -> None:
        """
        Save default full_dataset, screening, and grid_scan parameters to Redis.
        The default values are read from the default_params.yml config file
        
        Returns
        -------
        None
        """
        default_params_path =  path.join(path.dirname(__file__), "prefect_flows", "default_params.yml")
        with open(default_params_path) as config:
            default_params = yaml.safe_load(config)

        collection_type = "full_dataset"
        for key, value in default_params[collection_type].items():
            self.redis_connection.set(f"{collection_type}:{key}", value)


        collection_type = "screening"
        for key, value in default_params[collection_type].items():
            self.redis_connection.set(f"{collection_type}:{key}", value)


        collection_type = "grid_scan"
        for key, value in default_params[collection_type].items():
            self.redis_connection.set(f"{collection_type}:{key}", value)
