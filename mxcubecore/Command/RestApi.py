import copy
import logging

import httpx

from mxcubecore import Poller
from mxcubecore.CommandContainer import (
    ChannelObject,
    CommandObject,
)
from mxcubecore.dispatcher import saferef


class RestApiCommand(CommandObject):
    """REST API Command"""

    def __init__(self, name, base_url, username=None, args=None, **kwargs):
        CommandObject.__init__(self, name, username, **kwargs)

        self.base_url = base_url
        self.read_value_from_response = kwargs.get("read_value_from_response", True)
        self.pollers = {}
        self.__value_changed_callback_ref = None
        self.__timeout_callback_ref = None

        if args is None:
            self.arg_list = ()
        else:
            # not very nice...
            args = str(args)
            if not args.endswith(","):
                args += ","
            self.arg_list = eval("(" + args + ")")

        if len(self.arg_list) > 1:
            logging.getLogger("HWR").error(
                "RestApiCommand: Only scalar arguments are supported."
            )
            return

        logging.getLogger("HWR").debug(
            "RestApiCommand: initialized with base_url %s", self.base_url
        )

    # def __call__(self, *args, **kwargs):
    #     self.emit("commandBeginWaitReply", (str(self.name()),))

    #     if len(args) > 0 and len(self.arg_list) > 0:
    #         logging.getLogger("HWR").error(
    #             "%s: cannot execute command with arguments when 'args' is defined from XML",
    #             str(self.name()),
    #         )
    #         self.emit("commandFailed", (-1, str(self.name())))
    #         return
    #     elif len(args) == 0 and len(self.arg_list) > 0:
    #         args = self.arg_list

    #     try:
    #         if len(args) == 0:
    #             # Perform a GET request to retrieve the current value
    #             response = httpx.get(urljoin(f"{self.base_url}/value"), timeout=5.0)
    #             response.raise_for_status()
    #             value = response.json() if self.read_as_str else response.text
    #             self.emit("commandReplyArrived", (value, str(self.name())))
    #             return value
    #         else:
    #             # Perform a POST or PUT request to set a new value
    #             value = args[0]
    #             response = httpx.post(
    #                 f"{self.base_url}/value", json={"value": value}, timeout=5.0
    #             )
    #             response.raise_for_status()
    #             self.emit("commandReplyArrived", (0, str(self.name())))
    #             return 0
    #     except httpx.RequestError as e:
    #         logging.getLogger("HWR").error(
    #             "%s: HTTP request error: %s", str(self.name()), str(e)
    #         )
    #     except httpx.HTTPStatusError as e:
    #         logging.getLogger("HWR").error(
    #             "%s: HTTP status error: %s", str(self.name()), str(e)
    #         )
    #     except Exception as e:
    #         logging.getLogger("HWR").error(
    #             "%s: an error occurred: %s", str(self.name()), str(e)
    #         )

    #     self.emit("commandFailed", (-1, str(self.name())))

    def value_changed(self, value):
        try:
            callback = self.__value_changed_callback_ref()
        except Exception:
            pass
        else:
            if callback is not None:
                callback(value)

    def on_polling_error(self, exception, poller_id):
        logging.getLogger("HWR").error(
            "RestApiCommand: Polling error occurred: %s", str(exception)
        )

    def poll(
        self,
        polling_time=1000,
        arguments_list=(),
        value_changed_callback=None,
        timeout_callback=None,
        direct=True,
        compare=True,
    ):
        self.__value_changed_callback_ref = saferef.safe_ref(value_changed_callback)

        def poll_cmd():
            try:
                response = httpx.get(self.base_url, timeout=1)
                response.raise_for_status()
                return (
                    response.json()["value"]
                    if self.read_value_from_response
                    else response.json()
                )
            except Exception as e:
                logging.getLogger("HWR").error(
                    "RestApiCommand: Polling error: %s", str(e)
                )
                return None

        Poller.poll(
            poll_cmd,
            copy.deepcopy(arguments_list),
            polling_time,
            self.value_changed,
            self.on_polling_error,
            compare,
        )

    def stop_polling(self):
        pass

    def abort(self):
        pass

    def is_connected(self):
        try:
            response = httpx.get(self.base_url, timeout=1)
            response.raise_for_status()
            return True
        except Exception:
            return False

    def get_value(self) -> str | int | float:
        try:
            response = httpx.get(self.base_url, timeout=1)
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
        try:
            response = httpx.put(self.base_url, json={"value": value})
            response.raise_for_status()
        except Exception as e:
            logging.getLogger("HWR").error("RestApiCommand: Polling error: %s", str(e))
            return None


class RestApiChannel(ChannelObject):
    """Emulates a REST API channel with a RestApiCommand + polling"""

    def __init__(
        self, name, base_url, username=None, polling=None, args=None, **kwargs
    ):
        ChannelObject.__init__(self, name, username, **kwargs)
        self.command = RestApiCommand(
            name + "_internalCmd", base_url, username, args, **kwargs
        )
        try:
            self.polling = int(polling)
        except Exception:
            self.polling = None

        self.command.poll(self.polling, self.command.arg_list, self.value_changed)

    def value_changed(self, value):
        self.emit("update", value)

    def get_value(self):
        return self.command.get_value()

    def set_value(self, value):
        self.command.set_value(value)

    def is_connected(self):
        return self.command.is_connected()
