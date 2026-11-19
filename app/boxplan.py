"""Abendmodus pro Toniebox: zwischen Start- und Endzeit gelten andere Werte (Lautstärke, Licht).

Gesetzt über TeddyClouds Einstellungs-API (Overlay = Box-ID). Die Box übernimmt Werte beim nächsten Abgleich –
das passiert, wenn sie eingeschaltet wird oder aus dem Ruhezustand aufwacht, also typischerweise abends beim
Zubettgehen.
"""
import json
import logging
import threading
import time

from . import db, tc

log = logging.getLogger("boxplan")
KEYS = {"vol_spk": "toniebox.max_vol_spk", "vol_hdp": "toniebox.max_vol_hdp", "slap": "toniebox.slap_enabled",
        "slap_back_left": "toniebox.slap_back_left", "led": "toniebox.led"}
EVENING_KEYS = ("vol_spk", "vol_hdp", "led")
DEFAULT_EVENING = {"on": False, "start": "19:00", "end": "07:00", "vol_spk": 1, "vol_hdp": 1, "led": 2}


def _fmt(v):
    return ("true" if v else "false") if isinstance(v, bool) else str(int(v))


def plan(box_id):
    try:
        p = json.loads(db.get_setting(f"box_plan_{box_id}") or "{}")
    except ValueError:
        p = {}
    p.setdefault("evening", dict(DEFAULT_EVENING))
    return p


def save_plan(box_id, p):
    db.set_setting(f"box_plan_{box_id}", json.dumps(p))


def _minutes(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def evening_active(p, now=None):
    ev = p.get("evening") or {}
    if not ev.get("on"):
        return False
    lt = time.localtime(now)
    cur, a, b = lt.tm_hour * 60 + lt.tm_min, _minutes(ev["start"]), _minutes(ev["end"])
    return a <= cur < b if a < b else (cur >= a or cur < b)


def current_values(box_id):
    out = {}
    for k, key in KEYS.items():
        v = tc.box_setting(box_id, key)
        out[k] = (v == "true") if v in ("true", "false") else int(v) if v.isdigit() else v
    return out


def apply(box_id, values):
    for k, v in values.items():
        if k in KEYS:
            tc.set_box_setting(box_id, KEYS[k], _fmt(v))


def tick():
    for b in tc.boxes():
        bid = b["ID"]
        p = plan(bid)
        if not (p.get("evening") or {}).get("on") and p.get("applied") != "evening":
            continue
        want = "evening" if evening_active(p) else "day"
        if p.get("applied") == want:
            continue
        if want == "evening":
            if "day" not in p:   # Tageswerte merken, bevor der Abend sie überschreibt
                p["day"] = {k: v for k, v in current_values(bid).items() if k in EVENING_KEYS}
            apply(bid, {k: p["evening"][k] for k in EVENING_KEYS})
        else:
            apply(bid, p.get("day") or {})
        p["applied"] = want
        save_plan(bid, p)
        log.info("Box %s: %s-Profil gesetzt", bid, "Abend" if want == "evening" else "Tag")


def loop():
    while True:
        try:
            tick()
        except Exception as e:
            log.warning("Abendmodus: %s", e)
        time.sleep(60)


def start():
    threading.Thread(target=loop, daemon=True, name="boxplan").start()
