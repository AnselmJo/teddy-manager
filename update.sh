#!/bin/sh
# Teddy Manager aktualisieren: Sicherung -> neues Image bauen -> starten -> Healthcheck -> bei Fehler zurück.
# Aufruf auf dem Server:  ./update.sh  (im Projektordner)
# Hat das Verzeichnis ein Git-Remote, wird vorher "git pull" ausgeführt; sonst wird der vorhandene Code gebaut
# (z. B. nach rsync vom Rechner).
set -eu
cd "$(dirname "$0")"

say() { printf '\n== %s\n' "$*"; }
PORT=$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)
PORT=${PORT:-8090}

if [ -d .git ] && git remote | grep -q .; then
  say "Code holen"
  git pull --ff-only
fi

say "Sicherung der Datenbank"
mkdir -p data/backups
if [ -f data/db.sqlite ]; then
  # läuft der Container, sichert die App selbst (konsistent); sonst Kopie über einen kurzen Hilfscontainer (Dateien gehören root)
  docker exec teddy-manager python -c "from app import db; print(db.backup())" 2>/dev/null \
    || docker run --rm -v "$PWD/data:/d" alpine:3.20 cp /d/db.sqlite "/d/backups/db-before-update-$(date +%Y%m%d-%H%M%S).sqlite" \
    || echo "Warnung: keine Sicherung möglich"
fi

say "Bisheriges Image als Rückfall merken"
docker image tag teddy-manager:latest teddy-manager:previous 2>/dev/null || true

if grep -qE '^IMAGE=.+/' .env 2>/dev/null; then
  say "Neues Image laden"
  docker compose pull
else
  say "Neues Image bauen"
  docker compose build
fi

say "Starten"
docker compose up -d

say "Healthcheck"
i=0
while [ $i -lt 30 ]; do
  if curl -fsS http://127.0.0.1:$PORT/api/health >/dev/null 2>&1; then
    curl -fsS http://127.0.0.1:$PORT/api/health; echo
    say "Fertig."
    exit 0
  fi
  i=$((i + 1)); sleep 2
done

say "Neue Version startet nicht – zurück zur vorherigen"
docker logs --tail 40 teddy-manager || true
docker image tag teddy-manager:previous teddy-manager:latest
docker compose up -d --no-build
exit 1
