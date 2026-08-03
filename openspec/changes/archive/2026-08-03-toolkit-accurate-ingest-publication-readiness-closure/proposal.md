# Proposal: Toolkit Accurate-Ingest Publication Readiness Closure

## Why

`audit_module_publishability.py --module Well_of_Ruin --json` exits 1 due to four
blocker classes that prevent the module from passing the publishability gate.
Schema validation passes (62/62), meaning the module structure is sound but
required ancillary metadata and media artifacts are absent.

These blockers are a module-builder/readiness defect: the accurate-ingest or
ModuleBuilder pipeline emitted a structurally valid module but failed to produce
publishability-required artifacts that the audit gates demand.

## Blocker Classes

1. **Gameplay audit strict: 32 missing monster base media files.**  
   `modules/Well_of_Ruin/media/monsters/` has no `.jpg` files.  
   `check_monster_media()` returns `base=False` for all structural monster refs.

2. **No ingest sidecar.**  
   `find_latest_sidecar_for_slug("Well_of_Ruin")` returns `None`.  
   `homebrew_sidecar_audit.py --require-success` blocks.

3. **Continuity audit strict: missing continuity block.**  
   `module_context.json` has no `continuity` key.  
   Required: `continuity_version`, `entry_state_variants`, `cross_module_refs`,
   `standalone_fallback`.

4. **Semantic audit: missing semantic_authority payload.**  
   `module_context.json` has no `semantic_authority` key.

## What Changes

- Do NOT weaken existing audit gates.
- Do NOT edit audit scripts to pass by ignoring missing data.
- Keep tests provider-free and tempdir-backed.
- If Well_of_Ruin needs remediation, use deterministic small artifacts.

## Contract Requirements

(Encoded in parallel spec files.)

## Non-Goals

- No changes to existing audit scripts.
- No live provider calls in tests.
- No weakening of publishability/readiness/semantic/gameplay audits.
