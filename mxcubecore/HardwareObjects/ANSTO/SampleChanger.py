from __future__ import annotations

import logging  # noqa: E402
from asyncio import new_event_loop as asyncio_new_event_loop
from asyncio import set_event_loop as asyncio_set_event_loop  # noqa: E402
from functools import lru_cache  # noqa: E402
from time import time  # noqa: E402
from typing import (  # noqa: E402
    Any,
    Optional,
    Union,
)

from gevent import sleep  # noqa: E402
from mx_robot_library.client.client import Client  # noqa: E402
from mx_robot_library.config import get_settings as get_robot_settings  # noqa: E402
from mx_robot_library.schemas.common.path import RobotPaths  # noqa: E402
from mx_robot_library.schemas.common.position import RobotPositions  # noqa: E402
from mx_robot_library.schemas.common.sample import Pin as RobotPin
from mx_robot_library.schemas.common.sample import Puck as RobotPuck  # noqa: E402
from mx_robot_library.schemas.common.tool import RobotTools  # noqa: E402
from mx_robot_library.schemas.responses.state import StateResponse
from pydantic import JsonValue  # noqa: E402
from typing_extensions import (  # noqa: E402
    Literal,
    TypedDict,
)

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import (  # noqa: E402
    SampleChanger as AbstractSampleChanger,
)
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import SampleChangerState
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import (  # noqa: E402
    Basket as AbstractPuck,
)
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import Container
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import (
    Pin as AbstractPin,
)
from mxcubecore.TaskUtils import task as dtask  # noqa: E402

from .prefect_flows.prefect_client import MX3PrefectClient  # noqa: E402

# monkey.patch_all()


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

    def chained_load(self, sample_to_unload, sample_to_load):
        """
        Chain the unload of a sample with a load.

        Args:
            sample_to_unload (tuple): sample address on the form
                                      (component1, ... ,component_N-1, component_N)
            sample_to_load (tuple): sample address on the form
                                      (component1, ... ,component_N-1, component_N)
            (Object): Value returned by _execute_task either a Task or result of the
                      operation
        """
        _client = self.get_client()
        if isinstance(sample_to_load, str):
            sample_to_load: tuple[int, int] = tuple(
                int(_item) for _item in sample_to_load.split(":", maxsplit=1)
            )
        elif isinstance(sample_to_load, MxcubePin):
            sample_to_load: tuple[int, int] = (
                sample_to_load.container.robot_id,
                sample_to_load.robot_id,
            )

        if _client.status.state.goni_pin is not None:
            return self.unload_then_load(sample_to_load)
        return self.load(sample_to_load)

    def load_sample(
        self,
        holder_length: float,
        sample_location: Union[tuple[int, int], str],
        wait=False,
    ) -> Union[MxcubePin, None]:
        return self.load(sample_location, wait)

    def unload_then_load(self, sample=None, wait=True):
        """ """
        sample = self._resolve_component(sample)
        self.assert_not_charging()

        self.unload()
        self.load(sample)

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
            mxcube_pin._name = str(
                robot_pin
            )  # TODO: This is where sample name is set!! get name from DL
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
        sample: Union[tuple[int, int], str, MxcubePin],
    ) -> None:

        _client = self.get_client()
        if isinstance(sample, str):
            sample: tuple[int, int] = tuple(
                int(_item) for _item in sample.split(":", maxsplit=1)
            )
        elif isinstance(sample, MxcubePin):
            sample: tuple[int, int] = (sample.container.robot_id, sample.robot_id)

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

        try:
            # Mount pin using `mount` Prefect Flow
            _prefect_mount_client = MX3PrefectClient(
                name=self._mount_deployment_name,
                parameters={
                    "pin": {
                        "id": sample[1],
                        "puck": {
                            "id": sample[0],
                        },
                    }
                },
            )
            _event_loop = asyncio_new_event_loop()
            asyncio_set_event_loop(_event_loop)
            _event_loop.run_until_complete(
                _prefect_mount_client.trigger_flow(wait=True)
            )
        except Exception:
            logging.getLogger("user_level_log").error(
                f"Failed to mount sample. Please check the status of the robot."
            )
            raise

    def _do_unload(
        self,
        sample_slot: Optional[Any] = None,
    ) -> None:
        """ """
        _client = self.get_client()

        # Check position is currently SOAK
        if _client.status.state.position != RobotPositions.SOAK:
            _client.trajectory.soak(wait=False)

            # Wait for robot to start running the path
            _start_time_timeout = time() + 15
            while _client.status.state.path != RobotPaths.SOAK:
                # Timeout after 15 seconds if path not started
                if time() >= _start_time_timeout:
                    raise PathTimeout()
                sleep(0.5)

            # Wait for robot to finish running the path
            _end_time_timeout = time() + 120
            while _client.status.state.path != RobotPaths.UNDEFINED:
                # Timeout after 120 seconds if path not finished
                if time() >= _end_time_timeout:
                    raise PathTimeout()
                sleep(0.5)

            if _client.status.state.position != RobotPositions.SOAK:
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

        # Mount pin using `unmount` Prefect Flow
        _prefect_unmount_client = MX3PrefectClient(
            name=self._unmount_deployment_name,
            parameters={},
        )
        _event_loop = asyncio_new_event_loop()
        asyncio_set_event_loop(_event_loop)
        _event_loop.run_until_complete(_prefect_unmount_client.trigger_flow(wait=True))

    def _do_reset(self) -> None:
        """ """
        _client = self.get_client()
        _client.common.reset()

    def is_powered(self) -> bool:
        _client = self.get_client()
        return _client.status.state.power
