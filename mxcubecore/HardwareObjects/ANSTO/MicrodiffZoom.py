from enum import Enum
from .ExporterNState import ExporterNState

__copyright__ = """ Copyright © 2020 by the MXCuBE collaboration """
__license__ = "LGPLv3+"


class MicrodiffZoom(ExporterNState):
    """MicrodiffZoom class"""

    def init(self):
        """Initialize the zoom"""
        super().init()

        # check if we have values other that UNKNOWN
        _len = len(self.VALUES) - 1
        if _len > 0:
            # we can only assume that the values are consecutive integers
            # so the limits correspond to the keys.
            self.set_limits((1, _len))
        else:
            # no values in the config file, initialise from the hardware.
            self.set_limits(self._get_range())
            self._initialise_values()

    def set_limits(self, limits=(None, None)):
        """Set the low and high limits.
        Args:
            limits (tuple): two integers tuple (low limit, high limit).
        """
        self._nominal_limits = limits

    def update_value(self, value=None):
        """Check if the value has changed. Emits signal valueChanged.
        Args:
            value: value
        """
        # Make sure that update value of super class always is passed value=None
        # so that _get_value is called to get the Enum value and not the numeric
        # value passed by underlaying event data.
        super().update_value()

    def update_limits(self, limits=None):
        """Check if the limits have changed. Emits signal limitsChanged.
        Args:
            limits (tuple): two integers tuple (low limit, high limit).
        """
        if not limits:
            limits = self.get_limits()

        # All values are not None nor NaN
        self._nominal_limits = limits
        self.emit("limitsChanged", (limits,))

    def _initialise_values(self):
        """Initialise the ValueEnum from the limits"""
        low, high = self.get_limits()

        values = {f"LEVEL{v}": v for v in range(low, high + 1)}
        self.VALUES = Enum(
            "ValueEnum",
            dict(values, **{item.name: item.value for item in self.VALUES}),
        )

    def _get_range(self):
        """Get the zoom range.
        Returns:
            (tuple): two integers tuple - min and max value.
        """
        try:
            _low, _high = self._exporter.execute("getZoomRange")
        except (AttributeError, ValueError):
            _low, _high = 1, 10

        # inf is a problematic value
        if _low == float("-inf"):
            _low = 1

        if _high == float("inf"):
            _high = 10

        return _low, _high