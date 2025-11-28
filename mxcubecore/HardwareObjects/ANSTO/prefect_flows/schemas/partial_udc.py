from enum import StrEnum

from pydantic import (
    BaseModel,
    Field,
    PositiveFloat,
    PositiveInt,
    model_validator,
)

from .full_dataset import FullDatasetDialogBox
from .grid_scan import (
    GridScanDialogBox,
    GridScanParams,
)
from .screening import ScreeningDialogBox


class PartialUDCGridScanDialogBox(GridScanDialogBox):
    grid_step: str = Field(
        description="This is set as a string in the UI and is latter mapped to a tuple"
    )


class PartialUDCDialogBox(BaseModel):
    grid_scan: PartialUDCGridScanDialogBox
    perform_screening: bool = False
    screening: ScreeningDialogBox | None = None
    perform_full_dataset: bool = False
    full_dataset: FullDatasetDialogBox | None = None


# Below are the schemas copied from bluesky_worker single loop data collection flow schema
# Only a subset of the full schema is included here
class OpticalCenteringExtraConfig(BaseModel):
    grid_height_scale_factor: float = 2  # Cut the grid height by this amount


class OpticalCenteringParams(BaseModel):
    beam_position: list[int] | tuple[int, int] = Field(
        default=(612, 512),
        description="Global default. These are pixel (x,y) coordinates",
    )
    grid_step: list[float] | tuple[float, float] = Field(
        default=(80, 80),
        description="Global default. (x,y) grid step measured in micrometers",
    )
    calibrated_alignment_z: float = Field(
        default=0.480,
        description="Calibration parameter. Should be updated regularly",
    )
    extra_config: OpticalCenteringExtraConfig = OpticalCenteringExtraConfig()


class GridScanParams(BaseModel):
    """Parameters for executing grid scans"""

    omega_range: float = Field(description="Global default. Measured in degrees.")
    md3_alignment_y_speed: float = Field(description="Global default. Measured in mm/s")
    detector_distance: float = Field(description="Global default. Measured in meters.")
    photon_energy: float = Field(description="Global default. Measured in keV.")
    transmission: float = Field(strict=True, ge=0, le=1, default=0.1)
    crystal_finder_threshold: int = Field(default=1, description="Global default.")

    number_of_processes: int | None = None


