import logging
import os
from io import BytesIO

import gevent
from gevent import monkey  # noqa
from PIL import Image

from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.configuration.ansto.config import settings

# Important to patch socket for redis to work properly with gevent
monkey.patch_socket()  # noqa
from redis.exceptions import ConnectionError

from mxcubecore.HardwareObjects.ANSTO.redis_client import (
    NoFrameFoundError,
    RedisClient,
)


class MicrodiffCamera(HardwareObject):
    """
    This class is used to poll images from the MD3 server when using the Redis protocol.

    Example xml file:

    <device class="ANSTO.MicrodiffCamera">
        <!-- Properties -->
        <username>Camera</username>
        <interval>100</interval>
    </device>
    """

    def __init__(self, name: str) -> None:
        """Constructor for Camera class

        Parameters
        ----------
        name : str
            Human readable name of the hardware

        Returns
        -------
        None
        """
        HardwareObject.__init__(self, name)

        self.liveState = False
        self.refreshing = False
        self.imagegen = None
        self.refreshgen = None
        self.qImage = None
        self.qImageHalf = None
        self.delay = None
        self.array_size = None
        # Status (cam is getting images)
        # This flag makes errors to be printed only when needed in the log,
        # which prevents the log file to get gigantic.
        self._print_cam_success = True
        self._print_cam_error_null = True
        self._print_cam_error_size = True
        self._print_cam_error_format = True

        placeholder_path = os.path.join(
            os.path.dirname(__file__), "camera_unavailable.jpg"
        )
        self.placeholder_img = Image.open(placeholder_path)
        with BytesIO() as f:
            self.placeholder_img.convert("RGB").save(f, format="JPEG")
            f.seek(0)
            self.placeholder_img_bytes = f.getvalue()

    def _init(self) -> None:
        """Object initialization - executed before loading contents

        Returns
        -------
        None
        """
        self.stream_hash = "#"
        self.update_state(self.STATES.READY)

    def init(self) -> None:
        """Object initialization - executed after loading contents

        Returns
        -------
        None
        """

        self.camera_args = {
            "host": settings.MD3_REDIS_HOST,
            "port": settings.MD3_REDIS_PORT,
            "hybrid": "bzoom",
            "first": "acA2500-x5",
            "second": "acA2440-x30",
        }

        self.read_sizes()
        # Start camera image acquisition
        self.set_live(True)
        # Snapshot
        self.centring_status = {"valid": False}
        self.snapshots_procedure = None

    def read_sizes(self) -> None:
        """Set the camera image sizes.

        Returns
        -------
        None
        """
        self.depth = self.read_depth()
        self.width = self.read_width()
        self.height = self.read_height()
        self.array_size = self.read_array_size()

    def get_available_stream_sizes(self):
        try:
            w, h = self.get_width(), self.get_height()
            video_sizes = [(w, h), (int(w / 2), int(h / 2)), (int(w / 4), int(h / 4))]
        except (ValueError, AttributeError):
            video_sizes = []

        return video_sizes

    def image_generator(self) -> None:
        """Get images from the MD3 redis server.
        If a ConnectionError occurs, a placeholder image is emitted and
        we try to reconnect to the redis server.
        """
        while self.liveState:
            try:
                with RedisClient(self.camera_args) as md3_redis_client:
                    while self.liveState:
                        try:
                            self.get_camera_image(md3_redis_client)
                        except ConnectionError as ce:
                            logging.getLogger("HWR").error(
                                f"Redis connection lost: {ce}, reconnecting..."
                            )
                            self._emit_placeholder_image(ce)
                            gevent.sleep(0.02)
                            break
                        except Exception as e:
                            logging.getLogger("HWR").error(f"Error in image generator: {e}")
                            self._emit_placeholder_image(e)
                            break
            except Exception as ce:
                logging.getLogger("HWR").error(
                    f"Redis error: {ce}, retrying in 0.1s..."
                )
                self._emit_placeholder_image(ce)
                gevent.sleep(0.1)

    def get_camera_image(self, md3_redis_client: RedisClient) -> int:
        """Get camera image by converting into RGB and in JPEG format.
        If error occurs, a placeholder image is emitted.

        Returns
        -------
        int
            Returns -1 for error and 0 for success
        """
        try:
            imgArray = md3_redis_client.get_frame()
            self.height = imgArray.height
            self.width = imgArray.width

            img_rgb = imgArray
            if img_rgb.mode != "RGB":
                img_rgb = img_rgb.convert("RGB")
            with BytesIO() as f:
                img_rgb.save(f, format="JPEG")
                f.seek(0)
                img_bin_str = f.getvalue()

            # Send image to mxcubeweb
            self.emit("imageReceived", img_bin_str, self.height, self.width)
            if self._print_cam_success:
                logging.getLogger("HWR").info(
                    "ANSTO Camera is emitting images! Cam routine is ok."
                )

                self._print_cam_success = False
                self._print_cam_error_null = True
                self._print_cam_error_size = True
                self._print_cam_error_format = True
        except NoFrameFoundError as ex:
            self._emit_placeholder_image(ex)

    def _emit_placeholder_image(self, ex: NoFrameFoundError) -> None:
        logging.getLogger("HWR").error(
            f"Error while getting camera image, emitting placeholder: {ex}"
        )
        self.height = self.placeholder_img.height
        self.width = self.placeholder_img.width
        self.emit("imageReceived", self.placeholder_img_bytes, self.height, self.width)

        self._print_cam_success = True
        self._print_cam_error_null = True
        self._print_cam_error_size = True
        self._print_cam_error_format = False

    def read_depth(self) -> float:
        """Get the depth of the camera image

        Returns
        -------
        float
            Depth of camera image in mm
        """
        depth = 1
        try:
            depth = self.cam.depth
            if depth is None or depth <= 0:
                depth = 1
        except Exception:
            logging.getLogger("HWR").error("Error on getting camera pixel size.")

        logging.getLogger("HWR").info(f"Camera pixel size is {depth}.")
        return depth

    def read_width(self) -> float:
        """Get width of the camera image.

        Returns
        -------
        float
            Width of the camera image in mm
        """
        width = 0
        try:
            width = self.cam.width
            if width is None:
                width = 0
        except Exception:
            logging.getLogger("HWR").error("Error on getting camera width.")

        logging.getLogger("HWR").info(f"Camera width is {width}.")

        return width

    def read_height(self) -> float:
        """Get the height of the camera image

        Returns
        -------
        float
            Height of the camera image in mm
        """
        height = 0
        try:
            height = self.cam.height
            if height is None:
                height = 0
        except Exception:
            logging.getLogger("HWR").error("Error on getting camera height.")

        logging.getLogger("HWR").info(f"Camera height is {height}.")

        return height

    def read_array_size(self) -> float:
        """Get array size of the camera image

        Returns
        -------
        float
            Array size of the camera image in mm.
        """
        array_size = -1
        try:
            depth = self.read_depth()
            width = self.read_width()
            height = self.read_height()
            array_size = depth * width * height
        except Exception:
            logging.getLogger("HWR").error("Error on getting camera array size.")

        return array_size

    def get_depth(self) -> float:
        """Get depth of the camera image.

        Returns
        -------
        float
            Depth of the camera image in mm.
        """
        return self.depth

    def get_width(self) -> float:
        """Get width of the camera image.

        Returns
        -------
        float
            Width of the camera image in mm.
        """
        return self.width

    def get_height(self) -> float:
        """Get height of the camera image.

        Returns
        -------
        float
            Height of the camera image in mm.
        """
        return self.height

    def get_array_size(self) -> float:
        """Get array size of the camera image.

        Returns
        -------
        float
            Array size of the camera image in mm.
        """
        return self.array_size

    def get_image_dimensions(self) -> float:
        """Get image dimensions of the camera

        Returns
        -------
        float
            Image dimensions of the camera in mm.
        """
        return self.get_array_size()

    def contrast_exists(self) -> bool:
        """Check whether contrast exists.

        Returns
        -------
        bool
            Returns False.
        """
        return False

    def brightness_exists(self) -> bool:
        """Check whether brightness exists.

        Returns
        -------
        bool
            Returns False
        """
        return False

    def gain_exists(self) -> bool:
        """Check whether gain exists.

        Returns
        -------
        bool
            Returns True
        """
        return False

    def refresh_camera_procedure(self) -> None:
        """Refresh camera procedure by starting the camera
        and restarting the acquisition.

        Returns
        -------
        None
        """
        self.refreshing = True

        # Try to stop camera image acquisition
        self.set_live(False)
        # Wait a while
        gevent.sleep(0.2)
        # Set PVs to start
        # (Re)start camera image acquisition
        self.set_live(True)

    def refresh_camera(self) -> None:
        """Refresh camera

        Returns
        -------
        None
        """
        logging.getLogger("user_level_log").error(
            "Resetting camera, please, wait a while..."
        )

        # Start a new thread to don't freeze UI
        self.refreshgen = gevent.spawn(self.refresh_camera_procedure)

    def set_live(self, live):
        logging.getLogger("HWR").info(f"Setting camera live {live}")
        if live and self.liveState == live:
            return

        if live:
            if self.imagegen and not self.imagegen.dead:
                self.liveState = False
                self.imagegen.join(timeout=1)
            self.liveState = True
            self.imagegen = gevent.spawn(self.image_generator)
        else:
            self.liveState = False
            if self.imagegen and not self.imagegen.dead:
                self.imagegen.join(timeout=1)
                self.imagegen = None
        return True

    def take_snapshots_procedure(
        self,
        image_count: int,
        snapshotFilePath: str,
        snapshotFilePrefix: str,
        logFilePath: str,
        runNumber: int,
        collectStart: int,
        collectEnd: int,
        motorHwobj: HardwareObject,
        detectorHwobj: HardwareObject,
    ) -> None:
        """It takes snapshots of sample camera and camserver execution.

        Parameters
        ----------
        image_count : int
            Number of images.
        snapshotFilePath : str
            Filepath to store the snapshots
        snapshotFilePrefix : str
            File prefix of the snapshot
        logFilePath : str
            Logging filepath
        runNumber : int
            Run number
        collectStart : int
            Collection start position
        collectEnd : int
            Collection end position
        motorHwobj : HardwareObject
            Diffractometer hardware object
        detectorHwobj : HardwareObject
            Detector hardware object

        Returns
        -------
        None
        """
        # Avoiding a processing of AbstractMultiCollect class
        #  for saving snapshots
        # centred_images = []
        centred_images = None
        positions = []

        try:
            # Calculate goniometer positions where to take snapshots
            if collectEnd is not None and collectStart is not None:
                interval = collectEnd - collectStart
            else:
                interval = 0

            # To increment in angle increment
            increment = (
                0 if ((image_count - 1) == 0) else (interval / (image_count - 1))
            )

            for incrementPos in range(image_count):
                if collectStart is not None:
                    positions.append(collectStart + (incrementPos * increment))
                else:
                    positions.append(motorHwobj.getPosition())

            # Create folders if not found
            if not os.path.exists(snapshotFilePath):
                try:
                    os.makedirs(snapshotFilePath, mode=0o700)
                except OSError as e:
                    logging.getLogger().error(
                        f"Snapshot: error trying to create the directory"
                        f" {snapshotFilePath} ({str(e)})"
                    )

            for index in range(image_count):
                while motorHwobj.getPosition() < positions[index]:
                    gevent.sleep(0.02)

                logging.getLogger("HWR").info(
                    f"{self.__class__.__name__}" f" - taking snapshot #{index + 1}"
                )

                # Save snapshot image file
                motor_position = str(round(motorHwobj.getPosition(), 2))
                snapshotFileName = (
                    f"{snapshotFilePrefix}_{motor_position}"
                    f"_{motorHwobj.getEgu()}_snapshot.png"
                )

                imageFileName = os.path.join(snapshotFilePath, snapshotFileName)

                # imageInfo = self.takeSnapshot(imageFileName)

                # This way all shapes will be also saved...
                self.emit("saveSnapshot", imageFileName)

                # Send a command to detector hardware-object
                # to take snapshot of camserver execution...
                if logFilePath and detectorHwobj:
                    detectorHwobj.takeScreenshotOfXpraRunningProcess(
                        image_path=logFilePath, run_number=runNumber
                    )

                # centred_images.append((0, str(imageInfo)))
                # centred_images.reverse()
        except Exception:
            logging.getLogger("HWR").exception(
                f"{self.__class__.__name__}" f" - could not take crystal snapshots"
            )

        return centred_images

    def take_snapshots(
        self,
        image_count: int,
        snapshotFilePath: str,
        snapshotFilePrefix: str,
        logFilePath: str,
        runNumber: int,
        collectStart: int,
        collectEnd: int,
        motorHwobj: HardwareObject,
        detectorHwobj: HardwareObject,
        wait: bool = False,
    ) -> None:
        """It takes snapshots of sample camera and camserver execution.

        Parameters
        ----------
        image_count : int
            Number of images
        snapshotFilePath : str
            Filepath of the snapshot
        snapshotFilePrefix : str
            Prefix of the snapshot file.
        logFilePath : str
            Log filepath
        runNumber : int
            Run number
        collectStart : int
            Collection start position
        collectEnd : int
            Collection end position
        motorHwobj : HardwareObject
            Diffractometer hardware object
        detectorHwobj : HardwareObject
            Detector hardware object
        wait : bool, optional
            Whether to wait to get snapshots, by default False

        Returns
        -------
        None
        """
        if image_count > 0:
            self.snapshots_procedure = gevent.spawn(
                self.take_snapshots_procedure,
                image_count,
                snapshotFilePath,
                snapshotFilePrefix,
                logFilePath,
                runNumber,
                collectStart,
                collectEnd,
                motorHwobj,
                detectorHwobj,
            )

            self.centring_status["images"] = []

            self.snapshots_procedure.link(self.snapshots_done)

            if wait:
                self.centring_status["images"] = self.snapshots_procedure.get()

    def snapshots_done(self, snapshots_procedure: gevent.Greenlet) -> None:
        """Get snapshots

        Parameters
        ----------
        snapshots_procedure : gevent.Greenlet
            Snapshot procedure to take snapshots of camera

        Returns
        -------
        None
        """
        try:
            self.centring_status["images"] = snapshots_procedure.get()
        except Exception:
            logging.getLogger("HWR").exception(
                f"{self.__class__.__name__}" f" - could not take crystal snapshots"
            )

    def cancel_snapshot(self) -> None:
        """Cancel taking of snapshots of the camera.

        Returns
        -------
        None
        """
        try:
            self.snapshots_procedure.kill()
        except Exception as e:
            logging.getLogger("HWR").error(e)

    def __del__(self) -> None:
        """Stop the camera and image acquisition

        Returns
        -------
        None
        """
        logging.getLogger("HWR").exception(f"{self.__class__.__name__} - __del__()!")

        self.set_live(False)
