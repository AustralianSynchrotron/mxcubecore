import gevent
from mx3_beamline_library.devices.beam import ring_current

from mxcubecore import HardwareRepository as HWR
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractMachineInfo import AbstractMachineInfo


class MachineInfo(AbstractMachineInfo):
    def init(self):
        super().init()

        if settings.BL_ACTIVE:
            # The following channels is used to poll ring_current PV
            self.ring_current_channel = self.add_channel(
                {
                    "type": "epics",
                    "name": "ring_current",
                    "polling": 1000,  # milliseconds
                },
                ring_current.pvname,
            )
            self.ring_current_channel.connect_signal("update", self._value_changed)

    def _value_changed(self, value: float | None) -> None:
        """Emits a valueChanged signal. Used by self.ring_current_channel

        Parameters
        ----------
        value : float | None
            The ring current value
        """
        self._value = value
        self.emit("valueChanged", self._value)

    def get_current(self) -> float:
        """Gets the ring current"""
        return ring_current.get()
