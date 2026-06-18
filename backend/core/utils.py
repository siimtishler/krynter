from time import time_ns

from backend.core.logging import logger


def time_function(fn):
    def wrapper(*args, **kwargs):
        time_before = time_ns()
        ret_val = fn(*args, **kwargs)
        time_after = time_ns()
        logger.info(
            f"{fn.__name__}() spent time: ({(time_after - time_before) / 1e6})ms"
        )
        return ret_val

    return wrapper
