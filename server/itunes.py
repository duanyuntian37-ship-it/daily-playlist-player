"""30-second previews and artwork from the public iTunes Search API.

No key needed. GET https://itunes.apple.com/search?term=...&media=music

The preview is the fallback when a song has no usable Bilibili or
YouTube version. The artwork URL is used for the player cover.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

USER_AGENT = "daily-playlist-player/1.0 (https://github.com)"
TIMEOUT = 15


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_track(title: str, artist: str) -> dict:
    """Return {preview_url, artwork_url}; empty strings when not found."""
    qs = urllib.parse.urlencode(
        {"term": f"{title} {artist}", "media": "music", "entity": "song", "limit": "5"}
    )
    try:
        data = _get_json(f"https://itunes.apple.com/search?{qs}")
    except Exception:
        return {"preview_url": "", "artwork_url": ""}
    results = data.get("results", []) or []
    if not results:
        return {"preview_url": "", "artwork_url": ""}
    best = results[0]
    art = best.get("artworkUrl100", "")
    if art:
        art = art.replace("100x100bb", "600x600bb")
    return {"preview_url": best.get("previewUrl", ""), "artwork_url": art}
