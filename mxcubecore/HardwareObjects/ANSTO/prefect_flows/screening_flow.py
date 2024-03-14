import asyncio
import logging
from os import environ

from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.screening import ScreeningParams, ScreeningDialogBox

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
        # This is the payload we get from the UI"
        dialog_box_model = ScreeningDialogBox.parse_obj(dialog_box_parameters)


        screening_params = ScreeningParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=dialog_box_model.number_of_frames,
            detector_distance=dialog_box_model.detector_distance,
            photon_energy=dialog_box_model.photon_energy,
            beam_size=(80,80) # TODO: get beam size
            )

        prefect_parameters = {
            "sample_id": dialog_box_model.sample_id, 
            "crystal_id": 0, 
            "data_collection_id": 0, 
            "screening_params": screening_params.dict(),
            "run_data_processing_pipeline": False,
            "hardware_trigger": dialog_box_model.hardware_trigger,
            }
        

        logging.getLogger("HWR").debug(f"parameters sent to prefect flow {prefect_parameters}")

        screening_flow = MX3PrefectClient(
            name=SCREENING_DEPLOYMENT_NAME, parameters=prefect_parameters
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
                "omega_range": {
                    "title": "omega range",
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
