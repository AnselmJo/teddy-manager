"""Testumgebung: eigene, leere Datenordner – die App-Module lesen Pfade beim Import aus der Umgebung."""
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="tm-test-")
for key, sub in (("DATA_DIR", "data"), ("LIB_DIR", "library"), ("IMG_DIR", "img/teddy-manager"), ("TC_CONFIG_DIR", "config")):
    os.environ.setdefault(key, os.path.join(_tmp, sub))
    os.makedirs(os.environ[key], exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import db  # noqa: E402

db.init()
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
