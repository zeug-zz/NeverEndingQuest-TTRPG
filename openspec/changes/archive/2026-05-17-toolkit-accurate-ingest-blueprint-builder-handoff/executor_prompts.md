# Builder Execution Prompts: Phase 4 Blueprint Builder Handoff

Use these prompts to implement the change in small, reviewable passes. Each prompt assumes Phase 1 source graph artifacts and Phase 2-3 multipass/fidelity artifacts are available in the workspace.

## Prompt 1: Blueprint Utility and Fidelity Precheck

Implement only the foundational utility and fidelity precheck.

MUST do:

- Add `utils/toolkit_builder_blueprint.py` with the standard SPDX/header style.
- Add constants for:
  - `BUILDER_BLUEPRINT_VERSION = "source_faithful_builder_blueprint.v1"`
  - `BUILDER_HANDOFF_MODE_SOURCE_BLUEPRINT = "source_blueprint"`
  - refusal statuses such as `missing_artifacts`, `blocked_by_fidelity`, `failed_fidelity`, `invalid_packet`, `generation_failed`.
- Add helpers to load Phase 2-3 artifacts from a workspace path:
  - `source_graph.json`
  - `identity_resolution_report.json`
  - `plot_topology_report.json`
  - `source_graph_synthesis_report.json`
  - `normalized_packet.json`
  - `normalization_fidelity_report.json`
  - `normalization_report.json`
- Add `evaluate_blueprint_fidelity_precheck(...)`.
- Return structured precheck results, never bare booleans.
- Refuse blocked/failed fidelity by default.
- Allow clean/repaired fidelity.
- Allow degraded fidelity only when there are no blocking required-source findings.
- Add `build_builder_blueprint_report(...)`.

MUST NOT do:

- Do not modify packet builder yet.
- Do not generate builder narrative yet.
- Do not touch `ModuleBuilder` or `ModuleGenerator`.

Verification:

- Add `scripts/test_builder_blueprint_fidelity_gate.py`.
- Run `.venv/bin/python -m py_compile utils/toolkit_builder_blueprint.py scripts/test_builder_blueprint_fidelity_gate.py`.
- Run `.venv/bin/python scripts/test_builder_blueprint_fidelity_gate.py`.

## Prompt 2: Blueprint Generation

Implement deterministic blueprint generation from Phase 2-3 artifacts.

MUST do:

- Add `generate_builder_blueprint(...)` to `utils/toolkit_builder_blueprint.py`.
- Build `builder_blueprint.json` with:
  - `blueprint_version`
  - `source_hash`
  - `normalized_packet_hash`
  - `fidelity_status`
  - `blueprint_status`
  - `module`
  - `source_lock`
  - `area_plan`
  - `location_roster`
  - `npc_roster`
  - `plot_graph`
  - `puzzle_graph`
  - `clue_graph`
  - `encounter_plan`
  - `item_roster`
  - `tone_requirements`
  - `source_refs`
  - `warnings`
- Preserve source atom IDs and original source display names.
- Use identity report aliases for NPC/location aliases.
- Use plot topology report for plot, puzzle, and clue graphs.
- Use normalized packet only as reviewed packet shape/supporting data, not as the sole truth source.
- Carry unsupported invention findings into blueprint warnings/forbidden replacements.

MUST NOT do:

- Do not call an LLM for blueprint structure.
- Do not invent source facts to fill blueprint gaps.
- Do not apply narrative enrichment.

Verification:

- Add `scripts/test_builder_blueprint_generation.py`.
- Include a Numillian-style fixture with many NPCs, keyed locations, and Trial-at-the-Door-style puzzle chain.
- Run `.venv/bin/python scripts/test_builder_blueprint_generation.py`.

## Prompt 3: Source-Locked Builder Narrative

Implement deterministic narrative serialization from blueprint.

MUST do:

- Add `serialize_builder_blueprint_to_narrative(...)`.
- Emit sections in this order:
  - `SOURCE-FAITHFUL BUILD LOCK`
  - `MODULE IDENTITY AND TONE`
  - `REQUIRED LOCATION ROSTER`
  - `REQUIRED NPC ROSTER`
  - `PLOT TOPOLOGY`
  - `PUZZLE AND TRIAL RULES`
  - `CLUE GRAPH`
  - `ENCOUNTER AND MONSTER PLAN`
  - `ITEM AND TREASURE PLAN`
  - `FORBIDDEN INVENTIONS AND REPLACEMENTS`
  - `ALLOWED COMPRESSION OR MERGE NOTES`
