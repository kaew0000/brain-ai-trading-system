import logging
import logging.handlers
import os
import sys
import threading

import colorlog

# Read settings lazily to avoid circular imports at module load time
def _get_settings():
    from config.settings import settings
    return settings


# ── Shared file handler ─────────────────────────────────────────────────────
# get_logger() is called once per module with a distinct name (≈80+ call
# sites), and each of those names used to instantiate its own
# RotatingFileHandler on the same cfg.LOG_FILE path. That left dozens of
# independent, simultaneously-open file handles on one file. On Windows,
# os.rename() (used by doRollover()) fails with PermissionError/WinError 32
# whenever any other handle still has the file open — so once the file
# crossed maxBytes, every logger's next emit() re-triggered a rollover that
# was guaranteed to fail, and the record was dropped before ever reaching
# FileHandler.emit(). Sharing a single handler instance across all logger
# names means exactly one open handle exists on the file, so doRollover()
# can close its own stream and rename cleanly.
_file_handler = None
_file_handler_lock = threading.Lock()


def _get_shared_file_handler() -> logging.handlers.RotatingFileHandler:
    global _file_handler
    if _file_handler is not None:
        return _file_handler

    with _file_handler_lock:
        if _file_handler is not None:
            return _file_handler

        cfg = _get_settings()
        log_dir = os.path.dirname(cfg.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

        handler = logging.handlers.RotatingFileHandler(
            cfg.LOG_FILE,
            maxBytes=10 * 1024 * 1024,   # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        _file_handler = handler
        return _file_handler


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger with:
      - Colorized StreamHandler (console)
      - RotatingFileHandler (10 MB × 5 backups, UTF-8), shared by every
        logger name so the process holds exactly one open handle on
        cfg.LOG_FILE at a time.
    Idempotent: calling twice with the same name returns the same logger.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    cfg = _get_settings()
    level = getattr(logging, cfg.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    # ── Console (colorlog) ────────────────────────────────────────────────
    console = colorlog.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(
        colorlog.ColoredFormatter(
            fmt="%(log_color)s%(asctime)s [%(levelname)8s] %(name)s: %(message)s%(reset)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                "DEBUG":    "cyan",
                "INFO":     "green",
                "WARNING":  "yellow",
                "ERROR":    "red",
                "CRITICAL": "bold_red",
            },
        )
    )
    logger.addHandler(console)

    # ── Rotating File (shared instance — see _get_shared_file_handler) ─────
    logger.addHandler(_get_shared_file_handler())

    return logger
