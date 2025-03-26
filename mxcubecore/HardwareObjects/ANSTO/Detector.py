import ast
from typing import Literal
from urllib.parse import urljoin

from httpx import Client

from mxcubecore.BaseHardwareObjects import HardwareObjectState
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.abstract.AbstractDetector import AbstractDetector


class Detector(AbstractDetector):
    """
    Descript. : Detector class. Contains all information about detector
                the states are 'OK', and 'BAD'
                the status is busy, exposing, ready, etc.
                the physical property is RH for pilatus, P for rayonix
    """

    def __init__(self, name):
        """
        Descript. :
        """
        AbstractDetector.__init__(self, name)
        self._state = HardwareObjectState.READY
        self.simplon_state_to_hw_obj_state = {
            "error": HardwareObjectState.FAULT,
            "ready": HardwareObjectState.READY,
            "idle": HardwareObjectState.READY,
            "initialize": HardwareObjectState.BUSY,
            "na": HardwareObjectState.BUSY,
            "configure": HardwareObjectState.BUSY,
            "acquire": HardwareObjectState.BUSY,
            "test": HardwareObjectState.BUSY,
        }

    def init(self):
        """
        Descript. :
        """
        AbstractDetector.init(self)

        self._temperature = None
        self._humidity = None
        self._actual_frame_rate = None
        self._roi_modes_list = eval(self.get_property("roi_mode_list", '["4M", "16M"]'))
        self._roi_mode = self._get_detector_config("roi_mode")
        self._exposure_time_limits = eval(
            self.get_property("exposure_time_limits", "[0.04, 60000]")
        )

        state = self.get_state()
        self.update_state(state)

        self._beam_centre = (
            self._get_detector_config("beam_center_x"),
            self._get_detector_config("beam_center_y"),
        )

        if self._beam_centre == (0, 0):
            raise ValueError(
                "The beam centre has not been set via the SIMPLON API. "
                "Ensure 'beam_center_x' and 'beam_center_y' are different from zero"
            )
        self._distance_motor_hwobj = self.get_object_by_role("detector_distance")

        self._roi_modes_list = ast.literal_eval(self.get_property("roiModes", "()"))

        self._pixel_size = (
            self._get_detector_config("x_pixel_size") * 1000,  # mm
            self._get_detector_config("y_pixel_size") * 1000,  # mm
        )
        self._width = self._get_detector_config("x_pixels_in_detector")
        self._height = self._get_detector_config("y_pixels_in_detector")

        # Polls the detector's state from the SIMPLON API every 2 seconds
        self.state = self.add_channel(
            {
                "type": "rest_api",
                "name": "state",
                "polling": 2000,
            },
            urljoin(settings.SIMPLON_API, "/detector/api/1.8.0/status/state"),
        )
        self.state.connect_signal("update", self._update_state)

    def _update_state(
        self,
        value: Literal[
            "error", "ready", "idle", "initialize", "na", "configure", "acquire", "test"
        ],
    ) -> None:
        """
        Updates the detector state. Used by the self.state poller and is only called
        if the state of the detector has changed

        Parameters
        ----------
        value : Literal["error", "ready", "idle", "initialize", "na", "configure", "acquire", "test"]
            The detector state

        Returns
        -------
        None
        """
        self.update_state(self.simplon_state_to_hw_obj_state.get(value))

    def _get_detector_config(self, parameter):
        with Client() as client:
            response = client.get(
                urljoin(settings.SIMPLON_API, f"/detector/api/1.8.0/config/{parameter}")
            )
            response.raise_for_status()

        return response.json()["value"]

    def get_state(self) -> HardwareObjectState:
        try:
            with Client() as client:
                response = client.get(
                    urljoin(settings.SIMPLON_API, "/detector/api/1.8.0/status/state")
                )
            if response.status_code != 200:
                return HardwareObjectState.FAULT

            state = response.json()["value"]

        except Exception:
            return HardwareObjectState.FAULT

        busy_list = ["initialize", "configure", "acquire"]

        if state in busy_list:
            self._state = HardwareObjectState.BUSY
        elif state == "error":
            self._state = HardwareObjectState.FAULT
        elif state in ["na", "test"]:
            self._state = HardwareObjectState.UNKNOWN
        elif state in ["ready", "idle"]:
            self._state = HardwareObjectState.READY
        return self._state

    def has_shutterless(self):
        """Returns always True"""
        return True

    def prepare_acquisition(self, *args, **kwargs):
        """
        Prepares detector for acquisition
        """
        return

    def start_acquisition(self):
        """
        Starts acquisition
        """
        return

    def restart(self) -> None:
        return

    def get_beam_position(self, distance=None, wavelength=None):
        """Calculate the beam position for a given distance.
        Args:
            distance (float): detector distance [mm]
            wavelength (float): X-ray wavelength [Å]
        Returns:
            tuple(float, float): Beam position x,y coordinates [pixel].
        """

        return self._beam_centre

    def get_width(self):
        return self._get_detector_config("x_pixels_in_detector")

    def get_height(self):
        return self._get_detector_config("y_pixels_in_detector")
