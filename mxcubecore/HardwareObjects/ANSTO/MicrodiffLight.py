import logging
import math

from mxcubecore.BaseHardwareObjects import HardwareObjectState

from .ExporterMotor import ExporterMotor


class MicrodiffLight(ExporterMotor):
    """
    MicrodiffLight class. This class is used to control
    the backlight and frontlight of the MD3
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name: str
            The name of the hardware object

        Returns
        -------
        None
        """
        ExporterMotor.__init__(self, name)

    def init(self) -> None:
        """
        Object initialisation - executed after loading contents.

        Returns
        -------
        None
        """
        ExporterMotor.init(self)
        try:
            _low, _high = self.get_property("limits").split(",")
            self._limits = (int(_low), int(_high))
        except (AttributeError, TypeError, ValueError):
            self._limits = (0, 10)
        self.chan_light_is_on = self.get_channel_object("chanLightIsOn")
        self.update_state(self.STATES.READY)

    def _set_value(self, value: float) -> None:
        """
        Moves the motor to the absolute value

        Parameters
        ----------
        value : float
            The target value

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)
        self.motor_position_chan.set_value(round(value, 1))
        self.update_state(self.STATES.READY)

    def get_value(self) -> float:
        """
        Gets the motor position.

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

    def get_state(self) -> HardwareObjectState:
        """
        Get the light state as a motor

        Returns
        -------
        HardwareObjectState
            The state of the hardware object
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
