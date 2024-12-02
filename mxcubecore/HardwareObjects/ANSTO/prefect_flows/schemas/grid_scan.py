from typing import (
    Optional,
    Union,
)

from pydantic import BaseModel


class GridScanDialogBox(BaseModel):
    md3_alignment_y_speed: float
    omega_range: float
    detector_distance: float
    photon_energy: float
    hardware_trigger: bool = True
    sample_id: Optional[str] = None


class GridScanParams(BaseModel):
    sample_id: str
    grid_scan_id: Union[str, int]
    grid_top_left_coordinate: Union[tuple[int, int], list[int]]
    grid_height: int
    grid_width: int
    number_of_columns: int
    number_of_rows: int
    detector_distance: float
    photon_energy: float
    omega_range: float = 0
    md3_alignment_y_speed: float = 10
    beam_position: Union[tuple[int, int], list[int]] = (612, 512)
    count_time: Optional[float] = None
    hardware_trigger: bool = True
    crystal_finder_threshold: int = 1
    number_of_processes: Optional[float] = None
