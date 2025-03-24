from typing import (
    Optional,
    Union,
)

from pydantic.v1 import (
    BaseModel,
    Field,
)


# NOTE: The detector_distance and energy units used in
# the ScreeningDialogBox and Prefect ScreeningParams are different
# on purpose
class ScreeningDialogBox(BaseModel):
    exposure_time: float
    omega_range: float
    number_of_frames: int
    detector_distance: float = Field(description="Detector distance in millimeters")
    photon_energy: float = Field(description="Detector distance in keV")
    transmission: float = 0.1
    sample_id: Optional[str] = None
    processing_pipeline: str = "dials"
    crystal_counter: int = 0


class ScreeningParams(BaseModel):
    """Parameters for collecting screening data"""

    start_omega: Optional[float] = Field(
        default=0,
        description="This field does not matter as far as mxcube is concerned"
        "since collection is done at the angle at which the flow is started "
        "from mxcube",
    )
    omega_range: float = Field(
        default=10, description="Global default. Measured in degrees."
    )
    exposure_time: float = Field(description="Measured in seconds.")
    number_of_passes: int = 1
    count_time: float = None
    number_of_frames: int
    detector_distance: float = Field(description="Detector distance in meters")
    photon_energy: float = Field(description="Measured in keV.")
    transmission: float
    beam_size: Union[tuple[int, int], list[int]] = Field(
        default=(80, 80),
        description="Determined by the crystal finder. Not currently used. "
        "Measured in um.",
    )

    class Config:
        extra = "forbid"
