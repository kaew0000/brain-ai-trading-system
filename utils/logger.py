import logging
import logging.handlers
import os
import sys

import colorlog

# Read settings lazily to avoid circular imports at module load time
def _get_settings():
    from config.settings import settings
    return settings


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger with:
      - Colorized StreamHandler (console)
      - RotatingFileHandler (10 MB × 5 backups, UTF-8)
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

    # ── Rotating File ─────────────────────────────────────────────────────
    log_dir = os.path.dirname(cfg.LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        cfg.LOG_FILE,
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    return logger
