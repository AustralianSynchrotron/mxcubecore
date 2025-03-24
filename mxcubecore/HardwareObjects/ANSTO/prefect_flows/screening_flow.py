import asyncio
import logging
from os import environ

from mx3_beamline_library.devices.beam import (
    energy_master,
    transmission,
)
from mx3_beamline_library.devices.motors import actual_sample_detector_distance

from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.screening import (
    ScreeningDialogBox,
    ScreeningParams,
)

SCREENING_DEPLOYMENT_NAME = environ.get(
    "SCREENING_DEPLOYMENT_NAME", "mxcube-screening/plans"
)
ADD_DUMMY_PIN_TO_DB = environ.get("ADD_DUMMY_PIN_TO_DB", "false").lower() == "true"


class ScreeningFlow(AbstractPrefectWorkflow):

    def __init__(self, state, resolution: Resolution):
        super().__init__(state, resolution)

        self._collection_type = "screening"

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

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=dialog_box_model.photon_energy,
            roi_mode="disabled",
        )

        screening_params = ScreeningParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=dialog_box_model.number_of_frames,
            detector_distance=detector_distance,
            photon_energy=dialog_box_model.photon_energy,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
            beam_size=(80, 80),  # TODO: get beam size
        )

        if not ADD_DUMMY_PIN_TO_DB:
            pin = self.get_pin_model_of_mounted_sample_from_db()
            logging.getLogger("HWR").info(f"Mounted pin: {pin}")
            sample_id = pin.id
        else:
            logging.getLogger("HWR").warning(
                "A dummy pin will be added to the database. NOTE that this should "
                "only be used for development"
            )
            sample_id = dialog_box_model.sample_id

        prefect_parameters = {
            "sample_id": sample_id,
            "crystal_counter": dialog_box_model.crystal_counter,
            "screening_params": screening_params.dict(),
            "run_data_processing_pipeline": True,
            "hardware_trigger": True,
            "add_dummy_pin": ADD_DUMMY_PIN_TO_DB,
            "pipeline": dialog_box_model.processing_pipeline,
            "data_processing_config": None,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        screening_flow = MX3PrefectClient(
            name=SCREENING_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            loop = self._get_asyncio_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(screening_flow.trigger_data_collection(sample_id))
            logging.getLogger("HWR").info(
                "Screening complete. Data processing results will be displayed "
                "in MX-PRISM shortly"
            )

            self._state.value = "ON"
            self.mxcubecore_workflow_aborted = False
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex

    def dialog_box(self) -> dict:
        """
        Workflow dialog box. Returns a dictionary that follows a JSON schema

        Returns
        -------
        dialog : dict
            A dictionary following the JSON schema.
        """
        properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "minimum": 0,
                "default": float(self._get_dialog_box_param("exposure_time")),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "minimum": 0,
                "exclusiveMaximum": 361,
                "default": float(self._get_dialog_box_param("omega_range")),
                "widget": "textarea",
            },
            "number_of_frames": {
                "title": "Number of Frames",
                "type": "integer",
                "minimum": 1,
                "default": int(self._get_dialog_box_param("number_of_frames")),
                "widget": "textarea",
            },
            "resolution": {
                "title": "Resolution [Å]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from distance PV
                "maximum": 3000,  # TODO: get limits from distance PV
                "default": float(self._get_dialog_box_param("resolution")),
                "widget": "textarea",
            },
            "photon_energy": {
                "title": "Photon Energy [keV]",
                "type": "number",
                "minimum": 5,  # TODO: get limits from PV?
                "maximum": 25,
                "default": float(self._get_dialog_box_param("photon_energy")),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from PV?
                "maximum": 100,
                "default": float(self._get_dialog_box_param("transmission")),
                "widget": "textarea",
            },
            "processing_pipeline": {
                "title": "Data Processing Pipeline",
                "type": "string",
                "enum": ["dials", "fast_dp", "dials_and_fast_dp"],
                "default": self._get_dialog_box_param("processing_pipeline"),
            },
            "crystal_counter": {
                "title": "Crystal ID",
                "type": "integer",
                "minimum": 0,
                "default": int(self._get_dialog_box_param("crystal_counter")),
                "widget": "textarea",
            },
        }

        if ADD_DUMMY_PIN_TO_DB:
            # Dev only
            properties["sample_id"] = {
                "title": "Sample id (dev only)",
                "type": "string",
                "default": "my_sample",
                "widget": "textarea",
            }

        dialog = {
            "properties": properties,
            "required": [
                "exposure_time",
                "omega_range",
                "number_of_frames",
                "resolution",
                "photon_energy",
                "processing_pipeline",
                "crystal_counter",
                "transmission",
            ],
            "dialogName": "Screening Parameters",
        }

        return dialog
