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

  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
  let backendUrl = DEFAULT_BACKEND_URL;
  browser.storage.local.get({ backend_url: DEFAULT_BACKEND_URL })
    .then(item => {
      const stored = (item.backend_url || "").toString().trim();
      backendUrl = stored.startsWith("http") ? stored : DEFAULT_BACKEND_URL;
    })
    .catch(() => {});

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
      filter.write(event.data);
    };

    filter.onerror = event => {
      console.warn("[laclaugpt-collector] response filter error", platform, details.url, event.error);
      try { filter.disconnect(); } catch {}
    };

    filter.onstop = async () => {
      responseData += decoder.decode();
      try { filter.disconnect(); } catch {}

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
      types: ["main_frame", "xmlhttprequest"],
    },
    ["blocking"],
  );

  // content.js emits embedded page-state objects as {kind, body}. Keep this
  // envelope aligned so those captures reach the same canonical Python path
  // as intercepted API/GraphQL responses.
  browser.runtime.onMessage.addListener((message, sender) => {
    if (message?.type !== "embedded" || !Array.isArray(message.payloads)) {
      return undefined;
    }
    const pageUrl = sender?.tab?.url || message.page_url || "";
    for (const payload of message.payloads) {
      if (payload?.body === undefined) continue;
      void postToBackend({
        platform: message.platform,
        api_url: payload.kind || "embedded",
        platform_url: pageUrl,
        captured_at: new Date().toISOString(),
        body: JSON.stringify(payload.body),
      });
    }
    return undefined;
  });
})();