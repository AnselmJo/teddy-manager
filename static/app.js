"use strict";
/* Teddy Manager – Frontend ohne Build-Schritt. Texte: i18n.js, Icons: vendor/icons.svg (Lucide). */

const COLORS = [
  ["rot", "#e53935"], ["orange", "#fb8c00"], ["gelb", "#fdd835"], ["limette", "#7cb342"],
  ["gruen", "#2e7d32"], ["tuerkis", "#00acc1"], ["hellblau", "#42a5f5"], ["blau", "#1e3a8a"],
  ["lila", "#8e24aa"], ["pink", "#ec407a"], ["braun", "#6d4c41"], ["schwarz", "#263238"],
];
const colorHex = (k) => (k && k[0] === "#" ? k : (COLORS.find((c) => c[0] === k) || COLORS[7])[1]);
const isLight = (k) => {
  const h = colorHex(k), r = parseInt(h.slice(1, 3), 16), g = parseInt(h.slice(3, 5), 16), b = parseInt(h.slice(5, 7), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b > 170;
};

const S = { term: "Custom-Tonie", termPlural: "Custom-Tonies", tonies: [], media: [], kinds: {},
  libFilter: "", libUnused: false, libSearch: "", uploadKind: "lied", poll: null };

/* ---------- Helfer ---------- */
const SVGNS = "http://www.w3.org/2000/svg";
function icon(name, cls = "") {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("class", "ic " + cls);
  s.setAttribute("aria-hidden", "true");
  const u = document.createElementNS(SVGNS, "use");
  u.setAttribute("href", `/static/vendor/icons.svg?v=11#i-${name}`);
  s.append(u);
  return s;
}
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) el.append(k.nodeType ? k : String(k));
  return el;
}
const $ = (s) => document.querySelector(s);
const fmt = (sec) => {
  sec = Math.round(sec || 0);
  const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${mm}:${String(ss).padStart(2, "0")}`;
};
const fmtLong = (sec) => {
  const m = Math.round((sec || 0) / 60);
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`;
};
const fmtBytes = (b) => (b > 1e9 ? (b / 1e9).toFixed(1) + " GB" : Math.round(b / 1e6) + " MB");
const dot = (...xs) => xs.filter(Boolean).join(" · ");
const kindIcon = (k) => (k === "geschichte" ? "book-open" : k === "podcast" ? "podcast" : "music");
const natCmp = (a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
const thumb = (url, ic, extra = {}) =>
  h("div", { class: "thumb", style: url ? { backgroundImage: `url("${url}")`, ...extra } : extra }, url ? "" : icon(ic));
const btn = (ic, label, onclick, cls = "btn") => h("button", { class: cls, onclick }, ic ? icon(ic) : "", label || "");

async function api(path, opts = {}) {
  const o = { method: opts.method || "GET", headers: {} };
  if (opts.json !== undefined) { o.body = JSON.stringify(opts.json); o.headers["Content-Type"] = "application/json"; }
  if (opts.form) o.body = opts.form;
  let r;
  try { r = await fetch(path, o); } catch (e) { if (!opts.quiet) toast(t("noConn"), { err: true }); throw e; }
  if (r.status === 401) { showPin(); throw new Error("PIN"); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) {
    const msg = (data && data.detail) || `${r.status}`;
    if (!opts.quiet) toast(typeof msg === "string" ? msg : "?", { err: true });
    throw new Error(msg);
  }
  return data;
}

let toastTimer;
function toast(text, { err = false, undo = null, ms = 3500, undoLabel = "" } = {}) {
  const el = $("#toast");
  el.replaceChildren(h("span", {}, text));
  if (undo) el.append(h("button", { onclick: () => { el.hidden = true; undo(); } }, undoLabel || t("undo")));
  el.className = err ? "err" : "";
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), undo ? 8000 : ms);
}

/* ---------- Sheet ---------- */
function openSheet(title, ...content) {
  const sh = $("#sheet");
  sh.replaceChildren(h("div", { class: "grab" }), title ? h("h2", {}, title) : "", ...content);
  sh.hidden = false; $("#sheet-backdrop").hidden = false;
  sh.scrollTop = 0;
  return sh;
}
function closeSheet() {
  $("#sheet").hidden = true; $("#sheet-backdrop").hidden = true;
  if (S.sheetClose) { const f = S.sheetClose; S.sheetClose = null; f(); }
}
$("#sheet-backdrop").addEventListener("click", closeSheet);

/* ---------- Player (Mini-Player mit Spulen) ---------- */
const player = $("#player");
let playingId = null;
function setPlayIcons() {
  document.querySelectorAll(".play-btn").forEach((b) =>
    b.replaceChildren(icon(b.dataset.pid === playingId && !player.paused ? "pause" : "play")));
  const mini = $("#mini");
  if (mini) mini.querySelector(".mini-pp").replaceChildren(icon(player.paused ? "play" : "pause"));
}
let chapters = [];   // [{title, start}] des gerade gespielten Tonies
const chapterAt = (sec) => { let i = 0; chapters.forEach((c, k) => { if (sec >= c.start - 0.3) i = k; }); return i; };
function jumpChapter(dir) {
  if (!chapters.length) return;
  const i = chapterAt(player.currentTime);
  const target = dir < 0 && player.currentTime - chapters[i].start > 3 ? i : Math.max(0, Math.min(chapters.length - 1, i + dir));
  player.currentTime = chapters[target].start;
  if (player.paused) player.play();
}
function miniPlayer(title) {
  let mini = $("#mini");
  if (mini) mini.remove();
  {
    const range = h("input", { type: "range", min: 0, max: 1, step: 0.5, value: 0, class: "mini-range", "aria-label": "Position" });
    range.addEventListener("input", () => { if (isFinite(player.duration)) player.currentTime = +range.value; });
    const ch = chapters.length > 1;
    mini = h("div", { id: "mini" },
      ch ? h("button", { class: "row-btn", "aria-label": "Prev", onclick: () => jumpChapter(-1) }, icon("chevron-left")) : "",
      h("button", { class: "row-btn mini-pp", onclick: () => (player.paused ? player.play() : player.pause()) }, icon("pause")),
      ch ? h("button", { class: "row-btn", "aria-label": "Next", onclick: () => jumpChapter(1) }, icon("chevron-right")) : "",
      h("div", { class: "mini-main" }, h("div", { class: "mini-title" }), ch ? h("div", { class: "mini-chapter" }) : "",
        h("div", { class: "mini-line" }, range, h("span", { class: "mini-time" }, "0:00"))),
      h("button", { class: "row-btn", "aria-label": "Close", onclick: () => { player.pause(); player.removeAttribute("src"); playingId = null; mini.remove(); setPlayIcons(); } }, icon("x")));
    document.body.append(mini);
  }
  mini.querySelector(".mini-title").textContent = title || "";
}
player.addEventListener("timeupdate", () => {
  const mini = $("#mini");
  if (!mini) return;
  const r = mini.querySelector(".mini-range");
  if (isFinite(player.duration)) { r.max = player.duration; r.value = player.currentTime; }
  mini.querySelector(".mini-time").textContent = isFinite(player.duration) ? `${fmt(player.currentTime)} / ${fmt(player.duration)}` : fmt(player.currentTime);
  const chEl = mini.querySelector(".mini-chapter");
  if (chEl && chapters.length) { const i = chapterAt(player.currentTime); chEl.textContent = `${i + 1}/${chapters.length} · ${chapters[i].title}`; }
});
/* Weiterhören: Position je Figur/Titel lokal merken (nur bei längeren Inhalten sinnvoll) */
const RESUME_KEY = "tm_resume";
const resumeGet = (id) => { try { return (JSON.parse(localStorage.getItem(RESUME_KEY) || "{}"))[id]; } catch (e) { return null; } };
function resumeSet(id, pos, dur) {
  try {
    const all = JSON.parse(localStorage.getItem(RESUME_KEY) || "{}");
    if (!dur || dur < 600 || pos < 15 || pos > dur - 20) delete all[id]; else all[id] = { pos, at: Date.now() };
    localStorage.setItem(RESUME_KEY, JSON.stringify(all));
  } catch (e) { /* egal */ }
}
let lastSave = 0;
player.addEventListener("timeupdate", () => {
  if (playingId && Date.now() - lastSave > 4000) { lastSave = Date.now(); resumeSet(playingId, player.currentTime, player.duration); }
});
player.addEventListener("pause", () => playingId && resumeSet(playingId, player.currentTime, player.duration));
player.addEventListener("ended", () => playingId && resumeSet(playingId, 0, 0));

function playToggle(id, url, title, chs = []) {
  if (playingId === id) { player.paused ? player.play() : player.pause(); return; }
  chapters = chs || [];
  player.src = url;
  const saved = resumeGet(id);
  if (saved && saved.pos > 15) {
    player.addEventListener("loadedmetadata", () => { player.currentTime = saved.pos; }, { once: true });
    toast(t("resumeAt", { x: fmt(saved.pos) }), { undo: () => { player.currentTime = 0; }, undoLabel: t("fromStart") });
  }
  player.play().catch(() => toast(t("unplayable"), { err: true }));
  playingId = id;
  miniPlayer(title);
  setPlayIcons();
}
player.addEventListener("pause", setPlayIcons);
player.addEventListener("play", setPlayIcons);
player.addEventListener("ended", () => { setPlayIcons(); });
/* Ganze Figur am Handy abspielen (Custom-, Original- und Kreativ-Tonies), mit Kapiteln */
async function playTag(ruid, fallbackTitle) {
  const info = await api(`/api/tags/${ruid}/chapters`);
  if (!info.playable) { toast(t("notOnServer"), { err: true }); return; }
  playToggle("t" + ruid, `/api/tags/${ruid}/play`, fallbackTitle || info.title, info.chapters);
}

const playBtn = (id, url, title = "") => h("button", { class: "row-btn play-btn", "data-pid": id, "aria-label": "Play",
  onclick: (e) => { e.stopPropagation(); playToggle(id, url, title); } }, icon(playingId === id && !player.paused ? "pause" : "play"));
const iconBtn = (ic, label, onclick, cls = "") => h("button", { class: "row-btn " + cls, "aria-label": label, title: label,
  onclick: (e) => { e.stopPropagation(); onclick(e); } }, icon(ic));

/* ---------- PIN ---------- */
function showPin() {
  if (S.pinOpen) return;
  S.pinOpen = true;
  let pin = "";
  const dots = h("div", { class: "dots" }, "○○○○");
  const press = async (d) => {
    if (d === "⌫") pin = pin.slice(0, -1); else if (pin.length < 4) pin += d;
    dots.textContent = "●".repeat(pin.length) + "○".repeat(4 - pin.length);
    if (pin.length === 4) {
      const r = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin }) });
      if (r.ok) { S.pinOpen = false; S.sheetClose = null; closeSheet(); if (S.afterPin) { location.hash = S.afterPin; S.afterPin = null; } else route(); }
      else { pin = ""; dots.textContent = "○○○○"; toast(t("pinWrong"), { err: true }); }
    }
  };
  const pad = h("div", { class: "pad" }, ..."123456789".split("").map((d) => h("button", { onclick: () => press(d) }, d)),
    h("span"), h("button", { onclick: () => press("0") }, "0"), h("button", { onclick: () => press("⌫") }, "⌫"));
  openSheet(t("pin"), h("div", { class: "pin" }, dots, pad));
  S.sheetClose = S.afterPin ? () => { S.pinOpen = false; S.afterPin = null; } : () => { S.pinOpen = false; setTimeout(showPin, 50); };
}

/* ---------- Router ---------- */
function setHeader(title, back) {
  $("#title").textContent = title;
  $("#back").hidden = !back;
  S.backTo = back;
}
$("#back").addEventListener("click", () => (location.hash = S.backTo || "#tonies"));
$("#settings-btn").addEventListener("click", () => (location.hash = "#einstellungen"));

function applyLangStatic() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("#tabs a").forEach((a) => (a.querySelector(".tl").textContent = t(a.dataset.tab === "bibliothek" ? "library" : a.dataset.tab)));
}

let NAV = 0;
const currentView = () => (location.hash.slice(1) || "tonies").split("?")[0].split("/")[0];
/* Seite nur zeichnen, wenn sie noch die aktuelle ist (verhindert, dass eine späte Antwort die neue Seite überschreibt). */
function show(view, ...nodes) {
  if (currentView() !== view) return false;
  const el = $("#view");
  el.replaceChildren(...nodes);
  el.classList.remove("loading");
  return true;
}

async function route() {
  clearInterval(S.poll); S.poll = null;
  NAV++;
  window.scrollTo(0, 0);
  $("#draftbar")?.remove();
  document.body.classList.toggle("kids", (location.hash.slice(1) || "").startsWith("kinder"));
  $("#view").classList.add("loading");
  const [path, query] = (location.hash.slice(1) || "tonies").split("?");
  const [view, arg] = path.split("/");
  const tab = ["tonie", "archiv", "figuren"].includes(view) ? "tonies" : ["einstellungen", "hilfe"].includes(view) ? "" : view;
  document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("active", a.dataset.tab === tab));
  const params = new URLSearchParams(query || "");
  try {
    if (view === "tonie") await viewTonie(+arg);
    else if (view === "bibliothek") await viewLibrary(params);
    else if (view === "radio") await viewRadio(arg);
    else if (view === "einstellungen") await viewSettings(arg);
    else if (view === "hilfe") viewHelp();
    else if (view === "archiv") await viewArchive();
    else if (view === "kinder") await viewKids();
    else if (view === "figuren") await viewFigures();
    else await viewTonies();
  } catch (e) { console.error(e); }
  $("#view").classList.remove("loading");
}
window.addEventListener("hashchange", route);

