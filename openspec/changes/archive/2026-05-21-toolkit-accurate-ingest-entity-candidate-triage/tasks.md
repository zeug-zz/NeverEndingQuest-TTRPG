# Tasks

## 1. Triage Report Foundation

- [x] 1.1 Add candidate triage schema/constants/report helper without changing blueprint output.
- [x] 1.2 Add deterministic prefilters for obvious narrative phrases and underbound NPC warnings.
- [x] 1.3 Persist or surface a triage report artifact in the accurate-ingest workspace.

## 2. Blueprint Integration

- [x] 2.1 Wire triage decisions into builder blueprint NPC roster generation.
- [x] 2.2 Ensure rejected/reclassified narrative phrases cannot enter NPC rosters, media queues, or expected source NPC lists.
- [x] 2.3 Preserve legacy behavior with warnings when no triage artifact exists.

## 3. Numillian Regressions

- [x] 3.1 Add regression coverage that `but_this_is_not_true` is rejected or reclassified as non-actor text.
- [x] 3.2 Add regression coverage that Dog-Growl, Book-shut, and Deflation remain kept NPCs bound to The Rookery.
- [x] 3.3 Add or update source-contract tests proving kept NPCs require source role or binding evidence.

## 4. Verification

- [x] 4.1 Run compile checks for modified Python files.
- [x] 4.2 Run targeted accurate-ingest blueprint/source graph tests.
- [x] 4.3 Run Numillian end-to-end or benchmark-adjacent tests relevant to entity candidate triage.
- [x] 4.4 Validate the OpenSpec change.

## Suggested Verification Commands

```bash
.venv/bin/python -m py_compile utils/toolkit_entity_candidate_triage.py utils/toolkit_builder_blueprint.py utils/toolkit_homebrew_normalizer.py
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract scripts.test_accurate_ingest_numillian_end_to_end
openspec validate toolkit-accurate-ingest-entity-candidate-triage
```
