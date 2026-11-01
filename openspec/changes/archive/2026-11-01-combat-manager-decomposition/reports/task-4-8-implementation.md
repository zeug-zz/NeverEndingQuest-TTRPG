# Task 4.8 - Inventory Authority and Routing-Rejection Diagnostic

Status: **software-only implementation complete; no live run or G3 verdict**.

## Implementation

- `inventory_remove` runtime authority remains unchanged: equipment is the
  default; only `container="ammunition"` or `item_type="ammunition"` selects
  ammunition (`updates/update_character_info.py:1892+`). Structured inventory
  ops now select only the matching committed canonical container in combat
  validation context. This metadata does not copy candidate operation values;
  names such as "crossbow bolts" do not select ammunition. Existing prose-only
  context retains its previous inventory shape.
- The actual validation payload adds a conditional, narrow container-authority
  note only for structured inventory ops. Equipment/ammunition remain separate;
  no duplication, redirection, resource mechanics, or operation rewrite was
  introduced.
- On the existing enemy-boundary rejection only, `core/combat/validation.py`
  checks the existing trace gate before building a summary and sends a bounded
  observation through `trace_combat_observation`. It captures at most four
  `updateEncounter` actions/changes (512 characters each) and eight operations
  total with four selected scalar fields (128 characters each), plus a
  512-character reason, counts, and truncation metadata. It has no `path` field,
  and does not retain prompts, config keys, provider data, or full payloads.
  The precheck and rejection result are unchanged.

## Focused evidence

Provider-free tests passed separately:

| Suite | Result |
|---|---:|
| `scripts.test_combat_truth_pack` | 8 passed |
| `scripts.test_combat_validation_stage` | 13 passed |
| `scripts.test_update_character_ops_contract` | 21 passed |
| `scripts.test_combat_phase_integrity_precheck` | 18 passed |
| `scripts.test_combat_canonical_validation_facts` | 3 passed |
| `scripts.test_combat_trace_observation_writer` | 1 passed |
| `scripts.test_combat_decomposition_contract` | 9 passed |

The actual fake validation payload confirms ops-only ammunition removal carries
committed ammunition quantity 3, not candidate quantity 99, retains actor name
and container, and leaves actor/candidate state unchanged. The mechanics test
confirms explicit ammunition removal succeeds while the same name without an
ammunition selector retains the existing equipment-default failure. Routing
tests confirm trace-off does not call the observation writer, while trace-on
retains the exact actual changes/selected operation/reason within the bounds.
The shared real-writer regression passed.

Compile/AST checks passed with zero combat functions above 600 lines and the
legacy shim at 17 lines. ASCII compliance scanned 1,135 files with zero
violations. Scoped `git diff --check` and
`OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
combat-manager-decomposition --strict` passed.

No live capture or gate verdict was produced. The 18 strict live checks and
recorded prior FAIL/BLOCKED evidence are unchanged. At this report's original
implementation-verification checkpoint, Tasks 4.7, 5.3, and 5.4 remained
unchecked; the subsequent primary software-only verification is recorded
below.

## Primary software-only verification

- Primary source review passed the conditional inventory-container authority
  contract and the gate-first, bounded actual rejection diagnostic. Existing
  routing rules and precheck behavior remain unchanged; this review does not
  establish the unproven goal-prose mirror-failure cause.
- Fresh provider-free verification passed **193 tests in 13 separate
  processes**: Capture_Arena driver 47, combat-latency baseline 24, validation
  stage 13, truth pack 8, character-ops contract 21, phase integrity 18,
  canonical validation facts 3, trace writer 1, decomposition/static parity 9,
  routing 11, replay guards 7, prompt authority 7, and bootstrap 24.
- Primary reviewed the current source/document contract. Strict source/doc
  verification had already passed. Task 4.8's checkbox is now supported by
  this primary software-only PASS; it was previously checked prematurely.
- The retained individual allied 1-PC `175525` PASS is unchanged. The
  `180820` FAIL and `175906` BLOCKED verdicts remain unchanged; no new live/G3
  PASS is claimed. Tasks 5.3 and 5.4 remain unchecked.
