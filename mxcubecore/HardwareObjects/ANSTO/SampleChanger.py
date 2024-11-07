from __future__ import annotations

from gevent import monkey
monkey.patch_all()

import logging
from typing import Annotated, Any, Optional, Union, overload
from typing_extensions import Literal, TypedDict, deprecated
from time import sleep as time_sleep
from functools import lru_cache
from requests import get as requests_get
from pydantic import ConfigDict, Field, InstanceOf, Json, JsonValue, validate_call
from gevent import sleep
from mxcubecore.TaskUtils import task as dtask
from mxcubecore.HardwareObjects.abstract.AbstractSampleChanger import (
    SampleChanger as AbstractSampleChanger,
    SampleChangerState,
)
from mxcubecore.HardwareObjects.abstract.sample_changer.Container import (
    Basket as AbstractPuck,
    Pin as AbstractPin,
)
from mx_robot_library.config import get_settings as get_robot_settings
from mx_robot_library.client.client import Client
from mx_robot_library.schemas.common.sample import Puck as RobotPuck, Pin as RobotPin
from .md3 import MD3Phase

hwr_logger = logging.getLogger("HWR")
robot_config = get_robot_settings()


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


class Pin(AbstractPin):
    """MXCuBE Pin"""

    def __init__(self, basket: Puck, basket_no: int, sample_no: int) -> None:
        super().__init__(basket, basket_no, sample_no)
        self.robot_id = sample_no
        self.container: Puck


