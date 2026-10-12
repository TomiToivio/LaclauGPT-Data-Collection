# AI26 X account-sampling audit

Work package B of [#258](https://github.com/TomiToivio/LaclauGPT-Data-Collection/issues/258):
audit the configured AI26 X targets against the locked Phase 1 paper and the three empirical
arenas, and report gaps with evidence.

**This document is sampling provenance, not ideological classification.** Per
`configs/studies/ai26.example.yaml` and paper §4.1, inclusion is a sampling decision and
downstream analysis must infer positions from documents and relations, not from source
identity. No formation label below is applied to an actor; the *candidate formations* column
records why a stratum exists, not what an account believes.

Verified 2026-10-12 against `origin/main` = `94f8d6c` (23 configured X handles).
**Nothing in this document has been applied to any config.** Section 6 is a proposed diff
awaiting author approval.

## 1. Method, and what it can and cannot show

An unauthenticated probe of `https://x.com/<handle>` reading the Open Graph metadata:

```bash
curl -s --compressed -A '<browser UA>' -L --max-time 25 "https://x.com/$HANDLE" -o /tmp/x.html
# then read <meta property="og:title"> and <meta property="og:description">
```

The probe is calibrated, not assumed. A genuinely nonexistent handle returns **404** with
`og:title = "User Profile Not Found - X | 404 Error"` (confirmed with `@OECDdigital`, which
does not exist), while a live handle returns **200** with a real `og:title` of the form
`Display Name (@handle) on X`. Every finding below was reproduced on **two separate fetches**.

Limits, stated plainly:

- It establishes **existence and displayed identity only**. It does **not** measure recent
  activity, posting volume, or post content.
- `og:description` is the account bio for most handles, but for some accounts it is a
  **recent post text** (observed on `@pmarca`). It is identity evidence, not a bio field.
- Suspended, temporarily restricted, or intermittently rate-limited accounts are not
  distinguishable from active ones by this method.
- Follower counts appear only in X's empty-timeline fallback string, so they are visible for
  near-empty accounts and invisible for normal ones.

Consequently: **activity and reachability of every handle below still require the signed-in
browser tour of work package A.** This audit is necessary but not sufficient for that.

## 2. Verified defects — 3 of 23 configured handles

| Handle | Group / arena | Finding | Evidence (reproduced twice) |
|---|---|---|---|
| **`MIRI_AI`** | `xrisk_safety_x` / elites | **Wrong target.** Resolves to a personal account, not the Machine Intelligence Research Institute. | `og:title` = `AI (@miri_ai) on X`, `og:description` = a Japanese-language personal bio (`🧶🧵/⛸️/🐴/🍏 笑顔で幸せでありますように🍀✨💕`). Contrast the real organisation handle **`@MIRIBerkeley`**: `MIRI (@MIRIBerkeley) on X`, `"The Machine Intelligence Research Institute exists to maximize the probability that the creation of smarter-than-human intelligence has a positive imp…"`. |
| **`MetaAI`** | `frontier_labs_x` / elites | **Superseded by the organisation itself.** The account announces its own move. | `og:title` = `AI at Meta (@metaai) on X`, bio = `"We've moved, follow us at @AIatMeta for the latest on AI research and innovation from Meta."` **`@AIatMeta`** is live: `AI at Meta (@AIatMeta) on X`, `"We're building the future of personal superintelligence…"`. Collecting `MetaAI` yields a pointer, not current material. |
| **`OECD_AI`** | `governance_institutions_x` / parliamentary | **Inactive / effectively empty.** | `og:description` is X's empty-timeline fallback: `"14 followers · 0 following. Joined Nov 2021. See the latest conversations with @OECD_AI"`. Contrast **`@OECD`**, which is a live institutional account (`OECD ➡️ Better Policies for Better Lives (@OECD) on X`, `"…| Secretary-General: @MathiasCormann"`). |

`@MIRI_AI` is the most serious of the three: it is not a stale pointer but a **different
entity**, so the existential-risk stratum currently samples a stranger's personal timeline
while presenting it as MIRI.

## 3. Migration pressure, overlap and internal heterogeneity

- **Cross-platform duplication.** `@timnitGebru` now displays as
  `@timnitGebru (@dair-community.social/bsky.social) (@timnitGebru) on X` and `@emilymbender`
  as `@emilymbender.bsky.social (@emilymbender) on X`. Both are **also** configured on Bluesky
  and Mastodon inside the same `critical_ai_x` group, so one actor is counted across three
  platforms while the X leg is a bridge/parked account.
- **Announced platform migration.** `@FLI_org` and `@AdaLovelaceInst` both advertise Bluesky
  in their bios.
- **Self-declared low volume.** `@ESYudkowsky`: `"This is my serious low-volume account."`
- **One institution, two groups.** `@sama` sits in `techno_optimism_x` while `@OpenAI` — the
  organisation he leads — sits in `frontier_labs_x`. The same institution therefore appears
  in two strata.
- **A group the config itself calls non-synonymous.** `techno_optimism_x` (`@pmarca`,
  `@ylecun`, `@sama`) mixes a venture-capital techno-optimist, an academic deep-learning
  optimist, and a frontier-lab CEO. The group's own note says these traditions "should not be
  treated as synonymous", so the grouping is a retrieval convenience, and analysis must not
  read it as one position.
- **`@FLI_org` is not purely existential-risk.** FLI's own bio is `"reducing extreme risks"`
  (broader than AI), and paper §2.3 states that "concern about AI safety alone does not
  establish adherence to an existential-risk formation". The `xrisk_safety_x` group mixes
  x-risk-specific actors with a broader-risk institution.

## 4. Arena balance against paper §4.1

Counts of configured **X** handles by arena:

| Arena | X handles | Share | Composition |
|---|---|---|---|
| elites | 15 | 65 % | frontier labs (5), techno-optimism (3), x-risk/safety (3), critical AI (4) |
| grassroots | 4 | 17 % | labour/creator (3), pause/deployment-resistance (1) |
| parliamentary | 4 | 17 % | `EU_Commission`, `Europarl_EN`, `OECD_AI`, `NIST` |

Two structural observations:

1. **The parliamentary arena is served by the wrong actor type.** Paper §4.1 defines the third
   arena as "parliamentary and electoral politics … parliamentary debates, party programmes,
   campaign communications". The four configured handles are an executive body, a
   legislature-as-institution, an intergovernmental organisation, and a national standards
   agency. There is **no party, parliamentarian, candidate or campaign handle** configured,
   and **no first-party Finnish parliamentary X handle** (the Finnish Government is
   Bluesky-only). Governance-institution discourse is legitimate material, but it is not the
   same construct as parliamentary/electoral articulation, and §4.1 warns that "links between
   public discourse and policy outcomes must be demonstrated rather than inferred".
2. **The grassroots arena is thin, and thinner than the design.** 3 of the 6 configured
   grassroots groups carry **no X handles at all** (creator-rights/licensing,
   digital-rights/civil-liberties, data-centre/energy) — they are Bluesky/RSS-only. So the
   anti-AI/deployment-opposition and infrastructure-conflict strata that #258 asks to check
   have no X presence by design, and the grassroots X stratum is labour unions plus `@PauseAI`.

**Left-wing techno-optimism: 0 X handles, deliberately.** `left_techno_optimism_discovery` is
a discovery stratum using terms (`post-work`, `postcapitalism`, `public AI`, `public compute`,
`democratic AI`, `automation dividend`, `technological emancipation`) and entities rather than
pre-assigned accounts. Given paper §2.3's caution about collapsing left techno-optimism into
market accelerationism or into a programme of accelerated automation, this is recorded as a
**defensible coverage choice, not a defect** — but it does mean the abstract's "left-wing
techno-optimism" starting point is covered by discovery only.

## 5. Runtime divergence on this workstation

The private runtime study config on this workstation declares **8 groups / 23 X handles**,
while `configs/studies/ai26.example.yaml` declares **11 groups / 23 X handles**. Group ids and
counts only are reported here; no private handle name is reproduced.

The three groups present in the public design but **absent from the runtime copy** are exactly
the Bluesky-only grassroots ones: `grassroots_creator_rights_licensing`,
`grassroots_datacentre_energy_conflict`, `grassroots_rights_digital_civil_liberties`.

Consequence: the deployed grassroots stratum is thinner than the paper's design. This is a
**study-config deployment gap** of the same family as #206 ("deployed collection config is
stale and hand-edited"), not a sampling decision — the sampling decisions are already recorded
in the public template. It should be reconciled by the deployment path, not by editing the
design.

Related context: #207 recorded the X stratum as **nominal** (55 records from one 2026-09-16
run, none from a configured handle, arena blank, 12 below the publication floor). Combined
with §2 above, the X stratum has both a **reachability** problem and a **target-validity**
problem, and only the former is addressed by work package A.

