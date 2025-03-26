import logging
import time

from mx3_beamline_library.devices.motors import (
    actual_sample_detector_distance,
    detector_fast_stage,
)

from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class DetectorDistance(AbstractMotor, EPICSActuator):
    """Hardware Object that uses an Ophyd layer to control
    the detector distance.

    Example of xml config file:

    <device class="ANSTO.DetectorDistance">
        <username>Detector distance</username>
        <GUIstep>0.1</GUIstep>
        <unit>1e-1</unit>
    </device>
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

        self.distance_channel = self.add_channel(
            {
                "type": "epics",
                "name": "distance",
                "polling": 1000, # milliseconds
            },
            #transmission.pvname,
            "my_pv:distance" # TODO
        )
        self.distance_channel.connect_signal("update", self._value_changed)

        self.distance_is_moving_channel = self.add_channel(
            {
                "type": "epics",
                "name": "distance_is_moving",
                "polling": 1000, # milliseconds
            },
            #transmission.pvname,
            "my_pv:distance_is_moving" # TODO
        )
        self.distance_is_moving_channel.connect_signal("update", self._state_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used by self.transmission_channel

        Parameters
        ----------
        value : float | None
            The transmission value
        """
        self._value = value
        #if value is not None:
        self.emit("valueChanged", self._value)


    def _state_changed(
        self,
        value: bool,
    ) -> None:
        """Updates the state of the transmission hardware object. Used by
        self.filter_wheel_is_moving_channel

        Parameters
        ----------
        value : bool
            Wether the filter wheel is moving or not
        """
        if value:
            self.update_state(self.STATES.BUSY)
            self.update_specific_state(self.SPECIFIC_STATES.MOVING)
        else:
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
        self.update_state(self.STATES.BUSY)
        self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        while detector_fast_stage.moving:
            time.sleep(0.2)
            self.update_value(self.get_value())

        self.update_state(self.STATES.READY)
        self.update_value(self.get_value())
        return value

    def abort(self) -> None:
        """Stop the motor and update the new position of the motor.

        Returns
        -------
        None
        """
        detector_fast_stage.stop(success=True)

    def get_limits(self) -> tuple:
        """Get the limits of a motor.

        Returns
        -------
        tuple
            Low and High limits of a motor.
        """
        self._nominal_limits = (1, 2000)  # TODO: Need to get the actual limits
        return self._nominal_limits

    @property
    def velocity(self) -> float:
        """Get the velocity of the motor.

        Returns
        -------
        float
            Velocity of the motor
        """
        self._velocity = detector_fast_stage.velocity.get()
        return self._velocity

    @velocity.setter
    def velocity(self, value: float) -> None:
        """Set the velocity of the motor.

        Parameters
        ----------
        value : float
            Velocity of the motor

        Returns
        -------
        None
        """
        detector_fast_stage.velocity.put(value)

    def get_value(self) -> float:
        """Get the current position of the motor.

        Returns
        -------
        float
            Position of the motor.
        """
        #return actual_sample_detector_distance.get()
        from epics import caget
        return caget("my_pv:distance")
    def _set_value(self, value: float) -> None:
        """Sets the detector distance

        Parameters
        ----------
        value : float
            Position of the motor.

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)
        try:
            actual_distance = actual_sample_detector_distance.get()
            actual_detector_distance_setpoint = value
            diff = actual_detector_distance_setpoint - actual_distance
            current_fast_stage_val = detector_fast_stage.position

            fast_stage_setpoint = current_fast_stage_val + diff
            detector_fast_stage.move(fast_stage_setpoint, wait=False)
            self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        except Exception:
            logging.getLogger("user_level_log").error(
                f"Failed to change detector distance"
            )
