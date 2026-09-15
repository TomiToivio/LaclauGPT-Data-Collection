/**
 * LaclauGPT Collector content script.
 *
 * It supports page-tour scrolling and embedded public page-state extraction
 * that never appears as XHR. Nothing here reads credentials or cookies.
 */

(() => {
  "use strict";

  const sent = new Set();

  function fingerprint(kind, body) {
    try {
      return `${kind}:${JSON.stringify(body).slice(0, 4096)}`;
    } catch {
      return `${kind}:${String(body).slice(0, 4096)}`;
    }
  }

  function sendEmbedded(platform, payloads) {
    const fresh = [];
    for (const payload of payloads) {
      const key = fingerprint(payload.kind, payload.body);
      if (sent.has(key)) continue;
      sent.add(key);
      fresh.push(payload);
    }
    if (!fresh.length) return;
    browser.runtime.sendMessage({
      type: "embedded",
      platform,
      page_url: location.href,
      payloads: fresh,
    }).catch(() => {});
  }

  function extractTikTok() {
    const payloads = [];
    const sigi = document.getElementById("SIGI_STATE");
    if (sigi?.textContent) {
      try {
        payloads.push({ kind: "SIGI_STATE", body: JSON.parse(sigi.textContent) });
      } catch {}
    }

    const universal = document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__");
    if (universal?.textContent) {
      try {
        const parsed = JSON.parse(universal.textContent);
        const scope = parsed?.__DEFAULT_SCOPE__ ?? {};
        const items = [];
        const updated = scope["webapp.updated-items"];
        if (Array.isArray(updated)) {
          for (const entry of updated) {
            const item = entry?.itemStruct ?? entry;
            if (item && !item.liveRoomInfo) items.push(item);
          }
        }
        const detail = scope["webapp.video-detail"]?.itemInfo?.itemStruct;
        if (detail && !detail.liveRoomInfo) items.push(detail);
        if (items.length) {
          payloads.push({ kind: "UNIVERSAL_DATA", body: { itemList: items } });
        }
      } catch {}
    }
    sendEmbedded("tiktok", payloads);
  }

  function extractInstagram() {
    const payloads = [];
    for (const script of document.querySelectorAll("script[type='application/json']")) {
      const text = script.textContent || "";
      if (!text || !(/xdt_api__v1__feed|xdt_api__v1__user|Polaris/i.test(text))) continue;
      try {
        payloads.push({ kind: "application-json", body: JSON.parse(text) });
      } catch {}
    }
    sendEmbedded("instagram", payloads);
  }

  function scanEmbedded() {
    const host = location.hostname.toLowerCase();
    if (host === "tiktok.com" || host.endsWith(".tiktok.com")) {
      extractTikTok();
    } else if (host === "instagram.com" || host.endsWith(".instagram.com")) {
      extractInstagram();
    }
  }

  browser.runtime.onMessage.addListener((message) => {
    if (message?.action === "scroll") {
      window.scrollTo(0, document.body?.scrollHeight || document.documentElement.scrollHeight);
      setTimeout(scanEmbedded, 500);
      return Promise.resolve("scrolled");
    }
    return undefined;
  });

  scanEmbedded();
  let lastUrl = location.href;
  setInterval(() => {
    if (location.href !== lastUrl) {
      lastUrl = location.href;
      sent.clear();
      setTimeout(scanEmbedded, 750);
    }
  }, 1000);
})();
