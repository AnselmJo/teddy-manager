"""Build-Queue (genau ein Worker) und Abgleich Soll-Zustand (DB) -> TeddyCloud.

Der Zustand in der DB ist die Quelle der Wahrheit. reconcile() ist idempotent:
  1. Soll-Inhalt bestimmen (Playlist / Radio / leer) und dessen Schlüssel berechnen.
  2. Playlist: TAF nur neu bauen, wenn sich der Inhalt geändert hat oder die Datei fehlt.
     Gebaut wird in eine temporäre Datei, geprüft (Header gültig, Kapitelzahl), dann umbenannt.
     Bis dahin bleibt die alte TAF aktiv.
  3. Quelle (content json) und Anzeige (tonies.custom.json) setzen, wenn sie vom Soll abweichen.
"""
import hashlib
import json
import logging
import os
import threading
import time
import traceback

from . import config, db, media, tc

log = logging.getLogger("builder")


class BuildError(Exception):
    pass


def model_for(uid):
    return config.MODEL_PREFIX + uid


def _key(obj):
    return hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def playlist_tracks(tonie_id):
    return db.q("""SELECT m.* FROM playlist p JOIN media m ON m.id=p.media_id
                   WHERE p.tonie_id=? AND m.deleted_at IS NULL ORDER BY p.pos""", (tonie_id,))


def desired(t):
    if t["mode"] == "radio":
        st = db.q1("SELECT * FROM stations WHERE id=? AND deleted_at IS NULL", (t["station_id"],)) \
            if t["station_id"] else None
        if st:
            return {"kind": "radio", "key": "radio:" + st["url"], "station": st, "tracks": []}
        return {"kind": "empty", "key": "", "station": None, "tracks": []}
    tracks = playlist_tracks(t["id"])
    if not tracks:
        return {"kind": "empty", "key": "", "station": None, "tracks": [], "units": []}
    units = units_for(tracks)
    if t.get("sleep_mode"):
        units = apply_sleep(units, t)
    if all(u["start"] is None and not u["cuts"] and not u.get("gain") for u in units):   # Schlüsselformat von v1.0
        key = _key({"ln": bool(t["loudnorm"]), "m": [m["sha256"] for m in tracks]})
    else:
        key = _key({"ln": bool(t["loudnorm"]),
                    "u": [[u["media"]["sha256"], u["start"], u["end"]] + ([u["cuts"]] if u["cuts"] else [])
                          + ([u["gain"]] if u.get("gain") else []) for u in units]})
    return {"kind": "playlist", "key": key, "station": None, "tracks": tracks, "units": units}


def apply_sleep(units, t):
    """Einschlafmodus: Playlist bis zur Dauer wiederholen (optional), dort stoppen (optional) und über die Dauer
    gleichmäßig leiser werden bis sleep_end_pct %. Die Lautstärkekurve wird in die TAF gerechnet –
    die Box selbst kann so etwas nicht."""
    total_s = max(1, int(t["sleep_minutes"])) * 60
    end = max(0, min(100, int(t["sleep_end_pct"]))) / 100
    base = [u for u in units if u["duration"] > 0.5]
    if not base:
        return units
    seq = list(base)
    if t["sleep_stop"] and t["sleep_repeat"]:
        while sum(u["duration"] for u in seq) < total_s and len(seq) < config.MAX_TRACKS:
            seq += base
    out, offset = [], 0.0
    for u in seq:
        if t["sleep_stop"] and offset >= total_s:
            break
        u = dict(u)
        trim = None
        if t["sleep_stop"] and offset + u["duration"] > total_s:
            trim = round(total_s - offset, 2)
            u["duration"] = trim
        u["gain"] = {"o": round(offset, 2), "d": total_s, "e": end, "trim": trim,
                     "fade": bool(t["sleep_stop"] and (trim is not None or offset + u["duration"] >= total_s - 0.5))}
        offset += u["duration"]
        out.append(u)
    if out and t["sleep_stop"]:
        out[-1]["gain"]["fade"] = True
    return out[:config.MAX_TRACKS]


def merged_cuts(m):
    """Schnittbereiche eines Mediums (Original-Zeitachse), sortiert und zusammengefasst."""
    raw = sorted((float(c[0]), float(c[1])) for c in json.loads(m.get("cuts") or "[]") if float(c[1]) > float(c[0]))
    out = []
    for a, b in raw:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _unit(m, start, end, title, length):
    """Einheit mit den Schnitten, die in [start, end] fallen; Dauer ohne Schnitte."""
    lo, hi = start or 0.0, end if end is not None else length
    cuts = [(max(a, lo), min(b, hi)) for a, b in merged_cuts(m) if b > lo and a < hi]
    removed = sum(b - a for a, b in cuts)
    return {"media": m, "start": start, "end": end, "title": title, "cuts": [[round(a, 3), round(b, 3)] for a, b in cuts],
            "duration": max(0.0, (hi - lo) - removed)}


