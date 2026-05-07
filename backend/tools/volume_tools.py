from backend.tools.base import Tool, ToolResult


def _coinitialize():
    import comtypes

    comtypes.CoInitialize()


def _get_sessions():
    _coinitialize()
    from pycaw.pycaw import (
        DEVICE_STATE,
        AudioSession,
        AudioUtilities,
        EDataFlow,
        IAudioSessionControl2,
    )

    result = []
    devices = AudioUtilities.GetAllDevices(
        data_flow=EDataFlow.eRender.value,
        device_state=DEVICE_STATE.ACTIVE.value,
    )

    for device in devices:
        try:
            manager = device.AudioSessionManager
            enumerator = manager.GetSessionEnumerator()
            count = enumerator.GetCount()
        except Exception:
            continue

        device_name = device.FriendlyName or device.id or "output"
        for index in range(count):
            try:
                control = enumerator.GetSession(index)
                control2 = control.QueryInterface(IAudioSessionControl2)
                result.append((AudioSession(control2), device_name))
            except Exception:
                continue

    if result:
        return result

    return [(session, "default_output") for session in AudioUtilities.GetAllSessions()]


def _session_volume(session):
    from pycaw.pycaw import ISimpleAudioVolume

    return session._ctl.QueryInterface(ISimpleAudioVolume)


def _session_app_name(session) -> str:
    process = getattr(session, "Process", None)
    if process is not None:
        try:
            return process.name()
        except Exception:
            pass

    display_name = getattr(session, "DisplayName", "") or ""
    return display_name or "system"


def _session_pid(session) -> int | None:
    pid = getattr(session, "ProcessId", None)
    if pid:
        return int(pid)

    process = getattr(session, "Process", None)
    return getattr(process, "pid", None)


def _session_key(session, device: str) -> str:
    pid = _session_pid(session)
    name = _session_app_name(session)
    return f"{device}:{pid or 'nopid'}:{name}"


def _summarize_session(session, device: str) -> dict:
    volume = _session_volume(session)
    pid = _session_pid(session)
    return {
        "id": _session_key(session, device),
        "device": device,
        "app": _session_app_name(session),
        "pid": pid,
        "volume": round(float(volume.GetMasterVolume()), 3),
        "muted": bool(volume.GetMute()),
    }


def query_volume() -> ToolResult:
    sessions = []
    for session, device in _get_sessions():
        try:
            sessions.append(_summarize_session(session, device))
        except Exception:
            continue

    sessions.sort(key=lambda item: (item["device"], item["app"].lower(), item["pid"] or 0))
    return ToolResult(status="ok", content=sessions)


def _matches(summary: dict, app: str | None, pid: int | None, device: str | None) -> bool:
    if device and device.lower() not in summary["device"].lower():
        return False
    if pid is not None and summary["pid"] != pid:
        return False
    if app and app.lower() not in summary["app"].lower():
        return False
    return bool(app or pid is not None)


def set_app_volume(volume: float, app: str | None = None, pid: int | None = None, device: str | None = None) -> ToolResult:
    target = max(0.0, min(1.0, float(volume)))
    changed = []

    for session, session_device in _get_sessions():
        try:
            summary = _summarize_session(session, session_device)
            if not _matches(summary, app, pid, device):
                continue
            _session_volume(session).SetMasterVolume(target, None)
            summary["volume"] = target
            changed.append(summary)
        except Exception:
            continue

    if not changed:
        return ToolResult(status="error", error="No matching audio app found")

    return ToolResult(status="ok", content=changed)


def mute_app(muted: bool, app: str | None = None, pid: int | None = None, device: str | None = None) -> ToolResult:
    changed = []

    for session, session_device in _get_sessions():
        try:
            summary = _summarize_session(session, session_device)
            if not _matches(summary, app, pid, device):
                continue
            _session_volume(session).SetMute(bool(muted), None)
            summary["muted"] = bool(muted)
            changed.append(summary)
        except Exception:
            continue

    if not changed:
        return ToolResult(status="error", error="No matching audio app found")

    return ToolResult(status="ok", content=changed)


VOLUME_TOOLS = [
    Tool(
        name="query_volume",
        description="List app volumes by output device.",
        parameters={"type": "object", "properties": {}},
        function=query_volume,
    ),
    Tool(
        name="set_app_volume",
        description="Set app volume from 0 to 1.",
        parameters={
            "type": "object",
            "properties": {
                "volume": {"type": "number", "minimum": 0, "maximum": 1},
                "app": {"type": "string"},
                "pid": {"type": "integer"},
                "device": {"type": "string"},
            },
            "required": ["volume"],
        },
        function=set_app_volume,
    ),
    Tool(
        name="mute_app",
        description="Mute or unmute an app audio session.",
        parameters={
            "type": "object",
            "properties": {
                "muted": {"type": "boolean"},
                "app": {"type": "string"},
                "pid": {"type": "integer"},
                "device": {"type": "string"},
            },
            "required": ["muted"],
        },
        function=mute_app,
    ),
]
