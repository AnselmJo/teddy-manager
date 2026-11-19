"""Import per Link (YouTube / YouTube Music) – optionales Modul, standardmäßig aus.

Ablauf: Link erkennen -> Job in SQLite (übersteht Neustarts) -> ein Worker lädt mit yt-dlp die beste
Audiospur ohne Neukodierung -> automatische Aufbereitung (SponsorBlock, Stille, Lautheit, Metadaten, Cover)
als *Schnittbereiche* (nicht-destruktiv; angewendet erst beim TAF-Build).

yt-dlp, yt-dlp-ejs (passende Version per Extra) und Deno liegen zusammen in einer venv unter data/ytdlp/envs/.
Täglich wird eine neue Umgebung daneben gebaut und per Selbsttest geprüft; nur bei Erfolg wird umgeschaltet.
"""
import json
import logging
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

import httpx

from . import config, db, media

log = logging.getLogger("youtube")

HELPER = os.path.join(os.path.dirname(__file__), "yt_helper.py")
ENVS = os.path.join(config.YT_DIR, "envs")
CURRENT = os.path.join(config.YT_DIR, "current")
PREVIOUS = os.path.join(config.YT_DIR, "previous")
COOKIES = os.path.join(config.YT_DIR, "cookies.txt")
SELFTEST_LOG = os.path.join(config.YT_DIR, "selftest.log")
PIP_SPEC = ["yt-dlp[default,deno]", "ytmusicapi"]

SB_CATEGORIES = ["sponsor", "selfpromo", "interaction", "intro", "outro", "preview", "music_offtopic", "filler"]
DEFAULTS = {
    "yt_enabled": "0",
    "yt_sb_categories": json.dumps(["music_offtopic", "intro", "outro", "sponsor", "selfpromo", "interaction", "preview"]),
    "yt_prefer_song": "1",
    "yt_max_len": str(3 * 3600),
    "yt_playlist_max": "50",
    "yt_test_video": "jNQXAC9IVRw",   # „Me at the zoo“, 19 s, seit 2005 online
    "yt_title_rules": "\n".join([
        r"\s*[\(\[]\s*(official\s*)?(music\s*)?(video|audio|lyrics?(\s*video)?|visuali[sz]er|clip)\s*[\)\]]",
        r"\s*[\(\[]\s*offizielle[sr]?\s*(musik)?(video|clip)\s*[\)\]]",
        r"\s*[\(\[]\s*(hd|hq|4k|1080p|720p|remastered)\s*[\)\]]",
        r"\s*[\(\[][^\)\]]*(lyrics?|mit text|zum mitsingen|karaoke)[^\)\]]*[\)\]]",
        r"^[^\w\(\[]+",                      # Emojis/Zeichen am Anfang
        r"\s*\|.*$",
        r"\s+-\s+(kinderlieder|weihnachtslieder|lieder)\b.*$",   # „… - Kinderlieder zum Mitsingen“
    ]),
}
RETRY_DELAYS = [60, 300, 900]


def setting(key):
    return db.get_setting(key, DEFAULTS.get(key))


def enabled():
    return setting("yt_enabled") == "1"


def token():
    t = db.get_setting("yt_token")
    if not t:
        t = secrets.token_urlsafe(18)
        db.set_setting("yt_token", t)
    return t


def new_token():
    db.set_setting("yt_token", secrets.token_urlsafe(18))
    return token()


# ------------------------------------------------------------------ yt-dlp-Umgebung

_env_lock = threading.Lock()


def status():
    try:
        return json.loads(db.get_setting("yt_status") or "{}")
    except ValueError:
        return {}


def _set_status(**kw):
    s = status()
    s.update(kw)
    db.set_setting("yt_status", json.dumps(s))


def _bin(env, name):
    return os.path.join(env, "bin", name)


def _env_vars(env):
    e = dict(os.environ)
    e["PATH"] = os.path.join(env, "bin") + os.pathsep + e.get("PATH", "")
    e["HOME"] = config.YT_DIR                     # Caches von yt-dlp/deno landen hier
    e["XDG_CACHE_HOME"] = os.path.join(config.YT_DIR, "cache")
    e["DENO_DIR"] = os.path.join(config.YT_DIR, "cache", "deno")
    return e


def env_ready():
    return os.path.exists(_bin(CURRENT, "yt-dlp"))


def run(args, timeout=900, env=None):
    """yt-dlp aus der aktiven (oder angegebenen) Umgebung. -> CompletedProcess (Text)."""
    env = env or os.path.realpath(CURRENT)
    cmd = [_bin(env, "yt-dlp"), "--no-color", "--ignore-config"]
    if os.path.exists(COOKIES):
        cmd += ["--cookies", COOKIES]
    return subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout, env=_env_vars(env))


