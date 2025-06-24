from mx3_beamline_library.devices.beam import flux

from mxcubecore import HardwareRepository as HWR
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractFlux import AbstractFlux


class Flux(AbstractFlux):
    """Flux class"""

    def __init__(self, name):
        super().__init__(name)

    def init(self):
        super().init()

        if settings.BL_ACTIVE:
            # The following channel is used to poll the flux PV value
            self.energy_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "flux",
                    "polling": 2000,  # milliseconds
                },
                flux.pvname,
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

    def get_value(self):
        """Get flux in units of photons/s"""
        return flux.get()
