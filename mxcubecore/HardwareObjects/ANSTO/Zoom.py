import logging
import time
from enum import Enum
from typing import Tuple

from mxcubecore.HardwareObjects.abstract.AbstractNState import AbstractNState
from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor


class Zoom(OphydEpicsMotor, AbstractNState):
    """
    Changes the camera zoom assuming that a motorized zoom lens is attached.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. `/diffractometer_config/zoom`

        Returns
        -------
        None
        """
        AbstractNState.__init__(self, name)
        OphydEpicsMotor.__init__(self, name)

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents

        Returns
        -------
        None
        """
        AbstractNState.init(self)
        OphydEpicsMotor.init(self)

        self.initialise_values()

        _len = len(self.VALUES) - 1
        if _len > 0:
            # we can only assume that the values are consecutive integers
            # so the limits correspond to the keys
            limits = (1, _len)
            self.set_limits(limits)
        else:
            # Normally we get the limits from the hardware
            limits = (1, 10)
            self.set_limits(limits)
            # there is nothing in the xml file,
            # create ValueEnum from the limits
            self._initialise_values()

        self.update_limits(limits)
        current_value = self.get_value()
        self.update_value(current_value)
        self.update_state(self.STATES.READY)

    def set_limits(self, limits: Tuple[float, float]) -> None:
        """
        Set the low and high limits.

        Parameters
        ----------
        limits : tuple
            two element (low limit, high limit) tuple.

        Returns
        -------
        None
        """
        self._nominal_limits = limits

    def update_limits(self, limits: Tuple[float, float]) -> None:
        """
        Emits signal limitsChanged.

        Parameters
        ----------
        limits : Tuple[float, float]
            Two elements tuple (low limit, high limit)

        Returns
        -------
        None
        """
        self._nominal_limits = limits
        self.emit("limitsChanged", (limits,))

    def _move(self, value: Enum) -> Enum:
        """
        Moves a motor to `value`

        Parameters
        ----------
        value : Enum
            New value of a motor
        """
        self.update_state(self.STATES.BUSY)
        time.sleep(0.2)
        self.update_state(self.STATES.READY)

        current_value = self.get_value()
        self.update_value(current_value)
        logging.getLogger("HWR").debug(
            f"Moving motorized zoom lens to: {current_value}"
        )
        return value

    def get_value(self) -> Enum:
        """
        Reads the value of a motor

        Returns
        -------
        current_enum : Enum
            The current value of a motor
        """
        current_val = self.motor.user_readback.get()
        current_enum = self.value_to_enum(current_val)
        return current_enum

    def _set_value(self, value: Enum) -> None:
        """
        Sets a new motor value

        Parameters
        ----------
        value : Enum
            New value

        Returns
        -------
        None
        """
        target_val = value.value

        self.motor.user_setpoint.put(target_val, wait=False)
        self.update_value(target_val)
        self.update_state(self.STATES.READY)

    def update_value(self, value: Enum = None) -> Enum:
        """
        Checks if the value has changed. Emits signal `valueChanged`.

        Parameters
        ----------
        value : Enum
            New value
        """

        if value is None:
            value = self.get_value()

        if self._nominal_value is None:
            if value is None:
                return
        self.emit("valueChanged", (value,))