def helper(cmd, *args, timeout=90):
    env = os.path.realpath(CURRENT)
    p = subprocess.run([_bin(env, "python"), "-I", HELPER, cmd, *args], capture_output=True, text=True,
                       timeout=timeout, env=_env_vars(env))
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[-300:])
    return json.loads(p.stdout)


def _versions(env):
    def out(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=_env_vars(env)).stdout.strip()
        except Exception:
            return ""
    pip = out([_bin(env, "python"), "-m", "pip", "list", "--format=json"])
    try:
        pkgs = {p["name"].lower(): p["version"] for p in json.loads(pip)}
    except ValueError:
        pkgs = {}
    return {"ytdlp": pkgs.get("yt-dlp", ""), "ejs": pkgs.get("yt-dlp-ejs", ""), "deno": pkgs.get("deno", ""),
            "ytmusicapi": pkgs.get("ytmusicapi", "")}


def selftest(env):
    """Lädt das Testvideo (kurz) als Audio. -> (ok, meldung)"""
    vid = setting("yt_test_video")
    tmp = tempfile.mkdtemp(dir=config.TMP_DIR)
    try:
        p = run(["-f", "251/bestaudio/best", "--no-playlist", "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
                 f"https://www.youtube.com/watch?v={vid}"], timeout=300, env=env)
        files = os.listdir(tmp)
        ok = p.returncode == 0 and files and os.path.getsize(os.path.join(tmp, files[0])) > 10_000
        with open(SELFTEST_LOG, "w") as f:
            f.write(f"{time.strftime('%F %T')} env={env} rc={p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-6000:]}")
        if not ok:
            return False, explain(p.stderr)[0]
        try:   # ytmusicapi lädt?
            subprocess.run([_bin(env, "python"), "-I", "-c", "import ytmusicapi"], check=True, timeout=60,
                           capture_output=True, env=_env_vars(env))
        except Exception:
            return False, "ytmusicapi lässt sich nicht laden"
        return True, "OK"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def update(spec=None, reason="täglich"):
    """Neue Umgebung neben der alten bauen, testen, dann umschalten – sonst alte behalten."""
    if not _env_lock.acquire(blocking=False):
        return False
    try:
        os.makedirs(ENVS, exist_ok=True)
        os.makedirs(config.TMP_DIR, exist_ok=True)
        new = os.path.join(ENVS, time.strftime("%Y%m%d-%H%M%S"))
        _set_status(updating=True, message=f"Update läuft ({reason}) …")
        log.info("yt-dlp-Update (%s): baue %s", reason, new)
        try:
            subprocess.run([sys.executable, "-m", "venv", new], check=True, capture_output=True, timeout=300)
            p = subprocess.run([_bin(new, "python"), "-m", "pip", "install", "--no-cache-dir", "--upgrade",
                                *(spec or PIP_SPEC)], capture_output=True, text=True, timeout=1800)
            if p.returncode != 0:
                err = [ln for ln in p.stderr.splitlines() if ln.startswith("ERROR")]
                raise RuntimeError("Installation: " + (err[0] if err else p.stderr.strip()[-200:])[:250])
            ok, msg = selftest(new)
        except Exception as e:
            ok, msg = False, str(e)[:300]
        if not ok:
            shutil.rmtree(new, ignore_errors=True)
            active = env_ready()
            log.error("yt-dlp-Update verworfen: %s", msg)
            _set_status(updating=False, ok=active and status().get("ok", False), checked=time.time(),
                        message=("Update fehlgeschlagen – vorherige Version bleibt aktiv: " if active
                                 else "Einrichtung fehlgeschlagen: ") + msg)
            return False
        if os.path.islink(CURRENT):
            if os.path.lexists(PREVIOUS):
                os.remove(PREVIOUS)
            os.symlink(os.path.realpath(CURRENT), PREVIOUS)
        tmp_link = CURRENT + ".new"
        if os.path.lexists(tmp_link):
            os.remove(tmp_link)
        os.symlink(new, tmp_link)
        os.replace(tmp_link, CURRENT)
        keep = {os.path.realpath(CURRENT), os.path.realpath(PREVIOUS) if os.path.lexists(PREVIOUS) else ""}
        for d in os.listdir(ENVS):
            if os.path.join(ENVS, d) not in keep:
                shutil.rmtree(os.path.join(ENVS, d), ignore_errors=True)
        _set_status(updating=False, ok=True, checked=time.time(), selftest=time.time(),
                    message="Aktuell", **_versions(new))
        log.info("yt-dlp aktiv: %s", status())
        return True
    finally:
        _env_lock.release()


