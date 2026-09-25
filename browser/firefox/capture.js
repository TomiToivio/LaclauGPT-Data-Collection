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
  let inlineMediaEnabled = false;
  let inlineMediaMaxBytes = 64 * 1024 * 1024;
  browser.storage.local.get({ backend_url: DEFAULT_BACKEND_URL })
    .then(item => {
      const stored = (item.backend_url || "").toString().trim();
      backendUrl = stored.startsWith("http") ? stored : DEFAULT_BACKEND_URL;
      return refreshMediaConfig();
    })
    .catch(() => {});
  setInterval(() => { void refreshMediaConfig(); }, 60_000);

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

  async function refreshMediaConfig() {
    try {
      const response = await fetch(`${backendUrl}/status`, { credentials: "omit" });
      if (!response.ok) return;
      const status = await response.json();
      inlineMediaEnabled = status.capture_media_inline === true;
      const configured = Number(status.capture_media_max_bytes);
      if (Number.isSafeInteger(configured) && configured > 0) {
        inlineMediaMaxBytes = configured;
      }
    } catch {
      inlineMediaEnabled = false;
    }
  }

  function responseHeader(details, name) {
    const header = (details.responseHeaders || []).find(
      item => (item.name || "").toLowerCase() === name,
    );
    return header?.value || "";
  }

  function responseMime(details) {
    return responseHeader(details, "content-type").split(";", 1)[0].trim().toLowerCase();
  }

  function isTikTokMedia(details) {
    if (!inlineMediaEnabled || details.type !== "media") return false;
    try {
      const host = new URL(details.url).hostname.toLowerCase();
      const tiktokHost = ["tiktok.com", "tiktokcdn-eu.com"].some(
        suffix => host === suffix || host.endsWith(`.${suffix}`),
      );
      return tiktokHost && responseMime(details).startsWith("video/");
    } catch {
      return false;
    }
  }

  async function postMediaToBackend(details, mimeType, chunks, byteSize) {
    const metadata = new TextEncoder().encode(JSON.stringify({
      url: details.url,
      mime_type: mimeType,
      status_code: details.statusCode,
      content_range: responseHeader(details, "content-range"),
      captured_at: new Date().toISOString(),
    }));
    const prefix = new Uint8Array(4);
    new DataView(prefix.buffer).setUint32(0, metadata.byteLength, false);
    try {
      const response = await fetch(`${backendUrl}/media-capture`, {
        method: "POST",
        credentials: "omit",
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/octet-stream",
        },
        body: new Blob([prefix, metadata, ...chunks], {
          type: "application/octet-stream",
        }),
      });
      if (!response.ok) {
        console.warn(
          `[laclaugpt-collector] media handoff returned ${response.status}`,
          details.url,
          byteSize,
        );
      }
    } catch (error) {
      console.warn("[laclaugpt-collector] media handoff failed", details.url, error);
    }
  }
  function listener(details) {
    const platform = platformFor(details.url);
    const mediaCapture = isTikTokMedia(details);
    if (!platform && !mediaCapture) return;

    let filter;
    try {
      filter = browser.webRequest.filterResponseData(details.requestId);
    } catch (error) {
      console.warn("[laclaugpt-collector] cannot attach response filter", details.url, error);
      return;
    }

    const decoder = platform ? new TextDecoder("utf-8") : null;
    let responseData = "";
    const mediaChunks = [];
    let mediaBytes = 0;
    let mediaOverflow = false;

    filter.ondata = event => {
      if (decoder) {
        responseData += decoder.decode(event.data, { stream: true });
      } else if (!mediaOverflow) {
        mediaBytes += event.data.byteLength;
        if (mediaBytes <= inlineMediaMaxBytes) {
          mediaChunks.push(new Uint8Array(event.data));
        } else {
          mediaOverflow = true;
          mediaChunks.length = 0;
        }
      }
      filter.write(event.data);
    };

    filter.onerror = event => {
      console.warn(
        "[laclaugpt-collector] response filter error",
        platform || "tiktok-media",
        details.url,
        event.error,
      );
      try { filter.disconnect(); } catch {}
    };

    filter.onstop = async () => {
      if (decoder) responseData += decoder.decode();
      try { filter.disconnect(); } catch {}

      if (mediaCapture) {
        if (!mediaOverflow && mediaBytes > 0) {
          await postMediaToBackend(details, responseMime(details), mediaChunks, mediaBytes);
        } else if (mediaOverflow) {
          console.warn(
            "[laclaugpt-collector] media exceeds configured capture bound",
            details.url,
            inlineMediaMaxBytes,
          );
        }
        return;
      }

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
        "*://*.tiktokcdn-eu.com/*",
        "*://*.instagram.com/*",
        "*://*.x.com/*",
        "*://*.twitter.com/*",
      ],
      types: ["main_frame", "xmlhttprequest", "media"],
    },
    ["blocking", "responseHeaders"],
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