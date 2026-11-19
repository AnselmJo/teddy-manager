import os

from app import media
from conftest import FIXTURES

TAF = os.path.join(FIXTURES, "three-chapters.taf")   # 3 Sinustöne à 2 s, gebaut mit TeddyClouds Encoder


def test_is_taf():
    assert media.is_taf(TAF)
    assert not media.is_taf(__file__)


def test_taf_chapters():
    info = media.taf_info(TAF)
    assert isinstance(info["audio_id"], int) and len(info["sha1"]) == 40
    assert abs(info["duration"] - 6.0) < 0.3
    starts = [s for s, _ in info["chapters"]]
    assert len(starts) == 3
    for got, want in zip(starts, (0.0, 2.0, 4.0)):
        assert abs(got - want) < 0.3
    # Kapitel schließen lückenlos aneinander an, das letzte endet am Dateiende
    assert all(abs(info["chapters"][i][1] - info["chapters"][i + 1][0]) < 1e-6 for i in range(2))
    assert abs(info["chapters"][-1][1] - info["duration"]) < 1e-6