def rollback():
    """Auf die vorherige Umgebung zurück (manuell)."""
    if not os.path.lexists(PREVIOUS):
        return False
    prev = os.path.realpath(PREVIOUS)
    tmp_link = CURRENT + ".new"
    if os.path.lexists(tmp_link):
        os.remove(tmp_link)
    os.symlink(prev, tmp_link)
    os.replace(tmp_link, CURRENT)
    _set_status(ok=True, message="Auf vorherige Version zurückgesetzt", **_versions(prev))
    return True


# ------------------------------------------------------------------ Links

VID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_link(text):
    """Erste URL im geteilten Text -> {kind, ref, music, url} oder None."""
    m = re.search(r"https?://[^\s<>\"']+", text or "")
    if not m:
        return None
    url = m.group(0).rstrip(").,;!?»”\"'")
    u = urllib.parse.urlparse(url)
    host = u.netloc.lower().split(":")[0]
    for pre in ("www.", "m."):
        if host.startswith(pre):
            host = host[len(pre):]
    q = urllib.parse.parse_qs(u.query)
    music = host == "music.youtube.com"
    path = u.path.rstrip("/")
    vid = None
    if host == "youtu.be":
        vid = path.lstrip("/")[:11]
    elif host in ("youtube.com", "music.youtube.com", "youtube-nocookie.com"):
        if path == "/watch" and q.get("v"):
            vid = q["v"][0]
        elif re.match(r"^/(shorts|live|embed|v)/", path):
            vid = path.split("/")[2][:11]
        elif path == "/playlist" and q.get("list"):
            lid = q["list"][0]
            return {"kind": "playlist", "ref": lid, "music": music,
                    "url": f"https://{'music' if music else 'www'}.youtube.com/playlist?list={lid}"}
        elif path.startswith("/browse/MPRE"):
            bid = path.split("/")[2]
            return {"kind": "playlist", "ref": bid, "music": True, "url": f"https://music.youtube.com/browse/{bid}"}
    else:
        return None
    if not vid or not VID.match(vid):
        return None
    return {"kind": "video", "ref": vid, "music": music,
            "url": f"https://{'music' if music else 'www'}.youtube.com/watch?v={vid}"}


# ------------------------------------------------------------------ Fehler

def explain(stderr):
    """yt-dlp-Fehlertext -> (Meldung, erneut versuchen?, Update anstoßen?)"""
    s = (stderr or "").lower()
    if "confirm your age" in s or "age-restricted" in s or "inappropriate for some users" in s:
        return "Altersbeschränkt – Cookies nötig", False, False
    if "confirm you" in s and "bot" in s or "sign in to confirm" in s:
        return "YouTube verlangt eine Anmeldung (Bot-Schutz) – später erneut oder cookies.txt hinterlegen", True, False
    if "premieres in" in s or "will begin in" in s or "premiere" in s and "upcoming" in s:
        return "Premiere – noch nicht verfügbar", False, False
    if "is live" in s or "live event" in s or "livestream" in s:
        return "Livestream – nicht unterstützt", False, False
    if any(x in s for x in ("video unavailable", "private video", "has been removed", "not available in your country",
                            "this video is not available", "members-only", "join this channel")):
        return "Video nicht verfügbar", False, False
    if any(x in s for x in ("name resolution", "timed out", "network is unreachable", "connection reset",
                            "connection refused", "temporarily unavailable")):
        return "Keine Verbindung zu YouTube", True, False
    if any(x in s for x in ("signature", "nsig", "n challenge", "unable to extract", "requested format is not available",
                            "http error 403", "jsinterp", "player response", "ejs", "javascript runtime",
                            "precondition check failed", "http error 400")):
        return "YouTube hat etwas geändert – Update läuft", True, True
    return "Import fehlgeschlagen (Details im Log)", True, False


class ImportError_(Exception):
    def __init__(self, msg, retry=True, update=False):
        super().__init__(msg)
        self.retry, self.update = retry, update


# ------------------------------------------------------------------ Aufbereitung

def sponsorblock(video_id):
    cats = json.loads(setting("yt_sb_categories") or "[]")
    if not cats:
        return []
    try:
        r = httpx.get("https://sponsor.ajay.app/api/skipSegments",
                      params={"videoID": video_id, "categories": json.dumps(cats)}, timeout=15)
    except httpx.HTTPError as e:
        log.info("SponsorBlock nicht erreichbar: %s", e)
        return []
    if r.status_code == 404:
        return []
    if r.status_code != 200:
        return []
    return [[round(s["segment"][0], 2), round(s["segment"][1], 2), "sb:" + s.get("category", "")]
            for s in r.json() if s.get("actionType", "skip") == "skip" and s["segment"][1] > s["segment"][0]]


