"""Structured logging setup for the event aggregator.

Configures two handlers:
- Console: human-readable format at the specified log level.
- File: JSON-structured format at DEBUG level, written to logs/.
"""

import json
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON strings.

    Each record is serialized to a JSON object containing standard logging fields
    plus any extra context fields attached to the record (e.g., venue_id).
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format a log record as a single-line JSON string.

        Args:
            record: The log record to format.

        Returns:
            A single-line JSON string representing the log entry.
        """
        entry: dict = {
            "timestamp": datetime.utcfromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%f")
            + "Z",
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "message": record.getMessage(),
        }

        # Include exception info if present
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)

        # Include any extra fields attached to the record.
        # Standard LogRecord attributes to exclude from extras.
        _standard_attrs = frozenset(
            {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "message",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "taskName",
            }
        )

        for key, value in record.__dict__.items():
            if key not in _standard_attrs:
                entry[key] = value

        return json.dumps(entry, default=str)


def setup_logging(log_level: str, log_dir: Path) -> tuple[logging.Logger, Path]:
    """Set up console and JSON file logging.

    Configures the root logger with two handlers:
    - A StreamHandler writing human-readable messages to the console at the
      requested level.
    - A FileHandler writing JSON-structured messages at DEBUG level to a
      timestamped file inside log_dir.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        log_dir: Directory to write the JSON log file into. Created if absent.

    Returns:
        Tuple of (root logger, path to the log file).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_path = log_dir / f"run_{run_timestamp}.log"

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Remove any handlers that may have been added before this call
    # (e.g., during interactive sessions or repeated test runs).
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # --- JSON file handler ---
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JsonFormatter())
    root_logger.addHandler(file_handler)

    root_logger.debug(
        "Logging initialised",
        extra={"log_file": str(log_file_path), "console_level": log_level.upper()},
    )

    return root_logger, log_file_path
