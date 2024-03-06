#
#  Project: MXCuBE
#  https://github.com/mxcube
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Lesser General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Lesser General Public License for more details.
#
#   You should have received a copy of the GNU Lesser General Public License
#  along with MXCuBE. If not, see <http://www.gnu.org/licenses/>.

import time
import logging
import random
import warnings
from typing import Tuple

from pydantic import ValidationError
from mxcubecore.BaseHardwareObjects import HardwareObjectState

from mxcubecore.HardwareObjects.GenericDiffractometer import (
    GenericDiffractometer,
    PhaseEnum,
)

from mxcubecore import HardwareRepository as HWR
from gevent.event import AsyncResult
from scipy import optimize
import numpy as np
import numpy.typing as npt
import ast
import gevent

EXPORTER_TO_HWOBJ_STATE = {
    "Fault": HardwareObjectState.FAULT,
    "Ready": HardwareObjectState.READY,
    "Moving": HardwareObjectState.BUSY,
    "Busy": HardwareObjectState.BUSY,
    "Unknown": HardwareObjectState.BUSY,
    "Offline": HardwareObjectState.OFF,
}
from os import getenv

class Diffractometer(GenericDiffractometer):
    """
    Descript. :
    """

    def __init__(self, *args) -> None:
        GenericDiffractometer.__init__(self, *args)
        self.exporter_addr = getenv("EXPORTER_ADDRESS", "12.345.678.10:1234")

    def init(self):
        """
        Descript. :
        """
        # self.image_width = 100
        # self.image_height = 100

        GenericDiffractometer.init(self)
        self.last_centred_position = [612, 512]
        self.beam_position = [612, 512]

        self.current_phase = GenericDiffractometer.PHASE_CENTRING

        self.cancel_centring_methods = {}

        self.current_state_dict = {}
        self.centring_status = {"valid": False}
        self.centring_time = 0

        if "zoom" not in self.motor_hwobj_dict.keys():
            self.motor_hwobj_dict["zoom"] = self.get_object_by_role("zoom")
        if "focus" not in self.motor_hwobj_dict.keys():
            self.motor_hwobj_dict["focus"] = self.get_object_by_role("focus")

        calibration_x = self.motor_hwobj_dict["zoom"].get_property("pixels_per_mm_x")
        calibration_y = self.motor_hwobj_dict["zoom"].get_property("pixels_per_mm_y")
        self.zoom_calibration_x = ast.literal_eval(calibration_x)
        self.zoom_calibration_y = ast.literal_eval(calibration_y)

        self.get_zoom_calibration()

        self.mount_mode = self.get_property("sample_mount_mode")
        if self.mount_mode is None:
            self.mount_mode = "manual"

        self.equipment_ready()

        self.connect(self.motor_hwobj_dict["phi"], "valueChanged", self.phi_motor_moved)
        self.connect(
            self.motor_hwobj_dict["phiy"], "valueChanged", self.phiy_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["phiz"], "valueChanged", self.phiz_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["kappa"], "valueChanged", self.kappa_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["kappa_phi"],
            "valueChanged",
            self.kappa_phi_motor_moved,
        )
        self.connect(
            self.motor_hwobj_dict["sampx"], "valueChanged", self.sampx_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["sampy"], "valueChanged", self.sampy_motor_moved
        )

        self.movePhase = self.add_command(
            {
                "type": "exporter",
                "exporter_address": self.exporter_addr,
                "name": "move_to_phase",
            },
            "startSetPhase",
        )

        self.hwstate_attr = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self.exporter_addr,
                "name": "hwstate",
            },
            "HardwareState",
        )

        self.swstate_attr = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self.exporter_addr,
                "name": "swstate",
            },
            "State",
        )
        self.readPhase = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self.exporter_addr,
                "name": "read_phase",
            },
            "CurrentPhase",
        )
        self.state = self.add_channel(
            {
                "type": "exporter",
                "exporter_address": self.exporter_addr,
                "name": "state",
            },
            "State",
        )
        self.readPhase.connect_signal("update", self._update_phase_value)
        self.state.connect_signal("update", self._update_state)

    def _update_phase_value(self, value=None):
        if value is None:
            value = self.get_current_phase()
        self.emit("phaseChanged", (value))

    def _update_state(self, value):
        self.update_state(
            EXPORTER_TO_HWOBJ_STATE.get(value, HardwareObjectState.UNKNOWN)
        )

    def get_current_phase(self):
        return self.readPhase.get_value()

    def execute_server_task(self, method, timeout=30, *args):
        return

    def in_plate_mode(self):
        return self.mount_mode == "plate"

    def use_sample_changer(self):
        return self.mount_mode == "sample_changer"

    def is_reversing_rotation(self):
        return True

    def get_grid_direction(self):
        """
        Descript. :
        """
        return self.grid_direction

    def manual_centring(self) -> dict:
        """
        3-click centring procedure. This code is based on the sample_centering code
        located in the HardwareObjects folder in the mxcubecore github page.

        Returns
        -------
        centred_pos_dir: dict
            centred position
        """
        X, Y, phi_positions = [], [], []
        self.get_zoom_calibration()

        for click in range(3):
            self.user_clicked_event = AsyncResult()
            x, y = self.user_clicked_event.get()

            X.append(x / float(self.pixels_per_mm_x))
            Y.append(y / float(self.pixels_per_mm_y))
            phi_positions.append(np.radians(self.motor_hwobj_dict["phi"].get_value()))
            if click < 2:
                self.motor_hwobj_dict["phi"].set_value_relative(90)

        chi_angle = np.radians(90)
        chiRotMatrix = np.matrix(
            [
                [np.cos(chi_angle), -np.sin(chi_angle)],
                [np.sin(chi_angle), np.cos(chi_angle)],
            ]
        )
        Z = chiRotMatrix * np.matrix([X, Y])
        z = Z[1]
        avg_pos = Z[0].mean()

        r, a, offset = self.multiPointCentre(np.array(z).flatten(), phi_positions)
        dy = r * np.sin(a)
        dx = r * np.cos(a)

        d = chiRotMatrix.transpose() * np.matrix([[avg_pos], [offset]])

        d_horizontal = d[0] - (self.beam_position[0] / self.pixels_per_mm_x)
        d_vertical = d[1] - (self.beam_position[1] / self.pixels_per_mm_y)

        centered_position = {
            "sampx": self.motor_hwobj_dict["sampx"].get_value() + dx,
            "sampy": self.motor_hwobj_dict["sampy"].get_value() + dy,
            "phiy": self.motor_hwobj_dict["phiy"].get_value() + d_vertical[0, 0],
            "phiz": self.motor_hwobj_dict["phiz"].get_value() - d_horizontal[0, 0],
            "phix": 0.434,  # This is the focused position of the MD3
        }

        self.move_motors(centered_position)

        logging.getLogger("HWR").info(f"centered_position: {centered_position}")

        self.last_centred_position[0] = x
        self.last_centred_position[1] = y

        return centered_position

    def multiPointCentre(self, z: npt.NDArray, phis: list) -> npt.NDArray:
        """
        Multipoint centre function

        Parameters
        ----------
        z : npt.NDArray
            A numpy array containing a list of z values obtained during three-click centering
        phis : list
            A list containing phi values (a.k.a omega), e.g
            [0, 90, 180]

        Returns
        -------
        npt.NDArray
            The solution to the error function `errfunc`
        """

        def fitfunc(p, x):
            return p[0] * np.sin(x + p[1]) + p[2]

        def errfunc(p, x, y):
            return fitfunc(p, x) - y

        # The function call returns tuples of varying length
        result = optimize.leastsq(errfunc, [1.0, 0.0, 0.0], args=(phis, z))
        return result[0]

    def get_zoom_calibration(self) -> Tuple[float, float]:
        """
        Returns tuple with current zoom calibration (px per mm).

        Returns
        -------
        tuple
            Zoom calibration: (pixels_per_mm_x, pixels_per_mm_y)
        """
        zoom_enum = self.zoom.get_value()  # Get current zoom enum
        zoom_enum_str = zoom_enum.name  # as str
        try:
            self.pixels_per_mm_x = self.zoom_calibration_x.get(zoom_enum_str)
            self.pixels_per_mm_y = self.zoom_calibration_y.get(zoom_enum_str)
            logging.getLogger("HWR").debug(
                f"[Zoom] Pixels per mm: {self.pixels_per_mm_x}, {self.pixels_per_mm_y}"
            )
        except Exception as e:
            logging.getLogger("HWR").debug("[Zoom] Error on calibration: " + str(e))
        return (self.pixels_per_mm_x, self.pixels_per_mm_y)


    def automatic_centring(self):
        """Automatic centring procedure"""
        centred_pos_dir = self._get_random_centring_position()
        self.emit("newAutomaticCentringPoint", centred_pos_dir)
        return centred_pos_dir

    def _get_random_centring_position(self):
        """Get random centring result for current positions"""

        # Names of motors to vary during centring
        vary_actuator_names = ("sampx", "sampy", "phiy")

        # Range of random variation
        var_range = 0.08

        # absolute value limit for varied motors
        var_limit = 2.0

        result = self.current_motor_positions.copy()
        for tag in vary_actuator_names:
            val = result.get(tag)
            if val is not None:
                random_num = random.random()
                var = (random_num - 0.5) * var_range
                val += var
                if abs(val) > var_limit:
                    val *= 1 - var_range / var_limit
                result[tag] = val
        #
        return result

    def is_ready(self) -> bool:
        """
        Descript. :
        """
        return True

    def is_valid(self):
        """
        Descript. :
        """
        return True

    def invalidate_centring(self):
        """
        Descript. :
        """
        if self.current_centring_procedure is None and self.centring_status["valid"]:
            self.centring_status = {"valid": False}
            # self.emitProgressMessage("")
            self.emit("centringInvalid", ())

    def get_centred_point_from_coord(self, x, y, return_by_names=None):
        """
        Descript. :
        """
        centred_pos_dir = self._get_random_centring_position()
        return centred_pos_dir

    def get_calibration_data(self, offset):
        """
        Descript. :
        """
        # return (1.0 / self.x_calib, 1.0 / self.y_calib)
        return (1.0 / self.x_calib, 1.0 / self.y_calib)

    def refresh_omega_reference_position(self):
        """
        Descript. :
        """
        return

    # def get_omega_axis_position(self):
    #     """
    #     Descript. :
    #     """
    #     return self.current_positions_dict.get("phi")

    def beam_position_changed(self, value):
        """
        Descript. :
        """
        self.beam_position = value

    def get_current_centring_method(self):
        """
        Descript. :
        """
        return self.current_centring_method

    def motor_positions_to_screen(self, centred_positions_dict):
        """
        Descript. :
        """
        return self.last_centred_position[0], self.last_centred_position[1]

    def moveToCentredPosition(self, centred_position, wait=False):
        """
        Descript. :
        """
        try:
            return self.move_to_centred_position(centred_position)
        except Exception:
            logging.exception("Could not move to centred position")

    def phi_motor_moved(self, pos):
        """
        Descript. :
        """
        self.current_motor_positions["phi"] = pos
        self.emit("phiMotorMoved", pos)

    def phiy_motor_moved(self, pos):
        self.current_motor_positions["phiy"] = pos

    def phiz_motor_moved(self, pos):
        self.current_motor_positions["phiz"] = pos

    def sampx_motor_moved(self, pos):
        self.current_motor_positions["sampx"] = pos

    def sampy_motor_moved(self, pos):
        self.current_motor_positions["sampy"] = pos

    def kappa_motor_moved(self, pos):
        """
        Descript. :
        """
        self.current_motor_positions["kappa"] = pos
        if time.time() - self.centring_time > 1.0:
            self.invalidate_centring()
        self.emit_diffractometer_moved()
        self.emit("kappaMotorMoved", pos)

    def kappa_phi_motor_moved(self, pos):
        """
        Descript. :
        """
        self.current_motor_positions["kappa_phi"] = pos
        if time.time() - self.centring_time > 1.0:
            self.invalidate_centring()
        self.emit_diffractometer_moved()
        self.emit("kappaPhiMotorMoved", pos)

    def refresh_video(self):
        """
        Descript. :
        """
        self.emit("minidiffStateChanged", "testState")
        if HWR.beamline.beam:
            HWR.beamline.beam.beam_pos_hor_changed(300)
            HWR.beamline.beam.beam_pos_ver_changed(200)

    def start_auto_focus(self):
        """
        Descript. :
        """
        return

    def move_to_beam(self, x, y, omega=None):
        """
        Descript. : function to create a centring point based on all motors
                    positions.
        """

        print(
            (
                "moving to beam position: %d %d"
                % (self.beam_position[0], self.beam_position[1])
            )
        )

    def move_to_coord(self, x, y, omega=None):
        """
        Descript. : function to create a centring point based on all motors
                    positions.
        """
        warnings.warn(
            "Deprecated method, call move_to_beam instead", DeprecationWarning
        )
        return self.move_to_beam(x, y, omega)

    def start_move_to_beam(self, coord_x=None, coord_y=None, omega=None):
        """
        Descript. :
        """
        self.last_centred_position[0] = coord_x
        self.last_centred_position[1] = coord_y
        self.centring_time = time.time()
        curr_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.centring_status = {
            "valid": True,
            "startTime": curr_time,
            "endTime": curr_time,
        }
        motors = self.get_positions()
        # motors["beam_x"] = 0.1
        # motors["beam_y"] = 0.1
        self.last_centred_position[0] = coord_x
        self.last_centred_position[1] = coord_y
        self.centring_status["motors"] = motors
        self.centring_status["valid"] = True
        self.centring_status["angleLimit"] = False
        self.emit_progress_message("")
        self.accept_centring()
        self.current_centring_method = None
        self.current_centring_procedure = None

    def re_emit_values(self):
        self.emit("zoomMotorPredefinedPositionChanged", None, None)
        omega_ref = [0, 238]
        self.emit("omegaReferenceChanged", omega_ref)

    def move_kappa_and_phi(self, kappa, kappa_phi):
        return

    def get_osc_max_speed(self):
        return 66

    def get_osc_limits(self):
        if self.in_plate_mode:
            return (170, 190)
        else:
            return (-360, 360)

    def get_scan_limits(self, speed=None, num_images=None, exp_time=None):
        if self.in_plate_mode:
            return (170, 190)
        else:
            return (-360, 360)

    def get_osc_dynamic_limits(self):
        """Returns dynamic limits of oscillation axis"""
        return (0, 20)

    def get_scan_dynamic_limits(self, speed=None):
        return (-360, 360)

    def move_omega_relative(self, relative_angle):
        self.motor_hwobj_dict["phi"].set_value_relative(relative_angle, 5)

    def set_phase(self, phase: str, wait: bool = True, timeout: float = None) -> None:
        """
        Sets diffractometer to selected phase.
        By default available phase is Centring, BeamLocation,
        DataCollection, Transfer

        phase : str
            Diffractometer phase
        wait : bool, optional
            Wait until diffractometer is ready, by default True
        timeout : float, optional
            timeout in sec, by default none

        Returns
        -------
        None
        """
        logging.getLogger("HWR").debug(f"Setting phase: {phase}, wait={wait}")
        self.current_phase = str(phase)
        self.movePhase(phase)
        if wait:
            if timeout is None:
                timeout = 40
            self._wait_ready(timeout)
        self.emit("minidiffPhaseChanged", (self.current_phase,))

    def _wait_ready(self, timeout: float = None) -> None:
        """
        Waits until the MD3 is ready

        Parameters
        ----------
        timeout : float, optional
            None means infinite timeout, <=0 means default timeout (30s)

        Returns
        -------
        None
        """

        if timeout is not None and timeout <= 0:
            logging.getLogger("HWR").warning(
                "DEBUG: Strange timeout value passed %s" % str(timeout)
            )
            timeout = 30
        with gevent.Timeout(
            timeout, RuntimeError("Timeout waiting for diffractometer to be ready")
        ):
            while not self._ready():
                time.sleep(0.5)

    def get_point_from_line(self, point_one, point_two, index, images_num):
        return point_one.as_dict()

    def abort(self) -> None:
        return None

    def status(self) -> str:
        return "READY"

    def my_fancy_function(
        self, speed: float, num_images: int, exp_time: float, phase: PhaseEnum
    ) -> bool:
        return True

    def my_other_funny_function(self) -> None:
        pass

    def ssx_chip_scan(self, parameters):
        return

    def move_chip_to(self, x: int, y: int) -> None:
        print("moving chip to")
        return
