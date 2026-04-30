# Context

The prior change `toolkit-npc-identity-canonicalization` added `utils.npc_identity` and patched toolkit write boundaries so new NPC assets canonicalize labels before compendium/media writes. Existing compendium data still contains historical bad keys that were generated before that boundary fix.

This change defines a narrow data remediation workflow for the persisted NPC compendium.

# Goals

- Provide an operator-safe migration for existing descriptive NPC keys.
- Preserve all meaningful legacy data during canonical-key merge.
- Make dry-run output detailed enough for human review before `--apply`.
- Keep remediation deterministic and testable.

# Non-Goals

- No automatic runtime migration.
- No broad fuzzy matching beyond the canonicalization helper.
- No module source rewrite.
- No monster compendium rewrite.

# Decisions

## Reuse Shared Canonicalization

The remediation script MUST use `utils.npc_identity.canonicalize_npc_identity()` for deciding the canonical key. This keeps remediation aligned with the toolkit write-boundary fix.

## Default To Dry Run

The CLI MUST default to dry-run behavior. Mutation must require an explicit `--apply` flag.

## Merge Instead Of Blind Delete

When a legacy key canonicalizes to a different key, the script MUST merge it into the canonical entry. The legacy key may be removed only after metadata has been preserved on the canonical entry.

## Metadata Preservation

The canonical entry MUST preserve legacy identity context using additive fields such as:

- `source_label`
- `source_labels`
- `source_id`
- `source_ids`
- `role_hint`
- `role_hints`
- `legacy_ids`

If these names conflict with existing helper behavior, builder may extend `utils.npc_identity` minimally while preserving existing contracts.

## Description Merge Precedence

When duplicate entries collapse to one canonical key:

- Preserve an existing canonical-key description when present.
- If no canonical description exists, choose the longest non-empty description among merged entries.
- Store alternate non-empty descriptions in `alternate_descriptions` with source key metadata when they differ.

## Audit Artifact

The script MUST emit a deterministic report describing:

- keys scanned
- keys unchanged
- keys remediated
- legacy key -> canonical key mappings
- merged description decisions
- skipped entries and reasons
- output backup/report paths when applied

# Hard Constraints

- Use `.venv/bin/python` for verification commands.
- Use atomic JSON write helpers for applied changes.
- Do not mutate files on dry run.
- Do not touch `monster_compendium.json`.
- Keep output ASCII-only.

# Guidance

Suggested script path:

- `scripts/remediate_npc_compendium_keys.py`

Suggested CLI:

```bash
.venv/bin/python scripts/remediate_npc_compendium_keys.py --dry-run
.venv/bin/python scripts/remediate_npc_compendium_keys.py --apply
.venv/bin/python scripts/remediate_npc_compendium_keys.py --json --dry-run
```

The script should support a test-only `--path` argument so tests can run against a temporary compendium fixture.

# Migration and Rollback

- Dry run produces no writes.
- Apply writes a report and backup before replacing the compendium.
- Rollback is restoring the backup file.

# Verification Plan

- Unit tests for canonical-key detection and merge precedence.
- Fixture-based test using Numillian examples.
- Dry-run test proving no file mutation.
- Apply test against a temp file proving canonical keys and preserved metadata.
- OpenSpec validation.
