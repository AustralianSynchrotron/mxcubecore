import atexit
import os
import signal
import subprocess
import uuid

import psutil

from mxcubecore import BaseHardwareObjects
from mxcubecore.configuration.ansto.config import settings


class MicrodiffCamera(BaseHardwareObjects.HardwareObject):
    """Hardware object for the MD3 camera.
    It starts a video streamer process that reads images from MD3 Redis
    and serves them as an MJPEG or MPEG1 stream.
    """

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

    def get_available_stream_sizes(self) -> list[tuple[int, int]]:
        """Get the available stream sizes

        Returns
        -------
        list[tuple[int, int]]
            A list of available stream sizes as (width, height) tuples. Currently only returns the
        """
        try:
            w, h = self.get_width(), self.get_height()
            video_sizes = [(w, h)]
        except (ValueError, AttributeError):
            video_sizes = []

        return video_sizes

    def set_stream_size(self, w, h) -> None:
        """Set the current stream size."""
        self._current_stream_size = (int(w), int(h))

    def get_stream_size(self) -> tuple[int, int, float]:
        """Get the current stream size and scale factor."""
        width, height = self._current_stream_size
        scale = float(width) / self.get_width()
        return (width, height, scale)

    def clean_up(self):
        """Clean up resources when the hardware object is closed"""
        self.log.info("Shutting down video_stream...")
        if self._video_stream_process and self._video_stream_process.pid:
            os.kill(self._video_stream_process.pid, signal.SIGTERM)

    def start_video_stream_process(self) -> None:
        """Start the video streamer process if it's not already running.
        In simulation mode, the streamer emits a static test image,
        otherwise it reads from MD3 Redis and serves the stream on the configured port.
        """
        if (
            not self._video_stream_process
            or self._video_stream_process.poll() is not None
        ):
            if settings.BL_ACTIVE:
                cmd = [
                    "video-streamer",
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
        """Stop the video streamer process if it's running."""
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
        """Start the video streamer process with the given format, size, and port.

        Parameters
        ----------
        _format : str
            The video format to stream (e.g. "MJPEG" or "MPEG1").
        size : Tuple[int, int]
            The desired stream size as (width, height). If (0, 0), use the camera's native resolution.
        port : str
            The port to serve the video stream on.
        """
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
        """Restart the video streamer process with the current format and given size"""
        self.stop_streaming()
        self.start_streaming(self._format, size=size, port=self._port)

    def connectToDevice(self) -> bool:
        self.connected = True
        return self.connected

    def imageUpdated(self, value) -> None:
        self.log.info("<HW> got new image")
        self.log.info(f"Image value: {value}")

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
