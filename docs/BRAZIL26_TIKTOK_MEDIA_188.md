# Brazil26 TikTok media access restrictions (issue #188)

## Current outcome and boundary

The existing human-operated Firefox capture, canonical source identity, study provenance, media index, and 15-minute cron are retained. A detached worker receiving TikTok HTTP 401/403 records `access_restricted`, HTTP status, and a generic reason in the private media index. The same media key is not automatically retried by later cron runs; the system never attempts to replay cookies, copy browser credentials, spoof authentication, or bypass access controls. The separate capture-time handoff introduced by PR #190 can store eligible video bytes already delivered to an authorized Firefox session; this PR adds terminal-state and error-redaction safeguards to that implementation.

The status is **not** evidence that a public TikTok media URL is universally unavailable; it is a specific failure of this detached request. Avoid reporting it as a completed download or as a defect in the existing X/Instagram collection.

## Capture-time implementation and operational verification

1. Capture media bytes only from a full, successful response already delivered to the researcher's authorized Firefox session. Never initiate a hidden second collection/navigation path or use credentials outside the browser. Range/partial responses must not be saved as a complete video.
2. Use a bounded, nonblocking capture-to-loopback handoff; the original media response must remain byte-identical and the researcher's navigation must remain human-controlled.
3. Stage before canonical metadata arrives, and reconcile through the existing MediaDownloader media key and CollectionStore index after canonical insertion. Preserve existing completed rows; ensure a crash/restart leaves a durable pending or restricted state rather than a false completion. Keep sensitive URL query parameters and bytes entirely under ignored `data/`.
4. Enable the feature through the real `LACLAUGPT_CAPTURE_MEDIA_INLINE` runtime setting or the Brazil26 localhost profile (`[collector].download_media = true`), wired to that setting by PR #190. The cron worker remains responsible for other media and transient errors.
5. Run synthetic tests for 403, full/partial response handling, idempotency, restart/recovery, queue bounds, and regressions for X/Instagram, local/distributed profiles and Phase 0. Validate the actual capture on the authorized workstation before marking #188 complete.

## Privacy-safe workstation acceptance report

Report only aggregate counts per platform, e.g. completed, access-restricted, transient failed, and pending; whether a permitted TikTok video was linked to its canonical record; whether the 15-minute cron remains installed; whether loopback binding and human navigation remain enforced; and quality gate results. Never include cookies, signed URLs, handles, full local paths, private study YAML, or row-level records.

Generic example TOMLs drop obsolete `download_media` flags, but the Brazil26 localhost profile retains `download_media = true` because PR #190 wired it to real capture-time configuration. The independent 15-minute media cron scripts remain unchanged.
