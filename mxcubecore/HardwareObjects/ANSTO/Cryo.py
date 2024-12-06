import time

from mx3_beamline_library.devices.cryo import cryo_temperature

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


    def get_value(self) -> float:
        """Get the current position of the motor.

        Returns
        -------
        float
            Position of the motor.
        """
        return cryo_temperature.get()

