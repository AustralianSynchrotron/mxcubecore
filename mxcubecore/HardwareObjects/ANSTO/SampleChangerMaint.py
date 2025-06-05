import time
from typing import Literal
import logging

import gevent

from mxcubecore.BaseHardwareObjects import Equipment
from mxcubecore.TaskUtils import task


class SampleChangerMaint(Equipment):
    """ """

    __TYPE__ = "IRELEC_ISARA2_MAINT"

    def __init__(self, *args, **kwargs):
        Equipment.__init__(self, *args, **kwargs)

        self._state = "READY"
        self._running = 0
        self._powered = 0
        self._toolopen = 0
        self._message = "Nothing to report"
        self._regulating = 0
        self._lid1state = 0
        self._lid2state = 0
        self._lid3state = 0
        self._charging = 0
        self._currenttool = 1

    def init(self):
        """ """

    def get_current_tool(self):
        return self._currenttool

    ################################################################################
    def _do_abort(self):
        self._update_abort_state(True)
        self._update_message("Aborting current operation...")

        gevent.sleep(2)  # Simulate some processing time

        self._update_message("Aborted")
        self._update_abort_state(False)

    def _do_home(self):
        self._update_home_state(True)
        self._update_message("Homing...")

        gevent.sleep(2)  # Simulate some processing time
        self._update_message("Homing completed")
        self._update_home_state(False)

    def _do_soak(self):
        self._update_soak_state(True)
        self._update_message("Soaking...")

        gevent.sleep(2)  # Simulate some processing time
        self._update_message("Soaking completed")
        self._update_soak_state(False)
    
    def _do_reset(self):
        pass

    def _do_dry_gripper(self):
        self._update_dry_state(True)
        self._update_message("Drying gripper...")
        gevent.sleep(2)  # Simulate some processing time
        self._update_message("Gripper dried")
        self._update_dry_state(False)


    def _do_set_on_diff(self, sample):
        pass

    def _do_power_state(self, state=False):
        """ """
        if state:
            self._update_message("Powering on...")
        else:
            self._update_message("Powering off...")
        self._powered = state
        self._update_powered_state(state)

        if state:
            self._update_message("Powered on")
        else:
            self._update_message("Powered off")

    def _do_enable_regulation(self):
        pass

    def _do_disable_regulation(self):
        pass

    def _do_lid1_state(self, state=True):
        pass

    def _do_lid2_state(self, state=True):
        pass

    def _do_lid3_state(self, state=True):
        pass

    #########################          PROTECTED          #########################

    def _execute_task(self, wait, method, *args):
        ret = self._run(method, *args)
        if wait:
            return ret.get()
        else:
            return ret

    @task
    def _run(self, method, *args):
        exception = None
        ret = None
        try:
            ret = method(*args)
        except Exception as ex:
            exception = ex
        if exception is not None:
            raise exception  # pylint: disable-msg=E0702
        return ret

    #########################           PRIVATE           #########################
    def _update_abort_state(self, value):
        """Update the abort state and emit the corresponding signal."""
        self._running = value
        self.emit("abortStateChanged", (value,))
        self._update_global_state()

    def _update_soak_state(self, value):
        """Update the soak state and emit the corresponding signal."""
        self._running = value
        self.emit("soakStateChanged", (value,))
        self._update_global_state()

    def _update_dry_state(self, value):
        """Update the dry state and emit the corresponding signal."""
        self._running = value
        self.emit("dryStateChanged", (value,))
        self._update_global_state()

    def _update_home_state(self, value):
        """Update the home state and emit the corresponding signal."""
        self._running = value
        self.emit("homeStateChanged", (value,))
        self._update_global_state()

    def _update_running_state(self, value):
        self._running = value
        self.emit("runningStateChanged", (value,))
        self._update_global_state()

    def _update_powered_state(self, value):
        self._powered = value
        self.emit("powerStateChanged", (value,))
        self._update_global_state()

    def _update_tool_state(self, value):
        self._toolopen = value
        self.emit("toolStateChanged", (value,))
        self._update_global_state()

    def _update_message(self, value):
        self._message = value
        self.emit("messageChanged", (value,))
        self._update_global_state()

    def _update_regulation_state(self, value):
        self._regulating = value
        self.emit("regulationStateChanged", (value,))
        self._update_global_state()

    def _update_state(self, value):
        self._state = value
        self._update_global_state()

    def _update_lid1_state(self, value):
        self._lid1state = value
        self.emit("lid1StateChanged", (value,))
        self._update_global_state()

    def _update_lid2_state(self, value):
        self._lid2state = value
        self.emit("lid2StateChanged", (value,))
        self._update_global_state()

    def _update_lid3_state(self, value):
        self._lid3state = value
        self.emit("lid3StateChanged", (value,))
        self._update_global_state()

    def _update_operation_mode(self, value):
        self._charging = not value

    def _update_global_state(self):
        state_dict, cmd_state, message = self.get_global_state()
        self.emit("globalStateChanged", (state_dict, cmd_state, message))

    def get_global_state(self):
        """
        Update clients with a global state that
        contains different:

        - first param (state_dict):
            collection of state bits

        - second param (cmd_state):
            list of command identifiers and the
            status of each of them True/False
            representing whether the command is
            currently available or not

        - message
            a message describing current state information
            as a string
        """
        _ready = str(self._state) in ("READY", "ON")

        if self._running:
            state_str = "MOVING"
        elif not (self._powered) and _ready:
            state_str = "DISABLED"
        elif _ready:
            state_str = "READY"
        else:
            state_str = str(self._state)

        state_dict = {
            "toolopen": self._toolopen,
            "powered": self._powered,
            "running": self._running,
            "regulating": self._regulating,
            "lid1": self._lid1state,
            "lid2": self._lid2state,
            "lid3": self._lid3state,
            "state": state_str,
        }

        cmd_state = {
            "powerOn": (not self._powered) and _ready,
            "powerOff": (self._powered) and _ready,
            "abort": not self._running and _ready,
            "home": not self._running and _ready,
            "dry": not self._running and _ready,
            "soak": not self._running and _ready,
        }

        message = self._message

        return state_dict, cmd_state, message

    def get_cmd_info(self):
        """return information about existing commands for this object
        the information is organized as a list
        with each element contains
        [ cmd_name,  display_name, category ]
        """
        """ [cmd_id, cmd_display_name, nb_args, cmd_category, description ] """

        positions = [
                "Positions",
                [
                    ["home", "Home", "Home (trajectory)"],
                    ["dry", "Dry", "Dry (trajectory)"],
                    ["soak", "Soak", "Soak (trajectory)"],
                ],
            ]
        
        power = [
                "Power",
                [
                    ["powerOn", "PowerOn", "Switch Power On"],
                    ["powerOff", "PowerOff", "Switch Power Off"],
                ],
            ]
        abort = ["Abort", [["abort", "Abort", "Abort running trajectory"]]]
        cmd_list = [
            power,
            positions,
            abort
        ]
        return cmd_list

    def send_command(self, cmd_name, args=None) -> Literal[True]:
        """ """
        logging.getLogger("HWR").info("send_command called with %s", cmd_name)
        if cmd_name == "powerOn":
            self._do_power_state(True)
        elif cmd_name == "powerOff":
            self._do_power_state(False)
        elif cmd_name == "abort":
            self._do_abort()
        elif cmd_name == "home":
            self._do_home()
        elif cmd_name == "dry":
            self._do_dry_gripper()
        elif cmd_name == "soak":
            self._do_soak()
        return True
