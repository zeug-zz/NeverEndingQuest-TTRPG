# Tasks

## 1. Sandbox seam stop/go gate

- [x] 1.1 Before implementation edits, add `scripts/test_mapping_pilot_seams.py` to verify the copied-runtime wrapper points at `main.build_enhanced_dm_note`, `core.combat.prompts.assemble_combat_prompt`, and the combat response-observation path; verify stable logical-turn identity is available without a core edit. Run `.venv/bin/python scripts/test_mapping_pilot_seams.py`. If any seam is absent or turn identity requires a core hook, stop and request explicit owner approval; do not add the hook.

## 2. Frozen fixtures and prototype layout

- [x] 2.1 Add `scripts/mapping_pilot/__init__.py`, `manifest.py`, and `fixtures.py`, plus `scripts/test_mapping_pilot_fixtures.py`; verify all manifest entries before deterministic generation of the four fixture module inputs and derived expected-property files under `tmp/combat_capture/`, and verify mismatch refusal leaves output untouched. Run `.venv/bin/python scripts/test_mapping_pilot_fixtures.py`.
- [x] 2.2 Add `scripts/mapping_pilot/layout_schema.json` and `layout.py`, plus `scripts/test_mapping_pilot_layout.py`; verify stable IDs, schema shape, authored exits/relationships, unknowns, schematic positions, and authored-distance-only behavior. Run `.venv/bin/python scripts/test_mapping_pilot_layout.py`.

## 3. Opt-in Capture Arena seeding

- [x] 3.1 Extend only the opt-in path in `scripts/seed_combat_capture.py` and add `scripts/test_mapping_pilot_seed.py`; verify every fixture dry-seeds for P1 and P4, only counterbalance seeds are accepted and recorded, invalid options fail before mutation, and the omitted-option output matches the legacy byte baseline. Run `.venv/bin/python scripts/test_mapping_pilot_seed.py`.

## 4. Party/viewpoint knowledge filter (reasoning-heavy)

- [x] 4.1 Add `scripts/mapping_pilot/knowledge.py` and `scripts/test_mapping_pilot_knowledge.py`; verify hidden facts and unperceived exits never leak, viewpoint filtering does not create per-PC persistent knowledge, unknowns stay unknown, and absence is not treated as nonexistence. Run `.venv/bin/python scripts/test_mapping_pilot_knowledge.py`.

## 5. B/D packet projections

- [x] 5.1 Add `scripts/mapping_pilot/projections.py` and `scripts/test_mapping_pilot_projections.py`; verify B and D use the same filtered facts and exact preregistered instruction, D adds only an ASCII schematic, and repeated rendering yields identical packet bytes and hashes. Run `.venv/bin/python scripts/test_mapping_pilot_projections.py`.

## 6. D1 cartographer tooling (provider-free)

- [x] 6.1 Add Python source extraction and per-location prompt construction in `scripts/mapping_pilot/cartographer.py`, plus `scripts/test_mapping_pilot_cartographer.py`; verify the tool accepts three configured published module slugs and about 20 selected locations, builds one prompt per location, and uses only fixture/fake-client inputs in the test. Run `.venv/bin/python scripts/test_mapping_pilot_cartographer.py`.
- [x] 6.2 Complete D1 layout validation, existing-graph exit checks, audit-sheet output, and the 60-call guard in `scripts/mapping_pilot/cartographer.py`; extend `scripts/test_mapping_pilot_cartographer.py` to cover valid/invalid layouts, the call cap, and project-relative `tmp/` output with no `modules/` writes. Run `.venv/bin/python scripts/test_mapping_pilot_cartographer.py`.

## 7. M1 ASCII sketches

- [x] 7.1 Add `scripts/mapping_pilot/m1.py` and `scripts/test_mapping_pilot_m1.py`; verify deterministic sketches for fixtures and validated D1 layouts use the same filtered projection, label schematic positions, and add no hidden anchors, exits, or distances. Run `.venv/bin/python scripts/test_mapping_pilot_m1.py`.

## 8. Sandbox injection adapter (reasoning-heavy)

- [x] 8.1 Add `scripts/mapping_pilot/adapter.py` and `launcher.py`, plus `scripts/test_mapping_pilot_adapter.py`; wrap only the verified sandbox seams, delegate originals unchanged, and prove arm A produces byte-identical DM-note and combat-prompt outputs with no augmentation. Run `.venv/bin/python scripts/test_mapping_pilot_adapter.py`.
- [x] 8.2 Extend `scripts/mapping_pilot/adapter.py` and its tests to prove a B/D packet is reused byte-for-byte across normal prompt construction, validation retries, and same-turn transitions, with a per-turn packet-hash record. Run `.venv/bin/python scripts/test_mapping_pilot_adapter.py`.

## 9. Shadow combat zone ledger (reasoning-heavy)

- [x] 9.1 Add `scripts/mapping_pilot/zone_ledger.py` and `scripts/test_mapping_pilot_zone_ledger.py`; verify fixture-derived P1/P4 placements, engagement groups, adjacency, elevation, cover, bands, deterministic enemy movement/tie-breaks, movement-hint validation for one/two steps, contradiction counts, and that no observation changes or vetoes mechanical state. Run `.venv/bin/python scripts/test_mapping_pilot_zone_ledger.py`.

## 10. Scoring and evidence

- [x] 10.1 Add `scripts/mapping_pilot/scoring.py` and `scripts/test_mapping_pilot_scoring.py`; verify section 7.1 measures, not-estimable denominators, separate regression guards, unknown-not-zero cost, 800/35 attempt caps, 6-hour/25-minute wall-time caps, and the 10-percentage-point resolved-model imbalance flag plus fallback/unknown-model differences. Run `.venv/bin/python scripts/test_mapping_pilot_scoring.py`.
- [x] 10.2 Add `scripts/mapping_pilot/evidence.py` and `scripts/test_mapping_pilot_evidence.py`; verify unique per-row bundles under `tmp/router-rollout/mapping-pilot/<gate>/<run-id>/`, required section 8 provenance/artifacts, no secret fields, and rejection of bundle reuse. Run `.venv/bin/python scripts/test_mapping_pilot_evidence.py`.

## 11. Integrated verification and boundary audit

- [x] 11.1 Add `scripts/test_mapping_pilot_boundaries.py` and run `.venv/bin/python -m unittest discover -s scripts -p 'test_mapping_pilot_*.py'`; verify provider-free operation, all four fixtures for P1/P4, arm-A parity, project-relative scratch paths, and production-boundary assertions.
- [x] 11.2 Run `python3 scripts/check_ascii_compliance.py --summary-only` and `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-mapping-pilot-tooling --strict`; review `git diff --name-only` to confirm changes are limited to `scripts/` and `openspec/changes/v2-mapping-pilot-tooling/`, with no `core/`, `main.py`, `model_config.py`, published-module, installed-campaign, web/client, or port 8357 change. Do not start a server or run the live D1 operation.

## Workflow follow-up

- The separate live D1 run is not a build task in this change. Before that later operation, obtain owner go-ahead and the selected three module slugs/location set; keep its calls at or below 60 and preserve offline/live evidence separately.
- Live SP3/SP4 execution and primary adjudication remain outside this tooling change and require their own authorized workflow.
