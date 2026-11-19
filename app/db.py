import glob
import os
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY,
  sha256 TEXT UNIQUE NOT NULL,
  file TEXT NOT NULL,
  source TEXT NOT NULL,           -- upload | cover | teddycloud | logo
  label TEXT NOT NULL DEFAULT '',
  created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS media(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  artist TEXT NOT NULL DEFAULT '',
  duration REAL NOT NULL DEFAULT 0,
  path TEXT NOT NULL,             -- relativ zur Library (eigene Dateien unter _teddy-manager/)
  orig_name TEXT NOT NULL DEFAULT '',
  sha256 TEXT UNIQUE NOT NULL,
  cover_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
  created REAL NOT NULL,
  deleted_at REAL
);
CREATE TABLE IF NOT EXISTS stations(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
  created REAL NOT NULL,
  deleted_at REAL
);
CREATE TABLE IF NOT EXISTS tonies(
  id INTEGER PRIMARY KEY,
  uid TEXT UNIQUE NOT NULL,       -- z. B. E0040350XXXXXXXX (wie TeddyCloud, ohne Doppelpunkte)
  name TEXT NOT NULL,
  color TEXT NOT NULL,
  image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
  mode TEXT NOT NULL DEFAULT 'playlist',   -- playlist | radio
  station_id INTEGER REFERENCES stations(id) ON DELETE SET NULL,
  loudnorm INTEGER NOT NULL DEFAULT 1,
  created REAL NOT NULL,
  deleted_at REAL,
  status TEXT NOT NULL DEFAULT 'pending',  -- ok | empty | queued | building | error | pending
  status_msg TEXT NOT NULL DEFAULT '',
  status_at REAL,
  built_key TEXT,
  built_source TEXT,
  built_audio_id INTEGER,
  built_hash TEXT,
  built_seconds TEXT,
  applied_key TEXT,
  hint_until REAL
);
CREATE TABLE IF NOT EXISTS playlist(
  tonie_id INTEGER NOT NULL REFERENCES tonies(id) ON DELETE CASCADE,
  pos INTEGER NOT NULL,
  media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
  PRIMARY KEY(tonie_id, pos)
);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
"""


def connect():
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


@contextmanager
def tx():
    c = connect()
    try:
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def q(sql, args=()):
    with tx() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def q1(sql, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


# Spalten, die nach v1.0 dazugekommen sind: (Tabelle, Spalte, Definition)
MIGRATIONS = [
    ("images", "deleted_at", "REAL"),
    ("media", "album", "TEXT NOT NULL DEFAULT ''"),        # mehrteilige Geschichte: Name der Gruppe
    ("media", "album_pos", "INTEGER NOT NULL DEFAULT 0"),
    ("media", "chapters", "TEXT NOT NULL DEFAULT ''"),     # JSON [{title,start,end}] bei Dateien mit Kapiteln
    ("media", "clip_start", "REAL"),                       # Ausschnitt (z. B. ein Kapitel eines Tonies)
    ("media", "clip_end", "REAL"),
    ("media", "origin", "TEXT NOT NULL DEFAULT 'upload'"), # upload | library | tonie | youtube
    # Import per Link (YouTube / YouTube Music)
    ("media", "source_url", "TEXT NOT NULL DEFAULT ''"),
    ("media", "video_id", "TEXT NOT NULL DEFAULT ''"),     # tatsächlich geladene Video-ID
    ("media", "alt_video_id", "TEXT NOT NULL DEFAULT ''"), # andere Version (Musikvideo <-> Song)
    ("media", "version", "TEXT NOT NULL DEFAULT ''"),      # song | video
    ("media", "cuts", "TEXT NOT NULL DEFAULT ''"),         # JSON [[start,end,herkunft]] – wird beim Bauen entfernt
    ("media", "auto_cuts", "TEXT NOT NULL DEFAULT ''"),    # automatische Vorschläge (zum Zurücksetzen)
    ("media", "loudness", "TEXT NOT NULL DEFAULT ''"),     # loudnorm-Messung (1. Durchlauf)
    ("media", "source_chapters", "TEXT NOT NULL DEFAULT ''"),  # Kapitel der Quelle (zum Aufteilen)
    ("media", "is_new", "INTEGER NOT NULL DEFAULT 0"),     # erscheint im Bereich „Neu“
    ("tonies", "archived", "INTEGER NOT NULL DEFAULT 0"),
    # Einschlafmodus: über sleep_minutes leiser bis sleep_end_pct %, optional danach Stopp / Playlist wiederholen
    ("tonies", "sleep_mode", "INTEGER NOT NULL DEFAULT 0"),
    ("tonies", "sleep_minutes", "INTEGER NOT NULL DEFAULT 30"),
    ("tonies", "sleep_end_pct", "INTEGER NOT NULL DEFAULT 30"),
    ("tonies", "sleep_stop", "INTEGER NOT NULL DEFAULT 1"),
    ("tonies", "sleep_repeat", "INTEGER NOT NULL DEFAULT 1"),
    ("tonies", "hold", "INTEGER NOT NULL DEFAULT 0"),
    ("tonies", "built_at", "REAL"),                         # Zeitpunkt des letzten Builds (für „Box hat aktuellen Stand“)      # Entwurf: Playlist-Änderungen erst nach „Auf Tonie laden“ bauen
    # Podcasts
    ("media", "podcast_id", "INTEGER"),
    ("media", "guid", "TEXT NOT NULL DEFAULT ''"),
    ("media", "published", "REAL"),
]

EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS hidden_tags(uid TEXT PRIMARY KEY, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS box_cache(uid TEXT NOT NULL, audio_id INTEGER NOT NULL, ts REAL NOT NULL, PRIMARY KEY(uid, audio_id));
CREATE TABLE IF NOT EXISTS tag_events(id INTEGER PRIMARY KEY, ruid TEXT NOT NULL, ts REAL NOT NULL, kind TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS tag_events_ts ON tag_events(ts);
CREATE TABLE IF NOT EXISTS podcasts(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT NOT NULL DEFAULT '',
  feed_url TEXT UNIQUE NOT NULL,
  image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
  tonie_id INTEGER REFERENCES tonies(id) ON DELETE SET NULL,   -- Tonie, dessen Playlist das Abo verwaltet
  keep INTEGER NOT NULL DEFAULT 10,                             -- so viele neueste Folgen
  newest_first INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  last_check REAL,
  created REAL NOT NULL,
  deleted_at REAL
);
CREATE TABLE IF NOT EXISTS import_jobs(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,              -- video | playlist
  ref TEXT NOT NULL,               -- Video-ID, Playlist-ID oder Album-Browse-ID
  url TEXT NOT NULL,
  music INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,            -- queued | running | confirm | done | error | cancelled
  step TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  next_at REAL NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  media_id INTEGER,
  payload TEXT NOT NULL DEFAULT '',
  parent_id INTEGER,
  created REAL NOT NULL,
  updated REAL NOT NULL
);
"""


def init():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    os.makedirs(config.BACKUP_DIR, exist_ok=True)
    c = connect()
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    c.executescript(EXTRA_SCHEMA)
    c.execute("UPDATE import_jobs SET status='queued' WHERE status='running'")  # nach Neustart fortsetzen
    for table, col, decl in MIGRATIONS:
        if col not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    c.execute("UPDATE media SET origin='library' WHERE origin='upload' AND path NOT LIKE ?", (config.TM_SUB + "/%",))
    c.commit()
    c.close()


def get_setting(key, default=None):
    r = q1("SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(key, value):
    with tx() as c:
        if value is None:
            c.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, value))


def backup(keep=14):
    """Tägliche Sicherung per SQLite-Backup-API (konsistent auch während Schreibzugriffen)."""
    target = os.path.join(config.BACKUP_DIR, time.strftime("db-%Y%m%d.sqlite"))
    src = connect()
    dst = sqlite3.connect(target + ".tmp")
    src.backup(dst)
    dst.close()
    src.close()
    os.replace(target + ".tmp", target)
    for old in sorted(glob.glob(os.path.join(config.BACKUP_DIR, "db-*.sqlite")))[:-keep]:
        os.remove(old)
    return target
