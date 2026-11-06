# SP3b Supplemental Preregistration Amendment

**Status: DRAFT / NOT FROZEN.** Planning only: no preparation, provider
request, server/seeder, live execution, transcript rating or ADR action. D1/M1 are owner-owned work, not agent review items; this draft authorizes neither.
Transcript ratings and ADR-0034 await SP3b evidence and the later owner gate.
All harness fixes/provider-free checks, specific Overseer freeze, and a later
non-overlapping 8360 booking are prerequisites; no live work beforehand.

**Authority/base:** SP3 ruling `1a9946086d2ec84baf518dde58e0f60ba308714e`;
standing mailbox/lock rules and planning base `370dec003763fd46cd1800e089fe9d98c3ae0d39`
(ledger §§10.1-10.2; `C/rulings/S.md`). Host fix #105 (`9291994f`) unchanged; standing authorization is not an amendment-specific freeze.

Resolve `C=$(git rev-parse --path-format=absolute --git-common-dir)/neq-coordination`;
it is outside all worktrees and never committed. Read `C/rulings/S.md` at each
resume and between tasks; append dated-UTC reports to `C/inbox/S.md`, and treat
`C/bookings.log` as append-only. If `C` is inaccessible or a required read/write
fails, STOP and report; do not work around it.

This amendment has a separate SP3b identity; it is not a rewrite, content retry
or way to pass SP3. The 10 frozen files/manifest, original rows/evidence,
OpenSpec artifacts and narrative plan stay read-only; this file is outside the
manifest. Seven re-freezes and the missed pause remain deviations, not waived.

SP3 remains INCONCLUSIVE for all arm comparisons: content findings stand, no
cell repeats for quality, and SP3b addresses only infrastructure-invalidated
samples. All 26 original terminal statuses/classifications, including
`UNRESOLVED`, remain unchanged.

## 1. Proposed scope and fixed order

The **proposed** set is exactly 19 infrastructure-invalidated original cells
in stable filtered counterbalance order: E01, E03-E06, E13-E18, C01, C02-C08.
It is subject to Overseer review, not yet frozen or authorized for execution.
SP3B row IDs are new; preserve source cell, arm, party, script, repeat, seed,
and order as bound by `counterbalance.json`. Use frozen fixture/script bytes;
never adapt inputs, order, or classification after viewing content.

