from __future__ import annotations

import logging

from core.logger import LOG_DIR, get_logger, setup_logging


def test_setup_logging_creates_log_files():
    root = setup_logging("DEBUG")
    logger = get_logger("test_logger_creation")
    logger.info("mensagem de teste para validar arquivos de log")

    for handler in root.handlers:
        handler.flush()

    assert (LOG_DIR / "bot.log").exists()
    assert (LOG_DIR / "error.log").exists()


def test_setup_logging_is_idempotent():
    root_first = setup_logging("DEBUG")
    handler_count = len(root_first.handlers)

    root_second = setup_logging("DEBUG")

    assert root_second is root_first
    assert len(root_second.handlers) == handler_count


def test_get_logger_namespaces_under_limerence():
    logger = get_logger("meu_modulo")
    assert logger.name == "limerence.meu_modulo"


def test_error_log_only_receives_error_and_above():
    setup_logging("DEBUG")

    error_handlers = [
        h
        for h in logging.getLogger("limerence").handlers
        if getattr(h, "baseFilename", "").endswith("error.log")
    ]
    assert len(error_handlers) == 1
    assert error_handlers[0].level == logging.ERROR
