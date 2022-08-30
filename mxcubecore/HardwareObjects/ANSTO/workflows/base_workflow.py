import asyncio
import logging
import time
from abc import ABC, abstractmethod

from bluesky_queueserver_api import BPlan
from bluesky_queueserver_api.comm_base import RequestError, RequestFailedError
from bluesky_queueserver_api.http.aio import REManagerAPI

from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor


class AbstractBlueskyWorflow(ABC):
    """Abstract class to run Bluesky plans as part of
    an mxcubecore workflow. Classes created using this abstract class are meant
    to be used by the BlueskyWorklow class.

    Attributes
    ----------
    bluesky_plan_aborted : bool
        True if a bluesky plan is aborted, False otherwise. False, by default.
    mxcubecore_workflow_aborted : bool
        True if a mxcubecore worfklow is aborted, False otherwise. False, by default.
    """

    def __init__(
        self, motor_dict: dict[str, OphydEpicsMotor], state, REST: str
    ) -> None:
        """
        Parameters
        ----------
        motor_dict : dict[str, OphydEpicsMotor]
            A dictionary containing OphydEpicsMotors
        state : State
            The state of the BlueskyWorkflow class. See the State class in
            BlueskyWorflow for details
        REST : str
            The URL of the bluesky-queueserver-api
        """

        super().__init__()
        self.motor_dict = motor_dict
        self._state = state
        self.REST = REST

        self.bluesky_plan_aborted = False
        self.mxcubecore_workflow_aborted = False

    @abstractmethod
    def run(self) -> None:
        """
        Runs a bluesky plan
        """

    @abstractmethod
    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary that follows a JSON schema.
        """
        dialog = {
            "properties": {
                "name": {
                    "title": "Task name",
                    "type": "string",
                    "minLength": 2,
                    "default": "Test",
                },
            },
            "required": ["name"],
            "dialogName": "My Workflow parameters",
        }
        return dialog

    async def update_frontend_values(self, motor: OphydEpicsMotor) -> None:
        """
        Update the motor values in the Mxcube frontend

        Parameters
        ----------
        motor : OphydEpicsMotor
            An OphydEpicsMotor object

        Returns
        -------
        None
        """
        motor.update_specific_state(motor.SPECIFIC_STATES.MOVING)

        motor.update_state(motor.STATES.BUSY)
        current_value = motor.get_value()
        motor.update_value(current_value)
        await asyncio.sleep(0.01)

    async def run_bluesky_plan(self, item: BPlan) -> None:
        """
        Asynchronously run a bluesky plan. The motor's positions
        are updated in the Mxcube3 frontend while the bluesky
        plan is executing.

        Parameters
        ----------
        item : BPlan
            A Bplan object containing information about a bluesky plan

        Returns
        -------
        None
        """
        self.RM = REManagerAPI(http_server_uri=self.REST)

        await self.RM.item_add(item)

        await self.RM.environment_open()
        await self.RM.wait_for_idle()

        await self.RM.queue_start()

        # Sleep for 1 second until the RM changes the status to executing_plan
        time.sleep(1)
        RM_status = await self.RM.status()
        while RM_status["worker_environment_state"] == "executing_plan":
            if not self.bluesky_plan_aborted:
                time.sleep(0.2)
                for motor in self.motor_dict.values():
                    await self.update_frontend_values(motor)

                RM_status = await self.RM.status()
            else:
                # Abort bluesky plan
                self.bluesky_plan_aborted = False

                try:
                    await self.RM.re_pause()
                    await self.RM.wait_for_idle_or_paused()

                    await self.RM.re_abort()
                    await self.RM.wait_for_idle()
                except (RequestFailedError, RequestError) as e:
                    logging.getLogger("HWR").info(f"Abort error: {e}")

                await self.RM.queue_clear()
                await self.RM.wait_for_idle()

                for motor in self.motor_dict.values():
                    await self.update_frontend_values(motor)

                for motor in self.motor_dict.values():
                    motor.update_state(motor.STATES.READY)
                break
        else:
            for motor in self.motor_dict.values():
                motor.update_state(motor.STATES.READY)

        await self.RM.wait_for_idle()

        await self.RM.environment_close()
        await self.RM.wait_for_idle()

    @property
    def bluesky_plan_aborted(self) -> bool:
        """
        Gets the state of the bluesky plan

        Returns
        -------
        self._value : bool
            The state of the bluesky plan
        """
        return self._bluesky_plan_aborted

    @bluesky_plan_aborted.setter
    def bluesky_plan_aborted(self, value: bool) -> None:
        """
        Sets the state of the bluesky plan

        Parameters
        ----------
        value : bool
            The state of the bluesky plan

        Returns
        -------
        None
        """
        self._bluesky_plan_aborted = value

    @property
    def mxcubecore_workflow_aborted(self) -> bool:
        """
        Gets the state of the mxcubecore worflow

        Returns
        -------
        self._value: bool
            The state of the mxcubecore workflow
        """
        return self._mxcubecore_workflow_aborted

    @mxcubecore_workflow_aborted.setter
    def mxcubecore_workflow_aborted(self, value: bool) -> None:
        """
        Sets the state of the mxcubecore workflow

        Returns
        -------
        None
        """
        self._mxcubecore_workflow_aborted = value

    @property
    def state(self):
        """
        Gets the state of the workflow

        Returns
        -------
        _state : State
            The state of the workflow
        """
        return self._state

    @state.setter
    def state(self, new_state) -> None:
        """
        Sets the state of the workflow

        Parameters
        ----------
        new_state : State
            The state of the workflow

        Returns
        -------
        None
        """
        self._state = new_state
