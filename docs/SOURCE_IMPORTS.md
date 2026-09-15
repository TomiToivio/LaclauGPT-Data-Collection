# Source Import Map

This cleanup consolidates reusable collection code and patterns while removing unrelated analysis/simulation logic and all private operational material.

## Primary source: LaclauGPT-Discourse-Analysis

Imported/adapted as the architectural core:

- native TikTok/Instagram/X parser model under `collector/modules/`;
- stable normalization/provenance envelope from `collector/normalize.py`;
- browser/network-capture architecture and Firefox-first workflow;
- Bluesky public-XRPC collection pattern;
- separation of raw capture, normalized records, media and collection state.

The original collector explicitly states that collection produces source material and discourse analysis happens later. This repository makes that boundary structural.

## LaclauGPT-TikTok-Scraper

The original scraper is retained as design lineage for TikTok endpoint routing and browser capture. The current TikTok parser is the newer LaclauGPT-native implementation derived from that lineage rather than a wholesale copy of legacy Node/Firefox code.

## CyborgAnthropology

Reusable generic-source concepts are represented as optional adapters for feeds, public web/URL collection and future YouTube/Telegram/arXiv collectors. Analysis and project-specific code are not imported.

## LaclauGPT-Data-Storage

Only backend-integration ideas are used here: records and objects are behind interfaces, with MongoDB/S3 optional. Durable cross-project storage administration remains the responsibility of the Data Storage module.

## LaclauGPT-Social-Simulation-Laboratory

Only collection-worker/browser and scheduling ideas are relevant. Simulation models, agents and scenario logic are excluded.

## LaclauGPT-Discourse-Analysis-Private

Private code was treated as a review source, not as publishable content. Generic ideas retained include:

- laptop collector topology with filesystem/local state;
- server/distributed topology;
- collector-only execution mode;
- legacy generic collector interface patterns.

Real study configuration, account lists, researcher data, machine-specific paths, credentials and anything under private-only boundaries are deliberately not copied.

## Rule for future imports

Before copying code from another LaclauGPT repository:

1. verify the code is genuinely collection-related;
2. verify license/provenance;
3. remove project-specific paths, targets and credentials;
4. convert configuration to environment/example configuration;
5. make emitted records comply with the interoperability schema;
6. add synthetic tests;
7. document the import here.
