"""Nur-lesender Zugriff auf TeddyClouds tonies.json (Bildersuche, Einordnung Original/Kreativ)."""
import json
import logging
import os
import threading

from . import config

log = logging.getLogger("toniesjson")
_lock = threading.Lock()
_cache = {"mtime": None, "items": [], "by_model": {}, "by_audio": {}, "pics": set()}


def _load():
    path = os.path.join(config.TC_CONFIG_DIR, "tonies.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return _cache
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                with open(path, encoding="utf-8") as f:
                    items = json.load(f)
                _cache.update(mtime=mtime, items=items,
                              by_model={i.get("model"): i for i in items if i.get("model")},
                              by_audio={str(a): i for i in items for a in (i.get("audio_id") or [])},
                              pics={i.get("pic") for i in items if i.get("pic")})
            except (OSError, ValueError) as e:
                log.warning("tonies.json nicht lesbar: %s", e)
    return _cache


def category(model):
    """-> 'original' | 'kreativ' | None"""
    if not model:
        return None
    item = _load()["by_model"].get(model)
    if not item:
        return None
    return "kreativ" if "creative" in (item.get("category") or "").lower() else "original"


def search(q, limit=60):
    q = q.strip().lower()
    out, seen = [], set()
    for i in _load()["items"]:
        pic = i.get("pic")
        if not pic or pic in seen:
            continue
        hay = f"{i.get('title') or ''} {i.get('series') or ''}".lower()
        if q and q not in hay:
            continue
        if not i.get("language", "de").startswith("de") and not q:
            continue
        seen.add(pic)
        out.append({"title": i.get("title") or i.get("series") or "", "pic": pic})
        if len(out) >= limit:
            break
    return out


def known_pic(url):
    return url in _load()["pics"]


def by_audio(audio_id):
    return _load()["by_audio"].get(str(audio_id)) if audio_id is not None else None
