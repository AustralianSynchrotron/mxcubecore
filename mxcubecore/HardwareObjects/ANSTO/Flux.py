from mx3_beamline_library.devices.beam import flux

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
            self.flux_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "flux",
                    "polling": 2000,  # milliseconds
                },
                flux.pvname,
            )
            self.flux_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used to poll the flux PV.

        Parameters
        ----------
        value : float | None
            The flux value
        """
        self._value = value
        self.emit("valueChanged", self._value)

    def get_value(self) -> float:
        """
        Get flux in units of photons/s

        Returns
        -------
        float
            The flux in units of photons/s
        """
        return flux.get()
