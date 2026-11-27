"""Fetch lyrics from LRCLIB (https://lrclib.net), a free public API.

No key needed. GET /api/search?track_name=...&artist_name=...

Returns synced lyrics ([mm:ss.xx] lines) when available, otherwise
plain lyrics. Plain-only lyrics have no timestamps; the frontend
builds an estimated timeline from them (see client/app.js).
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

USER_AGENT = "daily-playlist-player/1.0 (https://github.com)"
TIMEOUT = 15


def _get_json(url: str) -> list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _parse_synced(text: str) -> list[list]:
    """'[01:23.45]line' -> [[83.45, 'line']]."""
    out: list[list] = []
    for line in (text or "").splitlines():
        match = re.match(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)", line.strip())
        if not match:
            continue
        sec = int(match.group(1)) * 60 + float(match.group(2))
        out.append([round(sec, 2), match.group(3).strip()])
    return out


def fetch_lyrics(title: str, artist: str) -> dict:
    """Return {synced: [[sec, text]], plain: str, has_timestamps: bool}."""
    qs = urllib.parse.urlencode({"track_name": title, "artist_name": artist})
    try:
        results = _get_json(f"https://lrclib.net/api/search?{qs}")
    except Exception:
        return {"synced": [], "plain": "", "has_timestamps": False}
    if not results:
        return {"synced": [], "plain": "", "has_timestamps": False}
    for entry in results:
        synced = _parse_synced(entry.get("syncedLyrics") or "")
        if synced:
            return {
                "synced": synced,
                "plain": entry.get("plainLyrics") or "",
                "has_timestamps": True,
            }
    first = results[0]
    return {
        "synced": [],
        "plain": first.get("plainLyrics") or "",
        "has_timestamps": False,
    }
