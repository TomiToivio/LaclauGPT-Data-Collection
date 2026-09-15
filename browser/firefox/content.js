function detectPlatform(hostname) {
  const host = hostname.toLowerCase();
  if (host.includes("tiktok.com")) return "tiktok";
  if (host.includes("instagram.com")) return "instagram";
  if (host === "x.com" || host.endsWith(".x.com") || host.includes("twitter.com")) return "x";
  if (host.includes("youtube.com") || host === "youtu.be") return "youtube";
  if (host.includes("bsky.app")) return "bluesky";
  return "web";
}

function firstText(selectors) {
  for (const selector of selectors) {
    const node = document.querySelector(selector);
    const value = node?.getAttribute("content") || node?.textContent || "";
    if (value.trim()) return value.trim();
  }
  return "";
}

function extractPage() {
  const sourceUrl = location.href.split("#", 1)[0];
  const platform = detectPlatform(location.hostname);
  const text = firstText([
    "meta[property='og:description']",
    "meta[name='description']",
    "article",
    "main"
  ]);
  const mediaUrls = [...document.querySelectorAll("meta[property='og:video'], meta[property='og:image']")]
    .map((node) => node.getAttribute("content"))
    .filter(Boolean);
  return {
    schema_version: "1.0",
    source_url: sourceUrl,
    platform,
    captured_at: new Date().toISOString(),
    collection_method: "browser-extension",
    post_id: "",
    author: "",
    text: text.slice(0, 20000),
    media_urls: [...new Set(mediaUrls)],
    api_url: "",
    raw: { title: document.title }
  };
}

browser.runtime.onMessage.addListener((message) => {
  if (message?.type !== "capture-current-page") return undefined;
  return Promise.resolve(extractPage());
});
