/*
 * Shared localhost-backend helper for the Firefox extension.
 *
 * Firefox extension pages need an explicit host permission for cross-origin
 * requests even when the target is loopback. manifest.json grants access to
 * 127.0.0.1/localhost and loads this helper before capture.js/navigation.js.
 */

(() => {
  "use strict";

  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
  const ALLOWED_HOSTS = new Set(["127.0.0.1", "localhost"]);

  function normalizeBackendUrl(value) {
    const candidate = (value || DEFAULT_BACKEND_URL).toString().trim();
    try {
      const url = new URL(candidate);
      if (url.protocol !== "http:" || !ALLOWED_HOSTS.has(url.hostname)) {
        throw new Error("backend must use HTTP on localhost/127.0.0.1");
      }
      return url.origin;
    } catch (error) {
      console.warn("[laclaugpt-collector] invalid backend URL; using localhost default", error);
      return DEFAULT_BACKEND_URL;
    }
  }

  async function backendUrl() {
    const stored = await browser.storage.local.get({
      backend_url: DEFAULT_BACKEND_URL,
      captureEndpoint: "",
    });
    // Keep compatibility with the older background.js captureEndpoint setting.
    const legacy = stored.captureEndpoint
      ? stored.captureEndpoint.toString().replace(/\/capture\/?$/, "")
      : "";
    return normalizeBackendUrl(stored.backend_url || legacy || DEFAULT_BACKEND_URL);
  }

  async function request(path, options = {}) {
    const base = await backendUrl();
    const target = `${base}${path.startsWith("/") ? path : `/${path}`}`;
    return fetch(target, {
      cache: "no-store",
      credentials: "omit",
      ...options,
    });
  }

  globalThis.LaclauGPTBackend = Object.freeze({
    DEFAULT_BACKEND_URL,
    backendUrl,
    request,
  });
})();
