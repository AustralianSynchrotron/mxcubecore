import pytest
import os
import typing
import pytest
from gevent import monkey

monkey.patch_all(thread=False)


if typing.TYPE_CHECKING:
    from mxcubecore.HardwareObjects.Beamline import Beamline

from mxcubecore import HardwareRepository as HWR

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))

@pytest.fixture(scope="class")
def beamline() -> "Beamline":
    """ """

    # Import beamline library with sim devices enabled
    os.environ["BL_ACTIVE"] = "false"

    from mx3_beamline_library.devices import motors, detectors

    # Check beamline library was initialised with sim devices enabled
    from mx3_beamline_library.devices.sim import motors as sim_motors, detectors as sim_detectors
    assert motors == sim_motors
    assert detectors == sim_detectors

    # Initialise hardware objects
    hwr_path = os.path.join(ROOT_DIR, "mxcubecore/configuration/ansto")
    HWR._instance = HWR.beamline = None
    HWR.init_hardware_repository(hwr_path)
    hwr = HWR.get_hardware_repository()
    hwr.connect()
    return HWR.beamline
