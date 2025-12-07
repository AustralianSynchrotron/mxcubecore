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
    auto_create_well: bool = Field(
        default=False,
        description="If True, a well will be added to the db automatically "
        "if it does not exist (only used for trays, not pins)",
    )
    project_name: str | None = Field(
        default=None,
        description="The name of the project. Only used if auto_create_well=True",
    )
    lab_name: str | None = Field(
        default=None,
        description="The name of the lab. Only used if auto_create_well=True",
    )
    sample_name: str | None = Field(
        default=None,
        description="The name of the sample. Only used if auto_create_well=True",
    )


class DataCollectionBase(BaseModel):
    """Data Collection Base Model"""

    start_omega: float | None = Field(
        default=None, description="If None, the current omega position is used"
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
