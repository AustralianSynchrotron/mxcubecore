import asyncio
import logging
from os import environ

from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient

SCAN_PREFECT_DEPLOYMENT_ID = environ.get(
    "SCAN_PREFECT_DEPLOYMENT_ID", "mxcube-scan/plans"
)


class ScreeningFlow(AbstractPrefectWorkflow):
    def run(self, dialog_box_parameters: dict) -> None:
        """Runs the screening flow

        Parameters
        ----------
        dialog_box_parameters : dict
            The parameters obtained from the mxcube dialog box

        Returns
        -------
        None
        """
        parameters = {
            "sample_id": "sample",
            "scan_range": 10,
            "exposure_time": 1,
            "hardware_trigger": True,
            "number_of_frames": 100,
            "number_of_passes": 1,
            "run_data_processing_pipeline": True,
            "detector_distance": -0.298,
            "photon_energy": 12700,
        }

        for key, val in dialog_box_parameters.items():
            parameters.update({key: val})

        logging.getLogger("HWR").debug(f"parameters sent to flow {parameters}")

        screening_flow = MX3PrefectClient(
            name=SCAN_PREFECT_DEPLOYMENT_ID, parameters=parameters
        )

        try:
            # NOTE: using asyncio.run() does not seem to work consistently
            loop = asyncio.get_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(screening_flow.trigger_flow(wait=True))
        except Exception as e:
            logging.getLogger("HWR").info(f"Failed to execute screening flow: {e}")

        self._state.value = "ON"
        self.mxcubecore_workflow_aborted = False

    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary following the JSON schema.
        """
        dialog = {
            "properties": {
                "exposure_time": {
                    "title": "exposure time",
                    "type": "number",
                    "minimum": 0,
                    "default": 1,
                    "widget": "textarea",
                },
                "scan_range": {
                    "title": "scan range",
                    "type": "number",
                    "minimum": 0,
                    "exclusiveMaximum": 361,
                    "default": 10,
                    "widget": "textarea",
                },
                "number_of_frames": {
                    "title": "number of frames",
                    "type": "number",
                    "minimum": 1,
                    "default": 100,
                    "widget": "textarea",
                },
                "detector_distance": {
                    "title": "detector distance",
                    "type": "number",
                    "default": -0.298,
                    "widget": "textarea",
                },
                "photon_energy": {
                    "title": "photon energy",
                    "type": "number",
                    "minimum": 0,
                    "default": 12700,
                    "widget": "textarea",
                },
                "hardware_trigger": {
                    "title": "Hardware trigger (dev only)",
                    "type": "boolean",
                    "minimum": 0,
                    "exclusiveMaximum": 361,
                    "default": False,
                    "widget": "textarea",
                },
                "sample_id": {
                    "title": "Sample id (dev only)",
                    "type": "string",
                    "default": "my_sample",
                    "widget": "textarea",
                },
            },
            "required": ["exposure_time"],
            "dialogName": "Grid scan parameters",
        }

        return dialog