| SP3b row | Source cell | Order | Arm | Party | Script | Repeat | Seed | Infrastructure basis; retained finding |
|---|---|---|---|---|---|---|---|---|
| `SP3B-001` | E01 | 01 | A | P1 | `scripts/interior.json` | 1 | 5101 | Collector stop/namespace collision; 0 turns, unbound recovery/no transcript. |
| `SP3B-002` | E03 | 03 | D | P1 | `scripts/interior.json` | 1 | 5101 | Worker socket disconnect; final receipt/assertions/lifecycle checkpoint absent; original `UNRESOLVED`. |
| `SP3B-003` | E04 | 04 | D | P1 | `scripts/landscape.json` | 1 | 5102 | Polling payload rejected after PING/PONG; no turns. |
| `SP3B-004` | E05 | 05 | B | P1 | `scripts/landscape.json` | 1 | 5102 | 22 MESSAGE packets exceeded decoder limit 16; `too_many_packets`. |
| `SP3B-005` | E06 | 06 | A | P1 | `scripts/landscape.json` | 1 | 5102 | `packet_location` NameError at `main.py:7486` counted as delivery, then timeout; host fix merged. |
| `SP3B-006` | E13 | 13 | D | P4 | `scripts/landscape.json` | 1 | 5105 | Same `packet_location` error/timeout; transition checks absent; host fix merged. |
| `SP3B-007` | E14 | 14 | A | P4 | `scripts/landscape.json` | 1 | 5105 | Same host error/timeout; arm A remains the frozen control. |
| `SP3B-008` | E15 | 15 | B | P4 | `scripts/landscape.json` | 1 | 5105 | Same `packet_location` error/timeout; host fix merged. |
| `SP3B-009` | E16 | 16 | B | P4 | `scripts/landscape.json` | 2 | 5106 | Same host error/timeout; transition checks absent. |
| `SP3B-010` | E17 | 17 | A | P4 | `scripts/landscape.json` | 2 | 5106 | Same host error/timeout; arm A unchanged. |
| `SP3B-011` | E18 | 18 | D | P4 | `scripts/landscape.json` | 2 | 5106 | Same host error/timeout; host fix merged. |
| `SP3B-012` | C01 | 19 | A | P1 | `scripts/combat.json` | 1 | 5201 | Missing Goblin template caused failed combat startup and fallthrough to `action_prediction` + `dm_main` (2 calls); correction recorded before C02. |
| `SP3B-013` | C02 | 20 | D | P1 | `scripts/combat.json` | 1 | 5201 | One unexpected `combat_main` startup call; preserve K2-03 stairs-to-balcony finding separately. |
| `SP3B-014` | C03 | 21 | D | P1 | `scripts/combat.json` | 2 | 5202 | Same startup invalidation; preserve K2-03 content finding separately. |
| `SP3B-015` | C04 | 22 | A | P1 | `scripts/combat.json` | 2 | 5202 | Same startup invalidation; preserve K2-03 content finding separately. |
| `SP3B-016` | C05 | 23 | D | P4 | `scripts/combat.json` | 1 | 5203 | Same startup invalidation; retain invented metric distance/height findings. |
| `SP3B-017` | C06 | 24 | A | P4 | `scripts/combat.json` | 1 | 5203 | Same startup invalidation; retain balcony overshoot/invented distance. |
| `SP3B-018` | C07 | 25 | A | P4 | `scripts/combat.json` | 2 | 5204 | Same startup invalidation; movement/round/enemy policy remain unknown. |
| `SP3B-019` | C08 | 26 | D | P4 | `scripts/combat.json` | 2 | 5204 | Same startup invalidation; preserve K2-03 finding separately. |

Eligibility is proposed only for listed infrastructure invalidations, not
content quality. C02-C08 qualify because unexpected startup calls invalidated
samples, not for K2-03/content findings; a corrected repeat is not a content
retry. Original outcomes/findings remain unchanged. Receipts:
`tmp/router-rollout/mapping-pilot/row-bundles/sp3/<cell>-20261105-01/router_receipts.json`.

E02, E07-E12, R01-R04 and unapproved rows remain excluded regardless of outcome.
E02's invented alley is not a rerun basis; E09 cap/E10 resume blocks do not
qualify. No content defect or E10 correction adds scope; no reserves/replacements.

Give each approved cell one new row execution with distinct run/row/row_run IDs
(`SP3B-001`...`SP3B-019`); keep original cell IDs as provenance. Never reuse a
main-run ID, terminal row, bundle, freeze or identity. Profile-authorized
operation retries are separate attempts charged to existing caps; no row
retry/replay/reseed. Failed/interrupted rows are terminal; unrun approved cells
are `missing` with reasons.

## 2. Cause-to-fix record

The fixes below are current/merged corrections, not proof of live success;
revalidate offline against final SP3b identity. Green tests/driver exit 0 are
never live PASS.

