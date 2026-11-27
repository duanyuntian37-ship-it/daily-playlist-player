-- Daily Playlist Player — SQLite schema.
-- Eight tables, mirroring the live space's data model.
-- The live space calls the likes table "feedback"; it is renamed here
-- for clarity. No user data ships with this schema.

CREATE TABLE IF NOT EXISTS songs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT '',
    styles TEXT NOT NULL DEFAULT '[]',
    duration_sec INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    song_id TEXT NOT NULL REFERENCES songs(id),
    style TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS likes (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    liked_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audio_cache (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    bvid TEXT NOT NULL DEFAULT '',
    cid INTEGER NOT NULL DEFAULT 0,
    audio_url TEXT NOT NULL DEFAULT '',
    fetched_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lyrics_cache (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    synced_json TEXT NOT NULL DEFAULT '[]',
    plain_text TEXT NOT NULL DEFAULT '',
    has_timestamps INTEGER NOT NULL DEFAULT 0,
    fetched_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS video_cache (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    platform TEXT NOT NULL DEFAULT '',
    video_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    fetched_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS youtube_cache (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    video_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    embeddable INTEGER NOT NULL DEFAULT 0,
    fetched_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS track_cache (
    song_id TEXT PRIMARY KEY REFERENCES songs(id),
    preview_url TEXT NOT NULL DEFAULT '',
    artwork_url TEXT NOT NULL DEFAULT '',
    fetched_at INTEGER NOT NULL DEFAULT 0
);
