from __future__ import annotations

import logging
from functools import lru_cache
from http import HTTPStatus
from time import time
from typing import (
    Any,
    Optional,
)
from urllib.parse import urljoin

import httpx
import redis
from gevent import sleep
from mx_robot_library.client.client import Client
from mx_robot_library.config import get_settings as get_robot_settings
from mx_robot_library.schemas.common.path import RobotPaths
from mx_robot_library.schemas.common.position import RobotPositions
from mx_robot_library.schemas.common.sample import Pin as RobotPin
from mx_robot_library.schemas.common.sample import Puck as RobotPuck
from mx_robot_library.schemas.common.tool import RobotTools
from mx_robot_library.schemas.responses.state import StateResponse
from pydantic import JsonValue
from typing_extensions import (
    Literal,
    TypedDict,
)

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import (
    SampleChanger as AbstractSampleChanger,
)
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import SampleChangerState
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import (
    Basket as AbstractPuck,
)
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import Container
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import (
    Pin as AbstractPin,
)
from mxcubecore.TaskUtils import task as dtask

from .prefect_flows.sync_prefect_client import MX3SyncPrefectClient

hwr_logger = logging.getLogger("HWR")
robot_config = get_robot_settings()


class SampleChangerError(Exception):
    """Sample Changer Error"""


class PathTimeout(SampleChangerError):
    """Path Timeout"""


class PositionError(SampleChangerError):
    """Position Error"""


class ToolError(SampleChangerError):
    """Tool Error"""


class SampleData(TypedDict, total=True):
    """Sample Data"""

    sampleID: str
    location: str
    sampleName: str
    code: str
    loadable: Literal[True]
    state: Literal[8, 4, 0]
    tasks: list[JsonValue]
    type: Literal["Sample"]
    defaultPrefix: Optional[str]
    defaultSubDir: Optional[str]


class MxcubePin(AbstractPin):
    """MXCuBE Pin"""

    def __init__(self, basket: MxcubePuck, puck_location: int, port: int) -> None:
        """
        Parameters
        ----------
        basket : MxcubePuck
            An MxcubePuck instance
        puck_location : int
            The puck location in the dewar
        port : int
            The pin position in the puck
        """
        super().__init__(basket, puck_location, port)
        self.robot_id = port
        self.container: MxcubePuck


class MxcubePuck(AbstractPuck):
    """MXCuBE Puck"""

    def __init__(
        self,
        container: Container,
        puck_location: int,
        samples_num: int = 16,
        name: str = "Puck",
    ) -> None:
        """
        Parameters
        ----------
        container : Container
            The container, e.g. the SampleChanger hardware object
        puck_location : int
            The puck location in the dewar
        samples_num : int, optional
            The number of samples per puck, by default 16
        name : str, optional
            The name of the puck, by default "Puck"
        """
        super(AbstractPuck, self).__init__(
            self.__TYPE__, container, MxcubePuck.get_basket_address(puck_location), True
        )
        self.robot_id = puck_location

        self._name = name
        self.samples_num = samples_num
        for port in range(1, samples_num + 1):
            slot = MxcubePin(self, puck_location, port)
            self._add_component(slot)