- Include exact source names and aliases.
- Include explicit forbidden-invention and replacement-plotline language.
- Keep output ASCII-safe.
- Ensure required source material is listed, not summarized away.

MUST NOT do:

- Do not compress required rosters into vague prose.
- Do not remove legacy narrative helpers until integration is complete.

Verification:

- Add `scripts/test_builder_narrative_source_lock.py`.
- Assert exact headings and exact source names are present.
- Assert forbidden-invention guidance is present.
- Run `.venv/bin/python scripts/test_builder_narrative_source_lock.py`.

## Prompt 4: Artifact Helpers and Normalizer Integration

Wire blueprint artifacts into the existing workspace artifact contract and normalization/build-prep seam.

MUST do:

- Extend `utils/toolkit_homebrew_upload_contract.py` with paths and helpers for:
  - `builder_blueprint.json`
  - `builder_blueprint_report.json`
- Add atomic persistence helpers.
- Add safe load helpers.
- Add feature flag support in `model_config.py` if not already present:
  - `ENABLE_ACCURATE_INGEST_BLUEPRINT_HANDOFF`
- Integrate blueprint generation after Phase 3 fidelity audit/repair and before final builder narrative persistence.
- Persist blueprint-derived `builder_narrative.md` only when blueprint status is ready.
- Persist compact blueprint status in an existing report surface.
- In accurate-ingest blueprint mode, fail closed on blueprint generation/persistence failure.
- In disabled/legacy mode, preserve legacy builder narrative behavior.

MUST NOT do:

- Do not change review UI.
- Do not add build-time stage gates.

Verification:

- Add or extend normalizer/upload contract tests.
- Run accurate-ingest source graph, multipass, and fidelity regression tests.

## Prompt 5: Packet Builder Handoff

Update packet builder to consume blueprint-backed handoff safely.

MUST do:

- Update `web/extensions/toolkit_homebrew_packet_builder.py` to load blueprint artifacts when present.
- Extend `builder_input.json` with:
  - `builder_input_version`
  - `handoff_mode`
  - `builder_blueprint_path`
  - `builder_narrative_path`
  - `blueprint_status`
  - `fidelity_status`
  - `source_lock`
  - `source_artifacts`
- Ensure `_read_builder_narrative(...)` prefers blueprint-derived narrative when `handoff_mode == "source_blueprint"` and blueprint status is ready.
- Refuse build execution when blueprint mode is required but blueprint status is not ready.
- Preserve old workspace behavior.

MUST NOT do:

- Do not rewrite `ModuleBuilder` internals.
- Do not add final build fidelity gates.

Verification:

- Add `scripts/test_packet_builder_blueprint_handoff.py`.
- Cover source-blueprint handoff, blocked blueprint refusal, missing blueprint legacy fallback, and builder input metadata.
- Run `.venv/bin/python scripts/test_packet_builder_blueprint_handoff.py`.

## Prompt 6: Final Validation and OpenSpec Verification

Run the final validation set and update task checkboxes only after all tests pass.

MUST run:

```bash
.venv/bin/python -m py_compile utils/toolkit_builder_blueprint.py utils/toolkit_homebrew_upload_contract.py utils/toolkit_homebrew_normalizer.py web/extensions/toolkit_homebrew_packet_builder.py
.venv/bin/python scripts/test_builder_blueprint_fidelity_gate.py
.venv/bin/python scripts/test_builder_blueprint_generation.py
.venv/bin/python scripts/test_builder_narrative_source_lock.py
.venv/bin/python scripts/test_packet_builder_blueprint_handoff.py
.venv/bin/python scripts/test_accurate_ingest_source_graph.py
.venv/bin/python scripts/test_toolkit_normalization_fidelity.py
openspec validate toolkit-accurate-ingest-blueprint-builder-handoff
```

Also run any existing multipass/normalizer regression tests present in the repository.

MUST report:

- Files changed.
- New artifacts generated.
- Test commands and results.
- Any pre-existing failures.
- Whether Phase 5 build-time fidelity gates are now ready to scaffold.
