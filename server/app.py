"""Daily Playlist Player — portable backend server.

Standard library only: http.server + sqlite3 + urllib. No npm, no
build step, no API keys.

Run:
    python3 server/app.py
    # then open http://localhost:8000

Options:
    --host, --port, --db PATH, --refresh-today

--refresh-today pre-warms today's pick (resolves Bilibili audio,
YouTube video, lyrics, and the iTunes preview into the caches) and
exits. Schedule it with cron/systemd if you want the live space's
managed daily-pick behaviour:

    0 7 * * * python3 /path/to/server/app.py --refresh-today

API (all JSON unless noted):
    GET  /api/today            today's pick {date, style, style_name, song}
    GET  /api/library?q=&style=
    GET  /api/song?id=
    GET  /api/audio?id=        resolved Bilibili audio {audio_url, bvid, cached}
    GET  /api/audio-stream?id= proxied Bilibili audio (Range supported)
    GET  /api/youtube?id=     {video_id, title, embeddable, cached}
    GET  /api/lyrics?id=      {synced, plain, has_timestamps, cached}
    GET  /api/preview?id=     {preview_url, artwork_url, cached}
    GET  /api/likes           {liked: [song ids]}
    POST /api/like            {id} -> {liked: bool}
    POST /api/refresh         pre-warm today -> {ok, resolved: {...}}
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bilibili
import db
import itunes
import lyrics
import youtube

ROOT = Path(__file__).resolve().parent.parent
CLIENT_DIR = ROOT / "client"
DEFAULT_DB = ROOT / "data" / "playlist.db"


def _resolve_audio(conn, song: dict) -> dict:
    cached = db.get_audio_cache(conn, song["id"])
    if cached:
        return {"audio_url": cached["audio_url"], "bvid": cached["bvid"], "cached": True}
    resolved = bilibili.resolve_audio(song["title"], song["artist"], song["duration_sec"])
    db.set_audio_cache(conn, song["id"], resolved)
    return {"audio_url": resolved["audio_url"], "bvid": resolved["bvid"], "cached": False}


def _resolve_youtube(conn, song: dict) -> dict:
    cached = db.get_youtube_cache(conn, song["id"])
    if cached:
        result = {
            "video_id": cached["video_id"],
            "title": cached["title"],
            "embeddable": bool(cached["embeddable"]),
            "cached": True,
        }
    else:
        resolved = youtube.resolve_video(song["title"], song["artist"])
        db.set_youtube_cache(conn, song["id"], resolved)
        result = {**resolved, "cached": False}
    db.set_video_cache(
        conn,
        song["id"],
        {"platform": "youtube", "video_id": result["video_id"], "title": result["title"]},
    )
    return result


def _resolve_lyrics(conn, song: dict) -> dict:
    cached = db.get_lyrics_cache(conn, song["id"])
    if cached:
        return {
            "synced": json.loads(cached["synced_json"]),
            "plain": cached["plain_text"],
            "has_timestamps": bool(cached["has_timestamps"]),
            "cached": True,
        }
    found = lyrics.fetch_lyrics(song["title"], song["artist"])
    db.set_lyrics_cache(conn, song["id"], found)
    return {**found, "cached": False}


def _resolve_preview(conn, song: dict) -> dict:
    cached = db.get_track_cache(conn, song["id"])
    if cached:
        return {
            "preview_url": cached["preview_url"],
            "artwork_url": cached["artwork_url"],
            "cached": True,
        }
    track = itunes.fetch_track(song["title"], song["artist"])
    db.set_track_cache(conn, song["id"], track)
    return {**track, "cached": False}


def refresh_today(conn) -> dict:
    """Pre-warm today's pick. Failures are reported per source, not fatal."""
    today = db.get_today(conn)
    song = today["song"]
    out: dict = {"date": today["date"], "song": song["title"], "resolved": {}}
    for name, fn in (
        ("audio", _resolve_audio),
        ("youtube", _resolve_youtube),
        ("lyrics", _resolve_lyrics),
        ("preview", _resolve_preview),
    ):
        try:
            out["resolved"][name] = {"ok": True, **fn(conn, song)}
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            out["resolved"][name] = {"ok": False, "error": str(exc)}
    return out


