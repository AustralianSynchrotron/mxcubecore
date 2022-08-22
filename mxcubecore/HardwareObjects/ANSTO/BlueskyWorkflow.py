import asyncio
import logging
import os
import pprint
import time

from gevent.event import Event
import redis
from bluesky_queueserver_api import BPlan


from mxcubecore import HardwareRepository as HWR
from mxcubecore.BaseHardwareObjects import HardwareObject
from .workflows.raster_worklfow import RasterWorflow
from mxcubecore.HardwareObjects.SampleView import SampleView
from mxcubecore.HardwareObjects.ANSTO.Diffractometer import Diffractometer


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
        self.REST = os.environ.get(
            "BLUESKY_QUEUESERVER_API", "http://bluesky-queueserver-rest:8080"
        )
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
        self.gevent_event = Event()
        self._state.value = "ON"
        self.count = 0

        hwr = HWR.get_hardware_repository()
        _diffractometer: Diffractometer = hwr.get_hardware_object("/diffractometer")
        self.motor_x = _diffractometer.alignment_x
        self.motor_z = _diffractometer.alignment_z

        self.sample_view: SampleView = hwr.get_hardware_object("/sample_view")

        self.beamline = HWR.beamline

        self.redis_connection = redis.StrictRedis(self.redis_host, self.redis_port)

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

        self.raster_workflow.bluesky_plan_aborted = True
        self.raster_workflow.mxcubecore_workflow_aborted = True

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
        # self.list_arguments[3].split("RAW_DATA/")[1]

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

            self.raster_workflow = RasterWorflow(
                motor_x=self.motor_x, motor_z=self.motor_z,
                sample_view=self.sample_view,
                state=self._state, redis_connection=self.redis_connection,
                gevent_event=self.gevent_event)

            self.raster_workflow.run(metadata=acquisition_parameters)

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
