"""SQLite storage for the daily-playlist framework.

Standard library only (sqlite3). The schema lives in data/schema.sql
and mirrors the live space's eight tables; the live ``feedback`` table
is named ``likes`` here for clarity.

Seeding is idempotent: the sample catalog is inserted only when the
songs table is empty, exactly like the live space's ensureSeeded.

The daily pick is deterministic by date, so no cron is needed to keep
it fresh: the style rotates by weekday (7 styles), and the song is
picked by hashing the date inside that style's songs. A daily
``refresh`` (see server/app.py --refresh-today) pre-warms the
audio/video/lyrics caches for today, which is the portable
replacement for the live space's managed cron job.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "data" / "schema.sql"
SAMPLE_PATH = ROOT / "data" / "sample_songs.json"

# Seven styles, rotating by weekday (Monday = index 0).
STYLES: list[tuple[str, str]] = [
    ("cn-pop", "华语流行"),
    ("en-pop", "欧美流行"),
    ("jp-pop", "日语流行"),
    ("ballad", "抒情慢歌"),
    ("anthem", "励志热血"),
    ("night", "深夜抒情"),
    ("weekend", "周末轻快"),
]

# Cache lifetimes in seconds.
AUDIO_TTL = 3600  # Bilibili playurl links are short-lived.
GENERIC_TTL = 7 * 24 * 3600


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def _song_styles(row: sqlite3.Row) -> list[str]:
    try:
        return json.loads(row["styles"])
    except (ValueError, TypeError):
        return []


def seed_if_empty(conn: sqlite3.Connection) -> int:
    """Insert the sample catalog only when songs is empty. Returns rows added."""
    count = conn.execute("SELECT COUNT(*) AS n FROM songs").fetchone()["n"]
    if count:
        return 0
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    added = 0
    for song in data["songs"]:
        conn.execute(
            "INSERT INTO songs (id, title, artist, lang, styles, duration_sec)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                song["id"],
                song["title"],
                song["artist"],
                song.get("lang", ""),
                json.dumps(song.get("styles", []), ensure_ascii=False),
                song.get("duration_sec", 0),
            ),
        )
        added += 1
    conn.commit()
    return added


def reseed(conn: sqlite3.Connection) -> int:
    """Upsert every song from the sample catalog. Returns rows written.

    Use after editing data/sample_songs.json: ``python3 server/app.py --reseed``.
    Likes and caches are untouched.
    """
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    n = 0
    for song in data["songs"]:
        conn.execute(
            "INSERT INTO songs (id, title, artist, lang, styles, duration_sec)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET"
            " title=excluded.title, artist=excluded.artist,"
            " lang=excluded.lang, styles=excluded.styles,"
            " duration_sec=excluded.duration_sec",
            (
                song["id"],
                song["title"],
                song["artist"],
                song.get("lang", ""),
                json.dumps(song.get("styles", []), ensure_ascii=False),
                song.get("duration_sec", 0),
            ),
        )
        n += 1
    conn.commit()
    return n


def song_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "artist": row["artist"],
        "lang": row["lang"],
        "styles": _song_styles(row),
        "duration_sec": row["duration_sec"],
    }


def get_song(conn: sqlite3.Connection, song_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    return song_to_dict(row) if row else None


def list_songs(
    conn: sqlite3.Connection, query: str = "", style: str = ""
) -> list[dict]:
    rows = conn.execute("SELECT * FROM songs ORDER BY id").fetchall()
    out = []
    q = query.strip().lower()
    for row in rows:
        song = song_to_dict(row)
        if style and style not in song["styles"]:
            continue
        if q and q not in song["title"].lower() and q not in song["artist"].lower():
            continue
        out.append(song)
    return out


def get_today(conn: sqlite3.Connection, on_date: date | None = None) -> dict:
    """Deterministic daily pick: style by weekday, song by date hash."""
    today = on_date or date.today()
    iso = today.isoformat()
    style_key, style_name = STYLES[today.weekday()]
    cached = conn.execute(
        "SELECT song_id FROM daily_picks WHERE date = ?", (iso,)
    ).fetchone()
    if cached:
        song = get_song(conn, cached["song_id"])
        if song:
            return {"date": iso, "style": style_key, "style_name": style_name, "song": song}
    candidates = [s for s in list_songs(conn) if style_key in s["styles"]]
    if not candidates:
        candidates = list_songs(conn)
    if not candidates:
        raise ValueError("song catalog is empty; seed the database first")
    digest = hashlib.sha256(f"{iso}:{style_key}".encode("utf-8")).hexdigest()
    pick = candidates[int(digest[:8], 16) % len(candidates)]
    conn.execute(
        "INSERT OR REPLACE INTO daily_picks (date, song_id, style) VALUES (?, ?, ?)",
        (iso, pick["id"], style_key),
    )
    conn.commit()
    return {"date": iso, "style": style_key, "style_name": style_name, "song": pick}


# --- likes ---------------------------------------------------------------

def is_liked(conn: sqlite3.Connection, song_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM likes WHERE song_id = ?", (song_id,)).fetchone()
    return row is not None


def toggle_like(conn: sqlite3.Connection, song_id: str) -> bool:
    """Toggle a like. Returns the new liked state."""
    if is_liked(conn, song_id):
        conn.execute("DELETE FROM likes WHERE song_id = ?", (song_id,))
        conn.commit()
        return False
    conn.execute("INSERT INTO likes (song_id) VALUES (?)", (song_id,))
    conn.commit()
    return True


def liked_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT song_id FROM likes ORDER BY liked_at").fetchall()
    return [r["song_id"] for r in rows]


# --- caches --------------------------------------------------------------

def _cache_get(conn: sqlite3.Connection, table: str, song_id: str, ttl: int) -> dict | None:
    row = conn.execute(f"SELECT * FROM {table} WHERE song_id = ?", (song_id,)).fetchone()
    if not row:
        return None
    if int(row["fetched_at"]) + ttl < int(time.time()):
        return None
    return dict(row)


def _cache_set(conn: sqlite3.Connection, table: str, song_id: str, fields: dict) -> None:
    cols = ["song_id"] + list(fields.keys()) + ["fetched_at"]
    vals = [song_id] + list(fields.values()) + [int(time.time())]
    placeholders = ", ".join("?" for _ in cols)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        vals,
    )
    conn.commit()


def get_audio_cache(conn: sqlite3.Connection, song_id: str) -> dict | None:
    return _cache_get(conn, "audio_cache", song_id, AUDIO_TTL)


def set_audio_cache(conn: sqlite3.Connection, song_id: str, resolved: dict) -> None:
    _cache_set(
        conn,
        "audio_cache",
        song_id,
        {
            "bvid": resolved["bvid"],
            "cid": resolved["cid"],
            "audio_url": resolved["audio_url"],
        },
    )


def get_lyrics_cache(conn: sqlite3.Connection, song_id: str) -> dict | None:
    return _cache_get(conn, "lyrics_cache", song_id, GENERIC_TTL)


def set_lyrics_cache(conn: sqlite3.Connection, song_id: str, lyrics: dict) -> None:
    _cache_set(
        conn,
        "lyrics_cache",
        song_id,
        {
            "synced_json": json.dumps(lyrics["synced"], ensure_ascii=False),
            "plain_text": lyrics["plain"],
            "has_timestamps": 1 if lyrics["has_timestamps"] else 0,
        },
    )


def get_youtube_cache(conn: sqlite3.Connection, song_id: str) -> dict | None:
    return _cache_get(conn, "youtube_cache", song_id, GENERIC_TTL)


def set_youtube_cache(conn: sqlite3.Connection, song_id: str, resolved: dict) -> None:
    _cache_set(
        conn,
        "youtube_cache",
        song_id,
        {
            "video_id": resolved["video_id"],
            "title": resolved["title"],
            "embeddable": 1 if resolved.get("embeddable") else 0,
        },
    )


def set_video_cache(conn: sqlite3.Connection, song_id: str, entry: dict) -> None:
    """Generic per-platform video record (platform, video_id, title)."""
    _cache_set(
        conn,
        "video_cache",
        song_id,
        {
            "platform": entry["platform"],
            "video_id": entry["video_id"],
            "title": entry["title"],
        },
    )


def get_track_cache(conn: sqlite3.Connection, song_id: str) -> dict | None:
    return _cache_get(conn, "track_cache", song_id, GENERIC_TTL)


def set_track_cache(conn: sqlite3.Connection, song_id: str, track: dict) -> None:
    _cache_set(
        conn,
        "track_cache",
        song_id,
        {"preview_url": track["preview_url"], "artwork_url": track["artwork_url"]},
    )
