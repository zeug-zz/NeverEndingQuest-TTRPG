# Context

Toolkit NPC routes currently build NPC IDs with naive string replacement from full display labels. Description generation and manual save endpoints trust those incoming IDs and persist them into the durable NPC compendium. A descriptive authored label therefore becomes a durable identity.

# Goals

- Centralize NPC identity normalization for toolkit writes.
- Split clean identity from descriptive appositive text without losing author intent.
- Deduplicate repeated variants of the same named NPC at the compendium key level.
- Keep compatibility for callers that still pass legacy descriptive IDs.

# Non-Goals

- No module source rewrite.
- No global compendium migration.
- No monster normalization changes.

# Decisions

1. Add `utils/npc_identity.py` with a small `NPCIdentity` dataclass and helpers.
2. Treat text before the first comma as canonical when it looks like a usable identity.
3. Treat comma suffix text as `role_hint` and preserve the full label as `source_label`.
4. Generate slugs from canonical identity only.
5. Merge source metadata additively at compendium write boundaries.

# Hard Constraints

- Python output and source additions must be ASCII-only.
- Host-file edits must be marked with `# TABLETOP MODE:`.
- Compendium writes must use atomic existing repository helpers when practical.
- The helper must not modify monster-oriented `_normalize_name_for_bestiary` behavior.

# Guidance

- Prefer conservative parsing over clever NLP.
- If the pre-comma segment is empty or clearly not useful, keep the original label.
- Store source IDs/labels as additive metadata arrays so duplicate variants remain auditable.
- Canonical IDs should be stable and filename-safe.

# Migration and Rollback

- Rollback removes utility imports and restores raw `npc_id` usage.
- Existing compendium entries are not deleted by this change, so rollback does not require data restoration.
- A future remediation script can merge bad legacy keys into canonical keys once this write-path fix is verified.

# Verification Plan

- Add unit tests for `Arannis`, `Elaris`, `Ilyra`, `Kobe`, and `Letharel` labels.
- Add source-contract tests ensuring toolkit routes call the canonical helper instead of naive full-label slug builders.
- Compile modified Python files.
- Run targeted tests and `openspec validate toolkit-npc-identity-canonicalization`.
