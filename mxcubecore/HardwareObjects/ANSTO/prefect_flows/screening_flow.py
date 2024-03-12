import asyncio
import logging
from os import environ

from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.loop_data_collection import ScreeningParams

SCREENING_DEPLOYMENT_NAME = environ.get(
    "SCREENING_DEPLOYMENT_NAME", "mxcube-screening/plans"
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
            "sample_id": "test2", 
            "crystal_id": 0, 
            "data_collection_id": 0, 
            "screening_params": ScreeningParams().dict(),
            "run_data_processing_pipeline": False,
            "hardware_trigger": False,
            }

        # FIXME!!!
        # for key, val in dialog_box_parameters.items():
        #     parameters.update({key: val})

        logging.getLogger("HWR").debug(f"parameters sent to flow {parameters}")

        screening_flow = MX3PrefectClient(
            name=SCREENING_DEPLOYMENT_NAME, parameters=parameters
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
