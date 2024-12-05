import time

from mx3_beamline_library.devices.optics import energy_master

from mxcubecore.HardwareObjects.abstract.AbstractEnergy import AbstractEnergy
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Energy(EPICSActuator, AbstractEnergy):
    """
    Sets and gets the energy and wavelength of the beam, while
    checking if the energy threshold is okay.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. `/energy`

        Returns
        -------
        None
        """
        super().__init__(name)

    def init(self) -> None:
        """
        Initialise default properties

        Returns
        -------
        None
        """
        super(Energy, self).init()

        self.energy = energy_master

        self.update_state(self.STATES.READY)
        self.detector = self.get_object_by_role("detector")  # Maybe this is not needed

    def set_value(self, value: float) -> None:
        """
        Sets the beam energy

        Parameters
        ----------
        value : float
            Target value [keV]

        Returns
        -------
        None
        """
        self.update_state(self.STATES.BUSY)

        self.energy.set(value)

        self.update_value(value)
        self.update_state(self.STATES.READY)

    def get_limits(self):
        return (5, 20)  # Hardcoded for now

    def get_value(self) -> float:
        """
        Read the energy.

        Returns
        -------
        value : float
            Actuator position.
        """
        value = self.energy.get()

        return value

    def _move(self, value: float):
        """
        Updates the mxcube UI to show that energy is changing

        Parameters
        ----------
        value : float
            The target value in keV

        Returns
        -------
        _type_
            _description_
        """

        while round(energy_master.get(), 2) != round(value, 2):
            time.sleep(0.2)
            self.update_state(self.STATES.BUSY)
            current_value = self.get_value()
            self.update_value(current_value)

        self.update_state(self.STATES.READY)
        return value
