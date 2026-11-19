"""Podcast-Abos: RSS-Feed lesen, die neuesten Folgen laden und optional einen Tonie automatisch damit füllen.

Folgen sind normale Medien (Art „podcast“, Gruppe = Podcast-Titel) unter library/_teddy-manager/media/podcasts/.
Ältere Folgen, die aus dem Abo-Fenster fallen und auf keinem anderen Tonie liegen, wandern in den Papierkorb.
Suche über das iTunes-Podcast-Verzeichnis (frei, ohne Schlüssel).
"""
import email.utils
import hashlib
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import httpx

from . import config, db, media

log = logging.getLogger("podcasts")
ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
UA = {"User-Agent": "TeddyManager (home network)"}
_lock = threading.Lock()
_wake = threading.Event()


def search(term):
    r = httpx.get("https://itunes.apple.com/search", params={"media": "podcast", "term": term, "country": "DE", "limit": 25},
                  timeout=15, headers=UA)
    r.raise_for_status()
    return [{"title": x.get("collectionName") or x.get("trackName"), "author": x.get("artistName") or "",
             "feed": x.get("feedUrl"), "image": x.get("artworkUrl600") or x.get("artworkUrl100")}
            for x in r.json().get("results", []) if x.get("feedUrl")]


def _dur(text):
    if not text:
        return 0.0
    try:
        s = 0.0
        for part in str(text).strip().split(":"):
            s = s * 60 + float(part)
        return s
    except ValueError:
        return 0.0


def parse_feed(url):
    r = httpx.get(url, timeout=30, follow_redirects=True, headers=UA)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    ch = root.find("channel")
    if ch is None:
        raise ValueError("Kein RSS-Feed")
    img = ch.find(f"{ITUNES}image")
    image = img.get("href") if img is not None else (ch.findtext("image/url") or None)
    items = []
    for it in ch.findall("item"):
        enc = it.find("enclosure")
        if enc is None or not enc.get("url") or not (enc.get("type", "audio").startswith("audio") or enc.get("url").endswith((".mp3", ".m4a"))):
            continue
        pub = it.findtext("pubDate")
        try:
            ts = email.utils.parsedate_to_datetime(pub).timestamp() if pub else 0
        except (TypeError, ValueError):
            ts = 0
        eimg = it.find(f"{ITUNES}image")
        items.append({"title": (it.findtext("title") or "Folge").strip(), "url": enc.get("url"),
                      "guid": (it.findtext("guid") or enc.get("url")).strip(), "published": ts,
                      "duration": _dur(it.findtext(f"{ITUNES}duration")),
                      "image": eimg.get("href") if eimg is not None else None})
    items.sort(key=lambda x: x["published"], reverse=True)
    return {"title": (ch.findtext("title") or "Podcast").strip(), "author": (ch.findtext(f"{ITUNES}author") or "").strip(),
            "image": image, "items": items}


def _image(url, label):
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, headers=UA)
        r.raise_for_status()
        return media.store_image(r.content, "cover", label[:120])
    except Exception as e:
        log.info("Bild %s nicht geladen: %s", url, e)
        return None


def subscribe(feed_url, tonie_id=None, keep=10, newest_first=True):
    existing = db.q1("SELECT * FROM podcasts WHERE feed_url=?", (feed_url,))
    if existing and not existing["deleted_at"]:
        return existing["id"]
    feed = parse_feed(feed_url)
    image = _image(feed["image"], feed["title"])
    with db.tx() as c:
        if existing:
            c.execute("""UPDATE podcasts SET deleted_at=NULL, title=?, author=?, image_id=?, tonie_id=?, keep=?, newest_first=?
                         WHERE id=?""", (feed["title"], feed["author"], image, tonie_id, keep, int(newest_first), existing["id"]))
            pid = existing["id"]
        else:
            pid = c.execute("""INSERT INTO podcasts(title,author,feed_url,image_id,tonie_id,keep,newest_first,created)
                               VALUES(?,?,?,?,?,?,?,?)""", (feed["title"], feed["author"], feed_url, image, tonie_id, keep,
                                                            int(newest_first), time.time())).lastrowid
    trigger(pid)
    return pid


