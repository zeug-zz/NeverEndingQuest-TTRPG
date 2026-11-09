# Pilot decision report

**DRAFT / NOT A DECISION / OWNER REVIEW REQUIRED**

**Date:** 2026-11-09
**Mode:** Provider-free documentation. This report authorizes no implementation,
production default, live evaluation, or module write.

This is an evidence synthesis and a set of recommendations for owner review.
It does not accept ADR-0034 or alter the frozen pilot contract. Source paths and
section names below identify the evidence used; no owner input is imputed or
replaced with an automated proxy.

## Evidence to date

### Main SP3: INCONCLUSIVE

The Overseer adjudication records every main-SP3 arm comparison as
**INCONCLUSIVE**. The primary attempted all 26 planned rows: 18 primary FAIL,
8 primary BLOCKED, and 0 live PASS. The run used 513 attempts and
3,453.3628182079847 live seconds. These are the primary's launch-to-teardown
row intervals, not booked elapsed time. No comparison is pooled across the
seven mid-matrix re-freezes. The missed three-consecutive-infrastructure pause
and all seven re-freezes remain deviations; neither was waived.

Content findings include an unknown back-door destination asserted as an alley
(E02), a closed/unknown kitchen door narrated as open (E07), invented space
beyond an unknown door (E11), and invented cues behind an unentered kitchen
door (E12). Several exploration rows also encountered a `packet_location`
backend error or lacked transition, return, or persistence coverage. Combat
rows recorded movement overshoots from the expected stairs to the balcony and
invented metric distances/heights where those metrics were unknown. C01 did not
start real combat because its Goblin template was missing. These findings are
not clean arm-level rates: critical lifecycle checks and denominators are
missing or unknown.

Auto-routing and source amendments confound comparisons. The SP4 report records
an estimated DeepSeek-share difference from A of 16.8185 percentage points for
B and 13.7918 points for D, above the report's 10-point flag, alongside route
unpinning and unknown/missing route observations. These are not causal format
effects. The row outcomes and caveats are in
`openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md`,
sections "Primary collection outcome", "Slot ledger", "Evidence corrections,
confounds, and limits", and "Later adjudication".

### SP3b: CLOSED BLOCKED

SP3b has 0 accepted lifecycle profiles and 19 unrun rows (SP3B-001 through
SP3B-019). The bounded provider-free attempt stopped before seeder or runtime
path execution; no supplementary runtime attempt is authorized. The proposed
amendment remains **DRAFT, NOT FROZEN**. This is a blocked profiling outcome,
not proof that runtime coverage is impossible. Sources:
`openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md`,
"SP3b attempt and readiness"; and
`tmp/router-rollout/mapping-pilot/sp3b-profiling/20261106T194337Z/primary-review.json`.

### M1: frozen threshold not met

The reviewed, read-only CSV is
`tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/ratings.csv`. Recalculation
over its 16 rated sketch rows gives:

| Group | n | Legibility | Usefulness |
| --- | ---: | ---: | ---: |
| Entire original packet | 16 | 42/16 = 2.625 | 46/16 = 2.875 |
| Authored fixtures, including combat fixtures | 5 | 25/5 = 5.000 | 23/5 = 4.600 |
| D1-generated locations | 11 | 17/11 = 1.54545 | 23/11 = 2.09091 |
| Combat fixture subset | 2 | 10/2 = 5.000 | 10/2 = 5.000 |

Both whole-packet means are below the frozen 3.5 threshold. The stratified
values are descriptive only; the combat subset is not a live-combat PASS, and
the redesigned examples are not substituted for original artifacts. The
arithmetic above was independently recomputed from the reviewed CSV; it agrees
with `sp4-primary-report.md`, "M1 original-artifact ratings". The 16 row values
are listed in that section. The CSV, not the pre-review blank sheet listed in
the earlier manifest, is the rating source for these means.

### D1 data feasibility

Run `d1-20261105-01` made 20 location calls against its 60-call cap. The run
notes record 21 router receipts including one fallback switch; the requested
run count remains 20. Eleven layouts validated and nine were `invalid_layout`.
The 1,048-row owner audit has no owner judgments, so precision and invented-exit
judgment remain **PENDING**. The automated graph check's seven exit flags are
not owner-audited findings. Sources:
`tmp/router-rollout/mapping-pilot/d1/d1-20261105-01/RUN_NOTES.md`,
`d1_audit_sheet.json`, and `d1_owner_audit.csv`; also
`sp4-primary-report.md`, "Later M1 owner review and mise-en-scene planning
handoff".

