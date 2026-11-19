"""Audio- und Bildverarbeitung: Tags/Kapitel lesen, Cover extrahieren, Bilder zuschneiden,
Kapitel ausschneiden und Lautheit angleichen, Münz-Standardbilder zeichnen."""
import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import unicodedata

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from . import config, db

log = logging.getLogger("media")

_TRANSLIT = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


def slugify(text, maxlen=60):
    s = "".join(_TRANSLIT.get(ch, ch) for ch in text)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen].strip("-")) or "titel"


def unique_path(directory, slug, ext):
    os.makedirs(directory, exist_ok=True)
    cand, n = os.path.join(directory, slug + ext), 2
    while os.path.exists(cand):
        cand = os.path.join(directory, f"{slug}-{n}{ext}")
        n += 1
    return cand


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ TAF

def is_taf(path):
    """TAF = 4-Byte-Länge + Protobuf-Header, ab 0x1000 Ogg-Opus."""
    try:
        with open(path, "rb") as f:
            head = f.read(config.TAF_HEADER + 4)
        return len(head) >= config.TAF_HEADER + 4 and head[config.TAF_HEADER:config.TAF_HEADER + 4] == b"OggS" \
            and struct.unpack(">I", head[:4])[0] < config.TAF_HEADER
    except OSError:
        return False


def _varint(b, i):
    v = shift = 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7F) << shift
        shift += 7
        if not c & 0x80:
            return v, i


def taf_info(path):
    """-> {audio_id, sha1, duration, chapters:[(start,end)]} aus Header und Ogg-Seiten."""
    with open(path, "rb") as f:
        hlen = struct.unpack(">I", f.read(4))[0]
        hdr = f.read(hlen)
        fields, pages, i = {}, [], 0
        while i < len(hdr):
            key, i = _varint(hdr, i)
            fn, wt = key >> 3, key & 7
            if wt == 0:
                fields[fn], i = _varint(hdr, i)
            elif wt == 2:
                ln, i = _varint(hdr, i)
                data = hdr[i:i + ln]
                i += ln
                if fn == 4:
                    j = 0
                    while j < len(data):
                        p, j = _varint(data, j)
                        pages.append(p)
                else:
                    fields[fn] = data
            else:
                break
        def granule_at(page):
            """TAF-Seiten sind 4096 Byte groß; Seite 0 beginnt hinter den Opus-Headern bei 0x1200
            (wie TeddyCloud handler.c). -> Granule-Position am Ende dieser Seite."""
            f.seek(config.TAF_HEADER + 4096 * page + (0x200 if page == 0 else 0))
            h = f.read(14)
            return struct.unpack("<q", h[6:14])[0] if len(h) == 14 and h[:4] == b"OggS" else None

        last, pos = 0, config.TAF_HEADER
        while True:   # Gesamtdauer: letzte Granule-Position
            f.seek(pos)
            h = f.read(27)
            if len(h) < 27 or h[:4] != b"OggS":
                break
            last = max(last, struct.unpack("<q", h[6:14])[0])
            pos += 27 + h[26] + sum(f.read(h[26]))
        total = last / 48000
        # Kapitel k beginnt mit Seite pages[k] -> Startzeit = Ende der Seite davor
        starts = [0.0 if p == 0 else max(granule_at(p - 1) or 0, 0) / 48000 for p in pages] or [0.0]
    chapters = [(s, starts[k + 1] if k + 1 < len(starts) else total) for k, s in enumerate(starts)]
    return {"audio_id": fields.get(3), "sha1": (fields.get(1) or b"").hex(), "duration": total, "chapters": chapters}


def _run(cmd, timeout=600, stdin=None):
    p = subprocess.run(cmd, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} fehlgeschlagen: {p.stderr.decode(errors='replace')[-600:]}")
    return p.stdout


class OggView:
    """Liefert für TAF-Dateien einen Pfad auf den reinen Ogg-Teil (temporäre Kopie), sonst die Datei selbst."""

    def __init__(self, path):
        self.path, self.tmp = path, None

    def __enter__(self):
        if is_taf(self.path):
            os.makedirs(config.TMP_DIR, exist_ok=True)
            fd, self.tmp = tempfile.mkstemp(suffix=".ogg", dir=config.TMP_DIR)
            with os.fdopen(fd, "wb") as out, open(self.path, "rb") as src:
                src.seek(config.TAF_HEADER)
                shutil.copyfileobj(src, out)
            return self.tmp
        return self.path

    def __exit__(self, *a):
        if self.tmp:
            os.remove(self.tmp)


