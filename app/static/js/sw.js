/* Service Worker — International Road Services – Libya
 * Strategies:
 *   - App shell & versioned static assets ............ cache-first (cache name carries the build hash)
 *   - Public pages (navigations) ...................... network-first → cached copy → /offline
 *   - Public JSON (road / meta / home stats) .......... network-first → cached copy
 *   - Admin, auth, notifications, attachments, /me ... network-only, NEVER cached
 *   - /api/v1/reports/nearby (driving mode) ........... network-only: a POST whose body carries the driver's
 *     (rounded) position; never cached.
 *   - /api/v1/reports/alertable (driving mode) ........ network-only here: the page itself keeps the list in
 *     IndexedDB (offline-store.js) and revalidates it with If-None-Match.
 *   - Map tiles (cross-origin, viewed only) ........... cache-first, refreshed after TILE_MAX_AGE_MS, at most
 *     TILE_MAX_ENTRIES (oldest dropped). Only tiles the user has actually seen are kept: no bulk prefetching
 *     (OpenStreetMap tile usage policy).
 *   - /drive and /map ................................ network-first, offline copy kept EVEN for signed-in
 *     users so driving mode opens without internet; the copy is dropped on logout (CLEAR_PRIVATE).
 *   - Responses marked "no-store"/"private" ........... never cached (personalised pages)
 * The version string below is injected by the server from a hash of /static.
 */
const VERSION = "__SW_VERSION__";
const STATIC_CACHE = "ir-static-" + VERSION;
const PAGES_CACHE = "ir-pages-v1";
const DATA_CACHE = "ir-data-v1";
const TILE_CACHE = "ir-tiles-v1";
const KEEP = [STATIC_CACHE, PAGES_CACHE, DATA_CACHE, TILE_CACHE];
const TILE_PATH = /^\/\d+\/\d+\/\d+(@2x)?\.(png|jpe?g|webp)$/;
const TILE_MAX_ENTRIES = 3000;          // ≈ 30–60 MB of OSM tiles
const TILE_MAX_AGE_MS = 30 * 24 * 3600 * 1000;
const TILE_STAMP = "x-ir-cached-at";

const SHELL = [
  "/offline",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/report-form.js",
  "/static/js/geo.js",
  "/static/js/drive-engine.js",
  "/static/js/drive.js",
  "/static/js/offline-store.js",
  "/static/js/map.js",
  "/static/vendor/leaflet/leaflet.js",
  "/static/vendor/leaflet/leaflet.css",
  "/static/vendor/bootstrap/bootstrap.rtl.min.css",
  "/static/vendor/bootstrap/bootstrap.min.css",
  "/static/vendor/bootstrap/bootstrap.bundle.min.js",
  "/static/vendor/bootstrap-icons/bootstrap-icons.min.css",
  "/static/vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
  "/static/fonts/tajawal-arabic-400-normal.woff2",
  "/static/fonts/tajawal-arabic-700-normal.woff2",
  "/static/fonts/tajawal-arabic-800-normal.woff2",
  "/static/fonts/tajawal-latin-400-normal.woff2",
  "/static/fonts/tajawal-latin-700-normal.woff2",
  "/static/images/brand/irs-logo.png",
  "/static/images/brand/nda-logo-on-blue.png",
  "/static/icons/icon-192.png",
];

const OFFLINE_APP_PAGES = [/^\/drive$/, /^\/map$/]; // kept offline even when personalised (cleared on logout)
const PUBLIC_PAGES = [/^\/$/, /^\/reports\/?$/, /^\/map$/, /^\/alerts$/, /^\/privacy$/, /^\/about$/, /^\/support$/, /^\/install$/, /^\/settings\/language$/, /^\/reports\/new$/, /^\/drive$/];
const PUBLIC_DATA = [/^\/api\/v1\/road$/, /^\/api\/v1\/meta$/, /^\/api\/v1\/home$/, /^\/api\/v1\/reports\/map$/];
const NEVER = [/^\/admin/, /^\/auth/, /^\/notifications/, /^\/profile/, /^\/settings\/notifications/, /^\/reports\/attachment/,
               /^\/api\/v1\/(notifications|me|auth|push)/, /^\/api\/v1\/reports\/(nearby|alertable)/, /^\/lang\//, /^\/sw\.js$/];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(new Request(u, { credentials: "same-origin" })).catch(() => null))))
  );
  // Wait for the page to ask (controlled update) unless this is the first install
  if (!self.registration.active) self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("ir-") && !KEEP.includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "SKIP_WAITING") self.skipWaiting();
  if (msg.type === "CLEAR_PRIVATE") { caches.delete(PAGES_CACHE); }
});

