# Teddy Manager


Handy-Web-App fürs Heimnetz, mit der man **Custom-Tonies** (eigene Figuren mit NFC-Tag, z. B. gedruckte
Traveltonie-Münzen) über TeddyCloud mit Liedern, Geschichten und Radiosendern befüllt.

| Begriff | Bedeutung |
|---|---|
| **Original-Tonie** | gekaufte Figur mit festem Inhalt – wird nur angezeigt, nie verändert |
| **Kreativ-Tonie** | gekaufte Kreativ-Figur – wird nur angezeigt, nie verändert |
| **Custom-Tonie** | eigene Figur mit NFC-Tag – wird vom Teddy Manager verwaltet |

- **http://&lt;server&gt;:8090/** – im Heimnetz
- optional per HTTPS über einen Reverse-Proxy (siehe unten)

Sprache: Einstellungen → Sprache (Deutsch / English). Icons: Lucide (ISC-Lizenz), lokal in `static/vendor/icons.svg`.

---

## Bedienung

**Tonies** – Raster aller Custom-Tonies in ihrer Farbe. Ohne eigenes Bild zeigt jeder Tonie eine Münze
in seiner Farbe (auch in TeddyCloud).

- **Neu:** Figur auf eine Toniebox legen → „Erkannt“ → Name und Farbe → Speichern.
  Hat die Box unbekannte Figuren gesehen, erscheint oben „neue Figur(en) einrichten“; das Auge-Symbol daneben
  blendet sie aus (Archiv).
- **Detail:** Bild antippen = Bild wählen (eigene Bilder, Kamera, Cover der Titel, Tonie-Bilder aus tonies.json,
  Münze). Name im Feld ändern. Farbe: 12 Farben oder das Farbrad für jede andere Farbe.
- **Inhalt:** Playlist (Griff ziehen = sortieren, x = entfernen, „Titel hinzufügen“) oder Radio.
- **Aktionen:** Neu bauen · Archivieren · Löschen (mit Rückgängig) · **Mehr**: Mischen (die Box kann kein Shuffle),
  Tauschen, Kopieren auf anderen Tonie.
- **Box hat aktuellen Stand:** Im Tonie steht unter dem Status „Auf der Box: aktuell“, „alter Stand – Tonie einmal
  auflegen“ oder „Noch nicht auf der Box“. Grundlage ist die Meldung der Box beim Aufwachen (welche Audio-ID sie je
  Figur gespeichert hat) bzw. ihr Download nach dem Bauen.
- **Zuletzt aufgelegt:** Legt jemand eine Figur auf eine Box, erscheint oben „Gerade aufgelegt“ mit „Öffnen“
  (unbekannte Figuren: „Einrichten“). Einstellungen → Verlauf zeigt die letzten Aufleg-Ereignisse. Gelesen wird
  TeddyClouds Log über einen nur lesenden Docker-Socket-Proxy (Dienst `teddy-manager-logs`); eine Zuordnung zur
  einzelnen Box gibt das Log nicht her.
- **Kinderansicht** (Einstellungen → Kinderansicht): unten erscheint der Tab „Kinder“ mit großen Kacheln und einem
  großen Player mit Kapitel-Tasten. Verlassen: Schloss-Symbol – mit PIN (falls gesetzt), sonst 1,5 s gedrückt halten.
- **Weiterhören:** Bei längeren Inhalten (ab 10 min) merkt sich das Handy die Stelle; beim nächsten Abspielen geht es
  dort weiter („Von vorn“ im Hinweis setzt zurück).
- **Abspielen am Handy:** ▶ am Bild spielt den Tonie so, wie TeddyCloud ihn der Box liefert – mit Kapiteln (⏮ ⏭
  im Mini-Player) und spulbar. Auch Original- und Kreativ-Tonies (Original & Kreativ → ▶), sofern die Box ihren
  Inhalt schon geladen hat.
- **Gleich laut** (Standard: an) gleicht beim Bauen alle Titel an (EBU R128; bei Import-Titeln zweistufig mit
  gespeicherter Messung).
