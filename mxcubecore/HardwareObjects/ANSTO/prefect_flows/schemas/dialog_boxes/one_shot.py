from .utils import get_dialog_box_param    


def get_one_shot_schema(resolution_limits: tuple[float, float]) -> dict:
    properties = {
            "exposure_time": {
                "title": "Total Exposure Time [s]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(get_dialog_box_param("exposure_time", collection_type="one_shot")),
                "widget": "textarea",
            },
            "omega_range": {
                "title": "Omega Range [degrees]",
                "type": "number",
                "exclusiveMinimum": 0,
                "default": float(get_dialog_box_param("omega_range", collection_type="one_shot")),
                "widget": "textarea",
            },
            "resolution": {
                "title": "Resolution [Å]",
                "type": "number",
                "minimum": resolution_limits[0],
                "maximum": resolution_limits[1],
                "default": float(get_dialog_box_param("resolution", collection_type="one_shot")),
                "widget": "textarea",
            },
            "transmission": {
                "title": "Transmission [%]",
                "type": "number",
                "minimum": 0,  # TODO: get limits from PV?
                "maximum": 100,
                "default": float(get_dialog_box_param("transmission", collection_type="one_shot")),
                "widget": "textarea",
            },
        }
    return properties