"""Zentrale Einstellungen. Alles, was vom Setup abhängt, kommt aus Umgebungsvariablen."""
import os

# Name für die selbst gebauten NFC-Figuren (in TeddyCloud als Serie sichtbar). Bewusst nur hier definiert.
TERM = "Custom-Tonie"
TERM_PLURAL = "Custom-Tonies"

# Farbpalette (gleiche Schlüssel wie im Frontend); daneben sind freie Farben als "#rrggbb" erlaubt.
COLORS = {
    "rot": "#e53935", "orange": "#fb8c00", "gelb": "#fdd835", "limette": "#7cb342", "gruen": "#2e7d32",
    "tuerkis": "#00acc1", "hellblau": "#42a5f5", "blau": "#1e3a8a", "lila": "#8e24aa", "pink": "#ec407a",
    "braun": "#6d4c41", "schwarz": "#263238",
}


def color_hex(color):
    if color and len(color) == 7 and color.startswith("#"):
        return color.lower()
    return COLORS.get(color, COLORS["blau"])

TC_URL = os.environ.get("TC_URL", "http://teddycloud:80")
# Adresse, unter der das Handy den Manager per HTTP erreicht (für die HTTP-Shortcuts-Konfiguration)
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
# Docker-Log-API für TeddyCloud (über docker-socket-proxy, nur lesend); leer = „Zuletzt aufgelegt“ aus
TC_LOG_URL = os.environ.get("TC_LOG_URL", "")

# TeddyCloud-Library (gemeinsames Volume). Wir schreiben ausschließlich in TM_SUB.
LIB_DIR = os.environ.get("LIB_DIR", "/library")
# Unterstrich: andere Library-Scanner (z. B. teddycloud-companion) überspringen solche Ordner.
# Ordnernamen: Standard für neue Installationen; ältere Installationen setzen TM_FOLDER/IMG_FOLDER in .env
TM_SUB = os.environ.get("TM_FOLDER", "_teddy-manager")
TM_DIR = os.path.join(LIB_DIR, TM_SUB)
MEDIA_DIR = os.path.join(TM_DIR, "media")
BUILD_DIR = os.path.join(TM_DIR, "build")
UNITS_DIR = os.path.join(TM_DIR, "cache", "units")  # vorbereitete Kapitel (Ausschnitt/Lautheit), reproduzierbar
YT_ORIGINALS = os.path.join(MEDIA_DIR, "originals", "youtube")  # geladene Audiospuren, unverändert
TMP_DIR = os.path.join(TM_DIR, "tmp")

# Bilder liegen in TeddyClouds custom_img (wird von TeddyCloud selbst ausgeliefert).
IMG_FOLDER = os.environ.get("IMG_FOLDER", "teddy-manager")
IMG_DIR = os.environ.get("IMG_DIR", f"/custom_img/{IMG_FOLDER}")
IMG_TC_PREFIX = f"/custom_img/{IMG_FOLDER}"

# TeddyCloud-Config, nur lesend (tonies.json für die Bildersuche).
TC_CONFIG_DIR = os.environ.get("TC_CONFIG_DIR", "/tc-config")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "db.sqlite")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
YT_DIR = os.path.join(DATA_DIR, "ytdlp")          # yt-dlp-Umgebungen, cookies.txt, Selbsttest-Log
LOG_PATH = os.path.join(DATA_DIR, "teddy-manager.log")

DEBOUNCE_S = float(os.environ.get("DEBOUNCE_S", "5"))
MAX_TRACKS = 99  # Grenze von TeddyClouds /api/fileEncode
PURGE_AFTER_S = 7 * 24 * 3600
MODEL_PREFIX = "tm-"
TAF_HEADER = 4096

# Medientypen: key -> (Einzahl, Mehrzahl, Ordner). Erweiterbar (z. B. Podcast).
KINDS = {
    "lied": ("Lied", "Lieder", "lieder"),
    "geschichte": ("Geschichte", "Geschichten", "geschichten"),
    "podcast": ("Podcast", "Podcasts", "podcasts"),
}

def media_abs(path):
    """media.path ist relativ zur Library. Eigene Dateien liegen unter TM_SUB, übernommene TAFs bleiben,
    wo sie sind (werden nur gelesen, nie verändert oder gelöscht)."""
    return os.path.join(LIB_DIR, path)


def media_owned(path):
    return path.startswith(TM_SUB + "/")


AUDIO_EXT = {".opus", ".ogg", ".oga", ".mp3", ".m4a", ".m4b", ".aac", ".flac", ".wav", ".taf", ".webm", ".mp4"}
