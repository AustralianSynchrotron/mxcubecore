import logging
from ophyd import EpicsSignal

from mxcubecore.HardwareObjects.abstract.AbstractEnergy import (
    AbstractEnergy)
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Energy(EPICSActuator, AbstractEnergy):
    """
    Sets and gets the energy and wavelenght of the beam, while
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

        self.energy = EpicsSignal(self.pv_prefix, name=self.energy_name)
        self.energy.wait_for_connection(timeout=5)

        self.update_state(self.STATES.READY)
        self.detector = self.get_object_by_role("detector")

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
        # TODO check if set_value is allowed
        # with check_threshold_energy(value)
        self.update_state(self.STATES.BUSY)

        self.energy.set(value)

        self.update_value(value)
        self.update_state(self.STATES.READY)

    def set_wavelength(self, value: float) -> None:
        """
        Set the wavelenght of the beam.

        Parameters
        ----------
        value : float
            Target position [keV]
        """
        self.set_value(self._calculate_energy(value))

    def get_value(self) -> float:
        """
        Read the actuator position.

        Returns
        -------
        value : float
            Actuator position.
        """
        value = self.energy.get()

        threshold_ok = self.check_threshold_energy(value)
        if threshold_ok:
            self._nominal_value = value
        else:
            value = None  # Invalid energy because threshold is invalid

        return value

    def check_threshold_energy(self, energy: float) -> bool:
        """
        Returns whether detector threshold energy is valid or not.

        Parameters
        ----------
        energy : float
            Energy value

        Returns
        -------
        bool
            If the detector energy is valid or not
        """
        # TODO: We have to define the set_threshold_energy() function
        # in the detector class. This function is not implemented yet, e.g.:
        # threshold_ok = self.detector.set_threshold_energy(energy)
        threshold_ok = energy

        if threshold_ok:
            logging.getLogger("HWR").info("Pilatus threshold is okay.")
            return True

        logging.getLogger("HWR").error("Pilatus threshold is not okay.")
        return False
