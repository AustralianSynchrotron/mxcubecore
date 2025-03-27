from enum import Enum
from os import getenv

from gevent import (
    Timeout,
    sleep,
)

from mxcubecore.Command.Exporter import Exporter
from mxcubecore.Command.exporter.ExporterStates import ExporterStates
from mxcubecore.HardwareObjects.abstract.AbstractNState import AbstractNState


class ExporterNState(AbstractNState):
    """
    Microdiff with Exporter implementation of AbstractNState. This class
    is effectively the same as:

    from mxcubecore.HardwareObjects.ExporterNState import ExporterNState

    with the difference that we read the exporter address from and ENV variable,
    instead of the xml config file.
    """

    SPECIFIC_STATES = ExporterStates

    def __init__(self, name):
        super().__init__(name)
        self._exporter = None
        self.value_channel = None
        self.state_channel = None
        self.use_value_as_state = None

    def init(self):
        """Initialise the device"""
        super().init()
        value_channel = self.get_property("value_channel_name")
        # use the value to check if action finished.
        self.use_value_as_state = self.get_property("value_state")
        state_channel = self.get_property("state_channel_name", "State")

        _exporter_address = getenv("EXPORTER_ADDRESS", "12.345.678.10:1234")
        _host, _port = _exporter_address.split(":")
        self._exporter = Exporter(_host, int(_port))

        self.value_channel = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": _exporter_address,
                "name": value_channel.lower(),
            },
            value_channel,
        )
        self.value_channel.connect_signal("update", self.update_value)

        self.state_channel = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": _exporter_address,
                "name": "state",
            },
            state_channel,
        )

        self.state_channel.connect_signal("update", self._update_state)
        self.update_state()

    def update_value(self, value=None):
        if self._nominal_value != value:
            self._nominal_value = value
            self.emit("valueChanged", (self.value_to_enum(value),))

    def _wait_hardware(self, value, timeout=None):
        """Wait timeout seconds till hardware in place.
        Args:
            value (str, int): value to be tested.
            timeout(float): Timeout [s]. None means infinite timeout.
        """
        with Timeout(timeout, RuntimeError("Timeout waiting for hardware")):
            while self.value_channel.get_value() != value:
                sleep(0.5)

    def _wait_ready(self, timeout=None):
        """Wait timeout seconds till status is ready.
        Args:
            timeout(float): Timeout [s]. None means infinite timeout.
        """
        with Timeout(timeout, RuntimeError("Timeout waiting for status ready")):
            while not self.get_state() == self.STATES.READY:
                sleep(0.5)

    def _update_state(self, state=None):
        """To be used to update the state when emiting the "update" signal.
        Args:
            state (str): optional state value
        Returns:
            (enum 'HardwareObjectState'): state.
        """
        if not state:
            state = self.get_state()
        else:
            state = self._str2state(state)
        return self.update_state(state)

    def _str2state(self, state):
        """Convert string state to HardwareObjectState enum value.
        Args:
            state (str): the state
        Returns:
            (enum 'HardwareObjectState'): state
        """
        try:
            return self.SPECIFIC_STATES.__members__[state.upper()].value
        except (AttributeError, KeyError):
            return self.STATES.UNKNOWN

    def get_state(self):
        """Get the device state.
        Returns:
            (enum 'HardwareObjectState'): Device state.
        """
        state = self.state_channel.get_value()
        return self._str2state(state)

    def abort(self):
        """Stop the action."""
        if self.get_state() != self.STATES.UNKNOWN:
            self._exporter.execute("abort")

    def _set_value(self, value):
        """Set device to value
        Args:
            value (str, int, float or enum): Value to be set.
        """
        # NB Workaround beacuse diffractomer does not send event on
        # change of actuators (light, scintillator, cryostream...)
        self.update_state(self.STATES.BUSY)

        if isinstance(value, Enum):
            if isinstance(value.value, (tuple, list)):
                value = value.value[0]
            else:
                value = value.value
        self.value_channel.set_value(value)
        # wait until the hardware returns value set
        if self.use_value_as_state:
            self._wait_hardware(value, 120)
        self._wait_ready(120)
        self.update_state(self.STATES.READY)

    def get_value(self):
        """Get the device value
        Returns:
            (Enum): Enum member, corresponding to the value or UNKNOWN.
        """
        _val = self.value_channel.get_value()
        return self.value_to_enum(_val)
