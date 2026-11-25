/* Offline store — a tiny key/value store on IndexedDB (window.IRStore).
 * Keeps public data the app needs without internet (e.g. the verified-hazard list of driving mode).
 * Never used for personal data. When IndexedDB is unavailable (private mode, blocked storage) it falls
 * back to memory for the current page, so callers never have to handle a storage failure.
 *
 *   await IRStore.get("drive-hazards")          → value or null
 *   await IRStore.set("drive-hazards", value)   → true when saved on the device, false when memory only
 */
(function (root) {
  "use strict";
  const DB_NAME = "ir-offline", STORE = "kv", VERSION = 1;
  const memory = new Map();
  let dbPromise = null;

  function open() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve) => {
      try {
        if (!root.indexedDB) { resolve(null); return; }
        const req = root.indexedDB.open(DB_NAME, VERSION);
        req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => resolve(null);
        req.onblocked = () => resolve(null);
      } catch (e) { resolve(null); }
    });
    return dbPromise;
  }

  function run(mode, fn) {
    return open().then((db) => new Promise((resolve) => {
      if (!db) { resolve(undefined); return; }
      try {
        const tx = db.transaction(STORE, mode);
        const req = fn(tx.objectStore(STORE));
        tx.oncomplete = () => resolve(req ? req.result : true);
        tx.onerror = tx.onabort = () => resolve(undefined);
      } catch (e) { resolve(undefined); }
    }));
  }

  root.IRStore = {
    async get(key) {
      const v = await run("readonly", (s) => s.get(key));
      if (v !== undefined && v !== true) return v;
      return memory.has(key) ? memory.get(key) : null;
    },
    async set(key, value) {
      memory.set(key, value);
      return (await run("readwrite", (s) => { s.put(value, key); return null; })) === true;
    },
  };
})(typeof self !== "undefined" ? self : this);
