"""Einschlafmodus und Schnittbereiche – reine Logik, ohne ffmpeg/TeddyCloud."""
import json

from app import builder, config


def media_row(sha, duration, cuts=()):
    return {"sha256": sha, "title": sha, "duration": duration, "chapters": "", "clip_start": None, "clip_end": None,
            "cuts": json.dumps([list(c) for c in cuts])}


def units(*durations):
    return builder.units_for([media_row(f"m{i}", d) for i, d in enumerate(durations)])


def tonie(**kw):
    t = {"sleep_minutes": 10, "sleep_end_pct": 20, "sleep_stop": 1, "sleep_repeat": 1}
    t.update(kw)
    return t


def test_sleep_repeats_and_stops_at_duration():
    out = builder.apply_sleep(units(240, 180), tonie())          # 7 min Playlist, 10 min Einschlafzeit
    assert abs(sum(u["duration"] for u in out) - 600) < 0.01
    assert [u["media"]["sha256"] for u in out] == ["m0", "m1", "m0"]
    assert out[-1]["gain"]["trim"] == 180 and out[-1]["gain"]["fade"]
    offsets = [u["gain"]["o"] for u in out]
    assert offsets == [0, 240, 420]
    assert all(u["gain"]["d"] == 600 and u["gain"]["e"] == 0.2 for u in out)


def test_sleep_without_repeat_keeps_playlist_short():
    out = builder.apply_sleep(units(120), tonie(sleep_repeat=0))
    assert len(out) == 1 and out[0]["gain"]["trim"] is None


def test_sleep_without_stop_plays_everything():
    out = builder.apply_sleep(units(400, 400), tonie(sleep_stop=0))
    assert len(out) == 2 and sum(u["duration"] for u in out) == 800
    assert not any(u["gain"]["fade"] for u in out)


def test_sleep_respects_chapter_limit():
    out = builder.apply_sleep(units(5), tonie(sleep_minutes=60))
    assert len(out) <= config.MAX_TRACKS


def test_cuts_are_merged_and_subtracted():
    m = media_row("x", 100, cuts=[(0, 5, "sb:intro"), (3, 8, "silence"), (90, 100, "manual")])
    assert builder.merged_cuts(m) == [(0.0, 8.0), (90.0, 100.0)]
    u = builder.units_for([m])[0]
    assert u["cuts"] == [[0.0, 8.0], [90.0, 100.0]] and abs(u["duration"] - 82) < 1e-6


def test_clip_only_counts_cuts_inside():
    m = media_row("x", 600, cuts=[(10, 20, "manual"), (310, 320, "manual")])
    m.update(clip_start=300.0, clip_end=400.0)
    u = builder.units_for([m])[0]
    assert u["cuts"] == [[310.0, 320.0]] and abs(u["duration"] - 90) < 1e-6