### Human review, Stage 1, and owner direction

Of 25 ledger-bound SP4 responses, seven are complete-for-rating and remain
unrated; 18 are not rateable. E01 is separately excluded: its recovered bundle
is not ledger-bound and has no usable transcript. The condition key remains
withheld until the seven ratings are locked. Stage 1 was owner-waived, not
scored. Sources: `sp4-primary-report.md`, "SP4 review and owner gate" and
"Later M1 owner review and mise-en-scene planning handoff".

The owner directs mapping toward **Narrator-first mise-en-scene**: a coherent,
actionable scene and route arrangement for narration first, with cumulative,
knowledge-filtered player maps as secondary projections. This is planning
direction, not a result that narration improved and not an implementation
authorization. Sources: `plans/v2-mapping-pilot-owner-feedback.md`,
"IMPORTANT owner development: mise-en-scene is the mapping goal"; and
`sp4-primary-report.md`, "Prospective central goal: narrator-first
mise-en-scene".

### PR116 prototype and PR118 holdout preparation

PR116's offline prototype is **ACCEPTED only as supplied-fixture tooling**. It
provides provider-free validation and audience-scoped projections for supplied
fixtures. It is not an evaluation, does not test or prove LLM Builder authoring,
and does not establish production behavior. Its staged-arrival checks bind
approved text and typed exact claims to supplied facts/provenance; they are not
general natural-language or semantic validation and cannot detect claims omitted
from the typed list. Sources: `scripts/mise_en_scene/README.md`, "Proposed
offline fixture contract", "Matched projections", and "Builder-authored staged
arrivals"; `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/reports/offline-build-verification.md`,
"Final primary checks" and "Status boundaries"; and that change's `proposal.md`
and `design.md`.

PR118 holdout preparation is referenced only as an **unfrozen draft**; two
leakage flags remain pending review. It supplies no frozen holdout, score, or
evaluation result and does not close any pilot question.

## Original pilot questions

Statuses refer to the original questions in `plans/v2-mapping-pilot.md`,
section 4. "Answered" means only that the specified frozen criterion has an
evidence-backed result; it is not a production decision.

| Question | Status | Evidence and boundary |
| --- | --- | --- |
| Q1: Does spatial context improve live sense of place? | **Pending owner input** | Main SP3 comparisons are INCONCLUSIVE; seven complete-for-rating transcripts remain unrated, 18 are not rateable, and E01 is excluded. No arm effect is established. `sp4-primary-report.md`, "SP4 review and owner gate" and "Later adjudication". |
| Q2: Which exploration format, B or D, is better per token? | **Inconclusive** | No pooling across seven re-freezes; auto-route and source-amendment confounds remain, and the format comparison is not evaluable. No B/D choice is inferred. `sp4-primary-report.md`, "Evidence corrections, confounds, and limits" and "SP4 review and owner gate". |
| Q3: Are zones close enough for combat, and how well does intent map to zones? | **Inconclusive** | Some combat rows show overshoot or invented metrics, but observed-round and contradiction denominators and intent outcomes remain unknown/incomplete. Combat granularity and enforcement are pending owner choice. `sp4-primary-report.md`, "Slot ledger" and "SP4 review and owner gate". |
| Q4: Can scene layouts be built from existing module prose? | **Pending owner input** | D1 produced 20 proposals (11 valid, 9 invalid) within 60 calls, but the 1,048-claim owner audit is blank. Automated validation is not the frozen owner precision/zero-invented-exit decision. `RUN_NOTES.md`; `plans/v2-mapping-pilot.md`, section 7.2. |
| Q5: Do schematic sketches help people share a picture? | **Answered for the frozen M1 threshold** | The reviewed 16-sketch means are 2.625 legibility and 2.875 usefulness, below 3.5 on both axes. This does not establish player/tester benefit or narrator improvement. `ratings.csv`; `sp4-primary-report.md`, "M1 original-artifact ratings". |
| Q6: What are the token, latency, and retry costs per arm? | **Inconclusive** | The run-wide totals are known (513 attempts; 3,453.3628182079847 live seconds), but route confounds and incomplete rows prevent a clean per-arm cost comparison. `sp4-primary-report.md`, "Primary collection outcome" and "Evidence corrections, confounds, and limits". |

## Recommendations for owner review

These are recommendations, not decisions. None authorizes production work.

