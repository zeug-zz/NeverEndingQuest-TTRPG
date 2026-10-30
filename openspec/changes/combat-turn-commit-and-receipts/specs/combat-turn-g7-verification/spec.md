# Spec Delta

## Purpose

Defines the software compatibility and live-evidence contract for Gate G7 across one-PC and four-PC combat parties.

## ADDED Requirements

### Requirement: G7 SHALL Verify Both Party Shapes and Every Commit Boundary

G7 acceptance SHALL cover one-PC and four-PC completed-turn replay plus controlled interruptions at character writes, the encounter-last write, post-commit phase synchronization, and success publication. Each restart SHALL use retained sandbox state without reseeding.

#### Scenario: G7 exercises the required party and interruption matrix
- **WHEN** the primary runs G7 after focused software checks pass
- **THEN** evidence SHALL include both party shapes, completed-turn replay, and every approved interruption boundary
- **AND** before/after snapshots SHALL prove receipt identity and no duplicate HP, resource, enemy, or reward effects

### Requirement: Provider-Free Restart Checks SHALL Exercise Bootstrap Manifest Recovery

Pre-receipt restart checks SHALL use actual combat bootstrap / `start_game` recovery from persisted history manifests for both party shapes. They SHALL NOT simulate recovery by manually reusing a `turn_id` and SHALL preserve provider-free behavior, prompt hashes, and G5T raw write counts.

#### Scenario: Provider-free restart tests recover pending manifests through bootstrap
- **GIVEN** a pre-receipt interruption is prepared for one-PC or four-PC combat with a valid persisted manifest
- **WHEN** the provider-free restart test starts combat through `start_game`
- **THEN** it SHALL recover from the manifest without a provider call, re-planning, regeneration, or manual `turn_id` reuse
- **AND** it SHALL verify stored narration publication under the original `applied_id`, unchanged prompt hashes, and unchanged G5T write counts

### Requirement: G7 Enemy-Batch Fixture IDs SHALL Cover Reachable Initiative Orders

G7 enemy-batch fixtures SHALL preserve the existing PC and goblin initiative inputs. Candidate encounter IDs SHALL be validated through the production manager/planner against every distinct reachable runtime order; each order SHALL yield an accepted batch with a damaging hit to exactly one PC. P4 target identity MAY vary and SHALL NOT be statically pinned.

#### Scenario: Enemy-batch initiative inputs are preserved without synthetic values
- **GIVEN** the existing inputs are P1 Acheron 18, P4 Acheron 20/Merisiel 18/Kira 16/Vitreol 14, and goblins 10/8
- **WHEN** the production initiative manager and deterministic planner enumerate reachable P1/P4 orders
- **THEN** every selected fixture batch SHALL be accepted and hit exactly one PC in every order
- **AND** the selected IDs SHALL be `turn_commit_p1_002` and `turn_commit_p4_130`
- **AND** no synthetic initiative or static P4 target expectation SHALL be introduced

### Requirement: The P4 Second Character-Write Boundary SHALL Be Normal-Path Only

P4 `after_character_write:2` SHALL be required for normal turns only, rejected for enemy-batch captures, and absent from the enemy-batch required matrix.

#### Scenario: The second character-write boundary is path-specific
- **WHEN** G7 validates a P4 normal boundary at `after_character_write:2`
- **THEN** the boundary SHALL remain required
- **WHEN** G7 validates a P4 enemy-batch boundary at `after_character_write:2`
- **THEN** the profile SHALL be rejected and no such matrix key SHALL be required

### Requirement: Enemy-Batch Recovery SHALL Use the Interrupt Manifest Target

Enemy-batch recovery SHALL derive its expected PC from the persisted interrupt manifest and require that one rostered PC alone to change. Receipt, applied-ID, and duplicate-effect checks SHALL remain in force.

#### Scenario: P4 enemy-batch target is resolved from the retained interrupt manifest
- **GIVEN** an interrupt run persisted one enemy-batch character effect for a rostered PC
- **WHEN** the paired recovery run resumes the same manifest
- **THEN** the recovery SHALL preserve that same single target and no other party character may change
- **AND** the receipt and applied-ID marker SHALL remain unique for the turn

### Requirement: G7 Live Verdict SHALL Be Primary-Owned

Only the primary orchestrator SHALL assign G7 `PASS`, `FAIL`, or `BLOCKED` after reviewing complete live evidence. Builder reports, provider-free tests, and driver exit status SHALL NOT constitute a live verdict.

#### Scenario: A required live observation or artifact is missing
- **WHEN** any party shape, interruption case, restart, or required evidence is missing or degraded
- **THEN** G7 SHALL remain `BLOCKED` or `FAIL` according to the observed condition
- **AND** no missing boundary SHALL be silently waived

#### Scenario: All live evidence is present
- **WHEN** the primary reviews the complete required evidence bundle and every assertion passes
- **THEN** the primary SHALL record the G7 verdict and evidence references in the owning change
- **AND** automated readiness SHALL NOT mark the gate complete

### Requirement: G7 Capture SHALL Use the Isolated Arena and Preserve Evidence

Live G7 runs SHALL use a real sandbox copy under `tmp/combat_capture/`, port `8360`, `NEQ_OPEN_BROWSER=0`, and the repository virtual environment. Each unique run's evidence SHALL be retained under `tmp/router-rollout/g7/<run-id>/`; the installed campaign and port `8357` SHALL NOT be used.

#### Scenario: A live G7 run is prepared and retained
- **WHEN** the primary executes a G7 row
- **THEN** it SHALL record the party shape, scenario and seed identity, source/worktree identity, model/provider identity, injection point, expected and observed checks, and artifact paths
- **AND** it SHALL preserve the transcript, server log, trace, and relevant before/after character, encounter, history, and receipt snapshots before teardown

### Requirement: Compatibility Goldens and Legacy Prompt Hashes SHALL Remain Unchanged

Provider-free G7 checks SHALL preserve the existing G1, G3, G4, and G5R compatibility goldens and all nine legacy combat prompt SHA-256 values. G7 SHALL NOT replace historical baselines, alter G5R targets, or change prompt bytes.

#### Scenario: Provider-free compatibility guards run
- **WHEN** the focused pre-capture compatibility suites run
- **THEN** the existing G1/G3/G4/G5R golden assertions SHALL remain unchanged and pass
- **AND** `scripts/test_combat_decomposition_contract.py` SHALL verify all nine legacy prompt hashes byte-for-byte