/* ---------- Tonies (Start) ---------- */
const BUSY = ["building", "queued", "pending"];
function statusBadge(x) {
  if (x.draft) return h("span", { class: "badge draft", title: t("draft") }, icon("pencil"));
  if (BUSY.includes(x.status)) return h("span", { class: "badge busy" }, h("span", { class: "spin" }));
  if (x.status === "error") return h("span", { class: "badge err" }, icon("triangle-alert"));
  return null;
}
function tonieTile(x) {
  const sub = x.mode === "radio" ? (x.station ? x.station.name : "–")
    : x.count ? dot(`${x.chapters} ${t("tracks")}`, fmtLong(x.duration)) : t("noTracks");
  return h("button", { class: "tile" + (isLight(x.color) ? " light" : ""), style: { background: x.hex },
    onclick: () => (location.hash = `#tonie/${x.id}`) },
    h("div", { class: "pic" + (x.own_image ? "" : " coin"), style: { backgroundImage: `url("${x.image}")` } }),
    h("div", { class: "name" }, x.name), h("div", { class: "sub" }, x.mode === "radio" ? icon("radio", "sm") : "", sub),
    h("div", { class: "badge-pos" }, statusBadge(x)));
}

async function viewTonies() {
  setHeader(t("tonies"));
  const nav = NAV;
  const [data, tagData] = await Promise.all([api("/api/tonies"), api("/api/tags", { quiet: true }).catch(() => ({ tags: [] }))]);
  if (nav !== NAV) return;
  S.tonies = data.tonies;
  const tags = tagData.tags;
  const active = S.tonies.filter((x) => !x.archived);
  const unknown = tags.filter((x) => x.kind === "unbekannt" && !x.archived);
  const others = tags.filter((x) => (x.kind === "original" || x.kind === "kreativ") && !x.archived);
  const archivedN = S.tonies.filter((x) => x.archived).length + tags.filter((x) => x.archived).length;
  const banner = unknown.length ? h("div", { class: "banner" },
    h("button", { class: "grow", onclick: openLearn }, icon("plus"), t("newFigures", { n: unknown.length })),
    iconBtn("eye-off", t("archiveAll"), async () => {
      await Promise.all(unknown.map((x) => api(`/api/tags/${x.uid}/archive`, { method: "POST" })));
      toast(t("archived"), { undo: async () => { await Promise.all(unknown.map((x) => api(`/api/tags/${x.uid}/archive`, { method: "DELETE" }))); viewTonies(); } });
      viewTonies();
    })) : "";
  const grid = h("div", { class: "grid" }, ...active.map(tonieTile),
    h("button", { class: "tile add", onclick: openLearn }, h("div", { class: "pic" }, icon("plus", "xl")), h("div", { class: "name" }, t("add"))));
  const more = h("ul", { class: "list card nav-list" },
    others.length ? navRow("package", t("othersTitle"), others.length, "#figuren") : "",
    archivedN ? navRow("archive", t("archiveTitle"), archivedN, "#archiv") : "");
  show("tonies", banner, grid, more.children.length ? more : "");
  if (S.tonies.some((x) => BUSY.includes(x.status))) S.poll = setInterval(async () => {
    const d = await api("/api/tonies", { quiet: true }).catch(() => null);
    if (!d || nav !== NAV) return;
    if (JSON.stringify(d.tonies) !== JSON.stringify(S.tonies)) viewTonies();
    else if (!d.tonies.some((x) => BUSY.includes(x.status))) clearInterval(S.poll);
  }, 2500);
}

/* Zeile, die zu einer Unterseite führt */
function navRow(ic, label, value, href, onclick) {
  return h("li", { class: "row clickable nav-row", onclick: onclick || (() => (location.hash = href)) },
    icon(ic), h("div", { class: "main t" }, label), value !== "" && value != null ? h("span", { class: "muted small" }, String(value)) : "",
    icon("chevron-right", "muted"));
}

function tagRow(x, archived, reload) {
  return h("li", { class: "row" }, thumb(x.picture, "circle"),
    h("div", { class: "main" }, h("div", { class: "t" }, x.title || "…" + x.uid.slice(-4)), h("div", { class: "s" }, t(x.kind))),
    x.playable && !archived ? h("button", { class: "row-btn", "aria-label": t("playTonie"), onclick: () => playTag(x.ruid, x.title) }, icon("play")) : "",
    archived
      ? h("button", { class: "btn small-btn", onclick: async () => { await api(`/api/tags/${x.uid}/archive`, { method: "DELETE" }); reload(); } }, icon("archive-restore"), t("unarchive"))
      : iconBtn("eye-off", t("archive"), async () => { await api(`/api/tags/${x.uid}/archive`, { method: "POST" }); toast(t("archived")); reload(); }));
}

async function viewFigures() {
  setHeader(t("othersTitle"), "#tonies");
  const { tags } = await api("/api/tags");
  const list = tags.filter((x) => (x.kind === "original" || x.kind === "kreativ") && !x.archived);
  show("figuren", h("ul", { class: "list card" }, ...list.map((x) => tagRow(x, false, viewFigures))),
    list.length ? "" : h("p", { class: "empty" }, t("nothing")));
}

async function viewArchive() {
  setHeader(t("archiveTitle"), "#tonies");
  const [{ tonies }, { tags }] = await Promise.all([api("/api/tonies"), api("/api/tags").catch(() => ({ tags: [] }))]);
  const arch = tonies.filter((x) => x.archived);
  const hidden = tags.filter((x) => x.archived);
  const restoreTonie = (x) => h("button", { class: "btn small-btn", onclick: async (e) => {
    e.stopPropagation(); await api(`/api/tonies/${x.id}`, { method: "PATCH", json: { archived: false } }); viewArchive();
  } }, icon("archive-restore"), t("unarchive"));
  show("archiv",
    arch.length ? h("div", { class: "card" }, h("h3", { class: "first" }, S.termPlural),
      h("ul", { class: "list" }, ...arch.map((x) => h("li", { class: "row clickable", onclick: () => (location.hash = `#tonie/${x.id}`) },
        h("div", { class: "thumb round", style: { background: `${x.hex} url("${x.image}") center/cover` } }),
        h("div", { class: "main" }, h("div", { class: "t" }, x.name)), restoreTonie(x))))) : "",
    hidden.length ? h("div", { class: "card" }, h("h3", { class: "first" }, t("hiddenFigures")),
      h("ul", { class: "list" }, ...hidden.map((x) => tagRow(x, true, viewArchive)))) : "",
    arch.length || hidden.length ? "" : h("p", { class: "empty" }, t("nothing")));
}

/* ---------- Farbe ---------- */
function colorPicker(current, onPick) {
  const wrap = h("div", { class: "swatches" });
  const mark = (el) => { wrap.querySelectorAll(".swatch").forEach((x) => x.classList.remove("on")); el.classList.add("on"); };
  for (const [key, hex] of COLORS) {
    const b = h("button", { class: "swatch" + (key === current ? " on" : ""), style: { background: hex }, "aria-label": key,
      onclick: () => { mark(b); onPick(key); } });
    wrap.append(b);
  }
  const custom = current && current[0] === "#";
  // Farbrad: rund, Farbton außen, Weiß zur Mitte; das native Farbfeld bleibt unsichtbar
  const input = h("input", { type: "color", class: "wheel-input", value: custom ? current : "#ff6f00", tabindex: -1, "aria-hidden": "true" });
  const dotEl = h("span", { class: "wheel-dot", style: custom ? { background: current } : {} });
  const wheel = h("button", { class: "swatch wheel" + (custom ? " on custom" : ""), title: t("ownColor"), "aria-label": t("ownColor"),
    onclick: () => input.click() }, dotEl);
  input.addEventListener("change", () => { mark(wheel); wheel.classList.add("custom"); dotEl.style.background = input.value; onPick(input.value); });
  wrap.append(wheel, input);
  return wrap;
}

/* ---------- Anlernen ---------- */
async function openLearn() {
  const { token } = await api("/api/learn/start", { method: "POST" });
  const known = (await api("/api/tags")).tags.filter((x) => x.kind === "unbekannt");
  let stopped = false;
  const box = h("div", {});
  box.append(h("div", { class: "center" }, h("div", { class: "learn-anim" }, icon("box", "xl")), h("p", { class: "big" }, t("placeOnBox"))));
  if (known.length) {
    box.append(h("h3", {}, t("seen")),
      h("ul", { class: "list" }, ...known.map((x) => h("li", { class: "row clickable", onclick: () => found(x) },
        h("div", { class: "thumb" }, icon("circle-dot")), h("div", { class: "main" }, h("div", { class: "t" }, "…" + x.uid.slice(-4)),
          h("div", { class: "s" }, dot(x.has_content ? t("hasContent") : "", x.archived ? t("archived") : ""))),
        icon("chevron-right", "muted")))));
  }
  openSheet(t("addTonie", { term: S.term }), box);
  S.sheetClose = () => (stopped = true);

  function found(tag) {
    stopped = true;
    let color = "blau";
    const name = h("input", { type: "text", placeholder: t("name"), maxlength: 60 });
    box.replaceChildren(h("p", { class: "big center ok-text" }, icon("circle-check"), " ", t("found")),
      h("label", { class: "field" }, t("name"), name), colorPicker(color, (c) => (color = c)),
      h("button", { class: "btn primary block", onclick: async () => {
        await api(`/api/tags/${tag.uid}/archive`, { method: "DELETE", quiet: true }).catch(() => {});
        const x = await api("/api/tonies", { method: "POST", json: { uid: tag.uid, name: name.value.trim() || "Tonie", color } });
        S.sheetClose = null; closeSheet(); location.hash = `#tonie/${x.id}`;
      } }, icon("check"), t("save")));
    name.focus();
  }
  (async function loop() {
    while (!stopped) {
      await new Promise((r) => setTimeout(r, 2000));
      if (stopped) break;
      try {
        const { new: fresh } = await api(`/api/learn/poll?token=${token}`, { quiet: true });
        if (fresh.length && !stopped) {
          const x = fresh[0];
          if (x.kind !== "unbekannt" && !confirm(t("notCustom", { x: t(x.kind) }) + `\n${x.title}`)) continue;
          found(x);
        }
      } catch (e) { /* weiter versuchen */ }
    }
  })();
}

/* ---------- Tonie-Detail ---------- */
async function viewTonie(id) {
  const nav = NAV;
  const cur = await api(`/api/tonies/${id}`);
  if (nav !== NAV) return;
  S.cur = cur;
  renderTonie();
  if (!S.tonies.length) api("/api/tonies").then((d) => (S.tonies = d.tonies));
  S.poll = setInterval(async () => {
    if (!BUSY.includes(S.cur.status) && !S.cur.hint) return;
    const n = await api(`/api/tonies/${id}`, { quiet: true }).catch(() => null);
    if (!n || nav !== NAV) return;
    if (n.status !== S.cur.status || n.status_msg !== S.cur.status_msg || n.hint !== S.cur.hint) { S.cur = n; renderStatus(); }
  }, 2000);
}

async function patchTonie(fields, rerender = true) {
  S.cur = await api(`/api/tonies/${S.cur.id}`, { method: "PATCH", json: fields });
  if (rerender) renderTonie(); else renderStatus();
}

function renderStatus() {
  const x = S.cur, el = $("#tonie-status");
  if (!el) return;
  drawDraftBar(x);
  let cls = "ok", ic = icon("circle-check"), text = t("stOk");
  if (x.draft) {
    el.className = "status draft";
    el.replaceChildren(icon("pencil"), h("div", { class: "grow" }, t("draftHint")));
    return;
  }
  if (BUSY.includes(x.status)) {
    cls = "busy"; ic = h("span", { class: "spin" });
    text = x.status === "building" ? dot(t("stBuilding"), x.status_msg) : t("stQueued");
  } else if (x.status === "error") { cls = "err"; ic = icon("triangle-alert"); text = x.status_msg; }
  else if (x.status === "empty") { cls = "warn"; ic = icon("circle"); text = t("stEmpty"); }

  el.className = "status " + cls;
  const boxLine = x.box_state && !BUSY.includes(x.status) && x.status !== "error"
    ? h("div", { class: "box-state " + x.box_state }, icon(x.box_state === "current" ? "check" : "box", "sm"), " ", t("box_" + x.box_state))
    : x.hint ? h("div", { class: "muted small" }, t("hint")) : "";
  el.replaceChildren(ic, h("div", { class: "grow" }, text, boxLine),
    x.status === "error" ? btn("refresh-cw", t("retry"), rebuild) : "");
}

/* Entwurf: schwebender Balken über den Tabs – erst ordnen, dann einmal laden */
function drawDraftBar(x) {
  $("#draftbar")?.remove();
  if (!x.draft || currentView() !== "tonie") return;
  document.body.append(h("div", { id: "draftbar" },
    h("span", { class: "grow" }, t("draft")),
    h("button", { class: "btn primary", onclick: async (e) => {
      e.currentTarget.disabled = true;
      S.cur = await api(`/api/tonies/${S.cur.id}/publish`, { method: "POST" });
      renderStatus();
    } }, icon("upload"), t("publish"))));
}

