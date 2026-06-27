from functools import wraps
from time import time_ns

from backend.core.logging import logger


def time_function(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        time_before = time_ns()
        try:
            ret_val = fn(*args, **kwargs)
        except Exception:
            time_after = time_ns()
            logger.exception(
                f"{fn.__name__} failed after {((time_after - time_before) / 1e6):.2f} ms",
            )
            raise
        else:
            time_after = time_ns()
            logger.debug(
                f"{fn.__name__} spent time {((time_after - time_before) / 1e6):.2f} ms",
            )
            return ret_val

    return wrapper