def units_for(tracks):
    """Ein Kapitel auf der Box je Einheit: ganze Datei, Ausschnitt oder jedes Kapitel einer Datei."""
    units = []
    for m in tracks:
        chapters = json.loads(m["chapters"] or "[]")
        if m["clip_start"] is not None:
            units.append(_unit(m, m["clip_start"], m["clip_end"], m["title"], m["clip_end"]))
        elif len(chapters) > 1:
            n = len(chapters)
            for i, c in enumerate(chapters):
                units.append(_unit(m, c["start"], c["end"], c.get("title") or f"{m['title']} ({i + 1}/{n})", c["end"]))
        else:
            units.append(_unit(m, None, None, m["title"], m["duration"]))
    return units


def tonie_pic(t):
    """Dateiname des Bildes: eigenes Bild oder Münze in der Tonie-Farbe."""
    img = db.q1("SELECT file FROM images WHERE id=? AND deleted_at IS NULL", (t["image_id"],)) if t["image_id"] else None
    return img["file"] if img else media.coin_image(config.color_hex(t["color"]))


def lib_path(source):
    if source and source.startswith("lib://"):
        return os.path.join(config.LIB_DIR, source[len("lib://"):])
    return None


def custom_entry(t, d):
    if d["kind"] == "playlist":
        tracks = [u["title"] for u in d["units"]]
        audio, hashes = [str(t["built_audio_id"])], [t["built_hash"] or ""]
    else:
        tracks = [d["station"]["name"]] if d["station"] else []
        audio, hashes = [], []
    return {
        "model": model_for(t["uid"]), "audio_id": audio, "hash": hashes,
        "title": f"{config.TERM} - {t['name']}", "series": config.TERM, "episodes": t["name"],
        "tracks": tracks, "release": "0", "language": "de-de", "category": "custom",
        "pic": f"{config.IMG_TC_PREFIX}/{tonie_pic(t)}",
    }


def set_status(tid, status, msg=""):
    with db.tx() as c:
        c.execute("UPDATE tonies SET status=?, status_msg=?, status_at=? WHERE id=?", (status, msg, time.time(), tid))


def build(t, units):
    if len(units) > config.MAX_TRACKS:
        raise BuildError(f"Höchstens {config.MAX_TRACKS} Kapitel pro Tonie möglich ({len(units)}).")
    total = sum(u["duration"] for u in units)
    inputs = []
    for i, u in enumerate(units):
        m = u["media"]
        if not os.path.exists(config.media_abs(m["path"])):
            raise BuildError(f"Datei für „{m['title']}“ fehlt.")
        if t["loudnorm"] or u["start"] is not None or u["cuts"] or u.get("gain"):
            set_status(t["id"], "building", f"{i + 1}/{len(units)}")
            inputs.append(media.prepare_unit(m, u["start"], u["end"], bool(t["loudnorm"]), u["cuts"], u.get("gain")))
        else:
            inputs.append(m["path"])

    set_status(t["id"], "building", f"TAF ({len(units)})")
    os.makedirs(config.BUILD_DIR, exist_ok=True)
    tmp_name = f".tmp-{t['uid']}-{int(time.time() * 1000)}.taf"
    tmp_abs = os.path.join(config.BUILD_DIR, tmp_name)
    try:
        tc.encode(inputs, f"{config.TM_SUB}/build/{tmp_name}", timeout=180 + total / 3)
        entry = next((f for f in tc.file_index(f"/{config.TM_SUB}/build") if f.get("name") == tmp_name), None)
        hdr = (entry or {}).get("tafHeader") or {}
        if not hdr.get("valid"):
            raise BuildError("Die gebaute TAF ist ungültig (Header-Prüfung fehlgeschlagen).")
        if len(hdr.get("trackSeconds") or []) != len(units):
            raise BuildError(f"Kapitelzahl stimmt nicht: {len(hdr.get('trackSeconds') or [])} statt {len(units)}.")
        final_name = f"{t['uid'][-4:].lower()}-{media.slugify(t['name'], 40)}.taf"
        os.replace(tmp_abs, os.path.join(config.BUILD_DIR, final_name))
    finally:
        if os.path.exists(tmp_abs):
            os.remove(tmp_abs)

    new_source = f"lib://{config.TM_SUB}/build/{final_name}"
    old_source = t["built_source"]
    with db.tx() as c:
        c.execute("""UPDATE tonies SET built_key=?, built_source=?, built_audio_id=?, built_hash=?, built_seconds=?,
                     hint_until=?, built_at=strftime('%s','now') WHERE id=?""",
                  (desired(t)["key"], new_source, hdr.get("audioId"), (hdr.get("sha1Hash") or "").upper(),
                   json.dumps(hdr.get("trackSeconds")), time.time() + 15 * 60, t["id"]))
    log.info("Gebaut: %s (%s) -> %s, audio_id=%s", t["name"], t["uid"], final_name, hdr.get("audioId"))
    return old_source, new_source


