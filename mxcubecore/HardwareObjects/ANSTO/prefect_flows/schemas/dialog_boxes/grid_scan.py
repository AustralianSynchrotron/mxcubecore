from .utils import get_dialog_box_param


def get_grid_scan_schema(partial_udc: bool = False) -> dict:
    properties = {
        "md3_alignment_y_speed": {
            "title": "Alignment Y Speed [mm/s]",
            "type": "number",
            "minimum": 0.1,
            "maximum": 14.8,
            "default": float(
                get_dialog_box_param(
                    "md3_alignment_y_speed", collection_type="grid_scan"
                )
            ),
            "widget": "textarea",
        },
        "transmission": {
            "title": "Transmission [%]",
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "default": float(
                get_dialog_box_param("transmission", collection_type="grid_scan")
            ),
            "widget": "textarea",
        },
        "detector_roi_mode": {
            "title": "Detector ROI Mode",
            "type": "string",
            "enum": ["4M", "disabled"],
            "default": str(
                get_dialog_box_param("detector_roi_mode", collection_type="grid_scan")
            ),
            "widget": "select",
        },
    }
    if partial_udc:
        properties["grid_step"] = {
            "title": "Grid Step Size [μm]",
            "type": "string",
            "enum": ["2.5x2.5", "5x5", "10x10", "20x20"],
            "default": str(
                get_dialog_box_param("grid_step", collection_type="grid_scan")
            ),
            "widget": "select",
        }
    return properties
