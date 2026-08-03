# Step 2.1 Evidence: Final-Editor Prompt Contract

Date: 2026-06-11

## 1. Files Added

- `prompts/toolkit/final_reconciliation_builder_prompt.txt` (new)

## 2. Files Modified

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md` (Step 2.1 checked off with completion notes)

## 3. Files Read (Context)

- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/proposal.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/design.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-llm-builder-final-editorial-pass/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-final-reconciliation-patch-contract/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/specs/accurate-ingest-bogus-source-atom-cleanup/spec.md`
- `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/evidence/step-1-1-baseline.md`
- `utils/toolkit_final_reconciliation.py` (existing brief/report helper for editable surfaces contract)
- `prompts/toolkit/normalization_fidelity_repair_prompt.txt` (style)
- `prompts/toolkit/blueprint_field_enrichment_prompt.txt` (style)
- `prompts/toolkit/source_identity_adjudication_prompt.txt` (style)
- `prompts/toolkit/source_section_extraction_prompt.txt` (style)
- `prompts/toolkit/homebrew_upload_normalization_prompt.txt` (style)

## 4. Prompt Contract Summary

The new prompt is a strict patch-plan contract for the final editorial boundary.
It runs ONLY after source graph, normalized packet, blueprint, backstage
audit, and source-enhanced ModuleBuilder have all completed. It consumes
`final_reconciliation_brief.json` and emits a single JSON object with
exactly six top-level keys:

- `version` (string, must be `accurate_ingest_final_reconciliation_patch.v1`)
- `status` (one of `ready`, `refused`, `failed`)
- `source_fidelity_claim` (string; MUST be `reconciled_degraded` when
  original source fidelity is blocked/degraded and accepted reconciliation
  is needed; MUST NOT claim clean `pass` unless the brief states source
  fidelity truly passed)
- `publication_intent` (string; `playable_module` for accepted/refused
  cases)
- `decisions` (array of decision objects)
- `file_patches` (array of patch objects; may be empty when bogus atoms
  are absent from ModuleBuilder output, which is the common Well of Ruin
  case)

### Decision Types (6, all bounded)

- `delete_bogus_atom`
- `reclassify_atom`
- `merge_into_existing`
- `preserve_as_dm_guidance`
- `create_missing_real_element` (only for atoms clearly present in source)
- `refuse`

### Forbidden Targets (rejected by Python gate, prompt pre-states)

- Runtime-only files (live `areas/*.json` other than `*_BU.json`,
  `module_plot.json` live state, `party_tracker.json`,
  `player_quests_*.json`, `encounters/**`, `modules/world_registry.json`,
  `modules/campaign.json`)
