import struct
import time
import logging
from typing import Union, Optional
from gevent import sleep

import redis
from PIL import Image, ImageOps

INT, FLOAT, STRING = 0, 1, 2
TYPE_IDX, IS_RANGE_IDX = 0, 1
parsers = {INT: int, FLOAT: float, STRING: None}

class RedisClient(redis.Redis):
    header_format = "<HiiHHQH"
    header_size = struct.calcsize(header_format)

    attributes = {
        "video_live": [INT, False, True, 1],
    }

    def __init__(self, args: dict):
        super().__init__(host=args["host"], port=args["port"], db=0)
        self._cameras = [args["hybrid"], args["first"], args["second"]]
        self._img_sub = self.pubsub()
        self._subscribed = False
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self.depth: Optional[int] = None

    def _read_attribute(self, name: str, cam_idx: int = 0) -> Union[str, int, float, list]:
        attr_name = name if cam_idx == 0 else self._cameras[cam_idx] + "::" + name
        attr_type, is_range = RedisClient.attributes[name][: IS_RANGE_IDX + 1]
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

    def _write_attribute(self, name: str, value: Union[str, int, float], cam_idx: int = 0) -> bool:
        cmd_channel = self._cameras[cam_idx] + ":SET:" + name
        attr_channel = self._cameras[cam_idx] + ":ATTR:" + name
        rep = None
        self.publish(cmd_channel, value)
        start_time = time.perf_counter()
        while (rep is None or rep["channel"].decode("utf-8") != attr_channel) and (
            time.perf_counter() - start_time < 2
        ):
            rep = self._img_sub.get_message()
            sleep(0.01)
        return (
            True if rep is not None and rep["data"].decode("utf-8") == "OK" else False
        )

    def get_frame(self) -> Optional[Image.Image]:
        video_live = self._read_attribute("video_live")
        if video_live != 1:
            self._write_attribute("video_live", 1)

        img_channel = self._cameras[0] + ":RAW"
        if not self._subscribed:
            self._img_sub.subscribe(img_channel)
            self._subscribed = True

        start = time.time()
        msg = None
        while True:
            msg = self._img_sub.get_message()
            if msg is not None and not isinstance(msg["data"], int):
                break
            if time.time() - start > 0.5:
                logging.warning("Timeout waiting for image subscription.")
                return None
            sleep(0.01)

        # Unpack image header
        _, width, height, _, _, frame_number, _ = struct.unpack(
            RedisClient.header_format, msg["data"][: RedisClient.header_size]
        )
        raw = msg["data"][RedisClient.header_size:]
        self.width, self.height = width, height

        try:
            img = Image.frombytes(mode="RGB", size=(width, height), data=raw)
        except ValueError:
            img = Image.frombytes(mode="L", size=(width, height), data=raw)
        return ImageOps.mirror(img)


if __name__ == "__main__":

    from mxcubecore.configuration.ansto.config import settings
    import numpy as np
    from time import perf_counter
    default_args = {
        "host": settings.MD3_REDIS_HOST,
        "port": settings.MD3_REDIS_PORT,
        "hybrid": "bzoom",
        "first": "acA2500-x5",
        "second": "acA2440-x30",
        "capture": True,
        "write_image": False,
    }
    cam = RedisClient(default_args)

    start = perf_counter()
    frame = cam.get_frame()
    print("Time taken to get frame:", perf_counter() - start)
    #print(np.array(frame))
