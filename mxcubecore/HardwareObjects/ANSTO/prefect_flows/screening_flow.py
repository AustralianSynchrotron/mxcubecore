import asyncio
import logging
from os import environ

from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.screening import (
    ScreeningDialogBox,
    ScreeningParams,
)

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
            beam_size=(80, 80),  # TODO: get beam size
        )

        prefect_parameters = {
            "sample_id": dialog_box_model.sample_id,
            "crystal_counter": dialog_box_model.crystal_counter,
            "screening_params": screening_params.dict(),
            "run_data_processing_pipeline": True,
            "hardware_trigger": dialog_box_model.hardware_trigger,
            "add_dummy_pin": True,
            "pipeline": dialog_box_model.processing_pipeline,
            "data_processing_config": None,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        screening_flow = MX3PrefectClient(
            name=SCREENING_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # NOTE: using asyncio.run() does not seem to work consistently
        loop = asyncio.get_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(screening_flow.trigger_data_collection())
        logging.getLogger("user_level_log").info(
            "Screening complete. Data processing results will be displayed "
            "in MX-PRISM shortly"
        )

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
                    "title": "Total Exposure Time [s]",
                    "type": "number",
                    "minimum": 0,
                    "default": 1,
                    "widget": "textarea",
                },
                "omega_range": {
                    "title": "Omega Range [degrees]",
                    "type": "number",
                    "minimum": 0,
                    "exclusiveMaximum": 361,
                    "default": 10,
                    "widget": "textarea",
                },
                "number_of_frames": {
                    "title": "Number of Frames",
                    "type": "number",
                    "minimum": 1,
                    "default": 100,
                    "widget": "textarea",
                },
                "detector_distance": {
                    "title": "Detector Distance [m]",
                    "type": "number",
                    "default": 0.396,
                    "widget": "textarea",
                },
                "photon_energy": {
                    "title": "Photon Energy [keV]",
                    "type": "number",
                    "minimum": 0,
                    "default": 13,
                    "widget": "textarea",
                },
                "processing_pipeline": {
                    "title": "Data Processing Pipeline",
                    "type": "string",
                    "enum": ["dials", "fast_dp", "dials_and_fast_dp"],
                    "default": "dials",
                },
                "crystal_counter": {
                    "title": "Crystal Counter",
                    "type": "number",
                    "minimum": 0,
                    "default": 0,
                    "widget": "textarea",
                },
                "hardware_trigger": {
                    "title": "Hardware trigger (dev only)",
                    "type": "boolean",
                    "default": True,
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