| Main-run cause / evidence | Verified correction and status | SP3b requirement |
|---|---|---|
| E01 collector/namespace failure; E03 disconnect omitted final evidence. | Collector namespace and lifecycle receipt collection corrected; E01 remains unbound, and the observed E03 disconnect is not thereby cured. | Provider-free checks prove disjoint namespaces and complete raw/final receipts, assertions, and lifecycle evidence before teardown; otherwise BLOCKED/UNRESOLVED. |
| Landscape preflight rejected the frozen pair. | Preflight narrowed without changing fixtures/scripts. | Accept the exact frozen pair; reject altered hashes/unknown variants before seeding. |
| E04 polling rejection; E05 22 MESSAGE packets exceeded decoder default 16. | Exclusive bounded 64-packet decoder; restore 16 only after reader stops. Conflicting ownership, bad prior bound, failed restore, or 65 packets fail closed. | Provider-free negatives cover exclusivity, exact bound, 65 rejection, cleanup/restore; no global limit/dependency change. |
| E06 child guard/receipt path used copied sandbox and could lose parent caps/receipts. | Parent-owned execution/manifest and durable caps; atomic no-overwrite receipt observer; invalid bootstrap fails closed. | Prove parent ledger owns counters/identity and reconcile all child attempts/receipts; unknown or missing evidence blocks. |
| E10 checked resume rejected a moved matching checkpoint. | Resume checks checkpoint hash, party/module/area/location and reciprocal frozen connectivity without reseeding. | Recheck offline; E10 remains excluded and its original terminal result is immutable. |
| C01 missing Goblin template/encounter hash parity; combat fell through to two startup operations. | Template/hash correction checked before C02; original C01 remains BLOCKED. | Offline rebuild and template/encounter identity/hash validation; failed-combat-fallback profile must fail preflight. |
| E06/E13-E18 `packet_location` NameError counted as delivery, then timeout. | PR #105 / `9291994f` fixes DM Note connectivity fallback; P1/P4 regressions in `scripts/test_main_location_connectivity_note_fix.py`. | Run provider-free P1/P4 regression against frozen source; no original row is upgraded. |

### Required but not yet implemented SP3b harness corrections

1. **Classifier/pause.** `default_row_runner_hooks()` has no classifier and
   writes `UNRESOLVED/no_classifier`; ledger pause recording depends on supplied
   classification and is not the missing gate. Classify pre-review from
   process/transport/provider status, time and artifact evidence only; unknown
   is unresolved, never eligible. Atomically persist the third consecutive
   infrastructure result/pause before row four can seed, launch or request.
   Mixed causes count; non-infrastructure breaks the streak. Only owner
   review/checked resume clears it; no automatic retry/replay/resume. Ledger or
   unit tests alone are insufficient.
2. **Filtered matrix/caps.** Bind 19 IDs/source cells and carry main usage
   across runs, pauses and bookings; current 30-slot/fresh counters do not.
   Unknown totals block preparation/requests.
3. **Fixture/lifecycle profiles.** Keep runtime, arm A, scripts and actual
   fixture `provider_call:false`/`provider_call_expected:false` controls
   unchanged; no suppression, core hook or script edit. Primary receipts at
   `tmp/router-rollout/mapping-pilot/row-bundles/sp3/<cell>-20261105-01/router_receipts.json`
   show E01/E03/E06 with six expected-false startup logical calls, ordered
   `travel_narration`, `safety_review`, `travel_narration`, `safety_review`,
   `action_prediction`, `dm_main`. C01's missing Goblin template caused failed
   combat startup to fall through to two calls (`action_prediction`,
   `dm_main`), not the normal profile; C02-C08 each show one expected-false
   startup `combat_main` call in corrected combat startup. These are observed,
   not guaranteed future counts.

   Before freeze, provider-free validation must source-link and test exact
   logical roles/order and call-ID/receipt linkage per fixture/lifecycle
   boundary. Retries are separate attempts within existing caps. Reject failed
   combat-fallback at preflight; target corrected real combat. Prove exploration
   and resume separately (six startup calls do not prove resume). No blanket
   whitelist/new unit cap; unexpected, unlinked or unprofiled operations fail
   closed. Prospective non-scripted lifecycle operations may be ratified at
   freeze; historical calls remain deviations, never silently waived.
4. **Deterministic no-model Disengage.** For K2-02, fabricate no call/receipt/
   response/hint/latency. Provider-free tests link consumed input, actor, actual
   output/action and canonical before/after state. `N/A (deterministic, no model
   call)` requires complete no-request receipts; zero receipts alone proves
   nothing. Missing correlation blocks.
5. **Chronological zone evidence.** Persist ordered events linked to
   row/lifecycle/step/actor/source/time: hint status/payload, applied enemy
   phases and explicit missing/invalid states. Never infer from narration/final
   state or treat absence as zero contradictions; missing source is unknown
   with reason. Provider-free negatives catch lost order/linkage and empty-success.
6. **Identity.** Apply Section 5 before every row, request and resume.

## 3. Cumulative budget and stop rules

