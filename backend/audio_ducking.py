import os
import sys
import threading

from config import duck_percentage


def _ducking_factor() -> float:
    return max(0.0, min(1.0, float(duck_percentage)))

_lock = threading.RLock()
_enabled = False
_listening = False
_ducked = False
_original_volumes = {}
_warned_unavailable = False


def set_enabled(enabled: bool, listening: bool | None = None) -> None:
    global _enabled, _listening

    with _lock:
        _enabled = bool(enabled)
        if listening is not None:
            _listening = bool(listening)
        _sync_locked()


def set_listening(listening: bool) -> None:
    global _listening

    with _lock:
        _listening = bool(listening)
        _sync_locked()


def restore() -> None:
    with _lock:
        _restore_locked()


def _sync_locked() -> None:
    if _enabled and _listening:
        _duck_locked()
    else:
        _restore_locked()


def _duck_locked() -> None:
    global _ducked, _original_volumes

    sessions = _get_audio_sessions()
    if sessions is None:
        return

    originals = dict(_original_volumes)
    own_pid = os.getpid()

    for session in sessions:
        if _is_own_session(session, own_pid):
            continue

        key = _session_key(session)
        if key in originals:
            continue

        volume = _get_session_volume(session)
        if volume is None:
            continue

        try:
            current = float(volume.GetMasterVolume())
            originals[key] = current
            volume.SetMasterVolume(current * _ducking_factor(), None)
        except Exception as exc:
            print(f"Audio ducking skipped one session: {exc}")

    _original_volumes = originals
    _ducked = bool(originals)


def _restore_locked() -> None:
    global _ducked, _original_volumes

    if not _ducked:
        _original_volumes = {}
        return

    sessions = _get_audio_sessions()
    if sessions is not None:
        for session in sessions:
            key = _session_key(session)
            if key not in _original_volumes:
                continue

            volume = _get_session_volume(session)
            if volume is None:
                continue

            try:
                volume.SetMasterVolume(_original_volumes[key], None)
            except Exception as exc:
                print(f"Audio ducking restore skipped one session: {exc}")

    _original_volumes = {}
    _ducked = False


def _get_audio_sessions():
    global _warned_unavailable

    if sys.platform != "win32":
        if not _warned_unavailable:
            print("Audio ducking is only available on Windows.")
            _warned_unavailable = True
        return None

    try:
        import comtypes
        from pycaw.pycaw import AudioUtilities

        comtypes.CoInitialize()
        return AudioUtilities.GetAllSessions()
    except Exception as exc:
        if not _warned_unavailable:
            print(f"Audio ducking unavailable: {exc}")
            _warned_unavailable = True
        return None


def _get_session_volume(session):
    try:
        from pycaw.pycaw import ISimpleAudioVolume

        return session._ctl.QueryInterface(ISimpleAudioVolume)
    except Exception:
        return None


def _is_own_session(session, own_pid: int) -> bool:
    pid = getattr(session, "ProcessId", None)
    if pid == own_pid:
        return True

    process = getattr(session, "Process", None)
    return getattr(process, "pid", None) == own_pid


def _session_key(session) -> str:
    ctl = getattr(session, "_ctl", None)
    if ctl is not None:
        for method_name in ("GetSessionInstanceIdentifier", "GetSessionIdentifier"):
            method = getattr(ctl, method_name, None)
            if method is None:
                continue
            try:
                return str(method())
            except Exception:
                pass

    pid = getattr(session, "ProcessId", None)
    process = getattr(session, "Process", None)
    name = ""
    if process is not None:
        try:
            name = process.name()
        except Exception:
            name = ""

    return f"{pid}:{name}:{id(session)}"
