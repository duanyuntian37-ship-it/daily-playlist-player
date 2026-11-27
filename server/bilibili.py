"""Resolve full-length audio from Bilibili's public web APIs.

No API key is used. These are the same public endpoints a browser hits
when it opens a Bilibili video page:

- search:   https://api.bilibili.com/x/web-interface/search/all/v2
- pagelist:  https://api.bilibili.com/x/player/pagelist
- playurl:   https://api.bilibili.com/x/player/playurl (DASH audio, fnval=16)

The audio URL returned by playurl is a time-limited DASH audio stream.
Play it through the server-side proxy (``/api/audio-stream``) so the
browser request carries the right Referer/User-Agent headers.

Known limits: search results are ranked by Bilibili and may include
covers, live recordings, or fan uploads; we pick by duration match.
Rate limiting and risk control can reject requests from some networks.
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
HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
TIMEOUT = 15


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _parse_duration(text: str) -> int:
    """'03:45' -> 225; '1:02:03' -> 3723; anything else -> 0."""
    if not text:
        return 0
    try:
        nums = [int(p) for p in str(text).strip().split(":")]
    except ValueError:
        return 0
    total = 0
    for n in nums:
        total = total * 60 + n
    return total


def _clean_title(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html or "")
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .strip()
    )


def search_video(keyword: str, limit: int = 8) -> list[dict]:
    """Search Bilibili videos. Returns [{bvid, title, author, duration_sec}]."""
    qs = urllib.parse.urlencode({"keyword": keyword})
    data = _get_json(
        f"https://api.bilibili.com/x/web-interface/search/all/v2?{qs}"
    )
    out: list[dict] = []
    for block in data.get("data", {}).get("result", []) or []:
        if block.get("result_type") != "video":
            continue
        for item in block.get("data", []) or []:
            bvid = item.get("bvid", "")
            if not bvid:
                continue
            out.append(
                {
                    "bvid": bvid,
                    "title": _clean_title(item.get("title", "")),
                    "author": item.get("author", ""),
                    "duration_sec": _parse_duration(item.get("duration", "")),
                }
            )
            if len(out) >= limit:
                return out
    return out


def get_cid(bvid: str) -> int:
    data = _get_json(
        f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}&jsonp=jsonp"
    )
    pages = data.get("data", []) or []
    if not pages:
        raise ValueError(f"no pagelist for {bvid}")
    return int(pages[0]["cid"])


def get_audio_url(bvid: str, cid: int) -> tuple[str, int]:
    """Return (dash_audio_url, duration_sec) for a video."""
    qs = urllib.parse.urlencode(
        {
            "bvid": bvid,
            "cid": cid,
            "qn": "0",
            "fnval": "16",
            "fnver": "0",
            "fourk": "1",
        }
    )
    data = _get_json(f"https://api.bilibili.com/x/player/playurl?{qs}")
    dash = (data.get("data", {}) or {}).get("dash", {}) or {}
    audios = dash.get("audio", []) or []
    if not audios:
        raise ValueError(f"no DASH audio for {bvid}")
    best = max(audios, key=lambda a: a.get("bandwidth", 0))
    duration = int((data.get("data", {}) or {}).get("timelength", 0) // 1000)
    return best["baseUrl"], duration


def resolve_audio(title: str, artist: str, expect_sec: int = 0) -> dict:
    """Full flow: search -> pick by duration -> cid -> DASH audio URL."""
    keyword = f"{title} {artist}"
    cands = search_video(keyword)
    if not cands:
        raise ValueError(f"no Bilibili video found for {keyword!r}")
    if expect_sec:
        # Prefer the candidate whose duration is closest to the song's.
        cands.sort(key=lambda c: abs((c["duration_sec"] or 0) - expect_sec))
    best = cands[0]
    cid = get_cid(best["bvid"])
    url, dur = get_audio_url(best["bvid"], cid)
    return {
        "bvid": best["bvid"],
        "cid": cid,
        "title": best["title"],
        "author": best["author"],
        "audio_url": url,
        "duration_sec": dur or best["duration_sec"],
    }
