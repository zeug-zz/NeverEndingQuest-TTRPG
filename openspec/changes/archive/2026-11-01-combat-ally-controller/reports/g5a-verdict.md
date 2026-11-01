# G5A Primary Verdict

**Verdict: PASS**

The primary independently reviewed all six capture bundles and their checks, before/after snapshots, and traces. The three P1 runs (`g5am8-p1-r1`, `g5am8-p1-r2`, `g5am8-p1-r3`) and three P4 runs (`g5am8-p4-r1`, `g5am8-p4-r2`, `g5am8-p4-r3`) share source digest `528087409ddd03e78ae0e0d6b0fad545a7fc0c1d4cb94a9dbdedb333ed71cf6e` and source head `07df20b10f9e6f31d6a01976fcb5ec6fa5d82afe`. The readiness matrix at `tmp/router-rollout/g5a/g5am8-matrix.json` reports all six runs ready with no blockers; the primary verdict is based on the independent review, not readiness alone.

Across the runs, the primary verified exact party rosters (1/4), round progression 1 to 2, one receipt, and one applied legal authored `take_cover` per party shape at `ca02-ally-shield-racks`, changing from no cover to half cover. The applied action was non-default and legal; directive hash and re-plan were evidenced. The traces showed two background requests initially and on re-plan, one sync narration, and narration deferred until preflight succeeds. P1 input/control counts were 4/6 with elapsed times 48.1s, 22.4s, and 29.0s; P4 counts were 10/17 with elapsed times 77.1s, 68.2s, and 86.3s. There were no timeouts or caps. Transport was OpenRouter; observed resolved models included `deepseek/deepseek-v4-flash-0731`, `openai/gpt-6-luna`, and `z-ai/glm-5.3-flash`. No raw logs are reproduced here.

Earlier attempts m1-m7 remain preserved as failed or blocked evidence and were not accepted or counted. The corrections carried into the passing evidence addressed prompt schema, seeded prefetch/completion attribution, cover traces and persisted proof, narration deferral before preflight, the 40 HP fixture, aggregate spec alignment, and per-step HP proof.

The owned port-8360 server was stopped; the capture sandbox was removed, the installed tree remained unchanged, and no port-8360 listener remains. Controller and prefetch defaults are off.

## Final Integration Verification (Task 6.1)

The clean final rerun completed **87 separate Python test processes: 1,633 tests, 0 failures, 0 skips**. Per-process results are preserved at `tmp/router-rollout/g5a/final/baseline-rerun-results.json`. Each process used the focused-test invocation prefix below, with one test module substituted per process:

```sh
PYTHONPATH=. PYTHONPYCACHEPREFIX=tmp/router-rollout/g5a/pycache .venv/bin/python -B -m unittest -q <test-module>
```

Verification results:

- All 237 changed Python files compiled successfully (`.venv/bin/python -m py_compile` over the changed Python files).
- ASCII compliance passed: 878 files checked, 0 issues (`.venv/bin/python scripts/check_ascii_compliance.py --summary-only`).
- Strict OpenSpec validation passed: `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate combat-ally-controller --strict`.
- Whitespace validation passed: `git diff --check`.
- All nine legacy prompt hashes and G1/G3(50)/G4/G5R golden guards passed. G5T Gate10 JSON and text output were byte-identical.
- `tmp/router-rollout/g5a/g5am8-matrix-final.json` reports READY with zero blockers, from the same source after teardown.

The test-only harness/profile corrections were made before this clean rerun; no implementation behavior was changed by those corrections. The sandbox is absent and no port-8360 listener remains.

## Scope Resolution

Per approved owner direction, `combat-absent-pc-autopilot` is subsumed by the ally controller. Converting a PC to an allied NPC or handing over an absent player's character, and PC/NPC character-sheet conversion, remain out of scope. No separate autopilot runtime, scaffold, or gate is required. Dodge and spatial defensive mechanics are excluded.
