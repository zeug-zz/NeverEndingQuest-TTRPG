# Task 6.2 - G4 Socket Driver, Receipt Collection, and Evidence Projection

Status: task 6.2 tooling implementation and fresh primary software verification
PASS; task 6.2 is checked. No live G4 capture or PASS verdict is claimed. Tasks
6.3 matrix/negative evaluation and primary-owned tasks 6.4/6.5 remain pending.

## Scope implemented

- Removed the task-6.2 deferral from the existing socket driver. G4 still uses
  only the fixed narrator-dialogue-travel and seeded combat-smoke profiles,
  with the existing G3 default and path kept separate. G4 run bundles validate
  under `tmp/router-rollout/g4/<run-id>/` using the same unique-path, symlink,
  and sandbox-root checks as G3.
- Narrator requests use the existing socket `start_game`/`user_input` contract.
  The five fixed profile turns have independent 300-second caps and use the
  profile's source-derived expected room IDs. A step stops the queue on timeout,
  cap, missing persisted location/party/active-PC observation, or missing
  distinct backend output for the Mira question. Input and control budgets
  remain separately represented; G4 health reads retain their separate bound
  of three.
- Added read-only G4 projection fields for persisted `currentLocation`,
  `currentLocationId`, `partyMembers`, and `active_character`. These are kept
  separate from G3's historical mechanical projection. Each G4 step retains its
  expected source-profile room/actor and observed persisted projection, plus
  captured backend outputs separated from GUI/user-input echoes.
- The evidence reader parses only the newly copied trace span. Receipt
  projection accepts actual `provider` adapter rows with paired call/attempt
  identity and observed provider, requested/resolved model, task, retry,
  fallback, usage availability/completeness, and cost provenance. Actual zero
  remains `actual`; estimates remain `estimated`; missing cost remains
  `unpriced_unknown`. Missing/duplicate identities or required metadata, absent
  receipts, parse failures, or receipt spans that do not pair to a single step
  remain BLOCKED. Declared config and aggregated router statistics are not used
  to fill runtime evidence.
- The run bundle records per-step G4 projections and actual receipt data in its
  manifest. The evidence helper does not assign a primary verdict. Existing G3
  raw bundle behavior, defaults, latency scripts, and G3 mechanical projection
  semantics remain unchanged.

## Receipt shape checked

The runtime adapter's `provider` trace row carries `call_id`, `attempt_id`,
`attempt_number`, `task`, `provider`, optional `observed_upstream_provider`,
`requested_model`, `resolved_model`, `retry`, `retry_tier`, `fallback`, token
counts, `usage_available`/`usage_complete`, cost amount/provenance/completeness,
outcome/error type, and elapsed time when known. The collector uses only rows
whose complete source-byte span belongs to exactly one captured step. It does
not reinterpret legacy compression/predictor events as migrated core receipts
or create attempt IDs for them.

## Verification

All suite runs used separate processes with `OPENSPEC_TELEMETRY=0`,
`DO_NOT_TRACK=1`, `PYTHONDONTWRITEBYTECODE=1`, and `TMPDIR=tmp`. Runtime-owner
suites were run with empty credential config fixtures and fatal process
tripwires armed before imports; the core inventory contract suite includes its
own expected-tripwire tests and asserts the untouched guard before exercising
them.

| Suite/check | Result |
|---|---:|
| `scripts.test_capture_drive` | PASS, 61 tests |
| `scripts.test_runtime_area_hydration` | PASS, 14 tests |
| `scripts.test_combat_latency_baseline` | PASS, 24 tests |
| `scripts.test_llm_runtime_receipt_adapter` | PASS, 15 tests |
| `scripts.test_llm_router` | PASS, 88 tests |
| `scripts.test_benchmark_model_profiles` | PASS, 6 tests |
| `scripts.test_gpt54_chat_params_contract` | PASS, 10 tests |
| `scripts.test_gpt54_mini_chat_params_shim` | PASS, 6 tests |
| `scripts.test_gpt56_luna_direct_openai_contract` | PASS, 41 tests |
| `scripts.test_core_chat_inventory_contract` | PASS, 14 tests |
| `scripts.test_core_chat_request_contracts` | PASS, 17 tests |
| **Total** | **PASS, 296 tests across 11 separate processes** |
| Scoped `py_compile` of capture driver/evidence/fixtures/tests | PASS |
| `python3 scripts/check_ascii_compliance.py --summary-only` | PASS, 0 violations |
| `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate llm-router-core-migration --strict` | PASS |

Focused tests cover G3 default/profile compatibility, fixed G4 P1/P4 input and
control limits, distinct G4 path validation, persisted room/party/active-PC
projection, receipt identity and pairing (including actual zero cost), and
timeout fail-stop with no later queued input. No G4 four-key matrix evaluation
was added or run here.

