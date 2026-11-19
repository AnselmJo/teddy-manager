// Minimaler Service Worker: macht die App installierbar und hält die Oberfläche offline verfügbar.
const CACHE = "tm-v11";
const SHELL = ["/", "/static/style.css?v=11", "/static/i18n.js?v=11", "/static/app.js?v=11", "/static/vendor/icons.svg?v=11", "/static/vendor/Sortable.min.js", "/static/icons/icon.svg"];
self.addEventListener("install", (e) => { e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/") || u.pathname === "/share") return;
  // Netzwerk zuerst, Cache nur als Rückfall
  e.respondWith(fetch(e.request).then((r) => {
    if (r.ok && SHELL.includes(u.pathname + u.search)) caches.open(CACHE).then((c) => c.put(e.request, r.clone()));
    return r;
  }).catch(() => caches.match(e.request)));
});
