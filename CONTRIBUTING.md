# Contributing

Thanks for your interest in Teddy Manager! Keep it simple – the app is meant to stay small, robust and easy to use on a phone.

- Backend: Python 3.12, FastAPI, SQLite (`app/`). Frontend: vanilla JS without a build step (`static/`).
- UI texts live in `static/i18n.js` (German and English) – add both when you add a string.
- Icons come from the Lucide sprite in `static/vendor/icons.svg`; please no emoji in the UI.
- Run a quick check before opening a pull request:

  ```bash
  python -m py_compile app/*.py
  node -e "new Function(require('fs').readFileSync('static/i18n.js','utf8')+require('fs').readFileSync('static/app.js','utf8'))"
  ```

- Only use TeddyCloud's HTTP API or the manager's own folders – never edit TeddyCloud files directly.
- Please don't add features that help copy content you don't own or that circumvent DRM.
