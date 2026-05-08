from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable, Iterable


BASE_DIR = Path(__file__).resolve().parents[1]
TASKS_PATH = BASE_DIR / "runtime" / "tasks.json"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


class TaskError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _serialize_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.replace(microsecond=0).strftime(ISO_FORMAT)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_clock_time(value: str) -> time:
    value = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    raise TaskError("Time must be HH:MM or HH:MM:SS for on_time tasks")


def parse_duration(value: str | int | float | None) -> timedelta:
    if value is None or value == "":
        raise TaskError("Duration is required")

    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds <= 0:
            raise TaskError("Duration must be greater than 0 seconds")
        return timedelta(seconds=seconds)

    text = str(value).strip().lower()
    if not text:
        raise TaskError("Duration is required")

    try:
        seconds = float(text)
    except ValueError:
        seconds = None
    if seconds is not None:
        if seconds <= 0:
            raise TaskError("Duration must be greater than 0 seconds")
        return timedelta(seconds=seconds)

    clock_match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{1,2})", text)
    if clock_match:
        hours = int(clock_match.group(1) or 0)
        minutes = int(clock_match.group(2))
        seconds = int(clock_match.group(3))
        if minutes > 59 or seconds > 59:
            raise TaskError("Duration clock format must be HH:MM:SS")
        total = timedelta(hours=hours, minutes=minutes, seconds=seconds)
        if total.total_seconds() <= 0:
            raise TaskError("Duration must be greater than 0 seconds")
        return total

    units = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }
    total_seconds = 0.0
    matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*([a-z]+)", text))
    if matches and "".join(match.group(0) for match in matches).replace(" ", "") == text.replace(" ", ""):
        for match in matches:
            unit = match.group(2)
            if unit not in units:
                raise TaskError(f"Unsupported duration unit: {unit}")
            total_seconds += float(match.group(1)) * units[unit]

        if total_seconds <= 0:
            raise TaskError("Duration must be greater than 0 seconds")
        return timedelta(seconds=total_seconds)

    raise TaskError("Duration must look like 10m, 2 hours, 01:30:00, or seconds")


def _load_raw_tasks(path: Path = TASKS_PATH) -> list[dict]:
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return [task for task in data if isinstance(task, dict)]