def _set(pid, **kw):
    with db.tx() as c:
        c.execute(f"UPDATE podcasts SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), pid))


def _download(item, pod):
    folder = os.path.join(config.MEDIA_DIR, "podcasts", media.slugify(pod["title"], 40))
    os.makedirs(folder, exist_ok=True)
    os.makedirs(config.TMP_DIR, exist_ok=True)
    ext = os.path.splitext(item["url"].split("?")[0])[1].lower()
    if ext not in config.AUDIO_EXT:
        ext = ".mp3"
    fd, tmp = tempfile.mkstemp(dir=config.TMP_DIR, suffix=ext)
    h = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out, httpx.stream("GET", item["url"], timeout=60, follow_redirects=True, headers=UA) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 16):
                h.update(chunk)
                out.write(chunk)
        dst = media.unique_path(folder, media.slugify(item["title"], 50), ext)
        shutil.move(tmp, dst)
        return dst, h.hexdigest()
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def sync(pid):
    """Neueste Folgen laden, ältere aussortieren, verwalteten Tonie aktualisieren."""
    from .builder import worker   # spät importieren (Zyklus vermeiden)
    pod = db.q1("SELECT * FROM podcasts WHERE id=? AND deleted_at IS NULL", (pid,))
    if not pod:
        return
    _set(pid, status="Prüfe Feed", error="")
    try:
        feed = parse_feed(pod["feed_url"])
        window = feed["items"][:max(1, pod["keep"])]
        cover = pod["image_id"]
        wanted = []
        for n, item in enumerate(window):
            m = db.q1("SELECT * FROM media WHERE podcast_id=? AND guid=?", (pid, item["guid"]))
            if m and m["deleted_at"]:
                with db.tx() as c:
                    c.execute("UPDATE media SET deleted_at=NULL WHERE id=?", (m["id"],))
            if not m:
                _set(pid, status=f"Lädt Folge {n + 1}/{len(window)}")
                path, sha = _download(item, pod)
                dup = db.q1("SELECT id FROM media WHERE sha256=?", (sha,))
                if dup:
                    os.remove(path)
                    m = db.q1("SELECT * FROM media WHERE id=?", (dup["id"],))
                else:
                    try:
                        meta = media.read_metadata(path, os.path.basename(path))
                        duration = meta["duration"]
                    except Exception:
                        duration = item["duration"]
                    ep_cover = _image(item["image"], item["title"]) if item["image"] and item["image"] != feed["image"] else cover
                    with db.tx() as c:
                        mid = c.execute("""INSERT INTO media(kind,title,artist,duration,path,orig_name,sha256,cover_id,
                                           album,album_pos,origin,source_url,podcast_id,guid,published,created)
                                           VALUES('podcast',?,?,?,?,?,?,?,?,?,'podcast',?,?,?,?,?)""",
                                        (item["title"][:200], pod["title"][:200], duration,
                                         os.path.relpath(path, config.LIB_DIR), os.path.basename(path), sha,
                                         ep_cover or cover, pod["title"][:200], -int(item["published"] // 60),
                                         item["url"], pid, item["guid"], item["published"], time.time())).lastrowid
                    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
            wanted.append(m["id"])
        # Aus dem Fenster gefallene Folgen aussortieren (wenn kein anderer Tonie sie nutzt)
        for old in db.q("SELECT * FROM media WHERE podcast_id=? AND deleted_at IS NULL", (pid,)):
            if old["id"] in wanted:
                continue
            other = db.q1("""SELECT p.tonie_id FROM playlist p JOIN tonies t ON t.id=p.tonie_id
                             WHERE p.media_id=? AND t.deleted_at IS NULL AND p.tonie_id IS NOT ?""", (old["id"], pod["tonie_id"]))
            if not other:
                with db.tx() as c:
                    c.execute("UPDATE media SET deleted_at=? WHERE id=?", (time.time(), old["id"]))
        if pod["tonie_id"]:
            ids = wanted if pod["newest_first"] else list(reversed(wanted))
            with db.tx() as c:
                c.execute("DELETE FROM playlist WHERE tonie_id=?", (pod["tonie_id"],))
                c.executemany("INSERT INTO playlist(tonie_id,pos,media_id) VALUES(?,?,?)",
                              [(pod["tonie_id"], i, mid) for i, mid in enumerate(ids)])
                c.execute("UPDATE tonies SET mode='playlist', hold=0 WHERE id=?", (pod["tonie_id"],))
            worker.mark(pod["tonie_id"], 2)
        _set(pid, status="", error="", last_check=time.time(), title=feed["title"])
        log.info("Podcast %s aktualisiert: %d Folgen", feed["title"], len(wanted))
    except Exception as e:
        log.warning("Podcast %s: %s", pod["title"], e)
        _set(pid, status="", error=f"Aktualisieren fehlgeschlagen: {str(e)[:200]}", last_check=time.time())


_queue = []


def trigger(pid):
    with _lock:
        if pid not in _queue:
            _queue.append(pid)
    _wake.set()


def loop():
    """Ein Worker; alle 3 Stunden werden alle Abos geprüft."""
    while True:
        _wake.wait(600)
        _wake.clear()
        for p in db.q("SELECT id, last_check FROM podcasts WHERE deleted_at IS NULL"):
            if not p["last_check"] or time.time() - p["last_check"] > 3 * 3600:
                trigger(p["id"])
        while True:
            with _lock:
                pid = _queue.pop(0) if _queue else None
            if pid is None:
                break
            try:
                sync(pid)
            except Exception:
                log.exception("Podcast-Sync %s", pid)


def start():
    threading.Thread(target=loop, daemon=True, name="podcasts").start()
    _wake.set()