function renderTonie() {
  const x = S.cur;
  if (currentView() !== "tonie" || location.hash !== `#tonie/${x.id}`) return;
  setHeader(x.name, "#tonies");
  const name = h("input", { type: "text", value: x.name, maxlength: 60, "aria-label": t("name") });
  name.addEventListener("change", () => patchTonie({ name: name.value }, false).then(() => setHeader(S.cur.name, "#tonies")));
  const hero = h("div", { class: "hero" + (isLight(x.color) ? " light" : ""), style: { background: x.hex } },
    h("button", { class: "pic" + (x.own_image ? "" : " coin"), style: { backgroundImage: `url("${x.image}")` },
      onclick: () => openImagePicker({ covers: x.covers, onPick: (id) => patchTonie({ image_id: id }) }),
      "aria-label": t("image") }, h("span", { class: "edit-dot" }, icon("pencil", "sm"))),
    x.playable ? h("button", { class: "play-dot", "aria-label": t("playTonie"), onclick: () =>
      x.mode === "radio" ? playToggle("st" + x.id, x.station.url, x.station.name) : playTag(x.ruid, x.name) }, icon("play")) : "",
    name, colorPicker(x.color, (c) => patchTonie({ color: c })));

  const seg = h("div", { class: "seg" },
    h("button", { class: x.mode === "playlist" ? "on" : "", onclick: () => x.mode !== "playlist" && patchTonie({ mode: "playlist" }) }, icon("list-music"), t("playlist")),
    h("button", { class: x.mode === "radio" ? "on" : "", onclick: () => x.mode !== "radio" && patchTonie({ mode: "radio" }) }, icon("radio"), t("radio")));
  const content = h("div", { class: "card" }, seg,
    x.podcast ? h("p", { class: "muted small" }, icon("podcast", "sm"), " ", t("managedBy", { x: x.podcast.title })) : "",
    x.mode === "radio" ? radioChooser() : playlistEditor());
  const sleepCard = x.mode === "playlist" ? sleepEditor(x) : "";

  const others = () => S.tonies.filter((o) => o.id !== x.id);
  const act = (ic, label, onclick, extra = {}) => h("button", { class: "act" + (extra.danger ? " danger" : ""), onclick, disabled: extra.disabled }, icon(ic), label);
  const more = () => openSheet(x.name, h("ul", { class: "list nav-list" },
    x.mode === "playlist" && x.count > 1 ? navRow("shuffle", t("shuffle"), "", null, () => { closeSheet(); shuffle(); }) : "",
    navRow("arrow-left-right", t("swap"), "", null, () => { closeSheet(); pickTonie(t("swapWith"), others(), swap); }),
    navRow("copy", t("copy"), "", null, () => { closeSheet(); pickTonie(t("copyTo"), others(), copyTo); })));
  const actions = h("div", { class: "actions four" },
    act("refresh-cw", t("rebuild"), rebuild),
    act(x.archived ? "archive-restore" : "archive", x.archived ? t("unarchive") : t("archive"), async () => {
      await patchTonie({ archived: !x.archived }, false);
      toast(x.archived ? t("unarchive") : t("archived"));
      location.hash = "#tonies";
    }),
    act("trash-2", t("del"), deleteTonie, { danger: true }),
    act("ellipsis-vertical", t("more"), more));

  show("tonie", hero, h("div", { id: "tonie-status" }), content, sleepCard, actions,
    h("p", { class: "muted small center" }, dot(x.last_seen ? `${t("lastPlaced")} ${relTime(x.last_seen)}` : "", `${S.term} · ${x.uid}`)));
  renderStatus();
}

function sleepEditor(x) {
  const sl = x.sleep;
  const patch = (v) => patchTonie({ sleep: v });
  const body = sl.on ? [
    h("p", { class: "muted small" }, t("sleepHint")),
    h("div", { class: "lbl" }, icon("timer"), t("sleepDur")),
    segChoice([[15, "15"], [30, "30"], [45, "45"], [60, "60"], [90, "90 min"]], sl.minutes, (v) => patch({ minutes: v })),
    h("div", { class: "lbl" }, icon("volume-1"), t("sleepEnd")),
    segChoice([[0, "0"], [20, "20"], [40, "40"], [60, "60 %"]], sl.end_pct, (v) => patch({ end_pct: v })),
    h("label", { class: "toggle compact" }, h("span", {}, icon("octagon-x"), t("sleepStop")),
      h("input", { type: "checkbox", checked: sl.stop, onchange: (e) => patch({ stop: e.target.checked }) })),
    sl.stop ? h("label", { class: "toggle compact" }, h("span", {}, icon("repeat"), t("sleepRepeat")),
      h("input", { type: "checkbox", checked: sl.repeat, onchange: (e) => patch({ repeat: e.target.checked }) })) : "",
  ] : [];
  return h("div", { class: "card" },
    h("label", { class: "toggle compact" }, h("span", { class: "strong" }, icon("moon"), t("sleep")),
      h("input", { type: "checkbox", checked: sl.on, onchange: (e) => patch({ on: e.target.checked }) })), ...body);
}

function playlistEditor() {
  const x = S.cur;
  const list = h("ul", { class: "list" });
  for (const m of x.tracks) {
    list.append(h("li", { class: "row", "data-id": m.id },
      h("span", { class: "handle", "aria-label": "Sort" }, icon("grip-vertical")),
      thumb(m.cover, kindIcon(m.kind)),
      h("div", { class: "main" }, h("div", { class: "t" }, m.title),
        h("div", { class: "s" }, dot(m.chapters > 1 ? `${m.chapters} ${t("chapters")}` : "", m.album && m.album !== m.title ? m.album : m.artist, fmt(m.net_duration)))),
      playBtn("m" + m.id, m.audio, m.title || m.name),
      iconBtn("x", t("del"), () => savePlaylist(x.tracks.filter((y) => y !== m).map((y) => y.id), m.title, x.tracks.map((y) => y.id)))));
  }
  if (window.Sortable) Sortable.create(list, { handle: ".handle", animation: 150,
    onEnd: () => savePlaylist([...list.children].map((li) => +li.dataset.id)) });
  return h("div", {},
    x.tracks.length ? list : h("p", { class: "empty" }, t("noTracks")),
    x.tracks.length ? h("p", { class: "muted small" }, dot(`${x.chapters} ${t("chapters")}`, fmtLong(x.duration))) : "",
    h("button", { class: "btn primary block", onclick: openAddTracks }, icon("plus"), t("addTracks")),
    h("label", { class: "toggle" }, h("span", {}, icon("volume-2"), t("evenVolume")),
      h("input", { type: "checkbox", checked: x.loudnorm, onchange: (e) => patchTonie({ loudnorm: e.target.checked }, false) })));
}

async function savePlaylist(ids, msg, undoIds) {
  S.cur = await api(`/api/tonies/${S.cur.id}/playlist`, { method: "PUT", json: { media_ids: ids } });
  renderTonie();
  if (msg) toast(msg, { undo: undoIds ? () => savePlaylist(undoIds) : null });
}

/* Bibliothek in Gruppen (Alben/mehrteilige Geschichten) */
function groupMedia(list) {
  const groups = [], byAlbum = new Map();
  for (const m of list) {
    if (!m.album) { groups.push({ single: m }); continue; }
    const k = m.kind + "|" + m.album;
    if (!byAlbum.has(k)) { const g = { album: m.album, kind: m.kind, parts: [] }; byAlbum.set(k, g); groups.push(g); }
    byAlbum.get(k).parts.push(m);
  }
  for (const g of byAlbum.values()) {
    g.parts.sort((a, b) => a.album_pos - b.album_pos || a.id - b.id);
    if (g.parts.length === 1) { const i = groups.indexOf(g); groups[i] = { single: g.parts[0] }; }
    g.duration = g.parts.reduce((s, p) => s + p.net_duration, 0);
    g.cover = (g.parts.find((p) => p.cover) || {}).cover;
  }
  return groups;
}
const matches = (m, q, kind, unused) => (!kind || m.kind === kind) && (!unused || !m.used) &&
  (!q || (m.title + " " + m.artist + " " + m.album).toLowerCase().includes(q));

async function openAddTracks() {
  const { media, kinds } = await api("/api/media");
  const inList = new Set(S.cur.tracks.map((m) => m.id));
  const chosen = [];
  let filter = "", q = "";
  const open = new Set();
  const list = h("ul", { class: "list" });
  const addBtn = h("button", { class: "btn primary block sticky", disabled: true, onclick: async () => {
    S.sheetClose = null; closeSheet();
    await savePlaylist([...S.cur.tracks.map((m) => m.id), ...chosen], `+${chosen.length}`);
  } }, icon("plus"), t("addTracks"));
  const refresh = () => { addBtn.disabled = !chosen.length; addBtn.replaceChildren(icon("plus"), chosen.length ? `${t("addTracks")} (${chosen.length})` : t("addTracks")); draw(); };
  const toggle = (ids, on) => { for (const id of ids) { const i = chosen.indexOf(id); if (on && i < 0) chosen.push(id); if (!on && i >= 0) chosen.splice(i, 1); } refresh(); };
  const row = (m, indent) => h("li", { class: "row clickable" + (indent ? " indent" : ""), onclick: () => toggle([m.id], !chosen.includes(m.id)) },
    h("input", { type: "checkbox", checked: chosen.includes(m.id) }), thumb(m.cover, kindIcon(m.kind)),
    h("div", { class: "main" }, h("div", { class: "t" }, m.title), h("div", { class: "s" },
      dot(m.chapters > 1 ? `${m.chapters} ${t("chapters")}` : "", indent ? "" : m.artist, fmt(m.net_duration)))),
    inList.has(m.id) ? icon("check", "muted") : "", playBtn("a" + m.id, m.audio, m.title || m.name));
  function draw() {
    const items = [];
    for (const g of groupMedia(media.filter((m) => matches(m, q, filter, false)))) {
      if (g.single) { items.push(row(g.single)); continue; }
      const ids = g.parts.map((p) => p.id), all = ids.every((id) => chosen.includes(id));
      items.push(h("li", { class: "row clickable", onclick: () => toggle(ids, !all) },
        h("input", { type: "checkbox", checked: all }), thumb(g.cover, kindIcon(g.kind)),
        h("div", { class: "main" }, h("div", { class: "t" }, g.album), h("div", { class: "s" }, dot(`${g.parts.length} ${t("parts")}`, fmt(g.duration)))),
        iconBtn(open.has(g.album) ? "chevron-down" : "chevron-right", "", () => { open.has(g.album) ? open.delete(g.album) : open.add(g.album); draw(); })));
      if (open.has(g.album)) g.parts.forEach((p) => items.push(row(p, true)));
    }
    list.replaceChildren(...items);
    if (!items.length) list.append(h("p", { class: "empty" }, media.length ? t("nothing") : t("emptyLib")));
  }
  const chips = kindChips(() => filter, (k) => { filter = k; draw(); });
  const search = searchRow("", (v) => { q = v.toLowerCase(); draw(); });
  draw();
  openSheet(t("addTracks"), search, chips, list, addBtn);
}

/* Art-Filter: antippen = nur diese Art, nochmal antippen = alle */
function kindChips(get, set) {
  const opts = [["lied", "music", t("songs")], ["geschichte", "book-open", t("stories")], ["podcast", "podcast", t("podcasts")]];
  const chips = h("div", { class: "chips filter" });
  const draw = () => chips.replaceChildren(...opts.map(([k, ic, label]) =>
    h("button", { class: "chip" + (get() === k ? " on" : ""), onclick: () => { set(get() === k ? "" : k); draw(); } }, icon(ic, "sm"), label)));
  draw();
  return chips;
}

/* Suchfeld mit Schalter „Ungenutzt“ in einer Zeile */
function searchRow(value, onInput, unused, onUnused) {
  const inp = h("input", { type: "search", class: "compact-input", placeholder: t("search"), value, oninput: (e) => onInput(e.target.value) });
  const tog = onUnused ? h("button", { class: "chip unused-toggle" + (unused ? " on" : ""), onclick: (e) => {
    unused = !unused; e.currentTarget.classList.toggle("on", unused); onUnused(unused);
  } }, t("unused")) : "";
  return h("div", { class: "search-row" }, inp, tog);
}

function radioChooser() {
  const x = S.cur;
  const wrap = h("div", {});
  api("/api/stations").then(({ stations }) => {
    if (!stations.length) { wrap.append(h("p", { class: "empty" }, t("noStations"))); return; }
    wrap.append(h("ul", { class: "list" }, ...stations.map((s) => h("li", { class: "row clickable", onclick: () => patchTonie({ station_id: s.id, mode: "radio" }) },
      thumb(s.image, "radio"), h("div", { class: "main" }, h("div", { class: "t" }, s.name)),
      playBtn("r" + s.id, s.url, s.title || s.name),
      icon(x.station && x.station.id === s.id ? "circle-dot" : "circle", "radio-dot")))));
  });
  return wrap;
}