def silence_cuts(path, duration):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn",
                        "-af", "silencedetect=noise=-50dB:d=0.5", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=900)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", p.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", p.stderr)]
    cuts = []
    if starts and starts[0] <= 0.05 and ends:
        lead = max(0.0, ends[0] - 0.1)           # 0,1 s Luft vor dem Einsatz
        if lead > 0.3:
            cuts.append([0.0, round(lead, 2), "silence"])
    if starts and (len(starts) > len(ends) or (ends and ends[-1] >= duration - 0.1)):
        tail = starts[-1] + 0.2
        if duration - tail > 0.3 and tail > 1:
            cuts.append([round(tail, 2), round(duration, 2), "silence"])
    return cuts


def measure_loudness(path):
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-vn",
                        "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=1800)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    return json.loads(m.group(0)) if m else None


def clean_title(title):
    out = title
    for rule in (setting("yt_title_rules") or "").splitlines():
        rule = rule.strip()
        if not rule:
            continue
        try:
            out = re.sub(rule, "", out, flags=re.I)
        except re.error:
            log.warning("Ungültige Titelregel: %s", rule)
    return re.sub(r"\s{2,}", " ", out).strip(" -–|") or title


def clean_artist(name):
    return re.sub(r"\s*-\s*Topic$", "", (name or "").strip())


def clean_channel(name):
    """Kanalname -> Interpret: „Rolf Zuckowski - Musik für Dich“ -> „Rolf Zuckowski“, „…VEVO“ -> „…“."""
    name = clean_artist(name)
    name = re.sub(r"VEVO$", "", name).strip()
    return re.split(r"\s+[-–|]\s+", name)[0].strip() or name


def split_video_title(raw, uploader):
    """„Interpret - Titel“ / „Interpret | Titel“ -> (interpret, titel). Bei „|“ nur, wenn der linke Teil
    zum Kanal passt – sonst ist „| …“ meist Beiwerk („| Kinderlieder zum Mitsingen“)."""
    up = (uploader or "").lower()
    for sep in (" - ", " – ", " | "):
        if sep in raw:
            a, b = (x.strip() for x in raw.split(sep, 1))
            if GENERIC.search(b) and not (a.lower() in up or up.startswith(a.lower())):
                return "", a          # „Titel - Weihnachtslieder zum Mitsingen“: rechts nur Beiwerk
            if a and b and (a.lower() in up or up.startswith(a.lower()) or sep != " | ") and len(a) <= 60:
                return a, b
            break
    return "", ""


# Beiwerk in Videotiteln (rechts vom Trenner) – kein Liedtitel
GENERIC = re.compile(r"(lieder|mitsingen|karaoke|lyrics?|official|offiziell|video|compilation|nursery|"
                     r"kinder|songs? for|zum tanzen|playlist|mix\b)", re.I)


def _cover(url):
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return media.store_image(r.content, "cover", "")
    except Exception as e:
        log.info("Cover %s nicht geladen: %s", url, e)
        return None


def _video_thumb(info):
    thumbs = [t for t in info.get("thumbnails") or [] if t.get("url")]
    if not thumbs:
        return info.get("thumbnail")
    return max(thumbs, key=lambda t: (t.get("preference") or -99, t.get("width") or 0)).get("url")


def _info(video_id, music):
    p = run(["-J", "--no-playlist", f"https://{'music' if music else 'www'}.youtube.com/watch?v={video_id}"], timeout=300)
    if p.returncode != 0:
        raise ImportError_(*explain(p.stderr))
    return json.loads(p.stdout)


# ------------------------------------------------------------------ Queue

_wake = threading.Event()


def _job(jid):
    return db.q1("SELECT * FROM import_jobs WHERE id=?", (jid,))


def _upd(jid, **kw):
    kw["updated"] = time.time()
    with db.tx() as c:
        c.execute(f"UPDATE import_jobs SET {', '.join(k + '=?' for k in kw)} WHERE id=?", (*kw.values(), jid))


def find_media(video_id):
    return db.q1("""SELECT * FROM media WHERE deleted_at IS NULL AND clip_start IS NULL
                    AND (video_id=? OR alt_video_id=?)""", (video_id, video_id))