class SampleChanger(AbstractSampleChanger):
    """ANSTO Sample Changer"""

    __TYPE__ = "IRELEC_ISARA2"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(self.__TYPE__, False, *args, **kwargs)

        self._pin_name_cache = {}

    def init(self) -> None:
        self._selected_sample = -1
        self._selected_basket = -1
        self._scIsCharging = None

        self.no_of_baskets = (
            robot_config.ASC_NUM_PUCKS
        )  # TODO: no_of_baskets = number of projects
        self.no_of_samples_in_basket = (
            robot_config.ASC_NUM_PINS
        )  # TODO: number of samples per project

        for puck_location in range(1, self.no_of_baskets + 1):
            basket = MxcubePuck(
                self,
                puck_location,
                samples_num=self.no_of_samples_in_basket,
            )
            self._add_component(basket)

        self._set_state(SampleChangerState.Unknown)
        self.signal_wait_task = None
        self.use_update_timer = True
        logging.getLogger("HWR").info(
            f"SampleChanger: Using update timer is {self.use_update_timer}",
        )

        task1s = self.__timer_1s_task(wait=False)
        task1s.link(self._on_timer_1s_exit)
        updateTask = self.__update_timer_task(wait=False)
        updateTask.link(self._on_timer_update_exit)

        self.update_info()

        self.log_filename = self.get_property("log_filename")

        self._mount_deployment_name = self.get_property("mount_deployment_name")
        self._unmount_deployment_name = self.get_property("unmount_deployment_name")

        client = self.get_client()

        loaded_pucks = client.status.get_loaded_pucks()
        self.loaded_pucks_dict: dict[int, RobotPuck] = {}
        for robot_puck in loaded_pucks:
            self.loaded_pucks_dict[robot_puck.id] = robot_puck

    @dtask
    def __update_timer_task(self, *args):
        while True:
            sleep(1)
            try:
                self._timer_update_counter += 1
                if self._timer_update_counter >= self._timer_update_counter:
                    self._on_timer_update()
                    self._timer_update_counter = 0
            except Exception:
                pass

    @lru_cache()
    def get_client(self) -> Client:
        """Cache the client, this allows the client to be used in dependencies and
        for overwriting in tests
        """
        return Client(host=settings.ROBOT_HOST, readonly=False)

    def get_log_filename(self):
        return self.log_filename

    def is_enabled(self):
        """ """
        try:
            _client = self.get_client()
            robot_state = _client.status.state
        except Exception:
            return None
        else:
            return robot_state.power and robot_state.remote_mode

    def _mxcube_sample_to_prefect_sample(
        self, mxcube_sample: str | MxcubePin
    ) -> dict[str, Any]:
        """MXCube sample to prefect sample conversion

        Parameters
        ----------
        mxcube_sample : str | MxcubePin
            The sample address in MXCuBE format, e.g. "1:01" or
            an instance of MxcubePin.

        Returns
        -------
        dict
            A dictionary describing the pin locations that
            prefect understands
        """
        if isinstance(mxcube_sample, str):
            sample_tuple = tuple(
                int(_item) for _item in mxcube_sample.split(":", maxsplit=1)
            )
        elif isinstance(mxcube_sample, MxcubePin):
            sample_tuple = (
                mxcube_sample.container.robot_id,
                mxcube_sample.robot_id,
            )
        else:
            raise ValueError(
                "mxcube_sample must be a str or MxcubePin instance, not {type(mxcube_sample)}"
            )

        prefect_pin = {
            "id": sample_tuple[1],
            "puck": {
                "id": sample_tuple[0],
            },
        }
        return prefect_pin

    def load(self, sample: str, sample_order: list[str] | None, wait: bool = False):
        """
        Load a sample.

        Parameters
        ----------
        sample : tuple
            sample address on the form (component1, ... ,component_N-1, component_N)
        sample_order : list[str] | None
            A sample order list containing a queue of samples. This can be used to prefetch
            samples. If None prefetching is not used
        wait : bool
            True to wait for load to complete False otherwise

        Returns
        -------
        Object
            Value returned by _execute_task either a Task or result of the
            operation
        """
        prefetch_sample = None  # Always define before the if-block
        if sample_order is not None and len(sample_order) > 0:
            for i in range(len(sample_order)):
                if sample_order[i] == sample:
                    try:
                        prefetch_sample = sample_order[i + 1]
                    except IndexError:
                        prefetch_sample = None
                    break
        else:
            prefetch_sample = None

        sample = self._resolve_component(sample)
        self.assert_not_charging()

        return self._execute_task(
            SampleChangerState.Loading, wait, self._do_load, sample, prefetch_sample
        )

    def is_mounted_sample(self, sample: tuple[int, int]) -> bool:
        return (
            self.get_component_by_address(
                MxcubePin.get_sample_address(sample[0], sample[1])
            )
            == self.get_loaded_sample()
        )

    def _do_abort(self):
        return

    def _do_change_mode(self):
        return

    def _do_update_info(self) -> None:
        """
        Polls and updates the Puck/Pin information and robot state.
        TODO: This method is called every second, but could be called
        less frequently
        """
        try:
            client = self.get_client()

            robot_state = client.status.state

            components: list[MxcubePuck] = self.get_components()
            for mxcube_puck_idx in range(self.no_of_baskets):
                puck_location = mxcube_puck_idx + 1
                robot_puck = self.loaded_pucks_dict.get(puck_location)
                mxcube_puck = components[mxcube_puck_idx]
                mxcube_puck._name = "test1"
                mxcube_puck._set_info(
                    present=robot_puck is not None,
                    id=(robot_puck is not None and str(robot_puck)) or None,
                    scanned=False,
                )

                for mxcube_pin_idx in range(self.no_of_samples_in_basket):
                    port = mxcube_pin_idx + 1
                    self._update_mxcube_pin_info(
                        robot_puck,
                        puck_location=puck_location,
                        port=port,
                        robot_state=robot_state,
                    )

            self._update_sample_changer_state(robot_state)

        except Exception as ex:
            ex

    def _update_mxcube_pin_info(
        self,
        robot_puck: RobotPuck,
        puck_location: int,
        port: int,
        robot_state: StateResponse,
    ):
        """
        Updates the pin information

        Parameters
        ----------
        robot_puck : RobotPuck
            A mx-robot-library Puck pydantic model
        puck_location : int
            The puck location in the dewar
        port : int
            The pin position in the puck
        robot_state : StateResponse
            The state from the robot as reported by the mx-robot-library
        """
        robot_pin: RobotPin | None = None
        if robot_puck is not None:
            robot_pin = RobotPin(
                id=port,
                puck=robot_puck,
            )

        address = MxcubePin.get_sample_address(puck_location, port)  # e.g. "1:01"
        mxcube_pin: MxcubePin = self.get_component_by_address(address)
        if robot_pin is not None and robot_puck.name:  # check also that barcode exists
            try:
                sample_name = self.get_sample_by_barcode_and_port(
                    port=port,
                    barcode=robot_puck.name.replace("-", ""),
                )
            except Exception:
                sample_name = str(robot_pin)
            mxcube_pin._name = sample_name
            pin_datamatrix = str(robot_pin)

            mxcube_pin._set_info(
                present=robot_puck is not None,
                id=pin_datamatrix,
                scanned=False,
            )
            loaded: bool = False
            if robot_state.goni_pin is not None:
                loaded = (
                    robot_state.goni_pin.puck.id,
                    robot_state.goni_pin.id,
                ) == (
                    puck_location,
                    port,
                )
            mxcube_pin._set_loaded(
                loaded=loaded,
                has_been_loaded=mxcube_pin.has_been_loaded() or loaded,
            )
            mxcube_pin._set_holder_length(MxcubePin.STD_HOLDERLENGTH)

    def _update_sample_changer_state(self, robot_state: StateResponse) -> None:
        """
        Updates the sample changer state

        Parameters
        ----------
        robot_state : StateResponse
            The Isara robot state response

        Returns
        -------
        None
        """
        _is_enabled = robot_state.power and robot_state.remote_mode
        _is_normal_state = _is_enabled and not robot_state.fault_or_stopped
        _state: int = SampleChangerState.Unknown
        if not _is_enabled:
            _state = SampleChangerState.Disabled
        elif robot_state.fault_or_stopped:
            _state = SampleChangerState.Fault
        elif robot_state.error is not None:
            # Might need to modify this to read binary alarms set in robot status.
            _state = SampleChangerState.Alarm
        elif robot_state.path.name != "":
            if robot_state.path.name in ("put", "getput", "putht", "getputht"):
                _state = SampleChangerState.Loading
            elif robot_state.path.name in ("get", "getht"):
                _state = SampleChangerState.Unloading
            elif robot_state.path.name == "pick":
                _state = SampleChangerState.Selecting
            elif robot_state.path.name == "datamatrix":
                _state = SampleChangerState.Scanning
            else:
                _state = SampleChangerState.Moving
        elif robot_state.goni_pin is not None:
            _state = SampleChangerState.Loaded
        elif _is_normal_state and robot_state.path.name == "":
            _state = SampleChangerState.Ready

        _last_state = self.state
        if _state != _last_state:
            self._set_state(
                state=_state,
                status=SampleChangerState.tostring(_state),
            )

    def _do_select(self, component) -> None:
        raise NotImplementedError

    def _do_scan(self, component, recursive) -> None:
        raise NotImplementedError

    def _do_load(
        self,
        sample: str | MxcubePin,
        prefetch_sample: str | MxcubePin | None,
    ) -> None:
        """
        Mounts a sample on the robot using the `mount` Prefect Flow.

        Parameters
        ----------
        sample : str | MxcubePin
            The sample to mount, in MXCuBE format, e.g. "1:01" or an instance of MxcubePin.
        prefetch_sample : str | MxcubePin | None
            The sample to prefetch, in MXCuBE format, e.g. "1:02" or an instance of MxcubePin.
            If None, no prefetching is done.

        Returns
        -------
        None
        """

        prefect_sample_to_mount = self._mxcube_sample_to_prefect_sample(sample)

        if prefetch_sample is not None:
            prefect_prefetch = self._mxcube_sample_to_prefect_sample(prefetch_sample)
        else:
            prefect_prefetch = None

        self._check_if_robot_is_ready()

        try:
            # Mount pin using `mount` Prefect Flow
            _prefect_mount_client = MX3SyncPrefectClient(
                name=self._mount_deployment_name,
                parameters={
                    "pin": prefect_sample_to_mount,
                    "prepick_pin": prefect_prefetch,
                },
            )

            _prefect_mount_client.trigger_flow(wait=True)
        except Exception:
            logging.getLogger("user_level_log").error(
                f"Failed to mount sample. Please check the status of the robot."
            )
            raise

    def _check_if_robot_is_ready(self) -> None:
        """
        Checks if the robot is ready to load or unload a sample.

        Raises
        ------
        PathTimeout
            If the robot does not change position to SOAK or does not change tool
            to DOUBLE_GRIPPER
        PositionError
            If the robot could not change position to SOAK
        ToolError
            If the robot could not change tool to DOUBLE_GRIPPER
        """
        _client = self.get_client()

        # Check position is currently SOAK
        if _client.status.state.position != RobotPositions.SOAK:
            _client.trajectory.soak(wait=False)

            # Wait for robot to start running the path
            _start_time_timeout = time() + 15
            while _client.status.state.path != RobotPaths.SOAK:
                # Timeout after 15 seconds if path not started
                if time() >= _start_time_timeout:
                    logging.getLogger("user_level_log").error(
                        "Failed to load sample. Robot could not change position to SOAK"
                    )
                    raise PathTimeout()
                sleep(0.5)

            # Wait for robot to finish running the path
            _end_time_timeout = time() + 120
            while _client.status.state.path != RobotPaths.UNDEFINED:
                # Timeout after 120 seconds if path not finished
                if time() >= _end_time_timeout:
                    logging.getLogger("user_level_log").error(
                        "Failed to load sample. Robot could not change position to SOAK"
                    )
                    raise PathTimeout()
                sleep(0.5)

            if _client.status.state.position != RobotPositions.SOAK:
                logging.getLogger("user_level_log").error(
                    "Failed to load sample. Robot could not change position to SOAK"
                )
                raise PositionError()

        # Check double gripper tool mounted
        if _client.status.state.tool != RobotTools.DOUBLE_GRIPPER:
            _client.trajectory.change_tool(tool=RobotTools.DOUBLE_GRIPPER, wait=False)

            # Wait for robot to start running the path
            _start_time_timeout = time() + 15
            while _client.status.state.path != RobotPaths.CHANGE_TOOL:
                # Timeout after 15 seconds if path not started
                if time() >= _start_time_timeout:
                    raise PathTimeout()
                sleep(0.5)

            # Wait for robot to finish running the path
            _end_time_timeout = time() + 240
            while _client.status.state.path != RobotPaths.UNDEFINED:
                # Timeout after 240 seconds if path not finished
                if time() >= _end_time_timeout:
                    raise PathTimeout()
                sleep(0.5)

            if _client.status.state.tool != RobotTools.DOUBLE_GRIPPER:
                raise ToolError()

    def chained_load(self, sample_to_unload, sample_to_load):
        """Chained load is not needed as the `mount` prefect-flow handles
        chained loads automatically
        """
        raise NotImplementedError

    def _do_unload(
        self,
        sample_slot: Any | None = None,
    ) -> None:
        """
        Unmounts a sample from the robot.

        Parameters
        ----------
        sample_slot : Any | None
            The sample slot to unload, by default None. If None, the currently loaded
            sample will be unloaded.

        Returns
        -------
        None
        """
        self._check_if_robot_is_ready()

        # Mount pin using `unmount` Prefect Flow
        try:
            _prefect_unmount_client = MX3SyncPrefectClient(
                name=self._unmount_deployment_name,
                parameters={},
            )

            _prefect_unmount_client.trigger_flow(wait=True)
        except Exception:
            logging.getLogger("user_level_log").error(
                f"Failed to unmount sample. Please check the status of the robot."
            )
            raise

    def _do_reset(self) -> None:
        """ """
        _client = self.get_client()
        _client.common.reset()

    def is_powered(self) -> bool:
        _client = self.get_client()
        return _client.status.state.power

    def get_sample_by_barcode_and_port(self, port: int, barcode: str) -> str:
        """
        Gets the pin model from the mx-data-layer-api from port and barcode.
        The epn is read from redis.

        Returns
        -------
        str
            The sample name

        """
        with redis.StrictRedis(
            host=settings.MXCUBE_REDIS_HOST,
            port=settings.MXCUBE_REDIS_PORT,
            username=settings.MXCUBE_REDIS_USERNAME,
            password=settings.MXCUBE_REDIS_PASSWORD,
            db=settings.MXCUBE_REDIS_DB,
        ) as redis_connection:

            epn_value: bytes | None = redis_connection.get("epn")
            if epn_value is None:
                logging.getLogger("user_level_log").error(
                    "epn redis key does not exist"
                )
                raise ValueError(
                    f"epn redis key does not exist",
                )

            epn_string = epn_value.decode("utf-8")

        return self.get_pin_name(
            epn_string=epn_string,
            port=port,
            barcode=barcode.replace("-", ""),
        )

    def get_pin_name(self, epn_string, port, barcode) -> str:
        """
        Get the pin name from the data layer API by barcode, port, and epn.
        If the pin name is already cached, returns the cached value,
        otherwise it will call the data layer API to get the pin name.

        Parameters
        ----------
        epn_string : str
            The epn strings
        port : int
            The port number of the pin.
        barcode : str
            The barcode of the puck containing the pin.

        Returns
        -------
        str
            The sample name.
        """
        key = (epn_string, port, barcode)
        if key in self._pin_name_cache:
            return self._pin_name_cache[key]

        url = urljoin(
            settings.DATA_LAYER_API,
            f"/samples/pins?filter_by_port={port}&filter_by_puck_barcode={barcode}&filter_by_visit_identifier={epn_string}",
        )
        r = httpx.get(url)
        if r.status_code == HTTPStatus.OK:
            data = r.json()
            if len(data) == 1:
                name = data[0]["name"]
                self._pin_name_cache[key] = name  # Cache only successful result
                return name
            else:
                raise ValueError(
                    f"Could not get pin by barcode, port, and epn from the data layer API: {r.content}",
                )
        else:
            raise ValueError(
                f"Could not get pin by barcode, port, and epn from the data layer API: {r.content}",
            )
