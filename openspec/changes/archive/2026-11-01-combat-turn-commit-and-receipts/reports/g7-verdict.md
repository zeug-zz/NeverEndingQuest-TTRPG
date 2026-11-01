# G7 Primary Verdict

Current status: PASS

## Primary adjudication

The primary orchestrator adjudicated the live G7 gate PASS after reviewing the preserved evidence. This is the primary's judgment, not an independent builder judgment. The evaluator status `READY_FOR_PRIMARY_REVIEW` was treated as readiness input only, not as the verdict.

The capture set contains 29 live pairs / 58 bundles across P1 and P4, normal and enemy-batch turns, completed-turn/replay cases, and all approved interruption boundaries. All 25 expected stop points were observed, alongside four complete/replay pairs. The P4 `after_character_write:2` case is normal-path only, as required by D8; it is not expected for enemy-batch. There were no timeouts or caps, all bundles had the same captured source identity, and the evaluator reports no missing, extra, duplicate, or pair-failure keys.

The primary independently compared each interrupt-after projection with its recover-before projection, and each replay before/after projection; no discrepancies were found. The actual P4 r17 recovery snapshot confirms shared `applied_id` and persisted level-3 slot/HP effects. Traces and manifests establish receipt identity, projections, publication, and absence of duplicate effects as reported by the evaluator and reviewed in the preserved run evidence.

## Method and expected/observed

Runs used real isolated Capture_Arena copies under `tmp/combat_capture/`, port 8360, `NEQ_OPEN_BROWSER=0`, and the repository virtual environment. Restarts retained sandbox state without reseeding. Expected coverage was both party shapes, both turn paths, completed-turn replay, and each approved stop boundary; observed coverage is represented by the 29-row manifest and corresponding paired bundles. D8's sole second-character-write boundary is P4 normal only.

The primary's mechanical-projection comparisons found no interrupt/recovery or replay discrepancies. Receipt/applied-ID identity remained consistent; no duplicate HP, resource, enemy, or reward effects were observed. The P4 r17 snapshot provided direct recovery-state confirmation of the shared ID and level-3 slot/HP effects.

## Evidence and limits

- `tmp/router-rollout/g7/g7m5-rows.txt` maps all 29 captures to their retained run IDs and party/path/boundary identity.
- Each mapped bundle is retained under `tmp/router-rollout/g7/<run-id>/`, including the run's manifests, trace, and applicable state/projection artifacts.
- `tmp/router-rollout/g7/g7m5-eval.json` records `READY_FOR_PRIMARY_REVIEW`, zero missing/extra/duplicate/pair-failure keys, and no synthetic keys. Its readiness status alone does not establish PASS; the primary's manual comparisons and snapshot review above complete the adjudication.
- The verdict is limited to the reviewed G7 capture set and its recorded source identity; it is not a claim of exactly-once external notification delivery.

## Commands

The primary's supplied adjudication identifies the capture setup and review outcomes above; no capture command transcript was included in the reviewed inputs, and no live captures were run by this builder. OpenSpec validation was run after recording the verdict:

```sh
OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-turn-commit-and-receipts --strict
```
