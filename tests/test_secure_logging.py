from __future__ import annotations

import importlib
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
import types

from app.core import logging_filters


def _token() -> tuple[str, str, str]:
    numeric = "1234567890"
    secret = "TESTONLY" * 5
    return f"{numeric}:{secret}", numeric, secret


class RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _contains_unsafe_object(value: object) -> bool:
    if isinstance(value, (BaseException, types.TracebackType)):
        return True
    if isinstance(value, dict):
        return any(
            _contains_unsafe_object(key) or _contains_unsafe_object(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_unsafe_object(item) for item in value)
    return False


def test_http_clients_are_warning_or_higher():
    logging_filters.install_filters(debug=False)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING


def test_structured_handler_never_receives_raw_exception_or_token():
    logging_filters.install_filters(debug=False)
    token, numeric, secret = _token()
    logger = logging.getLogger("neuroexam.secure-structured-test")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    handler = RecordingHandler()
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError(f"request failed for {token}")
        except RuntimeError:
            logger.exception("Telegram failure: %s", token)
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    record = handler.records[0]
    assert record.exc_info is None
    assert record.exc_text is not None
    assert "RuntimeError" in record.exc_text
    assert "Traceback" in record.exc_text
    assert "[REDACTED]" in record.exc_text
    assert not any(isinstance(value, BaseException) for value in record.__dict__.values())
    assert not any(isinstance(value, types.TracebackType) for value in record.__dict__.values())
    raw_record = repr(record.__dict__)
    assert token not in raw_record
    assert numeric not in raw_record
    assert secret not in raw_record


def test_extra_is_sanitized_after_logger_adds_it_to_record():
    logging_filters.install_filters(debug=False)
    token, numeric, secret = _token()
    logger = logging.getLogger("neuroexam.secure-extra-test")
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    handler = RecordingHandler()
    logger.addHandler(handler)
    recursive: list[object] = [token]
    recursive.append(recursive)
    try:
        try:
            raise ValueError(f"extra exception {token}")
        except ValueError as exc:
            tb = exc.__traceback__
            logger.warning(
                "structured warning",
                extra={
                    "token": token,
                    "nested": {
                        token: [token, (token, {token})],
                        "exception": exc,
                        "traceback": tb,
                        "recursive": recursive,
                    },
                },
            )
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 1
    record = handler.records[0]
    raw_record = repr(record.__dict__)
    assert token not in raw_record
    assert numeric not in raw_record
    assert secret not in raw_record
    assert "[REDACTED]" in raw_record
    assert "ValueError" in raw_record
    assert not _contains_unsafe_object(record.__dict__)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "structured warning"


def test_new_non_propagating_child_handler_receives_safe_extra_record():
    logging_filters.install_filters(debug=False)
    token, numeric, secret = _token()
    logger = logging.getLogger("neuroexam.child.created-after-install")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    handler = RecordingHandler()
    logger.addHandler(handler)
    try:
        logger.error("child error remains useful", extra={"payload": {"token": token}})
    finally:
        logger.removeHandler(handler)

    record = handler.records[0]
    raw_record = repr(record.__dict__)
    assert token not in raw_record
    assert numeric not in raw_record
    assert secret not in raw_record
    assert "[REDACTED]" in raw_record
    assert record.getMessage() == "child error remains useful"


def test_msg_args_fstring_warning_and_error_are_sanitized():
    logging_filters.install_filters(debug=False)
    token, numeric, secret = _token()
    logger = logging.getLogger("neuroexam.secure-output-test")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        logger.info("URL https://api.telegram.org/bot%s/getMe", token)
        logger.warning(f"warning {token}")
        logger.error("error token=%s", token)
        logger.error("ordinary message remains useful")
    finally:
        logger.removeHandler(handler)
    output = stream.getvalue()
    assert token not in output
    assert numeric not in output
    assert secret not in output
    assert output.count("[REDACTED]") == 3
    assert "warning" in output
    assert "error" in output
    assert "ordinary message remains useful" in output


def test_reload_is_idempotent_without_factory_chain_or_duplicate_filters():
    root = logging.getLogger()
    handler = logging.StreamHandler(io.StringIO())
    root.addHandler(handler)
    try:
        module = logging_filters
        module.install_filters(debug=False)
        make_record = logging.Logger.makeRecord
        for _ in range(4):
            module = importlib.reload(module)
            module.install_filters(debug=False)
            assert logging.Logger.makeRecord is make_record
        factory = logging.getLogRecordFactory()
        assert getattr(factory, module._FACTORY_MARKER, False) is True
        assert getattr(logging.Logger.makeRecord, module._MAKE_RECORD_MARKER, False) is True
        matching = [
            item
            for item in handler.filters
            if getattr(item, "_neuroexam_filter_marker", None) == module._FILTER_MARKER
        ]
        assert len(matching) == 1
        root_pii_filters = [
            item
            for item in root.filters
            if getattr(item, "_neuroexam_filter_marker", None) == "_neuroexam_pii_filter_v1"
        ]
        assert len(root_pii_filters) == 1

        token, numeric, secret = _token()
        target = handler.stream
        logger = logging.getLogger("neuroexam.reload-test")
        logger.error("reload token=%s", token)
        output = target.getvalue()
        assert output.count("reload token=") == 1
        assert token not in output
        assert numeric not in output
        assert secret not in output
        assert "[REDACTED]" in output
    finally:
        root.removeHandler(handler)


def test_multithreaded_extra_redaction_smoke():
    logging_filters.install_filters(debug=False)
    token, numeric, secret = _token()
    logger = logging.getLogger("neuroexam.threaded-redaction")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    handler = RecordingHandler()
    logger.addHandler(handler)

    def emit(index: int) -> None:
        logger.error("thread %d", index, extra={"nested": [token, {"value": token}]})

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(emit, range(64)))
    finally:
        logger.removeHandler(handler)

    assert len(handler.records) == 64
    rendered = repr([record.__dict__ for record in handler.records])
    assert token not in rendered
    assert numeric not in rendered
    assert secret not in rendered
    assert rendered.count("[REDACTED]") >= 64
    assert not any(_contains_unsafe_object(record.__dict__) for record in handler.records)


def test_production_logging_subprocess_never_outputs_raw_token():
    token, numeric, secret = _token()
    script = """
import logging
import main
token = "1234567890:" + "TESTONLY" * 5
logging.getLogger("httpx").info("hidden URL https://api.telegram.org/bot%s/getMe", token)
logging.getLogger("production-smoke").warning("warning token=%s", token)
class RawHandler(logging.Handler):
    def emit(self, record):
        print(repr(record.__dict__))
child = logging.getLogger("production-smoke.raw-child")
child.setLevel(logging.ERROR)
child.propagate = False
child.addHandler(RawHandler())
child.error("structured error", extra={"nested": {"token": token}})
try:
    raise RuntimeError("failed request " + token)
except RuntimeError:
    logging.getLogger("production-smoke").exception("safe traceback")
"""
    env = os.environ.copy()
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "REQUIRE_WEBHOOK_SECRET": "false",
            "REDIS_URL": "",
            "TELEGRAM_BOT_TOKEN": "",
            "OPENAI_API_KEY": "",
            "GOOGLE_SHEETS_CREDENTIALS": "",
            "GOOGLE_APPLICATION_CREDENTIALS": "",
        },
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = result.stdout + result.stderr
    assert token not in output
    assert numeric not in output
    assert secret not in output
    assert "[REDACTED]" in output
    assert "WARNING" in output
    assert "ERROR" in output
    assert "RuntimeError" in output
    assert "hidden URL" not in output
