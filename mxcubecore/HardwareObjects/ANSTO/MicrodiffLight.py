from .ExporterMotor import ExporterMotor
import logging
import math

class MicrodiffLight(ExporterMotor):
    def __init__(self, name):
        ExporterMotor.__init__(self, name)

    def init(self):
        ExporterMotor.init(self)
        try:
            _low, _high = self.get_property("limits").split(",")
            self._limits = (int(_low), int(_high))
        except (AttributeError, TypeError, ValueError):
            self._limits = (0, 10)
        self.chan_light_is_on = self.get_channel_object("chanLightIsOn")
        self.update_state(self.STATES.READY)

    def get_state(self):
        """Get the light state as a motor.
        Returns:
            (enum 'HardwareObjectState'): Light state.
        """
        return self._state

    def get_limits(self):
        return self._limits

    def light_is_out(self):
        return self.chan_light_is_on.get_value()

    def move_in(self):
        self.chan_light_is_on.set_value(True)

    def move_out(self):
        self.chan_light_is_on.set_value(False)

    def _set_value(self, value: float):
        """Move motor to absolute value.
        Args:
            value (float): target value
        """
        self.update_state(self.STATES.BUSY)
        self.motor_position_chan.set_value(round(value,1))
        self.update_state(self.STATES.READY)

    def get_value(self) -> float:
        """Gets the motor position.

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
        return  self._nominal_value