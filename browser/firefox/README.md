# Firefox browser collector

This extension is the canonical browser-assisted capture client for LaclauGPT Data Collection.

## What it captures

Capture is user-triggered by clicking the extension button. The extension sends a small envelope containing:

- current page URL
- detected platform label
- capture timestamp
- conservative page text/description
- Open Graph image/video references when present
- document title

It does **not** contain credentials, cookies, session storage, browser profiles, study target lists or authentication headers.

## Where data goes

The default endpoint is:

```text
http://127.0.0.1:8765/capture
```

Run the local capture service with:

```bash
laclaugpt-capture --database state/captures.sqlite3
```

The SQLite path is runtime data and is ignored by Git. Use a path outside the repository for real research projects when practical.

## Firefox development install

1. Open `about:debugging` in Firefox.
2. Choose **This Firefox**.
3. Choose **Load Temporary Add-on**.
4. Select `browser/firefox/manifest.json`.
5. Start `laclaugpt-capture` locally.
6. Navigate to a public source and click the extension button to capture the current page.

## Permissions

The extension requests only storage, active-tab access, and localhost HTTP access for the capture service. It does not request broad social-platform host permissions or continuous webRequest interception by default.

## Privacy and research safety

Do not add real target lists, private endpoints, credentials or cookies to this directory. Do not commit captured payloads or browser profiles. If a future specialized extension needs broader permissions, document exactly what is captured, why the permission is needed, whether collection is automatic, and how the researcher starts/stops it.

Historical automatic TikTok/API interception remains an architectural reference only. See `docs/COLLECTOR_MIGRATION.md` for the migration rationale.
