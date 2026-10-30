# Goal and G4 Checkpoint Recovery (2026-10-23)

## Scope and status

This is a documentation-only reconciliation of the existing eight-phase rollout
goal and its task 6.4 checkpoint. The goal was recovered in place; this did not
start a successor, restart execution, run live work, or declare G4 complete.
Task 6.4 and task 6.5 remain unchecked. Phase 3/G4 is in progress; phases 4-8
remain pending.

The existing goal is `1ee9341a-6823-4688-90fe-a22485ccf73f`, originating in
source session `ses_ecdcd4b80ffeTiY5Zeu1KVbcyK`. Its revision advanced from 13 to
14 through a plan operation that retained the full objective, all eight phases,
all ten completion criteria, completed evidence, and all decisions. No
successor goal was needed. The revision-13 top summary is historical; this
recovery amendment supersedes its stale progress/blocker description, not its
criteria. Cancelled predecessor `9d3345c5-2ae8-415e-b550-04c20f802d14` remains
closed. Phase 1/G2 and phase 2/G3 remain complete; phase 3/G4 remains in
progress.

The legacy goal JSON was not read or edited. The authoritative goal-tools record
and source-session checkpoints were available. The owner-confirmed key-rotation
checkpoints `1792358464` and `1792358574` remain valid; no new confirmation was
needed, and no secret or credential value was accessed.

## Evidence reconciliation

### Pre-live software evidence

The read-only pre-live records report 875 tests in 53 separate processes, all
status 0: 758 baseline tests plus 117 affected tests. The records are:

- `tmp/router-rollout/g4/prelive-baseline-final-first20.json`
- `tmp/router-rollout/g4/prelive-baseline-final-last21.json`
- `tmp/router-rollout/g4/prelive-affected-extra.json`

This evidence is pre-live and does not satisfy task 6.5. The historical
705-test baseline remains unchanged and is not retroactively rewritten.

### Current-source G4 bundle records

| Matrix case | Bundle | Primary evidence | Current interpretation |
|---|---|---|---|
| combat-smoke P1 | `tmp/router-rollout/g4/g4-final-combat-p1-1792364191592/` | `primary-review.json` PASS; 4 inputs, 6 controls, 2 health reads; 6 core receipts + 1 distinct legacy compression observation; canonical round 1 to 2 | Case PASS only |
| combat-smoke P4 | `tmp/router-rollout/g4/g4-final-combat-p4-1792364420538/` | `primary-review.json` PASS; 19 inputs, 32 controls, 2 health reads; 20 core receipts + 6 distinct legacy compression observations; canonical round 1 to 2 | Case PASS only; script r1/r2/r3 labels are not three canonical rounds |
| narrator-dialogue-travel P1 | `tmp/router-rollout/g4/g4-final-narrator-p1-1792364780759/` | Manifest has 17 recorded artifact hashes matching; current-source digest matches; 5 inputs, 7 controls, 2 health reads; 16 core receipts, no legacy observations; route/actor and actual Mira backend-response checks are present | Candidate only: no `primary-review.json`; `checks.json.primary_verdict` is PENDING. Do not promote to PASS |
| narrator-dialogue-travel P4 | No matching current-source bundle recorded | None | Missing; still required |

Both combat manifests record that all artifact hashes match and recorded dirty-
source files match the worktree. Both carry source digest
`297d98ccdcbb17fb0b5ed96d74c1d6a848f21675d6be20a9cfc741d267c5165b`. The P1
narrator candidate has the same recorded source digest and all 17 artifact
hashes match. Its pending verdict is not a primary review.

Earlier narrator primary PASS records
`g4-narrator-p1-1792360319245` and `g4-narrator-p4-1792360530876` remain
historical. Their source digest
`1e811baf9a11f6e41abf658b775bb64f96e445cd2792fc6eb42705e5a05a28b0` differs
from the current source in the recorded `capture_drive`/evidence files, so they
cannot satisfy the strict current-source matrix. The combat `combat_compression`
observations are kept separate from core receipts; their unknown provider/model
provenance remains unknown.

## Next required primary-owned work

Continue task 6.4 without changing its requirement or checkbox:

1. Inspect the preserved current-source narrator P1 candidate before deciding
   whether to rerun it; do not treat its pending primary verdict as PASS.
2. Obtain and review the missing current-source narrator P4 case.
3. Complete the primary four-key matrix review, preserving per-key outcomes and
   all raw evidence, with no gate or coverage waiver.
4. Only after task 6.4 is complete, perform task 6.5 and subsequent goal phases.

The `temperature=0.8` location-summary follow-up from phase 5 remains open, as
does the provenance uncertainty for legacy compression observations. This
recovery made no live or server calls, no prepare/restore operation, no
credential inspection, and no test execution. It does not declare G4 complete.

## Later primary review and P4 blocker addendum (2026-10-23)

The preceding candidate status is historical and retained verbatim. The primary
has since inspected the preserved narrator P1 transcript, all before/after and
per-step snapshots, all 16 core receipts, and server diagnostics, then wrote
`tmp/router-rollout/g4/g4-final-narrator-p1-1792364780759/primary-review.json`.
That exclusive review records case-only PASS for current-source
`narrator-dialogue-travel:p1`. The raw artifact bytes were unchanged; all 17
manifest artifact hashes and recorded source hashes were verified.

The review's checks pass for the persisted startup/route sequence
CA01 -> CA02 -> CA03 -> CA03 -> CA02 -> CA01 and Acheron throughout; actual
Warden Mira backend narration distinct from echo; Acheron's unchanged record
hash `5d9792c37d5a6ffdbf875409ea332bfd9ca8e4f0b04bf5bf7ca215de615348ff`; empty
active encounter and no character/resource/reward mutation; 5 inputs, 7
controls, 2 health reads, no timeouts/caps, and five turns each under 46 seconds;
and 16 uniquely paired core receipts (`openai`, `gpt-6-luna`, no fallback,
complete usage, explicitly unpriced cost). The review notes one semantic
correction on step 5. Excluded phase-5 HTTP 400 diagnostics remain for
transition-validator `temperature=0.3`, adventure summary `temperature=0.8`, and
quest formatter `temperature=0.3`; these are follow-ups, not successful
operation claims.

Current-source primary-reviewed PASS cases are combat-smoke P1/P4 and
narrator-dialogue-travel P1. Current-source narrator P4 is still missing; G4 and
task 6.5 remain incomplete/unchecked.

### Stop condition before narrator P4

Before P4 preparation, a listener was observed on port 8360 at PID 77348.
`lsof` tied both PIDs 77345 and 77348 to cwd `tmp/combat_capture` and stdout/
stderr `tmp/router-rollout/g4/server-g4-final-narrator-p1-1792364780759.log`.
The primary attempted TERM only against those positively owned processes; both
were denied `operation not permitted`. `ps` metadata inspection was denied.
Owner action is required to stop the retained capture processes before P4
preparation can continue. Do not retry termination or widen permissions. Do not
touch port 8357, prepare/restore, start a server, or perform live/network work.

The owner clarified that Nono has a known diagnostic path bug that can strip
leading directories and invent root paths. `nono why` for the exact intended
repository report path and `/bin/python` returned ALLOWED, consistent with that
clarification; no new filesystem grant was requested. This does not alter the
process ownership stop condition. Earlier restrictions remain in force; no
secret/runtime access, live operation, or gate waiver is authorized here.

The port-8360 blocker is resolved, and task 6.4 is complete with four same-source primary PASS reviews and a primary matrix PASS. Task 6.5 final verification remains pending; G4 overall is not yet complete.
