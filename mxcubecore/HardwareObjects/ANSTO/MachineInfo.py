
import time

import gevent

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.abstract.AbstractMachineInfo import AbstractMachineInfo
from mx3_beamline_library.devices.optics import ring_current


class MachineInfo(AbstractMachineInfo):
    def init(self):
        super().init()

    def get_current(self) -> float:
        """Gets the ring current"""
        return ring_current.get()
