import datetime
import os
import random
import struct
import time
from typing import Union

import numpy as np
import redis
from PIL import (
    Image,
    ImageOps,
)

INT, FLOAT, STRING = 0, 1, 2
TYPE_IDX, IS_RANGE_IDX, IS_GLOBAL_IDX, TEST_VALUES_IDX = 0, 1, 2, 3
parsers = {INT: int, FLOAT: float, STRING: None}

# IP ADDRESS :
MD_REDIS_HOST = os.environ.get("MD_REDIS_HOST", "12.345.678.90")
MD_REDIS_PORT = int(os.environ.get("MD_REDIS_PORT", "6379"))
IP = f"{MD_REDIS_HOST}:{MD_REDIS_PORT}"


class RedisClient(redis.Redis):
    """
    This class tests the video server when using the Redis protocol.
    It reads some of the attributes and displays them. It also tests image retrieval
    from the video server

    Usage:
        * Options:
            + host: IP address of the machine running the Redis service
            + port: communication port used by the video server's protocol
            + hybrid: name of the hybrid (bzoom) camera. Default is bzoom
            + first: name of the large field camera of the bzoom, defined in videoserver's
            config file (VideoStreamer.ini)
            + second: name of the small field camera of the bzoom
            + capture: boolean (True or False) indicating if images should be captured
            + write_image: boolean indicating if captured images should be stored.
            If true, capture is also true

        ./TestRedis.py --host=... --hybrid=... --first=... --second=...
        --capture=... --write_image=...

    This code is provided AS IS for example purpose and testing MD Device Server
    ARINAX - Sept 2021

    __author__ = "Johann Fotsing"
    """

    # Attributes are given with their types and booleans indicating if they are of range type.
    # Scalars and strings are not retrieved from the redis server the same way as lists are.
    attributes = {
        "camera_name": [STRING, False, True],
        "camera_pixelsize": [FLOAT, True, False],
        "image_width": [INT, False, False],
        "image_height": [INT, False, False],
        "video_exposure": [FLOAT, False, False, [2000, 50000, 22200]],
        "video_exposure_range": [FLOAT, True, False],
        "video_gain": [FLOAT, False, False, [0.1, 0.2, 0.3]],
        "video_gain_range": [FLOAT, True, False],
        "video_scale": [FLOAT, False, False, [0.1, 6.0, 1.0]],
        "num_zoom_levels": [INT, False, False],
        "video_zoom_idx": [INT, False, True, 3],
        "video_zoom_percent": [FLOAT, False, True, 0.6],
        "video_predefined_zoom_list": [FLOAT, True, True],
        "video_zoom_list": [FLOAT, True, False],
        "video_mode": [STRING, False, False, ["RGB8Packed", "BayerBG8", "BayerRG8"]],
        "video_white_balance": [STRING, False, False, ["Continuous", "Auto", "Off"]],
        "video_white_balance_red": [FLOAT, False, False, [0.1, 0.5, 0.8]],
        "video_white_balance_blue": [FLOAT, False, False, [0.1, 0.5, 0.8]],
        "width_magnification_ratio": [FLOAT, False, False],
        "height_magnification_ratio": [FLOAT, False, False],
        "width_optic_center_offset": [INT, False, False],
        "height_optic_center_offset": [INT, False, False],
        "video_live": [INT, False, True, 1],
        "video_last_image_counter": [INT, False, False],
        "video_fps": [FLOAT, False, True],
        "endianness": [INT, False, True],
        "camera_acq_rate": [FLOAT, False, False],
    }
    # ------------------
    header_format = "<HiiHHQH"
    header_size = struct.calcsize(header_format)
    img_dir = "TestRedisImages"
    num_acq = 10
    num_write_img = 10
    # ------------------
    log_file = "test_server_redis.log"
    separator = "-" * 10
    pre_header = "# "
    post_header = " #"
    # ------------------
    default_args = {
        "host": IP,
        "port": 6379,
        "hybrid": "bzoom",
        "first": "acA2500-x5",
        "second": "acA2440-x30",
        "capture": True,
        "write_image": False,
    }

    def __init__(self, args):
        redis.Redis.__init__(self, host=args["host"], port=args["port"], db=0)
        self.__cameras = [args["hybrid"], args["first"], args["second"]]
        self.__capture = args["capture"]
        self.__write_image = args["write_image"]
        self.__zoomLevels = None
        self.__attrSub = None
        self.__imgSub = None

        self.width: int = None
        self.heigh: int = None
        self.depth: int = None

        img = self.get_frame()
        try:
            self.width, self.height, self.depth = np.array(img).shape
        except ValueError:
            self.depth = None
            self.width, self.height = np.array(img).shape

    def __init(self) -> bool:
        """
        This function initializes the test client (ping to check connection, read cameras
        zoom levels & prepare image and attribute listeners)

        Returns
        -------
        bool
            A boolean indicating if the test client was correctly initialized
        """
        # Ping
        try:
            self.ping()
        except redis.exceptions.ConnectionError as e:
            print(e)
            return False
        # Read cameras' zoom levels
        self.__zoomLevels = [
            self.__read_attribute("video_zoom_list"),
            self.__read_attribute("video_zoom_list", 1),
            self.__read_attribute("video_zoom_list", 2),
        ]
        # Create clients to listen to attribute and image channels
        self.__attrSub = self.pubsub()
        self.__imgSub = self.pubsub()
        # Start listening on attributes channel
        self.__attrSub.psubscribe("*:ATTR:*")
        while self.__attrSub.get_message() is None:  # get the subscription message
            continue
        return True

    def __read_attribute(
        self, name: str, cam_idx: int = 0
    ) -> Union[str, int, float, list]:
        """
        This function reads the value of an attribute of one of the cameras of the video server.

        Parameters
        ----------
        name : str
            attribute's name
        cam_idx : int, optional
            index of the camera which attribute is read

        Returns
        -------
        Union[str, int, float, list]
            Attribute's value
        """
        attr_name = name if cam_idx == 0 else self.__cameras[cam_idx] + "::" + name
        [attr_type, is_range] = RedisClient.attributes[name][: IS_RANGE_IDX + 1]
        parser = parsers[attr_type]
        if not is_range:
            res = self.get(attr_name)
            if res is not None:
                res = res.decode("utf-8")
                if parser is not None:
                    res = parser(res)
        else:
            res = self.lrange(attr_name, 0, -1)
            if res is not None:
                res = [res_el.decode("utf-8") for res_el in res]
                if parser is not None:
                    res = [parser(res_el) for res_el in res]
        return res

    def __write_attribute(
        self, name: str, value: Union[str, int, float], cam_idx: int = 0
    ) -> bool:
        """
        This function sets a specific camera's attribute to a desired value.

        Parameters
        ----------
        name : str
            Name of the attribute
        value : Union[str, int, float]
            Value to set to the attribute
        cam_idx : int, optional
            Index of the camera which attribute is modified, by default 0

        Returns
        -------
        bool
            True if write successful, false otherwise
        """
        cmd_channel = self.__cameras[cam_idx] + ":SET:" + name
        attr_channel = self.__cameras[cam_idx] + ":ATTR:" + name
        rep = None
        self.publish(cmd_channel, value)
        start_time = time.perf_counter()
        while (rep is None or rep["channel"].decode("utf-8") != attr_channel) and (
            time.perf_counter() - start_time < 2
        ):
            rep = self.__attrSub.get_message()
        return (
            True if rep is not None and rep["data"].decode("utf-8") == "OK" else False
        )

    @staticmethod
    def __output(line: str) -> None:
        """
        This function logs some information from the test running. Text is printed in
        Terminal and in log file.

        Parameters
        ----------
        line : str
           line to be logged

        Returns
        -------
        None
        """
        print(line)
        with open(RedisClient.log_file, "a") as out:
            out.write(line + "\n")
            out.close()

    @staticmethod
    def __generate_header(txt: str) -> str:
        """
        This function decorates text to be displayed as a header.

        Parameters
        ----------
        txt : str
            Text to be decorated

        Returns
        -------
        str
            Decorated text
        """
        n = len(txt) + len(RedisClient.pre_header) + len(RedisClient.post_header)
        return (
            "*" * n
            + "\n"
            + RedisClient.pre_header
            + txt
            + RedisClient.post_header
            + "\n"
            + "*" * n
            + "\n"
        )

    def __time_tag(self, tag: str) -> None:
        """
        This function displays a time tag in the log file of this test.
        Mainly used to indicate start and end of test.

        Parameters
        ----------
        tag : str
            A meaningful description for the tag

        Returns
        -------
        None
        """
        time_tag = (
            "\n"
            + "#" * 5
            + " {} :: ".format(tag)
            + datetime.datetime.now().strftime("%c")
            + "  VideoServer tests with Redis  "
            + "#" * 5
            + "\n"
        )
        self.__output(time_tag)

    def __change_camera(self):
        """
        This function changes the camera pointed to by the hybrid camera.

        Returns
        -------
        int
            Index of the camera pointed to by the hybrid camera after change is performed
        """
        cam = self.__read_attribute("camera_name")
        old_idx = self.__cameras.index(cam)
        new_idx = 2 - old_idx + 1
        if len(self.__zoomLevels[new_idx]) < 2:
            return old_idx
        a, b = self.__zoomLevels[new_idx][0], self.__zoomLevels[new_idx][1]
        zoom_level = random.uniform(a, b)
        assert self.__write_attribute("video_zoom_percent", zoom_level)
        new_cam = self.__read_attribute("camera_name")
        assert cam != new_cam
        return new_idx

    def __check_attribute(self, name: str) -> None:
        """
        The check performed on writable attributes consists in writing an attribute and
        reading back its value. The test values are written in RedisClient.attributes.
        The initial value of the attribute is saved and restored after the test is performed.

        Parameters
        ----------
        name : str
            Name of the attribute to be tested

        Returns
        -------
        None
        """
        val = RedisClient.attributes[name][TEST_VALUES_IDX]
        if RedisClient.attributes[name][IS_GLOBAL_IDX]:
            init_value = self.__read_attribute(name)  # store initial value
            ok = (
                "OK"
                if self.__write_attribute(name, val)
                and self.__read_attribute(name) == val
                else "NOK"
            )
            self.__write_attribute(name, init_value)  # restore initial value
            line = "Set attribute %s to value %s %s" % (name, val, ok)
            self.__output(line)
        else:
            assert isinstance(val, list)
            for i, test_val in enumerate(val):
                prefix = (self.__cameras[i] + "::") if i != 0 else ""
                init_value = self.__read_attribute(
                    name, cam_idx=i
                )  # store initial value
                ok = (
                    "OK"
                    if self.__write_attribute(name, test_val, cam_idx=i)
                    and self.__read_attribute(name, cam_idx=i) == test_val
                    else "NOK"
                )
                # restore initial value
                self.__write_attribute(name, init_value, cam_idx=i)
                line = "Set attribute %s%s to value %s %s" % (
                    prefix,
                    name,
                    test_val,
                    ok,
                )
                self.__output(line)
        return

    def __poll_image(self) -> tuple[bytes, int, int, int]:
        """
        This function is used to retrieve one image from the Redis video server.

        Returns
        -------
        tuple[bytes, int, int, int]
            The raw data in bytes format, width, height and frame number
        """
        msg = None
        while msg is None or isinstance(msg["data"], int):
            try:
                msg = self.__imgSub.get_message()
            except redis.exceptions.ConnectionError:
                print("Reconnection")
                self.__imgSub.subscribe(self.__cameras[0] + "RAW")
        _, width, height, _, _, frame_number, _ = struct.unpack(
            RedisClient.header_format, msg["data"][: RedisClient.header_size]
        )
        raw = msg["data"][RedisClient.header_size :]
        return raw, width, height, frame_number

    def __log_all_attributes(self) -> None:
        """
        This function reads all attributes available in the Redis video server
        and displays them with their values.

        Returns
        -------
        None
        """
        # Generate header
        self.__output(self.__generate_header("Logging all attributes"))
        for attr in RedisClient.attributes:
            self.__output(RedisClient.separator)
            lines = ["%s = %s" % (attr, self.__read_attribute(attr))]
            if not RedisClient.attributes[attr][IS_GLOBAL_IDX]:
                lines.append(
                    "%s::%s = %s"
                    % (self.__cameras[1], attr, self.__read_attribute(attr, 1))
                )
                lines.append(
                    "%s::%s = %s"
                    % (self.__cameras[2], attr, self.__read_attribute(attr, 2))
                )
            for line in lines:
                self.__output(line)
        self.__output("\n")

    def __test_attributes(self) -> None:
        """
        This function is used to test all writable attributes. Tests are better
        described in self.__check_attribute().

        Returns
        -------
        None
        """
        # Generate header
        self.__output(self.__generate_header("Testing writable attributes"))
        # Start testing
        for attr in RedisClient.attributes:
            if (
                len(RedisClient.attributes[attr]) > TEST_VALUES_IDX
                and "magnification_ratio" not in attr
            ):
                # magnification ratios are not checked because they reinitialize zoom
                self.__output(RedisClient.separator)
                self.__check_attribute(attr)
        self.__output("\n")

    def __test_images(self) -> None:
        """
        This function is used to test image retrieval from the video server.
        Based on the capture and write_image options, images will be polled and
        stored in TangoTestClient.img_dir

        Returns
        -------
        None
        """
        if not self.__capture:
            self.__output(self.__generate_header("No image capture."))
            return
        self.__output(self.__generate_header("Testing video streamer"))
        # Set video live
        self.__write_attribute("video_live", 1)
        # Subscribe to image channel
        img_channel = self.__cameras[0] + ":RAW"
        self.__imgSub.subscribe(img_channel)
        while self.__imgSub.get_message() is None:  # get subscription message
            continue
        # Prepare image tab and time counters
        last_img_time = time.perf_counter()
        img_counter = 0
        img_tab = [None] * RedisClient.num_acq
        while self.__capture and img_counter < RedisClient.num_acq:
            raw, width, height, frame_number = self.__poll_image()
            try:
                img_tab[img_counter] = Image.frombytes(
                    mode="RGB", size=(width, height), data=raw
                )
            except ValueError:
                img_tab[img_counter] = Image.frombytes(
                    mode="L", size=(width, height), data=raw
                )
            img_counter += 1
            current_time = time.perf_counter()
            process_time = current_time - last_img_time
            last_img_time = current_time
            fps = self.__read_attribute("video_fps")
            fps_calc = float(1.0 / process_time)
            line = (
                "Image number: %2d,  Frame number: %d,  FPS: %6.3f,  "
                "Server FPS: %6.3f,  Process Time: %6.3fms"
                % (img_counter, frame_number, fps_calc, fps, process_time * 1000)
            )
            self.__output(line)
        # Create image directory
        if self.__write_image:
            if not os.path.exists(RedisClient.img_dir):
                os.mkdir(RedisClient.img_dir)
            for i, img in enumerate(img_tab[: RedisClient.num_write_img]):
                img.save("./%s/image%d.bmp" % (RedisClient.img_dir, i))

    def run(self) -> None:
        """
        This function is called to run the test client.

        Returns
        -------
        None
        """
        if not self.__init():
            print("Test client could not be initialized, test is aborted.")
            return
        self.__time_tag("Start")
        self.__log_all_attributes()
        # self.__test_attributes()
        self.__test_images()
        self.__time_tag("End")

    def get_frame(self) -> Image:
        """
        Gets a frame from the MD3 redis server.

        Returns
        -------
        Image
            An image object
        """
        if not self.__init():
            print("Test client could not be initialized, test is aborted.")
            return

        self.__write_attribute("video_live", 1)
        # Subscribe to image channel
        img_channel = self.__cameras[0] + ":RAW"
        self.__imgSub.subscribe(img_channel)
        while self.__imgSub.get_message() is None:  # get subscription message
            continue

        raw, self.width, self.height, frame_number = self.__poll_image()
        try:
            img = Image.frombytes(mode="RGB", size=(self.width, self.height), data=raw)
        except ValueError:
            # black and white image
            img = Image.frombytes(mode="L", size=(self.width, self.height), data=raw)

        # NOTE: The MD3 redis server returns mirrored images, therefore we mirror them back
        # this is a test to see if docker cp worked
        return ImageOps.mirror(img)


if __name__ == "__main__":
    default_args = {
        "host": "10.244.101.30",
        "port": 6379,
        "hybrid": "bzoom",
        "first": "acA2500-x5",
        "second": "acA2440-x30",
        "capture": True,
        "write_image": False,
    }
    cam = RedisClient(default_args)

    print(np.array(cam.get_frame()))
