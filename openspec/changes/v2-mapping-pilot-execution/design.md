# Design

## Context

See `proposal.md` - Why. The scope and frozen inputs are `plans/v2-mapping-pilot.md` s5.5-s5.7 and s6-s10, `plans/v2-mapping-pilot-prereg/README.md`, and `plans/v2-mapping-pilot-prereg/rubric.md`; those inputs are read-only. The single capability contract is `specs/mapping-pilot-execution/spec.md`.

SP1 already provides opt-in row seeding, an in-process sandbox launcher on port 8360, adapter turn-packet records, a shadow-only zone ledger, scoring including `pre_request_guard`/`score_row`/`score_matrix`, and immutable row evidence bundles. SP2 already provides source-bound D1 output and M1 review packets. Reuse `scripts/capture_drive.py` for its socket connection and turn-completion behavior, and `scripts/capture_evidence.py` for existing runtime evidence extraction; do not create a second socket protocol or a general experiment framework.

The SP2 evidence record at `openspec/changes/v2-mapping-pilot-offline/evidence.md` identifies D1 run `d1-20261105-01` and M1 run `m1-20261105-02`. The D1 audit owner fields and M1 ratings are blank and remain owner inputs. The narrative overview s10.1 records that Stage 1 packet ratings are waived, not scored, and that live transcript and M1 ratings are batched into one SP4 owner sitting.

## Goals / Non-Goals

**Goals:**

- Complete only the missing SP3 matrix orchestration and SP4 evidence/review composition while preserving the existing component boundaries.
- Keep automated measures, human ratings, owner D1 audit, primary verdicts, and owner decisions distinguishable in every artifact.
- Produce project-relative, resumable evidence and a Proposed spatial ADR without changing production behavior.

**Non-Goals:**

- No changes to frozen preregistration content or completed SP1/SP2 behavior.
- No provider calls or live server starts in builder tests; no live row execution by builders.
- No production mapping model, core hook, model routing, module data, web/client work, or ADR acceptance.

## Decisions

### Contract Layer (MUST)

1. **Add the smallest orchestration surface.** Add a matrix runner and focused review/report composition under `scripts/mapping_pilot/`, with adjacent `scripts/test_mapping_pilot_*.py` tests. The runner reads and verifies the frozen preregistration manifest and counterbalance rather than copying or rewriting them. This is smaller than changing the existing seeder, redesigning Capture Arena, or creating a generic experiment framework.

2. **Drive existing sandbox and socket seams.** For each row, the primary runner uses the existing opt-in seeder to create a fresh `tmp/combat_capture/` copy, invokes `launcher.py` for the row's arm/fixture/party, and supplies the exact preregistered script steps to the existing socket-driver session and turn-completion path. The current driver CLI is organized around named capture-gate profiles rather than these pilot JSON scripts; therefore the only new driver glue is the narrow mapping-pilot script adapter. It must not fork the socket protocol or change the frozen script bytes. `launcher.py` owns the 8360 sandbox server and headless environment; use the repository venv and never `run_web.py` on the installed campaign.

3. **Guard requests and use the orchestrator's live-time interpretation.** Reuse `scoring.pre_request_guard` immediately before each outbound attempt, including retries and classifier calls. The sandbox request wrapper maintains the row and matrix attempt counters; it increments for an issued attempt even if that attempt errors. Missing counters refuse the request. The preregistration leaves the term "Live wall time" undefined beyond its frozen values. The orchestrator interpretation is that each row's 25-minute interval starts at sandbox server launch and ends at teardown completion; the six-hour total is the sum of those row live intervals, excluding pauses between rows. Offline seeding before launch and evidence finalization/scoring after teardown are excluded from the live intervals, with their timestamps recorded separately. Booked-window elapsed time is also recorded separately and is not part of the six-hour sum. Record this interpretation in the matrix ledger before any live row; it interprets the undefined term and does not change the frozen 25-minute or six-hour values. Use monotonic measurements for elapsed-time guards and durable timestamps for the audit record. At either live-time cap, stop further live work, tear down the owned server, preserve raw evidence, and record the row as `FAIL` or `BLOCKED` under the stop rules; a time-cap stop is not automatically an infrastructure failure. No downstream model is pinned and no retry/fallback policy is added.

4. **Separate row evidence from matrix coverage.** Each attempted row gets a unique bundle through the existing evidence writer under `tmp/router-rollout/mapping-pilot/sp3/<row-run-id>/`, with exact packets, transcript, state snapshots, zone trace, checks, cap counts, lifecycle timestamps, logs, route receipts, and scorer output. Preserve raw live evidence before teardown; end the live interval at teardown completion, then finalize the bundle and score the row outside that interval. Keep a matrix ledger alongside the bundles with all 30 scheduled IDs, progress, booking/release, booked-window elapsed time, the recorded live-time interpretation, per-row live intervals and their sum, classifications, and terminal states. The evidence writer's terminal row verdicts remain `PASS`, `FAIL`, or `BLOCKED`; unattempted or unused slots are `missing` in the matrix ledger and are not represented by fabricated bundles. Reserve IDs remain distinct from their original failed rows.