def open_input(path):
    """-> (ffmpeg-Eingabeargumente, stdin-Datei|None). TAF wird ohne Kopie per Pipe ab 0x1000 gelesen."""
    if is_taf(path):
        f = open(path, "rb")
        f.seek(config.TAF_HEADER)
        return ["-f", "ogg", "-i", "pipe:0"], f
    return ["-i", path], None


# ------------------------------------------------------------------ Metadaten

def probe(path):
    with OggView(path) as p:
        out = _run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                    "-show_chapters", p], timeout=120)
    return json.loads(out)


def _tags(info):
    tags = {}
    for src in [info.get("format", {})] + info.get("streams", []):
        for k, v in (src.get("tags") or {}).items():
            tags.setdefault(k.lower(), v)
    return tags


def read_metadata(path, orig_name):
    """-> dict(title, artist, album, track, duration, chapters, cover). Wirft ValueError bei Nicht-Audio."""
    info = probe(path)
    if not any(s.get("codec_type") == "audio" for s in info.get("streams", [])):
        raise ValueError("Die Datei enthält keine Tonspur.")
    tags = _tags(info)
    duration = float(info.get("format", {}).get("duration") or 0)
    chapters = []
    if is_taf(path):
        ti = taf_info(path)
        duration = duration or ti["duration"]
        if len(ti["chapters"]) > 1:
            chapters = [{"title": "", "start": s, "end": e} for s, e in ti["chapters"]]
    elif len(info.get("chapters") or []) > 1:
        chapters = [{"title": (c.get("tags") or {}).get("title", ""), "start": float(c["start_time"]),
                     "end": float(c["end_time"])} for c in info["chapters"]]
    if duration <= 0:
        duration = measure_duration(path)
    stem = os.path.splitext(orig_name)[0]
    title, artist = tags.get("title", "").strip(), tags.get("artist", "").strip()
    if not title:
        if " - " in stem:
            a, t = stem.split(" - ", 1)
            title, artist = t.strip(), artist or a.strip()
        else:
            title = stem.replace("_", " ").strip()
    track = re.match(r"\d+", tags.get("track", "") or "")
    return {"title": title or "Ohne Titel", "artist": artist, "album": tags.get("album", "").strip(),
            "track": int(track.group()) if track else 0, "duration": duration, "chapters": chapters,
            "cover": extract_cover(path, info, tags)}


def measure_duration(path):
    args, stdin = open_input(path)
    try:
        p2 = subprocess.run(["ffmpeg", "-nostdin" if stdin is None else "-hide_banner", *args, "-f", "null", "-"],
                            stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=900)
    finally:
        if stdin:
            stdin.close()
    times = re.findall(rb"time=(\d+):(\d+):(\d+\.\d+)", p2.stderr)
    if not times:
        return 0.0
    h, m, s = times[-1]
    return int(h) * 3600 + int(m) * 60 + float(s)


def _flac_picture(b64):
    """METADATA_BLOCK_PICTURE (Vorbis/Opus-Kommentar) -> Bildbytes."""
    data = base64.b64decode(b64)
    pos = 4
    mlen = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4 + mlen
    dlen = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4 + dlen + 16
    plen = struct.unpack(">I", data[pos:pos + 4])[0]
    return data[pos + 4:pos + 4 + plen]


def extract_cover(path, info, tags):
    try:
        if tags.get("metadata_block_picture"):
            return _flac_picture(tags["metadata_block_picture"])
        vids = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        if vids:
            with OggView(path) as p:
                return _run(["ffmpeg", "-nostdin", "-v", "error", "-i", p, "-an", "-map", f"0:{vids[0]['index']}",
                             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], timeout=60) or None
    except Exception as e:  # Cover ist optional
        log.warning("Cover aus %s nicht lesbar: %s", path, e)
    return None


# ------------------------------------------------------------------ Bilder