### S1 - scene/layout foundation

- **Recommendation:** Prefer a relationship-rich, provenance-bearing scene
  foundation with explicit scope, topology-bound identities, fixed anchors
  versus mobile occupants, multi-cell extents, and explicit unknowns. Treat
  schematic cells as non-metric. Keep the final schema and contract open.
- **Rationale and evidence:** The owner feedback identifies empty grids and
  detached feature lists as inadequate mise-en-scene; PR116 demonstrates
  provider-free supplied-fixture checks for IDs, provenance, unknowns, linked
  views, and positional coverage. Neither source proves runtime utility.
- **Confidence:** Moderate for this design direction; low for any final schema
  choice.
- **Would change it:** Owner acceptance of an S1 contract, review against
  spatial/Builder/Narrator ownership, D1 audit findings, and independently
  reviewed evidence that a different representation better preserves action-
  relevant relationships.
- **Sources:** `plans/v2-spatial.md`, S1; `plans/v2-mapping-pilot-owner-feedback.md`,
  IMPORTANT section and Appendices A-I; `scripts/mise_en_scene/README.md`.

### S2 - Narrator spatial context

- **Recommendation:** Prioritize a bounded Narrator-facing projection of
  coherent scene and route relationships; derive player views from the same
  spatial facts. Do not select B versus D or set production packet limits here.
- **Rationale and evidence:** The owner explicitly sets Narrator-first
  mise-en-scene. SP3 does not distinguish B/D reliably, and PR116 only verifies
  supplied-fixture projection behavior.
- **Confidence:** Moderate in the Narrator-first priority; low in any specific
  payload format or runtime effect.
- **Would change it:** Owner format choice, locked transcript ratings, and a
  separately authorized evaluation with complete per-arm assertions, route
  identity, token/latency measures, and no pooling across cells.
- **Sources:** `plans/v2-mapping-pilot-owner-feedback.md`, IMPORTANT section;
  `plans/v2-spatial.md`, S2; `sp4-primary-report.md`, SP3 adjudication and SP4
  review.

### SC1 - encounter spatial state

- **Recommendation:** Keep the pilot ledger observational and do not choose
  combat granularity or enforcement from current SP3 results. Require an owner
  SC0 decision before any later SC1 contract or implementation.
- **Rationale and evidence:** Movement overshoots and invented metric claims
  occurred, but the valid-round, contradiction, and intent denominators needed
  by the frozen close-enough rule are unknown or incomplete. Observations do not
  establish a legal move contract.
- **Confidence:** High that the current evidence is insufficient for a choice;
  low on which granularity/enforcement level is best.
- **Would change it:** Owner selection of granularity and enforcement, plus
  complete shadow observations and intent outcomes evaluated against the frozen
  thresholds. Firelight authority remains limited to migrated rule families
  through the Python bridge under ADR-0033; unmigrated families retain Python
  guards.
- **Sources:** `plans/v2-mapping-pilot.md`, section 7.2; `plans/v2-spatial.md`,
  SC0-SC1; `adrs/0033-firelight-rules-engine-under-python-host-authority.md`.

### S3 - authored data and backfill

- **Recommendation:** Do not approve bulk backfill from D1 now. Keep the
  backfill-versus-Builder pipeline decision open until the owner audits D1.
  Preserve the prospective Builder-authored initial-scene path as a candidate,
  distinct from extracting legacy source facts.
- **Rationale and evidence:** D1 made 20/60 calls and yielded 11 valid and 9
  invalid layouts, but its 1,048 claim rows are unaudited. The frozen backfill
  rule requires at least 85% owner-audited precision and zero invented exits;
  automated graph flags are not that audit.
- **Confidence:** High that D1 cannot authorize backfill without the audit;
  low on the eventual pipeline choice.
- **Would change it:** Completed owner audit with its numerator, denominator,
  precision, and invented-exit judgments, followed by explicit owner selection
  of backfill, Builder-only, or a bounded combination.
