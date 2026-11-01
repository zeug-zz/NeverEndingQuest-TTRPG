# Spec Delta

## Purpose

Defines the repeated live G5T acceptance gate for commander-planned enemy batches, authored cover, and the optional prefetch sub-gate.

## ADDED Requirements

### Requirement: G5T SHALL use separate named commander scenarios

G5T SHALL add named P1 and P4 commander scenarios in the isolated Capture_Arena ensemble, with a designated Hobgoblin Captain commander, goblins with authored multiattack declarations, and an authored cover feature. Corrected G5T scripts and derived caps SHALL remain stable; existing G1/G3/G4/G5/G5R fixtures, identities, hashes, selectors, and evaluator behavior SHALL remain unchanged.

#### Scenario: G5T fixture starts above self-preservation thresholds
- **WHEN** either named G5T scenario is seeded
- **THEN** the Captain SHALL have 39/39 HP and both Goblin squads SHALL have 7/7 HP
- **AND** Squad B SHALL have its authored half-cover feature on its encounter entry
- **AND** no living enemy SHALL be bloodied or near-death at the first `/end`, so direct flee and surrender SHALL be unavailable
- **AND** any above-bloodied conditional flee SHALL become legal only if the commander selects the withdrawal order

#### Scenario: P1 commander scenario runs
- **WHEN** the named `g5t-commander-p1` scenario is captured
- **THEN** it SHALL exercise one PC party against a commander-led enemy squad
- **AND** it SHALL include an authored cover choice and a subsequent PC attack against a covered target
- **AND** the first `/end` SHALL contain no living bloodied or near-death enemy
- **AND** a bloodied-but-living goblin SHALL be present at the round-2 `/end` under both covered-attack hit and miss branches
- **AND** Acheron SHALL make two legal Extra Attack attack/damage pairs in round 2
- **AND** the Captain SHALL first reach 9/39 HP at the round-6 `/end`
- **AND** Acheron's final Extra Attack strikes SHALL defeat the last survivor
- **AND** a distinct final DM `/end` batch SHALL run the existing combat-exit and XP flow

#### Scenario: P4 commander scenario runs
- **WHEN** the named `g5t-commander-p4` scenario is captured
- **THEN** it SHALL exercise a four-PC party against a commander-led enemy squad
- **AND** it SHALL include an authored cover choice and a subsequent PC attack against a covered target
- **AND** the first `/end` SHALL contain no living bloodied or near-death enemy
- **AND** a bloodied-but-living goblin SHALL be present at the round-3 `/end` under both covered-attack hit and miss branches
- **AND** Acheron SHALL make two legal Extra Attack attack/damage pairs in round 2
- **AND** the Captain SHALL first reach 9/39 HP at the round-4 `/end`
- **AND** if combat remains active after round 4, Merisiel's legal attack SHALL defeat or follow the departure of the remaining Goblin before round-5 `/end`, where the Captain remains at 9/39 HP with individual surrender legal
- **AND** if the Captain does not surrender by round 5, Acheron's final Extra Attack strikes in round 6 SHALL defeat the last survivor
- **AND** a distinct final DM `/end` batch SHALL run the existing combat-exit and XP flow

#### Scenario: Final exit-closing batch is branch-robust
- **WHEN** the final PC attacks have defeated or departed every enemy while the encounter remains active
- **THEN** the script SHALL send a final `/end` as a batch step with its own step identity and round-correlated trace batch ID
- **AND** the final step SHALL not be skipped by target-inactive handling
- **AND** the driver SHALL wait for its `combat_exit_complete` marker before after-run capture
- **AND** if an earlier enemy batch already exited combat, the final step SHALL have a `status=skipped` receipt with `skip_reason=combat_ended` and no command SHALL be sent
- **AND** a skipped final batch SHALL be excluded from commander-batch timing requirements

