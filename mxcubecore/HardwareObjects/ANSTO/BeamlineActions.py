import logging
from time import perf_counter

import gevent
from mx3_beamline_library.devices.motors import detector_fast_stage
from mx_robot_library.client.client import Client
from mx_robot_library.schemas.common.path import RobotPaths
from mx_robot_library.schemas.common.position import RobotPositions

from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.CommandContainer import ChannelObject
from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.BeamlineActions import (
    BeamlineActions as BeamlineActionsBase,
)

from .mockup.channels import SimChannel


class BeamlineActions(BeamlineActionsBase):
    # For more examples, check the BeamlineActionsMockup class
    def __init__(self, *args):
        super().__init__(*args)


class ParkRobot:
    """Send the robot home and close the lid"""

    def __call__(self, *args, **kw):
        """
        Send the robot home and close the lid

        Returns
        -------
        args : tuple
            The original arguments passed to the method
        """
        robot = RobotTrajectory()

        robot.home()

        robot.close_lid()

        return args


class DetectorBack:
    """Send the the detector back"""

    def __call__(self, *args, **kw):
        self._move_detector_back()

        return args

    def _move_detector_back(self) -> None:
        """Move the detector fast stage back to upper limit minus 5 mm"""
        try:
            limits = detector_fast_stage.limits
            setpoint = limits[1] - 5  # Set point is 5 mm before the limit
            logging.getLogger("user_level_log").info(
                f"Moving detector fast stage to {setpoint} [mm]"
            )
        except Exception as e:
            setpoint = 650
            logging.getLogger("user_level_log").info(
                f"Failed to get limits for detector fast stage. Using default value: {setpoint}"
            )

        try:
            logging.getLogger("user_level_log").info("Moving detector fast stage...")
            detector_fast_stage.move(setpoint, wait=False)

            while detector_fast_stage.moving:
                gevent.sleep(0.5)

            logging.getLogger("user_level_log").info(
                "Detector fast stage successfully moved back"
            )
        except Exception as e:
            logging.getLogger("user_level_log").info(
                f"Failed to move detector fast stage: {str(e)}"
            )


class EnterHutch:
    """Send the robot home, close the lid, and send the detector back"""

    def __call__(self, *args, **kw):
        """
        Send the robot home, close the lid, and send the detector back

        Returns
        -------
        args : tuple
            The original arguments passed to the method
        """
        robot = RobotTrajectory()

        robot.home()

        robot.close_lid()

        self._move_detector_back()

        return args

    def _move_detector_back(self) -> None:
        """Move the detector fast stage back to upper limit minus 5 mm"""
        try:
            limits = detector_fast_stage.limits
            setpoint = limits[1] - 5  # Set point is 5 mm before the limit
            logging.getLogger("user_level_log").info(
                f"Moving detector fast stage to {setpoint} [mm]"
            )
        except Exception as e:
            setpoint = 650
            logging.getLogger("user_level_log").info(
                f"Failed to get limits for detector fast stage. Using default value: {setpoint}"
            )

        try:
            logging.getLogger("user_level_log").info("Moving detector fast stage...")
            detector_fast_stage.move(setpoint, wait=False)

            while detector_fast_stage.moving:
                gevent.sleep(0.5)

            logging.getLogger("user_level_log").info(
                "Detector fast stage successfully moved back"
            )
        except Exception as e:
            logging.getLogger("user_level_log").info(
                f"Failed to move detector fast stage: {str(e)}"
            )


class RobotTrajectory:
    """
    Class to handle robot trajectory commands such as homing and closing the lid.
    """

    def __init__(self):
        if settings.BL_ACTIVE:
            self.robot_client = Client(host=settings.ROBOT_HOST, readonly=False)

    def home(self) -> None:
        """
        Send the robot to home position

        Raises
        ------
        ValueError
            If the robot is not in home position after the command
        """
        logging.getLogger("user_level_log").info("Homing...")
        if settings.BL_ACTIVE:
            try:
                if self.robot_client.status.state.position == RobotPositions.HOME:
                    logging.getLogger("user_level_log").info(
                        "Robot is already in home position"
                    )
                    return
                self.robot_client.trajectory.home()

                self._wait_robot()

                if self.robot_client.status.state.position != RobotPositions.HOME:
                    raise ValueError(
                        f"Current position is {self.robot_client.status.state.position}, not home"
                    )

                logging.getLogger("user_level_log").info("Homing completed")
            except Exception as e:
                logging.getLogger("user_level_log").info(
                    f"Failed to change the robot position to home: {str(e)}"
                )
        else:
            gevent.sleep(2)  # Simulate some processing time
            logging.getLogger("user_level_log").info("[SIM mode] Homing completed")

    def close_lid(self) -> None:
        """
        Close the robot lid

        Raises
        ------
        ValueError
            If the lid cannot be closed
        """
        logging.getLogger("user_level_log").info("Closing lid...")
        if settings.BL_ACTIVE:
            try:

                response = self.robot_client.common.close_lid()
                if response.error is not None:
                    logging.getLogger("user_level_log").info(
                        f"Failed to close lid: {response.error}"
                    )
                    return

                logging.getLogger("user_level_log").info("Lid successfully closed")
            except Exception as e:
                logging.getLogger("user_level_log").info(
                    f"Failed to close the robot lid: {str(e)}"
                )
        else:
            gevent.sleep(2)  # Simulate some processing time
            logging.getLogger("user_level_log").info(
                "[SIM mode] Lid successfully closed"
            )

    def _wait_robot(self, timeout=120) -> None:
        """
        Waits until the robot has finished running a trajectory

        Parameters
        ----------
        timeout : float, optional
            The timeout in seconds, by default 120

        Raises
        ------
        ValueError
            Raises an error if the path cannot be changed after timeout seconds
        """
        _timeout = perf_counter() + timeout
        gevent.sleep(0.5)

        while self.robot_client.status.state.path != RobotPaths.UNDEFINED:
            gevent.sleep(0.5)
            if perf_counter() >= _timeout:
                raise ValueError(f"Could not change robot path after {timeout} seconds")