function pickTonie(title, list, onPick) {
  if (!list.length) { toast(t("noOther")); return; }
  openSheet(title, h("ul", { class: "list" }, ...list.map((o) => h("li", { class: "row clickable", onclick: () => { closeSheet(); onPick(o); } },
    h("div", { class: "thumb round", style: { background: `${o.hex} url("${o.image}") center/cover` } }),
    h("div", { class: "main" }, h("div", { class: "t" }, o.name), h("div", { class: "s" }, o.mode === "radio" ? t("radio") : `${o.chapters} ${t("tracks")}`))))));
}
async function shuffle() { S.cur = await api(`/api/tonies/${S.cur.id}/shuffle`, { method: "POST" }); renderTonie(); toast(t("shuffled")); }
async function swap(o) { S.cur = await api(`/api/tonies/${S.cur.id}/swap`, { method: "POST", json: { other_id: o.id } }); renderTonie(); toast(`${t("swap")}: ${o.name}`); }
async function copyTo(o) { await api(`/api/tonies/${S.cur.id}/copy`, { method: "POST", json: { target_id: o.id } }); toast(`${t("copy")}: ${o.name}`); }
async function rebuild() { S.cur = await api(`/api/tonies/${S.cur.id}/rebuild`, { method: "POST" }); renderStatus(); }
async function deleteTonie() {
  const x = S.cur;
  await api(`/api/tonies/${x.id}`, { method: "DELETE" });
  location.hash = "#tonies";
  toast(`${t("deleted")}: ${x.name}`, { undo: async () => { await api(`/api/tonies/${x.id}/restore`, { method: "POST" }); route(); } });
}

/* ---------- Bilder ---------- */
async function uploadImage(file, source = "upload") {
  if (file.size > 25e6) { toast(t("imageTooBig"), { err: true }); throw new Error("big"); }
  const f = new FormData(); f.append("file", file); f.append("source", source);
  return api("/api/images", { method: "POST", form: f });
}
function fileButton(ic, label, accept, onFile, extra = {}) {
  const input = h("input", { type: "file", accept, hidden: true, ...extra, onchange: (e) => e.target.files[0] && onFile(e.target.files[0]) });
  return h("label", { class: "btn" }, icon(ic), label, input);
}

/* Bild wählen – für Tonies, Titel und Sender. onPick(id|null) */
async function openImagePicker({ covers = [], onPick, noneLabel = t("coin") }) {
  const choose = async (id) => { S.sheetClose = null; closeSheet(); await onPick(id); };
  const body = h("div", {});
  let tab = "mine", editing = false;
  const tabs = h("div", { class: "seg" });
  const draw = async () => {
    tabs.replaceChildren(...[["mine", t("myImages")], ["cover", t("covers")], ["teddy", t("tonieImages")]].map(([k, l]) =>
      h("button", { class: tab === k ? "on" : "", onclick: () => { tab = k; editing = false; draw(); } }, l)));
    if (tab === "mine") {
      const { images } = await api("/api/images");
      const up = async (file) => { const r = await uploadImage(file); choose(r.id); };
      const grid = h("div", { class: "img-grid" }, ...images.map((i) => h("button", { class: editing ? "deletable" : "", style: { backgroundImage: `url("${i.url}")` }, title: i.label,
        onclick: async () => {
          if (!editing) return choose(i.id);
          await api(`/api/images/${i.id}`, { method: "DELETE" });
          toast(t("deleted"), { undo: async () => { await api(`/api/images/${i.id}/restore`, { method: "POST" }); } });
          draw();
        } }, editing ? h("span", { class: "del-badge" }, icon("trash-2", "sm")) : "")));
      body.replaceChildren(
        h("div", { class: "btns" }, fileButton("camera", t("camera"), "image/*", up, { capture: "environment" }), fileButton("image", t("photo"), "image/*", up)),
        grid,
        h("div", { class: "btns", style: { marginTop: "12px" } },
          h("button", { class: "btn", onclick: () => choose(null) }, noneLabel),
          images.length ? h("button", { class: "btn" + (editing ? " primary" : ""), onclick: () => { editing = !editing; draw(); } },
            icon(editing ? "check" : "pencil"), editing ? t("done") : t("editImages")) : ""));
    } else if (tab === "cover") {
      const uniq = [...new Map(covers.map((c) => [c.id, c])).values()];
      body.replaceChildren(uniq.length ? h("div", { class: "img-grid" }, ...uniq.map((c) => h("button", { style: { backgroundImage: `url("${c.url}")` }, onclick: () => choose(c.id) })))
        : h("p", { class: "empty" }, t("noCovers")));
    } else {
      const grid = h("div", { class: "img-grid" });
      const search = h("input", { type: "search", placeholder: t("searchTonie") });
      let timer;
      const run = async () => {
        const { results } = await api(`/api/teddyimages?q=${encodeURIComponent(search.value)}`);
        grid.replaceChildren(...results.map((r) => h("button", { style: { backgroundImage: `url("${r.pic}")` }, title: r.title, onclick: async () => {
          const res = await api("/api/images/import", { method: "POST", json: { url: r.pic, title: r.title } });
          choose(res.id);
        } })));
        if (!results.length) grid.append(h("p", { class: "empty" }, t("nothing")));
      };
      search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 300); });
      body.replaceChildren(search, h("p", { class: "muted small" }, t("needsInternet")), grid);
      run();
    }
  };
  openSheet(t("image"), tabs, body);
  draw();
}

/* ---------- Bibliothek ---------- */
async function viewLibrary(params) {
  setHeader(t("library"));
  const nav = NAV;
  const [data, imp, src] = await Promise.all([api("/api/media"), api("/api/import/jobs").catch(() => ({ jobs: [], enabled: false })),
    api("/api/sources/available", { quiet: true }).catch(() => ({ available: false }))]);
  if (nav !== NAV) return;
  S.media = data.media; S.kinds = data.kinds;
  if (params && params.get("geteilt") !== null) {
    toast(t("shared", { n: params.get("geteilt") }) + (+params.get("fehler") ? " · " + t("errN", { n: params.get("fehler") }) : ""), { err: +params.get("fehler") > 0 });
    history.replaceState(null, "", "#bibliothek");
  }
  const progress = h("div", {});
  const storyName = h("input", { type: "text", placeholder: t("storyName"), hidden: true });
  const multi = h("input", { type: "checkbox", onchange: (e) => (storyName.hidden = !e.target.checked) });
  const multiRow = h("label", { class: "toggle compact", hidden: S.uploadKind !== "geschichte" }, h("span", {}, icon("layers"), t("oneStory")), multi);
  const input = h("input", { type: "file", multiple: true, hidden: true, accept: "audio/*,.opus,.ogg,.mp3,.m4a,.m4b,.flac,.wav,.taf,.webm",
    onchange: (e) => doUpload([...e.target.files], progress,
      S.uploadKind === "geschichte" && multi.checked ? storyName.value.trim() || e.target.files[0]?.name.replace(/\.[^.]+$/, "") : "") });
  const kindSeg = segChoice([["lied", h("span", {}, icon("music"), t("asSong"))], ["geschichte", h("span", {}, icon("book-open"), t("asStory"))]],
    S.uploadKind, (k) => { S.uploadKind = k; multiRow.hidden = k !== "geschichte"; if (k !== "geschichte") { multi.checked = false; storyName.hidden = true; } });
  const linkRow = imp.enabled ? (() => {
    const link = h("input", { type: "url", placeholder: t("pasteLink") });
    return h("form", { class: "link-row", onsubmit: async (e) => {
      e.preventDefault();
      if (!link.value.trim()) return;
      const r = await api("/api/import/web", { method: "POST", json: { text: link.value } });
      link.value = ""; toast(r.message); viewLibrary();
    } }, link, h("button", { class: "btn", type: "button", "aria-label": t("ytSearch"), onclick: openYtSearch }, icon("search")),
      h("button", { class: "btn primary", type: "submit", "aria-label": t("importStart") }, icon("download")));
  })() : "";
  const upload = h("div", { class: "card compact-card" }, kindSeg, multiRow, storyName,
    h("div", { class: src.available ? "btns" : "btns one" },
      h("label", { class: "btn primary" }, icon("upload"), t("upload"), input),
      src.available ? btn("package", t("fromTonies"), openSources) : ""),
    linkRow, progress);
  const newArea = renderNewArea(imp.jobs || [], S.media.filter((m) => m.is_new));
  const list = h("ul", { class: "list" });
  const draw = () => {
    const q = S.libSearch.toLowerCase();
    const groups = groupMedia(S.media.filter((m) => matches(m, q, S.libFilter, S.libUnused)));
    list.replaceChildren(...groups.map((g) => g.single ? mediaRow(g.single) : groupRow(g)));
    if (!groups.length) list.append(h("p", { class: "empty" }, S.media.length ? t("nothing") : t("emptyLib")));
  };
  const chips = kindChips(() => S.libFilter, (k) => { S.libFilter = k; draw(); });
  const search = searchRow(S.libSearch, (v) => { S.libSearch = v; draw(); }, S.libUnused, (u) => { S.libUnused = u; draw(); });
  draw();
  show("bibliothek", upload, newArea, h("div", { class: "card compact-card" }, search, chips, list));
  const active = (imp.jobs || []).some((j) => ["queued", "running"].includes(j.status));
  if (active) S.poll = setInterval(async () => {
    const j = await api("/api/import/jobs", { quiet: true }).catch(() => null);
    if (!j || nav !== NAV) return;
    if (JSON.stringify(j.jobs) !== JSON.stringify(imp.jobs)) viewLibrary();
  }, 3000);
}

const JOB_LABEL = { queued: "jobQueued", running: "jobRunning", confirm: "jobConfirm", error: "jobError", done: "jobDone" };
function renderNewArea(jobs, fresh) {
  const open = jobs.filter((j) => ["queued", "running", "confirm", "error"].includes(j.status));
  if (!open.length && !fresh.length) return "";
  const list = h("ul", { class: "list" });
  for (const j of open) {
    const p = j.playlist;
    list.append(h("li", { class: "row" },
      h("div", { class: "thumb" }, j.status === "running" ? h("span", { class: "spin" }) : icon(j.status === "error" ? "triangle-alert" : j.kind === "playlist" ? "list-music" : "square-play")),
      h("div", { class: "main" }, h("div", { class: "t" }, p && p.title ? p.title : j.ref),
        h("div", { class: "s" + (j.status === "error" ? " err-text" : "") },
          dot(t(JOB_LABEL[j.status]), j.status === "confirm" && p ? t("playlistAsk", { n: p.count }) : j.step, j.error))),
      j.status === "confirm" ? h("div", { class: "confirm-btns" },
        h("button", { class: "btn small-btn", onclick: async () => {
          const r = await api(`/api/import/jobs/${j.id}/confirm`, { method: "POST", json: { kind: "lied" } }); toast(`+${r.queued}`); viewLibrary();
        } }, icon("music", "sm"), t("asSongs")),
        h("button", { class: "btn small-btn primary", onclick: async () => {
          const r = await api(`/api/import/jobs/${j.id}/confirm`, { method: "POST", json: { as_story: true } }); toast(`+${r.queued}`); viewLibrary();
        } }, icon("book-open", "sm"), t("asOneStory"))) : "",
      j.status === "error" ? iconBtn("refresh-cw", t("retry"), async () => { await api(`/api/import/jobs/${j.id}/retry`, { method: "POST" }); viewLibrary(); }) : "",
      j.status !== "running" ? iconBtn("x", t("cancel"), async () => { await api(`/api/import/jobs/${j.id}`, { method: "DELETE" }); viewLibrary(); }) : ""));
  }
  for (const m of fresh) {
    list.append(h("li", { class: "row clickable", onclick: () => editMedia(m) },
      thumb(m.cover, kindIcon(m.kind)),
      h("div", { class: "main" }, h("div", { class: "t" }, m.title),
        h("div", { class: "s" }, dot(m.artist, m.net_duration < m.duration - 1 ? `${fmt(m.net_duration)} / ${fmt(m.duration)}` : fmt(m.duration),
          m.version === "song" ? t("songVersion") : m.version === "video" ? t("videoVersion") : ""))),
      iconBtn("scissors", t("trim"), () => openTrimmer(m)),
      iconBtn("plus", t("toTonie"), () => putOnTonie(m)),
      iconBtn("check", t("dismiss"), async () => { await api(`/api/media/${m.id}`, { method: "PATCH", json: { is_new: false } }); viewLibrary(); })));
  }
  return h("div", { class: "card compact-card" }, h("h3", { class: "first" }, t("newArea")), list);
}

/* ---------- YouTube-Music-Suche (Vorhören ohne Download, spulbar) ---------- */
function openYtSearch() {
  let kind = "songs", timer;
  const q = h("input", { type: "search", placeholder: t("ytSearch") });
  const list = h("ul", { class: "list" });
  const run = async () => {
    if (q.value.trim().length < 2) return;
    list.replaceChildren(h("p", { class: "center" }, h("span", { class: "spin" })));
    const r = await api(`/api/yt/search?kind=${kind}&q=${encodeURIComponent(q.value.trim())}`).catch(() => ({ results: [] }));
    list.replaceChildren(...r.results.map((x) => x.browseId
      ? h("li", { class: "row clickable", onclick: () => openYtAlbum(x) }, thumb(x.thumb, "disc-3"),
          h("div", { class: "main" }, h("div", { class: "t" }, x.title), h("div", { class: "s" }, dot(x.artists.join(", "), x.year, x.album_type))),
          icon("chevron-right", "muted"))
      : ytTrackRow(x)));
    if (!r.results.length) list.append(h("p", { class: "empty" }, t("nothing")));
  };
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 450); });
  const seg = segChoice([["songs", t("songs")], ["albums", t("albums")], ["videos", t("videos")]], kind, (v) => { kind = v; run(); });
  openSheet(t("ytSearch"), q, seg, list);
  q.focus();
}