#### Scenario: G5T derived caps include the final exit-closing batch
- **WHEN** the fixed P1/P4 scripts and capture profiles are constructed
- **THEN** P1 SHALL contain 31 steps and 7 enemy batches, with `max_inputs=max_steps=31` and `max_requests=max_controls=33`
- **AND** P4 SHALL contain 42 steps and 6 enemy batches, with `max_inputs=max_steps=42` and `max_requests=max_controls=57`
- **AND** these G5T corrections SHALL NOT change G1/G3/G4/G5/G5R fixture identities or evaluators

#### Scenario: Existing capture identities remain stable
- **WHEN** G5T tooling is added
- **THEN** the existing P1/P4 action scripts and their fixture identity, step hash, profile contract, and scenario hash SHALL remain byte-compatible
- **AND** G1/G3/G4/G5/G5R selectors and evaluators SHALL retain their existing behavior

### Requirement: G5T commander batches SHALL meet the unchanged absolute targets

With prefetch disabled, each accepted primary G5T batch SHALL stay within two synchronous provider requests and zero combat-validation requests. Each batch SHALL meet the write, latency, and plan-legality targets below. Optional background standing-order requests SHALL be accounted for separately and SHALL NOT change primary acceptance counts.

#### Scenario: Three P1 and P4 runs meet absolute targets
- **WHEN** three G5T captures are completed for each party shape on one final source revision
- **THEN** reports SHALL show each accepted commander batch's plan, narration, and validation request counts
- **AND** reports SHALL show raw per-batch write counts and all three work-only latency observations plus the median for each party shape
- **AND** P1 and P4 medians SHALL each be at most 15000 ms
- **AND** every batch SHALL have at most two provider requests and raw writes SHALL NOT exceed one history write plus one encounter write plus one character write per distinct character whose canonical state changed in that batch
- **AND** every applied plan choice SHALL pass menu legality validation

#### Scenario: Invalid raw choice is contained
- **WHEN** a captured raw plan contains a missing, malformed, or unissued option ID
- **THEN** Python SHALL reject that choice and apply a legal rule-tier default
- **AND** the report SHALL preserve the raw rejection and bounded default reason
- **AND** an invalid raw choice SHALL NOT be treated as a validated applied
  choice
- **AND** if a ledger outcome nevertheless mirrors an accepted choice with an
  unissued option ID, the trace SHALL count the outcome as applied but illegal
  so the legality check fails closed

### Requirement: G5T SHALL capture required commander behavior

The named scenarios SHALL preserve authoritative evidence of commander choices, self-preservation outcomes, and cover behavior as detailed in the scenarios below. The G5T fixture may be corrected before its final capture freeze; corrections may update its derived step hash and caps without changing existing G1/G3/G4/G5/G5R contracts.

#### Scenario: Applied-choice legality is aggregated per batch

- **WHEN** G5T evaluates the per-batch legality observations
- **THEN** a batch with no applied commander choice SHALL be `NOT_APPLICABLE`
- **AND** a rule-tier/no-plan deviation SHALL NOT be blocked solely because its
  legality observation is absent
- **AND** a commander-planned batch with missing or ambiguous application
  evidence SHALL be `BLOCKED`
- **AND** any batch with fewer legal applied choices than applied choices SHALL
  be `FAIL`
- **AND** run status SHALL aggregate batch rows with `FAIL` taking precedence,
  then `BLOCKED`, then `PASS`, and `NOT_APPLICABLE` when no batch applies

#### Scenario: Squad followthrough is aggregated per commander batch

- **WHEN** G5T evaluates `commander_squad_follows_orders`
- **THEN** it SHALL require exactly one bounded squad observation for every
  commander-planned batch
- **AND** all observed `followed_orders=true` batches SHALL aggregate to `PASS`
- **AND** any observed `followed_orders=false` batch SHALL aggregate to `FAIL`
- **AND** missing or ambiguous evidence for a commander-planned batch, or a run
  with no commander-planned batch, SHALL aggregate to `BLOCKED`

