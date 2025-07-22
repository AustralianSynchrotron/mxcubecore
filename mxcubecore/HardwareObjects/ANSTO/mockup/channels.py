class SimChannel:
    """Only used for SIM mode"""
    def __getattr__(self, name):
        # Return a dummy function for any method
        def dummy(*args, **kwargs):
            return None

        return dummy
    

class SimMd3State(SimChannel):
    """Only used for SIM mode"""

    def get_value(self, *args, **kwargs):
        return "Ready"

class SimMd3Phase(SimChannel):
    """Only used for SIM mode"""

    def get_value(self, *args, **kwargs):
        return "DataCollection"
    