function ytTrackRow(x, sub = "") {
  const dl = h("button", { class: "row-btn", "aria-label": t("importStart"), onclick: async (e) => {
    e.stopPropagation();
    const r = await api("/api/yt/import", { method: "POST", json: { videoId: x.videoId } });
    dl.replaceChildren(icon("check")); dl.disabled = true; toast(r.message);
  } }, icon("download"));
  return h("li", { class: "row" }, x.thumb ? thumb(x.thumb, "music") : "",
    h("div", { class: "main" }, h("div", { class: "t" }, x.title),
      h("div", { class: "s" }, dot(sub || (x.artists || []).join(", "), x.album, x.duration ? fmt(x.duration) : ""))),
    playBtn("y" + x.videoId, `/api/yt/preview/${x.videoId}`, x.title), dl);
}

async function openYtAlbum(a) {
  const body = h("div", {}, h("p", { class: "center" }, h("span", { class: "spin" })));
  openSheet(a.title, body);
  const info = await api(`/api/yt/album/${a.browseId}`);
  const load = (asStory) => async () => {
    const r = await api("/api/yt/import", { method: "POST", json: { browseId: a.browseId, as_story: asStory } });
    closeSheet(); toast(r.message); viewLibrary();
  };
  const total = info.tracks.reduce((n, x) => n + (x.duration || 0), 0);
  if (!info.tracks.length) {
    body.replaceChildren(h("div", { class: "row" }, thumb(info.thumb, "disc-3"), h("div", { class: "main muted small" }, info.artists.join(", "))),
      h("p", { class: "warn-text small" }, t("albumLocked", { n: info.unavailable })));
    return;
  }
  body.replaceChildren(
    h("div", { class: "row" }, thumb(info.thumb, "disc-3"), h("div", { class: "main muted small" },
      dot(info.artists.join(", "), info.year, `${info.tracks.length} ${t("tracks")}`, fmtLong(total)))),
    h("div", { class: "btns" }, btn("book-open", t("asOneStory"), load(true), "btn primary"), btn("music", t("asSongs"), load(false))),
    h("ul", { class: "list" }, ...info.tracks.map((x, i) => ytTrackRow(x, String(i + 1)))));
}

async function putOnTonie(m) {
  if (!S.tonies.length) S.tonies = (await api("/api/tonies")).tonies;
  pickTonie(t("toTonie"), S.tonies.filter((x) => !x.archived), async (o) => {
    await api(`/api/tonies/${o.id}/append`, { method: "POST", json: { media_ids: [m.id] } });
    toast(`${m.title} → ${o.name}`); viewLibrary();
  });
}

/* Tonies, auf denen ein Titel liegt – antippen springt zum Tonie */
const goTonie = (id) => { closeSheet(); location.hash = `#tonie/${id}`; };
function tonieChips(list) {
  return h("div", { class: "tonie-chips" }, ...list.map((x) => h("button", { class: "chip tonie-chip", onclick: () => goTonie(x.id) },
    h("i", { style: { background: x.hex } }), x.name)));
}
function usedBadge(list) {
  if (!list.length) return "";
  return h("button", { class: "used", title: t("onTonies"), onclick: (e) => {
    e.stopPropagation();
    if (list.length === 1) return goTonie(list[0].id);
    openSheet(t("onTonies"), h("ul", { class: "list nav-list" }, ...list.map((x) => h("li", { class: "row clickable nav-row", onclick: () => goTonie(x.id) },
      h("i", { class: "dot", style: { background: x.hex } }), h("div", { class: "main t" }, x.name), icon("chevron-right", "muted")))));
  } }, String(list.length));
}

function mediaRow(m, inGroup) {
  return h("li", { class: "row clickable" + (inGroup ? " indent" : ""), onclick: () => editMedia(m) },
    thumb(m.cover, kindIcon(m.kind)),
    h("div", { class: "main" }, h("div", { class: "t" }, m.title),
      h("div", { class: "s" }, dot(m.chapters > 1 ? `${m.chapters} ${t("chapters")}` : "", inGroup ? "" : m.artist, fmt(m.net_duration),
        m.cuts.length ? t("net") : ""))),
    usedBadge(m.tonies),
    playBtn("l" + m.id, m.audio, m.title || m.name),
    iconBtn("trash-2", t("del"), () => deleteMedia([m], m.title)));
}

function groupRow(g) {
  const used = [...new Map(g.parts.flatMap((p) => p.tonies).map((x) => [x.id, x])).values()];
  return h("li", { class: "row clickable", onclick: () => openGroup(g) },
    thumb(g.cover, kindIcon(g.kind)),
    h("div", { class: "main" }, h("div", { class: "t" }, g.album),
      h("div", { class: "s" }, dot(`${g.parts.length} ${t("parts")}`, fmt(g.duration)))),
    usedBadge(used),
    iconBtn("trash-2", t("del"), () => deleteMedia(g.parts, g.album)));
}

async function deleteMedia(items, label) {
  const ids = items.map((m) => m.id);
  await api("/api/media/delete", { method: "POST", json: { ids } });
  closeSheet();
  viewLibrary();
  toast(`${t("deleted")}: ${label}`, { undo: async () => { await api("/api/media/restore", { method: "POST", json: { ids } }); viewLibrary(); } });
}

function openGroup(g) {
  const album = h("input", { type: "text", value: g.album });
  const list = h("ul", { class: "list" }, ...g.parts.map((p) => {
    const li = mediaRow(p, true);
    li.prepend(h("span", { class: "handle" }, icon("grip-vertical")));
    li.dataset.id = p.id;
    return li;
  }));
  if (window.Sortable) Sortable.create(list, { handle: ".handle", animation: 150, onEnd: async () => {
    const ids = [...list.children].map((li) => +li.dataset.id);
    await Promise.all(ids.map((id, i) => api(`/api/media/${id}`, { method: "PATCH", json: { album_pos: i } })));
  } });
  const sortByName = btn("arrow-down-a-z", t("sortByName"), async () => {
    const ids = [...g.parts].sort((a, b) => natCmp(a.title, b.title) || natCmp(a.orig_name || "", b.orig_name || "")).map((p) => p.id);
    await Promise.all(ids.map((id, i) => api(`/api/media/${id}`, { method: "PATCH", json: { album_pos: i } })));
    closeSheet(); toast(t("saved")); viewLibrary();
  });
  openSheet(g.album,
    h("label", { class: "field" }, t("album"), album), sortByName, list,
    h("div", { class: "btns" },
      btn("image", t("image"), () => openImagePicker({ covers: g.parts.filter((p) => p.cover).map((p) => ({ id: p.cover_id, url: p.cover })), noneLabel: t("none"),
        onPick: async (id) => { await Promise.all(g.parts.map((p) => api(`/api/media/${p.id}`, { method: "PATCH", json: { cover_id: id } }))); viewLibrary(); } })),
      btn("check", t("save"), async () => {
        if (album.value.trim() && album.value !== g.album) await Promise.all(g.parts.map((p) => api(`/api/media/${p.id}`, { method: "PATCH", json: { album: album.value.trim() } })));
        closeSheet(); viewLibrary();
      }, "btn primary")),
    btn("trash-2", t("del"), () => deleteMedia(g.parts, g.album), "btn danger block"));
}

async function doUpload(files, progress, album) {
  if (!files.length) return;
  if (album) files = [...files].sort((a, b) => natCmp(a.name, b.name));   // Teil 1, 2, … 10 in richtiger Reihenfolge
  let ok = 0, dup = 0, bad = [];
  for (let i = 0; i < files.length; i++) {
    progress.replaceChildren(h("p", { class: "small" }, h("span", { class: "spin" }), ` ${i + 1}/${files.length} · ${files[i].name}`));
    const f = new FormData(); f.append("files", files[i]); f.append("kind", album ? "geschichte" : S.uploadKind);
    if (album) { f.append("album", album); f.append("album_pos", i); }
    try {
      const { results } = await api("/api/media", { method: "POST", form: f });
      for (const r of results) r.status === "neu" ? ok++ : r.status === "doppelt" ? dup++ : bad.push(`${r.name}: ${r.message}`);
    } catch (e) { bad.push(files[i].name); }
  }
  progress.replaceChildren();
  toast(dot(t("newN", { n: ok }), dup ? t("dupN", { n: dup }) : "", bad.length ? t("errN", { n: bad.length }) + ": " + bad.join("; ") : ""),
    { err: bad.length > 0, ms: bad.length ? 9000 : 3500 });
  viewLibrary();
}

function editMedia(m) {
  const title = h("input", { type: "text", value: m.title });
  const artist = h("input", { type: "text", value: m.artist });
  const album = h("input", { type: "text", value: m.album });
  let kind = m.kind;
  const coverBtn = h("button", { class: "thumb big-thumb", style: m.cover ? { backgroundImage: `url("${m.cover}")` } : {},
    onclick: () => openImagePicker({ covers: m.cover ? [{ id: m.cover_id, url: m.cover }] : [], noneLabel: t("none"),
      onPick: async (id) => { await api(`/api/media/${m.id}`, { method: "PATCH", json: { cover_id: id } }); viewLibrary(); } }) }, m.cover ? "" : icon("image"));
  const seg = h("div", { class: "seg" });
  const drawSeg = () => seg.replaceChildren(
    h("button", { class: kind === "lied" ? "on" : "", onclick: () => { kind = "lied"; drawSeg(); } }, icon("music"), t("asSong")),
    h("button", { class: kind === "geschichte" ? "on" : "", onclick: () => { kind = "geschichte"; drawSeg(); } }, icon("book-open"), t("asStory")));
  drawSeg();
  const yt = m.origin === "youtube";
  const tools = h("div", { class: "btns" },
    btn("scissors", t("trim"), () => openTrimmer(m)),
    btn("plus", t("toTonie"), () => putOnTonie(m)),
    yt && m.source_chapters > 1 && !m.clip ? btn("split", t("splitShort"), async () => {
      const r = await api(`/api/media/${m.id}/split`, { method: "POST" }); closeSheet(); toast(`+${r.created}`); viewLibrary();
    }) : "",
    yt && m.source_chapters > 1 && !m.clip && m.chapters < 2 ? btn("list-ordered", t("useChapters", { n: m.source_chapters }), async () => {
      await api(`/api/media/${m.id}/use-chapters`, { method: "POST" }); closeSheet(); toast(t("saved")); viewLibrary();
    }) : "",
    yt && m.alt_video_id ? btn("refresh-cw", t("switchTo", { x: m.version === "song" ? t("videoVersion") : t("songVersion") }), async () => {
      await api(`/api/media/${m.id}/version`, { method: "POST" }); closeSheet(); toast(t("jobQueued")); viewLibrary();
    }) : "",
    yt ? btn("rotate-ccw", t("refetchSb"), async () => {
      const r = await api(`/api/media/${m.id}/sponsorblock`, { method: "POST" }); toast(`SponsorBlock: ${r.segments}`); closeSheet(); viewLibrary();
    }) : "",
    yt && m.source_url ? h("a", { class: "btn", href: m.source_url, target: "_blank", rel: "noopener" }, icon("external-link"), t("openSource")) : "");
  openSheet(m.title,
    h("div", { class: "row" }, coverBtn, h("div", { class: "main muted small" },
      dot(m.net_duration < m.duration - 1 ? `${fmt(m.net_duration)} (${t("orig")} ${fmt(m.duration)})` : fmt(m.duration),
        m.chapters > 1 ? `${m.chapters} ${t("chapters")}` : "", m.version === "song" ? t("songVersion") : m.version === "video" ? t("videoVersion") : ""))),
    m.tonies.length ? h("div", { class: "lbl" }, t("onTonies")) : "", m.tonies.length ? tonieChips(m.tonies) : "",
    tools,
    h("label", { class: "field" }, t("title"), title), h("label", { class: "field" }, t("artist"), artist),
    h("label", { class: "field" }, t("album"), album), seg,
    btn("check", t("save"), async () => {
      await api(`/api/media/${m.id}`, { method: "PATCH", json: { title: title.value, artist: artist.value, album: album.value, kind } });
      closeSheet(); viewLibrary();
    }, "btn primary block"),
    btn("trash-2", t("del"), () => deleteMedia([m], m.title), "btn danger block"));
}

/* ---------- Trimmer (nicht-destruktiv: speichert nur Schnittbereiche) ---------- */
const CUT_COLORS = { manual: "rgba(229,57,53,.32)", silence: "rgba(120,120,120,.35)", sb: "rgba(251,140,0,.35)" };
const cutColor = (origin) => CUT_COLORS[String(origin).startsWith("sb:") ? "sb" : origin] || CUT_COLORS.manual;

