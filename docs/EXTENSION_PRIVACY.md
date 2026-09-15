# Firefox extension privacy contract

What the extension does, exactly:

1. **What fields are captured.** Response bodies of public platform API
   endpoints on TikTok, Instagram and X (JSON/HTML with embedded page state),
   plus the request URL, the visited page URL, and an explicit capture
   timestamp. Legacy-salvaged TikTok endpoints (comment lists, user details,
   hashtag/challenge details) capture the same shape of public API data.
2. **When capture occurs.** Only when a `main_frame` or `xmlhttprequest`
   response arrives from a configured platform host and its URL matches a
   known public-API endpoint pattern. Nothing is captured on other pages.
   Scrolling/embedded-state forwarding only runs on the same three platforms.
3. **Where data is sent.** To the locally configured collector backend,
   default `http://127.0.0.1:8765`, changeable only via the extension's own
   storage (`backend_url`). No third-party service is contacted by the
   extension. If the backend is unreachable, capture is dropped with a
   console warning — nothing is queued to send later.
4. **Media.** The extension never downloads media; it forwards metadata and
   API response bodies only. Media downloads are an explicit, optional
   backend feature.
5. **Start/stop.** Passive capture is always on while a platform page is
   open in the browser; systematic navigation ("tour") runs only while the
   backend reports the study window active (`/tour` with `active: true`).
   Removing or disabling the extension stops all capture.
6. **Permissions requested** (minimised from the Discourse-Analysis variant):
   - `storage` — remember the backend URL;
   - `webRequest` + `webRequestBlocking` — response-body interception
     (Firefox MV2 requirement for `filterResponseData`);
   - `tabs` — resolve the visited page URL for provenance;
   - host permissions limited to the three platforms; no `<all_urls>`.
7. **No credentials.** The extension never reads cookies, login state or
   credentials, and never embeds tokens. `credentials: "omit"` is set on
   every backend request.