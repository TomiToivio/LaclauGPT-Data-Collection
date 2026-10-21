# AI26 sampling decision — a measured `ai_governance` query (#295)

**Status: decided 2026-10-21.** The study owner authorised this sampling decision
("do these and close them"); it is recorded here with its inclusion criteria and
the measurement that produced it. Sampling provenance is not an ideology label:
no actor is classified ideologically, and `source_family` explains *why material
is sampled*, never what an actor "is".

The checked-in example manifest (`configs/studies/ai26.sources.example.toml`) is
**not** the deployed private `data/config/ai26.sources.toml`. Reconciling the
deployed file is a separate deployment step for the owner. Nothing here deletes
or relabels records already in the store.

Index of this round's decisions: `docs/ai26-sampling-decisions-2026-10-21.md`.

---

## The decision: option 1, governance terms in the title

**The defect.** `all:artificial intelligence AND (governance OR regulation OR audit
OR evaluation OR liability OR standards)` matched `evaluation`/`audit` in nearly
every ML abstract. 124–129 of the parliamentary arena's records came from this one
query and virtually none concerned parliaments, parties, elections or legislation.

**Measurement, 2026-10-21, against the live arXiv API** (`export.arxiv.org/api/query`,
no key, `max_results` per the sample column) and the store (`ai26__records`,
`source.raw_metadata.source_name == "ai_governance"`, 129 rows at measurement time —
the issue's 124 had grown). "In window" is `submittedDate:[202609180000 TO
202610210000]`, i.e. the period the store covers.

| option | query, as actually sent | live results | in window | sample read | governance/policy material | old stored records surviving |
|---|---|---|---|---|---|---|
| **current (firehose)** | `all:artificial intelligence AND (governance OR regulation OR audit OR evaluation OR liability OR standards)` | 254,783 | 8,327 | 60 newest titles | **0/60** | 129/129 |
| **1. title-field (chosen)** | `(ti:"AI governance" OR ti:"AI regulation" OR ti:"AI Act" OR ti:"algorithmic accountability" OR ti:"AI audit")` | 336 | 10 | all 10 | **10/10** | **0/129** |
| 2. `cat:cs.CY` + governance terms | `cat:cs.CY AND (all:artificial AND all:intelligence) AND (all:governance OR all:regulation OR all:liability OR all:standards)` | 2,592 | 55 | all 55 | 22 clear + 7 borderline | 0/129 |
| 3. firehose minus `evaluation`/`audit` | `all:artificial intelligence AND (governance OR regulation OR liability OR standards)` | 249,905 (−1.9%) | 8,197 | 60 newest titles | **0/60** | 0/129 |

**The judgement rule used on the titles.** A result counts as governance/policy
material when the *object* of the paper is regulation, law, policy, oversight,
standards, liability, auditing-as-institution, public-sector governance, or the
political economy of AI. Technical methods, benchmarks, capability evaluations,
applications and model-behaviour studies do not count even when they mention
governance, evaluation or audit. Borderline means the title frames a governance
question but the artefact looks technical (a compliance tool, a maturity model).

**Decision: option 1, governance terms required in the title.** Reasons, in the
order the measurements give them:

1. It is the only option that measured at **full precision** (10/10) on a bounded
   yield (336 results overall; ~10 per 33 days).
2. Option 3 is not a fix: dropping `evaluation`/`audit` removes 1.9% of the
   results and changes nothing about what is collected (0/60 governance material
   in the newest 60, identical to the firehose).
3. Option 2 is the second-best on precision (40–53%) but five times the volume at
   half the precision, and it **cannot be expressed in this manifest today**: the
   collector prefixes `all:` to any query that declares no field, which demotes
   `cat:cs.CY` to a text term — measured 247,964 results with the prefix versus
   2,592 without. Enabling it would need `categories=` wired through the
   `scholarly_query` row, i.e. a loader change, not a config edit.
4. All four options keep **0 of the 129** contaminated records, so the choice is
   entirely about what the *replacement* collects.

**The query must be sent as written.** `ArxivCollector` used to prefix `all:`
unconditionally, so a field-qualified query became `all:all:(ti:...)`, which arXiv
rejects with **HTTP 400** (measured; the same query without the doubled prefix
returns 336). The collector now leaves a field-qualified query alone and only adds
`all:` when no field is declared. Without that fix, deploying option 1 would have
collected nothing — silently, and with a green test suite, because the config
string looked right.

**What remains open, and is recorded rather than fixed here.** The 129
already-stored records are *not* deleted or relabelled. They are a documented
contaminated stratum: any analysis must exclude or re-audit
`source_name == "ai_governance"` records stored before the deployment date. The
parliamentary arena's share will fall by roughly the contaminated volume when that
exclusion is applied — the issue's own figure (17.4% → 10.4%) is the estimate to
re-derive on the deployed corpus, not to assume.

The ETUI date parser (#297, merged) is untouched by this change.

---

---

## Verification (owner's deployment step)

1. Deploy the query, then confirm the scholarly stage logs no `HTTP 400` — the
   collector must send the field-qualified query as written.
2. Record the first three collected titles as evidence that the yield is
   governance material, and re-check `source_name == "ai_governance"` counts.
3. Apply the documented exclusion for pre-deployment `ai_governance` records
   before recomputing any arena share; the issue's 17.4% → 10.4% estimate must be
   re-derived on the deployed corpus, not assumed.
