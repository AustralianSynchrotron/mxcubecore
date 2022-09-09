import asyncio

from bluesky_queueserver_api import BPlan

from mxcubecore.HardwareObjects.ANSTO.OphydEpicsMotor import OphydEpicsMotor

from .base_workflow import AbstractBlueskyWorflow


class Collect(AbstractBlueskyWorflow):
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
        super().__init__(motor_dict, state, REST)

    def run(self, metadata: dict) -> None:
        """
        Executes a screen and collect worflow by calling the bluesky queueserver

        Returns
        -------
        None
        """
        self.state.value = "RUNNING"

        # Run bluesky plan
        # TODO: Currently we can only process the minimalInsulinMX1 master file
        # that containes 30 frames, therefore we set "nimages": 30.
        # We should update this once we can process any masterfile
        item = BPlan(
            "scan_plan",
            detector="dectris_detector",
            detector_configuration={"frame_time": 8, "nimages": 30},
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
