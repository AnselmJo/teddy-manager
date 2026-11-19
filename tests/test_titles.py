import pytest

from app import media, youtube


@pytest.mark.parametrize("raw, clean", [
    ("Baby Shark Dance [HD] (Official Video)", "Baby Shark Dance"),
    ("Das Obstlied || Kinderlieder zum Lernen", "Das Obstlied"),
    ("💡 Das Gemüselied || Kinderlieder zum Lernen", "Das Gemüselied"),
    ("Morgen, Kinder, wirds was geben - Weihnachtslieder zum Mitsingen", "Morgen, Kinder, wirds was geben"),
    ("Die besten TRAKTOR LIEDER! 20 Minuten Mix (Mit Text zum Mitsingen)", "Die besten TRAKTOR LIEDER! 20 Minuten Mix"),
    ("Ohne Zusatz", "Ohne Zusatz"),
])
def test_clean_title(raw, clean):
    assert youtube.clean_title(raw) == clean


def test_split_video_title():
    # linker Teil passt zum Kanal -> Interpret | Titel
    assert youtube.split_video_title("Rolf Zuckowski | Wie schön, dass du geboren bist (Lyric Video)",
                                     "Rolf Zuckowski - Musik für Dich")[0] == "Rolf Zuckowski"
    # rechts nur Beiwerk -> links ist der Titel
    assert youtube.split_video_title("Kling, Glöckchen - Weihnachtslieder zum Mitsingen | Sing Kinderlieder",
                                     "Sing mit mir - Kinderlieder") == ("", "Kling, Glöckchen")
    assert youtube.split_video_title("Coldplay - Yellow (Official Video)", "Coldplay") == ("Coldplay", "Yellow (Official Video)")


def test_clean_channel():
    assert youtube.clean_channel("Rolf Zuckowski - Musik für Dich") == "Rolf Zuckowski"
    assert youtube.clean_channel("PinkfongVEVO") == "Pinkfong"
    assert youtube.clean_artist("Pinkfong - Topic") == "Pinkfong"


def test_slugify():
    assert media.slugify("Große Uhren machen tick tack") == "grosse-uhren-machen-tick-tack"
    assert media.slugify("Ärger über Öl") == "aerger-ueber-oel"
    assert media.slugify("!!!") == "titel"
