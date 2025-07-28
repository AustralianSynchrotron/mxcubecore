"""
Plate Manipulator maintenance.
"""
from mxcubecore.BaseHardwareObjects import HardwareObject
import logging
from gevent import sleep
from mx_robot_library.schemas.common.path import RobotPaths
from mx_robot_library.schemas.common.position import RobotPositions
from time import time
from gevent import sleep

from mx_robot_library.schemas.common.tool import RobotTools
from .PlateManipulator import PlateManipulator
from mx_robot_library.schemas.common.sample import Plate


class PlateManipulatorMaint(HardwareObject):

    __TYPE__ = "PlateManipulatorMaintenance"

    """
    Actual implementation of the Plate Manipulator MAINTENANCE,
    COMMANDS ONLY
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def init(self):
        self.plate_manipulator: PlateManipulator = self.get_object_by_role("sample_changer")
        self._scan_limits = ''
        self._running = False
        self._message = None
        self._update_global_state()

    def _do_abort(self):
        """
        Abort current command

        :returns: None
        :rtype: None
        """
        return self.plate_manipulator._do_abort()
    
    def _move_to_crystal_position(self, args):
        """
        command to move MD head to x, y crystal position
        argrs: crystall uuid or none for current drop position

        :returns: None if exception
        :rtype: None
        """
        return self.plate_manipulator.move_to_crystal_position(args)
    

    def _do_change_mode(self, args):
        self.plate_manipulator._do_change_mode(args)


    def _get_scan_limits(self, args):
        """
        Omega Dynamic scan limit current command
        :returns: None
        :rtype: None
        """
        #self._scan_limits = self.plate_manipulator.get_scan_limits(args)
        self._update_global_state()
        return [1,1]


    def _update_global_state(self):
        state_dict, cmd_state, message = self.get_global_state()
        self.emit("globalStateChanged", (state_dict, cmd_state, message))

    def _robot_state(self):
        try:
            state = self.plate_manipulator.robot_client.status.state
        except Exception as e:
            logging.getLogger("user_level_log").error(f"Failed to get robot state: {e}")
            raise e

        if state.path == RobotPaths.UNDEFINED:
            return "MOVING"
        else:
            return "READY"

    def get_global_state(self):
        """
        """
        state = self._robot_state()
        #scan_limits = self._scan_limits
        # ready = self.plate_manipulator._ready()
        plate_info_dict =  self.plate_manipulator.get_plate_info()
        state_dict = {
            "running": self._running,
            #"scan_limits": scan_limits,
            "state": state,
            "plate_info" : plate_info_dict
        }

        cmd_state = {
            "abort": True,
        }


        return state_dict, cmd_state, self._message

    

    def get_cmd_info(self):
        """ return information about existing commands for this object
           the information is organized as a list
           with each element contains
           [ cmd_name,  display_name, category ]
        """
        """ [cmd_id, cmd_display_name, nb_args, cmd_category, description ] """

        cmd_list = [
            [
                "Actions",
                [
                    ["abort", "Abort", "Actions", None],
                ],
            ],
        ]

        return cmd_list

    def send_command(self, cmdname, args=None):
        if cmdname in ["getOmegaMotorDynamicScanLimits"]:
            self._get_scan_limits(args)
        if cmdname in ["moveToCrystalPosition"]:
            self._move_to_crystal_position(args)
        if cmdname == "abort":
            self._do_abort()
        if cmdname == "setPlateBarcode":
            self.set_plate_barcode(args)
        # if cmdname == "change_mode":
        #     self._do_change_mode(args)      
        return True
    
    def set_plate_barcode(self, args):
        """
        Set the barcode of the plate in the plate manipulator.

        :param args: The barcode to set.
        :type args: str
        """
        self._running = True
        self._message = f"Mounting tray {args}. Please wait..."
        self._update_global_state() 

        try:
            # TODO: Replace with prefect flow
            self.plate_manipulator.robot_client.trajectory.plate.mount(plate=Plate(id=1), wait=True)
        except Exception as e:
            self._running = False
            logging.getLogger("user_level_log").error(f"Failed to mount tray: {e}")
            self._message = f"Failed to mount tray: {e}"
            self._update_global_state()
            return
        self._message = f"Tray successfully mounted: {args}"
        self._update_global_state()

