import ast
import logging
import random
import time
import warnings
from typing import List, Tuple

from gevent.event import AsyncResult

from mxcubecore import HardwareRepository as HWR
from mxcubecore.HardwareObjects.GenericDiffractometer import GenericDiffractometer


class Diffractometer(GenericDiffractometer):
    """
    Diffractormeter class. Here, we define the 3-click centring procedure,
    move_to_beam and automatic centring procedure.
    """

    def __init__(self, name: str) -> None:
        """
        Parameters
        ----------
        name : str
            Name of a Hardware object, e.g. `/diffractometer`

        Returns
        -------
        None
        """
        GenericDiffractometer.__init__(self, name)

    def init(self) -> None:
        """
        Object initialisation - executed *after* loading contents.

        Returns
        -------
        None
        """

        GenericDiffractometer.init(self)
        # Bzoom: 1.86 um/pixel (or 0.00186 mm/pixel) at minimum zoom
        self.x_calib = 0.00186
        self.y_calib = 0.00186
        self.last_centred_position = [318, 238]

        self.pixels_per_mm_x = 1.0 / self.x_calib
        self.pixels_per_mm_y = 1.0 / self.y_calib
        if "zoom" not in self.motor_hwobj_dict.keys():
            self.motor_hwobj_dict["zoom"] = self.get_object_by_role("zoom")
        if "focus" not in self.motor_hwobj_dict.keys():
            self.motor_hwobj_dict["focus"] = self.get_object_by_role("focus")
        calibration_x = self.zoom.get_property("mm_per_pixel_x")
        calibration_y = self.zoom.get_property("mm_per_pixel_y")
        self.zoom_calibration_x = ast.literal_eval(calibration_x)
        self.zoom_calibration_y = ast.literal_eval(calibration_y)

        self.beam_position = [318, 238]

        self.current_phase = GenericDiffractometer.PHASE_CENTRING

        self.cancel_centring_methods = {}
        self.current_motor_positions = {
            "phiy": 0,
            "sampx": 0.0,
            "sampy": -1.0,
            "zoom": 1,
            "focus": 0,
            "phiz": 0,
            "phi": 0,
            "kappa": 11,
            "kappa_phi": 22.0,
        }

        self.current_state_dict = {}
        self.centring_status = {"valid": False}
        self.centring_time = 0

        self.mount_mode = self.get_property("sample_mount_mode")
        if self.mount_mode is None:
            self.mount_mode = "manual"

        self.equipment_ready()

        # TODO FFS get this cleared up - one function, one name
        self.getPositions = self.get_positions
        # self.moveMotors = self.move_motors

        self.connect(
            self.motor_hwobj_dict["phi"], "positionChanged", self.phi_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["phiy"], "positionChanged", self.phiy_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["phiz"], "positionChanged", self.phiz_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["kappa"], "positionChanged", self.kappa_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["kappa_phi"],
            "positionChanged",
            self.kappa_phi_motor_moved,
        )
        self.connect(
            self.motor_hwobj_dict["sampx"], "positionChanged", self.sampx_motor_moved
        )
        self.connect(
            self.motor_hwobj_dict["sampy"], "positionChanged", self.sampy_motor_moved
        )

    def getStatus(self) -> str:
        """
        Gets the status of a hwr object.

        Returns
        -------
        str
            The status of a hwr object
        """
        return "ready"

    def execute_server_task(self, method, timeout=30, *args):
        """
        Not implemented method. It is used to execute commands and wait till
           diffractometer is in ready state.
        """
        raise NotImplementedError

    def in_plate_mode(self) -> bool:
        """
        Returns True if diffractometer is in plate mode.

        Returns
        -------
        bool
           True if self.mount_mode == 'plate'
        """
        return self.mount_mode == "plate"

    def use_sample_changer(self) -> bool:
        """
        Returns True if sample changer is in use.

        Returns
        -------
        bool
            True if self.mount_mode == 'sample_changer'
        """

        return self.mount_mode == "sample_changer"

    def is_reversing_rotation(self) -> bool:
        """
        If reversing rotation is used.

        Returns
        -------
        bool
            reversing_rotation=True
        """
        return True

    def get_grid_direction(self) -> dict:
        """
        Gets grid direction. Grid_direction describes how a grid is collected
        'fast' is collection direction and 'slow' describes
        move to the next collection line.

        Returns
        -------
        grid_direction : dict
            grid direction, e.g. {"fast": (0, 1), "slow": (1, 0),
                                  "omega_ref": 0}
        """
        return self.grid_direction

    def manual_centring(self) -> dict:
        """
        3-click centring procedure. We use a dummy motor for
        omega (aka "phi").

        Returns
        -------
        centred_pos_dir: dict
            centred position of motor_x and motor_z
        """
        for click in range(3):
            self.user_clicked_event = AsyncResult()
            x, y = self.user_clicked_event.get()
            if click < 2:
                self.motor_hwobj_dict["phi"].set_value_relative(90)
        self.last_centred_position[0] = x
        self.last_centred_position[1] = y
        centred_pos_dir = self.calculate_move_to_beam_pos(x, y)
        return centred_pos_dir

    def automatic_centring(self) -> dict:
        """
        Automatic centring procedure. Not yet implemented.
        Returns a random centring position.

        Returns
        -------
        centred_pos_dir : dict
            A random position
        """
        centred_pos_dir = self._get_random_centring_position()
        self.emit("newAutomaticCentringPoint", centred_pos_dir)
        return centred_pos_dir

    def _get_random_centring_position(self) -> dict:
        """
        Get random centring result for current positions.

        Returns
        -------
        result : dict
            A random position
        """

        # Names of motors to vary during centring
        vary_motor_names = ("phix", "phiz")

        # Range of random variation
        var_range = 0.08

        # absolute value limit for varied motors
        var_limit = 2.0

        result = self.current_motor_positions.copy()
        for tag in vary_motor_names:
            val = result.get(tag)
            if val is not None:
                random_num = random.random()
                var = (random_num - 0.5) * var_range
                val += var
                if abs(val) > var_limit:
                    val *= 1 - var_range / var_limit
                result[tag] = val

        # The following value results in a focused image in the testrig
        result["phiy"] = 41
        result["zoom"] = self.motor_hwobj_dict.get("zoom").get_value()
        result.pop("zoom")
        return result

    def is_ready(self) -> bool:
        """
        If device is ready.

        Returns
        -------
        bool
            True
        """
        return True

    def isValid(self) -> bool:
        """
        If device is valid.

        Returns
        -------
        bool
            True
        """
        return True

    def invalidate_centring(self) -> None:
        """
        Emits centringInvalid if current_centring_procedure is None

        Returns
        -------
        None
        """
        if self.current_centring_procedure is None and self.centring_status["valid"]:
            self.centring_status = {"valid": False}
            # self.emitProgressMessage("")
            self.emit("centringInvalid", ())

    def get_centred_point_from_coord(
        self, x: float, y: float, return_by_names: bool = True
    ) -> dict:
        """
        Method not implemeted. Returns a random centring position

        Parameters
        ----------
        x : float
            x coordinate
        y : float
            y coordinate
        return_by_names: bool
            True or False

        Returns
        -------
        centred_pos_dir: dict
            A dict containing a random centring position
        """
        centred_pos_dir = self._get_random_centring_position()
        return centred_pos_dir

    # def get_calibration_data(self, offset):
    #    return (1.0 / self.x_calib, 1.0 / self.y_calib)

    def refresh_omega_reference_position(self) -> None:
        """
        Not implemented method.

        Returns
        -------
        None
        """
        return

    # def get_omega_axis_position(self):
    #     return self.current_positions_dict.get("phi")

    def beam_position_changed(self, value: List[float]) -> None:
        """
        Updates the position of the beam.

        Parameters
        ----------
        value : list
            position of the beam, e.g. [612, 512]

        Returns
        -------
        None
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

    def moveToCentredPosition(self, centred_position, wait: bool = False) -> None:
        """
        Descript. :
        """
        try:
            return self.move_to_centred_position(centred_position)
        except BaseException:
            logging.exception("Could not move to centred position")

    def phi_motor_moved(self, pos: float) -> None:
        """
        Moves phi motor.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["phi"] = pos
        self.emit("phiMotorMoved", pos)

    def phiy_motor_moved(self, pos: float) -> None:
        """
        Moves phiy motor.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["phiy"] = pos

    def phiz_motor_moved(self, pos: float) -> None:
        """
        Moves phiz motor.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["phiz"] = pos

    def sampx_motor_moved(self, pos: float) -> None:
        """
        Moves sampx motor.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["sampx"] = pos

    def sampy_motor_moved(self, pos: float) -> None:
        """
        Moves sampy motor.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["sampy"] = pos

    def kappa_motor_moved(self, pos: float) -> None:
        """
        Moves kappa motor. Emits kappaMotorMoved.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["kappa"] = pos
        if time.time() - self.centring_time > 1.0:
            self.invalidate_centring()
        self.emit_diffractometer_moved()
        self.emit("kappaMotorMoved", pos)

    def kappa_phi_motor_moved(self, pos: float) -> None:
        """
        Moves kappa_phi motor. Emits kappaPhiMotorMoved.

        Parameters
        ----------
        pos : float
            Target value

        Returns
        -------
        None
        """
        self.current_motor_positions["kappa_phi"] = pos
        if time.time() - self.centring_time > 1.0:
            self.invalidate_centring()
        self.emit_diffractometer_moved()
        self.emit("kappaPhiMotorMoved", pos)

    def refresh_video(self) -> None:
        """
        Sets the beam position to (300,200)

        Returns
        -------
        None
        """
        self.emit("minidiffStateChanged", "testState")
        if HWR.beamline.beam:
            HWR.beamline.beam.beam_pos_hor_changed(300)
            HWR.beamline.beam.beam_pos_ver_changed(200)

    def start_auto_focus(self) -> None:
        """
        Method not implemented.
        """
        raise NotImplementedError

    def calculate_move_to_beam_pos(self, x: float, y: float) -> dict:
        """
        Calculate motor positions to put sample on the beam.
        This method is called by the "Go to Beam" button in the Web UI.

        Parameters
        ----------
        x : float
            Position of pixel_x
        y : float
            position of pixel_y

        Returns
        -------
        centred_pos_dir: dict
            centred position of motor_x and motor_z
        """
        # Update beam position
        (
            self.beam_position[0],
            self.beam_position[1],
        ) = HWR.beamline.beam.get_beam_position_on_screen()
        logging.getLogger("HWR").info(
            f"beam position: {self.beam_position[0]}, {self.beam_position[1]}"
        )

        # Get clicked position of mouse pointer
        self.last_centred_position[0] = x
        self.last_centred_position[1] = y

        # Get current value of involved motors
        motor_x = self.motor_hwobj_dict["focus"].get_value()
        motor_z = self.motor_hwobj_dict["phiz"].get_value()

        # mm to move X axis
        move_motor_x = (x - self.beam_position[0]) / self.pixels_per_mm_x
        # Move absolute
        move_motor_x += motor_x

        # mm to move Z axis
        move_motor_z = (y - self.beam_position[1]) / self.pixels_per_mm_y
        # Move absolute
        move_motor_z += motor_z

        centred_pos_dir = {"focus": move_motor_x, "phiz": move_motor_z}

        logging.getLogger("HWR").info(f"Target position = {centred_pos_dir}")
        return centred_pos_dir

    def move_to_beam(self, x: float, y: float, omega: float = None) -> dict:
        """
        Method to create a centring point based on all motors positions.

        Parameters
        ----------
        x : float
            Position of pixel_x
        y : float
            position of pixel_y
        omega : float, optional
            Position of omega (currently not used)

        Returns
        -------
        centred_pos_dir: dict
            Centred position
        """

        centred_pos_dir = self.calculate_move_to_beam_pos(x, y)
        print("Moving motors to beam...")
        self.move_to_motors_positions(centred_pos_dir, wait=True)
        return centred_pos_dir

    def move_to_coord(self, x: float, y: float, omega: float = None) -> dict:
        """
        Deprecated method. Method to create a centring point based on
        all motors positions.

        Parameters
        ----------
        x : float
            Position of pixel_x
        y : float
            position of Pixel_y
        omega : float, optional
            Position of omega

        Returns
        -------
        dict
            A dict containing updated positions of the motors
        """
        warnings.warn(
            "Deprecated method, call move_to_beam instead", DeprecationWarning
        )
        return self.move_to_beam(x, y, omega)

    def start_move_to_beam(
        self, coord_x: float = None, coord_y: float = None, omega: float = None
    ) -> None:
        """
        Starts to move motors to beam.

        Parameters
        ----------
        coord_x : float, optional
            x coordinate
        coord_y : float, optional
            y coordinate
        omega : float, optional
            Omega. Currently not used

        Returns
        -------
        None
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
        motors["beam_x"] = 0.1
        motors["beam_y"] = 0.1
        self.last_centred_position[0] = coord_x
        self.last_centred_position[1] = coord_y
        self.centring_status["motors"] = motors
        self.centring_status["valid"] = True
        self.centring_status["angleLimit"] = False
        self.emit_progress_message("")
        self.accept_centring()
        self.current_centring_method = None
        self.current_centring_procedure = None

    def update_values(self) -> None:
        """
        Updates values. Emits zoomMotorPredefinedPositionChanged
        and omegaReferenceChanged.

        Returns
        -------
        None
        """
        self.emit("zoomMotorPredefinedPositionChanged", None, None)
        omega_ref = [0, 238]
        self.emit("omegaReferenceChanged", omega_ref)

    def get_osc_max_speed(self) -> float:
        """
        Gets oscillation maximum speed.

        Returns
        -------
        float
            Osc maximum speed
        """
        return 66

    def get_osc_limits(self) -> Tuple[float, float]:
        """
        Returns oscillation limits.

        Returns
        -------
        tuple
            Osc limits
        """
        if self.in_plate_mode:
            return (170, 190)
        else:
            return (-360, 360)

    def get_scan_limits(
        self, speed=None, num_images=None, exp_time=None
    ) -> Tuple[float, float]:
        """
        Gets scan limits. Necessary for example in the plate mode
        where osc range is limited.

        Returns
        -------
        tuple
            Oscillation limits
        """
        if self.in_plate_mode:
            return (170, 190)
        else:
            return (-360, 360)

    def get_osc_dynamic_limits(self) -> Tuple[float, float]:
        """
        Gets dynamic limits of oscillation axis.

        Returns
        -------
        tuple
           dynamic limits of oscillation axis
        """
        return (0, 20)

    def get_scan_dynamic_limits(self, speed=None) -> Tuple[float, float]:
        """
        Gets dynamic limits of scan.

        Returns
        -------
        tuple
           Dynamic limits of scan
        """
        return (-360, 360)

    def move_omega_relative(self, relative_angle) -> None:
        """
        Not implemented.
        """
        # self.motor_hwobj_dict["phi"].syncMoveRelative(relative_angle, 5)
        raise NotImplementedError

    def set_phase(self, phase: str, timeout: float = None) -> None:
        """
        Sets diffractometer to selected phase.
        By default available phase is Centring, BeamLocation,
        DataCollection, Transfer

        phase : str
            Diffractometer phase
        timeout : float
            timeout in sec

        Returns
        -------
        None
        """
        self.current_phase = str(phase)
        self.emit("minidiffPhaseChanged", (self.current_phase,))

    def get_point_from_line(self, point_one, point_two, index, images_num) -> dict:
        """
        Method used to get a new motor position based on a position
        between two positions. As arguments both motor positions are
        given. frame_num and frame_total is used estimate new point position
        Helical line goes from point_one to point_two.
        In this direction also new position is estimated.
        See the implementation of Soleil/PX2/PX2Diffractometer.py

        Returns
        -------
        dict
            point_one
        """
        return point_one.as_dict()

    @property
    def zoom(self):
        """
        Override method.
        """
        return self.motor_hwobj_dict.get("zoom")

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
        self.x_calib = self.zoom_calibration_x.get(zoom_enum_str)
        self.y_calib = self.zoom_calibration_y.get(zoom_enum_str)
        try:
            float(self.x_calib)
            float(self.y_calib)
            self.pixels_per_mm_x = 1.0 / self.x_calib
            self.pixels_per_mm_y = 1.0 / self.y_calib
        except Exception as e:
            print("[Zoom] Error on calibration: " + str(e))
        return (self.pixels_per_mm_x, self.pixels_per_mm_y)

    def get_pixels_per_mm(self) -> Tuple[float, float]:
        """
        Gets the zoom calibration.

        Returns
        -------
        tuple
            Zoom calibration: (pixels_per_mm_x, pixels_per_mm_y)
        """
        pixels_per_mm_x, pixels_per_mm_y = self.get_zoom_calibration()
        return (pixels_per_mm_x, pixels_per_mm_y)

    def update_zoom_calibration(self) -> None:
        """
        Updates zoom calibration. Emits pixelsPerMmChanged.

        Returns
        -------
        None
        """
        self.emit("pixelsPerMmChanged", ((self.pixels_per_mm_x, self.pixels_per_mm_y)))
