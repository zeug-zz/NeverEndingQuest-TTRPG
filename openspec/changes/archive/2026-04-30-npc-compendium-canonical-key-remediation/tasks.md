# Tasks

## 1. OpenSpec Artifacts

- [x] 1.1 Create proposal, design, tasks, executor prompts, and capability spec.
- [x] 1.2 Validate this OpenSpec change before implementation.

## 2. Remediation Script

- [x] 2.1 Add `scripts/remediate_npc_compendium_keys.py` with dry-run default and explicit `--apply`.
- [x] 2.2 Add `--path` support for fixture tests and optional `--json` structured output.
- [x] 2.3 Detect legacy descriptive keys using `utils.npc_identity` canonicalization.
- [x] 2.4 Merge legacy entries into canonical entries while preserving source metadata.
- [x] 2.5 Preserve conflicting alternate descriptions instead of discarding them.
- [x] 2.6 Write applied changes atomically and create a backup/audit artifact.

## 3. Safety and Scope Guards

- [x] 3.1 Ensure dry-run does not mutate the compendium file.
- [x] 3.2 Ensure `monster_compendium.json` is never read or written by the remediation script.
- [x] 3.3 Ensure skipped/ambiguous entries are reported instead of force-merged.
- [x] 3.4 Keep remediation opt-in; do not wire it into startup or toolkit runtime.

## 4. Regression Coverage

- [x] 4.1 Add fixture tests for Numillian bad keys: Arannis, Elaris, Ilyra, Kobe variants, and Letharel.
- [x] 4.2 Add merge-precedence tests for canonical description vs legacy descriptions.
- [x] 4.3 Add dry-run and apply-mode tests against temporary compendium files.
- [x] 4.4 Add source-contract tests proving runtime startup is not modified.

## 5. Verification

- [x] 5.1 Compile modified Python files with `.venv/bin/python -m py_compile`.
- [x] 5.2 Run targeted remediation tests.
- [x] 5.3 Run `openspec validate npc-compendium-canonical-key-remediation`.

## Guidance

- Keep this change focused on existing `npc_compendium.json` remediation.
- Do not broaden into module source cleanup unless a separate reviewed change is opened.
- Preserve legacy context as metadata; deletion is allowed only after successful merge into canonical entry.
