import logging
import logging.config

LOGGING_CONFIG: dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
            "rename_fields": {"asctime": "timestamp", "levelname": "level"},
            "reserved_attrs": ["color_message"],
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn.access": {"handlers": [], "propagate": False, "level": "WARNING"},
        "uvicorn.error": {"handlers": ["stdout"], "propagate": False, "level": "INFO"},
    },
    "root": {"handlers": ["stdout"], "level": "INFO"},
}


def configure_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)
