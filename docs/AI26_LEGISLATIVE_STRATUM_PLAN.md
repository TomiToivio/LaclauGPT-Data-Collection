# The parliamentary arena has no legislative stratum (#360)

**Status: gap analysis with verified endpoints. No source has been added yet, and this
document does not claim the gap is closed by one.**

## What the issue establishes

The Phase 1 paper's parliamentary arena promises parliamentary debates, party
programmes, campaign communications and election datasets (§4.1). The corpus holds:

| arena | records | fi | blank language |
|---|---|---|---|
| elites | 2,023 | 14 | 489 |
| grassroots | 658 | 53 | 33 |
| parliamentary | 614 | 24 | 324 |

`grep -c -i eduskunta data/config/ai26.sources.toml` → **0**. All 614 parliamentary
records are executive or institutional communication: Commission, Parliament press
service, Valtioneuvosto, OECD/NIST-style bodies, party press feeds.

**A party press release is party communication, not parliamentary debate.** The #349
Finnish party feeds are the closest thing the arena has and they do not make it a
legislative stratum. Neither party programmes nor election datasets are present at all.

## Why one config line will not fix it

Every existing source kind (`feed`, `web_source`, `x_account`, `bluesky_account`,
`mastodon_account`, `youtube_source`, `scholarly_query`) fetches a document stream. The
legislative material is a **structured, paginated, queryable corpus**: stenograms per
session, committee reports per committee, written questions per member. That needs a
collector that walks a paged API and maps a document type, not a URL added to a list.

`web_source` polls a single page; pointed at a session listing it would collect listing
pages, not speeches.

## Candidate endpoints, probed live 2026-10-27

| endpoint | status | content | what it would supply |
|---|---|---|---|
| `https://avoindata.eduskunta.fi/` | **200** | HTML | the open-data portal itself; entry point |
| `https://avoindata.eduskunta.fi/api/v1/tables` | **404** | JSON | the documented v1 table endpoint no longer resolves |
| `https://avoindata.eduskunta.fi/api/v1/` | **404** | JSON | same |
| `https://api.eduskunta.fi/` | **200** | HTML | API portal; must be read for the current base path and auth |
| `https://www.eduskunta.fi/FI/vaski/sivut/default.aspx` | **403** | HTML | documents are served but block non-browser clients |
| `https://data.finlex.fi/` | **200** | HTML | **legislation** (statutes), not debate - useful for policy uptake, not for the arena |
| `https://tulospalvelu.vaalit.fi/` | **200** | HTML | official election results; the election-dataset half of §4.1 |
| `https://www.kokoomus.fi/feed/` | **200** | `text/xml` | a working party feed - **party communication, not a legislative stratum** |

Two things follow. First, the v1 API path recorded in older documentation is dead, so
any implementation must start from `api.eduskunta.fi` rather than a remembered URL.
Second, `kokoomus.fi/feed` is live and addable **today**, but adding it would raise the
party-communication count and leave the legislative gap exactly where it is. That is
the distinction this document exists to keep visible.

## What implementing this actually requires

1. **Read `api.eduskunta.fi` and record the current base path, auth model and response
   schema** - the v1 path is 404, so this cannot be assumed.
2. **A dedicated collector** (`eduskunta`) with: request paging, a document-type field,
   per-session identifiers, rate limiting, and the same provenance contract the other
   collectors carry (`collection_provenance` with module, visited_url, transformations).
3. **A mapping decision**: stenograms, committee reports and written questions are
   different document types with different relevance behaviour. Whether all three enter
   the arena, or only those mentioning AI, is a **sampling decision for the study owner**.
4. **Party programmes** are a separate, smaller job: static documents, no API, one fetch
   each, and they age - a 2023 programme is a historical artefact, not a live claim.
5. **Election datasets**: `tulospalvelu.vaalit.fi` is fetchable, but joining results to
   parties and constituencies is analysis-side work, not collection-side.

## Acceptance test for closing #360

Not "a source was added". The test is:

- `grep -c -i eduskunta data/config/ai26.sources.toml` > 0 **and** the matching records
  carry a legislative document type; and
- a corpus audit showing parliamentary records whose source is a stenogram, committee
  report or written question - not executive communication; and
- §4.3's cross-arena movement claims can then be supported on the **receiving** side,
  which is the point of the whole arena.

Until then the paper's §4.1 claim about the parliamentary arena remains stronger than
the corpus underneath it.