def remove_old_build(old_source, new_source):
    """Alte TAF entfernen – nur eigene Dateien und nur, wenn kein anderer Tonie sie nutzt."""
    if not old_source or old_source == new_source or not old_source.startswith(f"lib://{config.TM_SUB}/build/"):
        return
    if db.q1("SELECT id FROM tonies WHERE built_source=?", (old_source,)):
        return
    p = lib_path(old_source)
    if p and os.path.exists(p):
        os.remove(p)
        log.info("Alte TAF entfernt: %s", p)


def reconcile(tid, force=False):
    t = db.q1("SELECT * FROM tonies WHERE id=?", (tid,))
    if not t:
        return
    ruid, model = tc.uid_to_ruid(t["uid"]), model_for(t["uid"])

    if t["deleted_at"]:
        if t["applied_key"] != "deleted" or force:
            info = tc.tag_info(ruid)
            if (info.get("tonieInfo") or {}).get("model") == model or info.get("source") == t["built_source"]:
                tc.content_set(ruid, source="", tonie_model="")
            tc.custom_delete([model])
            tc.reload_tonies()
            with db.tx() as c:
                c.execute("UPDATE tonies SET applied_key='deleted', status='deleted', status_msg='' WHERE id=?", (tid,))
        return

    d = desired(t)
    if d["kind"] == "playlist" and t["hold"] and t["built_key"] != d["key"]:
        # Entwurf: noch nicht bauen – die Box behält den bisherigen Inhalt, bis „Auf Tonie laden“ kommt
        set_status(tid, "draft", "")
        return
    old_new = None
    if d["kind"] == "playlist":
        src_path = lib_path(t["built_source"])
        if t["built_key"] != d["key"] or not src_path or not os.path.exists(src_path):
            set_status(tid, "building", "Wird vorbereitet…")
            old_new = build(t, d["units"])
            t = db.q1("SELECT * FROM tonies WHERE id=?", (tid,))
        source = t["built_source"]
    elif d["kind"] == "radio":
        source = d["station"]["url"]
    else:
        source = ""

    entry = custom_entry(t, d)
    apply_key = _key([source, d["kind"], entry])
    info = tc.tag_info(ruid)
    in_sync = info.get("source", "") == source and (info.get("tonieInfo") or {}).get("model") == model
    if force or apply_key != t["applied_key"] or not in_sync:
        live = d["kind"] == "radio"
        tc.content_set(ruid, source=source, tonie_model=model, live=live, nocloud=True)
        try:
            tc.custom_upsert(entry)
        except tc.DuplicateAudioId as e:
            # Verknüpfung läuft über tonie_model; audio_id/hash sind nur Zusatz -> ohne sie speichern.
            log.warning("%s: %s – speichere Eintrag ohne audio_id/hash", t["uid"], e)
            tc.custom_upsert(dict(entry, audio_id=[], hash=[]))
        tc.reload_tonies()
        with db.tx() as c:
            c.execute("UPDATE tonies SET applied_key=? WHERE id=?", (apply_key, tid))
        log.info("TeddyCloud aktualisiert: %s (%s) source=%s", t["name"], t["uid"], source or "(leer)")
    if old_new:
        remove_old_build(*old_new)

    set_status(tid, "empty" if d["kind"] == "empty" else "ok", "")


class Worker(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="build-worker")
        self.cv = threading.Condition()
        self.due = {}      # tonie_id -> (zeitpunkt, force)
        self.current = None

    def mark(self, tid, delay=None, force=False):
        delay = config.DEBOUNCE_S if delay is None else delay
        with self.cv:
            prev = self.due.get(tid)
            self.due[tid] = (time.time() + delay, force or (prev[1] if prev else False))
            self.cv.notify()
        if self.current != tid:
            with db.tx() as c:
                c.execute("UPDATE tonies SET status='queued', status_msg='' WHERE id=? AND deleted_at IS NULL", (tid,))

    def mark_all(self, delay=0, force=False):
        for r in db.q("SELECT id FROM tonies"):
            self.mark(r["id"], delay, force)

    def busy(self):
        return self.current is not None or bool(self.due)

    def run(self):
        while True:
            with self.cv:
                while True:
                    now = time.time()
                    ready = [(at, tid) for tid, (at, _) in self.due.items() if at <= now]
                    if ready:
                        tid = min(ready)[1]
                        force = self.due.pop(tid)[1]
                        break
                    nxt = min((at for at, _ in self.due.values()), default=None)
                    self.cv.wait(None if nxt is None else max(0.05, nxt - now))
                self.current = tid
            try:
                reconcile(tid, force)
            except tc.TCError as e:
                log.error("Tonie %s: %s", tid, e)
                set_status(tid, "error", str(e))
                self.mark(tid, 60)  # TeddyCloud evtl. kurz weg -> später erneut
                set_status(tid, "error", str(e) + " Neuer Versuch in 1 Minute.")
            except BuildError as e:
                log.error("Tonie %s: %s", tid, e)
                set_status(tid, "error", str(e))
            except Exception as e:
                log.error("Tonie %s: unerwarteter Fehler\n%s", tid, traceback.format_exc())
                set_status(tid, "error", f"Bauen fehlgeschlagen: {e}")
            finally:
                self.current = None


worker = Worker()
