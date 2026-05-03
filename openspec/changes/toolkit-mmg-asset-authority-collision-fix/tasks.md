# Tasks: toolkit-mmg-asset-authority-collision-fix

## Section 0: Correct Prior Delegated-Duplicate Direction

- [ ] 0.1 Treat the existing `media_authority` delegated duplicate NPC approach as transitional only; do not archive this change until duplicate NPC asset rows for monster-authoritative actors are removed or ignored.
- [ ] 0.2 Update or replace any tests that currently require `authority_delegated` NPC audit rows for `bandit_captain_gorvek`, `corrupted_ranger_thane`, or `malarok_the_corruptor`.

## Section 1: Unified Asset Canonical Monster Authority

- [ ] 1.1 In `web/web_interface.py`, derive module monster-authoritative slugs from module monster JSON files and structured `monsters[]` entries before building unified NPC assets.
- [ ] 1.2 In `/api/toolkit/modules/<module>/unified-assets`, suppress NPC assets whose canonical slug is module monster-authoritative.
- [ ] 1.3 Preserve true NPC assets that are not module monster-authoritative, including `wounded_ranger_gareth` and `merchant_kael`.
- [ ] 1.4 Keep type-qualified frontend keys (`<type>:<id>`) as a defensive UI invariant, but do not rely on them to keep same-slug monster/NPC duplicate rows.
- [ ] 1.5 Ensure selected generation payloads include same-slug monster-authoritative actors at most once and as `type: "monster"`.

## Section 2: Description And Compendium Hygiene

- [ ] 2.1 In NPC description status/generation code, check module monster authority before treating a slug as an NPC asset.
- [ ] 2.2 Prevent `npc_compendium.json` entries for module monster-authoritative slugs from causing MMG to emit NPC asset rows.
- [ ] 2.3 Remove or ignore Thornwood NPC compendium entries for `bandit_captain_gorvek`, `corrupted_ranger_thane`, and `malarok_the_corruptor` in MMG/description contexts.
- [ ] 2.4 Keep `wounded_ranger_gareth` as a true NPC description source using compendium/live area/BU area/AI fallback priority.
- [ ] 2.5 Preserve the broken-import remediation: UI-driven NPC description generation must not import `NPCBuilder` from `core.generators.npc_builder`.

## Section 3: Scene Follower And Runtime UX Contract

- [ ] 3.1 Add or update tests proving `data/runtime/scene_followers.json` records with `entity_type: "monster"` remain valid for captured/parleying/guiding actors.
- [ ] 3.2 Add or update tests proving monster-authoritative scene followers can remain visible in the non-combat strip when current-location and visibility rules allow it.
- [ ] 3.3 Verify prompt/source contracts still allow intelligent monsters to parley, flee, surrender, guide, or be captured without requiring NPC asset reclassification.
- [ ] 3.4 Verify combat commitment still routes monster-authoritative actors through `createEncounter.monsters[]` when formal combat begins.

## Section 4: Thornwood Data And Report Remediation

- [ ] 4.1 Regenerate Thornwood unified assets/report so `bandit_captain_gorvek`, `corrupted_ranger_thane`, and `malarok_the_corruptor` appear as monster assets only.
- [ ] 4.2 Ensure Thornwood MMG report has no duplicate NPC audit rows for those three slugs and no missing NPC media obligations for them.
- [ ] 4.3 Keep existing monster media and monster JSON/statblock files authoritative.
- [ ] 4.4 Keep `vitreol_corrupted_thrall` publishability media gap documented as pre-existing and unrelated to this change.

## Section 5: Verification

- [ ] 5.1 Run `.venv/bin/python -m py_compile web/web_interface.py utils/module_media_generator_report.py scripts/test_toolkit_mmg_authority_contract.py`.
- [ ] 5.2 Run `.venv/bin/python scripts/test_toolkit_mmg_authority_contract.py -v`.
- [ ] 5.3 Run `.venv/bin/python scripts/test_toolkit_module_build_publication_parity.py`.
- [ ] 5.4 Run `.venv/bin/python core/validation/validate_module_files.py --module The_Thornwood_Watch`.
- [ ] 5.5 Run `.venv/bin/python scripts/audit_module_publishability.py --module The_Thornwood_Watch --json` and confirm any remaining publishability failure is the pre-existing `vitreol_corrupted_thrall` media gap.
- [ ] 5.6 Run `openspec validate toolkit-mmg-asset-authority-collision-fix`.
