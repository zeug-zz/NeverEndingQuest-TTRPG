# Task 4.5 - Dynamic Validation Context Correction

Status: **Primary verification verdict: PASS — software-only.** This records
primary-supplied verification evidence; it is not a live G3 PASS. The failed
bundles, diagnostic evidence, frozen baseline history, and Task 5.3 report were
not modified.

## Implementation boundary

- `core/combat/combat_manager.py`: candidate updates still select relevant
  committed character records and determine whether inventory context is useful,
  but candidate prose/operations are no longer serialized as `touchedChanges` in
  the authoritative truth pack. Mechanical fields come from Python character
  state.
- `core/combat/validation.py`: labels the truth pack as committed Python state
  and labels the response as an uncommitted candidate. Candidate text,
  operations, `ALREADY_APPLIED`, and `touchedChanges` do not prove application;
  independently established prior applied events remain trusted. No prompt asset
  or unrelated prompt/context content was edited.
- Tests only were expanded in the retry: `scripts/test_combat_truth_pack.py`
  and `scripts/test_combat_validation_stage.py`. No product code changed in the
  retry.

## Guarded truth-pack and payload proof

- `test_combat_truth_pack` arms `ProviderTripwire` and fatal filesystem-write
  guards before reading source or executing the pure-AST-selected actual
  `_build_compact_combat_truth_pack` and its two helper functions. Its isolated
  `utils.pc_manager` fake only returns in-memory records; it does not import or
  read campaign state, instantiate the combat owner, or run the owner loop.
- The actual changed builder is exercised with explicit 1-PC and 4-PC encounter
  rosters, each containing a PC and Blairen. Proposed Acheron HP 20->12 with a
  forged `ALREADY_APPLIED` assertion remains HP 20 (`HP20proposed-8`); independently
  supplied Python state at HP 12 returns 12 (`actualcommitted12`). The
  `updateCharacterInfo` ops-only `hp_delta -8` case keeps committed HP 20 and adds
  no candidate `touchedChanges`. Candidate ammunition prose proposing 99 does not
  replace canonical quantity 3. Candidate, encounter, and all state-record
  dictionaries are deep-equal before/after each builder test.
- The actual validation stage is called with that same AST-selected production
  builder wired into `truth_pack_builder`, in-memory Python state, fake SDK
  client, and fake export/write seams. It captures the actual provider-call
  payload. The test checks committed HP/inventory values, excludes
  `touchedChanges` from the truth-pack JSON, verifies untouched history messages,
  encounter JSON, user input, and candidate raw JSON byte-for-byte, and allows
  only the approved candidate-boundary and committed-state heading/content
  changes. All nine static combat prompt assets are hashed against the frozen
  values in the existing prompt-contract source; the actual payload's prompt
  bytes are checked against its asset bytes.
- The validation test module imports the validation stage under armed provider
  and fatal outside-write guards. The AST-selected builder tests arm those same
  guard classes before source load/exec. Tests use only fake clients and fake
  export/write seams; no real SDK, network, server, campaign file, or owner loop.
- Truth-pack filesystem guards raise a dedicated `BaseException` sentinel from
  `builtins.open`, `io.open`, and `os.open` write hooks. A guard self-test proves
  an ordinary `except Exception` cannot swallow the sentinel and attempts all
  three writes against unique project-relative `tmp/` paths, asserting none of
  the files exists before or after the attempts.
- A separate validation-stage integration uses the actual existing
  `validate_already_applied_enemy_replay_precheck`: candidate-only
  `ALREADY_APPLIED` text without trusted history continues to the fake provider;
  a genuine prior history record for Goblin HP 20->12 rejects duplicate
  `hp_delta -8` before the provider (`replaystillblocked`). Candidate, encounter,
  and authoritative history remain unchanged. No PC receipt/precheck policy was
  added.

## Focused verification

All Python commands used `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1`; Python scratch
and bytecode paths used project-local `TMPDIR=tmp PYTHONPYCACHEPREFIX=tmp/pycache`.
Each suite ran in its own process:

| Suite | Result |
| --- | ---: |
| `scripts.test_combat_truth_pack` | 8 passed |
| `scripts.test_combat_validation_stage` | 10 passed |
| `scripts.test_combat_validation_routing` | 11 passed |
| `scripts.test_combat_phase_integrity_precheck` | 18 passed |
| `scripts.test_combat_runtime_prompt_authority` | 7 passed |
| `scripts.test_combat_resume_replay_guards` | 7 passed |
| `scripts.test_capture_drive` | 34 passed |
| `scripts.test_update_encounter_ops_runtime` | 4 passed |
| `scripts.test_validator_truth_pack` | 5 passed |
| `scripts.test_combat_decomposition_contract` | 9 passed |
| `scripts.test_combat_payload_hygiene` | 4 passed |
| **Total** | **117 passed** |

- `py_compile` passed for `core/combat/combat_manager.py`,
  `core/combat/validation.py`, `scripts/test_combat_truth_pack.py`, and
  `scripts/test_combat_validation_stage.py`.
- After the final guard-only test correction, `scripts.test_combat_truth_pack`
  passed 8 tests and `scripts.test_combat_validation_stage` passed 10 tests in
  separate processes; `py_compile` and scoped diff checks passed again.
- Combat-package AST audit: 261 functions; none exceeds 600 lines.
- ASCII compliance: 1,133 files scanned, zero violations.
- Scoped `git diff --check` passed; strict OpenSpec validation passed with
  `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate
  combat-manager-decomposition --strict`.
- Primary source review confirmed committed Python mechanical state is the only
  truth-pack authority; candidate text remains separate and uncommitted. The
  actual helper-to-validation-stage fake-payload tests cover the candidate-only
  and genuine-replay distinctions, both party sizes, PC/ally, ops-only,
  inventory, and deep no-mutation cases. Candidate-only `ALREADY_APPLIED` is not
  proof; independently established replay remains blocked. All nine frozen
  prompt assets are unchanged. These are primary-supplied software verification
  results, not a claim that the builder reran them.
- No live capture/server, provider call, preparation, owner loop, campaign
  mutation, outside write, or cleanup was run. G3 remains outside this report's
  claim and primary-owned live reruns remain required.
