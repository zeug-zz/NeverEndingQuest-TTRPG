# Task 4.9 - Validation-Context Authority Corrections

Status: primary-reviewed software-only verification **PASS**; Task 4.9 is checked.
No live rerun or G3 verdict was performed.

## Corrections

- Replaced the global prose-name-plus-mutation match with bounded mutation
  clauses and canonical encounter identities. A canonical non-enemy is rejected
  only when a local supported subject/recipient relation establishes its HP,
  condition, or resource mutation. Immediate HP-value continuations bind only to
  an exact canonical-name header or an unambiguous explicit injury recipient;
  misses, multiple possible recipients, and unrelated clauses do not bind.
  Explicit healing `to`/`for` and resource removal `from` relations identify the
  receiver rather than the healer/actor. Unknown or ambiguous prose proceeds to
  existing semantic validation. Structured operation target checks remain strict.
- The two actual rejected descriptions recorded in the `225308` primary review
  now proceed past the deterministic prose-routing check: Goblin's HP clause is
  separate from both Blairen's hit and Goblin's miss against Acheron. Tests retain
  positive rejection for canonical PC HP, explicit damage-to-PC, conditions,
  resources, and a later PC HP clause; they also retain ambiguous-prose deferral
  and typed non-enemy operation rejection. The original review's nested
  `operations: ["[truncated]"]` remains unknown; no operation is inferred from
  it. The original primary `225308` FAIL is unchanged.
- Added a code-only `full_enemy_batch_intent` bit when the validation caller has
  literal `user_input == "Enemies turn."`, manager phase `ENEMY_PHASE`, and
  non-empty pending actors. The phase helper evaluates actor coverage and round
  validity together once. It accepts only exact canonical clause subjects with
  bounded action/miss/hit/strike outcomes, a possessive weapon-attack clause, or
  an NPC-colon `Attack[roll]` declaration. Prefix entities such as `Inactive
  Goblin`/`Fake Goblin`, victim mentions, roster headers, ops, and candidate
  completion flags do not count. Candidate rounds must be integers equal to
  current or legal next; next requires existing PC-phase completion and is
  blocked while the current opening-batch marker is pending. Deferral reaches
  the existing semantic provider, where false feedback remains a rejection.
  Legacy callers without the code-derived flag remain strict. Guard 1, exit,
  replay, other round checks, and structured target rejection remain in place.
- Replaced nested operation objects in the gated rejection observation with at
  most four action-indexed top-level scalar groups. Captured changes are limited
  to 96 characters each and reason to 128; operation scalar strings are limited
  to 16 characters. Counts and truncation fields are retained. The existing
  trace gate remains before payload construction; no prompt, key, provider data,
  or candidate identity is retained.

## Focused evidence

Primary software-only verification passed: 215 tests in 14 separate
provider-free processes. All suites ran with `OPENSPEC_TELEMETRY=0
DO_NOT_TRACK=1`, project-local `TMPDIR=tmp`, and `PYTHONPYCACHEPREFIX=tmp/pycache`:

| Suite | Result |
|---|---:|
| `scripts.test_combat_narration_consistency_precheck` | 13 passed |
| `scripts.test_combat_phase_integrity_precheck` | 23 passed |
| `scripts.test_combat_validation_stage` | 15 passed |
| `scripts.test_combat_validation_routing` | 11 passed |
| `scripts.test_combat_trace_observation_writer` | 2 passed |
| `scripts.test_update_character_ops_contract` | 21 passed |
| `scripts.test_capture_drive` | 48 passed |
| `scripts.test_combat_latency_baseline` | 24 passed |
| `scripts.test_combat_decomposition_contract` | 9 passed |
| `scripts.test_combat_runtime_prompt_authority` | 7 passed |
| `scripts.test_combat_resume_replay_guards` | 7 passed |
| `scripts.test_combat_canonical_validation_facts` | 3 passed |
| `scripts.test_combat_validation_truth_pack` | 8 passed |
| `scripts.test_combat_bootstrap` | 24 passed |

Canonical clause identity and recipient resolution distinguish an attack victim
from the canonical mutation subject/recipient, including the reported
Blairen-hit/Goblin-miss cohort and the second Goblin possessive-miss form. The
narrow prospective complete NPC-batch qualification requires the exact
code-owned `Enemies turn.` input seam, canonical actor coverage, and permitted
round/handoff state; it only defers to mandatory full semantic validation. The
actual validation stage with a fake provider proves this path is called and its
false feedback is honored. Partial, prefix-invented, victim-only, invalid-round,
skipped-actor, premature-PC-action, and false-completion candidates remain
negative coverage; Guard 1 and genuine PC/allied HP, condition, and resource
mutation rejections remain strict.

The real-writer regression invokes the actual validation stage and actual JSONL
writer, reads the file back, and verifies exact action-indexed top-level scalar
operation fields (including operation, target/creature `Goblin`, and `hp_delta`
`-7`), bounded adversarial-Unicode changes/reason and operation values, counts
and truncation flags, and byte length under 8192. Character JSON fixture bytes
are unchanged; trace-off coverage asserts no writer call. The primary reported
`225308` FAIL remains unchanged. 300-second named-case exceptions, default bare
150-second bound, all 18 G3 strict-rejection keys, and Tasks 5.3/5.4 were not
changed.

Strict OpenSpec validation and scoped `git diff --check` passed. No live server,
real SDK/provider, owner loop, fixture preparation, campaign/key access, cleanup,
or primary-owned evidence mutation was performed. Tasks 5.3 and 5.4 remain
unchecked; no live/G3 PASS is claimed.
