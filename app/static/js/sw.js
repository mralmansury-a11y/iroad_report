/* Service Worker — International Road Services – Libya
 * Strategies:
 *   - App shell & versioned static assets ............ cache-first (cache name carries the build hash)
 *   - Public pages (navigations) ...................... network-first → cached copy → /offline
 *   - Public JSON (road / meta / home stats) .......... network-first → cached copy
 *   - Admin, auth, notifications, attachments, /me ... network-only, NEVER cached
 *   - Responses marked "no-store"/"private" ........... never cached (personalised pages)
 * The version string below is injected by the server from a hash of /static.
 */
const VERSION = "__SW_VERSION__";
const STATIC_CACHE = "ir-static-" + VERSION;
const PAGES_CACHE = "ir-pages-v1";
const DATA_CACHE = "ir-data-v1";
const KEEP = [STATIC_CACHE, PAGES_CACHE, DATA_CACHE];

const SHELL = [
  "/offline",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/home.js",
  "/static/js/report-form.js",
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

const PUBLIC_PAGES = [/^\/$/, /^\/reports\/?$/, /^\/map$/, /^\/alerts$/, /^\/privacy$/, /^\/about$/, /^\/support$/, /^\/install$/, /^\/settings\/language$/, /^\/reports\/new$/];
const PUBLIC_DATA = [/^\/api\/v1\/road$/, /^\/api\/v1\/meta$/, /^\/api\/v1\/home$/, /^\/api\/v1\/reports\/map$/];
const NEVER = [/^\/admin/, /^\/auth/, /^\/notifications/, /^\/profile/, /^\/settings\/notifications/, /^\/reports\/attachment/,
               /^\/api\/v1\/(notifications|me|auth|push)/, /^\/lang\//, /^\/sw\.js$/];

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

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return; // never intercept form posts / API writes
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // map tiles etc. go straight to network
  const p = url.pathname;
  if (NEVER.some((r) => r.test(p))) return;

  if (p.startsWith("/static/")) { event.respondWith(cacheFirst(req)); return; }
  if (PUBLIC_DATA.some((r) => r.test(p))) { event.respondWith(networkFirst(req, DATA_CACHE, null, true)); return; }
  if (req.mode === "navigate") {
    if (PUBLIC_PAGES.some((r) => r.test(p))) {
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
