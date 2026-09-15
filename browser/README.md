# Firefox extension

`browser/firefox/` is the canonical LaclauGPT browser capture extension.

## Install (Firefox, temporary add-on)

1. Open `about:debugging#/runtime/this-firefox`.
2. "Load Temporary Add-on…" and select `browser/firefox/manifest.json`.
3. Start the Python capture backend (see `docs/CAPTURE_BACKEND.md`):
   the extension defaults to `http://127.0.0.1:8765`.
4. To point the extension at another local backend, set `backend_url` in the
   extension storage (e.g. via `about:debugging` → Inspect →
   `browser.storage.local.set({ backend_url: "http://127.0.0.1:9000" })`).
   Never commit a study-specific backend address.

## Files

- `manifest.json` — MV2 manifest, minimal permissions (see
  `docs/EXTENSION_PRIVACY.md` for the full privacy contract).
- `capture.js` — response-body interception → POST `/capture` on the backend.
  Platform detection + endpoint matchers; site traffic forwarded untouched.
- `content.js` — scrolling for tour visits; embedded page-state JSON
  forwarding (TikTok SIGI/UNIVERSAL data, Instagram embedded JSON).
- `navigation.js` — tour navigation driven by the backend's `/tour` endpoint.

## Design lineage

- 2024 `LaclauGPT-TikTok-Scraper` (CC0): response interception pattern,
  byte-exact forwarding of the site's own response stream, TikTok
  comment/user/challenge endpoints (salvaged here).
- `LaclauGPT-Discourse-Analysis` collector: multi-platform matchers, backend
  POST architecture, tour navigation, embedded-state forwarding.

The legacy in-extension hard-coded target lists (searches/usernames/hashtags
in content.js) are deliberately NOT carried over: target lists are sensitive
operational configuration and live in the backend's ignored local study
config, never in this public repository.