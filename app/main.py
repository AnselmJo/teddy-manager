import hashlib
import hmac
import json
import logging
import logging.handlers
import mimetypes
import os
import random
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time

import httpx
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import boxlog, boxplan, builder, config, db, media, podcasts, tc, toniesjson, youtube
from .builder import worker

VERSION = open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")).read().strip()
TESTED_TC = "v0.7.0"
STATIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
HEX = re.compile(r"#[0-9a-fA-F]{6}")

log = logging.getLogger("app")


def setup_logging():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(),
              logging.handlers.RotatingFileHandler(config.LOG_PATH, maxBytes=2_000_000, backupCount=3)):
        h.setFormatter(fmt)
        root.addHandler(h)
    logging.getLogger("httpx").setLevel(logging.WARNING)


app = FastAPI(title="Teddy Manager", docs_url=None, redoc_url=None)


# ---------------------------------------------------------------- Hilfen

def img_url(image_id):
    if not image_id:
        return None
    r = db.q1("SELECT file FROM images WHERE id=? AND deleted_at IS NULL", (image_id,))
    return f"/img/{r['file']}" if r else None


def valid_color(c):
    return c in config.COLORS or bool(HEX.fullmatch(c or ""))


def media_out(m):
    on = db.q("""SELECT DISTINCT t.id, t.name, t.color FROM playlist p JOIN tonies t ON t.id=p.tonie_id
                 WHERE p.media_id=? AND t.deleted_at IS NULL ORDER BY t.name""", (m["id"],))
    used = len(on)
    chapters = json.loads(m["chapters"] or "[]")
    units = builder.units_for([m])
    return {"id": m["id"], "kind": m["kind"], "title": m["title"], "artist": m["artist"],
            "duration": m["duration"], "net_duration": sum(u["duration"] for u in units),
            "cover": img_url(m["cover_id"]), "cover_id": m["cover_id"], "used": used,
            "album": m["album"], "album_pos": m["album_pos"], "chapters": len(chapters),
            "clip": m["clip_start"] is not None, "origin": m["origin"],
            "cuts": json.loads(m["cuts"] or "[]"), "has_auto_cuts": bool(json.loads(m["auto_cuts"] or "[]")),
            "video_id": m["video_id"], "alt_video_id": m["alt_video_id"], "version": m["version"],
            "source_url": m["source_url"], "source_chapters": len(json.loads(m["source_chapters"] or "[]")),
            "is_new": bool(m["is_new"]), "clip_start": m["clip_start"],
            "tonies": [{"id": x["id"], "name": x["name"], "hex": config.color_hex(x["color"])} for x in on],
            "audio": f"/api/media/{m['id']}/audio", "original": f"/api/media/{m['id']}/original",
            "created": m["created"]}


def station_out(s):
    return {"id": s["id"], "name": s["name"], "url": s["url"], "image": img_url(s["image_id"]), "image_id": s["image_id"]}


def tonie_out(t, detail=False):
    d = builder.desired(t)
    tracks, units = d["tracks"], d.get("units", [])
    own = img_url(t["image_id"])
    out = {
        "id": t["id"], "uid": t["uid"], "name": t["name"], "color": t["color"],
        "hex": config.color_hex(t["color"]), "image": own or f"/img/{builder.tonie_pic(t)}", "own_image": bool(own),
        "mode": t["mode"], "status": t["status"], "status_msg": t["status_msg"],
        "hint": bool(t["hint_until"] and t["hint_until"] > time.time() and t["status"] == "ok"),
        "count": len(tracks), "chapters": len(units), "duration": sum(u["duration"] for u in units),
        "station": station_out(d["station"]) if d["station"] else None, "loudnorm": bool(t["loudnorm"]),
        "archived": bool(t["archived"]),
        "draft": bool(t["hold"] and d["kind"] == "playlist" and t["built_key"] != d["key"]),
        "ruid": tc.uid_to_ruid(t["uid"]),
        "box_state": boxlog.box_state(t),
        "last_seen": (db.q1("SELECT MAX(ts) ts FROM tag_events WHERE ruid=?", (tc.uid_to_ruid(t["uid"]),)) or {}).get("ts"),
        "playable": bool(t["built_source"]) if t["mode"] == "playlist" else bool(d["station"]),
        "sleep": {"on": bool(t["sleep_mode"]), "minutes": t["sleep_minutes"], "end_pct": t["sleep_end_pct"],
                  "stop": bool(t["sleep_stop"]), "repeat": bool(t["sleep_repeat"])},
        "podcast": (db.q1("SELECT id, title FROM podcasts WHERE tonie_id=? AND deleted_at IS NULL", (t["id"],)) or None),
    }
    if detail:
        out["tracks"] = [media_out(m) for m in tracks]
        out["covers"] = [{"id": m["cover_id"], "url": img_url(m["cover_id"])} for m in tracks if img_url(m["cover_id"])]
    return out


def get_tonie(tid):
    t = db.q1("SELECT * FROM tonies WHERE id=?", (tid,))
    if not t:
        raise HTTPException(404, "Tonie nicht gefunden.")
    return t


def need(cond, msg, code=400):
    if not cond:
        raise HTTPException(code, msg)


# ---------------------------------------------------------------- PIN

def _secret():
    s = db.get_setting("secret")
    if not s:
        s = secrets.token_hex(16)
        db.set_setting("secret", s)
    return s


def _pin_token():
    ph = db.get_setting("pin_hash")
    return hmac.new(_secret().encode(), ph.encode(), hashlib.sha256).hexdigest() if ph else None


@app.middleware("http")
async def pin_guard(request: Request, call_next):
    p = request.url.path
    if p.startswith("/api/") and p not in ("/api/health", "/api/auth", "/api/settings", "/api/import"):
        token = _pin_token()
        if token and not hmac.compare_digest(request.cookies.get("tm_auth", ""), token):
            return JSONResponse({"detail": "PIN"}, status_code=401)
    return await call_next(request)


def _auth_cookie(r):
    r.set_cookie("tm_auth", _pin_token(), max_age=365 * 86400, samesite="lax", httponly=True)


@app.post("/api/auth")
def auth(body: dict = Body(...)):
    ph = db.get_setting("pin_hash")
    pin = str(body.get("pin", ""))
    if ph and not hmac.compare_digest(hashlib.sha256((_secret() + pin).encode()).hexdigest(), ph):
        raise HTTPException(403, "PIN falsch.")
    r = JSONResponse({"ok": True})
    if ph:
        _auth_cookie(r)
    return r


def tc_version():
    try:
        with httpx.Client(base_url=config.TC_URL, timeout=5) as c:
            return c.get("/api/settings/get/internal.version.id").text.strip()[:40]
    except httpx.HTTPError:
        return None


@app.get("/api/settings")
def settings_get():
    ver = tc_version()
    usage = 0
    for root, _, files in os.walk(config.TM_DIR):
        usage += sum(os.path.getsize(os.path.join(root, f)) for f in files)
    free = shutil.disk_usage(config.LIB_DIR).free
    return {"pin_set": bool(db.get_setting("pin_hash")), "term": config.TERM, "term_plural": config.TERM_PLURAL,
            "version": VERSION, "teddycloud": ver is not None, "tc_version": ver, "tc_tested": TESTED_TC,
            "busy": worker.busy(), "lang": db.get_setting("lang", "de"), "usage": usage, "free": free,
            "kids": db.get_setting("kids") == "1", "boxlog": boxlog.status()}


@app.post("/api/settings/kids")
def settings_kids(body: dict = Body(...)):
    db.set_setting("kids", "1" if body.get("on") else "0")
    return {"ok": True}


_update_cache = {"ts": 0, "data": None}


@app.get("/api/update-check")
def update_check():
    """Neue Version auf GitHub? (nur wenn UPDATE_REPO gesetzt ist, z. B. „user/teddy-manager“; 6 h zwischengespeichert)"""
    repo = os.environ.get("UPDATE_REPO", "")
    if not repo:
        return {"enabled": False, "current": VERSION}
    if time.time() - _update_cache["ts"] > 6 * 3600:
        try:
            r = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=10,
                          headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            j = r.json()
            _update_cache.update(ts=time.time(), data={"latest": j.get("tag_name", "").lstrip("v"), "url": j.get("html_url")})
        except Exception as e:
            log.info("Update-Prüfung: %s", e)
            _update_cache.update(ts=time.time() - 5 * 3600, data=None)
    d = _update_cache["data"] or {}
    newer = bool(d.get("latest")) and tuple(int(x) for x in re.findall(r"\d+", d["latest"])[:3]) > \
        tuple(int(x) for x in VERSION.split("."))
    return {"enabled": True, "current": VERSION, "latest": d.get("latest"), "url": d.get("url"), "newer": newer}


