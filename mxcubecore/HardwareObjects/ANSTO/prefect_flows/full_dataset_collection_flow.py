import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.dialog_boxes.full_dataset import get_full_dataset_schema
from .schemas.full_dataset import (
    FullDatasetDialogBox,
    FullDatasetParams,
)
from .sync_prefect_client import MX3SyncPrefectClient


class FullDatasetFlow(AbstractPrefectWorkflow):
    def __init__(self, state, resolution: Resolution, sample_id: int | None):
        super().__init__(state, resolution, sample_id=sample_id)

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

        number_of_frames = (
            dialog_box_model.omega_range / dialog_box_model.degrees_per_frame
        )
        if number_of_frames.is_integer():
            number_of_frames = int(number_of_frames)
            omega_range = dialog_box_model.omega_range
        else:
            # adjust omega range to fit an integer number of frames
            number_of_frames = round(number_of_frames)
            omega_range = number_of_frames * dialog_box_model.degrees_per_frame
            logging.getLogger("user_level_log").warning(
                f"Adjusted omega range from {dialog_box_model.omega_range} "
                f"to {omega_range} to fit an integer number of frames "
                f"({number_of_frames}) with degrees per frame "
                f"{dialog_box_model.degrees_per_frame}"
            )

        logging.getLogger("HWR").info(
            f"Calculated number of frames: {number_of_frames} "
            f"from omega range {dialog_box_model.omega_range} "
            f"and degrees per frame {dialog_box_model.degrees_per_frame}"
        )
        full_dataset_params = FullDatasetParams(
            start_omega=dialog_box_model.start_omega,
            omega_range=omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=number_of_frames,
            detector_distance=detector_distance,
            photon_energy=photon_energy,
            beam_size=(80, 80),  # TODO: get beam size,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
        )

        if not settings.ADD_DUMMY_PIN_TO_DB:
            if self.sample_id is None:
                logging.getLogger("HWR").info("Getting sample from the data layer...")
                sample_id = self.get_sample_id_of_mounted_sample(dialog_box_model)
                logging.getLogger("HWR").info(f"Mounted sample id: {sample_id}")
            else:
                logging.getLogger("HWR").info(
                    f"Hand-mount mode, sample id: {self.sample_id}"
                )
                sample_id = self.sample_id

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
            logging.getLogger("user_level_log").info(
                "Dataset collection completed successfully."
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

        properties = get_full_dataset_schema(resolution_limits)

        tray_conditional: dict | None = None
        if self.get_head_type() == "Plate":
            tray_properties, tray_conditional = self.build_tray_dialog_schema()
            properties.update(tray_properties)

        dialog = {
            "properties": properties,
            "required": [
                "exposure_time",
                "omega_range",
                "degrees_per_frame",
                "resolution",
                "processing_pipeline",
                "crystal_counter",
                "transmission",
            ],
            "dialogName": "Dataset Parameters",
        }

        if tray_conditional:
            dialog.update(tray_conditional)

        return dialog
