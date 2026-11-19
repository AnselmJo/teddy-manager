"""Einmalige Übernahme bestehender Selbstbau-Tonies und Library-TAFs.

Aufruf im Container:  python -m app.importer --prefix E0040350XXXX [--dry-run] [UID=Name:Farbe ...]

- Jede einspurige TAF im Library-Hauptordner wird als Lied in die Bibliothek übernommen – ohne Kopie,
  die Bibliothek verweist auf die vorhandene Datei.
- Jeder Tag mit dem angegebenen UID-Präfix (--prefix, z. B. die ersten Stellen eurer NFC-Tags) wird als Custom-Tonie angelegt. Hat er eine TAF als Quelle,
  bekommt er diese als Playlist; die vorhandene TAF bleibt aktiv (kein Neubau), bis der Inhalt geändert wird.
"""
import json
import os
import sys
import time

from . import builder, config, db, media, tc

COLORS = ["rot", "orange", "gelb", "limette", "gruen", "tuerkis", "hellblau", "blau", "lila", "pink", "braun", "schwarz"]


def main(argv):
    dry = "--dry-run" in argv
    if "--prefix" not in argv:
        sys.exit("Bitte --prefix <UID-Anfang> angeben (z. B. --prefix E0040350ABCD) – nur diese Tags werden übernommen.")
    prefix = argv[argv.index("--prefix") + 1].upper()
    overrides = {}
    for a in argv:
        if "=" in a:
            uid, rest = a.split("=", 1)
            name, _, color = rest.partition(":")
            overrides[uid.upper()] = (name, color or None)
    db.init()
    os.makedirs(config.TMP_DIR, exist_ok=True)

    lib_tafs = {f["name"]: f for f in tc.file_index("/") if not f.get("isDir") and f.get("tafHeader", {}).get("valid")}
    media_by_file = {}
    for name, f in sorted(lib_tafs.items()):
        if len(f["tafHeader"].get("trackSeconds") or []) > 1:
            print(f"übersprungen (mehrere Kapitel): {name}")
            continue
        src = os.path.join(config.LIB_DIR, name)
        sha = media.sha256_file(src)
        row = db.q1("SELECT * FROM media WHERE sha256=?", (sha,))
        if not row:
            stem = os.path.splitext(name)[0]
            artist, title = (stem.split(" - ", 1) + [""])[:2] if " - " in stem else ("", stem)
            if not title:
                artist, title = "", stem
            print(f"Lied: {title!r} von {artist!r}")
            if dry:
                continue
            # Keine Kopie: die Bibliothek verweist auf die vorhandene Datei (wird nie verändert/gelöscht).
            with db.tx() as c:
                c.execute("""INSERT INTO media(kind,title,artist,duration,path,orig_name,sha256,created)
                             VALUES('lied',?,?,?,?,?,?,?)""",
                          (title.strip(), artist.strip(), media.measure_duration(src), name, name, sha, time.time()))
            row = db.q1("SELECT * FROM media WHERE sha256=?", (sha,))
        media_by_file[name] = row

    for i, tag in enumerate(tc.tag_index()):
        uid = (tag.get("uid") or "").replace(":", "").upper()
        if not uid.startswith(prefix) or db.q1("SELECT id FROM tonies WHERE uid=?", (uid,)):
            continue
        source = tag.get("source") or ""
        fname = source[len("lib://"):] if source.startswith("lib://") else None
        m = media_by_file.get(fname) if fname else None
        name, color = overrides.get(uid, (None, None))
        name = name or (m["title"] if m else f"Tonie {uid[-4:]}")
        color = color or COLORS[int(uid[-2:], 16) % len(COLORS)]
        print(f"{config.TERM}: {uid} -> {name!r} ({color}), Inhalt: {m['title'] if m else 'leer'}")
        if dry:
            continue
        with db.tx() as c:
            tid = c.execute("INSERT INTO tonies(uid,name,color,created) VALUES(?,?,?,?)",
                            (uid, name, color, time.time() + i * 0.001)).lastrowid
            if m:
                c.execute("INSERT INTO playlist(tonie_id,pos,media_id) VALUES(?,0,?)", (tid, m["id"]))
        if m:
            t = db.q1("SELECT * FROM tonies WHERE id=?", (tid,))
            hdr = lib_tafs[fname]["tafHeader"]
            with db.tx() as c:  # vorhandene TAF als „gebaut“ übernehmen -> kein Neubau
                c.execute("""UPDATE tonies SET built_key=?, built_source=?, built_audio_id=?, built_hash=?,
                             built_seconds=? WHERE id=?""",
                          (builder.desired(t)["key"], source, hdr.get("audioId"), (hdr.get("sha1Hash") or "").upper(),
                           json.dumps(hdr.get("trackSeconds")), tid))
    print("fertig – der laufende Teddy Manager gleicht die neuen Einträge innerhalb einer Stunde ab "
          "(oder sofort über „Alles neu synchronisieren“).")


if __name__ == "__main__":
    main(sys.argv[1:])