def store_image(raw, source, label=""):
    """Bild quadratisch zuschneiden, auf 512 px verkleinern, als WebP ablegen. -> images.id"""
    img = Image.open(io.BytesIO(raw))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGBA") if img.mode in ("P", "LA", "RGBA") else img.convert("RGB")
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))
    if side > 512:
        img = img.resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=85, method=4)
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    existing = db.q1("SELECT id, deleted_at FROM images WHERE sha256=?", (sha,))
    if existing:
        if existing["deleted_at"]:
            with db.tx() as c:
                c.execute("UPDATE images SET deleted_at=NULL WHERE id=?", (existing["id"],))
        return existing["id"]
    os.makedirs(config.IMG_DIR, exist_ok=True)
    fname = sha[:20] + ".webp"
    tmp = os.path.join(config.IMG_DIR, "." + fname)
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(config.IMG_DIR, fname))
    with db.tx() as c:
        cur = c.execute("INSERT INTO images(sha256,file,source,label,created) VALUES(?,?,?,?,?)",
                        (sha, fname, source, label, time.time()))
        return cur.lastrowid


def _shade(rgb, f):
    return tuple(max(0, min(255, int(c * f if f < 1 else c + (255 - c) * (f - 1)))) for c in rgb)


def coin_image(hex_color):
    """Standardbild: dicke Münze (Traveltonie-Form: Rand + vertiefte Fläche) in der Farbe. -> Dateiname"""
    hex_color = hex_color.lower()
    fname = f"coin2-{hex_color[1:]}.webp"
    path = os.path.join(config.IMG_DIR, fname)
    if os.path.exists(path):
        return fname
    S = 4 * 512                      # Supersampling
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, rx, ry = S / 2, S * 0.46, S * 0.31     # Ellipse der Oberseite (leicht von oben gesehen)
    thick = S * 0.15
    top_cy = S * 0.42
    bot_cy = top_cy + thick
    # Schatten
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse([cx - rx * 1.02, bot_cy - ry * 0.85 + S * 0.03, cx + rx * 1.02, bot_cy + ry * 0.85 + S * 0.05],
                                   fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(S * 0.02)))
    d = ImageDraw.Draw(img)
    # Seitenband: senkrechte Streifen mit Zylinder-Schattierung
    for x in range(int(cx - rx), int(cx + rx) + 1):
        u = (x - cx) / rx
        y_off = ry * math.sqrt(max(0.0, 1 - u * u))
        light = 0.5 + 0.25 * math.cos(u * math.pi / 2) - 0.08 * u
        d.line([(x, top_cy + y_off), (x, bot_cy + y_off)], fill=_shade(rgb, light))
    d.arc([cx - rx, bot_cy - ry, cx + rx, bot_cy + ry], start=0, end=180, fill=_shade(rgb, 0.35), width=int(S * 0.006))
    # Oberseite (Rand)
    d.ellipse([cx - rx, top_cy - ry, cx + rx, top_cy + ry], fill=_shade(rgb, 1.0))
    # Glanzkante oben links
    d.arc([cx - rx + S * 0.01, top_cy - ry + S * 0.01, cx + rx - S * 0.01, top_cy + ry - S * 0.01],
          start=190, end=290, fill=_shade(rgb, 1.35), width=int(S * 0.012))
    # Vertiefung: oberer Innenrand im Schatten, Fläche leicht dunkler
    k = 0.76
    irx, iry = rx * k, ry * k
    d.ellipse([cx - irx, top_cy - iry, cx + irx, top_cy + iry], fill=_shade(rgb, 0.68))
    d.ellipse([cx - irx, top_cy - iry + S * 0.022, cx + irx, top_cy + iry], fill=_shade(rgb, 0.9))
    d.arc([cx - irx, top_cy - iry, cx + irx, top_cy + iry], start=20, end=160, fill=_shade(rgb, 1.25), width=int(S * 0.008))
    img = img.resize((512, 512), Image.LANCZOS)
    os.makedirs(config.IMG_DIR, exist_ok=True)
    tmp = os.path.join(config.IMG_DIR, "." + fname)
    img.save(tmp, "WEBP", quality=90, method=4)
    os.replace(tmp, path)
    return fname


# ------------------------------------------------------------------ Bauen