class Puck(AbstractPuck):
    """MXCuBE Puck"""

    def __init__(self, container, number: int, samples_num: int = 10, name: str = "Puck") -> None:
        super(AbstractPuck, self).__init__(
            self.__TYPE__, container, Puck.get_basket_address(number), True
        )
        self.robot_id = number

        self._name = name
        self.samples_num = samples_num
        for _id in range(1, samples_num + 1):
            slot = Pin(self, number, _id)
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

        self.no_of_baskets = robot_config.ASC_NUM_PUCKS
        self.no_of_samples_in_basket = robot_config.ASC_NUM_PINS

        for _puck_id in range(1, self.no_of_baskets + 1):
            basket = Puck(
                self,
                _puck_id,
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
        return Client(host=self.get_property("robot_host"), readonly=False)

    def get_log_filename(self):
        return self.log_filename

    def is_enabled(self):
        """ """
        try:
            _client = self.get_client()
            _state_res = _client.status.state
        except Exception:
            return None
        else:
            return _state_res.power and _state_res.remote_mode

    # @deprecated(
    #     (
    #         "The `SampleChanger.chained_load` method should not be used, "
    #         "call the `SampleChanger.load` method instead."
    #     )
    # )
    # @validate_call
    # def chained_load(
    #     self,
    #     sample_to_unload: Union[tuple[int, int], str],
    #     sample_to_load: Annotated[
    #         Union[tuple[int, int], str],
    #         Field(pattern=r"(\d+):(\d+)"),
    #     ],
    # ) -> Union[Pin, None]:
    #     """ """
    #     raise NotImplementedError

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
                int(_item)
                for _item in sample_to_load.split(":", maxsplit=1)
            )
        elif isinstance(sample_to_load, Pin):
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
    ) -> Union[Pin, None]:
        return self.load(sample_location, wait)

    def unload_then_load(self, sample=None, wait=True):
        """ """
        sample = self._resolve_component(sample)
        self.assert_not_charging()
        return self._execute_task(
            SampleChangerState.Loading,
            wait,
            self._do_unload_then_load,
            sample,
        )

    # @validate_call
    # def load(
    #     self,
    #     sample: Annotated[
    #         Union[tuple[int, int], str],
    #         Field(pattern=r"(\d+):(\d+)"),
    #     ],
    #     wait: bool = True,
    # ) -> Union[Pin, None]:
    #     """ """
    #     raise NotImplementedError

    # def get_loaded_sample(self) -> Union[Pin, None]:
    #     """ """
    #     _client = self.get_client()
    #     _goni_pin = _client.status.state.goni_pin
    #     if _goni_pin is None:
    #         return None
    #     return self.get_component_by_address(
    #         Pin.get_sample_address(_goni_pin.puck.id, _goni_pin.id),
    #     )

    def is_mounted_sample(self, sample: tuple[int, int]) -> bool:
        return (
            self.get_component_by_address(
                Pin.get_sample_address(sample[0], sample[1])
            )
            == self.get_loaded_sample()
        )

    def _do_abort(self):
        return

    def _do_change_mode(self):
        return

    def _do_update_info(self) -> None:
        """ """
        try:
            # Update Puck/Pin info
            _client = self.get_client()

            _state_res = _client.status.state
            _loaded_pucks: dict[int, RobotPuck] = {}
            for _puck in _client.status.get_loaded_pucks():
                _loaded_pucks[_puck.id] = _puck

            _components: list[Puck] = self.get_components()
            for _mxcube_puck_idx in range(self.no_of_baskets):
                _puck_id = _mxcube_puck_idx + 1
                _puck = _loaded_pucks.get(_puck_id)
                _mxcube_puck = _components[_mxcube_puck_idx]
                _mxcube_puck._set_info(
                    present=_puck is not None,
                    id=(_puck is not None and str(_puck)) or None,
                    scanned=False,
                )

                for _mxcube_pin_idx in range(self.no_of_samples_in_basket):
                    _pin_id = _mxcube_pin_idx + 1
                    _pin: RobotPin | None = None
                    if _puck is not None:
                        _pin = RobotPin(
                            id=_pin_id,
                            puck=_puck,
                        )
                    _address = Pin.get_sample_address(_puck_id, _pin_id)
                    _mxcube_pin: Pin = self.get_component_by_address(_address)
                    _pin_datamatrix = f"matr{_puck_id}_{_pin_id}"
                    if _pin is not None:
                        _mxcube_pin._name = str(_pin)
                        _pin_datamatrix = str(_pin)
                    _mxcube_pin._set_info(
                        present=_puck is not None,
                        id=_pin_datamatrix,
                        scanned=False,
                    )
                    _loaded: bool = False
                    if _state_res.goni_pin is not None:
                        _loaded = (
                            _state_res.goni_pin.puck.id,
                            _state_res.goni_pin.id,
                        ) == (
                            _puck_id,
                            _pin_id,
                        )
                    _mxcube_pin._set_loaded(
                        loaded=_loaded,
                        has_been_loaded=_mxcube_pin.has_been_loaded() or _loaded,
                    )
                    _mxcube_pin._set_holder_length(Pin.STD_HOLDERLENGTH)

            # Update SC state
            _is_enabled = _state_res.power and _state_res.remote_mode
            _is_normal_state = _is_enabled and not _state_res.fault_or_stopped
            _state: int = SampleChangerState.Unknown
            if not _is_enabled:
                _state = SampleChangerState.Disabled
            elif _state_res.fault_or_stopped:
                _state = SampleChangerState.Fault
            elif _state_res.error is not None:
                # Might need to modify this to read binary alarms set in robot status.
                _state = SampleChangerState.Alarm
            elif _state_res.path.name != "":
                if _state_res.path.name in ("put", "getput", "putht", "getputht"):
                    _state = SampleChangerState.Loading
                elif _state_res.path.name in ("get", "getht"):
                    _state = SampleChangerState.Unloading
                elif _state_res.path.name == "pick":
                    _state = SampleChangerState.Selecting
                elif _state_res.path.name == "datamatrix":
                    _state = SampleChangerState.Scanning
                else:
                    _state = SampleChangerState.Moving
            elif _state_res.goni_pin is not None:
                _state = SampleChangerState.Loaded
            elif _is_normal_state and _state_res.path.name == "":
                _state = SampleChangerState.Ready

            # SampleChangerState.Resetting
            # SampleChangerState.Charging
            # SampleChangerState.ChangingMode
            # SampleChangerState.StandBy
            # SampleChangerState.Initializing
            # SampleChangerState.Closing

            _last_state = self.state
            if _state != _last_state:
                self._set_state(
                    state=_state,
                    status=SampleChangerState.tostring(_state),
                )
        except Exception as ex:
            ex

    def _do_select(self, component) -> None:
        raise NotImplementedError

    def _do_scan(self, component, recursive) -> None:
        raise NotImplementedError

    def _do_load(
        self,
        sample: Union[tuple[int, int], str, Pin],
    ) -> None:
        """ """
        _client = self.get_client()
        if isinstance(sample, str):
            sample: tuple[int, int] = tuple(int(_item) for _item in sample.split(":", maxsplit=1))
        elif isinstance(sample, Pin):
            sample: tuple[int, int] = (sample.container.robot_id, sample.robot_id)

        # Check position is currently SOAK
        if _client.status.state.position.name != "SOAK":
            _client.trajectory.soak(wait=True)

        # Check MD3
        _md3_client = MD3Phase(address="10.244.101.30", port=9001)
        if _md3_client.get() != "Transfer":
            _md3_client.set(value="Transfer", wait=True)

        # Mount pin
        _client.trajectory.puck.mount(sample, wait=True)

    def _do_unload_then_load(
        self,
        sample: Union[tuple[int, int], str, Pin],
    ) -> None:
        """ """
        _client = self.get_client()
        if isinstance(sample, str):
            sample: tuple[int, int] = tuple(int(_item) for _item in sample.split(":", maxsplit=1))
        elif isinstance(sample, Pin):
            sample: tuple[int, int] = (sample.container.robot_id, sample.robot_id)

        # Check position is currently SOAK
        if _client.status.state.position.name != "SOAK":
            _client.trajectory.soak(wait=True)

        # Check MD3
        _md3_client = MD3Phase(address="10.244.101.30", port=9001)
        if _md3_client.get() != "Transfer":
            _md3_client.set(value="Transfer", wait=True)

        # Mount pin
        _client.trajectory.puck.unmount_then_mount(sample, wait=True)

    def _do_unload(
        self,
        sample_slot: Optional[Any] = None,
    ) -> None:
        """ """
        _client = self.get_client()

        # Check position is currently SOAK
        if _client.status.state.position.name != "SOAK":
            _client.trajectory.soak(wait=True)

        # Check MD3
        _md3_client = MD3Phase(address="10.244.101.30", port=9001)
        if _md3_client.get() != "Transfer":
            _md3_client.set(value="Transfer", wait=True)

        # Unmount pin
        _client.trajectory.puck.unmount(wait=True)

    def _do_reset(self) -> None:
        """ """
        _client = self.get_client()
        _client.common.reset()

    def is_powered(self) -> bool:
        _client = self.get_client()
        return _client.status.state.power