- **Einschlafmodus** (pro Tonie, nur Playlist): Der Tonie wird über die gewählte Dauer (15–90 min) gleichmäßig
  leiser bis zum Zielwert (0–60 %) und hört danach auf (blendet in den letzten 8 s aus). Ist die Playlist kürzer,
  wird sie bis zur Dauer wiederholt. Die Lautstärkekurve wird beim Bauen in die TAF gerechnet – die Box selbst
  kann so etwas nicht. Höchstens 99 Kapitel.
- **Unten auf der Startseite:** „Original & Kreativ“ (Liste der gekauften Figuren, einzeln per Auge-Symbol
  ausblenden) und „Archiv“ (archivierte Custom-Tonies und ausgeblendete Figuren). Im Archiv holt
  **„Zurückholen“** alles wieder zurück. Archivierte Custom-Tonies bleiben in TeddyCloud eingerichtet und spielen
  weiter – sie sind nur in der App ausgeblendet. Die Zeilen erscheinen nur, wenn es dort etwas gibt.

Änderungen an der Playlist (Titel, Reihenfolge, Gleich laut, Einschlafmodus) sind zunächst ein **Entwurf**: Die Box
spielt weiter den bisherigen Inhalt, bis man unten im Balken **„Auf Tonie laden“** tippt. Dann baut der Manager die TAF –
**ein Kapitel pro Titel bzw. pro Kapitel einer Geschichte** (Klopfen springt weiter). Radio, Name, Farbe und Bild gelten
sofort. Status: Entwurf · aktuell · baut · Fehler (mit „Nochmal“).

> **Box spielt noch den alten Inhalt?** Die Box lädt nur neu, wenn sich die Audio-ID ändert (jeder Build
> bekommt eine neue). Tonie neu auflegen; hilft das nicht, Box aus- und einschalten. TeddyCloud bietet keinen
> Befehl, der den Abgleich der Box gezielt auslöst.

**Bibliothek**

- **Hochladen** als Lied oder Geschichte (Opus, MP3, M4A/M4B, OGG, FLAC, WAV, TAF; mehrere auf einmal).
  Titel, Interpret, Dauer, Cover und **Kapitel** (M4B, TAF) werden gelesen; doppelte Dateien erkannt.
- **Mehrteilig** (nur bei „Geschichte“ sichtbar): Haken setzen, Namen eingeben, Dateien wählen → die Teile werden
  zu einer Geschichte gruppiert (Reihenfolge in der Gruppe per ≡ änderbar). Geschichten mit gleichem
  Album-Tag werden automatisch gruppiert.
- **Aus Tonies** (nur sichtbar, wenn es Inhalte gibt): Inhalte, die die Box von eigenen Original-/Kreativ-Tonies zwischengespeichert hat
  (TeddyCloud-Library `by/`), ganz oder **einzelne Kapitel** als Lied/Geschichte übernehmen. Es wird nichts
  kopiert – die Bibliothek verweist auf die Datei und schneidet erst beim Bauen.
- Zeile antippen = bearbeiten (Titel, Interpret, Gruppe, Typ, Bild, Schneiden, Auf Tonie legen).
  Mülleimer = löschen (Rückgängig). Die Zahl in der Zeile = auf wie vielen Tonies der Titel liegt; antippen zeigt sie
  und springt zum Tonie. In der Bearbeiten-Ansicht stehen sie als farbige Chips.
- Filter: Lieder · Geschichten · Podcasts (antippen = nur diese Art, nochmal = alle) und daneben im Suchfeld
  **Ungenutzt** (auf keinem Tonie). Titelregeln (siehe Import) gelten auch beim Hochladen.

**Hörspiele und Hörbücher**

- *Eine Datei mit Kapiteln* (M4B, TAF, MP3/M4A mit Kapitelmarken): als Geschichte hochladen – jedes Kapitel wird
  ein Kapitel auf der Box.
- *Viele Einzeldateien:* Geschichte → Mehrteilig → Name → alle Dateien auswählen. Sortiert wird nach Dateiname
  in natürlicher Reihenfolge (Teil 2 vor Teil 10); vorhandene Tracknummern-Tags werden bei automatischer
  Gruppierung genutzt. In der Gruppe: per Griff umsortieren oder „Nach Name sortieren“.
