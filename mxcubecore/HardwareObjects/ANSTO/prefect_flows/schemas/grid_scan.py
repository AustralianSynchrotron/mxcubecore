from pydantic.v1 import BaseModel
from typing import Optional, Union


class GridScanDialogBox(BaseModel):
    exposure_time: float
    omega_range: float
    detector_distance: float
    photon_energy: float
    hardware_trigger: bool = True
    sample_id: Optional[str] = None


class GridScanParams(BaseModel):
    sample_id: str
    grid_scan_id: int = 0
    grid_top_left_coordinate: Union[tuple[int, int], list[int]]
    grid_height: int
    grid_width: int
    beam_position: Optional[Union[tuple[int, int], list[int]]] = [612, 512]
    number_of_columns: int
    number_of_rows: int
    exposure_time: float
    omega_range: float
    hardware_trigger: bool = False
    detector_distance: float
    photon_energy: float
