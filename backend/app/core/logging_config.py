import logging
import sys


def setup_logging(log_level: str = "INFO") -> None:
    """Configures application-wide logging format and handlers."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Avoid duplicate handlers if already configured
    root_logger = logging.getLogger()
    if root_logger.handlers:
        root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=log_format, datefmt=date_format))
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    # Set third-party loggers to reasonable levels
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


logger = logging.getLogger("changeguard")