def enqueue(text, auto=None):
    """-> (http_status, kurze Klartextmeldung für den Toast). auto: Playlist ohne Rückfrage bestätigen,
    z. B. {"as_story": True} für ein Hörspiel-Album aus der Suche."""
    if not enabled():
        return 403, "Import ist ausgeschaltet (Teddy Manager: Einstellungen)"
    link = parse_link(text)
    if not link:
        return 400, "Kein YouTube-Link erkannt"
    if link["kind"] == "video":
        m = find_media(link["ref"])
        if m:
            return 200, f"Schon in der Bibliothek: {m['title']}"
    if db.q1("SELECT id FROM import_jobs WHERE ref=? AND status IN ('queued','running','confirm')", (link["ref"],)):
        return 200, "Import läuft bereits"
    now = time.time()
    with db.tx() as c:
        c.execute("""INSERT INTO import_jobs(kind,ref,url,music,status,payload,created,updated)
                     VALUES(?,?,?,?, 'queued', ?, ?, ?)""", (link["kind"], link["ref"], link["url"], int(link["music"]),
                                                     json.dumps({"auto": auto}) if auto else "", now, now))
    _wake.set()
    if not env_ready():
        threading.Thread(target=update, kwargs={"reason": "Einrichtung"}, daemon=True).start()
    return 200, "Playlist erkannt – bitte im Teddy Manager bestätigen" if link["kind"] == "playlist" else "Import gestartet"


def confirm_playlist(jid, limit=None, kind="lied", as_story=False):
    """Playlist/Album bestätigen. as_story: alle Titel als Teile EINER Geschichte (Gruppe = Playlist-Titel,
    Reihenfolge = Playlist-Reihenfolge) – passend für Hörspiele/Hörbücher aus YouTube Music."""
    j = _job(jid)
    if not j or j["status"] != "confirm":
        return 0
    pl = json.loads(j["payload"] or "{}")
    entries = pl.get("entries", [])
    limit = min(int(limit or setting("yt_playlist_max")), int(setting("yt_playlist_max")))
    n, now = 0, time.time()
    with db.tx() as c:
        for pos, e in enumerate(entries[:limit]):
            if find_media(e["id"]):
                continue
            payload = {"kind": "geschichte" if as_story else kind, "album": (pl.get("title") or "Playlist") if as_story else "",
                       "pos": pos, "story": as_story}
            c.execute("""INSERT INTO import_jobs(kind,ref,url,music,status,parent_id,payload,created,updated)
                         VALUES('video',?,?,?, 'queued', ?, ?, ?, ?)""",
                      (e["id"], f"https://{'music' if j['music'] else 'www'}.youtube.com/watch?v={e['id']}",
                       j["music"], jid, json.dumps(payload), now + n * 0.001, now))
            n += 1
    _upd(jid, status="done", step=f"{n} Titel eingereiht")
    _wake.set()
    return n


def _process_playlist(j):
    ref = j["ref"]
    url = j["url"]
    title = ""
    if ref.startswith("MPRE"):
        a = helper("album", ref)
        if not a.get("playlistId"):
            raise ImportError_("Album nicht gefunden", retry=False)
        url, title = f"https://music.youtube.com/playlist?list={a['playlistId']}", a.get("title", "")
    p = run(["--flat-playlist", "-J", url], timeout=300)
    if p.returncode != 0:
        raise ImportError_(*explain(p.stderr))
    info = json.loads(p.stdout)
    entries = [{"id": e["id"], "title": e.get("title") or "", "duration": e.get("duration")}
               for e in info.get("entries") or [] if e.get("id") and VID.match(e["id"])]
    if not entries:
        raise ImportError_("Playlist ist leer oder nicht verfügbar", retry=False)
    auto = (json.loads(j["payload"] or "{}") or {}).get("auto")
    _upd(j["id"], status="confirm", step="", payload=json.dumps(
        {"title": title or info.get("title") or "", "entries": entries, "count": len(entries)}))
    if auto:   # aus der Suche: gleich einreihen
        confirm_playlist(j["id"], kind=auto.get("kind", "lied"), as_story=bool(auto.get("as_story")))


