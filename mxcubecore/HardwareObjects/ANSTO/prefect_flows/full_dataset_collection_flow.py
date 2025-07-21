import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.full_dataset import (
    FullDatasetDialogBox,
    FullDatasetParams,
)
from .sync_prefect_client import MX3SyncPrefectClient


class FullDatasetFlow(AbstractPrefectWorkflow):
    def __init__(self, state, resolution: Resolution):
        super().__init__(state, resolution)

        self._collection_type = "full_dataset"

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
        dialog_box_model = FullDatasetDialogBox.model_validate(dialog_box_parameters)

        photon_energy = energy_master.get()

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=photon_energy,
        )

        full_dataset_params = FullDatasetParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=dialog_box_model.number_of_frames,
            detector_distance=detector_distance,
            photon_energy=photon_energy,
            beam_size=(80, 80),  # TODO: get beam size,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
        )

        if not settings.ADD_DUMMY_PIN_TO_DB:
            pin = self.get_pin_model_of_mounted_sample_from_db()
            logging.getLogger("HWR").info(f"Mounted pin: {pin}")
            sample_id = pin.id
        else:
            logging.getLogger("HWR").warning(
                "A dummy pin will be added to the database. NOTE that this should "
                "only be used for development"
            )
            sample_id = dialog_box_model.sample_id

        head_type = self.get_head_type()
        if head_type == "Plate":
            type = "tray"
        elif head_type == "SmartMagnet":
            type = "pin"
        else:
            raise NotImplementedError(f"MD3 head type {head_type} not implemented")
        prefect_parameters = {
            "sample_id": sample_id,
            "crystal_counter": dialog_box_model.crystal_counter,
            "collection_params": full_dataset_params.dict(),
            "run_data_processing_pipeline": True,
            "hardware_trigger": True,
            "add_dummy_pin": settings.ADD_DUMMY_PIN_TO_DB,
            "pipeline": dialog_box_model.processing_pipeline,
            "data_processing_config": None,
            "type": type,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        full_dataset_flow = MX3SyncPrefectClient(
            name=settings.FULL_DATASET_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            full_dataset_flow.trigger_data_collection(sample_id)
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
        resolution_limits = self.resolution.get_limits()

        properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(self._get_dialog_box_param("exposure_time")),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "exclusiveMinimum": 0,
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
                "minimum": resolution_limits[0],
                "maximum": resolution_limits[1],
                "default": float(self._get_dialog_box_param("resolution")),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,
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

        if settings.ADD_DUMMY_PIN_TO_DB:
            properties["sample_id"] = {
                "title": "Database sample id (dev only)",
                "type": "integer",
                "default": 1,
                "widget": "textarea",
            }

        dialog = {
            "properties": properties,
            "required": [
                "exposure_time",
                "omega_range",
                "number_of_frames",
                "resolution",
                "processing_pipeline",
                "crystal_counter",
                "transmission",
            ],
            "dialogName": "Dataset Parameters",
        }

        return dialog
