"""
Class for cameras connected by EPICS Area Detector
"""
import logging
import os
from io import BytesIO
from threading import Thread

import gevent
import numpy as np
from PIL import Image

from mxcubecore.BaseHardwareObjects import HardwareObject
from mxcubecore.HardwareObjects.ANSTO.BlackFlyCam import BlackFlyCam
from mxcubecore.HardwareObjects.ANSTO.ImgPlugin import ImgPlugin


class Camera(HardwareObject):
    def __init__(self, name: str) -> None:
        """Constructor for Camera class

        Parameters
        ----------
        name : str
            Human readeable name of the hardware

        Returns
        -------
        None
        """
        HardwareObject.__init__(self, name)

        self.liveState = False
        self.refreshing = False
        self.imagegen = None
        self.refreshgen = None
        self.imgArray = None
        self.qImage = None
        self.qImageHalf = None
        self.delay = None
        self.array_size = None
        # Status (cam is getting images)
        # This flag makes errors to be printed only when needed in the log,
        # which prevents the log file to get gigantic.
        self._print_cam_sucess = True
        self._print_cam_error_null = True
        self._print_cam_error_size = True
        self._print_cam_error_format = True

        self.cam = None
        self.img_plugin = None

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
        self.cam = BlackFlyCam(f"{self.pv_prefix}:", name=self.username)
        self.cam.wait_for_connection(timeout=5)

        self.img_plugin = ImgPlugin(f"{self.pv_prefix}:image1:", name="ImagePlugin")
        self.img_plugin.wait_for_connection(timeout=5)

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

    def poll(self) -> None:
        """Poll/Acquisition of the camera images.

        Returns
        -------
        None
        """
        logging.getLogger("HWR").debug("ANSTO Camera image acquiring has started.")

        self.image_generator(self.delay)

    def image_generator(self, delay: float) -> None:
        """Stop camera image acquisition.

        Parameters
        ----------
        delay : float
            Delay to wait the acquisition process.
        """
        while self.liveState:
            self.get_camera_image()
            gevent.sleep(delay)

        logging.getLogger("HWR").debug("ANSTO Camera image acquiring has stopped.")

    def get_camera_image(self) -> int:
        """Get camera image by converting into RGB and in JPEG format.

        Returns
        -------
        int
            Returns -1 for error and 0 for success
        """
        self.imgArray = self.img_plugin.array_data.get()
        if self.imgArray is None:
            if self._print_cam_error_null:
                logging.getLogger("HWR").error(
                    f"{self.__class__.__name__} - Error: null camera image!"
                )

                self._print_cam_sucess = True
                self._print_cam_error_null = False
                self._print_cam_error_size = True
                self._print_cam_error_format = True
            # Return error for this frame, but cam remains live for new frames
            return -1

        if len(self.imgArray) != self.array_size:
            # PS: This check possibly can be removed and the treatment can be
            # moved into the except scope.
            if self._print_cam_error_size:
                logging.getLogger("HWR").error(
                    f"{self.__class__.__name__} - Error in array lenght!"
                    f" Expected {self.array_size},"
                    f" but got {len(self.imgArray)}."
                )

                self._print_cam_sucess = True
                self._print_cam_error_null = True
                self._print_cam_error_size = False
                self._print_cam_error_format = True
            # Try to read sizes again
            self.read_sizes()
            # Return error for this frame, but cam remains live for new frames
            return -1

        if self.refreshing:
            logging.getLogger("user_level_log").info("Camera was refreshed!")

            self.refreshing = False

        try:
            # Get data
            data = self.img_plugin.shaped_image.get()
            arr = data.astype(np.uint8)
            # Convert data to rgb image
            img = Image.fromarray(arr)
            # img_rot = img.rotate(angle=0, expand=True)
            img_rgb = img.convert("RGB")
            # Get binary image
            with BytesIO() as f:
                img_rgb.save(f, format="JPEG")
                f.seek(0)
                img_bin_str = f.getvalue()
            # Sent image to gui
            self.emit("imageReceived", img_bin_str, self.height, self.width)
            # logging.getLogger("HWR").debug('Got camera image: ' + \
            # str(img_bin_str[0:10]))
            if self._print_cam_sucess:
                logging.getLogger("HWR").info(
                    "ANSTO Camera is emitting images! Cam routine is ok."
                )

                self._print_cam_sucess = False
                self._print_cam_error_null = True
                self._print_cam_error_size = True
                self._print_cam_error_format = True
            return 0
        except Exception:
            if self._print_cam_error_format:
                logging.getLogger("HWR").error("Error while formatting camera image")

                self._print_cam_sucess = True
                self._print_cam_error_null = True
                self._print_cam_error_size = True
                self._print_cam_error_format = False
            return -1

    def read_depth(self) -> float:
        """Get the depth of the camera image

        Returns
        -------
        float
            Depth of camera image in mm
        """
        depth = 1
        try:
            depth = self.img_plugin.depth.get()
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
            width = self.img_plugin.width.get()
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
            height = self.img_plugin.height.get()
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
        return True

    @property
    def gain(self) -> float:
        """Get camera gain.

        Returns
        -------
        float
            Gain of the camera.
        """
        gain = None

        try:
            gain = self.cam.gain_rbv.get()
        except Exception:
            logging.getLogger("HWR").error("Error getting gain of camera.")

        return gain

    @gain.setter
    def gain(self, gain: float) -> None:
        """Set the camera gain

        Parameters
        ----------
        gain : float
            Gain of the camera

        Returns
        -------
        None
        """
        try:
            self.cam.gain.put(gain)
        except Exception:
            logging.getLogger("HWR").error("Error setting gain of camera.")

    @property
    def gain_auto(self) -> float:
        """Get camera auto-gain.

        Returns
        -------
        float
            Aut-gain of the camera.
        """
        auto = None

        try:
            auto = self.cam.gain_auto_rbv.get()
        except Exception:
            logging.getLogger("HWR").error("Error getting auto-gain of camera.")

        return auto

    @gain_auto.setter
    def gain_auto(self, gain_auto: float) -> None:
        """Set camera auto-gain.

        Parameters
        ----------
        gain_auto : float
            Auto-gain of the camera

        Returns
        -------
        None
        """
        try:
            self.cam.gain_auto.put(gain_auto)
        except Exception:
            logging.getLogger("HWR").error("Error setting auto-gain of camera.")

    @property
    def exposure_time(self) -> int:
        """Get camera exposure time

        Returns
        -------
        int
            Exposure time of the camera.
        """
        exp = None

        try:
            exp = self.cam.acquire_time_rbv.get()
        except Exception:
            logging.getLogger("HWR").error("Error getting exposure time of camera.")

        return exp

    @exposure_time.setter
    def exposure_time(self, exp: int) -> None:
        """Set the exposure time of the camera.

        Parameters
        ----------
        exp : int
            Exposure time

        Returns
        -------
        None
        """
        try:
            self.cam.acquire_time.put(exp)
        except Exception:
            logging.getLogger("HWR").error("Error setting gain of camera.")

    def start_camera(self) -> None:
        """Start the camera and it's associated plugins.

        Returns
        -------
        None
        """
        try:
            self.cam.array_callbacks.put(1)  # ArrayCallbacks
            self.img_plugin.enable.put(1)  # EnableCallbacks
            self.cam.acquire.put(0)  # Stop the aquisition
            self.cam.acquire.put(1)  # Start the aquisition
        except Exception as e:
            logging.getLogger("HWR").error(e)

    def stop_camera(self) -> None:
        """Stop the camera.

        Returns
        -------
        None
        """
        try:
            self.cam.acquire.put(0)
            self.cam.acquire.put(1)
        except Exception as e:
            logging.getLogger("HWR").error(e)

    def refresh_camera_procedure(self) -> None:
        """Refresh camera procedure by starting the camera
        and restarting the aquisition.

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
        self.start_camera()
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

    def set_live(self, live: bool) -> bool:
        """Start/Stop the camera image acquisition.

        Parameters
        ----------
        live : bool
            A boolean flag to start/stop the acquisition.

        Returns
        -------
        bool
            Status of the acquisition.
        """
        try:
            if live and self.liveState == live:
                return

            self.liveState = live

            if live:
                logging.getLogger("HWR").info("ANSTO Camera is going to poll images")
                # self.delay = float(int(self.getProperty("interval"))/1000.0)
                # the "interval" property is hardcoded at the moment
                self.delay = float(int(100.0 / 1000.0))

                thread = Thread(target=self.poll, daemon=True)
                thread.start()
            else:
                self.stop_camera()

            return True
        except Exception:
            logging.getLogger("HWR").error("Error while polling images")

            return False

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

        self.stop_camera()
        self.set_live(False)
