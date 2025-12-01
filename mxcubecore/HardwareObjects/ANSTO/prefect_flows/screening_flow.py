import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.dialog_boxes.screening import get_screening_schema
from .schemas.screening import (
    ScreeningDialogBox,
    ScreeningParams,
)
from .sync_prefect_client import MX3SyncPrefectClient


class ScreeningFlow(AbstractPrefectWorkflow):

    def __init__(self, state, resolution: Resolution, sample_id: int | None):
        super().__init__(state, resolution, sample_id=sample_id)

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
        dialog_box_model = ScreeningDialogBox.model_validate(dialog_box_parameters)

        photon_energy = energy_master.get()

        detector_distance = self._resolution_to_distance(
            dialog_box_model.resolution,
            energy=photon_energy,
        )

        screening_params = ScreeningParams(
            omega_range=dialog_box_model.omega_range,
            exposure_time=dialog_box_model.exposure_time,
            number_of_passes=1,
            count_time=None,
            number_of_frames=dialog_box_model.number_of_frames,
            detector_distance=detector_distance,
            photon_energy=photon_energy,
            # Convert transmission percentage to a value between 0 and 1
            transmission=dialog_box_model.transmission / 100,
            beam_size=(80, 80),  # TODO: get beam size
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
            "screening_params": screening_params.model_dump(),
            "run_data_processing_pipeline": True,
            "hardware_trigger": True,
            "add_dummy_pin": settings.ADD_DUMMY_PIN_TO_DB,
            "pipeline": self._get_dialog_box_param("processing_pipeline"),
            "data_processing_config": None,
            "type": type,
        }

        logging.getLogger("HWR").debug(
            f"parameters sent to prefect flow {prefect_parameters}"
        )

        screening_flow = MX3SyncPrefectClient(
            name=settings.SCREENING_DEPLOYMENT_NAME, parameters=prefect_parameters
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(dialog_box_model)

        try:
            screening_flow.trigger_data_collection(sample_id)
            logging.getLogger("user_level_log").info(
                "Screening completed successfully."
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
        resolution_limits = self.resolution.get_limits()

        properties = get_screening_schema(resolution_limits)

        tray_conditional: dict | None = None
        if self.get_head_type() == "Plate":
            tray_properties, tray_conditional = self.build_tray_dialog_schema()
            properties.update(tray_properties)

        dialog = {
            "properties": properties,
            "required": [
                "exposure_time",
                "omega_range",
                "number_of_frames",
                "resolution",
                "crystal_counter",
                "transmission",
            ],
            "dialogName": "Screening Parameters",
        }

        if tray_conditional:
            dialog.update(tray_conditional)

        return dialog