## 6. Proposed bounded changes — PENDING AUTHOR APPROVAL, NOT APPLIED

Caps respected: `target_accounts_soft_cap: 28`, `per_target_per_poll_cap: 4`,
`daily_record_cap: 240`. Every proposal below is a **1:1 replacement**, so the count stays at
**23** and no cap moves. Per #258, sampling changes stay reviewable separately from runtime
repairs, and if a decision cannot be made confidently it stays pending.

| # | Group | Remove | Add | Why | Confidence |
|---|---|---|---|---|---|
| 1 | `xrisk_safety_x` | `MIRI_AI` | `MIRIBerkeley` | The configured handle is a different entity; the replacement is MIRI's actual account and its bio matches MIRI's mission verbatim | **High** — both sides verified |
| 2 | `frontier_labs_x` | `MetaAI` | `AIatMeta` | The configured account states it moved to the replacement; the lab stratum should track the live account | **High** — the move is self-declared by the account |
| 3 | `governance_institutions_x` | `OECD_AI` | `OECD` | `OECD_AI` is an empty shell (14 followers, 0 following, no timeline); `@OECD` is the live institutional account | **Medium** — `@OECD` is verified live, but it is a general OECD account, not AI-specific, so the AI-governance rationale weakens. Author's call; dropping the row entirely is also defensible |

**Not proposed, deliberately.** No additions are proposed for the parliamentary/electoral gap
in §4, because naming party or campaign handles is a sampling decision about political actors
with real analytical consequences, and #258 says to keep such decisions pending rather than
make them confidently-unsupported. The gap is recorded instead. Likewise no new grassroots X
handles are proposed: the design's grassroots depth is Bluesky/RSS-based, and §5 suggests the
first fix is deploying the existing groups.

## 7. What this audit could not verify

- Recent activity, posting volume, or whether any of the 23 accounts is currently restricted
  or intermittently unavailable.
- Whether the private runtime config contains X targets beyond the 23 public ones. **It was
  not inspected for handle names, and none are reproduced here.**
- Any account's substantive positions. Candidate formations remain group-level sampling
  hypotheses.

All three require the signed-in Firefox tour and distributed MongoDB writes of work package A.
Until that runs, this audit should be read as **target-validity** evidence only.
