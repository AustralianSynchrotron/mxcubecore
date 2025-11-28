import logging

from mx3_beamline_library.devices.beam import energy_master

from mxcubecore.configuration.ansto.config import settings
from mxcubecore.queue_entry.base_queue_entry import QueueExecutionException

from ..redis_utils import get_redis_connection
from ..Resolution import Resolution
from .abstract_flow import AbstractPrefectWorkflow
from .schemas.dialog_boxes.full_dataset import get_full_dataset_schema
from .schemas.dialog_boxes.grid_scan import get_grid_scan_schema
from .schemas.dialog_boxes.screening import get_screening_schema
from .schemas.partial_udc import (
    FullDatasetParams,
    GridScanParams,
    OpticalCenteringExtraConfig,
    OpticalCenteringParams,
    PartialUDCDialogBox,
    ProjectStrategy,
    ScreeningParams,
    SingleLoopDataCollectionConfig,
)
from .sync_prefect_client import MX3SyncPrefectClient


class PartialUDCFlow(AbstractPrefectWorkflow):
    """Prefect Raster Workflow"""

    def __init__(
        self,
        state,
        resolution: Resolution,
        sample_id: int | None,
    ) -> None:
        super().__init__(state, resolution, sample_id=sample_id)

        self._collection_type = "partial_udc"
        self.grid_step_map = {
            "5x5": (5.0, 5.0),
            "10x10": (10.0, 10.0),
            "20x20": (20.0, 20.0),
        }

    def run(self, dialog_box_parameters: dict) -> None:
        """


        Parameters
        ----------
        dialog_box_parameters : dict
            A dictionary containing parameters from the dialog box

        Returns
        -------
        None
        """

        self._state.value = "RUNNING"
        head_type = self.get_head_type()
        # TODO: partial udc for plates not supported yet
        if head_type == "Plate":
            msg = "Partial UDC for plates is not supported yet"
            logging.getLogger("user_level_log").error(msg)
            raise QueueExecutionException(msg, self)

        dialog_box_model = PartialUDCDialogBox.model_validate(dialog_box_parameters)

        grid_scan_model = dialog_box_model.grid_scan
        screening_model = dialog_box_model.screening
        full_dataset_model = dialog_box_model.full_dataset

        if not settings.ADD_DUMMY_PIN_TO_DB:
            if self.sample_id is None:
                logging.getLogger("HWR").info("Getting sample from the data layer...")
                sample_id = self.get_sample_id_of_mounted_sample(grid_scan_model)
                logging.getLogger("HWR").info(f"Mounted sample id: {sample_id}")
            else:
                logging.getLogger("HWR").info(
                    f"Hand-mount mode, sample id: {self.sample_id}"
                )
                sample_id = self.sample_id

        else:
            logging.getLogger("HWR").warning(
                "SIM mode! The sample id will not be obtained from the data layer. "
                "Setting sample id to 1. "
                "Ensure that this sample id exists in the db before launching the flow"
            )
            sample_id = 1

        photon_energy = energy_master.get()

        with get_redis_connection() as redis_connection:
            default_resolution = float(redis_connection.get("grid_scan:resolution"))

        detector_distance = self._resolution_to_distance(
            default_resolution,
            energy=photon_energy,
        )
        logging.getLogger("HWR").info(
            f"Detector distance corresponding to {default_resolution} A: {detector_distance} [m]"
        )

        if dialog_box_model.perform_screening:
            screening_params = ScreeningParams(
                omega_range=screening_model.omega_range,
                exposure_time=screening_model.exposure_time,
                number_of_passes=1,
                count_time=None,
                number_of_frames=screening_model.number_of_frames,
                detector_distance=self._resolution_to_distance(
                    screening_model.resolution,
                    energy=photon_energy,
                ),
                photon_energy=photon_energy,
                transmission=screening_model.transmission / 100,
                beam_size=(80, 80),
            )
        else:
            screening_params = None

        if dialog_box_model.perform_full_dataset:
            full_dataset_params = FullDatasetParams(
                omega_range=full_dataset_model.omega_range,
                exposure_time=full_dataset_model.exposure_time,
                number_of_passes=1,
                count_time=None,
                number_of_frames=full_dataset_model.number_of_frames,
                detector_distance=self._resolution_to_distance(
                    full_dataset_model.resolution,
                    energy=photon_energy,
                ),
                photon_energy=photon_energy,
                transmission=full_dataset_model.transmission / 100,
                beam_size=(80, 80),
            )
        else:
            full_dataset_params = None

        partial_udc_config = SingleLoopDataCollectionConfig(
            optical_centering=OpticalCenteringParams(
                beam_position=(612, 512),
                extra_config=OpticalCenteringExtraConfig(grid_height_scale_factor=2),
                grid_step=self.grid_step_map[grid_scan_model.grid_step],
                calibrated_alignment_z=0.85,  # TODO: maybe get from redis?
            ),
            grid_scan=GridScanParams(
                omega_range=0,
                md3_alignment_y_speed=grid_scan_model.md3_alignment_y_speed,
                detector_distance=detector_distance,
                photon_energy=photon_energy,
                transmission=grid_scan_model.transmission / 100,
                crystal_finder_threshold=1,  # TODO: can user set this?
                number_of_processes=settings.GRID_SCAN_NUMBER_OF_PROCESSES,
            ),
            screening=screening_params,
            full_dataset=full_dataset_params,
            mount_pin_at_start_of_flow=False,
            add_dummy_pin_to_db=settings.ADD_DUMMY_PIN_TO_DB,
            project_strategy=ProjectStrategy(
                use_screening=dialog_box_model.perform_screening
            ),
        )
        prefect_parameters = {
            "sample_id": sample_id,
            "pin": None,
            "prepick_pin": None,
            "config": partial_udc_config.model_dump(exclude_none=True),
        }

        logging.getLogger("HWR").info(
            f"Parameters sent to prefect flow: {prefect_parameters}"
        )

        # Remember the collection params for the next collection
        self._save_dialog_box_params_to_redis(
            grid_scan_model, collection_type="grid_scan"
        )
        if dialog_box_model.perform_screening:
            self._save_dialog_box_params_to_redis(
                screening_model, collection_type="screening"
            )
        if dialog_box_model.perform_full_dataset:
            self._save_dialog_box_params_to_redis(
                full_dataset_model, collection_type="full_dataset"
            )

        with get_redis_connection() as redis_connection:
            redis_connection.set(
                "partial_udc:perform_screening",
                1 if dialog_box_model.perform_screening else 0,
            )
            redis_connection.set(
                "partial_udc:perform_full_dataset",
                1 if dialog_box_model.perform_full_dataset else 0,
            )

        partial_udc_flow = MX3SyncPrefectClient(
            name=settings.PARTIAL_UDC_DEPLOYMENT_NAME, parameters=prefect_parameters
        )
        try:
            partial_udc_flow.trigger_data_collection(sample_id, mode="partial_udc")
            logging.getLogger("user_level_log").info(
                "Partial UDC completed successfully."
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
        # Grid Scan Properties
        grid_scan_properties = get_grid_scan_schema(partial_udc=True)

        # Screening Properties
        resolution_limits = self.resolution.get_limits()
        screening_properties = get_screening_schema(resolution_limits)

        # Full Dataset Properties
        full_dataset_properties = get_full_dataset_schema(resolution_limits)

        with get_redis_connection() as redis_connection:
            perform_screening = bool(
                int(
                    redis_connection.get("partial_udc:perform_screening") or 0
                )  # False by default
            )
            perform_full_dataset = bool(
                int(
                    redis_connection.get("partial_udc:perform_full_dataset") or 0
                )  # False by default
            )

        dialog = {
            "properties": {
                "grid_scan": {
                    "type": "object",
                    "title": "Grid Scan Parameters",
                    "properties": grid_scan_properties,
                    "required": [
                        "md3_alignment_y_speed",
                        "transmission",
                    ],
                },
                "perform_screening": {
                    "type": "boolean",
                    "title": "Perform Screening",
                    "default": perform_screening,
                },
                "perform_full_dataset": {
                    "type": "boolean",
                    "title": "Perform Full Dataset",
                    "default": perform_full_dataset,
                },
            },
            "required": ["grid_scan"],
            "allOf": [
                {
                    "if": {"properties": {"perform_screening": {"const": True}}},
                    "then": {
                        "properties": {
                            "screening": {
                                "type": "object",
                                "title": "Screening Parameters",
                                "properties": screening_properties,
                                "required": [
                                    "exposure_time",
                                    "omega_range",
                                    "number_of_frames",
                                    "resolution",
                                    "crystal_counter",
                                    "transmission",
                                ],
                            }
                        }
                    },
                },
                {
                    "if": {"properties": {"perform_full_dataset": {"const": True}}},
                    "then": {
                        "properties": {
                            "full_dataset": {
                                "type": "object",
                                "title": "Dataset Parameters",
                                "properties": full_dataset_properties,
                                "required": [
                                    "exposure_time",
                                    "omega_range",
                                    "number_of_frames",
                                    "resolution",
                                    "crystal_counter",
                                    "transmission",
                                    "processing_pipeline",
                                ],
                            }
                        }
                    },
                },
            ],
            "dialogName": "Partial UDC Parameters",
        }

        return dialog