def _download(video_id, music):
    os.makedirs(config.YT_ORIGINALS, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=config.TMP_DIR)
    try:
        p = run(["-f", "251/bestaudio/best", "--no-playlist", "--no-part", "-o", os.path.join(tmp, "%(id)s.%(ext)s"),
                 f"https://{'music' if music else 'www'}.youtube.com/watch?v={video_id}"], timeout=3600)
        files = [f for f in os.listdir(tmp) if not f.endswith((".part", ".ytdl"))]
        if p.returncode != 0 or not files:
            raise ImportError_(*explain(p.stderr))
        ext = os.path.splitext(files[0])[1]
        dst = os.path.join(config.YT_ORIGINALS, video_id + ext)
        shutil.move(os.path.join(tmp, files[0]), dst)
        return dst
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _choose_version(video_id, music, uploader=""):
    """Song-Version (YouTube Music: „counterpart“ oder passender Song per Suche) bevorzugen, wenn die Dauer
    plausibel passt. -> (geladene ID, andere ID, version, ytm-Infos)"""
    try:
        ytm = helper("song", video_id, uploader)
    except Exception as e:
        log.info("YouTube Music nicht abfragbar (%s): %s", video_id, e)
        return video_id, "", ("song" if music else "video"), {}
    vtype = ytm.get("videoType") or ""
    cp = ytm.get("counterpart") or {}
    if vtype == "MUSIC_VIDEO_TYPE_ATV":
        return video_id, cp.get("videoId") or "", "song", ytm
    if cp.get("videoId") and setting("yt_prefer_song") == "1":
        vd, cd = ytm.get("duration") or 0, cp.get("duration") or 0
        if cd and (not vd or 0.5 * vd <= cd <= vd + 5):
            return cp["videoId"], video_id, "song", {**ytm, **{k: v for k, v in cp.items() if v}}
    return video_id, cp.get("videoId") or "", "video", ytm


def _check_playable(info):
    live = info.get("live_status") or ""
    if live in ("is_live", "post_live") or info.get("is_live"):
        raise ImportError_("Livestream – nicht unterstützt", retry=False)
    if live == "is_upcoming":
        raise ImportError_("Premiere – noch nicht verfügbar", retry=False)
    duration = float(info.get("duration") or 0)
    if duration > int(setting("yt_max_len")):
        raise ImportError_(f"Zu lang ({round(duration / 60)} min, Grenze {int(setting('yt_max_len')) // 60} min)", retry=False)