function cacheable(res) {
  if (!res || !res.ok || res.type === "opaque") return false;
  const cc = (res.headers.get("Cache-Control") || "").toLowerCase();
  return !cc.includes("no-store") && !cc.includes("private");
}

async function networkFirst(req, cacheName, fallbackUrl, forceCache) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (forceCache ? res.ok : cacheable(res)) cache.put(req, res.clone());
    return res;
  } catch (e) {
    const hit = await cache.match(req, { ignoreSearch: false });
    if (hit) return hit;
    if (fallbackUrl) {
      const off = await caches.match(fallbackUrl);
      if (off) return off;
    }
    return new Response("", { status: 503, statusText: "offline" });
  }
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) (await caches.open(STATIC_CACHE)).put(req, res.clone());
  return res;
}

/* Map tiles: cache-first; a stale tile is refreshed in the background; offline → the saved tile (any age). */
async function tileFirst(req) {
  const cache = await caches.open(TILE_CACHE);
  const hit = await cache.match(req);
  const fresh = hit && Date.now() - Number(hit.headers.get(TILE_STAMP) || 0) < TILE_MAX_AGE_MS;
  if (fresh) return hit;
  const update = fetch(req).then(async (res) => {
    if (!res.ok || res.type === "opaque") return res; // opaque responses would waste quota: never kept
    const headers = new Headers(res.headers);
    headers.set(TILE_STAMP, String(Date.now()));
    await cache.put(req, new Response(await res.clone().blob(), { status: res.status, statusText: res.statusText, headers }));
    trimTiles(cache);
    return res;
  });
  if (hit) { update.catch(() => null); return hit; }
  return update.catch(() => new Response("", { status: 504, statusText: "offline" }));
}

let trimming = false;
async function trimTiles(cache) {
  if (trimming) return;
  trimming = true;
  try {
    const keys = await cache.keys(); // insertion order: oldest first
    for (let i = 0; i < keys.length - TILE_MAX_ENTRIES; i++) await cache.delete(keys[i]);
  } finally { trimming = false; }
}

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never intercept form posts / API writes
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) {
    if (req.destination === "image" && req.mode === "cors" && TILE_PATH.test(url.pathname)) event.respondWith(tileFirst(req));
    return; // anything else cross-origin goes straight to the network
  }
  const p = url.pathname;
  if (NEVER.some((r) => r.test(p))) return;

  if (p.startsWith("/static/")) { event.respondWith(cacheFirst(req)); return; }
  if (PUBLIC_DATA.some((r) => r.test(p))) { event.respondWith(networkFirst(req, DATA_CACHE, null, true)); return; }
  if (req.mode === "navigate") {
    if (OFFLINE_APP_PAGES.some((r) => r.test(p))) {
      event.respondWith(networkFirst(req, PAGES_CACHE, "/offline", true));
    } else if (PUBLIC_PAGES.some((r) => r.test(p))) {
      event.respondWith(networkFirst(req, PAGES_CACHE, "/offline", false)); // honours no-store
    } else {
      event.respondWith(fetch(req).catch(() => caches.match("/offline")));
    }
  }
});

/* ---------------- Web Push ---------------- */
self.addEventListener("push", (event) => {
  let d = {};
  try { d = event.data ? event.data.json() : {}; } catch (e) { d = { title: event.data && event.data.text() }; }
  const title = d.title || "الطريق الدولي ليبيا";
  event.waitUntil(self.registration.showNotification(title, {
    body: d.body || "",
    lang: d.lang || "ar",
    dir: d.dir || "rtl",
    icon: "/static/icons/icon-192.png",
    badge: "/static/icons/icon-72.png",
    tag: d.kind || "ir",
    renotify: d.kind === "emergency",
    requireInteraction: d.kind === "emergency",
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const w of wins) { if (w.url === target && "focus" in w) return w.focus(); }
      return self.clients.openWindow(target);
    })
  );
});

self.addEventListener("pushsubscriptionchange", (event) => {
  // Browser rotated the subscription: re-subscribe with the same key.
  event.waitUntil((async () => {
    const old = event.oldSubscription;
    const key = old && old.options && old.options.applicationServerKey;
    if (!key) return;
    await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    // The page re-syncs the new endpoint with the server (CSRF-protected) on next visit — see app.js.
  })());
});