- Absolute paths
- Paths outside module_dir (paths starting with `..`, `/`, or `C:\`)
- Source graph, source manifest, normalized packet, blueprint, backstage
  audit, ingestion artifacts (e.g. `source_graph.json`,
  `source_manifest.json`, `normalized_packet.json`, `blueprint_*.json`,
  `accurate_ingest_audit_run/`, `agent_runs/`)
- `MODULE_SUMMARY.md` as a source of truth (downstream prose, not editable)
- Any file not listed in `editable_surfaces` in the brief

### Allowed Target Surfaces

ONLY files explicitly listed in `editable_surfaces` in the brief. The brief
is the whitelist. Common examples that may appear in editable_surfaces:

- `module_context.json`
- `module_context_BU.json`
- `module_plot_BU.json`
- `areas/*_BU.json`
- `map_*.json`

### Source-Fidelity Honesty Rules

- `source_fidelity_claim` MUST be `reconciled_degraded` when original
  source fidelity was blocked or degraded and accepted reconciliation is
  required.
- MUST NOT claim `pass`, `clean_pass`, or equivalent clean language unless
  the brief states the original source fidelity truly passed.
- Playable publication may pass as `reconciled_degraded` (degraded with
  waiver); clean source fidelity must not be claimed unless it truly
  passed.

### Status Semantics

- `ready` -- patch plan is valid, targets only whitelisted surfaces, safe
  to apply.
- `refused` -- reconciliation unsafe even after all decisions considered
  (e.g. real missing playable element with no editable surface, or fatal
  blocker present in evidence).
- `failed` -- cannot produce a valid patch plan for a known reason (e.g.
  missing required input key).

### ID and Structure Preservation

- Do NOT change module IDs, area IDs, location IDs, NPC IDs, item IDs, or
  monster IDs.
- Allowed surface rewrites are content-level (text fields, descriptions,
  plot points, optional sub-structures) within existing IDs.
- Keep patches minimal. One decision and one patch per blocker is enough
  unless the brief explicitly groups blockers.

### Well-Like Bogus Heading Treatment

The prompt explicitly enumerates the 12 Well of Ruin blocker terms and
classifies them into bogus patterns:

- Trap mechanics H3 sub-headings: `Trigger`, `Passive Element`,
  `Active Element` (source lines 17, 22, 41 in the archived baseline).
- Lore sub-section headings: `Echoes of Calamity`, `Deciphering Ruin`.
- Rune variant table headers: `**Well**spring of Legend`.
- Language list/table column headers: `Celestial`, `Draconic`, `Orcish`,
  `Infernal`, `Primordial`, `Abyssal`.

Decision priority for bogus headings: `delete_bogus_atom` (preferred),
`preserve_as_dm_guidance` (keep as DM mechanics in an existing location),
or `reclassify_atom` (move from required location to trap/hazard/lore
note) when a reclassification target already exists. NEVER use
`create_missing_real_element` to fabricate a playable room for a bogus
heading.

## 5. Style Consistency With Existing Toolkit Prompts

The new prompt follows the same conventions as the other prompts under
`prompts/toolkit/`:

- Role statement first ("You are a ...")
- Section headers: `=== SECTION ===` style
- MUST rules section with numbered items
- Strict output schema example
- Worked examples (here: 3 examples covering bogus cleanup, refusal, and
  failed status)
- ASCII-only output (no smart quotes, em-dashes, or Unicode arrows)

## 6. No Tests Added In This Step

- `scripts/` was searched (grep) for any natural contract test that
  already reads toolkit prompt file content. No matches found.
- Existing toolkit prompt files (normalization, blueprint enrichment,
  source identity, source section extraction, homebrew upload) have no
  prompt-content contract tests.
- Creating broad prompt-content test infrastructure is out of scope for
  Step 2.1 and forbidden by the Step 2.1 instructions ("do not create
  broad infrastructure").
- The prompt contract will be exercised in Step 2.2 when the runner
  (`utils/toolkit_llm_final_reconciliation.py`) is added with mock-provider
  test coverage.

## 7. Verification Commands Run

```bash
# ASCII compliance
python3 scripts/check_ascii_compliance.py prompts/toolkit/final_reconciliation_builder_prompt.txt
# Result: 0 violations

# Manual non-ASCII byte scan
python3 -c "with open('prompts/toolkit/final_reconciliation_builder_prompt.txt', 'rb') as f:
    data = f.read()
non_ascii = [(i, b) for i, b in enumerate(data) if b > 127]
print(f'Non-ASCII byte count: {len(non_ascii)}')"
# Result: Non-ASCII byte count: 0

# OpenSpec strict validation
openspec validate toolkit-accurate-ingest-llm-builder-final-editor --strict
# Result: Change 'toolkit-accurate-ingest-llm-builder-final-editor' is valid

# OpenSpec all-specs regression
openspec validate --specs
# Result: Totals: 364 passed, 0 failed (364 items)
```

## 8. Scope Confirmation

This step delivers Step 2.1 only:
- Added `prompts/toolkit/final_reconciliation_builder_prompt.txt` with
  the required contract elements.
- Updated `openspec/changes/toolkit-accurate-ingest-llm-builder-final-editor/tasks.md`
  to mark Step 2.1 complete and document verification commands and
  completion evidence.
- Added this evidence file `evidence/step-2-1-final-editor-prompt.md`.

No other production code, prompt files, route files, or module artifacts
were modified. The runner, patch validation, packet builder integration,
finisher integration, and tests are all in later steps (2.2, 3.x, 4.x, 5.x,
6.x, 7.x) and are explicitly out of scope here.
