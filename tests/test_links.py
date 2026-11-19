import pytest

from app import youtube


@pytest.mark.parametrize("text, ref, music", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ", False),
    ("Schau mal: https://youtu.be/dQw4w9WgXcQ?si=abc123", "dQw4w9WgXcQ", False),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&pp=ygUJa2luZGVy&feature=share", "dQw4w9WgXcQ", False),
    ("https://www.youtube.com/shorts/aqz-KE-bpKQ?feature=share", "aqz-KE-bpKQ", False),
    ("Wie schön – Rolf Zuckowski https://music.youtube.com/watch?v=XaKPbXXbtWY&si=Ab12", "XaKPbXXbtWY", True),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=RDdQw4w9WgXcQ", "dQw4w9WgXcQ", False),
])
def test_video_links(text, ref, music):
    link = youtube.parse_link(text)
    assert link["kind"] == "video" and link["ref"] == ref and link["music"] is music
    assert "si=" not in link["url"] and "pp=" not in link["url"]


def test_playlist_and_album_links():
    assert youtube.parse_link("https://music.youtube.com/playlist?list=OLAK5uy_abc")["kind"] == "playlist"
    album = youtube.parse_link("https://music.youtube.com/browse/MPREb_P68cUkcB28Y")
    assert album["kind"] == "playlist" and album["ref"] == "MPREb_P68cUkcB28Y" and album["music"]


@pytest.mark.parametrize("text", ["kein Link", "https://example.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/kurz", ""])
def test_no_link(text):
    assert youtube.parse_link(text) is None