- **Sources:** `plans/v2-mapping-pilot.md`, section 7.2; D1 `RUN_NOTES.md` and
  `d1_owner_audit.csv`; `plans/v2-spatial.md`, S3; owner feedback, IMPORTANT
  section.

  Owner-approved clarification: open facts are TITAN hooks, resolved only by Python-validated campaign commits (never Narrator narration); see [ADR-0034, "Open facts and TITAN resolution"](../../../../adrs/0034-spatial-authority-and-projections.md#open-facts-and-titan-resolution).

### S4 - shared player map

- **Recommendation:** Treat the player map as a secondary, cumulative,
  knowledge-filtered projection of the same canonical spatial relationships;
  do not ship or select a renderer from M1 alone.
- **Rationale and evidence:** M1 fails the frozen 3.5 threshold overall, while
  authored fixture sketches rate higher than D1 sketches. The owner requests
  cumulative discovery rather than a scene-by-scene replacement, but M1 is not
  a player cohort or a measure of narration gains.
- **Confidence:** Moderate in the secondary-projection principle; low that the
  current sketch approach meets the shared-picture goal across authored and
  legacy data.
- **Would change it:** Owner format decision, a reviewed projection contract,
  knowledge-leak checks, and separately authorized tester evidence for
  legibility and plan-discussion usefulness.
- **Sources:** `plans/v2-mapping-pilot-owner-feedback.md`, "Review notes:
  regional context, scale and cumulative discovery" and IMPORTANT section;
  `plans/v2-spatial.md`, S4; reviewed M1 CSV.

## Owner inputs - all PENDING

No item below has been filled by this report or by an automated count.

1. **PENDING - D1 audit:** owner judgments for all 1,048 claim rows, including
   precision numerator/denominator and invented exits.
2. **PENDING - live transcript ratings:** lock ratings for the seven
   complete-for-rating transcripts. Keep the 18 not rateable excluded, E01
   separately excluded, and the condition key withheld until lock.
3. **PENDING - format choice:** no B/D representation or production packet
   format is selected.
4. **PENDING - combat granularity/enforcement:** no zone granularity,
   clarification policy, or enforcement level is selected.
5. **PENDING - data pipeline:** no backfill-versus-Builder choice is selected.
6. **PENDING - ADR-0034:** explicit accept, revise, or leave Proposed decision.
7. **PENDING - mise-en-scene Section 2 decisions:** separately decide whether
   to authorize any evaluation and, if so, its exact source set/manifest,
   rubric and thresholds, assignment/order, assessor and model route, budgets,
   caps, and required runtime authority. PR118 remains an unfrozen draft with
   two leakage flags; neither is resolved or treated as owner approval here.

## Limits and threats to validity

- SP3 has protocol deviations, unpooled freezes, incomplete lifecycle coverage,
  missing rows, source amendments, and route variation. The total attempts and
  live time do not repair the missing per-arm validity or denominators.
- The 16 M1 scores are owner judgments on a small packet with visible sketch
  format (partial blinding). Fixture and D1 strata differ; the M1 means do not
  measure LLM narration or player outcomes.
- D1's automated validator is not the owner audit. The 20-location sample and
  three source modules do not establish population-wide backfill precision.
- Seven transcripts remain unrated; 18 are not rateable; E01 is excluded; the
  key remains withheld. Stage 1 was waived, not scored.
- PR116 proves only supplied-fixture tooling behavior. Exact approved text and
  typed-claim checks are not general semantic assurance, and the prototype is
  not proof of LLM Builder capability or production behavior.
- PR118 is not frozen or owner-approved. Its two leakage flags remain pending;
  no holdout result is used here.
- This document is provider-free and documentary only. No new model calls,
  live captures, production state changes, or module writes were performed or
  authorized.

## Source index

- `plans/v2-mapping-pilot.md`, sections 4, 7.2, 8, and 10.
- `openspec/changes/v2-mapping-pilot-execution/reports/sp4-primary-report.md`,
  including its later SP3b, M1, and mise-en-scene handoffs.
- `tmp/router-rollout/mapping-pilot/m1/m1-20261105-02/ratings.csv` (reviewed
  M1 values; read-only).
- `tmp/router-rollout/mapping-pilot/d1/d1-20261105-01/RUN_NOTES.md` and
  `d1_owner_audit.csv` (D1 run and pending audit).
- `plans/v2-mapping-pilot-owner-feedback.md`, especially the IMPORTANT
  mise-en-scene section (read-only).
- `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/proposal.md`,
  `design.md`, and
  `openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/reports/offline-build-verification.md`.
- `scripts/mise_en_scene/README.md` (PR116 offline prototype contract and
  limits).
- `plans/v2-spatial.md`, S1-S5 and SC0-SC4 (read-only planning context).
- `adrs/0034-spatial-authority-and-projections.md` and
  `adrs/0033-firelight-rules-engine-under-python-host-authority.md`.