async function openTrimmer(m) {
  if (!window.WaveSurfer) { toast("wavesurfer?", { err: true }); return; }
  const offset = m.clip ? (m.clip_start || 0) : 0;
  const full = await api(`/api/media/${m.id}`).catch(() => null);   // aktuelle Schnitte
  const media = full || m;
  const wave = h("div", { class: "wave" }, h("p", { class: "center small muted" }, h("span", { class: "spin" })));
  const timeEl = h("span", { class: "small muted" }, "0:00");
  const playB = h("button", { class: "btn primary" }, icon("play"));
  const legend = h("div", { class: "legend small" },
    h("span", {}, h("i", { style: { background: CUT_COLORS.sb } }), "SponsorBlock"),
    h("span", {}, h("i", { style: { background: CUT_COLORS.silence } }), "Stille"),
    h("span", {}, h("i", { style: { background: CUT_COLORS.manual } }), "manuell"));
  openSheet(t("trim") + ": " + m.title, wave, h("div", { class: "trim-bar" }, playB, timeEl), legend,
    h("div", { class: "btns" },
      btn("scissors", t("cutStart"), () => addCut(0, ws.getCurrentTime())),
      btn("scissors", t("cutEnd"), () => addCut(ws.getCurrentTime(), ws.getDuration()))),
    h("div", { class: "btns" },
      btn("plus", t("cutAdd"), () => { const c = ws.getCurrentTime(); addCut(c, Math.min(ws.getDuration(), c + 5)); }),
      btn("trash-2", t("cutDel"), () => { if (selected) { selected.remove(); selected = null; } })),
    h("p", { class: "muted small" }, t("cutHint")),
    h("div", { class: "btns" },
      btn("rotate-ccw", t("reset"), async () => { await api(`/api/media/${m.id}/cuts/reset`, { method: "POST" }); closeSheet(); toast(t("reset")); openTrimmer(m); }),
      btn("check", t("save"), save, "btn primary")));

  const ws = WaveSurfer.create({ container: wave, height: 110, normalize: true, waveColor: "#8aa4e8", progressColor: "#1e3a8a",
    cursorColor: "#e53935", url: m.original || m.audio, dragToSeek: true });
  const regions = ws.registerPlugin(WaveSurfer.Regions.create());
  const origins = new Map();
  let selected = null;
  function addCut(a, b, origin = "manual") {
    if (b - a < 0.1) return;
    const r = regions.addRegion({ start: a, end: b, color: cutColor(origin), drag: true, resize: true });
    origins.set(r.id, origin);
    return r;
  }
  ws.on("decode", () => {
    wave.querySelector("p")?.remove();
    const cuts = (media.cuts || []).map((c) => [c[0] - offset, c[1] - offset, c[2]]).filter((c) => c[1] > 0);
    cuts.forEach((c) => addCut(Math.max(0, c[0]), c[1], c[2]));
    regions.enableDragSelection({ color: CUT_COLORS.manual });
  });
  regions.on("region-created", (r) => { if (!origins.has(r.id)) origins.set(r.id, "manual"); });
  regions.on("region-clicked", (r, e) => {
    e.stopPropagation();
    regions.getRegions().forEach((x) => x.element && x.element.classList.remove("sel"));
    selected = r; r.element && r.element.classList.add("sel");
  });
  ws.on("timeupdate", (time) => {
    timeEl.textContent = `${fmt(time)} / ${fmt(ws.getDuration())}`;
    if (!ws.isPlaying()) return;
    for (const r of regions.getRegions()) if (time >= r.start && time < r.end - 0.05) { ws.setTime(Math.min(r.end, ws.getDuration())); break; }
  });
  ws.on("play", () => playB.replaceChildren(icon("pause")));
  ws.on("pause", () => playB.replaceChildren(icon("play")));
  playB.addEventListener("click", () => ws.playPause());
  S.sheetClose = () => ws.destroy();
  async function save() {
    const cuts = regions.getRegions().map((r) => [r.start + offset, r.end + offset, origins.get(r.id) || "manual"]);
    await api(`/api/media/${m.id}`, { method: "PATCH", json: { cuts } });
    closeSheet(); toast(t("saved")); viewLibrary();
  }
}

/* Inhalte von Tonies übernehmen (von der Box gespeicherte TAFs) */
async function openSources() {
  const body = h("div", {}, h("p", { class: "center" }, h("span", { class: "spin" })));
  openSheet(t("sourcesTitle"), body);
  const { sources } = await api("/api/sources");
  if (!sources.length) { body.replaceChildren(h("p", { class: "empty" }, t("sourcesHint"))); return; }
  body.replaceChildren(h("p", { class: "muted small" }, t("sourcesHint")),
    h("ul", { class: "list" }, ...sources.map((s) => h("li", { class: "row clickable", onclick: () => openSource(s) },
      thumb(s.pic, "package"), h("div", { class: "main" }, h("div", { class: "t" }, s.title),
        h("div", { class: "s" }, dot(s.series, `${s.chapters.length} ${t("chapters")}`, fmt(s.duration)))),
      s.imported ? icon("check", "muted") : icon("chevron-right", "muted")))));
}

function openSource(s) {
  const sel = new Set();
  let kind = s.chapters.length > 1 && s.chapters.every((c) => c.end - c.start < 400) ? "lied" : "geschichte";
  const takeSel = h("button", { class: "btn primary", disabled: true, onclick: () => doImport("chapters") }, t("takeSel", { n: 0 }));
  const list = h("ul", { class: "list" }, ...s.chapters.map((c, i) => {
    const done = s.imported_chapters.includes(i);
    const cb = h("input", { type: "checkbox", disabled: done });
    return h("li", { class: "row clickable", onclick: (e) => {
      if (done) return;
      if (e.target !== cb) cb.checked = !cb.checked;
      cb.checked ? sel.add(i) : sel.delete(i);
      takeSel.disabled = !sel.size; takeSel.textContent = t("takeSel", { n: sel.size });
    } }, cb, h("div", { class: "main" }, h("div", { class: "t" }, c.title || `${s.title} ${i + 1}`),
      h("div", { class: "s" }, dot(fmt(c.end - c.start), done ? t("already") : ""))));
  }));
  const seg = h("div", { class: "seg" });
  const drawSeg = () => seg.replaceChildren(
    h("button", { class: kind === "lied" ? "on" : "", onclick: () => { kind = "lied"; drawSeg(); } }, icon("music"), t("asSong")),
    h("button", { class: kind === "geschichte" ? "on" : "", onclick: () => { kind = "geschichte"; drawSeg(); } }, icon("book-open"), t("asStory")));
  drawSeg();
  async function doImport(mode) {
    const r = await api("/api/sources/import", { method: "POST", json: { path: s.path, mode, kind, chapters: [...sel] } });
    closeSheet(); toast(t("imported", { n: r.created })); viewLibrary();
  }
  openSheet(s.title, h("div", { class: "row" }, thumb(s.pic, "package"), h("div", { class: "main muted small" }, dot(s.series, fmt(s.duration)))),
    seg, h("div", { class: "btns" },
      h("button", { class: "btn", disabled: s.imported, onclick: () => doImport("whole") }, icon("download"), t("takeAll")), takeSel),
    list);
}

/* ---------- Radio ---------- */
async function viewRadio(sub) {
  setHeader(t("radio"));
  const nav = NAV;
  const seg = segChoice([["", h("span", {}, icon("radio"), t("stations"))], ["podcasts", h("span", {}, icon("podcast"), t("podcasts"))]],
    sub || "", (v) => (location.hash = v ? "#radio/podcasts" : "#radio"));
  if (sub === "podcasts") {
    const { podcasts: list } = await api("/api/podcasts");
    if (nav !== NAV) return;
    show("radio", seg,
      btn("plus", t("addPodcast"), openPodcastSearch, "btn primary block"),
      h("div", { class: "card compact-card" }, list.length ? h("ul", { class: "list" }, ...list.map((p) => h("li", { class: "row clickable", onclick: () => openPodcast(p.id) },
        thumb(p.image, "podcast"), h("div", { class: "main" }, h("div", { class: "t" }, p.title),
          h("div", { class: "s" + (p.error ? " err-text" : "") }, p.error || dot(`${p.count} ${t("episodes")}`, p.tonie ? `→ ${p.tonie.name}` : "", p.status))),
        icon("chevron-right", "muted"))))
        : h("p", { class: "empty" }, t("noPodcasts"))));
    if (list.some((p) => p.status)) S.poll = setInterval(() => nav === NAV && viewRadio("podcasts"), 4000);
    return;
  }
  const { stations } = await api("/api/stations");
  if (nav !== NAV) return;
  show("radio", seg,
    btn("plus", t("station"), () => editStation(null), "btn primary block"),
    h("div", { class: "card compact-card" }, stations.length ? h("ul", { class: "list" }, ...stations.map((s) => h("li", { class: "row clickable", onclick: () => editStation(s) },
      thumb(s.image, "radio"), h("div", { class: "main" }, h("div", { class: "t" }, s.name)), playBtn("s" + s.id, s.url, s.title || s.name))))
      : h("p", { class: "empty" }, t("noStations"))),
    h("p", { class: "muted small center" }, t("radioHint")));
}

async function openPodcastSearch() {
  const results = h("ul", { class: "list" });
  const q = h("input", { type: "search", placeholder: t("searchPodcast") });
  const feed = h("input", { type: "url", placeholder: "https://…/feed.xml" });
  let timer;
  q.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (q.value.trim().length < 3) return;
      results.replaceChildren(h("p", { class: "center" }, h("span", { class: "spin" })));
      const r = await api(`/api/podcasts/search?q=${encodeURIComponent(q.value.trim())}`).catch(() => ({ results: [] }));
      results.replaceChildren(...r.results.map((x) => h("li", { class: "row clickable", onclick: () => subscribeSheet(x) },
        thumb(x.image, "podcast"), h("div", { class: "main" }, h("div", { class: "t" }, x.title), h("div", { class: "s" }, x.author)),
        icon("plus", "muted"))));
      if (!r.results.length) results.append(h("p", { class: "empty" }, t("nothing")));
    }, 400);
  });
  openSheet(t("addPodcast"), q, results,
    h("div", { class: "lbl" }, icon("rss"), t("feedUrl")),
    h("form", { class: "link-row", onsubmit: (e) => { e.preventDefault(); if (feed.value.trim()) subscribeSheet({ title: feed.value.trim(), feed: feed.value.trim() }); } },
      feed, h("button", { class: "btn primary", type: "submit" }, icon("check"))));
  q.focus();
}

async function tonieOptions(current) {
  if (!S.tonies.length) S.tonies = (await api("/api/tonies")).tonies;
  return [[null, t("noTonie")], ...S.tonies.filter((x) => !x.archived).map((x) => [x.id, x.name])].map(([v, l]) =>
    h("option", { value: v ?? "", selected: (current ?? null) === v }, l));
}

async function subscribeSheet(x) {
  let keep = 10, newest = true;
  const sel = h("select", {}, ...(await tonieOptions(null)));
  openSheet(x.title,
    x.image ? h("div", { class: "row" }, thumb(x.image, "podcast"), h("div", { class: "main muted small" }, x.author || "")) : "",
    h("label", { class: "field" }, t("onTonie"), sel),
    h("div", { class: "lbl" }, t("keepN")), segChoice([[3, "3"], [5, "5"], [10, "10"], [20, "20"]], keep, (v) => (keep = v)),
    h("div", { class: "lbl" }, t("order")), segChoice([[true, t("newestFirst")], [false, t("oldestFirst")]], newest, (v) => (newest = v)),
    btn("check", t("subscribe"), async () => {
      await api("/api/podcasts", { method: "POST", json: { feed: x.feed, tonie_id: sel.value ? +sel.value : null, keep, newest_first: newest } });
      closeSheet(); location.hash = "#radio/podcasts"; viewRadio("podcasts");
    }, "btn primary block"));
}

async function openPodcast(id) {
  const p = await api(`/api/podcasts/${id}`);
  const patch = async (v) => { await api(`/api/podcasts/${id}`, { method: "PATCH", json: v }); toast(t("saved")); };
  const sel = h("select", { onchange: (e) => patch({ tonie_id: e.target.value ? +e.target.value : null }) }, ...(await tonieOptions(p.tonie ? p.tonie.id : null)));
  openSheet(p.title,
    h("div", { class: "row" }, thumb(p.image, "podcast"), h("div", { class: "main muted small" },
      dot(p.author, `${p.count} ${t("episodes")}`), p.error ? h("div", { class: "err-text" }, p.error) : "")),
    h("label", { class: "field" }, t("onTonie"), sel),
    h("div", { class: "lbl" }, t("keepN")), segChoice([[3, "3"], [5, "5"], [10, "10"], [20, "20"]], p.keep, (v) => patch({ keep: v })),
    h("div", { class: "lbl" }, t("order")), segChoice([[true, t("newestFirst")], [false, t("oldestFirst")]], p.newest_first, (v) => patch({ newest_first: v })),
    h("div", { class: "btns" },
      btn("refresh-cw", t("refresh"), async () => { await api(`/api/podcasts/${id}/sync`, { method: "POST" }); closeSheet(); toast(t("refresh")); viewRadio("podcasts"); }),
      btn("x", t("unsubscribe"), async () => { await api(`/api/podcasts/${id}`, { method: "DELETE" }); closeSheet(); toast(t("unsubscribe")); viewRadio("podcasts"); }, "btn danger")),
    h("ul", { class: "list" }, ...p.episodes.map((m) => h("li", { class: "row" }, thumb(m.cover, "podcast"),
      h("div", { class: "main" }, h("div", { class: "t" }, m.title), h("div", { class: "s" }, fmt(m.duration))), playBtn("p" + m.id, m.audio, m.title || m.name)))));
}

