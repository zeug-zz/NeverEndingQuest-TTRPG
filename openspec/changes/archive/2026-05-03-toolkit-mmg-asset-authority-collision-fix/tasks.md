# Tasks: toolkit-mmg-asset-authority-collision-fix

## Section 0: Correct Prior Delegated-Duplicate Direction

- [x] 0.1 Transitional delegated-duplicate NPC rows are no longer authoritative for monster-authoritative actors; duplicate same-slug NPC rows are suppressed in MMG output.
- [x] 0.2 Tests no longer require `authority_delegated` NPC audit rows for `bandit_captain_gorvek`, `corrupted_ranger_thane`, or `malarok_the_corruptor`.

## Section 1: Unified Asset Canonical Monster Authority

- [x] 1.1 In `web/web_interface.py`, module monster-authoritative slugs are derived from module monster JSON files and structured `monsters[]` entries before building unified NPC assets.
- [x] 1.2 In `/api/toolkit/modules/<module>/unified-assets`, NPC assets whose canonical slug is module monster-authoritative are suppressed.
- [x] 1.3 True NPC assets that are not module monster-authoritative, including `wounded_ranger_gareth` and `merchant_kael`, remain preserved.
- [x] 1.4 Type-qualified frontend keys (`<type>:<id>`) remain a defensive UI invariant, but suppression no longer depends on them.
- [x] 1.5 Selected generation payloads include same-slug monster-authoritative actors at most once and as `type: "monster"`.

## Section 2: Description And Compendium Hygiene

- [x] 2.1 NPC description status/generation code checks module monster authority before treating a slug as an NPC asset.
- [x] 2.2 `npc_compendium.json` entries for module monster-authoritative slugs no longer cause MMG to emit duplicate NPC asset rows.
- [x] 2.3 Thornwood NPC compendium entries for `bandit_captain_gorvek`, `corrupted_ranger_thane`, and `malarok_the_corruptor` are ignored in MMG/description contexts when monster-authoritative.
- [x] 2.4 `wounded_ranger_gareth` remains a true NPC description source using compendium/live area/BU area/AI fallback priority.
- [x] 2.5 Broken-import remediation is preserved: UI-driven NPC description generation does not import `NPCBuilder` from `core.generators.npc_builder`.

## Section 3: Scene Follower And Runtime UX Contract

- [x] 3.1 `data/runtime/scene_followers.json` records with `entity_type: "monster"` remain valid for captured/parleying/guiding actors.
- [x] 3.2 Monster-authoritative scene followers can remain visible in the non-combat strip when current-location and visibility rules allow it.
- [x] 3.3 Prompt/source contracts still allow intelligent monsters to parley, flee, surrender, guide, or be captured without requiring NPC asset reclassification.
- [x] 3.4 Combat commitment still routes monster-authoritative actors through `createEncounter.monsters[]` when formal combat begins.

## Section 4: Thornwood Data And Report Remediation

- [x] 4.1 Thornwood unified assets/report now show `bandit_captain_gorvek`, `corrupted_ranger_thane`, and `malarok_the_corruptor` as monster assets only.
- [x] 4.2 Thornwood MMG report has no duplicate NPC audit rows for those three slugs and no missing NPC media obligations for them.
- [x] 4.3 Existing monster media and monster JSON/statblock files remain authoritative.
- [x] 4.4 `vitreol_corrupted_thrall` publishability media gap remains documented as pre-existing and unrelated to this change.

## Section 5: Verification

- [x] 5.1 `.venv/bin/python -m py_compile web/web_interface.py utils/module_media_generator_report.py scripts/test_toolkit_mmg_authority_contract.py`.
- [x] 5.2 `.venv/bin/python scripts/test_toolkit_mmg_authority_contract.py -v`.
- [x] 5.3 `.venv/bin/python scripts/test_toolkit_module_build_publication_parity.py`.
- [x] 5.4 `.venv/bin/python core/validation/validate_module_files.py --module The_Thornwood_Watch`.
- [x] 5.5 `.venv/bin/python scripts/audit_module_publishability.py --module The_Thornwood_Watch --json` confirmed any remaining publishability failure is the pre-existing `vitreol_corrupted_thrall` media gap.
- [x] 5.6 `openspec validate toolkit-mmg-asset-authority-collision-fix`.

## Deferred Notes

- The only remaining publishability blocker in Thornwood is the pre-existing `vitreol_corrupted_thrall` base media gap; it is outside the scope of this authority-collision fix.
