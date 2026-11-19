"""Client für die TeddyCloud-HTTP-API (getestet mit v0.7.0).

Genutzte Endpunkte (alle auch von der TeddyCloud-Weboberfläche verwendet):
  GET  /api/getTagIndex, /api/getTagInfo?ruid=
  POST /content/json/set/<ruid>              (source, tonie_model, live, nocloud)
  POST /api/fileEncode?special=library       (source=… mehrfach, target=…)  -> TAF, ein Kapitel je Quelle
  GET  /api/fileIndexV2?special=library&path=
  POST /api/toniesCustomJsonUpsert, /api/toniesCustomJsonDelete
  GET  /api/toniesJsonReload
"""
import json
import logging

import httpx

from . import config

log = logging.getLogger("tc")


class TCError(Exception):
    pass


class DuplicateAudioId(TCError):
    """Ein fremder Eintrag in tonies.custom.json beschreibt dieselbe TAF (audio_id+hash)."""


def _client(timeout):
    return httpx.Client(base_url=config.TC_URL, timeout=timeout)


def _call(method, path, *, params=None, data=None, json_body=None, content=None, timeout=30.0):
    try:
        with _client(timeout) as c:
            r = c.request(method, path, params=params, data=data, json=json_body, content=content)
    except httpx.HTTPError as e:
        raise TCError(f"TeddyCloud nicht erreichbar ({type(e).__name__}: {e})") from e
    if r.status_code != 200:
        raise TCError(f"TeddyCloud {method} {path} -> HTTP {r.status_code}: {r.text.strip()[:300]}")
    return r


def uid_to_ruid(uid):
    b = bytes.fromhex(uid)
    return b[::-1].hex()


def ruid_to_uid(ruid):
    return bytes.fromhex(ruid)[::-1].hex().upper()


def tag_index():
    return _call("GET", "/api/getTagIndex").json().get("tags", [])


def tag_info(ruid):
    return _call("GET", "/api/getTagInfo", params={"ruid": ruid}).json().get("tagInfo", {})


def content_set(ruid, **fields):
    data = {k: ("true" if v is True else "false" if v is False else str(v)) for k, v in fields.items()}
    _call("POST", f"/content/json/set/{ruid}", data=data)


def encode(sources, target, timeout):
    """sources/target relativ zur Library. TeddyCloud dekodiert per ffmpeg zu 48 kHz Stereo."""
    data = {"source": list(sources), "target": target}  # httpx sendet Listen als wiederholte Felder
    r = _call("POST", "/api/fileEncode", params={"special": "library"}, data=data, timeout=timeout)
    if r.text.strip() != "OK":
        raise TCError(f"Kodieren fehlgeschlagen: {r.text.strip()[:300]}")


def file_index(path):
    return _call("GET", "/api/fileIndexV2", params={"special": "library", "path": path}).json().get("files", [])


def custom_upsert(entry):
    try:
        with _client(30) as c:
            r = c.post("/api/toniesCustomJsonUpsert", content=json.dumps(entry, ensure_ascii=False).encode(),
                       headers={"Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise TCError(f"TeddyCloud nicht erreichbar ({e})") from e
    if r.status_code == 400 and "Duplicate audio_id" in r.text:
        raise DuplicateAudioId(r.text.strip()[:300])
    if r.status_code != 200:
        raise TCError(f"tonies.custom.json konnte nicht geschrieben werden: {r.text.strip()[:300]}")


def custom_delete(models):
    try:
        with _client(30) as c:
            r = c.post("/api/toniesCustomJsonDelete", json={"models": models})
    except httpx.HTTPError as e:
        raise TCError(f"TeddyCloud nicht erreichbar ({e})") from e
    # 4xx, wenn der Eintrag nicht (mehr) existiert -> für uns gleichbedeutend mit Erfolg
    if r.status_code >= 500:
        raise TCError(f"Eintrag konnte nicht gelöscht werden: {r.text.strip()[:300]}")


def reload_tonies():
    _call("GET", "/api/toniesJsonReload")


def boxes():
    return _call("GET", "/api/getBoxes").json().get("boxes", [])


def box_setting(box_id, key):
    """Einstellung einer Box (Overlay = Box-ID, z. B. toniebox.max_vol_spk)."""
    return _call("GET", f"/api/settings/get/{key}", params={"overlay": box_id}).text.strip()


def set_box_setting(box_id, key, value):
    """Wird der Box beim nächsten Abgleich (Freshness-Check) mitgeschickt."""
    _call("POST", f"/api/settings/set/{key}", params={"overlay": box_id}, content=str(value).encode())
    # TeddyCloud 0.7.0 schickt „OK“ mit Content-Length 0 (Antwort kommt leer an) – daher Wert zurücklesen
    got = box_setting(box_id, key)
    if got != str(value):
        raise TCError(f"Einstellung {key} nicht übernommen (gesetzt {value}, gelesen {got or '–'})")


def ping():
    _call("GET", "/api/getBoxes", timeout=5)
