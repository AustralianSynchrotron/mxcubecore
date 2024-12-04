import time

from mx3_beamline_library.devices.motors import actual_sample_detector_distance, detector_fast_stage

from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class DetectorDistance(AbstractMotor, EPICSActuator):
    """Hardware Object that uses an Ophyd layer to control Epics motors

    Example of xml config file:

    <device class="ANSTO.OphydMotor">
        <username>PhiX</username>
        <motor_name>Motor X</motor_name>
        <pv_prefix>MX3:TESTRIG_X</pv_prefix>
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
        self.update_specific_state(self.SPECIFIC_STATES.MOVING)

        while detector_fast_stage.moving:
            time.sleep(0.2)
            self.update_state(self.STATES.BUSY)
            current_value = self.get_value()
            self.update_value(current_value)

        self.update_state(self.STATES.READY)
        return value

    def abort(self) -> None:
        """Stop the motor and update the new position of the motor.

        Returns
        -------
        None
        """
        detector_fast_stage.stop(success=True)
        self._set_value(self.get_value())
        self.update_state(self.STATES.READY)

    def get_limits(self) -> tuple:
        """Get the limits of a motor.

        Returns
        -------
        tuple
            Low and High limits of a motor.
        """
        self._nominal_limits = (0,2000) # Hardcoded for now
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
        return actual_sample_detector_distance.get()

    def _set_value(self, value: float) -> None:
        """Set the motor to a positions

        Parameters
        ----------
        value : float
            Position of the motor.

        Returns
        -------
        None
        """
        actual_distance = actual_sample_detector_distance.get()
        actual_detector_distance_setpoint = value 
        diff = actual_detector_distance_setpoint - actual_distance
        current_fast_stage_val = detector_fast_stage.position

        fast_stage_setpoint = current_fast_stage_val + diff
        detector_fast_stage.move(fast_stage_setpoint, wait=False)

        self.update_value(value)
        self.update_state(self.STATES.READY)
