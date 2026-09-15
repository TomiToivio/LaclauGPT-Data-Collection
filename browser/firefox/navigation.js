/**
 * LaclauGPT Collector — tour navigation layer.
 *
 * The backend owns the study configuration and returns one navigation row per
 * configured account/page URL. This script refreshes that tour before every
 * visit so study-window changes and config edits take effect without reloading
 * the extension. With no backend reachable, navigation stays idle — passive
 * capture on pages the researcher visits still works.
 *
 * This replaces the legacy TikTok content-script auto-navigation
 * (search/hashtag/user jumps driven by a hard-coded in-extension target
 * list): target lists are sensitive configuration and now live only in the
 * backend's ignored local study config.
 *
 * Academic research use only.
 */

(() => {
  "use strict";

  // Public default for a local collector backend. Any study-specific backend
  // address or port must be stored in the Firefox profile/private runtime
  // configuration rather than committed to this repository.
  const DEFAULT_BACKEND_URL = "http://127.0.0.1:8765";
  let backendUrl = DEFAULT_BACKEND_URL;
  let backendReady = browser.storage.local.get({ backend_url: DEFAULT_BACKEND_URL })
    .then(item => {
      const stored = (item.backend_url || "").toString().trim();
      backendUrl = stored.startsWith("http") ? stored : DEFAULT_BACKEND_URL;
    })
    .catch(() => {});
  const VISIT_INTERVAL_MS = 300000;
  const SCROLL_INTERVAL_MS = 3000;
  const SCROLLS_PER_VISIT = 10;

  let nextIndex = 0;
  let currentTabId = null;
  let busy = false;

  async function fetchTour() {
    try {
      await backendReady;
      const response = await fetch(`${backendUrl}/tour`, { cache: "no-store" });
      if (!response.ok) return null;
      return await response.json();
    } catch {
      return null;
    }
  }

  async function closeCurrentTab(tabId) {
    try { await browser.tabs.remove(tabId); } catch {}
    if (currentTabId === tabId) currentTabId = null;
  }

  async function visitNext() {
    if (busy) return;

    const tour = await fetchTour();
    const accounts = Array.isArray(tour?.accounts) ? tour.accounts : [];
    if (!tour?.active || accounts.length === 0) return;

    const item = accounts[nextIndex % accounts.length];
    nextIndex = (nextIndex + 1) % accounts.length;
    const url = item?.url;
    if (!url) return;

    busy = true;
    try {
      const tab = await browser.tabs.create({ url, active: true });
      currentTabId = tab.id;

      let scrolls = 0;
      const timer = setInterval(async () => {
        scrolls += 1;
        try {
          await browser.tabs.sendMessage(tab.id, { action: "scroll" });
        } catch {}

        if (scrolls >= SCROLLS_PER_VISIT) {
          clearInterval(timer);
          await closeCurrentTab(tab.id);
          busy = false;
        }
      }, SCROLL_INTERVAL_MS);
    } catch (error) {
      console.warn("[laclaugpt-collector] navigation failed", item, error);
      currentTabId = null;
      busy = false;
    }
  }

  setInterval(visitNext, VISIT_INTERVAL_MS);
  visitNext();
})();