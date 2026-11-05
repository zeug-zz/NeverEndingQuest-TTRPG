# Proposal

## Why

The frozen V2 mapping preregistration needs repeatable sandbox tooling before any live comparison: it must project the same party-known spatial facts into relationship-only and hybrid packets, seed isolated one-PC and four-PC rows, and preserve comparable evidence without changing the game. This change supplies provider-free SP1/SP2 tooling so the later, separately authorized D1 and live-matrix work can use the preregistered contracts rather than ad hoc scripts.

## What Changes

- MUST add opt-in mapping-pilot seeding to the existing capture seeder while preserving its omitted-flag behavior byte-for-byte; accept only preregistered seeds and record the effective seed.
- MUST verify `plans/v2-mapping-pilot-prereg/MANIFEST.sha256` before generating a sandbox-only spatial fixture module and derived expected-property files under `tmp/combat_capture/`; never write pilot content to the repository's `modules/` tree or `modules/published_modules.json`.
- MUST define a prototype layout contract, a party/viewpoint-aware knowledge filter, semantically equivalent B/D projections, and the exact shared B/D instruction from the frozen preregistration. Unknowns remain unknown, positions are labelled schematic, and distances appear only when authored.
- MUST provide a sandbox launcher adapter for the existing DM-note and combat-prompt seams. Arm A disables the adapter and has provider-free byte-parity tests. Packets remain stable throughout a turn, including retries and transitions, with per-turn packet-hash evidence.
- MUST provide an observed-not-enforced combat zone ledger, optional sandbox-only `movement_hint` observation, deterministic fixture placement/enemy policy, and preregistered scoring, cap accounting, route-confound reporting, evidence-bundle layout, and M1 sketch rendering.
- MUST provide D1 cartographer tooling for extraction, per-location prompt construction, validation, and audit-sheet generation across three configured published modules and about 20 locations. Its call budget is at most 60; provider-free tests use a fake client. The live D1 run is excluded from this change's build and requires later owner go-ahead.
- MUST include provider-free tests for each capability, including dry seeding of every fixture for both 1-PC and 4-PC parties, plus ASCII and production-boundary checks.
- MUST keep the pilot research-only: no production defaults or `model_config.py` routing changes, core-file edits, published-module changes, installed-campaign changes, `web/` or client work, or port 8357 use. `MULTIPLAYER_MODE` and party-size gates remain untouched.

If the sandbox-only prompt seams cannot be verified, implementation MUST stop. An environment-gated `# TABLETOP MODE:` core hook is outside this change unless the owner explicitly approves a separate scope; it MUST NOT be added as an unapproved fallback.

## Capabilities

### New Capabilities

- `mapping-pilot-tooling`: Specifies the isolated, provider-free-tested tooling contract for preparing and evaluating the preregistered mapping pilot without changing production gameplay.

### Modified Capabilities

None. No existing production behavior requirement changes.

## Impact

Implementation is limited to `scripts/` tooling and tests, plus scratch output beneath project-relative `tmp/`. The proposed layout is a small `scripts/mapping_pilot/` package with focused `scripts/test_mapping_pilot_*.py` suites; the design document will define module ownership and verification order. There are no dependency or production API changes.

The later pilot rows retain the preregistered ceilings of 800 provider attempts total, 35 per row, 6 hours total and 25 minutes per row; D1 is separately capped at 60 calls. Provider-free tooling tests make no provider calls. A later live row that encounters quota or provider outage stops and preserves its failure/blocker evidence rather than substituting a model, row, or additional request.
