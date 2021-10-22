from mxcubecore.HardwareObjects.abstract.AbstractSlits import AbstractSlits


__credits__ = ["MXCuBE collaboration"]


class Slits(AbstractSlits):
    def __init__(self, *args):
        AbstractSlits.__init__(self, *args)

    def init(self):
        # Slits start wide open
        self._value = [1.00, 1.00]
        self._min_limits = [0.001, 0.001]
        self._max_limits = [1, 1]

    def set_horizontal_gap(self, value):
        self._value[0] = value
        self.emit("valueChanged", self._value)

    def set_vertical_gap(self, value):
        self._value[1] = value
        self.emit("valueChanged", self._value)

    def stop_horizontal_gap_move(self):
        return

    def stop_vertical_gap_move(self):
        return
