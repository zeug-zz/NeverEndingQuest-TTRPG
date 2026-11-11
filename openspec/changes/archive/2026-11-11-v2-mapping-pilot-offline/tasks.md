# Tasks

## 1. Routed live-client adapter

- [x] 1.1 Add `scripts/mapping_pilot/live_client.py` and `scripts/test_mapping_pilot_live_client.py`; wrap the existing router call and receipt observer behind the cartographer's injected client signature, retain allowlisted per-attempt route/usage/error fields with unknowns explicit, and return JSON text without recording prompts or raw responses in receipt metadata. Verify production-auto preflight and error/quota receipt behavior with a fake router and no provider access. Run `.venv/bin/python scripts/test_mapping_pilot_live_client.py`.

## 2. Deterministic D1 selection

- [x] 2.1 Add `scripts/mapping_pilot/d1_selection.py` and `scripts/test_mapping_pilot_d1_selection.py`; implement the fixed module quotas and authored-`areaType` sorted-ID round robin, then atomically write a run-local selection record with commit and per-location source paths/SHA-256 values before any provider call. Verify repeatable ordering, 7/6/7 counts, provenance, missing-type/insufficient-quota refusal, and no partial record on refusal. Run `.venv/bin/python scripts/test_mapping_pilot_d1_selection.py`.

## 3. Selection-gated D1 run CLI

- [x] 3.1 Add `scripts/mapping_pilot/d1_run.py` and `scripts/test_mapping_pilot_d1_run.py`; require and verify the run-local selection record and source hashes before client construction, enforce the existing 60 cartographer-invocation cap, attach router receipts to each invocation, and constrain all output to `tmp/router-rollout/mapping-pilot/d1/<run-id>/`. Finalize the audit sheet with available feature, exit-side, and explicit visibility/perceivability/sightline claims, the 85%/zero-invented-exits threshold, and blank owner fields. Verify missing/stale selection refusal before the fake client is called, cap refusal at 60, error-slot accounting, receipt/audit contents, resumable same-selection evidence, and no writes under `modules/`. Run `.venv/bin/python scripts/test_mapping_pilot_d1_run.py`.

## 4. M1 sketch and owner-sheet packet

- [x] 4.1 Add `scripts/mapping_pilot/m1_packet.py` and `scripts/test_mapping_pilot_m1_packet.py`; render the four frozen fixtures, fixture-defined P1/P4 viewpoints, and validated D1 layouts, then write the deterministic run manifest and blank 1-5 legibility/usefulness sheet under `tmp/router-rollout/mapping-pilot/m1/<run-id>/`. Verify combat P1/P4 variants, omission of invalid D1 layouts, the 3.5 thresholds, partial-blinding disclosure, blank ratings, manifest hashes, and refusal to overwrite a run. Run `.venv/bin/python scripts/test_mapping_pilot_m1_packet.py`.

## 5. ORCHESTRATOR-OWNED final verification and evidence run

- [x] 5.1 ORCHESTRATOR-OWNED: after Tasks 1-4 pass, the primary/orchestrator runs `.venv/bin/python -m unittest discover -s scripts -p 'test_mapping_pilot_*.py'`, `python3 scripts/check_ascii_compliance.py --summary-only`, and `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-mapping-pilot-offline --strict`; review `git status --short` and `git diff --name-only` (including untracked paths) to verify the boundary is limited to this change, `scripts/mapping_pilot/`, its focused tests, and the two specified `tmp/` evidence roots. Only after those gates pass, the primary creates the D1 selection record before any provider call, runs the live D1 pass through the selection-gated CLI with no more than 60 client invocations, and generates the M1 packet from its validated layouts. Verify run IDs, source hashes/commit, every available router receipt, cap counts, artifact hashes and path containment, blank owner fields, and no changes under `modules/`; builders and tests MUST NOT run the live pass or make provider calls.