5. **Make reserve eligibility a pre-content record.** Before anyone opens transcript or response content, record the preregistered classification and its allowed process/transport/provider-status/artifact evidence. Only eligible infrastructure failures can activate R01-R04, in order, and each replacement inherits the failed cell and repeat without erasing its source record. `CONTENT/RESULT` never earns a reserve; `UNRESOLVED` waits for owner adjudication. A third consecutive infrastructure failure freezes the resume cursor until owner review.

6. **Separate collection from review and unblinding.** Build live review packets from preserved transcripts using opaque response IDs. Keep the condition key in a separate owner-controlled artifact and release it only after a rating-lock record exists. Hide row order, arm, route/model metadata, and fixture answer keys from the packet. Include the preregistered partial-blinding disclosure because an ASCII sketch can reveal D. Preserve rubric fields as blank until the owner supplies ratings; factual scoring remains separate.

7. **Compose SP4 from existing evidence and explicit owner inputs.** `decision_report.py` consumes row scores from `score_matrix`, the SP3 ledger, the D1 audit artifact, the M1 rating sheet, and locked transcript ratings. Report Q1-Q6: Q1 sense-of-place evidence informs the exploration-packet decision; Q2 compares B/D format; Q3 applies the zone/intent rules; Q4 covers D1 backfill; Q5 covers shared-map ratings; Q6 reports tokens, latency, retries, attempts, and route confounds and feeds the existing packet/format criteria without creating a new threshold. Use only the preregistered retain/revise/reject/inconclusive recommendation vocabulary for the five decisions. Missing human fields are `pending/not provided`; no values are imputed.

8. **Make the Module Builder handoff evidence-bound.** Add a concise module-data requirements and gap table to the SP4 report, with each item linked to D1 source/proposal/validation evidence and a separate owner-audit status. Do not convert model proposals into authored facts or claim the 85%/zero-invented-exits threshold is met without the owner audit. The current SP2 evidence has blank audit fields, so the current report must show that input as pending.

9. **Draft, do not adopt, the spatial ADR.** The ADR index currently ends at 0033; use `adrs/0034-spatial-authority-and-projections.md` only if 0034 remains the next free number at implementation. Follow `adrs/0000-template.md` and update `adrs/index.md`. The index legend defines `Proposed` as awaiting owner acceptance, although the template's inline status list omits it; use `Status: Proposed` as required and do not edit the template merely to imply acceptance. The ADR covers Python authority, projection-per-audience, schematic versus metric facts, observed versus enforced legality, and the frozen close-enough rule. The owner decision gate records choices and evidence separately; an explicit owner acceptance is still required before S1.

10. **Keep provider-free tests and the boundary guard honest.** Inject process, socket, request, clock, and owner-input boundaries in tests. Update `scripts/test_mapping_pilot_boundaries.py` to allow only this new OpenSpec directory and the exact proposed ADR/index paths in addition to its existing mapping-pilot paths. Verify arm A remains unchanged, both 1-PC and 4-PC rows are covered, and no provider or server starts during tests.

### Guidance Layer (SHOULD)

- SHOULD keep the matrix runner resumable by writing each state transition atomically and refusing to reuse a row run ID or evidence bundle.
- SHOULD preserve a compact booking/release record with Overseer identity, scheduled interval, actual start/finish, and non-overlap confirmation, without secrets.
- SHOULD keep the owner report readable without requiring access to raw runtime logs; link each conclusion to the relevant bundle or D1/M1 artifact.

## Risks / Trade-offs

- **Driver or sandbox startup fails:** classify from pre-content process/transport evidence, preserve the attempted row, and apply only the frozen reserve/pause rules; do not substitute a new driver or server path.
- **Cap state or request receipts are incomplete:** fail closed before another request, retain unknowns as unknown, and mark the row `BLOCKED` rather than estimating usage.
- **Blinding is partial:** disclose the ASCII format limitation and keep factual answer-key review separate from owner ratings.
- **Human evidence is absent:** produce a report with `pending/not provided`; do not turn the missing rating or audit into a pass, zero, or owner verdict.

No production migration or rollback is applicable. The run-specific sandbox and evidence remain under `tmp/`; the durable ADR remains Proposed until explicit owner acceptance.

## Open Questions

- The requested SP4 handoff requires a Module Builder module-data requirements/gap list, but the current `plans/v2-narrative-overview.md` s10 ledger does not specify a separate handoff schema or destination. This change will include the evidence-linked table in the SP4 report; the owner should confirm before any separate Builder integration whether a machine-readable consumer format is needed.
- The SP3-specific booking ID and interval are not present in the current ledger; the primary must obtain and record them before any live row. The N0 booking is not an SP3 booking.
- The owner has not yet supplied the D1 audit, live-transcript ratings, M1 ratings, or SP4 choices for format, combat granularity/enforcement, and data pipeline. These remain explicit SP4 inputs; the report records them as pending rather than selecting defaults.
