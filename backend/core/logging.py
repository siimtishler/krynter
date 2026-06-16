import logging

from backend.core.config import config

logging.basicConfig(
    level=logging.INFO, format="[%(asctime)s] [%(name)s] [%(levelname)s] [%(message)s]"
)
logger = logging.getLogger("krynter")
logger.setLevel(logging.DEBUG if config.app_debug else logging.INFO)
logger.debug("DEBUGGING ENABLED")
