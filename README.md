# Teddy Manager

Teddy Manager is a simple, phone-first web app for your home network that fills **custom Tonies** – your own NFC tags or 3D-printed
figures – with songs, stories, radio stations and podcasts through [TeddyCloud](https://github.com/toniebox-reverse-engineering/teddycloud).

You arrange content on your phone; the manager builds a proper TAF file with one chapter per track (tap the box to
skip), assigns it in TeddyCloud and keeps everything in sync.

> Deutsche Anleitung: [README.de.md](README.de.md)

> **Not affiliated with Boxine GmbH / tonies®.** “Tonie” and “Toniebox” are trademarks of Boxine GmbH. This is an
> independent hobby project for use with your own boxes, your own tags and your own audio files.

## Features

- **Custom Tonies** – learn new tags by placing them on a box, give them a name, colour and picture (a coin-style
  default image is generated in the tonie's colour). Original and Creative Tonies are only listed, never changed.
- **Playlists** – drag & drop order, shuffle, swap or copy content between tonies, even volume (EBU R128).
  Changes are kept as a **draft** until you tap “Load onto Tonie”.
- **Box up to date?** – shows whether a box already has the current version of a tonie (from the box's own report
  when it wakes up) or still plays the old one.
- **Last placed** – the app notices when a figure is put on a box (read from TeddyCloud's log through a read-only
  Docker socket proxy) and offers to open it; a history shows recent placements.
- **Kids view** (optional, own tab) – big tiles and a big player on the phone; leaving it needs the PIN.
- **Play on the phone** – play any custom tonie (and original/Creative Tonies whose content the box has cached) with
  chapter skipping and a seekable mini player; see on which tonies a track is used and jump there.
- **Sleep mode** – a tonie gets quieter over 15–90 minutes and then stops (repeats the playlist if needed).
  The volume curve is rendered into the audio, since the box can't do this itself.
- **Library** – upload songs and stories (Opus, MP3, M4A/M4B, FLAC, WAV, TAF), multi-part stories with natural
  sorting, chapter detection, duplicate detection, cover art, unused filter, waveform trimmer.
- **Radio** – internet radio stations as tonie content (TeddyCloud streams them live).
- **Podcasts** – subscribe via search or RSS; the newest episodes can fill a tonie automatically.
- **Toniebox settings** – max volume (speaker/headphones), tap-to-skip and direction, LED, plus an **evening mode**
  schedule per box.
- **Import by link (optional, off by default)** – share a YouTube / YouTube Music link from your phone (via the
  *HTTP Shortcuts* app) or search YouTube Music inside the app with a seekable preview. Picks the clean song version
  of music videos, removes SponsorBlock segments and silence non-destructively. See the legal note below.
- **Robust** – one build queue, atomic TAF builds (old content stays until the new one is verified), idempotent sync
  (“sync everything” restores the desired state), daily database backups, automatic rollback on failed updates.
- German and English UI, light and dark mode, installable PWA, optional 4-digit PIN.

## Requirements

- A running **TeddyCloud** (tested with **v0.7.0**) in Docker, with its web API reachable from the manager's
  container (same Docker network).
- Access to TeddyCloud's data folders `library/`, `custom_img/` and `config/` (bind mounts).
- Docker with Compose. Runs fine on a Raspberry Pi 4.

## Installation

```bash
git clone https://github.com/AnselmJo/teddy-manager.git
cd teddy-manager
cp .env.example .env        # adjust TEDDYCLOUD_DATA, TEDDYCLOUD_NETWORK, PUBLIC_URL, PORT
docker compose up -d --build
```

Prefer a ready-made image (amd64 + arm64)? Set `IMAGE=ghcr.io/anselmjo/teddy-manager:latest` in `.env` and run
`docker compose pull && docker compose up -d` instead of building.

Open `http://<server>:8090/`.

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `8090` | Port in your home network |
| `PUBLIC_URL` | – | Address your phone uses (written into the HTTP Shortcuts file) |
| `TEDDYCLOUD_DATA` | `../teddycloud/data` | Folder containing TeddyCloud's `library/`, `custom_img/`, `config/` |
| `TEDDYCLOUD_NETWORK` | `teddynet` | External Docker network TeddyCloud is attached to |
| `TC_URL` | `http://teddycloud:80` | TeddyCloud web API as seen from the container |
| `TEDDYCLOUD_CONTAINER` | `teddycloud` | Container name, used to read its log for “last placed” |
| `TC_LOG_URL` | (proxy URL) | Set to empty to disable log reading (then also remove the `teddy-manager-logs` service) |
| `IMAGE` | – | Use a published image instead of building locally |
| `TM_FOLDER` / `IMG_FOLDER` | `_teddy-manager` / `teddy-manager` | Own folders inside TeddyCloud's `library/` and `custom_img/` |
| `UPDATE_REPO` | – | `owner/repo` – shows a notice in the settings when a newer release exists |

**About the Docker socket proxy:** “last placed” needs TeddyCloud's log. The compose file adds
`tecnativa/docker-socket-proxy` with read-only container access (`CONTAINERS=1`, `POST=0`) on an internal network that
only the manager can reach. If you don't want that, remove the service and set `TC_LOG_URL=`.

If TeddyCloud uses **named volumes** instead of bind mounts, mount the same volumes into the manager
(`library` → `/library`, `custom_img` → `/custom_img`, `config` → `/tc-config:ro`) in a `docker-compose.override.yml`.

The manager only writes to `library/_teddy-manager/` and `custom_img/teddy-manager/`; it changes TeddyCloud content
records and `tonies.custom.json` only for the tags you set up as custom tonies. Don't let another tool (e.g. a sync
script) manage the same tags at the same time – they would overwrite each other.

**Migrating existing tags** (optional): tags whose UID starts with a given prefix and already point to a single TAF
can be adopted without re-encoding:

```bash
docker exec teddy-manager python -m app.importer --prefix E0040350ABCD --dry-run
```

**HTTPS** (needed to install the PWA on Android) works through any reverse proxy, e.g. Caddy with `tls internal`.

## How it works

```
Phone ──HTTP──▶ teddy-manager (FastAPI + SQLite) ──HTTP──▶ TeddyCloud web API
                    └── writes TAFs to library/_teddy-manager/build/
```

1. Units (whole file, chapter or clip) are cut / loudness-normalised with ffmpeg into a cache.
2. `POST /api/fileEncode` – TeddyCloud's own encoder builds the TAF (one chapter per unit, new audio ID) into a
   temporary file, which is verified via `/api/fileIndexV2` and then atomically renamed.
3. `POST /content/json/set/<ruid>` sets the source, `POST /api/toniesCustomJsonUpsert` the title, picture and track
   list, `GET /api/toniesJsonReload` reloads.

TeddyCloud endpoints used: `getTagIndex`, `getTagInfo`, `content/json/set`, `fileEncode`, `fileIndexV2`,
`toniesCustomJsonUpsert/Delete`, `toniesJsonReload`, `settings/get|set` (per-box overlay), `getBoxes`.

Known limits: the box only fetches new content when the audio ID changes (every build creates a new one); box
settings are applied when the box next wakes up; max. 99 chapters per tonie. No battery level (TeddyCloud doesn't expose it without RTNL).

## Import by link – legal note

Downloading from YouTube violates YouTube's terms of service and may not be legal where you live. The module is
**disabled by default** and shows this notice when enabled. Use it only for private purposes, at your own risk, and
don't redistribute anything. There is no support for DRM-protected services (e.g. Spotify), and content that YouTube
Music only serves to Premium subscribers (many audio-drama labels) can't be loaded.

yt-dlp (with matching yt-dlp-ejs and Deno) and ytmusicapi run in a separate virtualenv under `data/ytdlp/`, are updated
daily and only switched over after a self-test succeeds.

## Versioning

The version lives in [`VERSION`](VERSION) and follows [Semantic Versioning](https://semver.org). Changes are listed in
[CHANGELOG.md](CHANGELOG.md); a tag `vX.Y.Z` builds the release image.

## Updating, backup

```bash
./update.sh            # git pull (if cloned), backup DB, build or pull the image, start, health check, roll back on failure
```

With `UPDATE_REPO` set, the settings page shows when a newer release is available. Releases are built by
`.github/workflows/release.yml` when you push a tag like `v0.1.0`.

Daily database backups are stored in `data/backups/`; the settings page also offers a download.

## Development

Plain Python (FastAPI) and vanilla JavaScript – no frontend build step. Tests: `pip install -r requirements-dev.txt && pytest`.
See [CONTRIBUTING.md](CONTRIBUTING.md).


## TeddyCloud wishlist

Issues and ideas we found while building on TeddyCloud's API are collected in
[docs/teddycloud-requests.md](docs/teddycloud-requests.md).

## License

[GNU GPL v3.0](LICENSE). Bundled third-party assets (MIT, ISC, BSD-3-Clause – all GPL-compatible) are listed in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