- *YouTube Music:* Album- oder Playlist-Link teilen → unter Neu „Als Geschichte“ bestätigen → alle Titel landen in
  Playlist-Reihenfolge als Teile einer Geschichte (ohne Song-Versions-Suche). Ein einzelnes langes Video mit
  Kapiteln: „Als Kapitel nutzen“ (Kapitel auf der Box) oder „In Titel aufteilen“.
- Grenze: 99 Kapitel pro Tonie.
- Bilder löschen: Bild-Auswahl → Meine → Bearbeiten → Bild antippen.
- **Schneiden** (nicht-destruktiv): Wellenform mit Schnittbereichen (orange = SponsorBlock, grau = Stille,
  rot = manuell). Auf der Wellenform ziehen = neuer Bereich; Bereich antippen und „Bereich weg“; „Anfang bis hier
  weg“ / „Ab hier weg“ an der Abspielposition; Vorhören überspringt die Bereiche; „Zurücksetzen“ stellt die
  automatischen Vorschläge wieder her. Das Original bleibt unverändert.
- **Mini-Player:** Beim Abspielen erscheint über den Tabs eine Leiste mit Pause und Schieberegler zum Springen.
- **In YouTube Music suchen** (Lupe neben dem Linkfeld, nur mit eingeschaltetem Import): Songs, Alben, Videos;
  jeder Treffer lässt sich vorhören (spulbar, ohne Download) und mit dem Pfeil laden. Alben: „Als Geschichte“ oder
  „Als Lieder“. Hörspiel-Alben großer Labels gibt YouTube Music nur mit Premium-Anmeldung heraus – sie werden als
  nicht ladbar angezeigt.
- **Abspielen** in der Bibliothek spielt die **geschnittene** Fassung – so, wie sie auf den Tonie kommt (Hörprobe
  wird nach Import bzw. Speichern der Schnitte im Hintergrund vorbereitet und in `cache/preview/` abgelegt). Der
  Trimmer zeigt immer das Original. Auf den Tonie kommt die Schnittfassung beim Bauen.

**Radio** – oben umschalten zwischen **Sender** und **Podcasts**.
Sender anlegen (Name, Stream-URL, Logo), „Testen“ prüft den Stream auf dem Server.

**Podcasts:** „Podcast abonnieren“ → suchen (iTunes-Podcast-Verzeichnis) oder RSS-Adresse einfügen → optional
einen Tonie wählen, Anzahl neuester Folgen (3/5/10/20), Reihenfolge. Folgen werden geladen
(`media/podcasts/<podcast>/`), erscheinen in der Bibliothek unter „Podcasts“ (gruppiert) und – wenn ein Tonie
gewählt ist – automatisch als dessen Playlist. Prüfung alle 3 Stunden; ältere Folgen, die aus dem Fenster fallen
und auf keinem anderen Tonie liegen, wandern in den Papierkorb. Abo beenden lässt Folgen und Tonie-Inhalt stehen.
Vorinstalliert (Kleinkinder 1–3 Jahre, getestet 2026-10-29):

| Sender | Art |
|---|---|
| WDR Die Maus | Kinderradio mit Liedern, Geschichten |
| Radio Teddy – Kinderlieder | Kinderlieder |
| Radio Teddy – Gute Nacht | ruhige Einschlafmusik |
| Radio Teddy – Rolf Zuckowski | Zuckowski-Lieder |
| Radio Teddy – Kita Kabelsalat | Kita-Lieder |
| RPR1. Kinderlieder | Kinderlieder |
| Regenbogen Kinderlieder | Kinderlieder |
| laut.fm Kinderlieder | Kinderlieder |
| Naturmacher Radio | ruhige Familien-/Folkmusik |

**Einstellungen** (Zahnrad oben rechts) – eine Liste, jede Zeile führt auf eine eigene Seite: Sprache (DE/EN direkt
in der Zeile) · **Tonieboxen** (jede Box aufklappbar) · **Import per Link** (An/Aus, darunter aufklappbare
Abschnitte) · **TeddyCloud** (Status/Version, Alles abgleichen, TeddyCloud öffnen) · **PIN** · **Speicher**
(Belegung, Backup laden) · Hilfe.

