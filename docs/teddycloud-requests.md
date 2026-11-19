# Feature requests and bug reports for TeddyCloud

Collected while building Teddy Manager against **TeddyCloud v0.7.0 (439225a)** with two ESP32 boxes
(firmware `eu/v5.237.0`, CFW patched). Each section is written so it can be pasted into a GitHub issue at
<https://github.com/toniebox-reverse-engineering/teddycloud/issues>.

---

## Bug: `POST /api/settings/set/<key>` returns an empty body (`Content-Length: 0`)

`handleApiSettingsSet` builds `"OK"`/`"ERROR"` in `response`, but calls
`httpPrepareHeader(connection, "text/plain; charset=utf-8", 0)` before `httpWriteResponseString(...)`.
The client therefore always receives an empty body and cannot tell success from failure.

**Steps:** `curl -i -X POST 'http://teddycloud/api/settings/set/toniebox.max_vol_spk?overlay=<BOXID>' --data-binary 3`
→ `200`, `Content-Length: 0`, no body. The setting *is* applied (see log `Setting: 'toniebox.max_vol_spk' to '3'`).

**Expected:** `Content-Length` matching the body (`OK` or `ERROR`), ideally a non-2xx status on failure.
The same pattern may exist in other handlers (worth a grep for `httpPrepareHeader(..., 0)` followed by a body write).

---

## Feature: expose "tag placed" events without RTNL

Without RTNL, `internal.last_ruid` stays `ffffffffffffffff` and no SSE/MQTT `TagValid` event is sent. However, the box
sends a cloud *claim* (`handleCloudClaim … client claim requested rUID …`) on nearly every placement, and a content
request when content is missing. Today the only way to use this is parsing container logs.

**Proposal:** update `last_ruid`/`last_ruid_time` per box overlay and emit an SSE + MQTT event (e.g. `TagPlaced`
with `ruid`, `box`, `source: claim|content|rtnl`) from `handleCloudClaim` / `getTonieInfoForRequest`.
Please include the **box id** (client certificate CN), which is not visible in the log lines today.

---

## Feature: battery level and box status via API

The web UI and API offer no battery level, charging state, online state or "last contact" per box (only via RTNL
or MQTT for TB2). Proposal: `GET /api/boxes/<id>/state` with `online`, `lastSeen`, `lastRuid`, `battery`
(if known), `charger`, `firmware`, `volume` – filled from whatever source is available (RTNL, freshness check,
claim, MQTT).

---

## Feature: which content does a box have cached? (offline / travel check)

`process_freshness_check` logs the box's cached tags with their audio IDs (`uid: …, audioid: …`), and
`Setting freshnessCache with N entries` – but this is not available via the API. Proposal:
`GET /api/boxes/<id>/freshness` returning the last reported list (`ruid`, `audioId`, `time`). Apps could then show
"box has the current version" vs. "re-place the figure / reconnect the box".

---

## Feature: apply box settings without waiting for the next freshness check

Settings like `toniebox.max_vol_spk`, `led`, `slap_*` reach the box only with the next freshness check, which
happens on wake/power-on. Is there a way (e.g. a flag in the next response, or a documented trigger) to make the box
pick up changes sooner? If not possible, a short note in the settings UI would help users.

---

## Feature: asynchronous encoding with progress for `POST /api/fileEncode`

`/api/fileEncode` blocks until the TAF is written (minutes for long audio) and gives no progress.
Proposal: optional `async=true` returning a job id, plus `GET /api/encodeJobs/<id>` with `progress` (seconds encoded,
current source), and a way to cancel. Optional per-source parameters (`start`, `end`, `gain`, loudness
normalisation) would remove the need for pre-processing in third-party tools.

---

## Feature: `toniesCustomJsonUpsert` – allow the same `audio_id`+`hash` for several models

Upserting a custom entry fails with `Duplicate audio_id+hash pair detected` if *any* other entry (even from another
tool) references the same TAF. This is common when one TAF is used by several figures. Proposal: allow duplicates
(warn instead of reject), or resolve per `model` first.

---

## Feature: documented HTTP API (OpenAPI) and optional API token

The API on the plain HTTP port is unauthenticated. For home use this is fine, but a documented API (OpenAPI/
Markdown) and an **optional token** (header) for write endpoints would make third-party tools safer.

---

## Feature: read the server log via the API

Third-party tools currently need Docker socket access to read TeddyCloud's log (for placement events, freshness
reports, errors). A small `GET /api/logs?since=<ts>&filter=…` (or an SSE log stream) would avoid that entirely.

---

## Feature: chapter names in `getTagInfo` for library TAFs

`trackSeconds` is returned, but chapter names only exist if `tonies.json` / `tonies.custom.json` lists `tracks`.
Fine as is – but documenting that `tracks` in `tonies.custom.json` maps 1:1 to TAF chapters would help.

---

## Release / packaging

- Versioned Docker tags in addition to `:latest` (e.g. `:v0.7.0`) are available – it would help to document
  pinning in the compose example, since breaking API changes affect tools built on top.
- A changelog entry for API changes would make it easier for companion tools to follow.