## Fresh primary review and verification

- Primary reviewed the actual path `actualRouter(fakeSDK)->realadapter->realtracewriter->collector` and confirmed byte-span receipt pairing.
- Four synthetically labelled actual-run G4 cases covered narrator/combat P1/P4, bounds, projections, and fail-stop behavior. These are synthetic evidence, not live data or live G4 verdicts.
- Capture, hydration, and baseline runs used an empty credential configuration with shared guards armed before load; post-assertions confirmed the configuration remained untouched.
- The suite counts above comprise 61 capture, 14 hydration, 24 baseline, 15 adapter, 88 router, 6 benchmark, 10 GPT-5.4, 6 mini, 41 Luna, 14 inventory, and 17 request-contract tests. Strict, scoped-diff, ASCII/whitespace, and no-ignored-cleanup checks PASS.
- The associated result is addprimarysoftwarePASS 22/25, with 15/15 operations verified. Tasks 6.3-6.5 remain pending. The full 705-test suite was not rerun.

## Focused verification correction

- Added a provider-free vertical receipt test using the real `LLMRouter`, a fake
  SDK transport, the real `make_legacy_receipt_observer`, and the real
  `combat_latency_trace.emit_trace_event` JSONL writer under a unique project
  `tmp/` directory. The test parses that newly written span and passes its rows
  through `pair_g4_receipts` against a step byte span. It verifies task,
  call/attempt identity, transport provider, requested/resolved model, retry and
  fallback booleans, observed usage, reported actual zero, plus a second
  estimated-or-unpriced cost label. Removing required trace metadata remains
  BLOCKED. No production adapter/writer changes or collector relaxation were
  needed; the actual writer row shape satisfies the existing collector.
  During test shaping, a response without
  `usage.prompt_tokens_details.cached_tokens` correctly produced
  `usage_complete: false`; the synthetic complete-usage case was corrected to
  explicitly report cached tokens as zero. This was fixture completeness, not
  an adapter/writer contract mismatch.
- Added four finite synthetic G4 driver executions through `capture_drive.run`
  with the real bundle/snapshot/trace/projection code and fake socket/REST
  transports: narrator P1/P4 and seeded combat P1/P4. They verify exact fixed
  profile caps (narrator 6 inputs / 8 or 9 controls; combat 5/7 or 22/35), the
  300-second declared turn cap, health reads <=3, persisted room/active-PC and
  roster identity, distinct echo/backend output, source identity, source-byte
  receipt pairing, and manifest/transcript/server-log/trace/report/checks and
  before/after snapshot artifacts. Combat snapshots retain the seeded
  `capture_one_pc` Goblin or `capture_mp` Goblin Alpha/Beta identity. All four
  generated bundles are explicitly `synthetic` and `live_eligible: false`.
- A second full fake narrator run deliberately leaves CA02 unpersisted; the
  driver returns its failure code after two inputs and does not queue later
  turns. Missing snapshot projection and mismatched room/active-PC identity
  also remain BLOCKED. The separate four-key offline matrix remains pending
  under task 6.3.

## Safety and ownership boundaries

- All verification was provider-free. No actual server, socket endpoint,
  campaign, prepare/restore operation, credential, or user-owned session was
  accessed. No source profile declarations were treated as observations.
- The task-6.1 report records a credential-exposure incident and requires owner
  key rotation before any live capture. That prerequisite remains outstanding;
  this task does not inspect, use, rotate, or claim restoration of credentials.
- Only task 6.2 was checked. No task 6.3 matrix, task 6.4 live verdict, or
  task 6.5 final verification was performed.
- The security incident/owner key rotation prerequisite remains outstanding
  before any live capture. Synthetic evidence is not live data.
- Scratch/cache: `tmp/task-6-2-pycache`. Test fixture directories were confined
  to project `tmp/` and cleaned by their owning tests. Follow-up cache:
  `tmp/task-6-2-correction-pycache`. No live bundle was created.

## Attributable follow-up correction (task 6.3)

Task 6.3 added a startup-control trace-byte span bounded from the captured
pre-start offset through quiet startup readiness, so actual provider receipts
before the first scripted input have an explicit owner rather than being
misassigned to step 1. Every retained provider row must pair to exactly one
startup or input-step span; unpaired rows block, and deterministic `/att` or
`/dmg` combat steps may correctly have no provider receipt. The G4 profile now
observes startup CA01, then five adjacent persisted locations CA02, CA03, CA03
(Mira), CA02, CA01. This is the narrow source/evidence-plumbing correction for
the original task-6.2 driver and does not revise its G3 contract, expand
production routing scope, or claim live evidence.
