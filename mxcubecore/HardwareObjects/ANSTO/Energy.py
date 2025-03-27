import time

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractEnergy import AbstractEnergy
from mxcubecore.HardwareObjects.ANSTO.EPICSActuator import EPICSActuator


class Energy(EPICSActuator, AbstractEnergy):
    """
    Sets and gets the energy and wavelength of the beam

    Example of xml config file:

    <object class="ANSTO.Energy">
        <username>energy</username>
    </object>
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

        if settings.BL_ACTIVE:
            # The following channel is used to poll the energy PV value
            self.energy_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "energy",
                    "polling": 1000,  # milliseconds
                },
                self.energy.pvname,
            )
            self.energy_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used by self.energy_channel

        Parameters
        ----------
        value : float | None
            The energy value
        """
        self._value = value
        self.emit("valueChanged", self._value)

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
        return (5, 20)  # TODO: Get the real limits

    def get_value(self) -> float:
        """
        Read the energy in keV

        Returns
        -------
        value : float
            Actuator position.
        """
        value = self.energy.get()

        return value

    def _move(self, value: float) -> float:
        """
        Updates the mxcube UI to show that energy is changing

        Parameters
        ----------
        value : float
            The target value in keV

        Returns
        -------
        float
            The energy value in keV
        """

        while round(energy_master.get(), 2) != round(value, 2):
            time.sleep(0.2)
            self.update_state(self.STATES.BUSY)
            current_value = self.get_value()
            self.update_value(current_value)

        self.update_state(self.STATES.READY)
        return value