class DataCollectionBase(BaseModel):

    start_omega: float = Field(
        default=0, description="Output from PyBest. Measured in degrees."
    )
    omega_range: PositiveFloat = Field(
        description="Output from PyBest. Measured in degrees."
    )
    number_of_passes: int = 1
    count_time: PositiveFloat | None = None

    detector_distance: PositiveFloat = Field(
        default=0.3, description="Output from PyBest. Measured in m."
    )
    photon_energy: PositiveFloat = Field(
        default=13, description="Global default. Measured in keV."
    )
    transmission: float = Field(strict=True, ge=0, le=1, default=0.1)
    beam_size: tuple[PositiveInt, PositiveInt] | list[PositiveInt] = Field(
        default=(80, 80),
        description="Determined by the crystal finder. Not currently used. "
        "Measured in um.",
    )

    # Any pair of the following parameters can be defined:
    exposure_time: PositiveFloat | None = Field(
        default=None, description="Measured in seconds."
    )
    number_of_frames: PositiveInt | None = Field(
        default=None,
    )
    oscillation_speed: PositiveFloat | None = Field(
        default=None,
        description="Measured in degrees/s",
    )
    frame_rate: PositiveFloat | None = Field(
        default=None,
        description="Measured in Hz",
    )

    @model_validator(mode="after")
    def calculate_params(self):  # noqa
        if len(self.__dict__) == 0:
            return self

        exposure_time = self.exposure_time
        number_of_frames = self.number_of_frames
        oscillation_speed = self.oscillation_speed
        frame_rate = self.frame_rate
        omega_range = self.omega_range

        # Ensure exactly two parameters are set
        self.ensure_params_are_consistent(
            exposure_time, number_of_frames, oscillation_speed, frame_rate, omega_range
        )

        # Calculate the missing parameters
        if exposure_time is None:
            exposure_time = self.calculate_exposure_time(
                number_of_frames, oscillation_speed, frame_rate, omega_range
            )
            self.exposure_time = exposure_time
        if number_of_frames is None:
            number_of_frames = self.calculate_number_of_frames(
                exposure_time, oscillation_speed, frame_rate, omega_range
            )
            self.number_of_frames = number_of_frames
        if oscillation_speed is None:
            oscillation_speed = self.calculate_oscillation_speed(
                exposure_time, number_of_frames, frame_rate, omega_range
            )
            self.oscillation_speed = oscillation_speed
        if frame_rate is None:
            frame_rate = self.calculate_frame_rate(exposure_time, number_of_frames)
            self.frame_rate = frame_rate

        return self

    def ensure_params_are_consistent(
        self,
        exposure_time,
        number_of_frames,
        oscillation_speed,
        frame_rate,
        omega_range,
    ):
        set_params = []
        for param in [
            exposure_time,
            number_of_frames,
            oscillation_speed,
            frame_rate,
        ]:
            if param is not None:
                set_params.append(param)

        if len(set_params) == 4:
            if round(exposure_time, 3) != round(number_of_frames / frame_rate, 3):
                raise ConsistencyError(
                    "Exposure time, number of frames, and frame rate are inconsistent."
                )
            if round(oscillation_speed, 3) != round(
                omega_range * frame_rate / number_of_frames, 3
            ):
                raise ConsistencyError(
                    "Oscillation speed, omega range, and number of frames are "
                    "inconsistent."
                )
        elif len(set_params) == 3:
            if exposure_time is None:
                if round(oscillation_speed, 3) != round(
                    omega_range * frame_rate / number_of_frames, 3
                ):
                    raise ConsistencyError(
                        "Oscillation speed, omega range, and number of frames are "
                        "inconsistent."
                    )
            elif number_of_frames is None:
                if round(exposure_time, 3) != round(omega_range / oscillation_speed, 3):
                    raise ConsistencyError(
                        "Exposure time, omega range, and oscillation speed are "
                        "inconsistent."
                    )
            elif oscillation_speed is None:
                if round(exposure_time, 3) != round(number_of_frames / frame_rate, 3):
                    raise ConsistencyError(
                        "Exposure time, number of frames, and frame rate are inconsistent."
                    )
            elif frame_rate is None:
                if round(exposure_time, 3) != round(omega_range / oscillation_speed, 3):
                    raise ConsistencyError(
                        "Exposure time, number of frames, and oscillation speed are "
                        "inconsistent."
                    )
            elif len(set_params) < 1:
                raise ConsistencyError(
                    "Exactly 2 or more parameters of 'exposure_time', 'number_of_frames', "
                    "'oscillation_speed', 'frame_rate' must be set."
                )

    def calculate_exposure_time(
        self, number_of_frames, oscillation_speed, frame_rate, omega_range
    ):
        if number_of_frames is None and frame_rate is not None:
            number_of_frames = omega_range * frame_rate / oscillation_speed
        elif number_of_frames and oscillation_speed:
            frame_rate = number_of_frames * oscillation_speed / omega_range
        return number_of_frames / frame_rate

    def calculate_number_of_frames(
        self, exposure_time, oscillation_speed, frame_rate, omega_range
    ):
        if exposure_time and frame_rate:
            return round(exposure_time * frame_rate)
        elif exposure_time and oscillation_speed:
            raise ValueError(
                "Cannot calculate frame rate and number of frames "
                "from exposure time and oscillation speed"
            )

    @staticmethod
    def calculate_oscillation_speed(
        exposure_time, number_of_frames, frame_rate, omega_range
    ):
        if number_of_frames is not None and exposure_time is not None:
            frame_rate = number_of_frames / exposure_time
        elif exposure_time is not None and frame_rate is not None:
            number_of_frames = exposure_time * frame_rate
        return omega_range * frame_rate / number_of_frames

    @staticmethod
    def calculate_frame_rate(exposure_time, number_of_frames):
        return number_of_frames / exposure_time


