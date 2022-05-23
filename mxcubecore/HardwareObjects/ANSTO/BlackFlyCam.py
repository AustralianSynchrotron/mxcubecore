from ophyd import Component as Cpt, Device
from ophyd.signal import EpicsSignalRO


class BlackFlyCam(Device):
    """Ophyd has the following order:
    width, height, depth = ArraySize0_RBV, ArraySize1_RBV, ArraySize2_RBV

    but MXCube has a different format
    depth, width, height = ArraySize0_RBV, ArraySize1_RBV, ArraySize2_RBV

    This class was created to re-order and make ophyd compatible with MXCube.

    Attributes
    ----------
    depth: float
           Depth of the camera image
    width: float
           Width of the camera image
    height: float
           Height of the camera image
    acquire_time_rbv: int
        Acquire time of the camera image. Read-only
    gain_rbv: float
              Gain of the camera
    gain_auto: float
               Auto-gain of the camera
    gain_auto_rb: float
                  Auto-gain of the camera. Read-only.
    frame_rate: int
                Frame rate of the camera images.
    """

    depth = Cpt(EpicsSignalRO, ":image1:ArraySize0_RBV")
    width = Cpt(EpicsSignalRO, ":image1:ArraySize1_RBV")
    height = Cpt(EpicsSignalRO, ":image1:ArraySize2_RBV")
    array_data = Cpt(EpicsSignalRO, ":image1:ArrayData")

    acquire_time_rbv = Cpt(EpicsSignalRO, ":cam1:AcquireTime_RBV")
    gain_rbv = Cpt(EpicsSignalRO, ":cam1:Gain_RBV")
    gain_auto = Cpt(EpicsSignalRO, ":cam1:GainAuto")
    gain_auto_rbv = Cpt(EpicsSignalRO, ":cam1:GainAuto_RBV")
    frame_rate = Cpt(EpicsSignalRO, ":cam1:FrameRate")
