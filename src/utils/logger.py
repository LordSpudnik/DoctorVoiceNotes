"""
logger.py
=========

Centralised logging setup for Doctor Voice Notes.

PRD Section 13 requires the application to log: startup, shutdown, errors,
speech recognition failures, autosave events, document creation, and
microphone changes - all stored locally (Section 13 / Section 15).

WHY A ROTATING FILE HANDLER
----------------------------
The PRD expects sessions "exceeding two hours" (Section 7, Scalability) and
this app is meant to run day after day. Without rotation, app.log would
grow forever and eventually slow down the machine or fill the disk. A
RotatingFileHandler caps each log file at a fixed size and keeps a small
number of backups, so disk usage is bounded automatically with zero
maintenance required from the doctor.

HOW OTHER MODULES USE THIS FILE
---------------------------------
Every other module in this application should get its own named logger by
calling:

    from src.utils.logger import get_logger
    logger = get_logger(__name__)

    logger.info("Something happened")
    logger.warning("Something looked wrong but we recovered")
    logger.error("Something failed", exc_info=True)   # include stack trace

Using __name__ means log lines are automatically tagged with which module
produced them (e.g. "src.audio.recorder"), which makes app.log much easier
to read when diagnosing a problem after the fact.
"""

import logging
from logging.handlers import RotatingFileHandler

from src.utils.paths import get_logs_dir

# Guard flag so we only attach handlers to the root logger ONCE, even if
# get_logger() is called from many different modules during startup.
# Without this guard, every call would add another duplicate file handler,
# and every log line would end up written to the file multiple times over.
_LOGGING_CONFIGURED = False


def _configure_root_logger() -> None:
    """
    Attaches a rotating file handler (and, if not frozen into an exe, a
    console handler too) to the root logger. Called automatically the
    first time get_logger() is used anywhere in the app - you should not
    need to call this directly.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    log_path = get_logs_dir() / "app.log"

    # Format: timestamp | level | module name | message
    # Example line:
    # 2026-07-30 09:15:02 | INFO     | src.audio.recorder | Microphone opened: Realtek HD Audio
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotate at 5 MB, keep 3 old copies (app.log.1, app.log.2, app.log.3).
    # That caps total log disk usage at roughly 20 MB, which comfortably
    # covers many long dictation sessions without ever needing manual
    # cleanup by the doctor.
    file_handler = RotatingFileHandler(
        filename=str(log_path),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)

    # Also print to the console, but ONLY when running from source. Once
    # packaged as a windowed .exe there is no console for the doctor to
    # see, and attaching a console handler to a windowed exe can actually
    # raise an error on some systems (no valid stdout stream), so we must
    # gate this behind the "not frozen" check.
    from src.utils.paths import is_frozen

    if not is_frozen():
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(console_handler)

    _LOGGING_CONFIGURED = True


def get_logger(module_name: str) -> logging.Logger:
    """
    Returns a logger tagged with the given module name, configuring the
    shared file/console handlers on first use.

    Usage:
        logger = get_logger(__name__)
        logger.info("Recording started")
    """
    _configure_root_logger()
    return logging.getLogger(module_name)
