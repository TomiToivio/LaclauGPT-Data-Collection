# Study / arena collection configuration audit

Issue #20 audits the modular Collection package against the configuration conventions that evolved in the older public and private LaclauGPT discourse-analysis repositories. The goal is compatibility of **collection semantics**, not copying Analysis configuration into Collection.

## Source audit

| source path | capability | exists now? | decision | target Collection path | privacy notes |
|---|---|---:|---|---|---|
| `LaclauGPT-Discourse-Analysis/collector/config.py` | study window, platform toggles, candidates/parties/groups, handle validation | yes, adapted | keep/adapt | `src/laclaugpt_data_collection/study.py` | executable public fixtures remain synthetic |
| private `config/projects/ai26.yaml` | project ID, title/languages, retain-unjudged relevance plus Analysis switches | partial | port project metadata; reject Analysis switches | `configs/studies/ai26.example.yaml`, `effective_config.py` | no private runtime values are copied |
| private `config/arenas/elites.yaml` | arena title, platform/language/country metadata, collection notes and discovery hints | partial | adapt collection fields; convert analytic hints to discovery-only hints | layered arena config / AI26 public reference | model and Analysis settings rejected |
| private `config/arenas/grassroots.yaml` | grassroots arena scope and collection hints | partial | adapt collection fields | AI26 public reference | real target lists remain runtime/private |
| private `config/arenas/parliamentary.yaml` | parliamentary arena scope and governance anchor | partial | adapt collection fields | AI26 public reference | institutional collection preferred over partisan watch lists |
| private `run_configs/arena_elites.yaml` | model/stages plus duplicated arena metadata | no | reject model/stages; retain only compatible metadata if used as a layer | `effective_config.py` | Analysis execution belongs in Data Analysis |
| private/public source manifests | RSS/web source-family lists, priorities, sampling rationale | partial | retain generic convention and validate malformed feeds | `configs/studies/*.sources*.toml`, `server_runner.load_feed_manifest()` | operational/private extensions can live outside Git |
| public deployment TOML (`configs/laptop*.toml`, `server*.toml`) | machine, execution and storage profile | yes | include as machine/execution layers | `effective_config.resolve_collection_config()` | safe checked-in examples contain no secrets |

## Canonical resolution order

Collection now has a deterministic effective-configuration chain:

```text
project/study
  -> arena
    -> machine
      -> execution
        -> private runtime overrides
          -> explicit CLI/agent overrides
```

YAML and TOML layers can be mixed. Nested mappings merge recursively; later scalar/list values replace earlier values. The resolver computes a deterministic SHA-256 fingerprint for each layer and the effective configuration.

Legacy/private arena files are accepted as inputs without importing Analysis-only `analysis`, `model`, `stages`, or `memory_dir` settings. The old `dataset` block is projected into collection-facing metadata, and legacy `analytic_hints` are retained only as **discovery hints**. They are never treated as document classifications.

## Effective snapshot and provenance

`EffectiveCollectionConfig.safe_snapshot()` returns an inspectable representation containing:

- effective config hash;
- ordered layer identifiers and hashes;
- project/study, arena, machine/execution and operational collection settings;
- redacted secret-bearing values;
- redacted target/source lists.

Only a basename is retained for file-backed layer provenance so private directory structure is not leaked. `stamp_config_provenance()` attaches the compact safe provenance envelope to a canonical record. It deliberately does **not** serialize private source lists, credentials or full private configs.

## Private injection pattern

A public installation remains sufficient for local/synthetic use. A real study can extend the public project layer at runtime, for example:

```text
public module/
  configs/studies/ai26.example.yaml
  configs/laptop.example.toml

private runtime root/
  config/projects/ai26.yaml
  config/arenas/elites.yaml
  config/sources/ai26.sources.toml
  secrets/...
```

The private layer may override retry/pagination limits, enabled collectors, source lists or deployment details. The resulting effective hash records that a particular configuration was used without publishing its contents.

## AI26 collection taxonomy

The public AI26 example follows the paper rather than treating old source lists as a permanent ontology. The three empirical arenas are:

1. AI elites;
2. grassroots mobilisation;
3. parliamentary/electoral politics.

The public collection codebook uses the same small provisional formation vocabulary as the Analysis pipeline:

- accelerationism;
- doomerism;
- left-wing accelerationism;
- AI safety;
- AI critical;
- anti-AI.

These are **sampling anchors only** in Collection. Richer terms such as techno-optimism, x-risk, alignment, open-source advocacy, anti-hype, labour rights, public-interest AI, corporate governance and national-security competition remain source/discovery facets rather than extra top-level formations.

The September 2026 AI26 reference settings also include the live pacing/safety/competition dispute through discovery terms such as `pacing`, `independent evaluation`, `competition`, `AI race`, `China`, `liability` and `data centres`. This is intentionally relational: Collection must not freeze companies, movements or political actors into permanent ideological labels.

## Source-list validation

The RSS manifest loader now fails visibly for malformed enabled entries instead of silently dropping them. Enabled feeds require:

- a non-empty `name`;
- an HTTP(S) `feed_url`;
- optional `priority` of `P1`, `P2` or `P3`;
- a boolean `enabled` value when supplied.

Disabled entries are ignored. The convention remains simple enough for hand-maintained private manifests and cron/server operation.

## Boundary with Analysis

Collection may know enough theory to produce balanced sampling and arena/source-family provenance. It must not perform Laclaudian interpretation. Nodal/floating/empty signifiers, equivalence/difference, antagonism, affect, imaginaries, populism and final formation coding remain Data Analysis responsibilities.
