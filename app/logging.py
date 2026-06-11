import logging
import logging.config
import re

_SENSITIVE_PATTERNS = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"xox[abpr]-\S+"), "xox*-***"),
    (re.compile(r"1//[\w.\-]+"), "1//***"),
]


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            for pattern, replacement in _SENSITIVE_PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        return True


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

    for handler in logging.getLogger().handlers:
        handler.addFilter(SensitiveDataFilter())