**Tonieboxen** (pro Box): Name, maximale Lautstärke Lautsprecher und Kopfhörer (25/50/75/100 %), Klopfen an/aus,
Klopfrichtung („Links klopfen: zurück/vor“), Licht (an/gedimmt/aus). Gesetzt über TeddyClouds Einstellungs-API
(`/api/settings/set/toniebox.*?overlay=<Box-ID>`); die Box übernimmt sie beim nächsten Verbinden (Box kurz aus
und an).
**Abendmodus** (pro Box): Uhrzeit von/bis (auch über Mitternacht), eigene maximale Lautstärke und Licht. Der
Manager setzt zur Uhrzeit die Abendwerte und morgens wieder die Tageswerte; die Box übernimmt sie beim nächsten
Einschalten/Aufwachen (TeddyCloud kann sie nicht live an die Box schicken). Tageswerte, die abends geändert
werden, werden gemerkt und morgens gesetzt. Einen **Akkustand** liefert TeddyCloud nicht (käme nur über RTNL, das die Boxen hier nicht senden).

---

## Import per Link (YouTube / YouTube Music)

> **Rechtlicher Hinweis:** Downloads von YouTube verstoßen gegen dessen Nutzungsbedingungen und sind rechtlich
> nicht eindeutig. Nutzung auf eigenes Risiko, nur privat, nichts weitergeben. Kein Spotify, kein Umgehen von DRM.
> Das Modul ist standardmäßig **aus**; beim Einschalten erscheint dieser Hinweis. Ist es aus, lehnt
> `/api/import` mit „Import ist ausgeschaltet“ ab.

**Ablauf:** „Teilen → Zum Tonie“ am Handy (App *HTTP Shortcuts*) oder Link in der Bibliothek einfügen →
Job in der Queue → yt-dlp lädt die beste Audiospur (`251/bestaudio`, ohne Neukodierung) →
automatische Aufbereitung → Titel erscheint in **Bibliothek → Neu**. Dort: Schneiden, Auf Tonie legen, Erledigt.

Automatisch (alles als Schnittbereiche, nichts wird am Original verändert):

- **Song-Version:** Bei offiziellen Musikvideos sucht der Manager in YouTube Music die reine Audio-Version
  (gleicher Titel, passender Interpret, plausible Dauer) und lädt diese – ohne Video-Intro/Outro, mit
  quadratischem Album-Cover. Umschaltbar im Titel („Wechseln zu Musikvideo/Song-Version“), abschaltbar in den
  Einstellungen.
- **SponsorBlock:** Segmente der Kategorien music_offtopic, intro, outro, sponsor, selfpromo, interaction,
  preview (Standard; *filler* aus, weil es bei Geschichten echten Inhalt treffen kann). Später „SponsorBlock neu
  abrufen“.
- **Stille** am Anfang/Ende (−50 dB, ≥ 0,5 s).
- **Lautheit** wird beim Import gemessen und beim Bauen zweistufig angeglichen.
- **Metadaten:** Titel bereinigt („(Official Video)“, „[HD]“, „| … zum Mitsingen“, Emojis am Anfang …) über
  eine editierbare Regelliste; Interpret ohne „ - Topic“ / Kanalzusatz.
- **Kapitel:** Videos mit Kapiteln (z. B. Medleys) lassen sich per „In Kapitel aufteilen“ in einzelne Titel
  zerlegen – alle verweisen auf dasselbe Original.
- **Playlists/Alben** (`list=…`, `music.youtube.com/browse/…`): erscheinen unter „Neu“ zur Bestätigung
  („23 importieren“), Obergrenze einstellbar (Standard 50).
- Abgelehnt mit klarer Meldung: Livestreams, Premieren, länger als die Grenze (Standard 3 h), Duplikate
  (Video-ID schon in der Bibliothek).

**Queue:** persistent in SQLite (übersteht Neustarts), genau ein Download gleichzeitig, 5–10 s Pause zwischen
Downloads, bei Fehlern bis zu 3 Wiederholungen (nach 1, 5, 15 min).

