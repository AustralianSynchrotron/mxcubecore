import logging
from enum import Enum

from .ExporterNState import ExporterNState


class MicrodiffZoom(ExporterNState):
    """MicrodiffZoom class"""

    def init(self):
        """Initialize the zoom"""
        super().init()
        try:
            _low, _high = self._exporter.execute("getZoomRange")
            self.set_limits((_low, _high))
        except Exception as e:
            logging.getLogger("HWR").warning(
                f"Failed to get zoom range. Defaulting to (1, 7): {e}"
            )
            self.set_limits((1, 7))

        self._initialise_values()

    def set_limits(self, limits: tuple[int, int] = (None, None)) -> None:
        """
        Set the low and high limits.

        Parameters
        ----------
        limits : tuple[int, int], optional
            two integers tuple (low limit, high limit), by default (None, None)

        Returns
        -------
        None
        """
        self._nominal_limits = limits

    def update_value(self, value: int | Enum | None = None) -> None:
        """
        Updates the zoom value.

        Parameters
        ----------
        value : int | Enum | None, optional
            The new zoom value. If the value is an integer,
            we emit the corresponding enum value.

        Returns
        -------
        None
        """
        if value is not None:
            if isinstance(value, int):
                self.emit("valueChanged", (getattr(self.VALUES, f"LEVEL{value}"),))
            elif isinstance(value, Enum):
                self.emit("valueChanged", (value,))

        # NOTE: In principle adding here `self.emit("pixelsPerMmChanged", (pixels_per_mm))`
        # should update the pixels per mm values in the UI when the zoom level is changed
        # externally, but this does not work.
        # However modifying the SampleView component in mxcubeweb works

    def update_limits(self, limits: tuple[int, int] = None) -> None:
        """
        Check if the limits have changed. Emits signal limitsChanged

        Parameters
        ----------
        limits : tuple[int, int], optional
            The zoom limits, by default None

        Returns
        -------
        None
        """
        if not limits:
            limits = self.get_limits()

        # All values are not None nor NaN
        self._nominal_limits = limits
        self.emit("limitsChanged", (limits,))

    def _initialise_values(self) -> None:
        """
        Initialise the ValueEnum from the limits

        Returns
        -------
        None
        """
        low, high = self.get_limits()

        values = {f"LEVEL{v}": v for v in range(low, high + 1)}
        self.VALUES = Enum(
            "ValueEnum",
            dict(values, **{item.name: item.value for item in self.VALUES}),
        )