| Limit | Main run consumed | SP3b maximum remaining | Cumulative maximum |
|---|---:|---:|---:|
| Provider attempts | 513 | 287 | 800 |
| Live time (launch through final teardown) | 3,453.3628182079847 s | 18,146.637181792015 s | 21,600 s |
| Per row | -- | 35 attempts / 1,500 s | Unchanged |

These are hard ceilings, not targets/quotas. Count all provider attempts
(startup/resume, errors, retries, fallbacks, provider-backed classifier and
child calls). Row time spans launch through final teardown, including restarts.
Keep 35 attempts/1,500 seconds per row. Pauses or new IDs, bookings, processes
or resumes never reset usage; unknown totals block the next request/row.

Durably check counters before each request and refuse over-cap attempts. Before
a row, require known budget and provider-free teardown headroom within 1,500
seconds; record policy without adding headroom to the cap. If teardown safety is
unknown, do not start and stop requests before spending headroom. Frozen
FAIL/BLOCKED rules stand; only positively evidenced pre-content infrastructure enters the
pause streak. No reserves/replacement/replay/content rerun; unrun rows are
`missing` with reason.

Persist the classified third result/pause before row four can call seeder,
launcher, socket driver or provider. Mixed causes count; no automatic
retry/resume. Stay paused until owner review of evidence and checked-resume
authorization; main-run attempt/time totals remain charged.

## 4. Startup operations, control turns, and evidence completeness

Use Section 2 item 3 profiles; historical receipts remain deviations and frozen
false controls unchanged. No suppression, hook, script edit or blanket
whitelist; unexpected/unprofiled/unlinked operations fail closed. Retain linked
logical/per-attempt receipts (or explicit evidence failure), route/provider and
usage/cost/time; separate lifecycle metrics from turn scoring while charging
all attempts. Request `production-auto`/`openrouter/auto`, observe resolved Auto
model and report the 10-point route-share confound where matched. K2-02, hint and
enemy-phase evidence follows items 4-5; missing chronology/linkage is unknown,
never zero contradictions.

## 5. Single immutable execution identity

Use one immutable execution identity for the entire SP3b run, not one per cell.
Before prepare/seed/attempt, create a freeze artifact under the new project-
relative run directory (e.g. `tmp/router-rollout/mapping-pilot/sp3b/<sp3b-run-id>/execution-freeze.json`),
then bind its hash in the ledger before the first prepare/attempt. It must hash:

- full source commit, clean worktree/tree digest, `requirements-lock.txt`, exact interpreter/
  dependency versions and non-secret environment/config, route/static routing;
- prompt/tool/source hashes, frozen fixtures/scripts, approved lifecycle input profiles,
  classifier/scorer/driver/seeder and other control/protocol settings;
- unchanged 10-entry manifest/hashes, amendment hash, row bindings and budget
  baseline.

Exclude mutable party/encounter state, evidence outputs, timestamps, call IDs
and allowed resolved-Auto provider/model observations from the identity;
preserve them as linked evidence. Runtime state/output changes alone do not invalidate it.

The **PLANNING BASE** is `370dec003763fd46cd1800e089fe9d98c3ae0d39`; the SP3
adjudication is `1a9946086d2ec84baf518dde58e0f60ba308714e`. Neither is final
runtime identity or proof the harness is ready. Freeze only after required
corrections pass provider-free tests and the Overseer specifically freezes this
amendment, including source-linked profiles/prospective lifecycle declarations.
Booking is a later, separate gate.

Verify the identity before every row/request/resume. Any identity-field change
stops the run; preserve evidence and do not refreeze under another booking/ID.
Resolved Auto remains evidence, not an identity pin. Do not pool identities;
preserve the 10-point confound flag.

## 6. Evidence, scoring, and outcome gates

Keep SP3/SP3b separate; do not pool across freezes or fill missing comparators.
Preserve immutable evidence under the new project-relative root: IDs/source
cell/identity and arm/party/script-fixture hashes/repeat/seed; packets,
transcripts/output and canonical before/after state hashes/snapshots (including
encounter);
ordered zone events; all operation/attempt receipts, counts, route/provider,
cost/usage provenance and unknowns; expected/observed checks; server/driver
lifecycle and seed/launch/restart/teardown/finalize/score times; caps, deviations,
classification/source, verdict and missing artifacts. Save raw before teardown;
never alter original bundles.