class ScreeningParams(DataCollectionBase):
    """Parameters for collecting screening data"""


class FullDatasetParams(DataCollectionBase):
    """Parameters for collecting full datasets"""

    rotation_axis_offset: int | None = Field(
        default=None,
        description="Output from RadDose. Not yet implemented. Measured in um.",
    )


class ProjectStrategy(BaseModel):
    """Parameters for what to collect on, and when to stop"""

    use_screening: bool = Field(default=True, description="User defined")
    use_dose: bool = Field(
        default=False, description="User defined. Not yet implemented."
    )
    use_rotation_axis_offset: bool = Field(
        default=True, description="User defined. Not yet implemented."
    )

    # Full dataset targets
    target_av_dose: float | None = Field(
        default=None, description="User defined. Not yet implemented. Measured in MGy."
    )
    target_completeness: float | None = Field(
        default=None,
        description="User defined. Measured in percent.",
    )
    target_multiplicity: float | None = Field(
        default=None, description="User defined. Measured in factor."
    )
    target_resolution: float | None = Field(
        default=None, description="User defined. Measured in Å."
    )

    # Screening targets
    screening_target_resolution: float | None = Field(
        default=None,
        description="If None, it is automatically calculated as "
        "target_resolution + 1 [Å] (if target_resolution is not None).",
    )

    # Project criteria
    n_datasets_better_than: int | None = Field(
        default=None, description="User defined."
    )

    @model_validator(mode="before")
    @classmethod
    def set_screening_target_resolution(cls, values: dict):  # noqa
        """if target_resolution is not None, sets the screening target
        resolution to (target_resolution + 1) [Å]
        """
        if values.get("screening_target_resolution") is None:
            if values.get("target_resolution") is not None:
                values["screening_target_resolution"] = values["target_resolution"] + 1
                return values
        return values

    @model_validator(mode="before")
    @classmethod
    def validate_n_datasets_better_than(cls, values: dict):  # noqa
        """
        Checks that at least one target value has been given
        if `n_datasets_better_than` is not None
        """
        keys = [
            "target_av_dose",
            "target_completeness",
            "target_multiplicity",
            "target_resolution",
        ]
        key_vals = []
        if values.get("n_datasets_better_than") is not None:
            for key in keys:
                key_vals.append(values.get(key))
            if not any(key_vals):
                raise ValueError(
                    "n_datasets_better_than has been specified, but no target values "
                    "have been given. Update the ProjectStrategy schema."
                )
            return values
        return values


class ProcessingPipeline(StrEnum):
    DIALS = "dials"
    FAST_DP = "fast_dp"
    DIALS_AND_FAST_DP = "dials_and_fast_dp"
    DOZOR = "dozor"
    FAST_DP_AND_XIA2 = "fast_dp_and_xia2"
    XIA2 = "xia2"


class SingleLoopDataCollectionConfig(BaseModel):
    """Input of the UDC and partial UDC prefect flow"""

    optical_centering: OpticalCenteringParams = OpticalCenteringParams()
    grid_scan: GridScanParams
    screening: ScreeningParams | None = None
    full_dataset: FullDatasetParams | None = None
    project_strategy: ProjectStrategy = ProjectStrategy()
    processing_pipeline: ProcessingPipeline = ProcessingPipeline.FAST_DP

    mount_pin_at_start_of_flow: bool = Field(
        default=True, description="Only must be changed for debugging"
    )
    # Parameters used only for debugging purposes
    add_dummy_pin_to_db: bool = Field(
        default=False, description="Only must be True for debugging"
    )


class ConsistencyError(Exception):
    pass
