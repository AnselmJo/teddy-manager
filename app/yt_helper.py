"""Hilfsskript für YouTube Music – läuft mit dem Python der yt-dlp-Umgebung (ytmusicapi wird dort mit
aktualisiert). Ausgabe: JSON auf stdout.

  python yt_helper.py song <videoId>     -> Typ, Song-Version (counterpart), quadratisches Cover, Album, Interpreten
  python yt_helper.py album <browseId>   -> Playlist-ID und Titel eines YT-Music-Albums
"""
import json
import sys


def _len_to_s(text):
    if not text:
        return None
    s = 0
    for part in str(text).split(":"):
        s = s * 60 + int(part)
    return s


def _best_thumb(thumbs):
    if not thumbs:
        return None
    t = max(thumbs, key=lambda x: (x.get("width") or 0))
    url = t.get("url") or ""
    # Google-Bildserver: Größe direkt anfordern (quadratisch)
    if "googleusercontent.com" in url and "=w" in url:
        url = url.split("=w")[0] + "=w544-h544-l90-rj"
    return url


def _track(t):
    if not t:
        return None
    return {"videoId": t.get("videoId"), "title": t.get("title"), "videoType": t.get("videoType"),
            "duration": _len_to_s(t.get("length")) or t.get("duration_seconds"),
            "thumb": _best_thumb(t.get("thumbnail") or t.get("thumbnails")),
            "album": (t.get("album") or {}).get("name") if isinstance(t.get("album"), dict) else None,
            "artists": [a.get("name") for a in (t.get("artists") or []) if a.get("name")]}


STOP = {"musik", "music", "kinder", "kids", "lieder", "official", "band", "freunde", "seine", "und", "and", "the",
         "feat", "topic", "vevo", "fur", "dich", "channel", "kanal", "records"}


def _norm(s, brackets=True):
    import re
    import unicodedata
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss")
    if brackets:
        s = re.sub(r"[\(\[][^\)\]]*[\)\]]?[\)\]]?", " ", s)     # (Official Video), (Megamix Cut [Mixed]) …
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _words(s):
    return {w for w in _norm(s).split() if len(w) >= 4 and w not in STOP}


def _find_song(yt, title, artists, author, duration):
    """Song-Version (ATV) per Suche: Titel gleich, Interpret passt (Wortabgleich), Dauer plausibel.
    Bevorzugt die Fassung ohne Zusatz in Klammern (Studio statt Live/Remix)."""
    names = set().union(*[_words(a) for a in artists if a], _words(author))
    want = _norm(title)
    queries = [f"{want} {artists[0]}" if artists else "", f"{want} {author}" if author else "", want]
    seen, hits = set(), []
    for q in [x for x in queries if x]:
        for r in yt.search(q, filter="songs", limit=10)[:10]:
            vid = r.get("videoId")
            if r.get("resultType") != "song" or not vid or vid in seen:
                continue
            seen.add(vid)
            if _norm(r.get("title")) != want:
                continue
            r_words = set().union(*[_words(a.get("name")) for a in r.get("artists") or []])
            if names and not (names & r_words):
                continue
            d = r.get("duration_seconds") or _len_to_s(r.get("duration"))
            if duration and d and not (0.5 * duration <= d <= duration + 5):
                continue
            plain = _norm(r.get("title"), brackets=False) == want
            hits.append((not plain, abs((d or 0) - (duration or 0)), r))
        if hits:
            break
    if not hits:
        return None
    r = sorted(hits, key=lambda x: (x[0], x[1]))[0][2]
    hit = _track(r)
    hit["videoType"] = r.get("videoType") or "MUSIC_VIDEO_TYPE_ATV"
    hit["matched"] = "search"
    return hit


def song(video_id, uploader=""):
    from ytmusicapi import YTMusic
    yt = YTMusic()
    wp = yt.get_watch_playlist(videoId=video_id, limit=1)
    tracks = wp.get("tracks") or []
    first = next((t for t in tracks if t.get("videoId") == video_id), tracks[0] if tracks else None)
    out = _track(first) or {}
    out["counterpart"] = _track((first or {}).get("counterpart"))
    if not out["counterpart"] and out.get("videoType") in ("MUSIC_VIDEO_TYPE_OMV", "MUSIC_VIDEO_TYPE_UGC"):
        author = ""
        try:
            author = (yt.get_song(video_id).get("videoDetails") or {}).get("author") or ""
        except Exception:
            pass
        out["author"] = author
        out["counterpart"] = _find_song(yt, out.get("title"), out.get("artists") or [],
                                        " ".join(x for x in (author, uploader) if x), out.get("duration"))
    return out


def album(browse_id):
    from ytmusicapi import YTMusic
    a = YTMusic().get_album(browse_id)
    return {"playlistId": a.get("audioPlaylistId"), "title": a.get("title"),
            "artists": [x.get("name") for x in a.get("artists") or []]}


def search(query, kind="songs"):
    """Suche in YouTube Music: songs | albums | videos."""
    from ytmusicapi import YTMusic
    out = []
    for r in YTMusic().search(query, filter=kind, limit=20)[:20]:
        item = {"title": r.get("title"), "artists": [a.get("name") for a in r.get("artists") or [] if a.get("name")],
                "thumb": _best_thumb(r.get("thumbnails")), "type": kind}
        if kind == "albums":
            item.update(browseId=r.get("browseId"), year=r.get("year"), album_type=r.get("type"))
            if not item["browseId"]:
                continue
        else:
            item.update(videoId=r.get("videoId"), duration=r.get("duration_seconds") or _len_to_s(r.get("duration")),
                        album=(r.get("album") or {}).get("name") if isinstance(r.get("album"), dict) else None)
            if not item["videoId"]:
                continue
        out.append(item)
    return out


def album_tracks(browse_id):
    from ytmusicapi import YTMusic
    a = YTMusic().get_album(browse_id)
    return {"title": a.get("title"), "artists": [x.get("name") for x in a.get("artists") or []],
            "thumb": _best_thumb(a.get("thumbnails")), "playlistId": a.get("audioPlaylistId"), "year": a.get("year"),
            "tracks": [{"videoId": t.get("videoId"), "title": t.get("title"),
                        "duration": t.get("duration_seconds") or _len_to_s(t.get("duration"))}
                       for t in a.get("tracks") or [] if t.get("videoId")],
            # Hörspiel-Alben großer Labels liefert YouTube Music ohne Premium-Anmeldung nicht aus
            "unavailable": sum(1 for t in a.get("tracks") or [] if not t.get("videoId"))}


if __name__ == "__main__":
    print(json.dumps({"song": song, "album": album, "search": search, "album_tracks": album_tracks}[sys.argv[1]](*sys.argv[2:])))
