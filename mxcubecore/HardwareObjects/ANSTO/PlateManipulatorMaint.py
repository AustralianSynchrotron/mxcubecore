import logging
from typing import Literal

from mx_robot_library.schemas.common.path import RobotPaths
from mx_robot_library.schemas.common.sample import Plate

from mxcubecore.BaseHardwareObjects import HardwareObject

from .PlateManipulator import PlateManipulator


class PlateManipulatorMaint(HardwareObject):

    __TYPE__ = "PlateManipulatorMaintenance"

    """
    Implementation of the Plate Manipulator maintenance object.
    (commands only). Note that we've also added a component in the UI to mount trays
    which is not included in the get_cmd_info method, as this
    requires a barcode to be passed as an argument. Any method that requires
    input from the user should be implemented in the UI.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def init(self):
        self.plate_manipulator: PlateManipulator = self.get_object_by_role(
            "sample_changer"
        )
        self._scan_limits = ""
        self._running = False
        self._message = None
        self._update_global_state()

    def _do_abort(self) -> None:
        """
        Abort current command

        Returns
        -------
        None
        """
        self._message = "Aborting current command. Please wait..."
        self._update_global_state()
        try:
            self.plate_manipulator._do_abort()
        except Exception as e:
            logging.getLogger("user_level_log").error(f"Failed to abort: {e}")
            self._message = f"Failed to abort: {e}"
            self._update_global_state()
            return

        self._message = "Command aborted successfully"
        self._update_global_state()

    def _get_scan_limits(self, args):
        raise NotImplementedError()

    def _update_global_state(self) -> None:
        """Update the global state of the plate manipulator.

        Returns
        -------
        None
        """
        state_dict, cmd_state, message = self.get_global_state()
        self.emit("globalStateChanged", (state_dict, cmd_state, message))

    def _robot_state(self) -> Literal["MOVING", "READY"]:
        """Get the current state of the robot.

        Returns
        -------
        Literal["MOVING", "READY"]
            The state of the robot, either "MOVING" or "READY".
        """
        try:
            state = self.plate_manipulator.robot_client.status.state
        except Exception as e:
            logging.getLogger("user_level_log").error(f"Failed to get robot state: {e}")
            raise e

        if state.path == RobotPaths.UNDEFINED:
            return "MOVING"
        else:
            return "READY"

    def get_global_state(self) -> tuple[dict, dict, str]:
        """Get the global state of the plate manipulator.
        The barcode field was added by us so that the barcode can
        be updated correctly in the GUI. Similarly the barcode
        is handled by the UI in our branch of the code.

        Returns
        -------
        tuple[dict, dict, str]
            A tuple containing the state dictionary, command state dictionary, and message.
        """
        state = self._robot_state()
        plate_info_dict = self.plate_manipulator.get_plate_info()
        state_dict = {
            "running": self._running,
            # "scan_limits": scan_limits,
            "state": state,
            "plate_info": plate_info_dict,
        }

        cmd_state = {
            "abort": True,
            "barcode": plate_info_dict.get("plate_barcode", "No barcode found"),
        }

        return state_dict, cmd_state, self._message

    def get_cmd_info(self) -> list:
        """Return information about existing commands for this object.
        The information is organized as a list
        with each element containing
        [ cmd_name,  display_name, category ]

        Returns
        -------
        list
            A list of commands available for the plate manipulator maintenance.
        """

        cmd_list = [
            [
                "Actions",
                [
                    ["abort", "Abort", "Actions", None],
                ],
            ],
        ]

        return cmd_list

    def send_command(self, cmdname: str, args: str | None = None) -> bool:
        """Send a command to the plate manipulator maintenance.

        Returns
        -------
        bool
            True if the command was sent successfully, otherwise False.
        """
        if cmdname == "abort":
            self._do_abort()
        elif cmdname == "setPlateBarcode":
            self._mount_tray(args)

        return True

    def _mount_tray(self, args: str) -> None:
        """
        Mount a tray with the given barcode

        Parameters
        ----------
        args : str
            The barcode of the tray to mount.

        Returns
        -------
        None
        """
        self._running = True
        self._message = f"Mounting tray {args}. Please wait..."
        self._update_global_state()

        try:
            # TODO: Replace with prefect flow
            self.plate_manipulator.robot_client.trajectory.plate.mount(
                plate=Plate(id=1), wait=True
            )
        except Exception as e:
            self._running = False
            logging.getLogger("user_level_log").error(f"Failed to mount tray: {e}")
            self._message = f"Failed to mount tray: {e}"
            self._update_global_state()
            return
        self._message = f"Tray successfully mounted: {args}"
        self._update_global_state()
