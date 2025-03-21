import asyncio
import logging
from os import environ

from mx3_beamline_library.devices.beam import (
    energy_master,
    transmission,
)
from mx3_beamline_library.devices.motors import actual_sample_detector_distance

from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from .abstract_flow import AbstractPrefectWorkflow
from .prefect_client import MX3PrefectClient
from .schemas.full_dataset import (
    FullDatasetDialogBox,
    FullDatasetParams,
)

FULL_DATASET_DEPLOYMENT_NAME = environ.get(
    "FULL_DATASET_DEPLOYMENT_NAME", "mxcube-full-data-collection/plans"
)
ADD_DUMMY_PIN_TO_DB = environ.get("ADD_DUMMY_PIN_TO_DB", "false").lower() == "true"


class FullDatasetFlow(AbstractPrefectWorkflow):
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
        # This is the payload we get from the UI
        dialog_box_model = FullDatasetDialogBox.parse_obj(dialog_box_parameters)

        full_dataset_params = FullDatasetParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=dialog_box_model.number_of_frames,
            detector_distance=dialog_box_model.detector_distance / 1000,
            photon_energy=dialog_box_model.photon_energy,
            beam_size=(80, 80),  # TODO: get beam size,
            transmission=transmission.get(),
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
            "collection_params": full_dataset_params.dict(),
            "run_data_processing_pipeline": True,
            "hardware_trigger": dialog_box_model.hardware_trigger,
            "add_dummy_pin": ADD_DUMMY_PIN_TO_DB,
            "pipeline": dialog_box_model.processing_pipeline,
            "data_processing_config": None,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        full_dataset_flow = MX3PrefectClient(
            name=FULL_DATASET_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        try:
            loop = self._get_asyncio_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                full_dataset_flow.trigger_data_collection(sample_id)
            )
            logging.getLogger("HWR").info(
                "Full dataset collection complete. Data processing results will be displayed "
                "in MX-PRISM shortly"
            )
        except Exception as ex:
            raise QueueExecutionException(str(ex), self) from ex

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
        properties = {
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
                "title": "Detector Distance [mm]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from distance PV
                "maximum": 3000,  # TODO: get limits from distance PV
                "default": round(actual_sample_detector_distance.get(), 2),
                "widget": "textarea",
            },
            "photon_energy": {
                "title": "Photon Energy [keV]",
                "type": "number",
                "minimum": 5,  # TODO: get limits from PV?
                "maximum": 25,
                "default": round(energy_master.get(), 2),
                "widget": "textarea",
            },
            "processing_pipeline": {
                "title": "Data Processing Pipeline",
                "type": "string",
                "enum": ["dials", "fast_dp", "dials_and_fast_dp"],
                "default": "fast_dp",
            },
            "crystal_counter": {
                "title": "Crystal ID",
                "type": "number",
                "minimum": 0,
                "default": 0,
                "widget": "textarea",
            },
        }

        if ADD_DUMMY_PIN_TO_DB:
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
                "detector_distance",
                "photon_energy",
                "processing_pipeline",
                "crystal_counter",
            ],
            "dialogName": "Dataset Parameters",
        }

        return dialog
