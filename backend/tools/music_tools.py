import time
import webbrowser
from urllib.parse import quote, quote_plus

from config import music_provider
from backend.tools.base import Tool, ToolResult
from backend.tools.browser_tools import open_or_reuse_page
from backend.tools.keyboard import (
    VK_MEDIA_NEXT_TRACK,
    VK_MEDIA_PLAY_PAUSE,
    VK_MEDIA_PREV_TRACK,
    press_key,
)


def next_track() -> ToolResult:
    press_key(VK_MEDIA_NEXT_TRACK)
    return ToolResult(status="ok", content="Next track")


def previous_track() -> ToolResult:
    press_key(VK_MEDIA_PREV_TRACK)
    return ToolResult(status="ok", content="Previous track")


def pause_music() -> ToolResult:
    press_key(VK_MEDIA_PLAY_PAUSE)
    return ToolResult(status="ok", content="Toggled play/pause")


def _youtube_music_url(song: str) -> str:
    try:
        from ytmusicapi import YTMusic

        results = YTMusic().search(song, filter="songs", limit=1)
        if results:
            video_id = results[0].get("videoId")
            if video_id:
                return f"https://music.youtube.com/watch?v={video_id}"
    except Exception:
        pass

    return f"https://music.youtube.com/search?q={quote_plus(song)}"


def play_music(song: str) -> ToolResult:
    if not song.strip():
        return ToolResult(status="error", error="Song name is required")

    provider = str(music_provider).strip().lower()
    if provider == "spotify":
        url = f"spotify:search:{quote(song)}"
        webbrowser.open(url)
    elif provider == "youtube_music":
        url = _youtube_music_url(song)
        open_or_reuse_page(url, "music.youtube.com")
    else:
        return ToolResult(status="error", error="Unknown music_provider")

    time.sleep(1.0)
    press_key(VK_MEDIA_PLAY_PAUSE)
    return ToolResult(status="ok", content=f"Playing via {provider}")


MUSIC_TOOLS = [
    Tool(
        name="next_track",
        description="Skip to next music track.",
        parameters={"type": "object", "properties": {}},
        function=next_track,
    ),
    Tool(
        name="previous_track",
        description="Previous music track.",
        parameters={"type": "object", "properties": {}},
        function=previous_track,
    ),
    Tool(
        name="play_music",
        description="Play a song by name.",
        parameters={
            "type": "object",
            "properties": {"song": {"type": "string"}},
            "required": ["song"],
        },
        function=play_music,
    ),
    Tool(
        name="pause_music",
        description="Toggle music pause/play.",
        parameters={"type": "object", "properties": {}},
        function=pause_music,
    ),
]
