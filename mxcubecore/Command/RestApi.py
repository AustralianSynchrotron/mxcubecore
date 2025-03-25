import logging
from typing import (
    Any,
    Callable,
)

import httpx

from mxcubecore import Poller
from mxcubecore.CommandContainer import (
    ChannelObject,
    CommandObject,
)
from mxcubecore.dispatcher import saferef


class RestApiCommand(CommandObject):
    """
    A REST API Command class for polling and interacting with REST APIs, e.g.
    the Dectris SIMPLON API
    """

    def __init__(self, name: str, url: str, username: str | None, **kwargs):
        """
        Parameters
        ----------
        name : str
            The name of the Command object
        url : str
            The full url, e.g. "http://localhost:8000/detector/api/1.8.0/status/state"
        username : str | None, optional
            The username, by default None
        """
        CommandObject.__init__(self, name, username, **kwargs)

        self.url = url
        self.read_value_from_response = kwargs.get("read_value_from_response", True)
        self.pollers = {}
        self.__value_changed_callback_ref = None

        logging.getLogger("HWR").debug(
            "RestApiCommand: initialized with url %s", self.url
        )

    def value_changed(self, value: Any):
        """
        Calls the callback function when the value changes.

        Parameters
        ----------
        value : Any
            The new value to be passed to the callback function.
        """
        try:
            callback = self.__value_changed_callback_ref()
        except Exception:
            pass
        else:
            if callback is not None:
                callback(value)

    def on_polling_error(self, exception: Exception, poller_id: int) -> None:
        """
        Handles errors that occur during polling.

        Parameters
        ----------
        exception : Exception
            The exception that occurred during polling.
        poller_id : int
            The ID of the poller that encountered the error.
        """
        logging.getLogger("HWR").error(
            "RestApiCommand: Polling error occurred: %s", str(exception)
        )

    def _poll_cmd(self) -> Any:
        """
        Executes a polling command by sending an HTTP request to self.url

        Returns
        -------
        Any
            The value from the JSON response if `read_value_from_response`
            is True, otherwise the entire JSON response. Returns None if an
            error occurs
        """

        try:
            response = httpx.get(self.url, timeout=1)
            response.raise_for_status()
            return (
                response.json()["value"]
                if self.read_value_from_response
                else response.json()
            )
        except Exception as e:
            logging.getLogger("HWR").error("RestApiCommand: Polling error: %s", str(e))
            return None

    def poll(
        self,
        polling_time: int = 1000,
        value_changed_callback: Callable | None = None,
        timeout_callback: Callable | None = None,
        direct: bool = True,
        compare: bool = True,
    ):
        """
        Starts polling the REST API endpoint

        Parameters
        ----------
        polling_time : int, optional
            The polling interval, by default 1000.
        value_changed_callback : Callable, optional
            A callback function to be called when the polled value changes, by default None.
        timeout_callback : Callable, optional
            A callback function to be called on timeout, by default None.
        direct : bool, optional
            Whether to directly call the callback, by default True.
        compare : bool, optional
            Whether to compare the new and old value before calling the callback,
            by default True.
        """
        self.__value_changed_callback_ref = saferef.safe_ref(value_changed_callback)

        Poller.poll(
            self._poll_cmd,
            (),
            polling_time,
            self.value_changed,
            self.on_polling_error,
            compare,
        )

    def stop_polling(self):
        """
        Stops polling
        """
        pass

    def abort(self):
        """
        Aborts the current operation.
        """
        pass

    def is_connected(self) -> bool:
        """
        Checks if the REST API endpoint is connected

        Returns
        -------
        bool
            True if the endpoint is connected, False otherwise
        """
        try:
            response = httpx.get(self.url, timeout=1)
            response.raise_for_status()
            return True
        except Exception:
            return False

    def get_value(self) -> Any:
        """
        Retrieves the current value from the REST API endpoint.

        Returns
        -------
        Any
            The value from the JSON response if `read_value_from_response` is True,
            otherwise the entire JSON response. Returns None if an error occurs
        """
        try:
            response = httpx.get(self.url, timeout=1)
            response.raise_for_status()
            return (
                response.json()["value"]
                if self.read_value_from_response
                else response.json()
            )
        except Exception as e:
            logging.getLogger("HWR").error("RestApiCommand: Polling error: %s", str(e))
            return None

    def set_value(self, value) -> None:
        """
        Sets a new value on the REST API endpoint

        Parameters
        ----------
        value : Any
            The new value to set on the endpoint
        """
        try:
            response = httpx.put(self.url, json={"value": value})
            response.raise_for_status()
        except Exception as e:
            logging.getLogger("HWR").error("RestApiCommand: Polling error: %s", str(e))
            return None


class RestApiChannel(ChannelObject):
    """
    A REST API Channel class for polling and interacting with the Dectris SIMPLON API
    """

    def __init__(
        self,
        name: str,
        url: str,
        username: str | None = None,
        polling: int | float | None = None,
        **kwargs
    ):
        """
        Parameters
        ----------
        name : str
            The name of the Command object
        url : str
            The full url, e.g. "http://localhost:8000/detector/api/1.8.0/status/state"
        username : str | None, optional
            The username, by default None
        polling: int | float | None = None
            The polling interval in milliseconds
        """
        ChannelObject.__init__(self, name, username, **kwargs)
        self.command = RestApiCommand(name + "_internalCmd", url, username, **kwargs)
        try:
            self.polling = int(polling)
        except Exception:
            self.polling = None

        self.command.poll(self.polling, self.value_changed)

    def value_changed(self, value: Any):
        """
        Emits an update signal when the value changes

        Parameters
        ----------
        value : Any
            The new value to emit
        """
        self.emit("update", value)

    def get_value(self) -> Any:
        """
        Retrieves the current value from the REST API command

        Returns
        -------
        Any
            The current value obtained from self.url
        """
        return self.command.get_value()

    def set_value(self, value) -> None:
        """
        Sets a new value on the REST API command

        Parameters
        ----------
        value : Any
            The new value to set on self.url
        """
        self.command.set_value(value)

    def is_connected(self) -> bool:
        """
        Checks if the REST API command is connected

        Returns
        -------
        bool
            True if the REST API command is connected, False otherwise
        """
        return self.command.is_connected()
