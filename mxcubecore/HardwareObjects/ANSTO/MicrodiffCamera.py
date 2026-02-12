"""Class for cameras connected to framegrabbers run by Taco Device Servers"""

import atexit
import os
import signal
import subprocess
import uuid
from typing import (
    List,
    Tuple,
)

import psutil

from mxcubecore import BaseHardwareObjects
from mxcubecore.configuration.ansto.config import settings


class MicrodiffCamera(BaseHardwareObjects.HardwareObject):
    def __init__(self, name):
        super().__init__(name)

    def _init(self):
        self._format = "MPEG1"
        self.stream_hash = ""
        self.connected = False
        self.update_state(BaseHardwareObjects.HardwareObjectState.READY)
        self._video_stream_process = None
        self._current_stream_size = (0, 0)
        self._port = 8002

    def init(self):
        self.log.info("initializing camera object")

    def connectToDevice(self) -> bool:
        self.connected = True
        return self.connected

    def imageUpdated(self, value) -> None:
        print("<HW> got new image")
        print(value)

    def gammaExists(self) -> bool:
        return False

    def contrastExists(self) -> bool:
        return False

    def brightnessExists(self) -> bool:
        return False

    def gainExists(self) -> bool:
        return False

    def get_width(self) -> int:
        return settings.MD3_IMAGE_WIDTH

    def get_height(self) -> int:
        return settings.MD3_IMAGE_HEIGHT

    def set_live(self, state) -> bool:
        self.liveState = state
        return True

    def get_available_stream_sizes(self) -> List[Tuple[int, int]]:
        try:
            w, h = self.get_width(), self.get_height()
            video_sizes = [(w, h)]
        except (ValueError, AttributeError):
            video_sizes = []

        return video_sizes

    def set_stream_size(self, w, h) -> None:
        self._current_stream_size = (int(w), int(h))

    def get_stream_size(self) -> Tuple[int, int, float]:
        width, height = self._current_stream_size
        scale = float(width) / self.get_width()
        return (width, height, scale)

    def clean_up(self):
        self.log.info("Shutting down video_stream...")
        if self._video_stream_process and self._video_stream_process.pid:
            os.kill(self._video_stream_process.pid, signal.SIGTERM)

    def start_video_stream_process(self) -> None:
        if (
            not self._video_stream_process
            or self._video_stream_process.poll() is not None
        ):
            if settings.BL_ACTIVE:
                cmd = [
                    "video-streamer",
                    "-d",
                    "-of",
                    str(self._format),
                    "-uri",
                    f"redis://{settings.MD3_REDIS_HOST}:{settings.MD3_REDIS_PORT}",
                    "-irc",
                    "bzoom:RAW",
                    "-p",
                    str(self._port),
                ]
            else:
                cmd = [
                    "video-streamer",
                    "-d",
                    "-of",
                    str(self._format),
                    "-uri",
                    "test",
                    "-p",
                    str(self._port),
                ]

            if self.stream_hash:
                cmd += ["-id", str(self.stream_hash)]

            self._video_stream_process = subprocess.Popen(
                cmd,
                close_fds=True,
                stdout=subprocess.DEVNULL,
            )

            atexit.register(self.clean_up)

    def stop_streaming(self) -> None:
        if self._video_stream_process:
            try:
                ps = [self._video_stream_process] + psutil.Process(
                    self._video_stream_process.pid
                ).children()
                for p in ps:
                    p.kill()
            except psutil.NoSuchProcess:
                self.log.exception("")

            self._video_stream_process = None

    def start_streaming(self, _format="MPEG1", size=(0, 0), port="8000") -> None:
        self._format = _format
        self._port = port

        if str(self._format).upper() == "MJPEG":
            self.stream_hash = ""
        else:
            if not self.stream_hash:
                self.stream_hash = uuid.uuid4().hex

        if not size[0]:
            _s = int(self.get_width()), int(self.get_height())
        else:
            _s = int(size[0]), int(size[1])

        self.set_stream_size(_s[0], _s[1])
        self.start_video_stream_process()

    def restart_streaming(self, size) -> None:
        self.stop_streaming()
        self.start_streaming(self._format, size=size, port=self._port)
