from ophyd.areadetector.plugins import ImagePlugin_V34
from ophyd.areadetector.base import Component as Cpt
from ophyd.signal import EpicsSignalRO


class ImgPlugin(ImagePlugin_V34):
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
    """
    depth = Cpt(EpicsSignalRO, "ArraySize0_RBV")
    width = Cpt(EpicsSignalRO, "ArraySize1_RBV")
    height = Cpt(EpicsSignalRO, "ArraySize2_RBV")
