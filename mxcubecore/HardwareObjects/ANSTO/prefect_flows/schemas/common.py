from pydantic import (
    BaseModel,
    Field,
)


class DataCollectionDialogBoxBase(BaseModel):
    """Data Collection Dialog Box Base Model"""

    exposure_time: float
    omega_range: float
    resolution: float = Field(
        description="Measured in Angstrom. This value is converted to "
        "distance in meters internally, which is the parameter "
        "prefect expects"
    )
    # photon_energy: float = Field(description="Photon energy in keV")
    transmission: float = Field(description="Measured in percentage")
    sample_id: int | None = None


class DataCollectionBase(BaseModel):
    """Data Collection Base Model"""

    start_omega: float = Field(
        default=0,
        description="This field does not matter as far as mxcube is concerned "
        "since collection is done at the angle at which the flow is started "
        "from mxcube",
    )
    omega_range: float = Field(
        default=10, description="Global default. Measured in degrees."
    )
    exposure_time: float = Field(description="Measured in seconds.")
    number_of_passes: int = 1
    count_time: float | None = None
    number_of_frames: int
    detector_distance: float = Field(description="Detector distance in meters")
    photon_energy: float = Field(description="Measured in keV.")
    transmission: float = Field(strict=True, ge=0, le=1)
    beam_size: tuple[int, int] | list[int] = Field(
        default=(80, 80),
        description="Determined by the crystal finder. Not currently used. "
        "Measured in um.",
    )

    class Config:
        extra = "forbid"
