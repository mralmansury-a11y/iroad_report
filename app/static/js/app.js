/* International Road Services – Libya · core client script (no inline JS: strict CSP) */
(function () {
  "use strict";
  const cfgEl = document.getElementById("ir-config");
  const IR = (window.IR = cfgEl ? JSON.parse(cfgEl.textContent) : { i18n: {}, endpoints: {} });
  const t = (k) => (IR.i18n && IR.i18n[k]) || k;
  IR.t = t;
  IR.csrf = () => (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  /* ---------- safe storage (may throw in private mode) ---------- */
  IR.store = {
    get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  /* ---------- toast ---------- */
  const toastEl = document.getElementById("irToast");
  let toastTimer;
  IR.toast = function (msg, actionLabel, onAction, ms) {
    if (!toastEl) return;
    toastEl.querySelector(".msg").textContent = msg;
    const btn = toastEl.querySelector("[data-action]");
    if (actionLabel && onAction) {
      btn.textContent = actionLabel; btn.classList.remove("d-none");
      btn.onclick = () => { toastEl.classList.remove("show"); onAction(); };
    } else { btn.classList.add("d-none"); btn.onclick = null; }
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    if (!actionLabel) toastTimer = setTimeout(() => toastEl.classList.remove("show"), ms || 4500);
  };

  /* ---------- fetch JSON helper (adds CSRF + fetch marker) ---------- */
  IR.api = async function (url, opts) {
    opts = opts || {};
    const headers = Object.assign({ "X-Requested-With": "fetch", Accept: "application/json" }, opts.headers || {});
    if (opts.method && opts.method !== "GET") headers["X-CSRFToken"] = IR.csrf();
    if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
    const res = await fetch(url, Object.assign({ credentials: "same-origin" }, opts, { headers }));
    let data = null;
    try { data = await res.json(); } catch (e) { /* non-JSON */ }
    return { status: res.status, ok: res.ok, data };
  };

  /* ---------- geolocation with clear failure reasons + fallback ----------
   * 1) Browsers allow geolocation ONLY on HTTPS (or localhost) → explicit "insecure" error.
   * 2) High accuracy first (GPS); on timeout/unavailable retry once with network location.  */
  IR.geolocate = function () {
    return new Promise((resolve, reject) => {
      if (!window.isSecureContext) { reject({ code: "insecure" }); return; }
      if (!("geolocation" in navigator)) { reject({ code: "unsupported" }); return; }
      const attempt = (high) => navigator.geolocation.getCurrentPosition(
        resolve,
        (err) => { if (high && err.code !== 1) attempt(false); else reject(err); },
        high ? { enableHighAccuracy: true, timeout: 12000, maximumAge: 0 }
             : { enableHighAccuracy: false, timeout: 20000, maximumAge: 300000 }
      );
      attempt(true);
    });
  };

  /* ---------- theme (dark default, per-visitor cookie) ---------- */
  document.querySelectorAll("[data-theme-toggle]").forEach((b) =>
    b.addEventListener("click", () => {
      const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
      document.documentElement.dataset.theme = next;
      document.cookie = "theme=" + next + ";path=/;max-age=31536000;samesite=lax" + (location.protocol === "https:" ? ";secure" : "");
    })
  );

  /* ---------- sticky header shadow ---------- */
  const hdr = document.querySelector("[data-sticky-header]");
  if (hdr) {
    const onScroll = () => hdr.classList.toggle("is-scrolled", window.scrollY > 4);
    window.addEventListener("scroll", onScroll, { passive: true }); onScroll();
  }

  /* ---------- online / offline indicator ---------- */
  const offEl = document.getElementById("irOffline");
  function netState() {
    if (!offEl) return;
    if (navigator.onLine) {
      if (offEl.classList.contains("show")) IR.toast(t("online"));
      offEl.classList.remove("show");
    } else offEl.classList.add("show");
    document.dispatchEvent(new CustomEvent("ir:net", { detail: { online: navigator.onLine } }));
  }
  window.addEventListener("online", netState);
  window.addEventListener("offline", netState);
  if (!navigator.onLine) netState();

  /* ---------- small behaviours ---------- */
  document.querySelectorAll("select[data-autosubmit]").forEach((s) => s.addEventListener("change", () => s.form.submit()));
  document.querySelectorAll("form[data-confirm], button[data-confirm]").forEach((el) => {
    const form = el.tagName === "FORM" ? el : el.form;
    form.addEventListener("submit", (e) => { if (!window.confirm(t("confirm"))) e.preventDefault(); });
  });
  document.querySelectorAll('[data-action="reload"]').forEach((b) => b.addEventListener("click", () => location.reload()));

  /* ---------- service worker + controlled updates ---------- */
  if ("serviceWorker" in navigator && (location.protocol === "https:" || location.hostname === "localhost" || location.hostname === "127.0.0.1")) {
    const hadController = !!navigator.serviceWorker.controller;
    window.addEventListener("load", async () => {
      try {
        const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
        const promptUpdate = (w) => IR.toast(t("updateReady"), t("reload"), () => w.postMessage({ type: "SKIP_WAITING" }));
        if (reg.waiting && navigator.serviceWorker.controller) promptUpdate(reg.waiting);
        reg.addEventListener("updatefound", () => {
          const nw = reg.installing;
          nw && nw.addEventListener("statechange", () => {
            if (nw.state === "installed" && navigator.serviceWorker.controller) promptUpdate(nw);
          });
        });
        // Reload only when an UPDATED worker takes over (never on the very first install)
        let reloaded = false;
        navigator.serviceWorker.addEventListener("controllerchange", () => {
          if (!hadController || reloaded) return;
          reloaded = true; location.reload();
        });
        IR.swReg = reg;
        document.dispatchEvent(new CustomEvent("ir:sw-ready", { detail: reg }));
        // On logout drop every cached page (defence in depth: personalised pages are never cached anyway)
        document.querySelectorAll('form[action$="/auth/logout"]').forEach((f) => f.addEventListener("submit", () => {
          if (navigator.serviceWorker.controller) navigator.serviceWorker.controller.postMessage({ type: "CLEAR_PRIVATE" });
        }));
      } catch (e) { console.warn("SW registration failed", e); }
    });
  }

  /* ---------- install prompt ---------- */
  let deferredPrompt = null;
  const installBtns = document.querySelectorAll('[data-action="install"]');
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault(); deferredPrompt = e;
    installBtns.forEach((b) => b.classList.remove("d-none"));
  });
  installBtns.forEach((b) => b.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    installBtns.forEach((x) => x.classList.add("d-none"));
  }));
  const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;
  const standalone = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  const stateEl = document.querySelector("[data-install-state]");
  if (stateEl && isIos && !standalone) stateEl.textContent = t("installIos");

  /* ---------- web push ---------- */
  function b64ToUint8(b64) {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }
  const pushSupported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const enableBtns = document.querySelectorAll('[data-action="push-enable"]');
  const disableBtns = document.querySelectorAll('[data-action="push-disable"]');
  const pushState = document.querySelector("[data-push-state]");

  async function refreshPushUi() {
    if (!pushSupported || !IR.vapid) {
      enableBtns.forEach((b) => b.classList.add("d-none"));
      if (pushState) pushState.textContent = t("pushUnsupported");
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    enableBtns.forEach((b) => b.classList.toggle("d-none", !!sub));
    disableBtns.forEach((b) => b.classList.toggle("d-none", !sub));
    if (pushState && sub) pushState.textContent = t("pushEnabled");
  }
  async function enablePush() {
    try {
      const perm = await Notification.requestPermission(); // explicit user gesture
      if (perm !== "granted") { IR.toast(t("pushDenied")); return; }
      const reg = await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription()) ||
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(IR.vapid) }));
      const r = await IR.api(IR.endpoints.pushSub, { method: "POST", json: { subscription: sub.toJSON() } });
      if (r.ok) IR.toast(t("pushEnabled")); else IR.toast(t("networkError"));
      refreshPushUi();
    } catch (e) { IR.toast(t("pushUnsupported")); }
  }
  async function disablePush() {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await IR.api(IR.endpoints.pushUnsub, { method: "POST", json: { endpoint: sub.endpoint } });
      await sub.unsubscribe();
    }
    refreshPushUi();
  }
  enableBtns.forEach((b) => b.addEventListener("click", enablePush));
  disableBtns.forEach((b) => b.addEventListener("click", disablePush));
  if (enableBtns.length && pushSupported) navigator.serviceWorker.ready.then(refreshPushUi);
  else if (enableBtns.length) refreshPushUi();

  // Keep the server in sync when the browser rotates the subscription or the user logs in/out
  if (pushSupported && IR.vapid && Notification.permission === "granted") {
    navigator.serviceWorker.ready.then(async (reg) => {
      const sub = await reg.pushManager.getSubscription();
      if (!sub) return;
      const sig = sub.endpoint + "|" + (IR.authenticated ? "u" : "a") + "|" + IR.lang;
      if (IR.store.get("ir-push-sync") === sig) return;
      const r = await IR.api(IR.endpoints.pushSub, { method: "POST", json: { subscription: sub.toJSON() } }).catch(() => null);
      if (r && r.ok) IR.store.set("ir-push-sync", sig);
    });
  }
})();