def _process_video(j, target_media=None, force_id=None):
    if not target_media:
        m = find_media(j["ref"])
        if m:
            _upd(j["id"], status="done", media_id=m["id"], step="Schon vorhanden")
            return
    _upd(j["id"], step="Prüfe Video")
    if force_id:
        use_id, alt_id, version, ytm = force_id, json.loads(j["payload"] or "{}").get("from", ""), None, {}
        try:
            ytm = helper("song", force_id)
            version = "song" if ytm.get("videoType") == "MUSIC_VIDEO_TYPE_ATV" else "video"
        except Exception:
            version = "video"
        info = _info(use_id, False)
    else:
        info = _info(j["ref"], bool(j["music"]))
        _check_playable(info)
        opts = json.loads(j["payload"] or "{}") if j["kind"] == "video" else {}
        if opts.get("story"):   # Teil eines Hörspiels/Albums: genau diese Spur, keine Versionssuche
            use_id, alt_id, version, ytm = j["ref"], "", "song" if j["music"] else "video", {}
        else:
            use_id, alt_id, version, ytm = _choose_version(j["ref"], bool(j["music"]), info.get("uploader") or "")
        if use_id != j["ref"]:
            info = _info(use_id, True)
    _check_playable(info)
    duration = float(info.get("duration") or 0)

    _upd(j["id"], step="Lädt")

    path = _download(use_id, bool(j["music"]) or version == "song")
    try:
        _upd(j["id"], step="Bereitet auf")
        duration = duration or media.measure_duration(path)
        sha = media.sha256_file(path)
        cuts = sponsorblock(use_id) + silence_cuts(path, duration)
        loud = measure_loudness(path)
        uploader = info.get("uploader") or info.get("channel") or ""
        split_artist, split_title = split_video_title(info.get("title") or "", uploader)
        # YouTube Music nennt bei Musikvideos oft falsche Interpreten – nur bei echten Song-Versionen (ATV) nutzen
        ytm_ok = ytm.get("videoType") == "MUSIC_VIDEO_TYPE_ATV" or version == "song"
        title = clean_title(info.get("track") or (ytm.get("title") if ytm_ok or not split_artist else None)
                            or split_title or info.get("title") or use_id)
        artist = clean_artist((info.get("artists") or [None])[0] or info.get("artist") or info.get("creator")
                              or (", ".join(ytm.get("artists") or []) if ytm_ok else "") or split_artist
                              or clean_channel(uploader))
        cover = _cover(ytm.get("thumb")) if ytm.get("thumb") else None
        cover = cover or _cover(_video_thumb(info))
        chapters = [{"title": c.get("title") or "", "start": float(c["start_time"]), "end": float(c["end_time"])}
                    for c in info.get("chapters") or []]
        rel = os.path.relpath(path, config.LIB_DIR)
        fields = dict(title=title[:200], artist=artist[:200], duration=duration, path=rel,
                      orig_name=os.path.basename(path), sha256=sha, cover_id=cover, origin="youtube",
                      source_url=f"https://{'music' if version == 'song' else 'www'}.youtube.com/watch?v={use_id}",
                      video_id=use_id, alt_video_id=alt_id or "", version=version or "",
                      cuts=json.dumps(cuts), auto_cuts=json.dumps(cuts), loudness=json.dumps(loud) if loud else "",
                      source_chapters=json.dumps(chapters) if len(chapters) > 1 else "")
        with db.tx() as c:
            if target_media:   # Versionswechsel: bestehenden Eintrag umstellen
                old = db.q1("SELECT * FROM media WHERE id=?", (target_media,))
                fields.pop("title"), fields.pop("artist")
                if old["cover_id"]:
                    fields.pop("cover_id")
                c.execute(f"UPDATE media SET {', '.join(k + '=?' for k in fields)} WHERE id=?",
                          (*fields.values(), target_media))
                mid = target_media
            else:
                dup = db.q1("SELECT id, deleted_at FROM media WHERE sha256=?", (sha,))
                if dup and not dup["deleted_at"]:
                    os.remove(path)
                    _upd(j["id"], status="done", media_id=dup["id"], step="Schon vorhanden")
                    return
                if dup:
                    c.execute("DELETE FROM media WHERE id=?", (dup["id"],))
                opts = json.loads(j["payload"] or "{}") if j["kind"] == "video" else {}
                fields.update(kind=opts.get("kind") or "lied", album=(opts.get("album") or "")[:200],
                              album_pos=int(opts.get("pos") or 0), is_new=1, created=time.time())
                cols = ",".join(fields)
                mid = c.execute(f"INSERT INTO media({cols}) VALUES({','.join('?' * len(fields))})",
                                tuple(fields.values())).lastrowid
        if target_media and old["path"] != rel and config.media_owned(old["path"]):
            if not db.q1("SELECT id FROM media WHERE path=? AND deleted_at IS NULL", (old["path"],)):
                try:
                    os.remove(config.media_abs(old["path"]))
                except OSError:
                    pass
        _upd(j["id"], status="done", media_id=mid, step="Fertig", error="")
        if cuts:   # geschnittene Hörprobe gleich vorbereiten
            try:
                m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
                from .builder import _unit
                u = _unit(m, None, None, "", m["duration"])
                media.preview(m, None, None, u["cuts"])
            except Exception as e:
                log.info("Hörprobe %s: %s", mid, e)
        log.info("Import fertig: %s – %s (%s, %s, %d Schnitte)", artist, title, use_id, version, len(cuts))
        return mid
    except Exception:
        if not target_media and not db.q1("SELECT id FROM media WHERE path=?", (os.path.relpath(path, config.LIB_DIR),)):
            try:
                os.remove(path)
            except OSError:
                pass
        raise


def switch_version(mid):
    """Musikvideo <-> Song-Version: andere ID laden und den Eintrag umstellen (als Job)."""
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    if not m or not m["alt_video_id"]:
        return False
    now = time.time()
    with db.tx() as c:
        c.execute("""INSERT INTO import_jobs(kind,ref,url,music,status,payload,created,updated)
                     VALUES('switch',?,?,1,'queued',?,?,?)""",
                  (m["alt_video_id"], f"https://www.youtube.com/watch?v={m['alt_video_id']}",
                   json.dumps({"media_id": mid, "from": m["video_id"]}), now, now))
    _wake.set()
    return True


_preview_urls = {}


def preview_url(video_id):
    """Direkte Audio-Adresse für das Vorhören (ohne Download), 30 min zwischengespeichert."""
    hit = _preview_urls.get(video_id)
    if hit and hit[1] > time.time():
        return hit[0]
    p = run(["-f", "251/bestaudio/best", "-g", "--no-playlist", f"https://music.youtube.com/watch?v={video_id}"], timeout=60)
    if p.returncode != 0 or not p.stdout.strip():
        raise ImportError_(*explain(p.stderr))
    url = p.stdout.strip().splitlines()[0]
    _preview_urls[video_id] = (url, time.time() + 1800)
    return url


def refetch_sponsorblock(mid):
    m = db.q1("SELECT * FROM media WHERE id=?", (mid,))
    sb = sponsorblock(m["video_id"])
    keep = [c for c in json.loads(m["cuts"] or "[]") if not str(c[2]).startswith("sb:")]
    auto = [c for c in json.loads(m["auto_cuts"] or "[]") if not str(c[2]).startswith("sb:")] + sb
    with db.tx() as c:
        c.execute("UPDATE media SET cuts=?, auto_cuts=? WHERE id=?", (json.dumps(keep + sb), json.dumps(auto), mid))
    return len(sb)