def _save_raw_tasks(tasks: Iterable[dict], path: Path = TASKS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(tasks), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


@dataclass
class TaskEvent:
    name: str

    def initial_next_run(self, task: dict, now: datetime) -> str:
        raise NotImplementedError

    def next_after_run(self, task: dict, now: datetime) -> str:
        if not task.get("repeat"):
            return ""

        frequency = task.get("frequency") or task.get("time")
        if not frequency:
            return ""

        next_run = now + parse_duration(frequency)
        return _serialize_datetime(next_run)

    def should_run_on_start(self, task: dict) -> bool:
        return False


class OnStartEvent(TaskEvent):
    def __init__(self):
        super().__init__("on_start")

    def initial_next_run(self, task: dict, now: datetime) -> str:
        return ""

    def should_run_on_start(self, task: dict) -> bool:
        return True


class OnTimeEvent(TaskEvent):
    def __init__(self):
        super().__init__("on_time")

    def initial_next_run(self, task: dict, now: datetime) -> str:
        raw_time = task.get("time")
        if not raw_time:
            raise TaskError("time is required for on_time tasks")

        explicit_datetime = _parse_datetime(str(raw_time))
        if explicit_datetime is not None:
            if explicit_datetime <= now and task.get("repeat") and task.get("frequency"):
                frequency = parse_duration(task.get("frequency"))
                while explicit_datetime <= now:
                    explicit_datetime += frequency
            return _serialize_datetime(explicit_datetime)

        clock_time = _parse_clock_time(str(raw_time))
        next_run = datetime.combine(now.date(), clock_time)
        if next_run <= now:
            next_run += timedelta(days=1)
        return _serialize_datetime(next_run)

    def next_after_run(self, task: dict, now: datetime) -> str:
        if not task.get("repeat"):
            return ""

        if task.get("frequency"):
            return _serialize_datetime(now + parse_duration(task.get("frequency")))

        raw_time = task.get("time")
        if _parse_datetime(str(raw_time)) is not None:
            return ""

        clock_time = _parse_clock_time(str(raw_time))
        next_run = datetime.combine(now.date(), clock_time)
        while next_run <= now:
            next_run += timedelta(days=1)
        return _serialize_datetime(next_run)


class AfterTimeEvent(TaskEvent):
    def __init__(self):
        super().__init__("after_time")

    def initial_next_run(self, task: dict, now: datetime) -> str:
        delay = parse_duration(task.get("time"))
        return _serialize_datetime(now + delay)


EVENTS: dict[str, TaskEvent] = {
    event.name: event
    for event in (
        OnStartEvent(),
        OnTimeEvent(),
        AfterTimeEvent(),
    )
}


class TaskStore:
    def __init__(self, path: Path = TASKS_PATH):
        self.path = path
        self._lock = threading.Lock()

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return _load_raw_tasks(self.path)

    def create_task(
        self,
        *,
        event: str,
        prompt: str,
        repeat: bool = False,
        time: str | int | float | None = None,
        frequency: str | int | float | None = None,
        name: str | None = None,
    ) -> dict:
        if event not in EVENTS:
            raise TaskError(f"Unsupported task event: {event}")

        prompt = str(prompt).strip()
        if not prompt:
            raise TaskError("prompt is required")

        now = _now()
        task = {
            "id": uuid.uuid4().hex[:10],
            "name": str(name).strip() if name else "",
            "event": event,
            "repeat": bool(repeat),
            "frequency": "" if frequency is None else str(frequency).strip(),
            "time": "" if time is None else str(time).strip(),
            "prompt": prompt,
            "created_at": _serialize_datetime(now),
            "last_run_at": "",
            "next_run_at": "",
            "run_count": 0,
            "enabled": True,
        }
        task["next_run_at"] = EVENTS[event].initial_next_run(task, now)

        with self._lock:
            tasks = _load_raw_tasks(self.path)
            tasks.append(task)
            _save_raw_tasks(tasks, self.path)

        return task

    def delete_task(self, task_id: str) -> bool:
        task_id = str(task_id).strip()
        with self._lock:
            tasks = _load_raw_tasks(self.path)
            kept = [task for task in tasks if str(task.get("id")) != task_id]
            if len(kept) == len(tasks):
                return False
            _save_raw_tasks(kept, self.path)
            return True

    def due_tasks(self, now: datetime) -> list[dict]:
        due: list[dict] = []
        with self._lock:
            tasks = _load_raw_tasks(self.path)
            changed = False
            kept: list[dict] = []

            for task in tasks:
                if not task.get("enabled", True):
                    kept.append(task)
                    continue

                event = EVENTS.get(str(task.get("event", "")))
                next_run = _parse_datetime(str(task.get("next_run_at", "")))
                if event is None or next_run is None or next_run > now:
                    kept.append(task)
                    continue

                due.append(dict(task))
                task["last_run_at"] = _serialize_datetime(now)
                task["run_count"] = int(task.get("run_count", 0)) + 1
                task["next_run_at"] = event.next_after_run(task, now)
                changed = True

                if task.get("repeat") and task.get("next_run_at"):
                    kept.append(task)

            if changed:
                _save_raw_tasks(kept, self.path)

        return due

    def startup_tasks(self) -> list[dict]:
        due: list[dict] = []
        now = _now()
        with self._lock:
            tasks = _load_raw_tasks(self.path)
            changed = False
            kept: list[dict] = []

            for task in tasks:
                if not task.get("enabled", True):
                    kept.append(task)
                    continue

                event = EVENTS.get(str(task.get("event", "")))
                if event is None or not event.should_run_on_start(task):
                    kept.append(task)
                    continue

                due.append(dict(task))
                task["last_run_at"] = _serialize_datetime(now)
                task["run_count"] = int(task.get("run_count", 0)) + 1
                changed = True

                if task.get("repeat"):
                    kept.append(task)

            if changed:
                _save_raw_tasks(kept, self.path)

        return due


class TaskScheduler:
    def __init__(
        self,
        store: TaskStore,
        callback: Callable[[dict], None],
        poll_seconds: float = 1.0,
    ):
        self.store = store
        self.callback = callback
        self.poll_seconds = max(0.2, poll_seconds)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._run_tasks(self.store.startup_tasks())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._run_tasks(self.store.due_tasks(_now()))
            self._stop.wait(self.poll_seconds)

    def _run_tasks(self, tasks: Iterable[dict]) -> None:
        for task in tasks:
            threading.Thread(
                target=self.callback,
                args=(task,),
                daemon=True,
            ).start()


default_task_store = TaskStore()
