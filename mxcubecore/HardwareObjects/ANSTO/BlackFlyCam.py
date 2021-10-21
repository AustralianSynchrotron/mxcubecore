from ophyd.areadetector.base import EpicsSignalWithRBV, ADComponent as ADCpt
from ophyd.areadetector.cam import CamBase
from ophyd.signal import EpicsSignalRO


class BlackFlyCam(CamBase):
    acquire_time_rbv = ADCpt(EpicsSignalRO, "AcquireTime_RBV")
    gain_rbv = ADCpt(EpicsSignalRO, "Gain_RBV")
    gain_atuo = ADCpt(EpicsSignalWithRBV, "GainAuto")
    gain_atuo_rbv = ADCpt(EpicsSignalRO, "GainAuto_RBV")
    frame_rate = ADCpt(EpicsSignalWithRBV, 'FrameRate')
