import asyncio

from bluesky_queueserver_api import BPlan

from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor

from .base_workflow import AbstractBlueskyWorflow
from bluesky_queueserver_api.http.aio import REManagerAPI


class Collect(AbstractBlueskyWorflow):
    def __init__(
        self, motor_dict: dict[str, OphydEpicsMotor], state
    ) -> None:
        """
        Parameters
        ----------
        run_engine : REManagerAPI
            The bluesky run engine. We assume that the run engine has been opened
        motor_dict : dict[str, OphydEpicsMotor]
            A dictionary containing OphydEpicsMotors
        state : State
            The state of the BlueskyWorkflow class. See the State class in
            BlueskyWorflow for details
        """
        super().__init__(motor_dict, state)

    def run(self, metadata: dict) -> None:
        """
        Executes a screen and collect worflow by calling the bluesky queueserver

        Returns
        -------
        None
        """
        self.state.value = "RUNNING"

        # Run bluesky plan
        item = BPlan(
            "scan_plan",
            detector="dectris_detector",
            detector_configuration={"frame_time": 8},
            metadata=metadata,
        )
        asyncio.run(self.run_bluesky_plan(item))

        self.state.value = "ON"
        self.mxcubecore_workflow_aborted = False

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
