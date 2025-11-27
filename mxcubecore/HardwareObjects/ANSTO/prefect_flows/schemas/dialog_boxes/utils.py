from typing import Literal

from ....redis_utils import get_redis_connection


def get_dialog_box_param(
    parameter: Literal[
        "exposure_time",
        "omega_range",
        "number_of_frames",
        "processing_pipeline",
        "crystal_counter",
        "photon_energy",
        "resolution",
        "md3_alignment_y_speed",
        "transmission",
        "auto_create_well",
        "lab_name",
        "project_name",
    ],
    collection_type: Literal["screening", "full_dataset", "grid_scan", "one_shot"],
) -> str | int | float | None:
    """
    Retrieve a parameter value from Redis.

    Parameters
    ----------
    parameter : Literal[
        "exposure_time",
        "omega_range",
        "number_of_frames",
        "processing_pipeline",
        "crystal_counter",
        "photon_energy",
        "resolution",
        "md3_alignment_y_speed",
        "transmission",
        "auto_create_well",
        "lab_name",
        "project_name",
    ]
        A parameter saved in redis
    collection_type : str | None
        The collection type. If None, use the current collection type

    Returns
    -------
    str | int | float
        The last value set in redis for a given parameter
    """

    with get_redis_connection() as redis_connection:
        if parameter in ["lab_name", "project_name", "auto_create_well"]:
            value = redis_connection.get(f"mxcube_common_params:{parameter}")
        else:
            value = redis_connection.get(f"{collection_type}:{parameter}")

        if parameter == "auto_create_well":
            if value is not None:
                return bool(int(value))
        else:
            return value
