"""„Zuletzt aufgelegt“: liest TeddyClouds Log (Docker-Log-API über einen nur lesenden Socket-Proxy).

Ohne RTNL meldet die Box das Auflegen einer Figur nicht direkt. Sie schickt aber bei fast jedem Auflegen einen
„claim“ (bzw. bei neuem Inhalt eine Inhaltsanfrage) an TeddyCloud – diese Zeilen werten wir aus:
  >> client claim requested rUID <ruid>
  >> client requested content for rUID <ruid>
Eine Zuordnung zur einzelnen Box steht nicht im Log.
"""
import logging
import re
import struct
import threading
import time
from datetime import datetime

import httpx

from . import config, db

log = logging.getLogger("boxlog")
LINE = re.compile(r"^(\S+)\s.*?(claim requested rUID|requested content for rUID) ([0-9a-f]{16})")
# Beim Aufwachen meldet die Box ihren Speicher: „uid: E004…, nocloud: 1, live: 0, updated: 0, audioid: 6AE79882 (…)“
FRESH = re.compile(r"^(\S+)\s.*process_freshness_check\|\s+uid: (E0[0-9A-F]{14}), .*?audioid: ([0-9A-F]{8})")
_state = {"ok": None, "error": ""}


def _frames(raw):
    """Docker-Log-Stream (ohne TTY) ist gemultiplext: 8 Byte Kopf (Typ, 0, 0, 0, Länge) + Daten."""
    out, i = [], 0
    while i + 8 <= len(raw):
        size = struct.unpack(">I", raw[i + 4:i + 8])[0]
        out.append(raw[i + 8:i + 8 + size])
        i += 8 + size
    if i == 0 and raw:   # Container mit TTY: kein Multiplexing
        return [raw]
    return out


def _ts(iso):
    return datetime.fromisoformat(iso[:26].replace("Z", "") + "+00:00").timestamp()


def poll(since):
    r = httpx.get(config.TC_LOG_URL, params={"stdout": 1, "stderr": 1, "timestamps": 1, "since": int(since)}, timeout=15)
    r.raise_for_status()
    events, cache = [], []
    for chunk in _frames(r.content):
        for line in chunk.decode("utf-8", "replace").splitlines():
            m = LINE.search(line)
            if m:
                events.append((_ts(m.group(1)), m.group(3), "claim" if m.group(2).startswith("claim") else "content"))
                continue
            f = FRESH.search(line)
            if f:
                cache.append((f.group(2), int(f.group(3), 16), _ts(f.group(1))))
    if cache:
        store_cache(cache)
    return events


def store_cache(rows):
    """Welche Audio-ID hat eine Box für eine Figur gespeichert (letzte Meldung je ID)."""
    with db.tx() as c:
        c.executemany("""INSERT INTO box_cache(uid, audio_id, ts) VALUES(?,?,?)
                         ON CONFLICT(uid, audio_id) DO UPDATE SET ts=MAX(ts, excluded.ts)""", rows)


def box_state(t):
    """Hat die Box den aktuellen Stand eines Custom-Tonies? -> current | old | pending | None
    TeddyCloud vergibt Audio-IDs als Zeit - 0x50000000; die Box meldet sie mit dem Versatz zurück."""
    if not enabled() or t["mode"] != "playlist" or not t["built_audio_id"]:
        return None
    expected = (int(t["built_audio_id"]) + 0x50000000) & 0xFFFFFFFF
    built_at = t["built_at"] or ((t["hint_until"] or 0) - 900)
    from . import tc
    ruid = tc.uid_to_ruid(t["uid"])
    if db.q1("SELECT 1 FROM box_cache WHERE uid=? AND audio_id=?", (t["uid"], expected)) or \
            db.q1("SELECT 1 FROM tag_events WHERE ruid=? AND kind='content' AND ts>?", (ruid, built_at)):
        return "current"
    if db.q1("SELECT 1 FROM box_cache WHERE uid=? AND ts>?", (t["uid"], built_at)):
        return "old"
    return "pending"


def store(events):
    added = 0
    for ts, ruid, kind in sorted(events):
        last = db.q1("SELECT ts FROM tag_events WHERE ruid=? ORDER BY ts DESC LIMIT 1", (ruid,))
        if last and ts - last["ts"] < 20:   # claim + content desselben Auflegens zusammenfassen
            continue
        with db.tx() as c:
            c.execute("INSERT INTO tag_events(ruid, ts, kind) VALUES(?,?,?)", (ruid, ts, kind))
        added += 1
    return added


def loop():
    last = time.time() - 120
    while True:
        try:
            events = poll(last - 2)
            if events:
                store(events)
                last = max(last, max(e[0] for e in events))
            else:
                last = max(last, time.time() - 30)
            _state.update(ok=True, error="")
        except Exception as e:
            if _state["ok"] is not False:
                log.warning("TeddyCloud-Log nicht lesbar (%s) – „Zuletzt aufgelegt“ pausiert", e)
            _state.update(ok=False, error=str(e)[:200])
            time.sleep(27)
        time.sleep(3)
        if int(time.time()) % 3600 < 4:   # Verlauf auf 90 Tage begrenzen
            with db.tx() as c:
                c.execute("DELETE FROM tag_events WHERE ts < ?", (time.time() - 90 * 86400,))


def enabled():
    return bool(config.TC_LOG_URL)


def status():
    return {"enabled": enabled(), **_state}


def start():
    if enabled():
        threading.Thread(target=loop, daemon=True, name="boxlog").start()