**yt-dlp-Umgebung:** `data/ytdlp/envs/<datum>/` (venv mit `yt-dlp[default,deno]` – also passender
`yt-dlp-ejs`-Version und Deno als JavaScript-Runtime – sowie `ytmusicapi`), aktiv über den Link
`data/ytdlp/current`. **Täglich** wird eine neue Umgebung daneben gebaut und mit einem kurzen Testvideo geprüft
(Einstellung „Testvideo“, Standard `jNQXAC9IVRw`, 19 s). Nur wenn der Selbsttest klappt, wird umgeschaltet; sonst
bleibt die bisherige aktiv und die Einstellungen zeigen „Update fehlgeschlagen – vorherige Version bleibt
aktiv“. „Vorherige Version“ schaltet manuell zurück. Log: `data/ytdlp/selftest.log`.

### Handy einrichten (HTTP Shortcuts)

Die Anleitung steht auch in der App unter Einstellungen → Import per Link → Hilfe.

1. App **HTTP Shortcuts** installieren (Play Store oder F-Droid).
2. Im Teddy Manager: Einstellungen → Import per Link → **Shortcut-Datei laden** (`zum-tonie.json`, enthält den Token).
3. In HTTP Shortcuts: Menü → Import / Export → Aus Datei importieren → `zum-tonie.json`.
4. Testen: in YouTube Music Teilen → HTTP Shortcuts → **Zum Tonie** → Toast „Import gestartet“.

Manuell: globale Variable `geteilter_text` (Typ Text, „Wert aus dem Teilen-Dialog übernehmen“); Shortcut POST an
`http://<server>:8090/api/import`, Header `X-Teddy-Token: <Token>`, Body = eigener Text (text/plain) mit der
Variable, Antwort als Toast. Die API akzeptiert auch JSON `{"text": "…"}`. Sie antwortet immer mit einer kurzen
Textzeile („Import gestartet“, „Fehler: Kein YouTube-Link erkannt“, „Schon in der Bibliothek: …“).
Neuer Token in den Einstellungen → Shortcut-Datei neu laden.

**Warum nicht das PWA-Teilen-Ziel?** Android zeigt eine PWA nur im Teilen-Menü, wenn sie als WebAPK installiert
ist; das scheitert an einer LAN-IP mit eigenem Zertifikat. Dafür bräuchte es eine eigene Domain mit
Let's-Encrypt-Zertifikat (DNS-Challenge), einen lokalen DNS-Eintrag auf die Server-IP und in der FritzBox
eine DNS-Rebind-Ausnahme für die Domain. Nicht umgesetzt.

### Einstellungen des Imports
Modul an/aus · Token (anzeigen, neu erzeugen) · Shortcut-Datei · SponsorBlock-Kategorien · Song-Version
bevorzugen · max. Länge · max. Titel pro Playlist · Titelregeln · optionale `cookies.txt` (Rechte 600, nur bei
Altersbeschränkung oder Bot-Schutz; Zweit-Account verwenden) · yt-dlp-Version/-Status · Jetzt aktualisieren ·
Vorherige Version · Testvideo.

### Fehlersuche Import

| Meldung | Bedeutung / Lösung |
|---|---|
| Video nicht verfügbar | privat, gelöscht oder gesperrt |
| Altersbeschränkt – Cookies nötig | `cookies.txt` eines (Zweit-)Accounts hochladen |
| YouTube verlangt eine Anmeldung (Bot-Schutz) | später erneut; sonst `cookies.txt`. Weiterer Ausweg (nicht aktiviert): PO-Token-Provider-Plugin für yt-dlp in die venv installieren (`data/ytdlp/current/bin/pip install …`) |
| YouTube hat etwas geändert – Update läuft | das tägliche Update wird sofort angestoßen; der Job wiederholt sich automatisch |
| Livestream / Premiere | nicht unterstützt |
| Import ist ausgeschaltet | Einstellungen → Import per Link → An |

Details: `docker logs teddy-manager`, `data/ytdlp/selftest.log`.

Grenze: höchstens 99 Kapitel pro Tonie (TeddyCloud).

---

## Wie es funktioniert

