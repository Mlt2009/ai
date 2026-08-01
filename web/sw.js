/* Minimal service worker: makes the app installable and shell-cached. */
const CACHE = "atlas-v1";
const SHELL = ["/", "/style.css", "/app.js", "/manifest.json", "/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

/* Network-first so live data stays live; cache is the offline fallback. */
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || e.request.url.includes("/ws")) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
