import logging
import time
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
    # TODO: Test if this class works with real hardware
    """
    OphydShutter class to control the shutter using Ophyd
    """

    SPECIFIC_STATES = OpenCloseStatus

    def init(self):
        """Initialisation"""
        super().init()
        self.shutter = getattr(shutters, self.get_property("actuator_name"))
        self.update_value(self.get_value())
        self.update_state(self.STATES.READY)

    @property
    def is_open(self) -> bool:
        """
        Check if the shutter is open

        Returns
        -------
        bool
            True if the shutter is open, False otherwise
        """
        return self.get_value() == self.VALUES.OPEN

    def open(self, timeout=None):
        """
        Opens the shutter

        Parameters
        ----------
        timeout : float, optional
            If timeout == 0: return at once and do not wait.
            if timeout is None: wait forever.

        Returns
        -------
        None
        """
        self.set_value(self.VALUES.OPEN, timeout=timeout)

    def close(self, timeout: float = None) -> None:
        """
        Closes the shutter

        Parameters
        ----------
        timeout : float, optional
            If timeout == 0: return at once and do not wait.
            if timeout is None: wait forever.

        Returns
        -------
        None
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

    def set_value(self, value: Enum, timeout=0) -> None:
        """Sets the actuator value

        Parameters
        ----------
        value : Enum
            The shutter value
        timeout : int, optional
            The timeout, by default 0

        Raises
        ------
        ValueError
            Invalid value or attempt to set read only actuator.
        RuntimeError
            Timeout waiting for status ready  # From wait_ready
        """
        if self.read_only:
            raise ValueError("Attempt to set value for read-only Actuator")

        self._set_value(value)
        self.update_value()
        if timeout == 0:
            return
        self.wait_ready(timeout)

    def _set_value(self, value: Enum):
        """Sets the shutter value

        Parameters
        ----------
        value : Enum
            The shutter value

        Raises
        ------
        ValueError
            Raised if the value is not valid
        """
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
                f"Invalid value {value}. Only `ValueEnum.OPEN: 'open'` and "
                "`ValueEnum.CLOSED: 'closed'` are allowed."
            )

        logging.getLogger("HWR").info(
            f"open_close_cmd successfully set to {self.shutter.open_close_cmd.get()}"
        )
        logging.getLogger("HWR").info(
            f"open_close_status value: {self.shutter.open_close_status.get() }"
        )
        return

    def _move(self, value: float) -> float:
        """Move the shutter to a given value.

        Parameters
        ----------
        value : float
            Position of the shutter.

        Returns
        -------
        float
            New position of the motor.
        """
        self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        while self.shutter.open_close_status.get() == OpenCloseStatus.MOVING:
            time.sleep(0.1)
            self.update_state(self.STATES.BUSY)

        self.update_state(self.STATES.READY)
        return value