```
Handy ──HTTP(S)──▶ teddy-manager (FastAPI, :8090 / Caddy :8445) ──HTTP──▶ teddycloud:80 (API, Netzwerk teddynet)
                     │  SQLite = Sollzustand
                     └─ schreibt nur in library/_teddy-manager/ und custom_img/teddy-manager/
```

Bauen (eine Queue, genau ein Worker, Änderungen werden entprellt):

1. Jede Einheit (ganze Datei, Kapitel oder Ausschnitt) wird bei Bedarf geschnitten und/oder lautheitsangeglichen
   → `library/_teddy-manager/cache/units/*.flac` (wiederverwendet, nach 30 Tagen ohne Zugriff gelöscht).
2. `POST /api/fileEncode` – TeddyClouds eigener Encoder baut eine TAF mit einem Kapitel pro Einheit und einer
   neuen Audio-ID in eine **temporäre Datei**.
3. Prüfen über `/api/fileIndexV2` (Header gültig, Kapitelzahl stimmt), dann **atomar umbenennen**.
   Bis dahin bleibt die alte TAF aktiv.
4. `POST /content/json/set/<ruid>` (source, tonie_model `tm-<UID>`), `POST /api/toniesCustomJsonUpsert`
   (Titel, Bild, Kapitelnamen), `GET /api/toniesJsonReload`. Alte TAF löschen.

Radio: `source` = Stream-URL; TeddyCloud setzt `live`/`nocloud` und kodiert live mit ffmpeg.

Der Abgleich ist idempotent: beim Start, stündlich und über „↻ Alles abgleichen“; gebaut wird nur, wenn sich
der Inhalt geändert hat oder die TAF fehlt.

**Anlernen:** Die Boxen senden keine RTNL-Ereignisse an TeddyCloud, ein Live-Ereignis „Tag aufgelegt“ gibt es
daher nicht. Eine **neue** Figur fragt aber immer bei TeddyCloud nach und erscheint dadurch in
`/api/getTagIndex` – darauf wartet die App. Bekannte Figuren wählt man im Raster aus.

---

## Ordner

Auf dem Server (neben TeddyCloud):

```
teddy-manager/                      Code, Dockerfile, docker-compose.yml, update.sh
teddy-manager/data/db.sqlite        Zustand (Quelle der Wahrheit)
teddy-manager/data/backups/         tägliche DB-Sicherung, 14 Tage
teddy-manager/data/ytdlp/           yt-dlp-Umgebungen (envs/, current, previous), cookies.txt, selftest.log
teddy-manager/data/teddy-manager.log
teddycloud/data/library/_teddy-manager/
    media/lieder/, media/geschichten/   hochgeladene Originale (unverändert)
    media/originals/youtube/<id>.<ext>  per Link geladene Audiospuren (unverändert)
    build/<uid4>-<slug>.taf             gebaute TAFs, eine pro Tonie (jederzeit reproduzierbar)
    cache/units/                        geschnittene/angeglichene Zwischendateien (darf gelöscht werden)
teddycloud/data/custom_img/teddy-manager/   Bilder (512 px WebP) und Münzbilder coin2-<farbe>.webp
```

Der Ordner beginnt mit `_`, damit andere Library-Scanner (z. B. teddycloud-companion) ihn überspringen.

**Keine doppelten Lieder:** TAFs, die schon in der TeddyCloud-Library liegen (Hauptordner, `by/`), werden nicht
kopiert. Die Bibliothek verweist auf sie, liest sie nur und löscht oder verändert sie nie.

Gelöschte Titel, Bilder, Sender und Tonies landen zunächst im Papierkorb (↶ Rückgängig) und werden nach
7 Tagen endgültig entfernt (eigene Dateien; übernommene Dateien bleiben unangetastet).

---

## Backup und Wiederherstellen

Automatisch: täglich `data/backups/db-YYYYMMDD.sqlite`. Manuell: ⚙ → ⬇ Backup laden.

Komplettsicherung (DB + eigene Medien + Bilder):

```bash
tar czf teddy-manager-$(date +%F).tgz data ../teddycloud/data/library/_teddy-manager/media ../teddycloud/data/custom_img/teddy-manager
```

Wiederherstellen:

