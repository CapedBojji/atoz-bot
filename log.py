"""
Centralized logging setup.

Provides `setup_logger()` to write logs with automatic daily rotation
and cleanup of old log files.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Optional


def setup_logger(
    log_dir: Path | str = "logs",
    retention_days: int = 7,
    level: int = logging.INFO,
    logger_name: Optional[str] = None,
) -> logging.Logger:
    """
    Configure a logger with automatic daily rotation at midnight.

    - Creates `log_dir` if it doesn't exist.
    - Rotates logs daily at midnight (works continuously, no restart needed).
    - Automatically keeps last `retention_days` backups, deletes older files.
    - Writes to `app.log` with dated backups like `app.log.2026-01-17`.

    Returns the configured logger.
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    log_file = log_path / "app.log"

    logger = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    logger.setLevel(level)

    # Clear existing handlers to avoid duplicates if called multiple times
    if logger.handlers:
        logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # TimedRotatingFileHandler: rotates at midnight, keeps retention_days backups
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if logger_name:
        logger.propagate = False

    return logger