def worker():
    """Genau ein Import gleichzeitig. Pausen zwischen Downloads schonen die Heim-IP."""
    last_download = 0
    while True:
        try:
            if not enabled() or not env_ready():
                _wake.wait(30)
                _wake.clear()
                continue
            j = db.q1("""SELECT * FROM import_jobs WHERE status='queued' AND next_at<=? ORDER BY id LIMIT 1""",
                      (time.time(),))
            if not j:
                _wake.wait(15)
                _wake.clear()
                continue
            gap = random.uniform(5, 10) - (time.time() - last_download)
            if j["kind"] != "playlist" and gap > 0:
                time.sleep(gap)
            _upd(j["id"], status="running", attempts=j["attempts"] + 1)
            try:
                if j["kind"] == "playlist":
                    _process_playlist(j)
                elif j["kind"] == "switch":
                    p = json.loads(j["payload"])
                    _process_video(j, target_media=p["media_id"], force_id=j["ref"])
                    last_download = time.time()
                else:
                    _process_video(j)
                    last_download = time.time()
            except ImportError_ as e:
                _fail(j, str(e), e.retry, e.update)
            except subprocess.TimeoutExpired:
                _fail(j, "Zeitüberschreitung", True, False)
            except Exception as e:
                log.exception("Import %s fehlgeschlagen", j["id"])
                _fail(j, f"Import fehlgeschlagen: {e}", True, False)
        except Exception:
            log.exception("Import-Worker")
            time.sleep(10)


def _fail(j, msg, retry, upd):
    attempt = j["attempts"] + 1
    if upd:
        threading.Thread(target=update, kwargs={"reason": "nach Fehler"}, daemon=True).start()
    if retry and attempt <= len(RETRY_DELAYS):
        delay = RETRY_DELAYS[attempt - 1]
        _upd(j["id"], status="queued", next_at=time.time() + delay, error=msg,
             step=f"Neuer Versuch in {delay // 60} min")
    else:
        _upd(j["id"], status="error", error=msg, step="")
    log.warning("Import %s (%s): %s", j["id"], j["ref"], msg)


def daily():
    """Täglich yt-dlp aktualisieren (mit Selbsttest/Rückfall)."""
    while True:
        try:
            if enabled():
                if not env_ready():
                    update(reason="Einrichtung")
                elif time.time() - (status().get("checked") or 0) > 23 * 3600:
                    update()
        except Exception:
            log.exception("yt-dlp-Update")
        time.sleep(1800)


def start():
    os.makedirs(config.YT_DIR, exist_ok=True)
    threading.Thread(target=worker, daemon=True, name="import-worker").start()
    threading.Thread(target=daily, daemon=True, name="ytdlp-update").start()


def jobs(limit=60):
    rows = db.q("SELECT * FROM import_jobs WHERE status<>'cancelled' ORDER BY id DESC LIMIT ?", (limit,))
    out = []
    for r in rows:
        p = json.loads(r["payload"] or "{}") if r["kind"] == "playlist" else {}
        out.append({"id": r["id"], "kind": r["kind"], "ref": r["ref"], "url": r["url"], "status": r["status"],
                    "step": r["step"], "error": r["error"], "media_id": r["media_id"], "attempts": r["attempts"],
                    "next_at": r["next_at"], "updated": r["updated"],
                    "playlist": {"title": p.get("title"), "count": p.get("count")} if p else None})
    return out


def shortcut_config(base_url):
    """Export-Datei für die Android-App „HTTP Shortcuts“ (Import aus Datei oder URL)."""
    import uuid
    var_id, sc_id, cat_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "version": 92, "compatibilityVersion": 90,
        "categories": [{"id": cat_id, "name": "Teddy Manager", "shortcuts": [{
            "id": sc_id, "executionType": "app", "name": "Zum Tonie",
            "description": "Geteilten YouTube-Link an den Teddy Manager schicken",
            "method": "POST", "url": f"{base_url}/api/import", "timeout": 20000,
            "requestBodyType": "custom_text", "contentType": "text/plain",
            "bodyContent": "{{" + var_id + "}}",
            "headers": [{"key": "X-Teddy-Token", "value": token()}],
            "responseHandling": {"uiType": "toast", "successOutput": "response"},
            "launcherShortcut": False,
        }]}],
        "variables": [{"id": var_id, "key": "geteilter_text", "type": "text", "title": "Link",
                       "isShareText": True, "isShareTitle": False}],
    }
