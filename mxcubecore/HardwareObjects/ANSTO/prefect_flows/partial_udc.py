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
    """Partial UDC Prefect Flow. Allows running:
    - Optical and X-ray Centering
    - Optical and X-ray Centering + Screening
    - Optical and X-ray Centering + Full Dataset
    - Optical and X-ray Centering + Screening + Full Dataset
    """

    def __init__(
        self,
        state,
        resolution: Resolution,
        sample_id: int | None,
    ) -> None:
        super().__init__(state, resolution, sample_id=sample_id)

        self._collection_type = "partial_udc"
        self.grid_step_map = {
            "2.5x2.5": (2.5, 2.5),
            "5x5": (5.0, 5.0),
            "10x10": (10.0, 10.0),
            "20x20": (20.0, 20.0),
        }

    def _check_optical_centering_params(self) -> None:
        """Check that required optical centering parameters are in redis.
        Currently checks por the following parameters:
        - top_camera_target_coords:x_pixel_target
        - top_camera_pixels_per_mm:pixels_per_mm_x

        Additionally gets the following optional parameters from redis:
        - optical_centering:calibrated_alignment_z (default: 0.487 m)
        - optical_centering:grid_height_scale_factor (default: 2)

        Returns
        -------
        None
        """
        with get_redis_connection() as redis_connection:
            if (
                redis_connection.hget("top_camera_target_coords", "x_pixel_target")
                is None
            ):
                msg = (
                    "Top camera target coordinates are not set. "
                    + "Run optical centering calibration before running Partial UDC."
                )
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)
            if (
                redis_connection.hget("top_camera_pixels_per_mm", "pixels_per_mm_x")
                is None
            ):
                msg = (
                    "Top camera pixels per mm are not set. "
                    + "Run optical centering calibration before running Partial UDC."
                )
                logging.getLogger("user_level_log").error(msg)
                raise QueueExecutionException(msg, self)

            # The values below are saved in redis so that they can be changed on the fly
            # if needed while we tune the optical centering params.
            self.calibrated_alignment_z = redis_connection.get(
                "optical_centering:calibrated_alignment_z"
            )
            if self.calibrated_alignment_z is None:
                self.calibrated_alignment_z = 0.487
                logging.getLogger("HWR").warning(
                    f"Calibrated alignment Z not found in redis, using default value: {self.calibrated_alignment_z} m"
                )
            else:
                self.calibrated_alignment_z = float(self.calibrated_alignment_z)

            self.grid_height_scale_factor = redis_connection.get(
                "optical_centering:grid_height_scale_factor"
            )
            if self.grid_height_scale_factor is None:
                self.grid_height_scale_factor = 2
                logging.getLogger("HWR").warning(
                    f"Grid height scale factor not found in redis, using default value: {self.grid_height_scale_factor}"
                )
            else:
                self.grid_height_scale_factor = float(self.grid_height_scale_factor)

    def run(self, dialog_box_parameters: dict) -> None:
        """
        Runs the Partial UDC prefect flow

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

        self._check_optical_centering_params()

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

        if dialog_box_model.run_screening:
            screening_params = ScreeningParams(
                omega_range=screening_model.omega_range,
                exposure_time=screening_model.exposure_time,
                number_of_passes=1,
                count_time=None,
                degrees_per_frame=screening_model.degrees_per_frame,
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

        if dialog_box_model.run_full_dataset:
            full_dataset_params = FullDatasetParams(
                omega_range=full_dataset_model.omega_range,
                exposure_time=full_dataset_model.exposure_time,
                number_of_passes=1,
                count_time=None,
                degrees_per_frame=full_dataset_model.degrees_per_frame,
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
                extra_config=OpticalCenteringExtraConfig(
                    grid_height_scale_factor=self.grid_height_scale_factor
                ),
                grid_step=self.grid_step_map[grid_scan_model.grid_step],
                calibrated_alignment_z=self.calibrated_alignment_z,
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
                use_screening=dialog_box_model.run_screening
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
        if dialog_box_model.run_screening:
            self._save_dialog_box_params_to_redis(
                screening_model, collection_type="screening"
            )
        if dialog_box_model.run_full_dataset:
            self._save_dialog_box_params_to_redis(
                full_dataset_model, collection_type="full_dataset"
            )

        with get_redis_connection() as redis_connection:
            redis_connection.set(
                "partial_udc:run_screening",
                1 if dialog_box_model.run_screening else 0,
            )
            redis_connection.set(
                "partial_udc:run_full_dataset",
                1 if dialog_box_model.run_full_dataset else 0,
            )

        self.prefect_client = MX3SyncPrefectClient(
            name=settings.PARTIAL_UDC_DEPLOYMENT_NAME, parameters=prefect_parameters
        )
        try:
            self.prefect_client.trigger_data_collection(sample_id, mode="partial_udc")
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
        screening_properties = get_screening_schema(resolution_limits, partial_udc=True)

        # Full Dataset Properties
        full_dataset_properties = get_full_dataset_schema(
            resolution_limits, partial_udc=True
        )

        with get_redis_connection() as redis_connection:
            run_screening = bool(
                int(
                    redis_connection.get("partial_udc:run_screening") or 0
                )  # False by default
            )
            run_full_dataset = bool(
                int(
                    redis_connection.get("partial_udc:run_full_dataset") or 0
                )  # False by default
            )

        dialog = {
            "properties": {
                "grid_scan": {
                    "type": "object",
                    "title": "Optical and X-ray Centering",
                    "properties": grid_scan_properties,
                    "required": [
                        "md3_alignment_y_speed",
                        "transmission",
                    ],
                },
                "run_screening": {
                    "type": "boolean",
                    "title": "Screen",
                    "default": run_screening,
                },
                "run_full_dataset": {
                    "type": "boolean",
                    "title": "Dataset",
                    "default": run_full_dataset,
                },
            },
            "required": ["grid_scan"],
            "allOf": [
                {
                    "if": {"properties": {"run_screening": {"const": True}}},
                    "then": {
                        "properties": {
                            "screening": {
                                "type": "object",
                                "title": "Screen Parameters",
                                "properties": screening_properties,
                                "required": [
                                    "exposure_time",
                                    "omega_range",
                                    "resolution",
                                    "transmission",
                                    "degrees_per_frame",
                                ],
                            }
                        }
                    },
                },
                {
                    "if": {"properties": {"run_full_dataset": {"const": True}}},
                    "then": {
                        "properties": {
                            "full_dataset": {
                                "type": "object",
                                "title": "Dataset Parameters",
                                "properties": full_dataset_properties,
                                "required": [
                                    "exposure_time",
                                    "omega_range",
                                    "resolution",
                                    "transmission",
                                    "processing_pipeline",
                                    "degrees_per_frame",
                                ],
                            }
                        }
                    },
                },
            ],
            "dialogName": "Partial UDC Parameters",
        }

        return dialog
