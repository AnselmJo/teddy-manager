# Third-party notices

Teddy Manager itself is licensed under the GNU GPL v3.0. The bundled components below keep their own (GPL-compatible) licenses.

Bundled in `static/vendor/`:

| Component | Version | License |
|---|---|---|
| [Lucide](https://lucide.dev) icons (subset as SVG sprite `icons.svg`) | 1.57.0 | ISC |
| [SortableJS](https://github.com/SortableJS/Sortable) | 1.15.2 | MIT |
| [wavesurfer.js](https://wavesurfer.xyz) + regions plugin | 7.12.12 | BSD-3-Clause |

Installed at build/run time (not bundled): FastAPI, Uvicorn, python-multipart, HTTPX, Pillow (Python packages,
see `requirements.txt`), ffmpeg (Debian package), and – only when the optional link import is enabled –
yt-dlp, yt-dlp-ejs, Deno and ytmusicapi in a separate virtualenv.

TeddyCloud is a separate project and is not included.