function editStation(s) {
  const name = h("input", { type: "text", value: s ? s.name : "", placeholder: t("name") });
  const url = h("input", { type: "url", value: s ? s.url : "", placeholder: "https://…" });
  let imageId;
  const logo = h("button", { class: "thumb big-thumb", style: s && s.image ? { backgroundImage: `url("${s.image}")` } : {},
    onclick: () => openImagePicker({ noneLabel: t("none"), onPick: async (id) => {
      imageId = id;
      if (s) { await api(`/api/stations/${s.id}`, { method: "PATCH", json: { image_id: id } }); viewRadio(); }
    } }) }, s && s.image ? "" : icon("radio"));
  const result = h("span", { class: "small" });
  openSheet(s ? s.name : t("station"),
    h("div", { class: "row" }, logo, h("div", { class: "main" }, h("label", { class: "field" }, t("name"), name))),
    h("label", { class: "field" }, t("streamUrl"), url),
    h("div", { class: "btns" },
      btn("radio", t("test"), async () => {
        result.replaceChildren(h("span", { class: "spin" }));
        const r = await api("/api/stations/check", { method: "POST", json: { url: url.value } });
        result.replaceChildren(icon(r.ok ? "circle-check" : "triangle-alert"), " ", r.ok ? t("reachable") : t("unreachable"));
      }),
      btn("play", "", () => playToggle("edit", url.value))),
    h("p", { class: "center" }, result),
    btn("check", t("save"), async () => {
      const b = { name: name.value, url: url.value };
      if (imageId !== undefined) b.image_id = imageId;
      await api(s ? `/api/stations/${s.id}` : "/api/stations", { method: s ? "PATCH" : "POST", json: b });
      closeSheet(); viewRadio();
    }, "btn primary block"),
    s ? btn("trash-2", t("del"), async () => {
      await api(`/api/stations/${s.id}`, { method: "DELETE" });
      closeSheet(); viewRadio();
      toast(`${t("deleted")}: ${s.name}`, { undo: async () => { await api(`/api/stations/${s.id}/restore`, { method: "POST" }); viewRadio(); } });
    }, "btn danger block") : "");
}

/* ---------- Einstellungen ---------- */
function segChoice(options, current, onPick) {
  const wrap = h("div", { class: "seg" });
  const draw = (cur) => wrap.replaceChildren(...options.map(([v, label]) =>
    h("button", { class: v === cur ? "on" : "", onclick: () => { draw(v); onPick(v); } }, label)));
  draw(current);
  return wrap;
}

async function viewSettings(sub) {
  if (sub === "boxen") return viewBoxes();
  if (sub === "verlauf") return viewHistory();
  if (sub === "import") return viewImportSettings();
  setHeader(sub ? t("settings") : t("settings"), sub ? "#einstellungen" : "#tonies");
  const st = await api("/api/settings");
  const untested = st.tc_version && st.tc_version !== st.tc_tested;
  if (sub === "teddycloud") {
    setHeader("TeddyCloud", "#einstellungen");
    return show("einstellungen", h("div", { class: "card" },
      h("p", {}, icon(st.teddycloud ? "circle-check" : "triangle-alert"), " ", st.teddycloud ? `${t("connected")} · ${st.tc_version}` : t("offline")),
      untested ? h("p", { class: "warn-text small" }, t("untested", { x: st.tc_version })) : ""),
      h("ul", { class: "list card nav-list" },
        navRow("refresh-cw", t("syncAll"), "", null, async () => { await api("/api/sync", { method: "POST" }); toast(t("syncing")); }),
        navRow("external-link", t("openTc"), "", null, () => window.open(`https://${location.hostname}:8443/`, "_blank", "noopener"))));
  }
  if (sub === "pin") {
    setHeader(t("pin"), "#einstellungen");
    const pin = h("input", { type: "password", inputmode: "numeric", maxlength: 4, placeholder: "••••" });
    return show("einstellungen", h("div", { class: "card" },
      h("p", { class: "muted small" }, st.pin_set ? t("pinSet") : t("pinNone")), pin,
      h("div", { class: "btns", style: { marginTop: "10px" } },
        btn("lock", t("setPin"), async () => { await api("/api/settings/pin", { method: "POST", json: { pin: pin.value } }); toast(t("pinSet")); location.hash = "#einstellungen"; }, "btn primary"),
        h("button", { class: "btn", disabled: !st.pin_set, onclick: async () => { await api("/api/settings/pin", { method: "POST", json: { pin: "" } }); toast(t("pinNone")); location.hash = "#einstellungen"; } }, icon("lock-open"), t("removePin")))));
  }
  if (sub === "speicher") {
    setHeader(t("storage"), "#einstellungen");
    return show("einstellungen", h("ul", { class: "list card nav-list" },
      h("li", { class: "row nav-row" }, icon("hard-drive"), h("div", { class: "main t" }, "Teddy Manager"), h("span", { class: "muted small" }, fmtBytes(st.usage))),
      h("li", { class: "row nav-row" }, icon("hard-drive"), h("div", { class: "main t" }, t("free")), h("span", { class: "muted small" }, fmtBytes(st.free))),
      navRow("download", t("backup"), "", null, () => { location.href = "/api/backup"; })));
  }
  const imp = await api("/api/import/settings").catch(() => ({ enabled: false }));
  const langSeg = segChoice(Object.entries(LANGS).map(([k, v]) => [k, k.toUpperCase()]), LANG, async (k) => {
    LANG = k; try { localStorage.setItem("tm_lang", k); } catch (e) { /* egal */ }
    await api("/api/settings/lang", { method: "POST", json: { lang: k } }).catch(() => {});
    applyLangStatic(); viewSettings();
  });
  langSeg.classList.add("mini-seg");
  const upd = await api("/api/update-check", { quiet: true }).catch(() => ({}));
  const kidsToggle = h("input", { type: "checkbox", id: "kidsToggle", checked: st.kids, onchange: async (e) => {
    await api("/api/settings/kids", { method: "POST", json: { on: e.target.checked } }); S.kids = e.target.checked; updateKidsButton();
    toast(S.kids ? t("kidsOn") : t("kidsOff"));
  } });
  show("einstellungen", h("ul", { class: "list card nav-list" },
    h("li", { class: "row nav-row" }, icon("globe"), h("div", { class: "main t" }, t("language")), langSeg),
    h("li", { class: "row nav-row" }, icon("smile"), h("label", { class: "main t", for: "kidsToggle" }, t("kidsMode")), kidsToggle),
    st.boxlog.enabled ? navRow("clock", t("history"), st.boxlog.ok === false ? t("offline") : "", "#einstellungen/verlauf") : "",
    navRow("box", t("boxes"), "", "#einstellungen/boxen"),
    navRow("download", t("importTitle"), imp.enabled ? t("importOn") : t("importOff"), "#einstellungen/import"),
    navRow(st.teddycloud && !untested ? "circle-check" : "triangle-alert", "TeddyCloud", st.teddycloud ? st.tc_version : t("offline"), "#einstellungen/teddycloud"),
    navRow("lock", t("pin"), st.pin_set ? t("importOn") : t("importOff"), "#einstellungen/pin"),
    navRow("hard-drive", t("storage"), fmtBytes(st.usage), "#einstellungen/speicher"),
    navRow("info", t("help"), "", "#hilfe")),
    h("p", { class: "muted small center" }, `Teddy Manager ${st.version}`,
      upd.newer ? h("a", { href: upd.url, target: "_blank", rel: "noopener", class: "upd" }, " · " + t("updateAvail", { x: upd.latest })) : ""));
}

async function viewBoxes() {
  setHeader(t("boxes"), "#einstellungen");
  const { boxes: list } = await api("/api/boxes");
  const set = (id, body) => api(`/api/boxes/${id}`, { method: "PATCH", json: body }).then(() => toast(t("saved")));
  const vol = [[0, "25"], [1, "50"], [2, "75"], [3, "100 %"]];
  show("einstellungen", ...list.map((b, i) => {
    const name = h("input", { type: "text", value: b.name });
    name.addEventListener("change", () => set(b.id, { name: name.value }));
    return h("details", { class: "card fold", open: list.length === 1 || i === 0 },
      h("summary", {}, icon("box"), h("span", { class: "grow" }, b.name), icon("chevron-down", "muted fold-ic")),
      h("label", { class: "field" }, t("name"), name),
      b.evening.on ? h("h3", {}, t("dayValues")) : "",
      h("div", { class: "lbl" }, icon("speaker"), t("volSpk")), segChoice(vol, b.vol_spk, (v) => set(b.id, { vol_spk: v })),
      h("div", { class: "lbl" }, icon("headphones"), t("volHdp")), segChoice(vol, b.vol_hdp, (v) => set(b.id, { vol_hdp: v })),
      h("label", { class: "toggle compact" }, h("span", {}, icon("hand"), t("slap")),
        h("input", { type: "checkbox", checked: b.slap, onchange: (e) => set(b.id, { slap: e.target.checked }) })),
      h("div", { class: "lbl" }, t("slapDir")), segChoice([[false, t("back")], [true, t("forward")]], b.slap_back_left, (v) => set(b.id, { slap_back_left: v })),
      h("div", { class: "lbl" }, icon("sun"), t("led")), segChoice([[0, t("ledOn")], [2, t("ledDim")], [1, t("ledOff")]], b.led, (v) => set(b.id, { led: v })),
      eveningEditor(b, set),
      h("p", { class: "muted small" }, b.id));
  }), h("p", { class: "muted small" }, t("boxHint") + " " + t("battery")));
}

function eveningEditor(b, set) {
  const ev = b.evening;
  const wrap = h("div", { class: "evening" });
  const setEv = (v) => set(b.id, { evening: v });
  const timeIn = (key) => {
    const inp = h("input", { type: "time", value: ev[key], step: 300 });
    inp.addEventListener("change", () => inp.value && setEv({ [key]: inp.value }));
    return inp;
  };
  const vol = [[0, "25"], [1, "50"], [2, "75"], [3, "100 %"]];
  const draw = () => wrap.replaceChildren(
    h("label", { class: "toggle compact" }, h("span", { class: "strong" }, icon("moon"), t("evening"),
      b.evening_now ? h("span", { class: "pill" }, t("activeNow")) : ""),
      h("input", { type: "checkbox", checked: ev.on, onchange: (e) => { ev.on = e.target.checked; setEv({ on: ev.on }); draw(); } })),
    ...(ev.on ? [
      h("div", { class: "time-row" }, h("label", {}, t("from"), timeIn("start")), h("label", {}, t("to"), timeIn("end"))),
      h("div", { class: "lbl" }, icon("speaker"), t("volSpk")), segChoice(vol, ev.vol_spk, (v) => setEv({ vol_spk: v })),
      h("div", { class: "lbl" }, icon("headphones"), t("volHdp")), segChoice(vol, ev.vol_hdp, (v) => setEv({ vol_hdp: v })),
      h("div", { class: "lbl" }, icon("sun"), t("led")), segChoice([[0, t("ledOn")], [2, t("ledDim")], [1, t("ledOff")]], ev.led, (v) => setEv({ led: v })),
      h("p", { class: "muted small" }, t("eveningHint"))] : []));
  draw();
  return wrap;
}

function fold(title, ic, ...kids) {
  return h("details", { class: "card fold" }, h("summary", {}, icon(ic), h("span", { class: "grow" }, title), icon("chevron-down", "muted fold-ic")), ...kids);
}

async function viewImportSettings() {
  setHeader(t("importTitle"), "#einstellungen");
  const s = await api("/api/import/settings");
  const reload = () => viewImportSettings();
  const save = async (body) => { await api("/api/import/settings", { method: "POST", json: body }); toast(t("saved")); };
  const onoff = segChoice([[false, t("importOff")], [true, t("importOn")]], s.enabled, async (v) => {
    if (v) {
      openSheet(t("legalTitle"), h("p", {}, t("legalText")),
        btn("check", t("accept"), async () => { await save({ enabled: true, accepted: true }); closeSheet(); reload(); }, "btn primary block"),
        btn("", t("cancel"), () => { closeSheet(); reload(); }, "btn block"));
    } else { await save({ enabled: false }); reload(); }
  });
  const intro = h("div", { class: "card explain" },
    h("p", {}, t("importExplain")),
    h("ul", { class: "small" }, h("li", {}, t("importHow1")), h("li", {}, t("importHow2")), h("li", {}, t("importHow3"))),
    h("p", { class: "disclaimer small" }, icon("triangle-alert", "sm"), " ", t("legalText")));
  if (!s.enabled) return show("einstellungen", intro, h("div", { class: "card" }, onoff));
  const stx = s.status || {};
  const status = h("p", { class: "small " + (stx.ok === false ? "warn-text" : "muted") },
    s.ready ? dot(`yt-dlp ${stx.ytdlp || "?"}`, stx.message || "") : (stx.updating ? t("updating") : stx.message || t("updating")));
  const tokenEl = h("code", { class: "token" }, s.token);
  const sb = h("div", { class: "chips wrap" }, ...s.sb_all.map((c) => h("button", { class: "chip" + (s.yt_sb_categories.includes(c) ? " on" : ""), onclick: async (e) => {
    const set = new Set(s.yt_sb_categories); set.has(c) ? set.delete(c) : set.add(c);
    s.yt_sb_categories = [...set]; e.currentTarget.classList.toggle("on");
    await save({ yt_sb_categories: s.yt_sb_categories });
  } }, c)));
  const num = (key, label, factor = 1) => {
    const inp = h("input", { type: "number", min: 1, value: Math.round(+s[key] / factor) });
    inp.addEventListener("change", () => save({ [key]: String(Math.round(+inp.value * factor)) }));
    return h("label", { class: "field" }, label, inp);
  };
  const rules = h("textarea", { rows: 6, spellcheck: "false" }, s.yt_title_rules);
  rules.addEventListener("change", () => save({ yt_title_rules: rules.value }));
  const testVid = h("input", { type: "text", value: s.yt_test_video });
  testVid.addEventListener("change", () => save({ yt_test_video: testVid.value.trim() }));
  const cookieInput = h("input", { type: "file", accept: ".txt,text/plain", hidden: true, onchange: async (e) => {
    const f = new FormData(); f.append("file", e.target.files[0]);
    await api("/api/import/cookies", { method: "POST", form: f }); toast(t("saved")); reload();
  } });
  show("einstellungen", intro,
    h("div", { class: "card" }, onoff, status),
    fold(t("setupHelp"), "smartphone",
      h("p", { class: "muted small" }, t("setupShort")),
      h("div", { class: "btns" },
        h("a", { class: "btn primary", href: "/api/import/shortcut.json", download: "zum-tonie.json" }, icon("file-down"), t("shortcutShort")),
        h("a", { class: "btn", href: "#hilfe" }, icon("info"), t("help"))),
      h("div", { class: "lbl" }, icon("key-round"), t("token")),
      h("div", { class: "token-row" }, tokenEl, iconBtn("refresh-cw", t("newToken"), async () => { const r = await api("/api/import/token", { method: "POST" }); tokenEl.textContent = r.token; }))),
    fold(t("automatic"), "wand",
      h("label", { class: "toggle compact" }, h("span", {}, t("preferSong")),
        h("input", { type: "checkbox", checked: s.yt_prefer_song === "1", onchange: (e) => save({ yt_prefer_song: e.target.checked }) })),
      h("div", { class: "lbl" }, t("sbCats")), sb,
      num("yt_max_len", t("maxLen"), 60), num("yt_playlist_max", t("plMax"))),
    fold(t("advanced"), "sliders-horizontal",
      h("div", { class: "lbl" }, t("titleRulesShort")), h("p", { class: "muted small" }, t("titleRules")), rules,
      h("div", { class: "lbl" }, t("cookies")), h("p", { class: "muted small" }, t("cookiesHint")),
      h("div", { class: "btns" }, h("label", { class: "btn" }, icon("upload"), t("upCookies"), cookieInput),
        h("button", { class: "btn", disabled: !s.cookies, onclick: async () => { await api("/api/import/cookies", { method: "DELETE" }); reload(); } }, icon("trash-2"), t("delCookies"))),
      h("div", { class: "lbl" }, "yt-dlp"),
      h("p", { class: "muted small" }, dot(stx.ytdlp && `yt-dlp ${stx.ytdlp}`, stx.ejs && `ejs ${stx.ejs}`, stx.deno && `Deno ${stx.deno}`, stx.ytmusicapi && `ytmusicapi ${stx.ytmusicapi}`)),
      h("label", { class: "field" }, t("testVideo"), testVid),
      h("div", { class: "btns" },
        btn("refresh-cw", t("updateNow"), async () => { await api("/api/import/update", { method: "POST", json: {} }); toast(t("updating")); }),
        h("button", { class: "btn", disabled: !s.previous, onclick: async () => { await api("/api/import/rollback", { method: "POST" }); reload(); } }, icon("undo-2"), t("rollback")))));
}

