import logging
from ophyd import EpicsSignal

from mxcubecore.HardwareObjects.abstract.AbstractEnergy import (
    AbstractEnergy)
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Energy(EPICSActuator, AbstractEnergy):
    """Energy class"""

    def init(self):
        """Initialise default properties"""
        super(Energy, self).init()

        self.energy = EpicsSignal(self.pv_prefix, name=self.energy_name)
        self.energy.wait_for_connection(timeout=5)

        self.update_state(self.STATES.READY)
        self.detector = self.get_object_by_role("detector")

    def set_value(self, value):
        """Override method."""
        # TODO check if set value is allowed
        # with check_threshold_energy(value)
        self.update_state(self.STATES.BUSY)

        self.energy.set(value)

        self.update_value(value)
        self.update_state(self.STATES.READY)

    def get_value(self):
        """Read the actuator position.
        Returns:
            float: Actuator position.
        """
        value = self.energy.get()

        threshold_ok = self.check_threshold_energy(value)
        if threshold_ok:
            self._nominal_value = value
        else:
            value = None  # Invalid energy because threshold is invalid

        return value

    def check_threshold_energy(self, energy):
        """ Returns whether detector threshold energy is valid or not."""
        # TODO: We have to define the set_threshold_energy() function
        # in the detector class
        # threshold_ok = self.detector.set_threshold_energy(energy)
        threshold_ok = energy

        if threshold_ok:
            logging.getLogger("HWR").info("Pilatus threshold is okay.")
            return True

        logging.getLogger("HWR").error("Pilatus threshold is not okay.")
        return False
