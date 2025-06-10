import time

from mx3_beamline_library.devices.cryo import cryo_temperature

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractMotor import AbstractMotor
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Cryo(AbstractMotor, EPICSActuator):
    """Hardware Object that uses an Ophyd layer to control Epics motors

    Example of xml config file:

    <object class ="ANSTO.Cryo">
        <username>Cryo</username>
        <read_only>True</read_only>
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

        self.update_state(self.STATES.READY)

        if settings.BL_ACTIVE:
            # The following channel is used to poll the cryo temperature PV value
            self.cryo_temperature_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "cryo_temperature",
                    "polling": 1000,  # milliseconds
                },
                cryo_temperature.pvname,
            )
            self.cryo_temperature_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used by self.cryo_temperature_channel

        Parameters
        ----------
        value : float | None
            The energy value
        """
        self._value = value
        self.emit("valueChanged", self._value)

    def get_value(self) -> float:
        """Get the current position of the motor.

        Returns
        -------
        float
            Position of the motor.
        """
        return cryo_temperature.get()

    def _set_value(self, value: float) -> None:
        """Sets the new temperature

        Parameters
        ----------
        value : float
            Position of the motor.

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)
        cryo_temperature.set(value)

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

        while round(cryo_temperature.get(), 1) != round(value, 1):
            time.sleep(0.2)
            self.update_value(self.get_value())

        self.update_state(self.STATES.READY)
        self.update_value(self.get_value())
        return value
