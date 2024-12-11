import logging
from enum import (
    Enum,
    IntEnum,
    unique,
)

from mx3_beamline_library.devices import shutters

from mxcubecore.BaseHardwareObjects import HardwareObjectState
from mxcubecore.HardwareObjects.abstract.AbstractShutter import AbstractShutter
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


@unique
class OpenCloseCmd(IntEnum):
    NO_ACTION = 0
    CLOSE = 1
    OPEN = 2


@unique
class OpenCloseStatus(IntEnum):
    UNKNOWN = 0
    INVALID = 1  # MAJOR
    CLOSED = 2  # NO_ALARM
    OPEN = 3  # NO_ALARM
    MOVING = 4  # NO_ALARM


class OphydShutter(AbstractShutter, EPICSActuator):
    # NOTE, TODO if this class does not work, we can revert to using the ShutterMockup class
    # To test the addition of the white beam shutter to the UI
    """
    ShutterMockup for simulating a simple open/close shutter.
    Fake some of the states of the shutter to correspong to values.
    """

    SPECIFIC_STATES = OpenCloseStatus

    def init(self):
        """Initialisation"""
        super().init()
        self.shutter = getattr(shutters, self.get_property("actuator_name"))
        self.update_value(self.get_value())
        self.update_state(self.STATES.READY)

    @property
    def is_open(self):
        """Check if the shutter is open.
        Returns:
            (bool): True if open, False otherwise.
        """
        return self.get_value() == self.VALUES.OPEN

    def open(self, timeout=None):
        """Open the shutter.
        Args:
            timeout(float): optional - timeout [s],
                            If timeout == 0: return at once and do not wait
                            if timeout is None: wait forever.
        """
        self.set_value(self.VALUES.OPEN, timeout=timeout)

    def close(self, timeout=None):
        """Close the shutter.
        Args:
            timeout(float): optional - timeout [s],
                            If timeout == 0: return at once and do not wait
                            if timeout is None: wait forever.
        """
        self.set_value(self.VALUES.CLOSED, timeout=timeout)

    def get_value(self) -> Enum:
        """Read the shutter position.

        Returns
        -------
        Enum
            The shutter position.
        """
        value = self.shutter.open_close_status.get()
        if value == OpenCloseStatus.CLOSED:
            return self.VALUES.CLOSED
        elif value == OpenCloseStatus.OPEN:
            return self.VALUES.OPEN
        else:
            return self.VALUES.UNKNOWN

    def set_value(self, value, timeout=0):
        """Set actuator to value.
        Args:
            value: target value
            timeout (float): optional - timeout [s],
                             If timeout == 0: return at once and do not wait
                                              (default);
                             if timeout is None: wait forever.
        Raises:
            ValueError: Invalid value or attemp to set read only actuator.
            RuntimeError: Timeout waiting for status ready  # From wait_ready
        """
        if self.read_only:
            raise ValueError("Attempt to set value for read-only Actuator")

        self._set_value(value)
        self.update_value()
        if timeout == 0:
            return
        self.wait_ready(timeout)

    def _set_value(self, value: Enum):
        # value, e.g.
        # ValueEnum.OPEN: 'open'
        # TODO: Validate this with real hardware!
        logging.getLogger("HWR").info(f"Setting shutter {self.shutter.name} to {value}")
        if value.value.lower() == "open":
            logging.getLogger("HWR").info("Opening shutter...")
            self.shutter.open_close_cmd.set(OpenCloseCmd.OPEN)
            logging.getLogger("HWR").info("Shutter opened")
        elif value.value.lower() == "closed":
            logging.getLogger("HWR").info("Closing shutter..")
            self.shutter.open_close_cmd.set(OpenCloseCmd.CLOSE)
            logging.getLogger("HWR").info("Shutter closed")
        else:
            raise ValueError(
                f"Invalid value {value}. Only {self.VALUES.OPEN} and {self.VALUES.CLOSED} are allowed."
            )

        logging.getLogger("HWR").info(
            f"open_close_cmd successfully set to {self.shutter.open_close_cmd.get()}"
        )
        logging.getLogger("HWR").info(
            f"open_close_status value: {self.shutter.open_close_status.get() }"
        )
        return
