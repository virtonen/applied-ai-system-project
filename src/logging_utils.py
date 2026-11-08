"""
Search logging: one JSON object per line, so the log is easy to read, grep and parse.

The default file is logs/recommender.log. Set VIBEMATCH_LOG_FILE to use another path.
Logging never raises: if the file cannot be written, the app keeps working.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

LOGGER_NAME = "vibematch"
DEFAULT_LOG_FILE = Path(__file__).resolve().parent.parent / "logs" / "recommender.log"


def configure_logging(path: Optional[Union[str, Path]] = None) -> Optional[Path]:
    """Send log lines to `path` (or the default file). Replaces any earlier handler."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)

    log_path = Path(path or os.environ.get("VIBEMATCH_LOG_FILE") or DEFAULT_LOG_FILE)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return log_path


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    """Write one JSON line: a UTC timestamp, the event name and any extra fields."""
    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers and configure_logging() is None:
        return
    record = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **fields}
    try:
        logger.log(level, json.dumps(record, default=str))
    except Exception:  # logging must never break the app
        pass
