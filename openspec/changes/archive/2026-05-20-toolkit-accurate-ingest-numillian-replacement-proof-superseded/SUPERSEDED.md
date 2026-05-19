# Superseded: Accurate-Ingest Numillian Replacement Proof

**Status:** Superseded/Cancelled before implementation.

**Date archived:** 2026-05-20

## Reason

This change was scoped to prove that the deterministic accurate-ingest pipeline could replace the old inaccurate `The_Hidden_City_of_Numillian` module with a deterministic blueprint-seed-generated version. Its work is absorbed into Change 9 (`toolkit-accurate-ingest-numillian-release-proof`) of `plans/accurate-ingest-fix.md`, which requires the source-enhanced ModuleBuilder path rather than the rejected deterministic seed-writer path.

No tasks were ever implemented (0/43 complete).

## Preserved Value

The benchmark expectations documented here remain valid as source-fidelity requirements for the recovery Change 9:

- 13 source locations preserved by original source names or approved alias mapping.
- Required NPC threshold from benchmark fixture.
- Trial-at-the-Door puzzle.
- Skull riddle.
- Flooding room puzzle.
- Kill-the-dog mindscape test.
- Gatepact lore.
- Kobe protection objective.
- Quirky character-driven tone.
- No generic ward-network/conspiracy replacement plot.
- False-positive entity rejection (e.g., `but_this_is_not_true` must not become an NPC).

The v1 archive guard spec (`toolkit-numillian-v1-archive-guard`) should be reviewed for any release-hardening requirements not yet covered by the recovery plan.

## Do Not Sync

The delta specs from this change must not be promoted as canonical main specs. They were written for the superseded deterministic-seed path.
