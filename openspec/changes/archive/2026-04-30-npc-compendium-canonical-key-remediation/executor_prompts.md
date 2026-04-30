# Executor Prompts

## Builder Prompt

Implement `npc-compendium-canonical-key-remediation`.

Requirements:

- Add `scripts/remediate_npc_compendium_keys.py`.
- Use `utils.npc_identity` for canonical key decisions.
- Default to dry-run; require `--apply` for writes.
- Support `--path` for tests and `--json` for machine-readable reports.
- Merge descriptive legacy keys into canonical keys while preserving source labels, source IDs, role hints, legacy IDs, and alternate descriptions.
- Use atomic JSON writing on apply.
- Do not touch monster compendium files.
- Do not wire remediation into app startup.
- Add focused tests for Numillian bad keys and dry-run/apply behavior.
- Run compile, targeted tests, and OpenSpec validation.

## Verification Prompt

Verify `npc-compendium-canonical-key-remediation` by checking:

- Dry-run produces a report and does not mutate the fixture.
- Apply mode rewrites only the target NPC compendium fixture.
- Bad keys collapse to canonical keys (`arannis`, `elaris`, `ilyra`, `kobe`, `letharel`).
- Conflicting duplicate descriptions are preserved deterministically.
- Legacy identity metadata is preserved.
- Runtime startup/toolkit paths are not modified to auto-run remediation.
- `openspec validate npc-compendium-canonical-key-remediation` passes.
