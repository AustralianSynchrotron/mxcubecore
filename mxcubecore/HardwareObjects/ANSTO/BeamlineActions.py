import logging
from time import perf_counter

import gevent
from mx3_beamline_library.devices.motors import detector_fast_stage
from mx_robot_library.client.client import Client
from mx_robot_library.schemas.common.path import RobotPaths
from mx_robot_library.schemas.common.position import RobotPositions

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.HardwareObjects.BeamlineActions import BeamlineActions


class BeamlineActions(BeamlineActions):
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