/* ---------- Hilfe: Handy-Einrichtung ---------- */
function viewHelp() {
  setHeader(t("help"), "#einstellungen");
  const base = `http://${location.hostname}:8090`;
  const step = (n, ...kids) => h("li", {}, ...kids);
  show("hilfe", h("div", { class: "card help" },
    h("h3", { class: "first" }, "Neue Figur anlernen"),
    h("p", {}, "Tonies → Neu, dann die Figur auf eine Box legen. Nach ein paar Sekunden erscheint „Erkannt“. Bekannte Figuren, die die Box schon gesehen hat, stehen direkt darunter."),
    h("h3", {}, "Box spielt noch den alten Inhalt"),
    h("p", {}, "Die Box lädt neu, sobald sich der Inhalt ändert. Tonie abnehmen und wieder auflegen; hilft das nicht, die Box aus- und einschalten."),
    h("h3", {}, "Einschlafmodus und Abendmodus"),
    h("p", {}, "Einschlafmodus (im Tonie): wird über die gewählte Dauer leiser und hört dann auf – auch wenn die Playlist kürzer ist (sie wird wiederholt). Abendmodus (Einstellungen → Tonieboxen): ab der Uhrzeit gelten geringere Lautstärke und gedimmtes Licht, sobald die Box eingeschaltet wird."),
    h("h3", {}, "Podcasts"),
    h("p", {}, "Radio → Podcasts → Podcast abonnieren. Mit einem Tonie verknüpft, liegen dort immer die neuesten Folgen (Prüfung alle 3 Stunden)."),
    h("h3", {}, "Hörspiele aus vielen Dateien"),
    h("p", {}, "Bibliothek → Geschichte → Mehrteilig, Name eingeben, alle Dateien auswählen. Sie werden nach Dateinamen sortiert (Teil 2 vor Teil 10). Umsortieren in der Gruppe per Griff oder „Nach Name sortieren“."),
    h("h3", {}, "„Teilen → Zum Tonie“ mit HTTP Shortcuts"),
    h("p", {}, "Einmalig am Android-Handy einrichten. Danach schickt „Teilen“ in YouTube oder YouTube Music den Link an den Teddy Manager."),
    h("ol", {},
      step(1, "App „HTTP Shortcuts“ aus dem Play Store (oder F-Droid) installieren."),
      step(2, "Hier unter Einstellungen → Import per Link die Datei ", h("b", {}, "„Shortcut-Datei laden“"), " auf das Handy laden."),
      step(3, "In HTTP Shortcuts: Menü (⋮) → Import / Export → Aus Datei importieren → zum-tonie.json wählen."),
      step(4, "Fertig: Der Shortcut „Zum Tonie“ schickt einen POST an ", h("code", {}, `${base}/api/import`),
        " mit dem Token im Header ", h("code", {}, "X-Teddy-Token"), ". Der geteilte Text wird über die Variable „geteilter_text“ übergeben (Option „Wert aus dem Teilen-Dialog übernehmen“)."),
      step(5, "Testen: In YouTube Music bei einem Lied auf Teilen → HTTP Shortcuts → Zum Tonie. Es erscheint „Import gestartet“.")),
    h("h3", {}, "Ohne Datei einrichten"),
    h("ol", {},
      step(1, "Neue globale Variable: Typ Text, Schlüssel geteilter_text, unter Erweitert „Wert aus dem Teilen-Dialog übernehmen“ (Text) aktivieren."),
      step(2, "Neuer Shortcut „Zum Tonie“: Methode POST, URL ", h("code", {}, `${base}/api/import`), "."),
      step(3, "Request-Header: X-Teddy-Token = Token aus den Einstellungen."),
      step(4, "Request-Body: Eigener Text, Content-Type text/plain, Inhalt {geteilter_text} (Variable einfügen)."),
      step(5, "Antwort-Verarbeitung: als Toast anzeigen, Ausgabe = Antwort.")),
    h("h3", {}, "Hinweise"),
    h("ul", {},
      h("li", {}, "Funktioniert nur im Heim-WLAN."),
      h("li", {}, "Neuer Token in den Einstellungen → Shortcut-Datei neu laden und importieren."),
      h("li", {}, "Playlists und Alben werden im Teddy Manager unter Bibliothek → Neu bestätigt.")),
  ));
}

/* ---------- Kinderansicht ---------- */
function updateKidsButton() {
  let tab = $("#tab-kids");
  if (S.kids && !tab) {
    tab = h("a", { id: "tab-kids", href: "#kinder", "data-tab": "kinder" }, icon("smile", "ti"), h("span", { class: "tl" }, t("kidsTab")));
    $("#tabs").append(tab);
  } else if (!S.kids && tab) tab.remove();
}

async function viewKids() {
  setHeader("");
  const { tiles } = await api("/api/kids");
  let hold;
  const exit = h("button", { class: "kids-exit", "aria-label": t("exitKids") }, icon("lock"));
  const leave = async () => {
    const st = await api("/api/settings", { quiet: true }).catch(() => ({}));
    if (st.pin_set) { S.afterPin = "#tonies"; showPin(); } else location.hash = "#tonies";
  };
  // ohne PIN: 1,5 s gedrückt halten, damit Kinder nicht versehentlich herauskommen
  exit.addEventListener("pointerdown", () => { hold = setTimeout(leave, 1500); exit.classList.add("holding"); });
  ["pointerup", "pointerleave", "pointercancel"].forEach((ev) => exit.addEventListener(ev, () => { clearTimeout(hold); exit.classList.remove("holding"); }));
  const stage = h("div", { class: "kids-player", hidden: true });
  const grid = h("div", { class: "kids-grid" }, ...tiles.map((x) => h("button", { class: "kids-tile", style: { background: x.hex },
    onclick: () => kidsPlay(x, stage) }, h("div", { class: "kids-pic", style: x.image ? { backgroundImage: `url("${x.image}")` } : {} }),
    h("div", { class: "kids-name" }, x.name))));
  show("kinder", exit, grid, stage, tiles.length ? "" : h("p", { class: "empty" }, t("nothing")));
}

async function kidsPlay(x, stage) {
  if (x.radio) playToggle("st" + x.ruid, x.radio, x.name);
  else await playTag(x.ruid, x.name);
  $("#mini")?.remove();
  const pp = h("button", { class: "kids-big", "aria-label": "Play" }, icon(player.paused ? "play" : "pause"));
  pp.addEventListener("click", () => (player.paused ? player.play() : player.pause()));
  const sync = () => pp.isConnected && pp.replaceChildren(icon(player.paused ? "play" : "pause"));
  player.addEventListener("play", sync); player.addEventListener("pause", sync);
  const bar = h("input", { type: "range", min: 0, max: 1, step: 1, value: 0, class: "kids-range" });
  bar.addEventListener("input", () => { if (isFinite(player.duration)) player.currentTime = +bar.value; });
  player.addEventListener("timeupdate", () => { if (bar.isConnected && isFinite(player.duration)) { bar.max = player.duration; bar.value = player.currentTime; } });
  stage.replaceChildren(
    h("button", { class: "kids-close", "aria-label": "Close", onclick: () => { player.pause(); stage.hidden = true; } }, icon("x")),
    h("div", { class: "kids-cover", style: { background: `${x.hex} ${x.image ? `url("${x.image}") center/cover` : ""}` } }),
    h("div", { class: "kids-title" }, x.name),
    h("div", { class: "kids-controls" },
      h("button", { class: "kids-small", onclick: () => jumpChapter(-1) }, icon("chevron-left")), pp,
      h("button", { class: "kids-small", onclick: () => jumpChapter(1) }, icon("chevron-right"))),
    bar);
  stage.hidden = false;
}

/* ---------- Zuletzt aufgelegt (aus dem TeddyCloud-Log) ---------- */
let lastEventTs = null;
function relTime(ts) {
  const m = Math.round((Date.now() / 1000 - ts) / 60);
  if (m < 1) return t("justNow");
  if (m < 60) return t("minAgo", { n: m });
  const hh = Math.round(m / 60);
  return hh < 24 ? t("hAgo", { n: hh }) : new Date(ts * 1000).toLocaleDateString();
}
function placedBanner(ev) {
  $("#placed")?.remove();
  if (document.body.classList.contains("kids")) return;
  const open = ev.tonie_id ? () => (location.hash = `#tonie/${ev.tonie_id}`)
    : ev.type === "unbekannt" ? () => openLearn() : () => (location.hash = "#figuren");
  const el = h("div", { id: "placed" },
    h("div", { class: "thumb round", style: { background: `${ev.hex || "var(--line)"} ${ev.image ? `url("${ev.image}") center/cover` : ""}` } }),
    h("div", { class: "main" }, h("div", { class: "s" }, t("placedNow")), h("div", { class: "t" }, ev.name)),
    h("button", { class: "btn primary small-btn", onclick: () => { el.remove(); open(); } }, ev.type === "unbekannt" ? t("setup") : t("open")),
    iconBtn("x", "", () => el.remove()));
  document.body.append(el);
  setTimeout(() => el.remove(), 20000);
}
async function pollPlaced() {
  if (document.hidden) return;
  const r = await api("/api/events/latest", { quiet: true }).catch(() => null);
  if (!r || !r.event) return;
  if (lastEventTs !== null && r.event.ts > lastEventTs + 0.5) placedBanner(r.event);
  lastEventTs = Math.max(lastEventTs || 0, r.event.ts);
}

async function viewHistory() {
  setHeader(t("history"), "#einstellungen");
  const { events } = await api("/api/events?limit=60");
  show("einstellungen", h("ul", { class: "list card compact-card" }, ...events.map((e) => h("li", { class: "row clickable",
    onclick: () => (e.tonie_id ? (location.hash = `#tonie/${e.tonie_id}`) : null) },
    h("div", { class: "thumb round", style: { background: `${e.hex || "var(--line)"} ${e.image ? `url("${e.image}") center/cover` : ""}` } }),
    h("div", { class: "main" }, h("div", { class: "t" }, e.name), h("div", { class: "s" }, dot(relTime(e.ts), t(e.type === "custom" ? "customShort" : e.type)))))),
    events.length ? "" : h("p", { class: "empty" }, t("noHistory"))));
}

/* ---------- Start ---------- */
(async () => {
  try {
    const st = await (await fetch("/api/settings")).json();
    S.term = st.term; S.termPlural = st.term_plural; S.kids = !!st.kids;
    let stored = null; try { stored = localStorage.getItem("tm_lang"); } catch (e) { /* egal */ }
    if (!stored && st.lang && I18N[st.lang]) LANG = st.lang;
  } catch (e) { /* offline */ }
  applyLangStatic();
  updateKidsButton();
  route();
  pollPlaced();
  setInterval(pollPlaced, 4000);
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