```bash
docker compose stop
cp data/backups/db-YYYYMMDD.sqlite data/db.sqlite
docker compose start
```

Danach ⚙ → ↻ Alles abgleichen: fehlende TAFs werden neu gebaut, Quellen und Anzeige in TeddyCloud
wiederhergestellt.

---

## Update

```bash
./update.sh
```

Das Skript sichert die DB, merkt sich das laufende Image als `teddy-manager:previous`, baut neu, startet und
prüft `/api/health`. Startet die neue Version nicht, geht es automatisch zurück zur vorherigen.
Hat das Verzeichnis ein Git-Remote, holt es vorher den neuesten Stand (`git pull`); sonst wird der vorhandene
Code gebaut (z. B. nach `rsync` vom Rechner). Datenbank-Änderungen migrieren beim Start automatisch.

Der Container startet nach einem Neustart des Servers automatisch (`restart: unless-stopped`) und hat einen Healthcheck.

### TeddyCloud-Updates
Getestet mit **TeddyCloud v0.7.0 (439225a)**; ⚙ zeigt die laufende Version und warnt bei einer anderen.
Genutzt werden nur diese Schnittstellen (alle auch von der TeddyCloud-Weboberfläche verwendet):
`/api/getTagIndex`, `/api/getTagInfo`, `/content/json/set/<ruid>`, `/api/fileEncode`, `/api/fileIndexV2`,
`/api/toniesCustomJsonUpsert`, `/api/toniesCustomJsonDelete`, `/api/toniesJsonReload`,
`/api/settings/get/internal.version.id`. Nach einem TeddyCloud-Update einen Tonie ↻ neu bauen und prüfen.

Hinweis: TeddyCloud läuft mit dem Image-Tag `:latest` und kann sich daher bei jedem `docker compose pull`
ändern. Wer das vermeiden will, setzt in TeddyClouds `docker-compose.yaml` eine feste Version.

Bekannt: TeddyCloud lehnt doppelte `audio_id`+`hash`-Paare in `tonies.custom.json` ab. Hat ein fremder Eintrag
dieselbe TAF, speichert der Teddy Manager seinen Eintrag ohne audio_id/hash (Verknüpfung über `tonie_model`).

---

## Fehlersuche

| Problem | Lösung |
|---|---|
| App nicht erreichbar | `docker ps` – läuft `teddy-manager`? `docker logs teddy-manager` |
| ⚠️ „TeddyCloud nicht erreichbar“ | TeddyCloud-Container prüfen; die App versucht es jede Minute erneut |
| Box spielt alten Inhalt | Tonie neu auflegen, sonst Box aus/an |
| Neue Figur wird nicht erkannt | Box muss mit TeddyCloud verbunden sein; Figur 5 s liegen lassen. Sonst erscheint sie danach unter „👀 Schon gesehen“ |
| „🧸 Aus Tonies“ ist leer | Eigenen Original-Tonie einmal auf die Box legen und komplett laden lassen |
| Tonie-Bilder/Cover laden nicht | Dafür ist Internet nötig (Bilder liegen im Tonies-CDN); gewählte Bilder sind danach lokal |
| HTTPS-Warnung am Handy | Root-Zertifikat des Reverse-Proxys auf dem Handy installieren |
| Upload „Datei nicht lesbar“ | Format prüfen; Details in `data/teddy-manager.log` |

Logs: `docker logs -f teddy-manager` oder `data/teddy-manager.log`.

Übersetzungen: `static/i18n.js` (Deutsch, Englisch). Meldungen, die vom Server kommen (z. B. Fehlertexte von
TeddyCloud), sind noch deutsch.

---

## HTTPS (optional)

Für „Als App installieren“ verlangt Android HTTPS. Beispiel für einen Caddy-Reverse-Proxy im selben Docker-Netz:

```
https://<server-ip>:8445 {
	tls internal
	reverse_proxy teddy-manager:8000
}
```

Das Handy muss dem Root-Zertifikat von Caddy vertrauen. Das Teilen-Ziel der PWA funktioniert mit einer LAN-IP trotzdem
meist nicht (siehe „Warum nicht das PWA-Teilen-Ziel?“) – dafür gibt es den Weg über HTTP Shortcuts.