def prepare_unit(media_row, start, end, loudnorm, cuts=(), gain=None):
    """Kapitel/Ausschnitt ohne Schnittbereiche (und ggf. Lautheit) als FLAC im Cache.
    Alle Zeiten beziehen sich auf das Original. -> Pfad relativ zur Library."""
    measured = json.loads(media_row["loudness"] or "null") if loudnorm and "loudness" in media_row.keys() else None
    key = f"{media_row['sha256'][:24]}-{start or 0:.2f}-{end or 0:.2f}-{'ln' if loudnorm else 'raw'}"
    if cuts or measured:
        key += "-" + json.dumps([[round(a, 2), round(b, 2)] for a, b in cuts]) + ("-m" if measured else "")
    if gain:
        key += "-g" + json.dumps(gain, sort_keys=True)
    rel = f"{config.TM_SUB}/cache/units/{hashlib.sha1(key.encode()).hexdigest()[:24]}.flac"
    dst = os.path.join(config.LIB_DIR, rel)
    if os.path.exists(dst):
        return rel
    os.makedirs(config.UNITS_DIR, exist_ok=True)
    args, stdin = open_input(config.media_abs(media_row["path"]))
    filters = []
    if start is not None or end is not None:
        filters.append("atrim=" + ":".join(x for x in (f"start={start:.3f}" if start is not None else "",
                                                        f"end={end:.3f}" if end is not None else "") if x))
    if cuts:
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts)
        filters.append(f"aselect='not({expr})'")
    if filters or gain:
        filters.append("asetpts=N/SR/TB")
    if gain and gain.get("trim"):   # Einschlafmodus: am Ende der Dauer abschneiden
        filters += [f"atrim=end={gain['trim']:.3f}", "asetpts=N/SR/TB"]
    if loudnorm:
        ln = "loudnorm=I=-18:TP=-1.5:LRA=11"
        if measured and not cuts and start is None:   # Zweiter Durchlauf mit gespeicherter Messung: genauer
            ln += (f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                   f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                   f":offset={measured['target_offset']}:linear=true")
        filters.append(ln)
    if gain:   # Einschlafmodus: über die Gesamtdauer gleichmäßig leiser (t = Zeit in dieser Einheit)
        o, d, e = gain["o"], gain["d"], gain["e"]
        filters.append(f"volume='max({e:.3f},1-{1 - e:.3f}*min(1,(t+{o:.2f})/{d}))':eval=frame")
        if gain.get("fade"):
            length = gain.get("trim")
            if length is None:
                length = (end if end is not None else media_row["duration"]) - (start or 0) - sum(b - a for a, b in cuts)
            filters.append(f"afade=t=out:st={max(0, length - 8):.2f}:d=8")
    filt = ["-af", ",".join(filters)] if filters else []
    tmp = dst + ".tmp.flac"
    try:
        _run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args, "-vn", *filt,
              "-ar", "48000", "-ac", "2", "-c:a", "flac", tmp], timeout=3600, stdin=stdin)
    finally:
        if stdin:
            stdin.close()
    os.replace(tmp, dst)
    return rel


def preview(media_row, start, end, cuts):
    """Geschnittene Hörprobe (Opus/Ogg, seekbar) im Cache – so, wie es später auf dem Tonie klingt
    (ohne Lautheitsangleichung). -> absoluter Pfad"""
    key = json.dumps([media_row["sha256"], start, end, cuts])
    dst = os.path.join(config.TM_DIR, "cache", "preview", hashlib.sha1(key.encode()).hexdigest()[:24] + ".ogg")
    if os.path.exists(dst):
        os.utime(dst)
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    filters = []
    if start is not None or end is not None:
        filters.append("atrim=" + ":".join(x for x in (f"start={start:.3f}" if start is not None else "",
                                                        f"end={end:.3f}" if end is not None else "") if x))
    if cuts:
        filters.append("aselect='not(" + "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cuts) + ")'")
    filters.append("asetpts=N/SR/TB")
    args, stdin = open_input(config.media_abs(media_row["path"]))
    tmp = dst + ".tmp.ogg"
    try:
        _run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args, "-vn", "-af", ",".join(filters),
              "-c:a", "libopus", "-b:a", "96k", tmp], timeout=1800, stdin=stdin)
    finally:
        if stdin:
            stdin.close()
    os.replace(tmp, dst)
    return dst


def check_stream(url):
    """Liest ein paar Sekunden aus dem Stream. -> (ok, meldung)"""
    try:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-rw_timeout", "8000000", "-i", url, "-t", "3",
                        "-f", "null", "-"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=25, check=True)
        return True, "OK"
    except subprocess.TimeoutExpired:
        return False, "Zeitüberschreitung"
    except subprocess.CalledProcessError as e:
        return False, e.stderr.decode(errors="replace").strip()[-200:]
