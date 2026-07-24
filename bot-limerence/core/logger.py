from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"

_FILE_FORMAT = logging.Formatter(
    fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_CONSOLE_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[41m",
}
_RESET = "\033[0m"


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _CONSOLE_COLORS.get(record.levelno, "")
        base = f"%(asctime)s | {color}%(levelname)-8s{_RESET} | %(name)s | %(message)s"
        formatter = logging.Formatter(fmt=base, datefmt="%H:%M:%S")
        return formatter.format(record)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("limerence")
    root.setLevel(log_level)
    root.propagate = False

    if root.handlers:
        return root

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(_ConsoleFormatter())
    root.addHandler(console_handler)

    bot_file_handler = RotatingFileHandler(
        LOG_DIR / "bot.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    bot_file_handler.setLevel(log_level)
    bot_file_handler.setFormatter(_FILE_FORMAT)
    root.addHandler(bot_file_handler)

    error_file_handler = RotatingFileHandler(
        LOG_DIR / "error.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(_FILE_FORMAT)
    root.addHandler(error_file_handler)

    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"limerence.{name}")
