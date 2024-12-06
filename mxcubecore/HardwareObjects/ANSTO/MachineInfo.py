import gevent
from mx3_beamline_library.devices.optics import ring_current

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractMachineInfo import AbstractMachineInfo


class MachineInfo(AbstractMachineInfo):
    def init(self):
        super().init()

    def get_current(self) -> float:
        """Gets the ring current"""
        return ring_current.get()
