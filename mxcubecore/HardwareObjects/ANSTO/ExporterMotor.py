import logging
import math
import sys

from gevent import (
    Timeout,
    sleep,
)

from mxcubecore.Command.Exporter import Exporter
from mxcubecore.Command.exporter.ExporterStates import ExporterStates
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor


class ExporterMotor(AbstractMotor):
    """Microdiff with Exporter implementation of AbstractMotor

    Example of xml config file:

    <device class="ANSTO.ExporterMotor">
        <username>PhiX</username>
        <exporter_address>12.345.678.91:9002</exporter_address>
        <actuator_name>AlignmentX</actuator_name>
        <tolerance>1e-2</tolerance>
    </device>
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            name of the Hardware Object

        Returns
        -------
        None
        """
        AbstractMotor.__init__(self, name)
        self.username = None
        self._motor_pos_suffix = None
        self._motor_state_suffix = None
        self._exporter = None
        self._exporter_address = None
        self.motor_position_chan = None
        self.motor_state_chan = None

    def init(self) -> None:
        """Object initialization - executed after loading contents

        Returns
        -------
        None
        """
        AbstractMotor.init(self)
        self._motor_pos_suffix = self.get_property("position_suffix", "Position")
        self._motor_state_suffix = self.get_property("state_suffix", "State")

        self._exporter_address = settings.EXPORTER_ADDRESS
        _host, _port = self._exporter_address.split(":")
        self._exporter = Exporter(_host, int(_port))

        self.motor_position_chan = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self._exporter_address,
                "name": "position",
            },
            self.actuator_name + self._motor_pos_suffix,
        )
        if self.motor_position_chan:
            self.get_value()
            self.motor_position_chan.connect_signal("update", self.update_value)

        self.motor_state_chan = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self._exporter_address,
                "name": "motor_state",
            },
            self.actuator_name + self._motor_state_suffix,
        )

        if self.motor_state_chan:
            self.motor_state_chan.connect_signal("update", self._update_state)

        self.update_state()
        logging.getLogger("HWR").debug(f"username: {self.username}")

    def get_state(self):
        """Get the motor state.

        Returns
        -------
        enum 'HardwareObjectState'
            Motor state.
        """
        try:
            _state = self.motor_state_chan.get_value().upper()
            self.specific_state = _state
            return ExporterStates.__members__[_state].value
        except (KeyError, AttributeError):
            return self.STATES.UNKNOWN

    def _update_state(self, state):
        try:
            state = state.upper()
            state = ExporterStates.__members__[state].value
        except (AttributeError, KeyError):
            state = self.STATES.UNKNOWN
        return self.update_state(state)

    def _get_hwstate(self) -> str:
        """Get the hardware state, reported by the MD3 application.

        Returns
        -------
        str
            The state of the MD3
        """
        try:
            return self._exporter.read_property("HardwareState")
        except Exception:
            return "Ready"

    def _get_swstate(self) -> str:
        """Get the software state, reported by the MD3 application.

        Returns
        -------
        str
            he state of the MD3
        """
        return self._exporter.read_property("State")

    def _ready(self) -> bool:
        """Get the "Ready" state - software and hardware.

        Returns
        -------
        bool
            True if both "Ready", False otherwise.
        """
        if (
            self._get_swstate() == "Ready"
            and self._get_hwstate() == "Ready"
            and self.motor_state_chan.get_value() == "Ready"
        ):
            return True
        return False

    def _wait_ready(self, timeout: float = 3) -> None:
        """Wait for the state to be "Ready".

        Parameters
        ----------
        timeout : float
            waiting time [s].

        Raises
        ------
        RuntimeError
            Execution timeout.

        Returns
        -------
        None
        """
        with Timeout(timeout, RuntimeError("Execution timeout")):
            while not self._ready():
                sleep(0.01)

    def wait_move(self, timeout: float = 20) -> None:
        """Wait until the end of move ended, using the application state.

        Parameters
        ----------
        timeout : float
            Timeout [s]. Default value is 20 s

        Returns
        -------
        None
        """
        self._wait_ready(timeout)

    def wait_motor_move(self, timeout: float = 20) -> None:
        """Wait until the end of move ended using the motor state.

        Parameters
        ----------
        timeout : float
            Timeout [s]. Default value is 20 s

        Raises
        ------
        RuntimeError
            Execution timeout.

        Returns
        -------
        None
        """
        with Timeout(timeout, RuntimeError("Execution timeout")):
            while self.get_state() != self.STATES.READY:
                sleep(0.01)

    def get_value(self) -> float:
        """Get the motor position.

        Returns
        -------
        float
            Motor position.
        """
        _v = self.motor_position_chan.get_value()

        if _v is None or math.isnan(_v):
            logging.getLogger("HWR").debug(
                f"Value of {self.actuator_name} is NaN or None"
            )
            _v = self._nominal_value

        self._nominal_value = _v

        return self._nominal_value

    def __get_limits(self, cmd: str) -> tuple[float, float]:
        """Returns motor low and high limits.

        Parameters
        ----------
        cmd : str
            command name

        Returns
        -------
        tuple
            Two floats tuple (low limit, high limit).
        """
        try:
            _low, _high = self._exporter.execute(cmd, (self.actuator_name,))
            # inf is a problematic value, convert to sys.float_info.max
            if _low == float("-inf"):
                _low = -sys.float_info.max

            if _high == float("inf"):
                _high = sys.float_info.max

            return _low, _high
        except ValueError:
            return -1e4, 1e4

    def get_limits(self) -> tuple[float, float]:
        """Returns motor low and high limits.

        Returns
        -------
        tuple
            Two floats tuple (low limit, high limit).
        """
        self._nominal_limits = self.__get_limits("getMotorLimits")
        return self._nominal_limits

    def get_dynamic_limits(self) -> tuple[float, float]:
        """Returns motor low and high dynamic limits.

        Returns
        -------
        tuple
            Two floats tuple (low limit, high limit).
        """
        return self.__get_limits("getMotorDynamicLimits")

    def _set_value(self, value: float) -> None:
        """Move motor to absolute value.

        Parameters
        ----------
        value : float
            Target value

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)
        self.motor_position_chan.set_value(value)

    def abort(self) -> None:
        """Stop the motor movement immediately.

        Returns
        -------
        None
        """
        if self.get_state() != self.STATES.UNKNOWN:
            self._exporter.execute("abort")

    def home(self, timeout: float = None) -> None:
        """Homing procedure.

        Parameters
        ----------
        timeout : float, optional
            Homing procedure timeout, by default None

        Returns
        -------
        None
        """
        self._exporter.execute("startHomingMotor", (self.actuator_name,))
        self.wait_ready(timeout)

    def get_max_speed(self) -> float:
        """Get the motor maximum speed.

        Returns
        -------
        float
            The maximum speed [unit/s].
        """
        return self._exporter.execute("getMotorMaxSpeed", (self.actuator_name,))