class ParkGoni(HardwareObject):
    def __init__(self, *args, **kwargs):
        super().__init__(rootName="ParkGoni", *args, **kwargs)

        if settings.BL_ACTIVE:
            self.capillary_position = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "capillary",
                },
                "CapillaryPosition",
            )

            self.beamstop_position = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "beamstop",
                },
                "BeamstopPosition",
            )

            self.aperture_position = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "aperture",
                },
                "AperturePosition",
            )
            self.scintillator_position = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "scintillator",
                },
                "ScintillatorPosition",
            )
            self.backlight_switch = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "backlight_switch",
                },
                "BackLightIsOn",
            )

            self.front_light_switch = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "front_light_switch",
                },
                "FrontLightIsOn",
            )
            self.state = self.add_channel(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "state",
                },
                "State",
            )
            self.move_phase = self.add_command(
                {
                    "type": "exporter",
                    "exporter_address": settings.EXPORTER_ADDRESS,
                    "name": "move_to_phase",
                },
                "startSetPhase",
            )
        else:
            self.capillary_position = SimChannel("capillary", initial_value="BEAM")
            self.beamstop_position = SimChannel("beamstop", initial_value="BEAM")
            self.aperture_position = SimChannel("aperture", initial_value="BEAM")
            self.scintillator_position = SimChannel(
                "scintillator", initial_value="BEAM"
            )
            self.backlight_switch = SimChannel("backlight", initial_value=0)
            self.state = SimChannel("state", initial_value="Ready")
            self.move_phase = SimChannel("move_phase")

    def __call__(self, *args, **kw) -> None:
        """
        Parks the goniometer by moving the capillary, beamstop, aperture,
        scintillator and backlight to their PARK positions.

        Returns
        -------
        None
        """
        logging.getLogger("user_level_log").info("Parking the goniometer...")

        try:
            # Set the phase to transfer to park the backlight. This seems
            # more reliable than directly turning off the backlight as it
            # ensures other components of the md3 are also in the correct position,
            # otherwise turning off the backlight directly sometimes fails
            logging.getLogger("user_level_log").info("Setting phase to Transfer")
            self.move_phase("Transfer")
            gevent.sleep(0.5)
            while self.state.get_value() != "Ready":
                gevent.sleep(0.5)
        except Exception as e:
            logging.getLogger("user_level_log").error(
                f"Failed to set phase to Transfer: {e}"
            )
            return

        if self.front_light_switch.get_value():
            try:
                self.front_light_switch.set_value(0)
            except Exception as e:
                logging.getLogger("user_level_log").warning(
                    f"Warning: Failed to turn off the front light: {e}"
                )

        channel_objects = [
            self.capillary_position,
            self.beamstop_position,
            self.aperture_position,
            self.scintillator_position,
        ]

        for channel in channel_objects:
            try:
                pos = channel.get_value()
                if pos != "PARK":
                    logging.getLogger("user_level_log").info(
                        f"Parking {channel.name()}..."
                    )
                    channel.set_value("PARK")
            except Exception as e:
                logging.getLogger("user_level_log").error(
                    f"Failed to park {channel.name()}: {e}"
                )
                return
        gevent.sleep(0.5)
        while self.state.get_value() != "Ready":
            gevent.sleep(0.5)

        # Ensure all positions are in PARK state
        timeout = 30  # seconds
        start_time = perf_counter()
        while True:
            non_park_state_list = self._all_parked(channel_objects)
            if not non_park_state_list:
                break
            if perf_counter() - start_time > timeout:
                logging.getLogger("user_level_log").error(
                    f"Timeout while waiting for goniometer to park. "
                    f"Still not parked: {non_park_state_list}"
                )
                return
            gevent.sleep(1)

        logging.getLogger("user_level_log").info("Goniometer parked successfully")

    def _all_parked(self, channel_objects: list[ChannelObject]) -> list[str]:
        """
        Checks if all channel objects are in the PARK state.
        If not, returns a list of those that are not.

        Returns
        -------
        list[str]
            A list of channel object names that are not in the PARK state.
        """
        non_park_state_list = []
        for channel in channel_objects:
            if channel.get_value() != "PARK":
                non_park_state_list.append(channel.name())
        if self.backlight_switch.get_value():
            non_park_state_list.append(self.backlight_switch.name())
        return non_park_state_list
