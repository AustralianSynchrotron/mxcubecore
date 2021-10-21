"""
Class for cameras connected by EPICS Area Detector
"""
import os
import logging
import gevent
from io import BytesIO
from threading import Thread

from PIL import Image
import numpy as np

from mxcubecore import BaseHardwareObjects

from mxcubecore.HardwareObjects.ANSTO.BlackFlyCam import BlackFlyCam
from mxcubecore.HardwareObjects.ANSTO.ImgPlugin import ImgPlugin


class Camera(BaseHardwareObjects.Device):
    def __init__(self, name):
        BaseHardwareObjects.Device.__init__(self, name)

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

    def _init(self):
        self.stream_hash = "#"
        self.set_is_ready(True)

    def init(self):
        self.cam = BlackFlyCam(f"{self.pv_prefix}:", name=self.username)
        self.cam.wait_for_connection(timeout=5)

        self.img_plugin = ImgPlugin(
            f"{self.pv_prefix}:image1:", name="ImagePlugin")

        self.read_sizes()
        # Start camera image acquisition
        self.setLive(True)
        # Snapshot
        self.centring_status = {"valid": False}
        self.snapshots_procedure = None

    def read_sizes(self):
        self.depth = self.read_depth()
        self.width = self.read_width()
        self.height = self.read_height()
        self.array_size = self.read_array_size()

    def poll(self):
        logging.getLogger("HWR").debug(
            'ANSTO Camera image acquiring has started.')
        self.imageGenerator(self.delay)

    def imageGenerator(self, delay):
        while self.liveState:
            self.getCameraImage()
            gevent.sleep(delay)
        logging.getLogger("HWR").debug(
            'ANSTO Camera image acquiring has stopped.')

    def getCameraImage(self):
        # Get the image from uEye camera IOC
        self.imgArray = self.img_plugin.array_data.get()
        if self.imgArray is None:
            if self._print_cam_error_null:
                logging.getLogger("HWR").error(
                    "%s - Error: null camera image!" % (self.__class__.__name__))
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
                    "%s - Error in array lenght! Expected %d, but got %d." %
                    (self.__class__.__name__, self.array_size, len(self.imgArray)))
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
            #img_rot = img.rotate(angle=0, expand=True)
            img_rgb = img.convert('RGB')
            # Get binary image
            with BytesIO() as f:
                img_rgb.save(f, format='JPEG')
                f.seek(0)
                img_bin_str = f.getvalue()
            # Sent image to gui
            self.emit("imageReceived", img_bin_str, self.height, self.width)
            # logging.getLogger("HWR").debug('Got camera image: ' + \
            # str(img_bin_str[0:10]))
            if self._print_cam_sucess:
                logging.getLogger("HWR").info(
                    "ANSTOCamera is emitting images! Cam routine is ok.")
                self._print_cam_sucess = False
                self._print_cam_error_null = True
                self._print_cam_error_size = True
                self._print_cam_error_format = True
            return 0
        except:
            if self._print_cam_error_format:
                logging.getLogger("HWR").error(
                    'Error while formatting camera image')
                self._print_cam_sucess = True
                self._print_cam_error_null = True
                self._print_cam_error_size = True
                self._print_cam_error_format = False
            return -1

    def read_depth(self):
        depth = 1
        try:
            depth = self.img_plugin.depth.get()
            if depth is None or depth <= 0:
                depth = 1
        except:
            print("Error on getting camera pixel size.")
        finally:
            logging.getLogger("HWR").info(
                "Camera pixel size is %d." % (depth))
            return depth

    def read_width(self):
        width = 0
        try:
            width = self.img_plugin.width.get()
            if width is None:
                width = 0
        except:
            print("Error on getting camera width.")
        finally:
            logging.getLogger("HWR").info("Camera width is %d." % (width))
            return width

    def read_height(self):
        height = 0
        try:
            height = self.img_plugin.height.get()
            if height is None:
                height = 0
        except:
            print("Error on getting camera height.")
        finally:
            logging.getLogger("HWR").info(
                "Camera height is %d." % (height))
            return height

    def read_array_size(self):
        array_size = -1
        try:
            depth = self.read_depth()
            width = self.read_width()
            height = self.read_height()
            array_size = depth * width * height
        except:
            print("Error on getting camera array size.")
        return array_size

    def get_depth(self):
        return self.depth

    def get_width(self):
        return self.width

    def get_height(self):
        return self.height

    def get_array_size(self):
        return self.array_size

    def getStaticImage(self):
        pass
        # qtPixMap = QtGui.QPixmap(self.source, "1")
        # self.emit("imageReceived", qtPixMap)

    def get_image_dimensions(self):
        return self.get_array_size()

    def getWidth(self):
        # X
        return self.get_width()

    def getHeight(self):
        # Z
        return self.get_height()

    def contrastExists(self):
        return False

    def brightnessExists(self):
        return False

    def gainExists(self):
        return True

    def get_gain(self):
        gain = None

        try:
            gain = self.cam.gain_rbv.get()
        except:
            print("Error getting gain of camera...")

        return gain

    def set_gain(self, gain):
        try:
            self.cam.gain.put(gain)
        except:
            print("Error setting gain of camera...")

    def get_gain_auto(self):
        auto = None

        try:
            auto = self.cam.gain_auto_rbv.get()
        except:
            print("Error getting auto-gain of camera...")

        return auto

    def set_gain_auto(self, gain_auto):
        try:
            self.cam.gain_auto.put(gain_auto)
        except:
            print("Error setting auto-gain of camera...")

    def get_exposure_time(self):
        exp = None

        try:
            exp = self.cam.acquire_time_rbv.get()
        except:
            print("Error getting exposure time of camera...")

        return exp

    def set_exposure_time(self, exp):
        try:
            self.cam.acquire_time.put(exp)
        except:
            print("Error setting exposure time of camera...")

    def start_camera(self):
        try:
            self.cam.array_callbacks.put(1)  # ArrayCallbacks
            self.img_plugin.enable.put(1)  # EnableCallbacks
            self.cam.acquire.put(0)  # Stop the aquisition
            self.cam.acquire.put(1)  # Start the aquisition
        except:
            pass

    def stop_camera(self):
        try:
            self.cam.acquire.put(0)
            self.cam.acquire.put(1)
        except:
            pass

    def refresh_camera_procedure(self):
        self.refreshing = True

        # Try to stop camera image acquisition
        self.setLive(False)
        # Wait a while
        gevent.sleep(0.2)
        # Set PVs to start
        self.start_camera()
        # (Re)start camera image acquisition
        self.setLive(True)

    def refresh_camera(self):
        logging.getLogger("user_level_log").error(
            "Resetting camera, please, wait a while...")
        print("refresh_camera")

        # Start a new thread to don't freeze UI
        self.refreshgen = gevent.spawn(self.refresh_camera_procedure)

    def setLive(self, live):
        try:
            if live and self.liveState == live:
                return

            self.liveState = live

            if live:
                logging.getLogger("HWR").info(
                    "ANSTO Camera is going to poll images")
                # self.delay = float(int(self.getProperty("interval"))/1000.0)
                # the "interval" property is hardcoded at the moment
                self.delay = float(int(100.0/1000.0))
                thread = Thread(target=self.poll)
                thread.daemon = True
                thread.start()
            else:
                self.stop_camera()

            return True
        except:
            logging.getLogger("HWR").error('Error while polling images')
            return False

    def imageType(self):
        return None

    def takeSnapshot(self, *args):
        pass
        # imgFile = QtCore.QFile(args[0])
        # imgFile.open(QtCore.QIODevice.WriteOnly)
        # self.qtPixMap.save(imgFile,"PNG")
        # imgFile.close()

    def take_snapshots_procedure(self, image_count, snapshotFilePath,
                                 snapshotFilePrefix, logFilePath, runNumber,
                                 collectStart, collectEnd, motorHwobj,
                                 detectorHwobj):
        """
        Descript. : It takes snapshots of sample camera
         and camserver execution.
        """
        # Avoiding a processing of AbstractMultiCollect class
        #  for saving snapshots
        # centred_images = []
        centred_images = None
        positions = []

        try:
            # Calculate goniometer positions where to take snapshots
            if (collectEnd is not None and collectStart is not None):
                interval = (collectEnd - collectStart)
            else:
                interval = 0

            # To increment in angle increment
            increment = 0 if ((image_count - 1) ==
                              0) else (interval / (image_count - 1))

            for incrementPos in range(image_count):
                if (collectStart is not None):
                    positions.append(collectStart + (incrementPos * increment))
                else:
                    positions.append(motorHwobj.getPosition())

            # Create folders if not found
            if (not os.path.exists(snapshotFilePath)):
                try:
                    os.makedirs(snapshotFilePath, mode=0o700)
                except OSError as diag:
                    logging.getLogger().error(
                        "Snapshot: error trying to create the directory %s (%s)" %
                        (snapshotFilePath, str(diag)))

            for index in range(image_count):
                while (motorHwobj.getPosition() < positions[index]):
                    gevent.sleep(0.02)

                logging.getLogger("HWR").info(
                    "%s - taking snapshot #%d" %
                    (self.__class__.__name__, index + 1))

                # Save snapshot image file
                motor_position = str(round(motorHwobj.getPosition(), 2))
                snapshotFileName = (f"{snapshotFilePrefix}_{motor_position}"
                                    f"_{motorHwobj.getEgu()}_snapshot.png")

                imageFileName = os.path.join(
                    snapshotFilePath, snapshotFileName)

                # imageInfo = self.takeSnapshot(imageFileName)

                # This way all shapes will be also saved...
                self.emit("saveSnapshot", imageFileName)

                # Send a command to detector hardware-object
                # to take snapshot of camserver execution...
                if (logFilePath and detectorHwobj):
                    detectorHwobj.takeScreenshotOfXpraRunningProcess(
                        image_path=logFilePath, run_number=runNumber)

                # centred_images.append((0, str(imageInfo)))
                # centred_images.reverse()
        except:
            logging.getLogger("HWR").exception(
                "%s - could not take crystal snapshots" %
                (self.__class__.__name__))

        return centred_images

    def take_snapshots(self, image_count, snapshotFilePath, snapshotFilePrefix,
                       logFilePath, runNumber, collectStart, collectEnd,
                       motorHwobj, detectorHwobj, wait=False):
        """
        Descript. :  It takes snapshots of sample camera and
         camserver execution.
        """
        if image_count > 0:
            self.snapshots_procedure = gevent.spawn(
                self.take_snapshots_procedure, image_count, snapshotFilePath,
                snapshotFilePrefix, logFilePath, runNumber, collectStart,
                collectEnd, motorHwobj, detectorHwobj)

            self.centring_status["images"] = []

            self.snapshots_procedure.link(self.snapshots_done)

            if wait:
                self.centring_status["images"] = self.snapshots_procedure.get()

    def snapshots_done(self, snapshots_procedure):
        """
        Descript. :
        """
        try:
            self.centring_status["images"] = snapshots_procedure.get()
        except:
            logging.getLogger("HWR").exception(
                "%s - could not take crystal snapshots" %
                (self.__class__.__name__))

    def cancel_snapshot(self):
        try:
            self.snapshots_procedure.kill()
        except:
            pass

    def __del__(self):
        logging.getLogger().exception("%s - __del__()!" %
                                      (self.__class__.__name__))
        self.stop_camera()
        self.setLive(False)
