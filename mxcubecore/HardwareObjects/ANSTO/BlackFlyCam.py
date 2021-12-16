from ophyd.areadetector.base import EpicsSignalWithRBV, ADComponent as ADCpt
from ophyd.areadetector.cam import CamBase
from ophyd.signal import EpicsSignalRO


class BlackFlyCam(CamBase):
    """
    Attributes
    ----------
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
    acquire_time_rbv = ADCpt(EpicsSignalRO, "AcquireTime_RBV")
    gain_rbv = ADCpt(EpicsSignalRO, "Gain_RBV")
    gain_atuo = ADCpt(EpicsSignalWithRBV, "GainAuto")
    gain_atuo_rbv = ADCpt(EpicsSignalRO, "GainAuto_RBV")
    frame_rate = ADCpt(EpicsSignalWithRBV, 'FrameRate')