Keep the frozen rubric, measures, contract and thresholds. Only complete
matched cells in this identity contribute; unknown denominators are not
estimable. Report per-family evidence/missing cells; this is not full-matrix
coverage. Driver exit 0, green tests or complete transport is not PASS. Missing
checks, attribution, K2-02 evidence, chronology or artifacts leaves the row
FAIL/BLOCKED and gate incomplete.

## 7. Offline preflight and approval checklist

These read-only/provider-free commands run at repo root; they do not start a
server, seed, inspect credentials, call a provider, rate transcripts or take
ADR action. No live command is authorized here.

### Frozen preregistration: verify all 10 original hashes

```sh
.venv/bin/python -c 'from scripts.mapping_pilot.manifest import verify_manifest; h=verify_manifest(); assert len(h) == 10, len(h); print("verified", len(h), "frozen entries")'
(cd plans/v2-mapping-pilot-prereg && shasum -a 256 -c MANIFEST.sha256)
```

Both commands must verify all ten frozen entries; this amendment stays outside
and does not alter `MANIFEST.sha256`.

### Eligibility, bindings, count, and order

```sh
python3 - <<'PY'
import json
import re
from pathlib import Path

root = Path("plans/v2-mapping-pilot-prereg")
data = json.loads((root / "counterbalance.json").read_text())
rows = {row["row_id"]: row for row in data["rows"]}
ids = ["E01", *[f"E{i:02d}" for i in range(3, 7)], *[f"E{i:02d}" for i in range(13, 19)], *[f"C{i:02d}" for i in range(1, 9)]]
pattern = r"^\| `SP3B-(\d{3})` \| ([EC]\d{2}) \| (\d{2}) \| ([ABD]) \| P([14]) \| `([^`]+)` \| (\d+) \| (\d+) \|"
entries = re.findall(pattern, (root / "SP3b-amendment.md").read_text(), re.M)
assert [entry[1] for entry in entries] == ids
assert len(entries) == 19
for index, (new_id, cell, order, arm, party, script, repeat, seed) in enumerate(entries, 1):
    row = rows[cell]
    actual = (int(order), arm, int(party), script, int(repeat), int(seed))
    frozen = (row["run_order"], row["arm"], row["party"], row["script"], row["repeat"], row["fixed_seed"])
    assert new_id == f"{index:03d}" and row["row_type"] == "planned" and actual == frozen, cell
print("19 amendment-table bindings match counterbalance in filtered order")
PY
```

### Cumulative budget baseline and remaining ceiling

```sh
python3 - <<'PY'
import json
import math
from pathlib import Path

totals = json.loads(Path("tmp/router-rollout/mapping-pilot/sp3/sp3-s-20261105t200000z/primary-collection-closeout.json").read_text())["matrix_totals"]
assert totals == {"matrix_attempts": 513, "matrix_elapsed_seconds": 3453.3628182079847}
assert (800 - totals["matrix_attempts"]) == 287
assert math.isclose(21600 - totals["matrix_elapsed_seconds"], 18146.637181792015, rel_tol=0, abs_tol=1e-9)
print("remaining ceiling verified: 287 attempts; 18146.637181792015 seconds")
PY
```

Unknown/mismatched source totals block freeze. At freeze, confirm unchanged
35-attempt/1,500-second row caps, cumulative cap linkage, stop/pause behavior,
and the measured teardown headroom. No new run ID or booking may reset these
values.

### Required future provider-free harness tests (not present or run in this docs phase)

The existing provider-free suite predates these requirements. Before freeze, a
separately authorized implementation phase must add
`scripts/test_mapping_pilot_sp3b_execution.py`, with tripwires forbidding
provider/server/seeder/socket-driver calls. Negative cases must prove:

- pre-review classifier (`None` is not infrastructure); atomic mixed-cause third-failure pause before row four; non-infrastructure resets streak; owner review/checked resume only, no retry/replay;
- parsed immutable 19-row bindings/order and unique IDs; no content/result/unresolved/terminal original can be selected as replacement;
- cumulative caps across IDs/bookings/resumes, unknown-total refusal, all attempts charged and teardown headroom within row cap;
- immutable-identity drift stops without refreeze, while runtime state/evidence/times/call IDs/resolved-Auto observations do not drift it;
- source-linked per-fixture/lifecycle roles/order and call-ID/receipt linkage; unexpected/unlinked calls fail; retries charged under existing caps (no new unit cap); C01 fallback rejected, corrected combat targeted, exploration/resume separately proven, false controls unchanged; historical receipts do not auto-authorize calls;
- K2-02 correlation/no-model and chronological zone ordering/linkage/missingness; no fabricated calls/hints or empty-success traces;
- cap/timeout/interruption/evidence-loss/pause stops preserve evidence and mark unrun approved rows `missing`, without replay.

After that file exists, the exact provider-free command is:

```sh
test -f scripts/test_mapping_pilot_sp3b_execution.py && .venv/bin/python scripts/test_mapping_pilot_sp3b_execution.py
```

**Existing P1/P4 test limitation (2026-11-06):** combined
`.venv/bin/python -m unittest scripts.test_mapping_pilot_fixtures scripts.test_main_location_connectivity_note_fix`
ran 15 tests/4 errors; all dynamic-`main` import checks hit
`scripts.core_chat_test_safety.TripwireFailure` at `httpx.Client` construction
in the import-time combat factory. Isolated `.venv/bin/python -m unittest
scripts.test_mapping_pilot_fixtures` passed 9 tests. Logs:
`tmp/sp3b-amendment-provider-free-final.log` and
`tmp/sp3b-amendment-fixture-tests.log`; no provider request/server ran. This is
a harness-isolation issue, not evidence host fix #105 (`9291994f`) is defective.
Do not bypass tripwires or change host source here; before freeze, an authorized
implementation phase must isolate the regression harness with safety guards on.

The implementation phase must also rerun
`.venv/bin/python -m unittest discover -s scripts -p 'test_mapping_pilot_*.py'`
and the P1/P4 host regression above; run ASCII checks for changed Python.
No OpenSpec scaffold is needed. No provider test/live command/server/seeder,
transcript rating or ADR action is authorized here; D1/M1 remain owner work,
not agent review items.

### Identity, booking, scope, and freeze approvals

Before freeze, verify clean source/lock/environment/route, profiles,
amendment/manifest hashes, controls, caps and run freeze; verify identity before
each row/request/resume. Only this file may change; preserve the manifest.

After specific Overseer freeze and any required implementation approval, S
self-books via ledger §10.2 (not Overseer-booked), using its atomic 8360/8370
lock; if held, no force/retry. Immediately write required `holder.json` fields
(`booking_id=<gate>-S-<UTC yyyymmddThhmmssZ>`, holder/gate/ruling, <=8h window,
frozen caps) and append `bookings.log`. Confirm both ports unoccupied/no-overlap;
do not start a row that cannot finish in-window. Caps stay 287 attempts/six
cumulative hours/35 attempts and 1,500s per row. Release only after teardown/no
listeners on both; append evidence, remove holder then `rmdir`, report inbox.
Follow §10.2 stale/missing-holder rules exactly (including 10 minutes), no
broadening. This PR does no booking/port inspection/live work. Submit evidence
to inbox; Overseer records verdicts; S may report observations, not gate PASS.

## 8. Freeze decision

Remain DRAFT until corrections/tests pass, profiles/lifecycle declarations are
reviewed, identity is frozen and the Overseer specifically freezes this file.
Next publish an amendment-only PR, append a dated UTC PR/report to
`C/inbox/S.md`, then pause for a specific amendment ruling in `C/rulings/S.md`.
Standing authorization is not a freeze; do not self-merge/self-freeze. Only
after that ruling and any needed implementation approval may S self-book per
§10.2. No execution or coverage/PASS/ADR claim before all gates.
