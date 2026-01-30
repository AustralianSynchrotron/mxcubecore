from typing import (
    Literal,
    Optional,
    Union,
)

from pydantic import (
    BaseModel,
    Field,
)


class GridScanDialogBox(BaseModel):
    detector_roi_mode: Literal["4M", "disabled"]
    md3_alignment_y_speed: float
    # photon_energy: float
    transmission: float = Field(description="Measured in percentage")
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

class MXCubeGridScanParams(BaseModel):
    grid_top_left_coordinate: tuple[int, int] | list[int]
    grid_height: int
    grid_width: int
    number_of_columns: int
    number_of_rows: int
    detector_distance: float
    photon_energy: float
    transmission: float
    omega_range: float = 0
    md3_alignment_y_speed: float
    beam_position: tuple[int, int] | list[int] = (612, 512)
    count_time: float | None = None

class GridScanPrefectFlow(BaseModel):
    sample_id: int
    params: list[MXCubeGridScanParams]
    hardware_trigger: bool = True
    crystal_finder_threshold: int = 1
    number_of_processes: int | None = None
    use_centring_table: bool = True
    detector_roi_mode: Literal["4M", "disabled"] = "4M"