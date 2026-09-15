/**
 * LaclauGPT Collector — Firefox capture layer.
 *
 * Canonical browser capture for LaclauGPT-Data-Collection. Design lineage:
 * the 2024 LaclauGPT-TikTok-Scraper (CC0) introduced response-body
 * interception with the site's own response stream left untouched; the
 * Discourse-Analysis collector generalised it to TikTok/Instagram/X with
 * platform detection. This version adds legacy-salvaged capture endpoints:
 * TikTok comment lists, user details and hashtag/challenge details.
 *
 * Parsing happens server-side in the Python package; this layer forwards
 * raw response bodies plus minimal provenance to the local backend.
 *
 * Privacy contract (docs/EXTENSION_PRIVACY.md): capture starts only on
 * configured platform API endpoints, bodies are forwarded to the locally
 * configured backend (default http://127.0.0.1:8765), no credentials,
 * cookies or browsing history are collected, and the website's own
 * response stream is forwarded byte-for-byte unchanged.
 *
 * Academic research use only.
 */

(() => {
  "use strict";

  // Public default for a local collector backend. Study-specific backend
  // addresses and ports belong in Firefox profile/private runtime settings.
  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
  let backendUrl = DEFAULT_BACKEND_URL;
  browser.storage.local.get({ backend_url: DEFAULT_BACKEND_URL })
    .then(item => {
      const stored = (item.backend_url || "").toString().trim();
      backendUrl = stored.startsWith("http") ? stored : DEFAULT_BACKEND_URL;
    })
    .catch(() => {});

  // Endpoint matchers: which response URLs carry parseable public API data.
  // TikTok entries include the legacy-salvaged comment/user/challenge
  // endpoints; X entries match GraphQL post operations; Instagram matches
  // the feed/graphql endpoints.
  const MATCHERS = {
    tiktok: /api\.tiktokv\.com|\/api\/(?:post|challenge)\/item_list|\/api\/user\/playlist|\/api\/search\/(?:item_list|general\/full)|\/api\/preload\/item_list|\/api\/comment\/list\/|\/api\/user\/detail\/|\/api\/challenge\/detail\//,
    x: /(?:^|\.)x\.com\/i\/api\/graphql|(?:^|\.)twitter\.com\/i\/api\/graphql|\/i\/api\/graphql(?:\/|\?|$)/,
    instagram: /\/api\/v1\/|\/graphql\/query(?:[\/?]|$)/,
  };

  function platformFor(url) {
    for (const [platform, matcher] of Object.entries(MATCHERS)) {
      if (matcher.test(url || "")) return platform;
    }
    return null;
  }

  async function tabUrlFor(tabId) {
    if (tabId < 0) return "";
    try {
      const tab = await browser.tabs.get(tabId);
      return tab?.url || "";
    } catch {
      return "";
    }
  }

  async function postToBackend(payload) {
    try {
      const response = await fetch(`${backendUrl}/capture`, {
        method: "POST",
        credentials: "omit",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        console.warn(`[laclaugpt-collector] backend ${backendUrl} returned ${response.status}`);
      }
    } catch (error) {
      console.warn(`[laclaugpt-collector] backend unreachable at ${backendUrl}`, error);
    }
  }

  /**
   * Intercept a response without modifying what the website receives.
   *
   * The historical scraper used filterResponseData for this job.
   * event.data is written back as the original ArrayBuffer, byte-for-byte;
   * decoding is only for the collector's private forward copy.
   */
  function listener(details) {
    const platform = platformFor(details.url);
    if (!platform) return;

    let filter;
    try {
      filter = browser.webRequest.filterResponseData(details.requestId);
    } catch (error) {
      console.warn("[laclaugpt-collector] cannot attach response filter", details.url, error);
      return;
    }

    const decoder = new TextDecoder("utf-8");
    let responseData = "";

    filter.ondata = event => {
      responseData += decoder.decode(event.data, { stream: true });
      // Forward exactly the bytes received by the browser. Do not decode and
      // re-encode the website response.
      filter.write(event.data);
    };

    filter.onerror = event => {
      console.warn("[laclaugpt-collector] response filter error", platform, details.url, event.error);
      try { filter.disconnect(); } catch {}
    };

    filter.onstop = async () => {
      responseData += decoder.decode();
      try { filter.disconnect(); } catch {}

      // Capture source HTML and API/GraphQL JSON, never image/video bodies:
      // main_frame + xmlhttprequest only (manifest types filter enforces this).
      const pageUrl = await tabUrlFor(details.tabId)
        || details.documentUrl || details.originUrl || "";
      await postToBackend({
        platform,
        api_url: details.url,
        platform_url: pageUrl,
        captured_at: new Date().toISOString(),
        body: responseData,
      });
    };
  }

  browser.webRequest.onHeadersReceived.addListener(
    listener,
    {
      urls: [
        "*://*.tiktok.com/*",
        "*://*.instagram.com/*",
        "*://*.x.com/*",
        "*://*.twitter.com/*",
      ],
      // Capture source HTML and API/GraphQL JSON, never image/video bodies.
      types: ["main_frame", "xmlhttprequest"],
    },
    ["blocking"],
  );

  // The content script forwards embedded page-state JSON that never appears
  // as a separate XHR; both paths converge on the same backend endpoint.
  browser.runtime.onMessage.addListener((message, sender) => {
    if (message?.type !== "embedded" || !Array.isArray(message.payloads)) {
      return undefined;
    }
    const pageUrl = sender?.tab?.url || message.page_url || "";
    for (const payload of message.payloads) {
      if (!payload?.json) continue;
      void postToBackend({
        platform: message.platform,
        api_url: payload.kind || "embedded",
        platform_url: pageUrl,
        captured_at: new Date().toISOString(),
        body: JSON.stringify(payload.json),
      });
    }
    return undefined;
  });
})();