@app.post("/api/settings/lang")
def settings_lang(body: dict = Body(...)):
    lang = body.get("lang")
    need(lang in ("de", "en"), "lang")
    db.set_setting("lang", lang)
    return {"ok": True}


@app.post("/api/settings/pin")
def settings_pin(body: dict = Body(...)):
    pin = str(body.get("pin") or "")
    if not pin:
        db.set_setting("pin_hash", None)
        return {"ok": True}
    need(re.fullmatch(r"\d{4}", pin), "PIN: 4 Ziffern")
    db.set_setting("pin_hash", hashlib.sha256((_secret() + pin).encode()).hexdigest())
    r = JSONResponse({"ok": True})
    _auth_cookie(r)
    return r


@app.get("/api/backup")
def backup_download():
    path = db.backup()
    return FileResponse(path, filename=f"teddy-manager-{time.strftime('%Y-%m-%d')}.sqlite",
                        media_type="application/octet-stream")


@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION}


@app.post("/api/sync")
def sync_all():
    """Stellt den Sollzustand für alle Tonies wieder her (Quellen, Anzeige, fehlende TAFs)."""
    worker.mark_all(0, force=True)
    return {"ok": True}


# ---------------------------------------------------------------- Tags / Anlernen

def classify_tags():
    ours = {r["uid"]: r for r in db.q("SELECT id, uid, deleted_at FROM tonies")}
    hidden = {r["uid"] for r in db.q("SELECT uid FROM hidden_tags")}
    out = []
    for tag in tc.tag_index():
        uid = (tag.get("uid") or "").replace(":", "").upper()
        if not uid.startswith("E0") or len(uid) != 16:
            continue
        info = tag.get("tonieInfo") or {}
        model = info.get("model") or ""
        if uid in ours and not ours[uid]["deleted_at"]:
            kind = "custom"
        else:
            kind = toniesjson.category(model) or "unbekannt"
        out.append({"uid": uid, "ruid": tag.get("ruid"), "kind": kind, "model": model,
                    "title": " – ".join(x for x in dict.fromkeys([info.get("series"), info.get("episode")]) if x),
                    "picture": info.get("picture") if (info.get("picture") or "").startswith("http") else None,
                    "has_content": bool(tag.get("source")), "archived": uid in hidden,
                    "playable": bool(tag.get("valid") and tag.get("exists"))})
    return out


def describe_event(ev):
    uid = tc.ruid_to_uid(ev["ruid"])
    t = db.q1("SELECT * FROM tonies WHERE uid=? AND deleted_at IS NULL", (uid,))
    out = {"ruid": ev["ruid"], "uid": uid, "ts": ev["ts"], "kind": ev["kind"]}
    if t:
        own = img_url(t["image_id"])
        out.update(type="custom", tonie_id=t["id"], name=t["name"], hex=config.color_hex(t["color"]),
                   image=own or f"/img/{builder.tonie_pic(t)}")
        return out
    try:
        info = tc.tag_info(ev["ruid"])
    except tc.TCError:
        info = {}
    ti = info.get("tonieInfo") or {}
    out.update(type=toniesjson.category(ti.get("model")) or "unbekannt",
               name=" – ".join(x for x in dict.fromkeys([ti.get("series"), ti.get("episode")]) if x) or "…" + uid[-4:],
               image=ti.get("picture") if (ti.get("picture") or "").startswith("http") else None,
               playable=bool(info.get("valid")))
    return out


@app.get("/api/events/latest")
def events_latest():
    """Zuletzt auf eine Box gelegte Figur (aus dem TeddyCloud-Log)."""
    ev = db.q1("SELECT * FROM tag_events ORDER BY ts DESC LIMIT 1")
    return {**boxlog.status(), "event": describe_event(ev) if ev else None}


@app.get("/api/events")
def events_list(limit: int = 40):
    return {"events": [describe_event(e) for e in db.q("SELECT * FROM tag_events ORDER BY ts DESC LIMIT ?", (min(limit, 200),))]}


@app.get("/api/tags")
def tags():
    try:
        return {"tags": classify_tags()}
    except tc.TCError as e:
        raise HTTPException(502, str(e))


_learn = {}


@app.post("/api/learn/start")
def learn_start():
    try:
        snapshot = {t["uid"] for t in classify_tags()}
    except tc.TCError as e:
        raise HTTPException(502, str(e))
    token = secrets.token_hex(8)
    for k in [k for k, v in _learn.items() if v[1] < time.time() - 3600]:
        _learn.pop(k)
    _learn[token] = (snapshot, time.time())
    return {"token": token}


@app.get("/api/learn/poll")
def learn_poll(token: str):
    need(token in _learn, "Abgelaufen.", 404)
    snapshot = _learn[token][0]
    try:
        tags_now = classify_tags()
        new = [t for t in tags_now if t["uid"] not in snapshot and t["kind"] != "custom"]
        if not new:   # schon bekannte, aber nicht eingerichtete Figur gerade aufgelegt? (Log)
            since = _learn[token][1]
            placed = {tc.ruid_to_uid(e["ruid"]) for e in db.q("SELECT ruid FROM tag_events WHERE ts>?", (since,))}
            new = [t for t in tags_now if t["uid"] in placed and t["kind"] != "custom"]
        if new:   # neu aufgelegte Figur ist offensichtlich nicht (mehr) archiviert
            with db.tx() as c:
                c.executemany("DELETE FROM hidden_tags WHERE uid=?", [(t["uid"],) for t in new])
    except tc.TCError as e:
        raise HTTPException(502, str(e))
    return {"new": new}


# ---------------------------------------------------------------- Kinderansicht

@app.get("/api/kids")
def kids_tiles():
    """Große Kacheln zum Abspielen am Handy: Custom-Tonies und Originale, deren Inhalt auf dem Server liegt."""
    tiles = []
    for t in db.q("SELECT * FROM tonies WHERE deleted_at IS NULL AND archived=0 ORDER BY created"):
        o = tonie_out(t)
        if o["playable"]:
            tiles.append({"ruid": o["ruid"], "name": o["name"], "hex": o["hex"], "image": o["image"],
                          "radio": o["station"]["url"] if o["mode"] == "radio" and o["station"] else None})
    try:
        for x in classify_tags():
            if x["kind"] in ("original", "kreativ") and x["playable"] and not x["archived"]:
                tiles.append({"ruid": x["ruid"], "name": x["title"], "hex": "#5b6170", "image": x["picture"], "radio": None})
    except tc.TCError:
        pass
    return {"tiles": tiles}


# ---------------------------------------------------------------- Tonies

@app.get("/api/tonies")
def tonies_list():
    rows = db.q("SELECT * FROM tonies WHERE deleted_at IS NULL ORDER BY created")
    return {"tonies": [tonie_out(t) for t in rows], "busy": worker.busy()}


@app.post("/api/tonies")
def tonie_create(body: dict = Body(...)):
    uid = str(body.get("uid", "")).replace(":", "").upper()
    need(re.fullmatch(r"[0-9A-F]{16}", uid), "UID?")
    name = str(body.get("name") or "").strip()[:60] or "Tonie"
    color = str(body.get("color") or "blau")
    need(valid_color(color), "Farbe?")
    existing = db.q1("SELECT * FROM tonies WHERE uid=?", (uid,))
    with db.tx() as c:
        if existing:
            need(existing["deleted_at"], "Schon angelegt.", 409)
            c.execute("UPDATE tonies SET deleted_at=NULL, name=?, color=?, applied_key=NULL WHERE id=?",
                      (name, color, existing["id"]))
            tid = existing["id"]
        else:
            tid = c.execute("INSERT INTO tonies(uid,name,color,created) VALUES(?,?,?,?)",
                            (uid, name, color, time.time())).lastrowid
    worker.mark(tid, 0)
    return tonie_out(get_tonie(tid), True)


@app.get("/api/tonies/{tid}")
def tonie_get(tid: int):
    return tonie_out(get_tonie(tid), True)


