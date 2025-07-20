import redis

from mxcubecore.configuration.ansto.config import settings


def get_redis_connection(decode_response: bool = True) -> redis.StrictRedis:
    """Create and return a Redis connection.

    Parameters
    ----------
    decode_response : bool
        By default True

    Returns
    -------
    redis.StrictRedis
        A redis connection
    """
    return redis.StrictRedis(
        host=settings.MXCUBE_REDIS_HOST,
        port=settings.MXCUBE_REDIS_PORT,
        username=settings.MXCUBE_REDIS_USERNAME,
        password=settings.MXCUBE_REDIS_PASSWORD,
        db=settings.MXCUBE_REDIS_DB,
        decode_responses=decode_response,
    )
