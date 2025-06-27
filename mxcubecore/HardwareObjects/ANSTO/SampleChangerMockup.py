import logging
import time

from mxcubecore.HardwareObjects.abstract import AbstractSampleChanger
from mxcubecore.HardwareObjects.abstract.sample_changer import Container


class SampleChangerMockup(AbstractSampleChanger.SampleChanger):
    """Sample Changer Mockup class that supports prefetching"""

    __TYPE__ = "Mockup"
    NO_OF_BASKETS = 5
    NO_OF_SAMPLES_IN_BASKET = 10

    def __init__(self, *args, **kwargs):
        super(SampleChangerMockup, self).__init__(self.__TYPE__, False, *args, **kwargs)

    def init(self):
        self._selected_sample = -1
        self._selected_basket = -1
        self._scIsCharging = None

        self.no_of_baskets = self.get_property(
            "no_of_baskets", SampleChangerMockup.NO_OF_BASKETS
        )

        self.no_of_samples_in_basket = self.get_property(
            "no_of_samples_in_basket", SampleChangerMockup.NO_OF_SAMPLES_IN_BASKET
        )

        for i in range(self.no_of_baskets):
            basket = Container.Basket(
                self, i + 1, samples_num=self.no_of_samples_in_basket
            )
            self._add_component(basket)

        self._init_sc_contents()
        self.signal_wait_task = None
        AbstractSampleChanger.SampleChanger.init(self)

    def load(self, sample: str, sample_order: list[str] | None, wait=False) -> None:
        """
        Loads a sample and prefetches the next sample is sample_order is not None.
        Note that to use this class requires modifying the
        SampleChanger class in mxcubeweb (under /mxcubeweb/core/components/samplechanger.py)
        so that the sample_order list is passed to this function

        Parameters
        ----------
        sample : str
            The sample to mount
        sample_order : list[str] | None
            A list containing the sample order, or None if there is no queue. Used
            to prefetch samples
        wait : bool, optional
            Wait for task to complete, by default False

        Returns
        -------
        None
        """

        if sample_order is not None:
            for i in range(len(sample_order)):
                if sample_order[i] == sample:
                    try:
                        prefetch_sample = sample_order[i + 1]
                    except IndexError:
                        prefetch_sample = None
                    break
        else:
            prefetch_sample = None

        logging.getLogger("HWR").info(f"Prefetching sample: {prefetch_sample}")
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", True)
        previous_sample = self.get_loaded_sample()
        self._set_state(AbstractSampleChanger.SampleChangerState.Loading)
        self._reset_loaded_sample()

        if isinstance(sample, tuple):
            basket, sample = sample
        else:
            basket, sample = sample.split(":")

        self._selected_basket = basket = int(basket)
        self._selected_sample = sample = int(sample)

        msg = "Loading sample %d:%d" % (basket, sample)
        logging.getLogger("user_level_log").info(
            "Sample changer: %s. Please wait..." % msg
        )

        self.emit("progressInit", (msg, 100))
        for step in range(2 * 100):
            self.emit("progressStep", int(step / 2.0))
            time.sleep(0.01)

        mounted_sample = self.get_component_by_address(
            Container.Pin.get_sample_address(basket, sample)
        )
        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)

        if mounted_sample is not previous_sample:
            self._trigger_loaded_sample_changed_event(mounted_sample)
        self.update_info()
        logging.getLogger("user_level_log").info("Sample changer: Sample loaded")
        self.emit("progressStop", ())

        self.emit("fsmConditionChanged", "sample_is_loaded", True)
        self.emit("fsmConditionChanged", "sample_mounting_sample_changer", False)

        return self.get_loaded_sample()

    def unload(self, sample_slot=None, wait: bool = None):
        logging.getLogger("user_level_log").info("Unloading sample")
        sample = self.get_loaded_sample()
        sample._set_loaded(False, True)
        self._selected_basket = -1
        self._selected_sample = -1
        self._trigger_loaded_sample_changed_event(self.get_loaded_sample())
        self.emit("fsmConditionChanged", "sample_is_loaded", False)

    def get_loaded_sample(self):
        return self.get_component_by_address(
            Container.Pin.get_sample_address(
                self._selected_basket, self._selected_sample
            )
        )

    def is_mounted_sample(self, sample):
        return (
            self.get_component_by_address(
                Container.Pin.get_sample_address(sample[0], sample[1])
            )
            == self.get_loaded_sample()
        )

    def _init_sc_contents(self) -> None:
        """
        Initializes the sample changer content with default values.

        Returns
        -------
        None
        """
        named_samples = {}
        if self.has_object("test_sample_names"):
            for tag, val in self["test_sample_names"].get_properties().items():
                named_samples[val] = tag

        for basket_index in range(self.no_of_baskets):
            basket = self.get_components()[basket_index]
            datamatrix = None
            present = True
            scanned = False
            basket._set_info(present, datamatrix, scanned)

        sample_list = []
        for basket_index in range(self.no_of_baskets):
            for sample_index in range(self.no_of_samples_in_basket):
                sample_list.append(
                    (
                        "",
                        basket_index + 1,
                        sample_index + 1,
                        1,
                        Container.Pin.STD_HOLDERLENGTH,
                    )
                )
        for spl in sample_list:
            address = Container.Pin.get_sample_address(spl[1], spl[2])
            sample = self.get_component_by_address(address)
            sample_name = named_samples.get(address)
            if sample_name is not None:
                sample._name = sample_name
            datamatrix = "matr%d_%d" % (spl[1], spl[2])
            present = scanned = loaded = has_been_loaded = False
            sample._set_info(present, datamatrix, scanned)
            sample._set_loaded(loaded, has_been_loaded)
            sample._set_holder_length(spl[4])

        self._set_state(AbstractSampleChanger.SampleChangerState.Ready)

    def is_powered(self):
        return True
