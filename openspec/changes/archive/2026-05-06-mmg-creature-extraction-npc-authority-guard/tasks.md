## 1. Plan Revision

- [x] 1.1 Revise proposal to clarify that full revert is not recommended, but current broad authority promotion must be refined.
- [x] 1.2 Revise design to define explicit monster authority, weak monster candidates, NPC authority, and module-local independence.
- [x] 1.3 Revise spec to require source-aware conflict resolution and report parity.

## 2. Code Implementation

- [x] 2.1 Add or refactor a module-local MMG authority helper that does not read `party_tracker.json` or other campaign runtime state.
- [x] 2.2 Track monster candidate provenance in unified-assets extraction: module monster JSON, structured `location.monsters`, `location.creatures`, and `location.visibleHostiles`.
- [x] 2.3 Build NPC authority from module-local sources: `module_context.json`, `module_context_BU.json` when present, `npcs_seed.json` when present, and area `location.npcs[].name` entries.
- [x] 2.4 Add safe alias expansion for NPC authority: parenthetical bare-prefix aliases and comma/appositive canonical-prefix aliases.
- [x] 2.5 Replace broad `monster_authority_slugs.update(monsters.keys())` behavior so weak `creatures` or `visibleHostiles` candidates cannot promote themselves to monster authority.
- [x] 2.6 Apply source-aware conflict resolution in unified-assets: explicit monster beats NPC hint, NPC beats weak monster candidate, weak-only monster remains.
- [x] 2.7 Update `utils/module_media_generator_report.py` so same-slug canonicalization mirrors the same authority rules instead of globally preferring monster rows.
- [x] 2.8 Preserve existing structured `location.monsters` behavior and existing monster-authoritative Thornwood behavior.

**Verification for 2.1-2.8**: `.venv/bin/python -m py_compile web/web_interface.py utils/module_media_generator_report.py` passes.

## 3. Regression Tests

- [x] 3.1 Add tests for `creatures` parsing: comma split, trailing period trim, parenthetical qualifier stripping.
- [x] 3.2 Add tests for `visibleHostiles` parsing: `name` preferred over `monsterType`, empty/missing names skipped.
- [x] 3.3 Add tests for NPC authority aliases: `Ma (Margaret Thornfield)` matches `Ma (commoner)`, `Red (The Crimson Binder)` matches `Red`.
- [x] 3.4 Add tests that weak creature-derived NPC collisions preserve NPC rows and drop weak monster rows.
- [x] 3.5 Add tests that explicit monster-authoritative collisions preserve monster rows and suppress duplicate NPC rows.
- [x] 3.6 Add tests that weak-only true monsters survive when no NPC authority conflicts.
- [x] 3.7 Add tests that report generation mirrors endpoint conflict resolution.
- [x] 3.8 Add a source-contract or behavior test proving MMG authority does not read `party_tracker.json`.
- [x] 3.9 Replace or retire duplicated extraction-only scripts if they can drift from the endpoint implementation; prefer shared helper or Flask test-client coverage.

**Verification for 3.1-3.9**: `.venv/bin/python scripts/test_mmg_creature_npc_authority.py` or equivalent focused tests pass.

## 4. Module Verification

- [x] 4.1 Smoke test `Night_of_the_Restless_Dead` through Flask test client: `Ma`, `Blarg`, and `Red` appear only as NPCs; weak creature monster rows for those slugs are absent.
- [x] 4.2 Smoke test `Night_of_the_Restless_Dead`: true weak-only monsters from `creatures` or `visibleHostiles` still appear as monsters when not NPC-authoritative.
- [x] 4.3 Smoke test `The_Thornwood_Watch`: `bandit_captain_gorvek`, `corrupted_ranger_thane`, and `malarok_the_corruptor` remain monster assets only.
- [x] 4.4 Smoke test a module without `creatures` or `visibleHostiles`: no regression in asset counts or classifications.

## 5. OpenSpec Validation

- [x] 5.1 Run `openspec validate mmg-creature-extraction-npc-authority-guard` and resolve any artifact issues.
- [x] 5.2 After implementation and approval, archive with spec sync.

## 6. ASCII Compliance

- [x] 6.1 Run `python3 scripts/check_ascii_compliance.py --summary-only` or targeted equivalent before commit.