class Handler(BaseHTTPRequestHandler):
    db_path: str = str(DEFAULT_DB)

    # -- helpers ---------------------------------------------------------
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _song_or_400(self, params: dict) -> tuple[dict | None, sqlite3_conn_type]:
        song_id = (params.get("id") or [""])[0]
        conn = db.open_db(self.db_path)
        song = db.get_song(conn, song_id)
        if not song:
            conn.close()
            self._send_json({"error": f"unknown song id: {song_id}"}, 400)
            return None, None
        return song, conn

    # -- routing ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path == "/" or path == "/index.html":
                self._serve_static("index.html")
            elif path.startswith("/api/"):
                self._handle_api(path, params)
            else:
                self._serve_static(path.lstrip("/"))
        except Exception as exc:  # noqa: BLE001 - return 500, don't crash
            self._send_json({"error": str(exc)}, 500)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler name
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {}
        try:
            if parsed.path == "/api/like":
                song_id = str(body.get("id", ""))
                conn = db.open_db(self.db_path)
                if not db.get_song(conn, song_id):
                    conn.close()
                    self._send_json({"error": f"unknown song id: {song_id}"}, 400)
                    return
                liked = db.toggle_like(conn, song_id)
                conn.close()
                self._send_json({"liked": liked})
            elif parsed.path == "/api/refresh":
                conn = db.open_db(self.db_path)
                result = refresh_today(conn)
                conn.close()
                self._send_json({"ok": True, **result})
            else:
                self._send_json({"error": "unknown route"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, 500)

    def _handle_api(self, path: str, params: dict) -> None:
        if path == "/api/today":
            conn = db.open_db(self.db_path)
            today = db.get_today(conn)
            conn.close()
            self._send_json(today)
            return
        if path == "/api/library":
            conn = db.open_db(self.db_path)
            songs = db.list_songs(
                conn,
                query=(params.get("q") or [""])[0],
                style=(params.get("style") or [""])[0],
            )
            conn.close()
            self._send_json({"songs": songs})
            return
        if path == "/api/song":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            liked = db.is_liked(conn, song["id"])
            conn.close()
            self._send_json({**song, "liked": liked})
            return
        if path == "/api/likes":
            conn = db.open_db(self.db_path)
            ids = db.liked_ids(conn)
            songs = [db.get_song(conn, sid) for sid in ids]
            conn.close()
            self._send_json({"liked": [s for s in songs if s]})
            return
        if path == "/api/audio":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            try:
                result = _resolve_audio(conn, song)
            finally:
                conn.close()
            self._send_json(result)
            return
        if path == "/api/audio-stream":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            try:
                resolved = _resolve_audio(conn, song)
            finally:
                conn.close()
            self._proxy_audio(resolved["audio_url"])
            return
        if path == "/api/youtube":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            try:
                result = _resolve_youtube(conn, song)
            finally:
                conn.close()
            self._send_json(result)
            return
        if path == "/api/lyrics":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            try:
                result = _resolve_lyrics(conn, song)
            finally:
                conn.close()
            self._send_json(result)
            return
        if path == "/api/preview":
            song, conn = self._song_or_400(params)
            if song is None:
                return
            try:
                result = _resolve_preview(conn, song)
            finally:
                conn.close()
            self._send_json(result)
            return
        self._send_json({"error": "unknown route"}, 404)

    def _proxy_audio(self, audio_url: str) -> None:
        """Stream Bilibili DASH audio with Range passthrough."""
        headers = dict(bilibili.HEADERS)
        range_header = self.headers.get("Range")
        if range_header:
            headers["Range"] = range_header
        req = urllib.request.Request(audio_url, headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as exc:
            self._send_json({"error": f"audio upstream {exc.code}"}, 502)
            return
        self.send_response(resp.status)
        ctype = resp.headers.get("Content-Type", "audio/mp4")
        self.send_header("Content-Type", ctype)
        if resp.headers.get("Content-Length"):
            self.send_header("Content-Length", resp.headers["Content-Length"])
        if resp.headers.get("Content-Range"):
            self.send_header("Content-Range", resp.headers["Content-Range"])
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            self.wfile.write(chunk)

    def _serve_static(self, name: str) -> None:
        safe = Path(name).name
        target = CLIENT_DIR / safe
        if not target.is_file():
            self._send_text(b"not found", "text/plain; charset=utf-8", 404)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        self._send_text(
            target.read_bytes(), ctype or "application/octet-stream"
        )

    def log_message(self, fmt: str, *args) -> None:  # noqa: N802 - stdlib name
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")


# sqlite3.Connection type for annotations without importing sqlite3 here.
sqlite3_conn_type = object


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Playlist Player server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument(
        "--refresh-today",
        action="store_true",
        help="pre-warm today's pick and exit",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="upsert data/sample_songs.json into the DB and exit",
    )
    args = parser.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = db.open_db(args.db)
    db.init_db(conn)
    added = db.seed_if_empty(conn)
    if args.reseed:
        print(f"Reseeded {db.reseed(conn)} songs from data/sample_songs.json")
        conn.close()
        return
    if args.refresh_today:
        print(json.dumps(refresh_today(conn), ensure_ascii=False, indent=2))
        conn.close()
        return
    conn.close()

    Handler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Daily Playlist Player running at http://{args.host}:{args.port}")
    if added:
        print(f"Seeded {added} sample songs into {args.db}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
