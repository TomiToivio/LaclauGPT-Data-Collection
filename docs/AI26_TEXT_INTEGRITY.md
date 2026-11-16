# Text integrity in the link fetcher (#429)

A fetched body can be binary while claiming to be text: a cache returns gzip under
`content-type: text/html`, or `httpx` cannot decode the `content-encoding` it was given. Decoding such
a body with `errors="replace"` produces a perfectly valid Python string, so nothing fails — the record
is stored as `ready` and the analysis stage codes the noise as discourse.

One record in the AI26 store did exactly that: 43.8 % of its 8,996 characters were `U+FFFD` and it
carried 896 control characters, including the NUL that truncated the field to 25 characters when the
CSV backup was read back. A backup noticed what the pipeline did not.

## The rule

`web_fetch.decode_text_body()` undoes a compression layer when the bytes start with a known signature
(gzip, zlib, zstd) and then measures what it decoded:

| measure | refuse above | why this threshold |
| --- | --- | --- |
| share of `U+FFFD` | 0.10 | the real defect is 0.438; legitimate Finnish, Japanese and Romanian pages are 0.0 |
| control characters outside `\n\r\t` | 5 | line breaks and tabs are text; runs of `0x01` are not |

A body that fails is **not stored**: the fetch returns `binary_body_rejected:<reason>` so the row is
visibly absent with a reason. A body that passes keeps its diagnostics in
`raw_capture.metadata.text_decode` (`compressed_as`, `decompressed_from`, `replacement_share`,
`control_characters`), so the next audit does not have to re-fetch a page that may have changed.

The check is deliberately about *encoding damage*, never about script: a rule that rejected non-ASCII
would delete all 337 Finnish and 193 Japanese records.

## Repairing what is already stored

```bash
python scripts/quarantine_implausible_text.py            # report only
python scripts/quarantine_implausible_text.py --apply    # quarantine
```

It applies the same rule to stored text and marks a match `handoff.status=excluded` with
`reason=implausible_text:binary_body_rejected`, appending to an existing reason rather than replacing
it, and pushes a `quarantine` provenance entry carrying the measurements. Nothing is deleted.

Applied on Laskin 2026-11-16: **1 record** (`6ada2eba85cf548aec73e7ea`, quoteinvestigator.com), which
had already been excluded for `missing_source_publication_time` — the two reasons now both appear, so
fixing the publication time will not quietly re-admit a record whose text is noise.
