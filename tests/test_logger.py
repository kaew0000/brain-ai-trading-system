"""
Regression tests for utils/logger.py.

Covers the root cause of the Windows log-rotation PermissionError
(WinError 32) seen in production: get_logger() previously built a brand
new RotatingFileHandler for every distinct logger name (~80+ call sites
across the codebase), leaving that many simultaneously open handles on
the same file. On Windows, os.rename() inside doRollover() fails whenever
another handle still has the file open, so once the file crossed
maxBytes every subsequent emit() re-attempted (and lost) its rollover.

These tests assert that every logger name now shares one file handler
instance, so the process only ever holds a single open handle on
cfg.LOG_FILE.
"""
import importlib
import logging
import logging.handlers

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def clean_logger_module(tmp_path, monkeypatch):
    """
    Reload utils.logger with a temp log file and a clean logging registry,
    so tests don't depend on import order or leak handlers/state into
    other test modules.
    """
    import config.settings as settings_module

    monkeypatch.setattr(settings_module.settings, "LOG_FILE", str(tmp_path / "brain_bot_test.log"))

    import utils.logger as logger_module
    importlib.reload(logger_module)

    yield logger_module

    # Teardown: close and drop any handlers created during the test so the
    # temp file handle doesn't leak into subsequent tests.
    for name in ("test.module.a", "test.module.b", "test.module.c"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            h.close()
            lg.removeHandler(h)
    if logger_module._file_handler is not None:
        logger_module._file_handler.close()
    importlib.reload(logger_module)


def test_different_names_share_one_file_handler(clean_logger_module):
    """The bug: each distinct name used to get its own RotatingFileHandler
    on the same path. The fix: they must all get the *same* instance."""
    logger_module = clean_logger_module

    log_a = logger_module.get_logger("test.module.a")
    log_b = logger_module.get_logger("test.module.b")
    log_c = logger_module.get_logger("test.module.c")

    file_handlers_a = [h for h in log_a.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    file_handlers_b = [h for h in log_b.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    file_handlers_c = [h for h in log_c.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]

    assert len(file_handlers_a) == 1
    assert len(file_handlers_b) == 1
    assert len(file_handlers_c) == 1

    # Same object, not just same path — this is what prevents the extra
    # open OS-level handles that caused the Windows rename to fail.
    assert file_handlers_a[0] is file_handlers_b[0] is file_handlers_c[0]


def test_only_one_open_stream_on_the_log_file(clean_logger_module):
    """There must be exactly one live file handle on cfg.LOG_FILE, no
    matter how many distinct logger names are created."""
    logger_module = clean_logger_module

    for i in range(10):
        logger_module.get_logger(f"test.module.many.{i}")

    handler = logger_module._get_shared_file_handler()
    assert handler.stream is not None
    assert not handler.stream.closed

    # Confirm it really is the one-and-only handler backing every logger
    # created above, not just a coincidentally-equal path.
    for i in range(10):
        lg = logging.getLogger(f"test.module.many.{i}")
        rfh = [h for h in lg.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
        assert rfh == [handler]

    for i in range(10):
        logging.getLogger(f"test.module.many.{i}").handlers.clear()


def test_get_logger_idempotent_for_same_name(clean_logger_module):
    """Pre-existing behavior must be preserved: calling get_logger() twice
    with the same name must not duplicate handlers."""
    logger_module = clean_logger_module

    log1 = logger_module.get_logger("test.module.a")
    log1_handler_count = len(log1.handlers)

    log2 = logger_module.get_logger("test.module.a")

    assert log1 is log2
    assert len(log2.handlers) == log1_handler_count


def test_rollover_does_not_raise_with_shared_handler(clean_logger_module):
    """End-to-end regression for the WinError 32 scenario: force a
    rollover while multiple logger names are backed by the shared
    handler, and confirm no exception propagates (the failure mode in
    production was doRollover() raising PermissionError)."""
    logger_module = clean_logger_module

    log_a = logger_module.get_logger("test.module.a")
    logger_module.get_logger("test.module.b")
    logger_module.get_logger("test.module.c")

    handler = logger_module._get_shared_file_handler()
    handler.doRollover()  # must not raise

    log_a.info("message after rollover")
    handler.flush()
