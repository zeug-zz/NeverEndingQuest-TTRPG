# G3 Stage-Order Conflict - Owner-Delegated Resolution

Status: **Owner-delegated planning resolution recorded 2026-10-16. This report preserves the original finding; it does not claim source behavior changed or G3 passed.**

## Conflict

The approved stage contract requires `apply/commit` -> `phase transitions` -> `narration/output` (`design.md:64-76`; `specs/combat-turn-stage-contract/spec.md:9-16`). The design also requires extracted stages to preserve existing order and control-flow semantics (`design.md:76`), the parity requirement preserves mutation and persistence behavior (`specs/combat-behavior-hygiene-parity/spec.md:21-32`), and Task 3.5 explicitly says to preserve the current mutation and persistence sequence (`tasks.md:24`). These constraints cannot all be satisfied by imposing the new strict linear ordering on the current validated-response path.

## Current owner sequence (read-only source inspection)

In `core/combat/combat_manager.py`:

1. AI round metadata and round/phase marker work occurs at lines 3938-3988; encounter state is saved and combat history may be compressed/saved at lines 3990-4015.
2. Narration is printed and stdout flushed at lines 4034-4037.
3. Action handling starts at line 4039. Character updates are queued, while `updateEncounter` is applied immediately at lines 4063-4089.
4. Turn-queue/active-PC bookkeeping runs at lines 4127-4159; opening-batch phase bookkeeping and encounter persistence run at lines 4161-4175.
5. Consolidated character updates are applied at lines 4177-4178.

Thus, the existing publication/mutation sequence places narration before queued character updates and immediate encounter updates, and some phase bookkeeping occurs after narration and action processing. A strict stage-order rewrite would change those observable ordering semantics; retaining the existing order would not implement the stage contract's prescribed sequence.

## Owner-delegated resolution (2026-10-16)

The owner authorized preserving the validated legacy execution, mutation, persistence, and publication order for G3. The nine stages are responsibility boundaries, not a required physical pipeline. Stage owners may include pre/post substeps at the existing call points. Apply/commit and phase-transition extraction stays at those points; narration/output is owned at the legacy publication point, with shared template selection, and is not forced to run last.

The proposed character-first/encounter-last commit followed by post-commit phase work and success publication is deferred to Build 6 / G7, `combat-turn-commit-and-receipts`. Its owning artifacts must define the sequence before implementation and include interruption/replay observations at the new commit boundaries. G3 and this decomposition do not implement or verify that ordering.

The active proposal, design, stage contract, tasks, and master plans were reconciled to this decision. G3 capture prerequisites and live acceptance remain incomplete; this resolution is not a waiver and does not alter source code.