#### Scenario: Squad follows its commander plan
- **WHEN** an accepted commander plan selects coordinated legal options
- **THEN** the run evidence SHALL compare the issued menu choices with the applied resolver ledger
- **AND** it SHALL establish that the squad followed the valid plan
- **AND** an accepted non-attack choice replaced by its matching final-ledger outcome, including side surrender projected as actor departures, SHALL count as applied and followed

#### Scenario: Goblin disposition supports an observable flee decision

- **WHEN** a G5T Goblin is scheduled in a commander batch
- **THEN** its bounded actor-scoped cowardly disposition MAY inform its choice to flee
- **AND** the disposition SHALL state that a bloodied Goblin with a direct flee option prefers escape over attacking or taking cover, refers to Nimble Escape, and reserves individual surrender for being cornered or near death
- **AND** the flee menu option SHALL explain that it uses the actor's action to Disengage, prevents an attack that turn, and leaves combat at turn end
- **AND** flee SHALL remain a model choice and SHALL NOT be forced by the fixture
- **AND** under both hit and miss outcomes of the covered-target attack, a Goblin SHALL be alive at 3/7 HP at P1 round 2 and P4 round 3 `/end` decisions

#### Scenario: Acheron uses Extra Attack in one round

- **WHEN** the P1 or P4 G5T script reaches Acheron's designated Extra Attack round
- **THEN** Acheron SHALL receive two separate `/att` and paired `/dmg` opportunities in that same round
- **AND** each damage value SHALL be within the acting PC's declared weapon's non-critical total-damage range
- **AND** skipping damage after the covered-target miss SHALL NOT suppress a later same-PC attack or its independently paired damage

#### Scenario: Near-death commander side may surrender
- **WHEN** an eligible near-death commander side selects the issued surrender option
- **THEN** authoritative encounter evidence SHALL show living side members marked `defeated`
- **AND** the existing combat exit and XP lifecycle SHALL complete without a new status value or movement action
- **AND** the G5T Captain's bounded authored disposition SHALL state that he prefers to yield rather than die pointlessly when near death after his troops have fled or fallen
- **AND** when the Captain is the only eligible enemy actor, the commander-plan prompt SHALL strongly prefer exactly one listed individual or side-level surrender option without forcing that choice
- **AND** Python SHALL continue validating the issued option IDs and SHALL own the surrender outcome
- **AND** no living enemy SHALL be at or below 25% HP at an `/end` before the covered-target attack resolves and at least one subsequent enemy batch runs
- **AND** the Captain SHALL first reach the near-death surrender threshold at P1 round 6 (9/39 HP) or P4 round 4 (9/39 HP)
- **AND** P4 SHALL preserve a second live 9/39 HP surrender opportunity at round-5 `/end`, after the goblins have fled or been defeated and before round-6 final PC strikes

#### Scenario: An observed creature flee leaves combat state coherent
- **WHEN** an eligible creature selects flee
- **THEN** the applied ledger SHALL show its action resolved as Disengage with no attack that turn
- **AND** its final encounter entry SHALL have `status=defeated` and `defeatReason=fled`
- **AND** it SHALL be absent from subsequent actor and target menus while the remaining encounter continues coherently
- **AND** when a later tactical plan result exists, the report SHALL compare its `actor_ids` and `target_ids` against the departed actor
- **AND** when a later batch instead uses the whole-batch fallback, the report MAY establish exclusion from exactly one accepted later `combat_action_batch` cohort, its explicit actor/affected-entity records, the matching accepted `combat_validation_result` for `llm_fallback`, and the persisted defeated encounter entry
- **AND** missing or ambiguous fallback evidence SHALL remain `BLOCKED`
- **AND** any all-enemies-defeated exit and XP processing SHALL use the existing paths unchanged

#### Scenario: A self-preservation batch exits combat

- **WHEN** a flee or surrender outcome in a batch triggers the existing combat
  exit and XP path
