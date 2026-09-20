# Phase 1 Instagram browser capture

Issue: #132  
Parent: #111  
Prerequisite: #105

This slice uses the existing researcher-triggered Firefox/local canonical capture
path. It does not revive the legacy Node backend, add continuous interception, or
activate X/Twitter.

## Activation gate

Instagram remains operationally disabled until issue #105 records a successful
real researcher-triggered Firefox/TikTok smoke outside CI. Synthetic tests are not
a substitute for that prerequisite.

After #105 is satisfied, Instagram may be enabled in the researcher's private
study configuration and exercised with the manual smoke below. Public CI remains
synthetic/offline.

## Identity contract

For Instagram posts and reels:

- canonical `source_url` is the normalized Instagram permalink;
- `source_native_ids.document_id` uses the shortcode when available, otherwise
  the source-native media identifier;
- the original numeric/media identifier remains in the exact raw captured item;
- an explicit native parent/repost/reshare/reference identifier is preserved as
  `source_native_ids.parent_document_id` when the captured payload contains one;
- `source.raw_metadata.native_relationship_type` records whether that explicit
  relation was a `parent`, `repost`, `reshare`, or `reference`;
- no relationship is inferred from author, caption, timing, URL similarity, or
  carousel membership.

Carousel children remain media assets of the parent post rather than independent
social-post records.

## Raw provenance

The canonical record keeps both:

1. `raw_capture.payload`: the exact parsed source item used for normalization;
2. `raw_capture.ref`: the durable reference to the full captured response.

The public synthetic fixture contains no real account, cookie, token, password,
session identifier, or credential material.

## Deduplication and handoff

Repeated capture of the same canonical Instagram permalink is idempotent in the
collection store. Collection leaves `analysis` and multimodal analysis fields
empty. The resulting canonical record is accepted by the standard Collection ->
Analysis handoff contract; media-bearing reels become ready once the referenced
media state is durable.

## Error and privacy boundary

The local capture server rejects non-loopback bind addresses before opening a
socket. Malformed JSON/body types fail explicitly at the browser-capture decoding
boundary. Payloads that do not contain recognizable Instagram post/reel objects
produce no records rather than guessed records.

## Public automated acceptance

Run:

```bash
pytest -q tests/test_phase1_browser_instagram.py tests/test_instagram_parser.py
pytest -q
```

The first command proves the issue-specific vertical slice. The full suite is the
Phase 0/RSS and repository regression gate.

## Manual Firefox/Instagram smoke

Only perform this after #105 contains the successful Firefox/TikTok smoke record.

1. Use the dedicated research Firefox profile and the existing local capture
   extension/backend.
2. Bind the backend to `127.0.0.1` or another accepted loopback address only.
3. Enable Instagram only in private research configuration. Do not enable X as
   part of this smoke.
4. Open a public Instagram post or reel intentionally selected by the researcher.
5. Confirm the capture counter increases and one canonical Instagram record is
   written.
6. Confirm the canonical permalink and source-native identity are stable.
7. Confirm exact-item raw payload plus the full-response raw reference are
   preserved.
8. Capture the same post/reel again and confirm no duplicate canonical record is
   inserted.
9. Confirm no credential/cookie/session material is written to public fixtures or
   logs.
10. Confirm the Collection -> Analysis handoff can be produced.
11. Record the smoke result on #132 before activating another browser platform.

A failed smoke must remain visible as a failed/manual acceptance result. Do not
silently broaden endpoint matchers or enable another platform to work around it.
