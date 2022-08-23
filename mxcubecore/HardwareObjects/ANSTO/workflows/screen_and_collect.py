from .base_workflow import AbstractBlueskyWorflow
import asyncio
from bluesky_queueserver_api import BPlan


class ScreenAndCollect(AbstractBlueskyWorflow):
    def __init__(self, state, REST: str) -> None:
        super().__init__(state, REST)

    def screen_and_collect_worklow(self, item: BPlan) -> None:
        """
        Executes a screen and collect worflow by calling the bluesky queueserver

        Parameters
        ----------
        item : Bplan
            A Bplan object containing information about a bluesky plan

        Returns
        -------
        None
        """
        self.state.value = "RUNNING"

        # Run bluesky plan
        item = BPlan(
            "scan_plan",
            detector="dectris_detector",
            detector_configuration={"frame_time": 8, "nimages": 2},
            metadata={"username": "Jane Doe", "sample_id": "test"},
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