- **THEN** evidence SHALL mark that outcome `satisfied_by_exit=true` only when
  the same batch has an `auto_exit` XP observation and the after snapshot has no
  active combat encounter
- **AND** actor and target menu arrays SHALL not be required after that exit

#### Scenario: An observed cover choice affects a later PC attack and expires
- **WHEN** a valid cover option is selected and a later PC attack targets that covered creature
- **THEN** evidence SHALL show the effective AC and attack comparison include the authored cover bonus
- **AND** after the encounter exits, cover SHALL no longer affect subsequent attacks

#### Scenario: Model-chosen tactical outcomes are conditional within a run
- **WHEN** a model-chosen flee, surrender, or cover outcome does not occur during one capture
- **THEN** that outcome SHALL be reported as `NOT_OBSERVED` for the run
- **AND** the run SHALL NOT be `BLOCKED` solely because that conditional outcome was not observed
- **AND** every observed self-preservation and cover instance SHALL be validated, with any invalid observed instance making the run `FAIL`

#### Scenario: Required tactical outcomes are observed across the party-shape runs
- **WHEN** the three captures for a party shape are aggregated
- **THEN** at least one valid observation SHALL exist across those runs for `fled`, `surrendered`, a cover-applied effective-AC attack, and cover expiration/inertness after exit
- **AND** missing shape-level coverage SHALL produce `BLOCKED` with `g5t_outcome_not_observed_across_runs:<item>:p<N>`
- **AND** missing observations SHALL NOT be zero-filled or treated as `PASS`
- **AND** attack effective AC SHALL be substantiated by the scripted covered-target step's authoritative before snapshot and matching after-step backend output

### Requirement: Standing-order prefetch SHALL be an optional separately reported sub-gate

G5T's primary commander acceptance SHALL be measured with prefetch disabled and SHALL retain its limit of at most two synchronous provider requests per accepted commander batch. If the optional standing-order prefetch sub-gate is run, it SHALL report background request counts and outcomes separately from synchronous requests, with no more than two background standing-order requests per batch. Prefetch results SHALL NOT be mixed into or used to waive primary G5T targets.

#### Scenario: Primary G5T is evaluated without prefetch
- **WHEN** the default-off prefetch flag is disabled
- **THEN** the primary G5T result SHALL be evaluated using synchronous commander planning
- **AND** no background standing-order observation SHALL be required for primary PASS

#### Scenario: Optional standing-order prefetch sub-gate is evaluated
- **WHEN** the optional prefetch flag is enabled in isolated captures
- **THEN** initial and re-plan requests SHALL be reported under a distinct background standing-order site/attribution
- **AND** background requests SHALL be counted separately from synchronous requests and SHALL NOT exceed two per batch
- **AND** pending, failed, cancelled, expired, unavailable, and consumed outcomes SHALL be reported separately
- **AND** `/end` SHALL make no synchronous planner request after the standing-order path has been selected
- **AND** the primary G5T verdict SHALL remain separately visible

### Requirement: G5T flags SHALL remain disabled pending primary review

`COMBAT_TACTICAL_BRAIN_ENABLED` and `COMBAT_TACTICAL_PREFETCH_ENABLED` SHALL remain false by default. The tactical brain SHALL also require `DETERMINISTIC_ENEMY_RESOLUTION_ENABLED=true`. Flags SHALL remain off until the primary reviewer records G5T PASS and a separate rollout decision is approved.

#### Scenario: Capture gate is incomplete or fails
- **WHEN** any required G5T scenario, run, behavioral assertion, or absolute target is missing or fails
- **THEN** the verdict SHALL remain FAIL or BLOCKED as appropriate
- **AND** the shipped flags SHALL remain disabled

#### Scenario: G5T passes primary review
- **WHEN** all required G5T evidence is complete and the primary reviewer records PASS
- **THEN** the evidence SHALL support a separate rollout decision
- **AND** the verdict alone SHALL NOT change shipped defaults
