# Task 4.6 - Canonical Non-PC Validation Facts

Status: **Primary software verification PASS.** The primary-owned `172935` bundle
remains FAIL. No live rerun, G3 PASS, or acceptance waiver is claimed.

## Implementation boundary

- `core/combat/combat_manager.py` adds the owner-private
  `_build_canonical_non_pc_attack_facts` projection and wires it as a distinct
  validation dependency. It reads the current module name from the existing
  `party_tracker.json` source, constructs the existing `ModulePathManager`,
  loads enemy templates by `monsterType` through `get_monster_path` and
  `safe_json_load`, and loads NPC templates through the existing
  `load_npc_with_fuzzy_match` path. NPC results are accepted only when the
  returned canonical `name` exactly matches the encounter identity; enemy
  template identity must match the requested `monsterType`. Identity failures
  remain `stale_or_mismatched` or `unknown`.
- Enemy facts are read from the monster template's canonical `actions` field,
  matching the existing preroll source shape; NPC facts are read from the
  character template's `attacksAndSpellcasting` field. The payload identifies
  that actual source field and never labels monster actions as character
  `attacksAndSpellcasting`.
- Canonical output is bounded to 32 non-PC encounter entries, 8 source attack
  records per entry, 80-character actor/source identities, 120-character
  source filenames, 240-character text fields, and the attack/stat fields
  `attackBonus`, `name`, `damageDice`, `damageBonus`, `damageType`, `type`,
  `description`, `range`, and `reach`. `attackBonus` and `damageBonus` are
  source-backed only when finite, non-boolean numbers; malformed strings,
  booleans, NaN/infinite numbers, and objects are omitted and marked unknown.
  No bonus, attack, or damage default is introduced. A failed party-tracker
  read leaves module provenance explicitly `unknown`.
- Each record carries actor name/type/eligibility and source module, source
  identity, basename provenance, and status. Defeated/dead/inactive or zero-HP
  actors are explicitly ineligible while their source facts remain separately
  visible. Missing and malformed individual fields are labelled
  `unknown_missing` / `unknown_malformed`; unavailable, invalid, or mismatched
  templates do not contribute mechanics.
- `core/combat/validation.py` adds a distinct source-facts section to the actual
  validation request. It remains separate from committed Python truth-pack
  state and the uncommitted candidate. Candidate/preroll text is not an input to
  the projection. The dynamic-size/compression decision preview was deliberately
  left unchanged, so the addition does not change compression routing or retry
  behavior. The legacy validation callback signature and prompt assets are
  unchanged.
- The unchanged validation callback does not expose clean startup generation
  maps. To avoid callsite/callback churn or a global cache, the owner uses the
  existing canonical NPC/monster loader paths for this validation-only read.
  The source module remains the module named by the existing party-tracker
  loader contract.

## Guarded coverage

`scripts/test_combat_canonical_validation_facts.py` arms the provider tripwire
and fatal outside-write guards before AST-selecting the production projection.
Fake module paths, safe JSON reads, NPC reads, and a fake validation client feed
the canonical Goblin `actions` shape (Scimitar and Shortbow, each +4 / 1d6 / +2)
and Blairen `attacksAndSpellcasting` shape (+3 / 1d8 / +1) through the actual
production projection and actual validation stage to the captured fake
validation payload. Coverage includes 1-PC and 4-PC rosters, ally/enemy
identity, source-backed attack and damage modifiers, missing source,
mismatched/stale identity, malformed attack data and numeric modifiers, failed
party-tracker reads, inactive-enemy eligibility, candidate non-authority, and
deep equality of source/encounter/candidate data before and after. Existing validation-stage
coverage retains the legacy callback/patch behavior and Task 4.5 committed-state
and replay checks. Runtime prompt-authority/decomposition suites retain frozen
asset and generation-byte parity checks.

## Verification performed by this builder

All Python tests used separate processes with `OPENSPEC_TELEMETRY=0`,
`DO_NOT_TRACK=1`, `TMPDIR=tmp`, `PYTHONPYCACHEPREFIX=tmp/pycache`, and
`PYTHONPATH=.`.

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
| `scripts.test_combat_canonical_validation_facts` | 3 passed |
| `scripts.test_combat_bootstrap` | 24 passed |

- `py_compile` passed for the owner, validation stage, and focused test modules.
- ASCII compliance scanned 1,134 files with zero violations.
- `openspec validate combat-manager-decomposition --strict` passed.
- No full combat owner loop, live server, API/provider call, campaign state,
  installed campaign, preparation, or G3 rerun was used. `172935` remains FAIL.

## Primary software verification

Primary reviewed the corrected canonical sources: enemy `actions` and NPC
`attacksAndSpellcasting`, using the same existing canonical paths with strict
identity/provenance, finite numeric fields, and explicit unknowns. Candidate
data cannot override source facts; the projection is transient and does not
mutate state. The legacy callback shape is unchanged; only validation context
was added. Primary ran 144 tests in 13 separate processes (canonical 3, truth 8,
stage 10, bootstrap 24, routing 11, phase 18, prompt authority 7, replay 7,
capture 34, encounter 4, validator truth 5, decomposition 9, hygiene 4); strict
OpenSpec validation and scoped diff check passed. Task 4.5 remains checked;
Tasks 5.3 and 5.4 remain unchecked. The `172935` bundle remains FAIL, and no
G3/live PASS is claimed.
