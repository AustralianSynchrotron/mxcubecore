import logging
import time

from mx3_beamline_library.devices.beam import (
    filter_wheel_is_moving,
    transmission,
)

from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Transmission(AbstractMotor, EPICSActuator):
    """Hardware Object that uses an Ophyd layer to the Transmission.

    Example of xml config file:

    <object class = "ANSTO.Transmission">
    <username>transmission</username>
    </object>
    """

    def __init__(self, name: str) -> None:
        """Constructor to instantiate OphydEpicsMotor class and it's features.

        Parameters
        ----------
        name : str
            Human readable name of the motor.

        Returns
        -------
        None
        """
        AbstractMotor.__init__(self, name)
        EPICSActuator.__init__(self, name)

        self._wrap_range = None

    def init(self) -> None:
        """Object initialization - executed after loading contents

        Returns
        -------
        None
        """
        AbstractMotor.init(self)
        EPICSActuator.init(self)

        self.get_limits()
        self.get_velocity()
        self.update_state(self.STATES.READY)

    def _move(self, value: float) -> float:
        """Move the motor to a given value.

        Parameters
        ----------
        value : float
            Position of the motor.

        Returns
        -------
        float
            New position of the motor.
        """
        # TODO: Verify with real data
        self.update_state(self.STATES.BUSY)
        self.update_specific_state(self.SPECIFIC_STATES.MOVING)
        while filter_wheel_is_moving.get():
            time.sleep(0.1)
            self.update_value(self.get_value())

        self.update_state(self.STATES.READY)
        self.update_value(self.get_value())
        return value

    def get_limits(self) -> tuple:
        """Get the limits of a motor.

        Returns
        -------
        tuple
            Low and High limits of a motor.
        """
        self._nominal_limits = (0, 100)
        return self._nominal_limits

    def get_value(self) -> float:
        """Get the current position of the motor.

        Returns
        -------
        float
            The transmission value in percentage
        """
        return transmission.get() * 100  # convert to percentage

    def _set_value(self, value: float) -> None:
        """Set the transmission to a given value.

        Parameters
        ----------
        value : float
            The transmission value in percentage

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)
        try:
            transmission.set(value / 100)
            self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        except Exception:
            logging.getLogger("user_level_log").error("Failed to change transmission")

    def abort(self) -> None:
        """Stop the motor and update the new position of the motor.

        Returns
        -------
        None
        """
        pass
