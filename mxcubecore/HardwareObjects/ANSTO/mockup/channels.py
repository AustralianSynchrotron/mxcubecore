class SimChannel:
    """Only used for SIM mode"""

    def __init__(self, name: str = "sim_channel", initial_value=None):
        self._name = name
        self._value = initial_value

    def __getattr__(self, name):
        # Return a dummy function for any method
        def dummy(*args, **kwargs):
            return None

        return dummy

    def set_value(self, value):
        self._value = value

    def get_value(self):
        return self._value

    def __call__(self, value=None):
        if value is not None:
            self.set_value(value)
        return self.get_value()

    def name(self):
        return self._name


class SimMd3State(SimChannel):
    """Only used for SIM mode"""

    def get_value(self, *args, **kwargs):
        return "Ready"


class SimMd3Phase(SimChannel):
    """Only used for SIM mode"""

    def get_value(self, *args, **kwargs):
        return "DataCollection"
