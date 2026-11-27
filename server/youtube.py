"""Resolve an embeddable YouTube video id from public pages.

No API key. Two public endpoints only:

- results page: https://www.youtube.com/results?search_query=...
  (video ids are read out of the page's ytInitialData payload)
- oEmbed: https://www.youtube.com/oembed?url=...&format=json
  (HTTP 200 means the video can be embedded; it also returns its title)

Known limits: this is scraping, not an official API. Page-format
changes, rate limiting, and network blocks (YouTube is unreachable
from ordinary mainland-China networks) will break it. Callers must
fall back to the 30-second iTunes preview when it fails.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 15


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "replace")


def _get_json(url: str) -> dict:
    return json.loads(_get_text(url))


def search_video_ids(query: str, limit: int = 5) -> list[str]:
    """Return candidate video ids in result order."""
    qs = urllib.parse.urlencode({"search_query": query})
    html = _get_text(f"https://www.youtube.com/results?{qs}")
    ids: list[str] = []
    for match in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
        vid = match.group(1)
        if vid not in ids:
            ids.append(vid)
        if len(ids) >= limit:
            break
    return ids


def oembed(video_id: str) -> dict | None:
    """Return {title, author} if the video is embeddable, else None."""
    watch = "https://www.youtube.com/watch?v=" + video_id
    url = (
        "https://www.youtube.com/oembed?url="
        + urllib.parse.quote(watch, safe="")
        + "&format=json"
    )
    try:
        data = _get_json(url)
    except Exception:
        return None
    if not data.get("title"):
        return None
    return {"title": data.get("title", ""), "author": data.get("author_name", "")}


def resolve_video(title: str, artist: str) -> dict:
    """Full flow: search -> first embeddable video id."""
    query = f"{title} {artist}"
    for vid in search_video_ids(query):
        meta = oembed(vid)
        if meta:
            return {
                "video_id": vid,
                "title": meta["title"],
                "author": meta["author"],
                "embeddable": True,
            }
    raise ValueError(f"no embeddable YouTube video found for {query!r}")