@app.patch("/api/tonies/{tid}")
def tonie_patch(tid: int, body: dict = Body(...)):
    get_tonie(tid)
    fields = {}
    if "name" in body:
        fields["name"] = str(body["name"]).strip()[:60] or "Tonie"
    if "color" in body:
        need(valid_color(body["color"]), "Farbe?")
        fields["color"] = body["color"].lower() if body["color"].startswith("#") else body["color"]
    if "image_id" in body:
        need(body["image_id"] is None or img_url(body["image_id"]), "Bild?")
        fields["image_id"] = body["image_id"]
    if "mode" in body:
        need(body["mode"] in ("playlist", "radio"), "mode?")
        fields["mode"] = body["mode"]
    if "station_id" in body:
        fields["station_id"] = body["station_id"]
    if "loudnorm" in body:
        fields["loudnorm"] = 1 if body["loudnorm"] else 0
    if "sleep" in body:      # Einschlafmodus
        sl = body["sleep"]
        if "on" in sl:
            fields["sleep_mode"] = 1 if sl["on"] else 0
        if "minutes" in sl:
            need(5 <= int(sl["minutes"]) <= 180, "5–180 min")
            fields["sleep_minutes"] = int(sl["minutes"])
        if "end_pct" in sl:
            need(0 <= int(sl["end_pct"]) <= 100, "0–100 %")
            fields["sleep_end_pct"] = int(sl["end_pct"])
        if "stop" in sl:
            fields["sleep_stop"] = 1 if sl["stop"] else 0
        if "repeat" in sl:
            fields["sleep_repeat"] = 1 if sl["repeat"] else 0
    if any(k in fields for k in ("loudnorm", "sleep_mode", "sleep_minutes", "sleep_end_pct", "sleep_stop", "sleep_repeat")) \
            or fields.get("mode") == "playlist":
        fields["hold"] = 1          # Entwurf – gebaut wird erst mit „Auf Tonie laden“
    if fields.get("mode") == "radio" or "station_id" in fields:
        fields["hold"] = 0          # Radio gilt sofort
    if "archived" in body:   # nur Anzeige – der Tonie bleibt in TeddyCloud eingerichtet
        with db.tx() as c:
            c.execute("UPDATE tonies SET archived=? WHERE id=?", (1 if body["archived"] else 0, tid))
    if fields:
        with db.tx() as c:
            c.execute(f"UPDATE tonies SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), tid))
        worker.mark(tid)
    return tonie_out(get_tonie(tid), True)


def _set_playlist(c, tid, media_ids):
    c.execute("DELETE FROM playlist WHERE tonie_id=?", (tid,))
    c.executemany("INSERT INTO playlist(tonie_id,pos,media_id) VALUES(?,?,?)",
                  [(tid, i, m) for i, m in enumerate(media_ids)])


@app.put("/api/tonies/{tid}/playlist")
def tonie_playlist(tid: int, body: dict = Body(...)):
    get_tonie(tid)
    ids = [int(x) for x in body.get("media_ids", [])]
    known = {r["id"]: r for r in db.q("SELECT * FROM media WHERE deleted_at IS NULL")}
    need(all(i in known for i in ids), "Titel?")
    units = builder.units_for([known[i] for i in ids])
    need(len(units) <= config.MAX_TRACKS, f"Max. {config.MAX_TRACKS} Kapitel ({len(units)}).")
    with db.tx() as c:
        _set_playlist(c, tid, ids)
        c.execute("UPDATE tonies SET mode='playlist', hold=1 WHERE id=?", (tid,))
        c.executemany("UPDATE media SET is_new=0 WHERE id=?", [(i,) for i in ids])
    worker.mark(tid)
    return tonie_out(get_tonie(tid), True)


@app.post("/api/tonies/{tid}/append")
def tonie_append(tid: int, body: dict = Body(...)):
    """Titel hinten anhängen (z. B. „Auf Tonie legen“ aus dem Bereich „Neu“)."""
    ids = [r["media_id"] for r in db.q("SELECT media_id FROM playlist WHERE tonie_id=? ORDER BY pos", (tid,))]
    return tonie_playlist(tid, {"media_ids": ids + [int(i) for i in body.get("media_ids", [])]})


# ---------------------------------------------------------------- Archiv (Anzeige)

@app.post("/api/tags/{uid}/archive")
def tag_archive(uid: str):
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO hidden_tags(uid, created) VALUES(?,?)", (uid.upper(), time.time()))
    return {"ok": True}


@app.delete("/api/tags/{uid}/archive")
def tag_unarchive(uid: str):
    with db.tx() as c:
        c.execute("DELETE FROM hidden_tags WHERE uid=?", (uid.upper(),))
    return {"ok": True}


# ---------------------------------------------------------------- Tonieboxen

@app.get("/api/boxes")
def boxes_list():
    try:
        out = []
        for b in tc.boxes():
            p = boxplan.plan(b["ID"])
            item = {"id": b["ID"], "name": db.get_setting(f"box_name_{b['ID']}") or b.get("boxName") or b["ID"]}
            item.update(boxplan.current_values(b["ID"]))
            if p.get("applied") == "evening" and p.get("day"):   # Tageswerte anzeigen, nicht die gerade aktiven Abendwerte
                item.update(p["day"])
            item["evening"] = p["evening"]
            item["evening_now"] = p.get("applied") == "evening"
            out.append(item)
        return {"boxes": out}
    except tc.TCError as e:
        raise HTTPException(502, str(e))


@app.patch("/api/boxes/{box_id}")
def box_patch(box_id: str, body: dict = Body(...)):
    need(re.fullmatch(r"[0-9A-Fa-f]{12}", box_id), "Box?")
    if "name" in body:
        db.set_setting(f"box_name_{box_id}", str(body["name"]).strip()[:40] or None)
    p = boxplan.plan(box_id)
    day = {}
    for k in boxplan.KEYS:
        if k in body:
            v = body[k]
            need(isinstance(v, bool) or (str(v).isdigit() and int(v) <= 3), "Wert?")
            day[k] = v
    try:
        if day:
            p.setdefault("day", {}).update({k: v for k, v in day.items() if k in boxplan.EVENING_KEYS})
            if p.get("applied") == "evening":   # abends: nur merken; nicht abendliche Werte (Klopfen) sofort setzen
                boxplan.apply(box_id, {k: v for k, v in day.items() if k not in boxplan.EVENING_KEYS})
            else:
                boxplan.apply(box_id, day)
        if "evening" in body:
            ev = body["evening"]
            for k in ("start", "end"):
                if k in ev:
                    need(re.fullmatch(r"\d{2}:\d{2}", str(ev[k])), "Zeit?")
                    p["evening"][k] = ev[k]
            for k in ("vol_spk", "vol_hdp", "led"):
                if k in ev:
                    need(str(ev[k]).isdigit() and int(ev[k]) <= 3, "Wert?")
                    p["evening"][k] = int(ev[k])
            if "on" in ev:
                p["evening"]["on"] = bool(ev["on"])
            if p.get("applied") == "evening":   # geänderte Abendwerte gleich übernehmen
                p["applied"] = None
        boxplan.save_plan(box_id, p)
        if "evening" in body:
            threading.Thread(target=boxplan.tick, daemon=True).start()
    except tc.TCError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.post("/api/tonies/{tid}/shuffle")
def tonie_shuffle(tid: int):
    get_tonie(tid)
    ids = [r["media_id"] for r in db.q("SELECT media_id FROM playlist WHERE tonie_id=? ORDER BY pos", (tid,))]
    if len(set(ids)) > 1:
        orig = list(ids)
        while ids == orig:
            random.shuffle(ids)
        with db.tx() as c:
            _set_playlist(c, tid, ids)
            c.execute("UPDATE tonies SET hold=1 WHERE id=?", (tid,))
        worker.mark(tid, 1)
    return tonie_out(get_tonie(tid), True)


def _content(tid):
    t = get_tonie(tid)
    return t["mode"], t["station_id"], t["loudnorm"], \
        [r["media_id"] for r in db.q("SELECT media_id FROM playlist WHERE tonie_id=? ORDER BY pos", (tid,))]


def _put_content(c, tid, content):
    mode, station, loud, ids = content
    c.execute("UPDATE tonies SET mode=?, station_id=?, loudnorm=?, hold=? WHERE id=?",
              (mode, station, loud, 1 if mode == "playlist" else 0, tid))
    _set_playlist(c, tid, ids)


@app.post("/api/tonies/{tid}/swap")
def tonie_swap(tid: int, body: dict = Body(...)):
    other = int(body.get("other_id"))
    need(other != tid, "?")
    a, b = _content(tid), _content(other)
    with db.tx() as c:
        _put_content(c, tid, b)
        _put_content(c, other, a)
    worker.mark(tid, 1)
    worker.mark(other, 1)
    return tonie_out(get_tonie(tid), True)


@app.post("/api/tonies/{tid}/copy")
def tonie_copy(tid: int, body: dict = Body(...)):
    target = int(body.get("target_id"))
    need(target != tid, "?")
    get_tonie(target)
    with db.tx() as c:
        _put_content(c, target, _content(tid))
    worker.mark(target, 1)
    return {"ok": True}


@app.post("/api/tonies/{tid}/rebuild")
def tonie_rebuild(tid: int):
    get_tonie(tid)
    with db.tx() as c:
        c.execute("UPDATE tonies SET built_key=NULL, applied_key=NULL, hold=0 WHERE id=?", (tid,))
    worker.mark(tid, 0)
    return tonie_out(get_tonie(tid), True)


@app.post("/api/tonies/{tid}/publish")
def tonie_publish(tid: int):
    """Entwurf fertig: jetzt bauen und auf den Tonie laden."""
    get_tonie(tid)
    with db.tx() as c:
        c.execute("UPDATE tonies SET hold=0 WHERE id=?", (tid,))
    worker.mark(tid, 0)
    return tonie_out(get_tonie(tid), True)


@app.delete("/api/tonies/{tid}")
def tonie_delete(tid: int):
    get_tonie(tid)
    with db.tx() as c:
        c.execute("UPDATE tonies SET deleted_at=? WHERE id=?", (time.time(), tid))
    worker.mark(tid, 10)  # kurze Gnadenfrist für „Rückgängig“
    return {"ok": True}


@app.post("/api/tonies/{tid}/restore")
def tonie_restore(tid: int):
    get_tonie(tid)
    with db.tx() as c:
        c.execute("UPDATE tonies SET deleted_at=NULL, applied_key=NULL WHERE id=?", (tid,))
    worker.mark(tid, 0)
    return tonie_out(get_tonie(tid), True)


# ---------------------------------------------------------------- Medien

def _insert_media(c, **f):
    f.setdefault("created", time.time())
    cols = ",".join(f)
    return c.execute(f"INSERT INTO media({cols}) VALUES({','.join('?' * len(f))})", tuple(f.values())).lastrowid


def _ingest(tmp_path, orig_name, kind, sha, album, album_pos):
    """Datei aus TMP übernehmen. -> (status, media_row, meldung)"""
    dup = db.q1("SELECT * FROM media WHERE sha256=?", (sha,))
    if dup:
        os.remove(tmp_path)
        if dup["deleted_at"]:
            with db.tx() as c:
                c.execute("UPDATE media SET deleted_at=NULL WHERE id=?", (dup["id"],))
            return "neu", db.q1("SELECT * FROM media WHERE id=?", (dup["id"],)), ""
        return "doppelt", dup, ""
    try:
        meta = media.read_metadata(tmp_path, orig_name)
    except Exception as e:
        os.remove(tmp_path)
        log.warning("Upload %s abgelehnt: %s", orig_name, e)
        return "fehler", None, str(e) if isinstance(e, ValueError) else "Datei nicht lesbar."
    meta["title"] = youtube.clean_title(meta["title"])   # gleiche Titelregeln wie beim Link-Import
    ext = os.path.splitext(orig_name)[1].lower() or ".audio"
    if media.is_taf(tmp_path):
        ext = ".taf"
    if not album and kind == "geschichte" and meta["album"]:
        album, album_pos = meta["album"], meta["track"]   # mehrteilige Geschichte über das Album-Tag
    folder = config.KINDS[kind][2]
    slug = media.slugify(f"{meta['artist']}-{meta['title']}" if meta["artist"] else meta["title"])
    dst = media.unique_path(os.path.join(config.MEDIA_DIR, folder), slug, ext)
    shutil.move(tmp_path, dst)
    cover_id = None
    if meta["cover"]:
        try:
            cover_id = media.store_image(meta["cover"], "cover", meta["title"])
        except Exception as e:
            log.warning("Cover von %s nicht verwendbar: %s", orig_name, e)
    with db.tx() as c:
        mid = _insert_media(c, kind=kind, title=meta["title"][:200], artist=meta["artist"][:200],
                            duration=meta["duration"], path=os.path.relpath(dst, config.LIB_DIR), orig_name=orig_name,
                            sha256=sha, cover_id=cover_id, album=(album or "")[:200], album_pos=album_pos or 0,
                            chapters=json.dumps(meta["chapters"]) if meta["chapters"] else "", origin="upload")
    log.info("Neu in Bibliothek: %s (%s)", meta["title"], os.path.relpath(dst, config.LIB_DIR))
    return "neu", db.q1("SELECT * FROM media WHERE id=?", (mid,)), ""


async def _save_upload(f: UploadFile):
    os.makedirs(config.TMP_DIR, exist_ok=True)
    fd, path = tempfile.mkstemp(dir=config.TMP_DIR, suffix=".upload")
    h = hashlib.sha256()
    with os.fdopen(fd, "wb") as out:
        while chunk := await f.read(1 << 20):
            h.update(chunk)
            out.write(chunk)
    return path, h.hexdigest()


async def _handle_uploads(files, kind, album="", album_pos=0):
    results = []
    for i, f in enumerate(files):
        name = os.path.basename(f.filename or "upload")
        if os.path.splitext(name)[1].lower() not in config.AUDIO_EXT and not (f.content_type or "").startswith("audio"):
            results.append({"name": name, "status": "fehler", "message": "Format?"})
            continue
        path, sha = await _save_upload(f)
        status, row, msg = await run_in_threadpool(_ingest, path, name, kind, sha, album, album_pos + i)
        results.append({"name": name, "status": status, "message": msg, "media": media_out(row) if row else None})
    return results


@app.get("/api/media")
def media_list():
    rows = db.q("SELECT * FROM media WHERE deleted_at IS NULL ORDER BY created DESC")
    return {"media": [media_out(m) for m in rows], "kinds": {k: v[:2] for k, v in config.KINDS.items()}}


@app.post("/api/media")
async def media_upload(files: list[UploadFile] = File(...), kind: str = Form("lied"),
                       album: str = Form(""), album_pos: int = Form(0)):
    need(kind in config.KINDS, "kind?")
    return {"results": await _handle_uploads(files, kind, album.strip(), album_pos)}


@app.post("/share")
async def share_target(request: Request):
    """Android-Share-Target der PWA: geteilte Dateien landen als Lieder in der Bibliothek."""
    form = await request.form()
    files = [v for k, v in form.multi_items() if hasattr(v, "filename") and v.filename]
    res = await _handle_uploads(files, "lied")
    ok = sum(1 for r in res if r["status"] in ("neu", "doppelt"))
    return RedirectResponse(f"/#bibliothek?geteilt={ok}&fehler={len(res) - ok}", status_code=303)


def affected_tonies(media_ids):
    if not media_ids:
        return []
    marks = ",".join("?" * len(media_ids))
    return [r["tonie_id"] for r in db.q(f"SELECT DISTINCT tonie_id FROM playlist WHERE media_id IN ({marks})",
                                        tuple(media_ids))]


@app.patch("/api/media/{mid}")
def media_patch(mid: int, body: dict = Body(...)):
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    fields = {}
    if "title" in body:
        fields["title"] = str(body["title"]).strip()[:200] or m["title"]
    if "artist" in body:
        fields["artist"] = str(body["artist"]).strip()[:200]
    if "album" in body:
        fields["album"] = str(body["album"]).strip()[:200]
    if "album_pos" in body:
        fields["album_pos"] = int(body["album_pos"])
    if "kind" in body and body["kind"] != m["kind"]:
        need(body["kind"] in config.KINDS, "kind?")
        fields["kind"] = body["kind"]
    if "kind" in fields and config.media_owned(m["path"]):  # eigene Datei in den passenden Ordner verschieben
        src = config.media_abs(m["path"])
        stem, ext = os.path.splitext(os.path.basename(src))
        dst = media.unique_path(os.path.join(config.MEDIA_DIR, config.KINDS[fields["kind"]][2]), stem, ext)
        os.rename(src, dst)
        fields["path"] = os.path.relpath(dst, config.LIB_DIR)
    if "cover_id" in body:
        need(body["cover_id"] is None or img_url(body["cover_id"]), "Bild?")
        fields["cover_id"] = body["cover_id"]
    if "is_new" in body:
        fields["is_new"] = 1 if body["is_new"] else 0
    if "cuts" in body:   # Schnittbereiche [[start, ende, herkunft]] – Original bleibt unverändert
        length = m["clip_end"] if m["clip_end"] is not None else m["duration"]
        cuts = []
        for c in body["cuts"]:
            a, b = max(0.0, float(c[0])), min(float(length or 1e9), float(c[1]))
            if b - a >= 0.05:
                cuts.append([round(a, 2), round(b, 2), str(c[2] if len(c) > 2 else "manual")[:40]])
        fields["cuts"] = json.dumps(sorted(cuts))
    if fields:
        with db.tx() as c:
            c.execute(f"UPDATE media SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), mid))
        if "cuts" in fields:
            warm_preview(mid)
            for tid in affected_tonies([mid]):
                worker.mark(tid)
        if "title" in fields:  # Trackliste in TeddyCloud aktualisieren
            for tid in affected_tonies([mid]):
                worker.mark(tid)
    return media_out(db.q1("SELECT * FROM media WHERE id=?", (mid,)))


@app.post("/api/media/delete")
def media_delete_many(body: dict = Body(...)):
    """Mehrere Titel (z. B. alle Teile einer Geschichte) in den Papierkorb."""
    ids = [int(i) for i in body.get("ids", [])]
    with db.tx() as c:
        c.executemany("UPDATE media SET deleted_at=? WHERE id=?", [(time.time(), i) for i in ids])
    for tid in affected_tonies(ids):
        worker.mark(tid, 10)
    return {"ok": True}


@app.post("/api/media/restore")
def media_restore_many(body: dict = Body(...)):
    ids = [int(i) for i in body.get("ids", [])]
    with db.tx() as c:
        c.executemany("UPDATE media SET deleted_at=NULL WHERE id=?", [(i,) for i in ids])
    for tid in affected_tonies(ids):
        worker.mark(tid, 1)
    return {"ok": True}


@app.get("/api/media/{mid}")
def media_get(mid: int):
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    return media_out(m)


@app.post("/api/media/{mid}/cuts/reset")
def media_cuts_reset(mid: int):
    """Manuelle Schnitte verwerfen, automatische Vorschläge wiederherstellen."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    with db.tx() as c:
        c.execute("UPDATE media SET cuts=auto_cuts WHERE id=?", (mid,))
    warm_preview(mid)
    for tid in affected_tonies([mid]):
        worker.mark(tid)
    return media_out(db.q1("SELECT * FROM media WHERE id=?", (mid,)))


@app.post("/api/media/{mid}/sponsorblock")
def media_sponsorblock(mid: int):
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m and m["video_id"], "Kein YouTube-Titel.")
    n = youtube.refetch_sponsorblock(mid)
    for tid in affected_tonies([mid]):
        worker.mark(tid)
    return {"segments": n, "media": media_out(db.q1("SELECT * FROM media WHERE id=?", (mid,)))}


@app.post("/api/media/{mid}/split")
def media_split(mid: int):
    """Video mit Kapiteln in einzelne Titel aufteilen (verweisen alle auf dasselbe Original)."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    chapters = json.loads(m["source_chapters"] or "[]")
    need(len(chapters) > 1, "Keine Kapitel.")
    created = []
    with db.tx() as c:
        for i, ch in enumerate(chapters):
            key = f"{m['sha256']}#k{i}"
            if db.q1("SELECT id FROM media WHERE sha256=? AND deleted_at IS NULL", (key,)):
                continue
            c.execute("DELETE FROM media WHERE sha256=?", (key,))
            created.append(_insert_media(
                c, kind=m["kind"], title=(ch["title"] or f"{m['title']} {i + 1}")[:200], artist=m["artist"],
                duration=ch["end"] - ch["start"], path=m["path"], orig_name=m["orig_name"], sha256=key,
                cover_id=m["cover_id"], album=m["title"][:200], album_pos=i, clip_start=ch["start"], clip_end=ch["end"],
                origin=m["origin"], cuts=m["cuts"], auto_cuts=m["auto_cuts"], video_id=m["video_id"],
                source_url=m["source_url"], version=m["version"], is_new=1))
        c.execute("UPDATE media SET deleted_at=? WHERE id=?", (time.time(), mid))   # Ganzes ausblenden (Rückgängig)
    return {"created": len(created)}


@app.post("/api/media/{mid}/version")
def media_version(mid: int):
    """Musikvideo <-> Song-Version wechseln (lädt die andere Version)."""
    need(youtube.enabled(), "Import ist ausgeschaltet.")
    need(youtube.switch_version(mid), "Keine andere Version bekannt.")
    return {"ok": True}


def warm_preview(mid):
    """Geschnittene Hörprobe im Hintergrund vorbereiten, damit „Abspielen“ sofort startet."""
    def run():
        try:
            m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
            unit = builder._unit(m, m["clip_start"], m["clip_end"], "", m["clip_end"] if m["clip_end"] is not None else m["duration"])
            if unit["cuts"]:
                media.preview(m, m["clip_start"], m["clip_end"], unit["cuts"])
        except Exception as e:
            log.info("Hörprobe %s: %s", mid, e)
    threading.Thread(target=run, daemon=True).start()


@app.get("/api/media/{mid}/audio")
def media_audio(mid: int):
    """Hörprobe so, wie sie auf den Tonie kommt: mit Schnitten (zwischengespeichert, seekbar)."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    start = m["clip_start"]
    end = m["clip_end"]
    unit = builder._unit(m, start, end, "", end if end is not None else m["duration"])
    if not unit["cuts"]:
        return media_original(mid)
    try:
        path = media.preview(m, start, end, unit["cuts"])
    except Exception as e:
        log.warning("Hörprobe %s nicht erzeugt: %s", mid, e)
        return media_original(mid)
    return FileResponse(path, media_type="audio/ogg")


@app.get("/api/media/{mid}/original")
def media_original(mid: int):
    """Ungeschnittene Fassung (für den Trimmer)."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m, "?", 404)
    path = config.media_abs(m["path"])
    if m["clip_start"] is not None:   # Ausschnitt: per ffmpeg ohne Neukodierung herausschneiden
        args, stdin = media.open_input(path)
        p = subprocess.Popen(["ffmpeg", "-hide_banner", "-v", "error", *args, "-ss", f"{m['clip_start']:.2f}",
                              "-to", f"{m['clip_end']:.2f}", "-vn", "-c:a", "copy", "-f", "ogg", "pipe:1"],
                             stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        def body():
            try:
                while chunk := p.stdout.read(1 << 16):
                    yield chunk
            finally:
                p.kill()
                if stdin:
                    stdin.close()
        return StreamingResponse(body(), media_type="audio/ogg")
    if media.is_taf(path):
        def body():
            with open(path, "rb") as f:
                f.seek(config.TAF_HEADER)
                while chunk := f.read(1 << 16):
                    yield chunk
        return StreamingResponse(body(), media_type="audio/ogg",
                                 headers={"Content-Length": str(os.path.getsize(path) - config.TAF_HEADER)})
    mime = {".opus": "audio/ogg", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".m4a": "audio/mp4",
            ".m4b": "audio/mp4", ".webm": "audio/webm"}.get(os.path.splitext(path)[1].lower()) or mimetypes.guess_type(path)[0]
    return FileResponse(path, media_type=mime or "application/octet-stream")


# ---------------------------------------------------------------- Import per Link (YouTube)

@app.post("/api/import")
async def import_link(request: Request):
    """Für „HTTP Shortcuts“: Body = geteilter Text (oder JSON {"text": …}), Header X-Teddy-Token (alt: X-Tonie-Token).
    Antwortet immer mit einer kurzen Klartextzeile (wird am Handy als Toast angezeigt)."""
    given = request.headers.get("x-teddy-token") or request.headers.get("x-tonie-token") or ""   # alter Name bleibt gültig
    if not hmac.compare_digest(given, youtube.token()):
        return PlainTextResponse("Fehler: Token ungültig – Shortcut neu einrichten", status_code=200)
    raw = (await request.body()).decode("utf-8", "replace")
    text = raw
    if raw.lstrip().startswith("{"):
        try:
            text = str(json.loads(raw).get("text", ""))
        except ValueError:
            pass
    code, msg = await run_in_threadpool(youtube.enqueue, text)
    return PlainTextResponse(msg if code == 200 else "Fehler: " + msg, status_code=200)


@app.post("/api/import/web")
def import_web(body: dict = Body(...)):
    """Link aus der Oberfläche (eingefügt) – gleiche Logik, ohne Token (PIN-geschützt)."""
    code, msg = youtube.enqueue(str(body.get("text", "")))
    need(code == 200, msg, code)
    return {"message": msg}


@app.get("/api/yt/search")
def yt_search(q: str, kind: str = "songs"):
    """YouTube-Music-Suche in der App (Songs, Alben, Videos)."""
    need(youtube.enabled() and youtube.env_ready(), "Import ist ausgeschaltet.")
    need(kind in ("songs", "albums", "videos") and q.strip(), "?")
    try:
        return {"results": youtube.helper("search", q.strip()[:120], kind, timeout=40)}
    except Exception as e:
        raise HTTPException(502, f"Suche nicht möglich: {str(e)[:150]}")


@app.get("/api/yt/album/{browse_id}")
def yt_album(browse_id: str):
    need(youtube.enabled() and re.fullmatch(r"[A-Za-z0-9_-]{5,60}", browse_id), "?")
    try:
        return youtube.helper("album_tracks", browse_id, timeout=40)
    except Exception as e:
        raise HTTPException(502, f"Album nicht ladbar: {str(e)[:150]}")


async def proxy_audio(url, request, media_type=None):
    """Audio durchreichen – mit Range-Anfragen, damit der Mini-Player spulen kann."""
    headers = {"Range": request.headers["range"]} if "range" in request.headers else {}
    client = httpx.AsyncClient(timeout=30, follow_redirects=True)
    upstream = await client.send(client.build_request("GET", url, headers=headers), stream=True)
    if upstream.status_code >= 400:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(502, f"Abspielen nicht möglich ({upstream.status_code})")
    out = {k: upstream.headers[k] for k in ("content-length", "content-range", "accept-ranges") if k in upstream.headers}

    async def body():
        try:
            async for chunk in upstream.aiter_bytes(1 << 16):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()
    return StreamingResponse(body(), status_code=upstream.status_code, headers=out,
                             media_type=media_type or upstream.headers.get("content-type", "application/octet-stream"))


@app.get("/api/tags/{ruid}/play")
async def tag_play(ruid: str, request: Request):
    """Inhalt einer Figur am Handy abspielen (so, wie TeddyCloud ihn der Box liefert)."""
    need(re.fullmatch(r"[0-9a-f]{16}", ruid), "?")
    info = await run_in_threadpool(tc.tag_info, ruid)
    need(info.get("valid") and info.get("audioUrl"), "Kein Inhalt auf dem Server.", 404)
    return await proxy_audio(config.TC_URL + info["audioUrl"], request, "audio/ogg")


@app.get("/api/tags/{ruid}/chapters")
def tag_chapters(ruid: str):
    need(re.fullmatch(r"[0-9a-f]{16}", ruid), "?")
    info = tc.tag_info(ruid)
    ti = info.get("tonieInfo") or {}
    names = ti.get("tracks") or []
    secs = info.get("trackSeconds") or []
    title = " – ".join(x for x in dict.fromkeys([ti.get("series"), ti.get("episode")]) if x)
    return {"title": title, "playable": bool(info.get("valid")),
            "chapters": [{"title": names[i] if i < len(names) else f"{i + 1}", "start": s} for i, s in enumerate(secs)]}


@app.get("/api/yt/preview/{video_id}")
async def yt_preview(video_id: str, request: Request):
    """Vorhören ohne Download: leitet die Audiospur durch (mit Range, also spulbar)."""
    need(youtube.enabled() and youtube.VID.match(video_id), "?")
    try:
        url = await run_in_threadpool(youtube.preview_url, video_id)
    except Exception as e:
        raise HTTPException(502, str(e)[:150])
    try:
        return await proxy_audio(url, request, "audio/webm")
    except HTTPException:
        youtube._preview_urls.pop(video_id, None)
        raise


@app.post("/api/yt/import")
def yt_import(body: dict = Body(...)):
    """Treffer aus der Suche laden: Song/Video oder ganzes Album (als Geschichte oder als Lieder)."""
    if body.get("browseId"):
        info = youtube.helper("album_tracks", str(body["browseId"]), timeout=40)
        need(info.get("playlistId"), "Album ohne Titel.")
        code, msg = youtube.enqueue(f"https://music.youtube.com/playlist?list={info['playlistId']}",
                                    auto={"as_story": bool(body.get("as_story")), "kind": "lied"})
    else:
        need(youtube.VID.match(str(body.get("videoId", ""))), "?")
        code, msg = youtube.enqueue(f"https://music.youtube.com/watch?v={body['videoId']}")
    need(code == 200, msg, code)
    return {"message": msg}


@app.get("/api/import/jobs")
def import_jobs():
    return {"jobs": youtube.jobs(), "enabled": youtube.enabled(), "ready": youtube.env_ready()}


@app.post("/api/import/jobs/{jid}/confirm")
def import_confirm(jid: int, body: dict = Body(default={})):
    kind = body.get("kind", "lied")
    need(kind in config.KINDS, "kind?")
    return {"queued": youtube.confirm_playlist(jid, body.get("limit"), kind=kind, as_story=bool(body.get("as_story")))}


@app.post("/api/import/jobs/{jid}/retry")
def import_retry(jid: int):
    with db.tx() as c:
        c.execute("UPDATE import_jobs SET status='queued', next_at=0, attempts=0, error='', step='' WHERE id=?", (jid,))
    youtube._wake.set()
    return {"ok": True}


@app.delete("/api/import/jobs/{jid}")
def import_cancel(jid: int):
    with db.tx() as c:
        c.execute("UPDATE import_jobs SET status='cancelled' WHERE id=? AND status<>'running'", (jid,))
    return {"ok": True}


IMPORT_KEYS = ("yt_sb_categories", "yt_prefer_song", "yt_max_len", "yt_playlist_max", "yt_title_rules", "yt_test_video")


@app.get("/api/import/settings")
def import_settings():
    out = {k: youtube.setting(k) for k in IMPORT_KEYS}
    out["yt_sb_categories"] = json.loads(out["yt_sb_categories"] or "[]")
    return out | {"enabled": youtube.enabled(), "token": youtube.token(), "status": youtube.status(),
                  "ready": youtube.env_ready(), "cookies": os.path.exists(youtube.COOKIES),
                  "sb_all": youtube.SB_CATEGORIES, "previous": os.path.lexists(youtube.PREVIOUS)}


@app.post("/api/import/settings")
def import_settings_set(body: dict = Body(...)):
    if "enabled" in body:
        if body["enabled"]:
            need(body.get("accepted"), "Bitte den Hinweis bestätigen.")
            db.set_setting("yt_enabled", "1")
            if not youtube.env_ready():
                threading.Thread(target=youtube.update, kwargs={"reason": "Einrichtung"}, daemon=True).start()
        else:
            db.set_setting("yt_enabled", "0")
    for k in IMPORT_KEYS:
        if k in body:
            v = body[k]
            if k == "yt_sb_categories":
                v = json.dumps([c for c in v if c in youtube.SB_CATEGORIES])
            elif k in ("yt_max_len", "yt_playlist_max"):
                need(str(v).isdigit() and int(v) > 0, "Zahl?")
            elif k == "yt_prefer_song":
                v = "1" if v in (True, "1", 1) else "0"
            elif k == "yt_test_video":
                need(youtube.VID.match(str(v)), "Video-ID?")
            db.set_setting(k, str(v))
    youtube._wake.set()
    return import_settings()


@app.post("/api/import/token")
def import_token():
    return {"token": youtube.new_token()}


@app.post("/api/import/cookies")
async def import_cookies(file: UploadFile = File(...)):
    raw = await file.read()
    need(len(raw) < 2_000_000 and b"youtube.com" in raw, "Keine YouTube-cookies.txt.")
    os.makedirs(config.YT_DIR, exist_ok=True)
    fd = os.open(youtube.COOKIES, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    return {"ok": True}


@app.delete("/api/import/cookies")
def import_cookies_delete():
    if os.path.exists(youtube.COOKIES):
        os.remove(youtube.COOKIES)
    return {"ok": True}


@app.post("/api/import/update")
def import_update(body: dict = Body(default={})):
    """yt-dlp jetzt aktualisieren. Optional "spec" (Paketliste) – z. B. zum Testen des Rückfalls."""
    spec = body.get("spec")
    need(spec is None or (isinstance(spec, list) and all(isinstance(x, str) for x in spec)), "spec?")
    threading.Thread(target=youtube.update, kwargs={"spec": spec, "reason": "manuell"}, daemon=True).start()
    return {"ok": True}


@app.post("/api/import/rollback")
def import_rollback():
    need(youtube.rollback(), "Keine vorherige Version vorhanden.")
    return {"ok": True}


@app.get("/api/import/shortcut.json")
def import_shortcut(request: Request):
    """Fertige Konfiguration für die Android-App „HTTP Shortcuts“ (Import aus Datei oder URL)."""
    base = config.PUBLIC_URL or f"http://{request.url.hostname}:8090"
    return JSONResponse(youtube.shortcut_config(base),
                        headers={"Content-Disposition": 'attachment; filename="zum-tonie.json"'})


# ---------------------------------------------------------------- Tonie-Inhalte übernehmen

_src_cache = {}


def _tag_titles():
    """lib-Pfad -> tonieInfo der Tags, die darauf zeigen (Titel für Inhalte, die tonies.json nicht kennt)."""
    try:
        return {t["source"][6:]: t.get("tonieInfo") or {} for t in tc.tag_index() if (t.get("source") or "").startswith("lib://")}
    except tc.TCError:
        return {}


def _source_info(rel, tag_info=None):
    p = os.path.join(config.LIB_DIR, rel)
    st = os.stat(p)
    hit = _src_cache.get(rel)
    if hit and hit[0] == st.st_mtime:
        return hit[1]
    ti = media.taf_info(p)
    item = toniesjson.by_audio(ti["audio_id"]) or {}
    if not item and tag_info and tag_info.get("series"):
        item = {"series": tag_info.get("series"), "episodes": tag_info.get("episode") or tag_info.get("series"),
                "tracks": tag_info.get("tracks") or [], "pic": tag_info.get("picture")}
    names = item.get("tracks") or []
    chapters = [{"title": names[i] if i < len(names) else "", "start": s, "end": e}
                for i, (s, e) in enumerate(ti["chapters"])]
    info = {"path": rel, "audio_id": ti["audio_id"], "duration": ti["duration"], "chapters": chapters,
            "title": item.get("episodes") or item.get("title") or os.path.splitext(os.path.basename(rel))[0],
            "series": item.get("series") or "", "pic": item.get("pic") or None,
            "origin": "tonie" if rel.startswith("by/") else "library", "sha256": media.sha256_file(p)}
    _src_cache[rel] = (st.st_mtime, info)
    return info


@app.get("/api/sources/available")
def sources_available():
    """Gibt es TAFs, die noch nicht in der Bibliothek sind? (für den Knopf „Aus Tonies“)"""
    used = {m["path"] for m in db.q("SELECT path FROM media WHERE deleted_at IS NULL")}
    for root, dirs, files in os.walk(config.LIB_DIR):
        rel_root = os.path.relpath(root, config.LIB_DIR)
        if rel_root.split(os.sep)[0] == config.TM_SUB:
            dirs[:] = []
            continue
        for fn in files:
            if fn.lower().endswith(".taf") and os.path.normpath(os.path.join(rel_root, fn)) not in used:
                return {"available": True}
    return {"available": False}


@app.get("/api/sources")
def sources():
    """TAFs in der TeddyCloud-Library, die (noch) nicht in der Bibliothek sind – vor allem von der Box
    zwischengespeicherte Inhalte eigener Original-Tonies (library/by/…)."""
    known = {m["sha256"] for m in db.q("SELECT sha256 FROM media WHERE deleted_at IS NULL")}
    used_paths = {m["path"] for m in db.q("SELECT path FROM media WHERE deleted_at IS NULL")}
    titles = _tag_titles()
    out = []
    for root, dirs, files in os.walk(config.LIB_DIR):
        rel_root = os.path.relpath(root, config.LIB_DIR)
        if rel_root.split(os.sep)[0] == config.TM_SUB:
            dirs[:] = []
            continue
        for fn in sorted(files):
            rel = os.path.normpath(os.path.join(rel_root, fn))
            if not fn.lower().endswith(".taf"):
                continue
            try:
                info = _source_info(rel, titles.get(rel))
            except Exception as e:
                log.warning("TAF %s nicht lesbar: %s", rel, e)
                continue
            done = info["sha256"] in known
            done_ch = [i for i in range(len(info["chapters"])) if f"{info['sha256']}#{i}" in known]
            if info["origin"] == "library" and (done or rel in used_paths):
                continue
            out.append({k: v for k, v in info.items() if k != "sha256"} | {"imported": done, "imported_chapters": done_ch})
    out.sort(key=lambda x: (x["origin"] != "tonie", x["series"], x["title"]))
    return {"sources": out}


def _cover_from(url, label):
    if not url or not toniesjson.known_pic(url):
        return None
    try:
        r = httpx.get(url, timeout=15, follow_redirects=True)
        r.raise_for_status()
        return media.store_image(r.content, "teddycloud", label[:120])
    except Exception as e:
        log.info("Cover %s nicht geladen (offline?): %s", url, e)
        return None


@app.post("/api/sources/import")
def sources_import(body: dict = Body(...)):
    rel = os.path.normpath(str(body.get("path", "")))
    need(not rel.startswith("..") and rel.lower().endswith(".taf") and os.path.exists(os.path.join(config.LIB_DIR, rel)),
         "Datei?")
    kind = body.get("kind", "geschichte")
    need(kind in config.KINDS, "kind?")
    info = _source_info(rel, _tag_titles().get(rel))
    cover = _cover_from(info["pic"], info["title"])
    name = info["title"]
    created = []
    with db.tx() as c:
        if body.get("mode") == "whole":
            if not db.q1("SELECT id FROM media WHERE sha256=? AND deleted_at IS NULL", (info["sha256"],)):
                c.execute("DELETE FROM media WHERE sha256=?", (info["sha256"],))
                created.append(_insert_media(
                    c, kind=kind, title=name[:200], artist=info["series"][:200], duration=info["duration"], path=rel,
                    orig_name=os.path.basename(rel), sha256=info["sha256"], cover_id=cover, origin=info["origin"],
                    chapters=json.dumps(info["chapters"]) if len(info["chapters"]) > 1 else ""))
        else:
            for i in sorted({int(i) for i in body.get("chapters", [])}):
                need(0 <= i < len(info["chapters"]), "Kapitel?")
                key = f"{info['sha256']}#{i}"
                if db.q1("SELECT id FROM media WHERE sha256=? AND deleted_at IS NULL", (key,)):
                    continue
                c.execute("DELETE FROM media WHERE sha256=?", (key,))
                ch = info["chapters"][i]
                created.append(_insert_media(
                    c, kind=kind, title=(ch["title"] or f"{name} {i + 1}")[:200], artist=info["series"][:200],
                    duration=ch["end"] - ch["start"], path=rel, orig_name=os.path.basename(rel), sha256=key,
                    cover_id=cover, album=name[:200], album_pos=i, clip_start=ch["start"], clip_end=ch["end"],
                    origin=info["origin"]))
    log.info("Aus %s übernommen: %d Einträge", rel, len(created))
    return {"created": len(created)}


# ---------------------------------------------------------------- Podcasts

def podcast_out(p, episodes=False):
    t = db.q1("SELECT id, name FROM tonies WHERE id=? AND deleted_at IS NULL", (p["tonie_id"],)) if p["tonie_id"] else None
    n = db.q1("SELECT COUNT(*) n FROM media WHERE podcast_id=? AND deleted_at IS NULL", (p["id"],))["n"]
    out = {"id": p["id"], "title": p["title"], "author": p["author"], "feed": p["feed_url"], "image": img_url(p["image_id"]),
           "tonie": t, "keep": p["keep"], "newest_first": bool(p["newest_first"]), "status": p["status"], "error": p["error"],
           "last_check": p["last_check"], "count": n}
    if episodes:
        out["episodes"] = [media_out(m) for m in db.q("""SELECT * FROM media WHERE podcast_id=? AND deleted_at IS NULL
                                                         ORDER BY published DESC""", (p["id"],))]
    return out


@app.get("/api/podcasts")
def podcasts_list():
    return {"podcasts": [podcast_out(p) for p in db.q("SELECT * FROM podcasts WHERE deleted_at IS NULL ORDER BY title")]}


@app.get("/api/podcasts/search")
def podcasts_search(q: str):
    try:
        return {"results": podcasts.search(q)}
    except Exception as e:
        raise HTTPException(502, f"Suche nicht möglich (Internet?): {e}")


@app.post("/api/podcasts")
def podcast_add(body: dict = Body(...)):
    feed = str(body.get("feed", "")).strip()
    need(re.match(r"https?://\S+$", feed), "Feed-Adresse?")
    tid = body.get("tonie_id")
    need(tid is None or db.q1("SELECT id FROM tonies WHERE id=?", (tid,)), "Tonie?")
    try:
        pid = podcasts.subscribe(feed, tid, int(body.get("keep") or 10), bool(body.get("newest_first", True)))
    except Exception as e:
        raise HTTPException(502, f"Feed nicht lesbar: {e}")
    return podcast_out(db.q1("SELECT * FROM podcasts WHERE id=?", (pid,)))


@app.get("/api/podcasts/{pid}")
def podcast_get(pid: int):
    p = db.q1("SELECT * FROM podcasts WHERE id=?", (pid,))
    need(p, "?", 404)
    return podcast_out(p, True)


@app.patch("/api/podcasts/{pid}")
def podcast_patch(pid: int, body: dict = Body(...)):
    fields = {}
    if "tonie_id" in body:
        need(body["tonie_id"] is None or db.q1("SELECT id FROM tonies WHERE id=?", (body["tonie_id"],)), "Tonie?")
        fields["tonie_id"] = body["tonie_id"]
    if "keep" in body:
        need(1 <= int(body["keep"]) <= 50, "1–50")
        fields["keep"] = int(body["keep"])
    if "newest_first" in body:
        fields["newest_first"] = 1 if body["newest_first"] else 0
    if fields:
        with db.tx() as c:
            c.execute(f"UPDATE podcasts SET {', '.join(k + '=?' for k in fields)} WHERE id=?", (*fields.values(), pid))
        podcasts.trigger(pid)
    return podcast_out(db.q1("SELECT * FROM podcasts WHERE id=?", (pid,)))


@app.post("/api/podcasts/{pid}/sync")
def podcast_sync(pid: int):
    podcasts.trigger(pid)
    return {"ok": True}


@app.delete("/api/podcasts/{pid}")
def podcast_delete(pid: int):
    """Abo beenden. Folgen bleiben in der Bibliothek (löschbar), der Tonie behält seine Playlist."""
    with db.tx() as c:
        c.execute("UPDATE podcasts SET deleted_at=?, tonie_id=NULL WHERE id=?", (time.time(), pid))
    return {"ok": True}


@app.post("/api/media/{mid}/use-chapters")
def media_use_chapters(mid: int):
    """Kapitel der Quelle (z. B. YouTube-Video) als Kapitel auf der Box nutzen – ohne Aufteilen."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    need(m and len(json.loads(m["source_chapters"] or "[]")) > 1, "Keine Kapitel.")
    with db.tx() as c:
        c.execute("UPDATE media SET chapters=source_chapters, kind='geschichte' WHERE id=?", (mid,))
    for tid in affected_tonies([mid]):
        worker.mark(tid)
    return media_out(db.q1("SELECT * FROM media WHERE id=?", (mid,)))


# ---------------------------------------------------------------- Radio

@app.get("/api/stations")
def stations_list():
    return {"stations": [station_out(s) for s in db.q("SELECT * FROM stations WHERE deleted_at IS NULL ORDER BY name")]}


def _station_fields(body):
    fields = {}
    if "name" in body:
        fields["name"] = str(body["name"]).strip()[:80]
        need(fields["name"], "Name?")
    if "url" in body:
        url = str(body["url"]).strip()
        need(re.match(r"https?://\S+$", url), "URL: http(s)://…")
        fields["url"] = url
    if "image_id" in body:
        fields["image_id"] = body["image_id"]
    return fields


def tonies_with_station(sid):
    return [r["id"] for r in db.q("SELECT id FROM tonies WHERE station_id=? AND mode='radio'", (sid,))]


@app.post("/api/stations")
def station_create(body: dict = Body(...)):
    f = _station_fields(body)
    need("name" in f and "url" in f, "Name/URL?")
    with db.tx() as c:
        sid = c.execute("INSERT INTO stations(name,url,image_id,created) VALUES(?,?,?,?)",
                        (f["name"], f["url"], f.get("image_id"), time.time())).lastrowid
    return station_out(db.q1("SELECT * FROM stations WHERE id=?", (sid,)))


@app.patch("/api/stations/{sid}")
def station_patch(sid: int, body: dict = Body(...)):
    f = _station_fields(body)
    if f:
        with db.tx() as c:
            c.execute(f"UPDATE stations SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), sid))
        for tid in tonies_with_station(sid):
            worker.mark(tid)
    return station_out(db.q1("SELECT * FROM stations WHERE id=?", (sid,)))


@app.delete("/api/stations/{sid}")
def station_delete(sid: int):
    with db.tx() as c:
        c.execute("UPDATE stations SET deleted_at=? WHERE id=?", (time.time(), sid))
    for tid in tonies_with_station(sid):
        worker.mark(tid, 10)
    return {"ok": True}


@app.post("/api/stations/{sid}/restore")
def station_restore(sid: int):
    with db.tx() as c:
        c.execute("UPDATE stations SET deleted_at=NULL WHERE id=?", (sid,))
    for tid in tonies_with_station(sid):
        worker.mark(tid, 1)
    return {"ok": True}


@app.post("/api/stations/check")
def station_check(body: dict = Body(...)):
    ok, msg = media.check_stream(str(body.get("url", "")).strip())
    return {"ok": ok, "message": msg}


# ---------------------------------------------------------------- Bilder

@app.get("/api/images")
def images_list():
    rows = db.q("SELECT * FROM images WHERE deleted_at IS NULL ORDER BY created DESC")
    return {"images": [{"id": r["id"], "url": f"/img/{r['file']}", "source": r["source"], "label": r["label"]}
                       for r in rows]}


@app.post("/api/images")
async def image_upload(file: UploadFile = File(...), source: str = Form("upload")):
    raw = await file.read()
    need(len(raw) < 25_000_000, "Bild zu groß.")
    try:
        iid = await run_in_threadpool(media.store_image, raw, "logo" if source == "logo" else "upload", "")
    except Exception as e:
        log.warning("Bild-Upload fehlgeschlagen: %s", e)
        raise HTTPException(400, "Bild nicht lesbar.")
    return {"id": iid, "url": img_url(iid)}


def _image_users(iid):
    return [r["id"] for r in db.q("SELECT id FROM tonies WHERE image_id=?", (iid,))]


@app.delete("/api/images/{iid}")
def image_delete(iid: int):
    with db.tx() as c:
        c.execute("UPDATE images SET deleted_at=? WHERE id=?", (time.time(), iid))
    for tid in _image_users(iid):   # Tonie zeigt jetzt die Münze -> TeddyCloud-Bild aktualisieren
        worker.mark(tid, 10)
    return {"ok": True}


@app.post("/api/images/{iid}/restore")
def image_restore(iid: int):
    with db.tx() as c:
        c.execute("UPDATE images SET deleted_at=NULL WHERE id=?", (iid,))
    for tid in _image_users(iid):
        worker.mark(tid, 1)
    return {"ok": True}


@app.get("/api/teddyimages")
def teddy_images(q: str = ""):
    return {"results": toniesjson.search(q)}


@app.post("/api/images/import")
def image_import(body: dict = Body(...)):
    url = str(body.get("url", ""))
    need(toniesjson.known_pic(url), "Bild?")
    iid = _cover_from(url, str(body.get("title", "")))
    need(iid, "Bild nicht geladen (Internet?).", 502)
    return {"id": iid, "url": img_url(iid)}


# ---------------------------------------------------------------- Hintergrundaufgaben

def purge():
    cutoff = time.time() - config.PURGE_AFTER_S
    for m in db.q("SELECT * FROM media WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)):
        p = config.media_abs(m["path"])
        still_used = db.q1("SELECT id FROM media WHERE path=? AND id<>? AND deleted_at IS NULL", (m["path"], m["id"]))
        if config.media_owned(m["path"]) and not still_used and os.path.exists(p):
            os.remove(p)
        with db.tx() as c:
            c.execute("DELETE FROM media WHERE id=?", (m["id"],))
        log.info("Endgültig gelöscht: %s", m["title"])
    for t in db.q("SELECT * FROM tonies WHERE deleted_at IS NOT NULL AND deleted_at < ? AND applied_key='deleted'",
                  (cutoff,)):
        with db.tx() as c:
            c.execute("DELETE FROM tonies WHERE id=?", (t["id"],))
        builder.remove_old_build(t["built_source"], None)
    for i in db.q("SELECT * FROM images WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)):
        with db.tx() as c:
            c.execute("DELETE FROM images WHERE id=?", (i["id"],))
        p = os.path.join(config.IMG_DIR, i["file"])
        if os.path.exists(p):
            os.remove(p)
    with db.tx() as c:
        c.execute("DELETE FROM stations WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,))
        c.execute("DELETE FROM import_jobs WHERE status IN ('done','cancelled','error') AND updated < ?",
                  (time.time() - 30 * 86400,))
    # Kapitel-Cache: unbenutzte Dateien nach 30 Tagen entfernen (werden bei Bedarf neu erzeugt)
    for d in (config.TMP_DIR, config.UNITS_DIR, os.path.join(config.TM_DIR, "cache", "preview")):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            p = os.path.join(d, name)
            if os.path.getatime(p) < time.time() - (86400 if d == config.TMP_DIR else 30 * 86400):
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)


def housekeeping():
    last_day = None
    while True:
        try:
            day = time.strftime("%Y-%m-%d")
            if day != last_day:
                log.info("Sicherung: %s", db.backup())
                purge()
                last_day = day
            worker.mark_all(0)  # Abgleich prüfen (z. B. nach TeddyCloud-Neustart oder -Update)
        except Exception:
            log.exception("Hintergrundaufgabe fehlgeschlagen")
        time.sleep(3600)


@app.on_event("startup")
def startup():
    setup_logging()
    for d in (config.MEDIA_DIR, config.BUILD_DIR, config.UNITS_DIR, config.TMP_DIR, config.IMG_DIR, config.YT_DIR):
        os.makedirs(d, exist_ok=True)
    old_norm = os.path.join(config.TM_DIR, "cache", "norm")   # Cache von v1.0
    if os.path.isdir(old_norm):
        shutil.rmtree(old_norm, ignore_errors=True)
    db.init()
    worker.start()
    youtube.start()
    podcasts.start()
    boxlog.start()
    boxplan.start()
    threading.Thread(target=housekeeping, daemon=True, name="housekeeping").start()
    log.info("Teddy Manager %s gestartet", VERSION)


# ---------------------------------------------------------------- Frontend

os.makedirs(config.IMG_DIR, exist_ok=True)
app.mount("/img", StaticFiles(directory=config.IMG_DIR), name="img")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(os.path.join(STATIC, "manifest.webmanifest"), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(os.path.join(STATIC, "sw.js"), media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})
