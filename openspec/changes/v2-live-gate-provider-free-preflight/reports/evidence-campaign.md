# FR11 campaign evidence reconciliation

## Ruling

**BLOCKED; no booking and no live-gate PASS. FR11 is not complete.** The
campaign artifacts below are bounded startup observations, not full-row
integration evidence. No evidence establishes booking eligibility for any row.
Tasks 2.1, 3.1, and 4.1 remain unchecked.

## Resume prerequisites

`fr11-resume-prerequisites/preflight/checkpoints.json` records all eight
prerequisites as `BLOCKED` with reason `resume checkpoint identity is invalid`.
Every result has `host_started: false`; scope explicitly excludes host, lock,
and provider. No checkpoint moved. These results are not lifecycle call
measurements.

## Bounded startup observations

Each listed profile-evidence file records a completed startup exchange and its
observed router call count. The first three are bound to source
`ff0e7bd78bdf895b15db160c85811284de1af53d`, **not**
`58ab23336d7dcc521e5ec9d8774c6dae8a002b25`. The remaining five are bound to
`58ab23336d7dcc521e5ec9d8774c6dae8a002b25`. This is source identity from the
evidence itself; it does not establish portability or row coverage.

| Run / row | Fixture / party | Lifecycle calls | Evidence SHA-256 | Teardown recorded |
| --- | --- | ---: | --- | --- |
| `fr11-campaign-e07-start-02` / E07 | `interior_tavern` / 4 | startup 9 | `dddb5f9924ce5b3ec7fc74e410b44fd8d800a21a3fdb3588822fb7ba6187ed8a` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-e13-start-01` / E13 | `landscape_village` / 4 | startup 9 | `f32e12bc24c8bf3a5f850c68f1805da163345340e36611ac87b544b009419ae9` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-tower4-start-01` / E13 | `transition_tower_approach` / 4 | startup 9 | `38a859a71b5603f071f61ecdeacaa843ca90c7bc127570a15730247f367329ae` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-c01-start-02` / C01 | `combat_stage_tavern_zones` / 1 | startup 2 | `8b32ca745a7e6e6f3e3cf1df863a3f14b31d9a19785f49a05be6ecfda59461f8` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-c05-start-01` / C05 | `combat_stage_tavern_zones` / 4 | startup 2 | `42f921b8ef828f3e60430b9482f0a7526f7ee0fc89113a6d39fc98d39dc8bd4a` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-e01-start-01` / E01 | `interior_tavern` / 1 | startup 9 | `7387a196a26903fa9a9293a966c35f5fa616a3a35522296f14f56226b4d83fc3` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-e04-start-01` / E04 | `landscape_village` / 1 | startup 9 | `c6064eb47f42c822d9ac567179ab12465ae558323d825de892733ca8e1a7502f` | server stopped; lock released; 8360/8370 free |
| `fr11-campaign-tower1-start-01` / E04 | `transition_tower_approach` / 1 | startup 9 | `a58af9438841ed57c163f29d36fe64f2e2f43c1e59c114c8cfc41ce965df4669` | server stopped; lock released; 8360/8370 free |

For each row, the evidence path is
`tmp/router-rollout/live-gate-preflight/<run>/preflight/rows/<profile-run-id>/profile-evidence.json`,
where `<profile-run-id>` is `pf-<run>-<row>`. Counts are observed startup
calls only. No declared startup/resume profile is established, and no resume
call count is established by these files.

## Required frozen-row census

The frozen plan has 26 rows. **Every row's coverage status is MISSING**: pair
sampling or a successful startup exchange does not imply coverage of another
row.

| Fixture / party | Planned row IDs | Coverage |
| --- | --- | --- |
| `interior_tavern` / 1 | E01, E02, E03 | MISSING |
| `interior_tavern` / 4 | E07, E08, E09, E10, E11, E12 | MISSING |
| `landscape_village` / 1 | E04, E05, E06 | MISSING |
| `landscape_village` / 4 | E13, E14, E15, E16, E17, E18 | MISSING |
| `transition_tower_approach` / 1 | E04, E05, E06 | MISSING |
| `transition_tower_approach` / 4 | E13, E14, E15, E16, E17, E18 | MISSING |
| `combat_stage_tavern_zones` / 1 | C01, C02, C03, C04 | MISSING |
| `combat_stage_tavern_zones` / 4 | C05, C06, C07, C08 | MISSING |

The four replacement-only reserves remain unactivated. The complete 26-row
scripted host path was not run.

## Driver proof and comparison

`fr11-pf6-driver-proof/preflight/driver-proof.json` reports two passing
fault-injection tests against guarded actual driver source lines
`scripts/mapping_pilot/execution.py:709-710` and
`scripts/mapping_pilot/scoring.py:91,101`, at source
`58ab23336d7dcc521e5ec9d8774c6dae8a002b25`. It proves injected attempt/time
caps and three-failure pause only. Its scope says “not a host run”; upstream
provider request count is explicitly `not_observed_by_this_trace`. This is not
PF6 integration PASS.

`fr11-comparison-attempt-01/preflight/comparator-output.json` is BLOCKED:
comparison is unverified, host execution and guarded per-source reconciliation
are MISSING, with `lifecycle_profile_measurements_missing`. It records no
pilot evidence. The old checkout identity is clean
`5999af374ded4f56b21b25d68fc10f9520444b51`; frozen main is
`f4f49b9ddece4adea10b7bdb4db9a1358b208b0d`. There were no real per-source
executions. The app/tooling dual-identity boundary remains unresolved.

Accordingly, all booking eligibility is **unverified/MISSING**. This report
records neither FR11 completion nor authorization to book or run a live gate.
