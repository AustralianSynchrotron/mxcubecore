from typing import (
    Optional,
    Union,
)

from pydantic import (
    BaseModel,
    Field,
)


class GridScanDialogBox(BaseModel):
    md3_alignment_y_speed: float
    # photon_energy: float
    transmission: float = Field(description="Measured in percentage")
    auto_create_well: bool = Field(
        default=False, description="If True, a well will be added to the db automatically "
        "if it does not exist (only used for trays, not pins)"
    )
    project_name: str | None = Field(
        default=None, description="The name of the project and the lab in the format "
        "<project_name> (Lab: <lab_name>). Only used if auto_create_well=True"
    )


class GridScanParams(BaseModel):
    sample_id: int
    grid_scan_id: Union[str, int]
    grid_top_left_coordinate: Union[tuple[int, int], list[int]]
    grid_height: int
    grid_width: int
    number_of_columns: int
    number_of_rows: int
    detector_distance: float = Field(description="Distance measured in meters")
    photon_energy: float
    omega_range: float = 0
    md3_alignment_y_speed: float = 1
    beam_position: Union[tuple[int, int], list[int]] = (612, 512)
    count_time: Optional[float] = None
    hardware_trigger: bool = True
    crystal_finder_threshold: int = 1
    number_of_processes: Optional[float] = None
    transmission: float = Field(strict=True, ge=0, le=1)
    use_centring_table: bool
