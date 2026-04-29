from __future__ import annotations

import faulthandler
import logging
import sys
import threading
from pathlib import Path


RUNTIME_DIR = Path(__file__).resolve().parent
LOG_PATH = RUNTIME_DIR / "jarvis.log"
_fault_log = None


class _LogStream:
    def __init__(self, level: int):
        self.level = level
        self._buffer = ""

    def write(self, text: object) -> int:
        value = str(text)
        self._buffer += value
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                logging.log(self.level, line.rstrip())
        return len(value)

    def flush(self) -> None:
        if self._buffer.strip():
            logging.log(self.level, self._buffer.rstrip())
        self._buffer = ""


def configure_logging() -> None:
    global _fault_log

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_PATH,
        filemode="a",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s",
        force=True,
    )

    if sys.stdout is None or getattr(sys.stdout, "closed", False):
        sys.stdout = _LogStream(logging.INFO)
    if sys.stderr is None or getattr(sys.stderr, "closed", False):
        sys.stderr = _LogStream(logging.ERROR)

    try:
        _fault_log = LOG_PATH.open("a", encoding="utf-8")
        faulthandler.enable(file=_fault_log)
    except Exception as exc:
        logging.exception("Failed to enable faulthandler: %s", exc)

    def handle_thread_exception(args: threading.ExceptHookArgs) -> None:
        logging.exception(
            "Unhandled exception in thread %s",
            args.thread.name if args.thread else "<unknown>",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = handle_thread_exception
