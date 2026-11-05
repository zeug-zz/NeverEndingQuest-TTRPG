# Offline verification report

This is partial offline evidence only and does not establish the N0 live
transport gate.

## Final closeout checks (2026-11-05)

- `.venv/bin/python scripts/test_network_spike_fixture.py` -> Ran 11 tests OK.
- `tmp/n0/.venv/bin/python scripts/network_spike/n0_driver.py --self-test > tmp/n0/n0-final-self-test.txt` -> exit 0; 62 PASS entries, 0 FAIL entries. Three test names are duplicated; these are not 62 distinct tests.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> scanned 807 files, 0 violations.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-network-transport-feasibility --strict` -> valid.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate --specs` -> 467 passed, 0 failed (existing warnings).
- `pre-commit run bandit --files scripts/network_spike/fixture_auth.py scripts/network_spike/fixture_server.py scripts/network_spike/n0_driver.py` -> Passed.
- `gitleaks dir scripts/network_spike --no-banner --redact --exit-code 1` -> no leaks found.
- `tmp/n0/audit/.venv/bin/python -m pip_audit -r scripts/network_spike/requirements-spike.txt --strict --progress-spinner off` -> No known vulnerabilities found.
- `git diff --check` -> exit 0 (untracked-files caveat).
- Latest Semgrep runtime-patch artifact remains `tmp/n0/semgrep/network_spike-runtime-patch.json`: 9 targets, 12 triaged findings, 0 errors (`--metrics=off --timeout 0`). Findings were reviewed; this is not a zero-findings result. CI remains authoritative and was not run here.

## Driver and fixture checks

- `tmp/n0/.venv/bin/python scripts/network_spike/n0_driver.py --self-test` ->
  62 PASS, 0 FAIL. Runtime-override/probe check names appear twice; this is not
  62 distinct tests.
  Previous named checks included `redaction`, `url_rejects_userinfo`, `url_rejects_evil_suffix`,
  `url_rejects_query`, `url_rejects_fragment`, `url_rejects_path`,
  `url_accepts_canonical_https`, `url_parser_sample_bounded`,
  `child_environment_allowlist`, `missing_url_after_start_fails_cleanup`,
  `checksum_mismatch_no_extract`, `isolated_home_xdg_and_temp_paths`,
  `failed_declarative_serve_blocks_and_cleans_profile`,
  `redaction_precedes_log_truncation`, `bounded_process_output_and_logs`,
  `evidence_schema_missing_required_check`,
  `cleanup_exception_forces_fail_and_retains_pids`.
- `.venv/bin/python scripts/test_network_spike_fixture.py` -> Ran 11 tests OK.
- `.venv/bin/python -m py_compile scripts/network_spike/n0_driver.py` -> exit 0.
- `tmp/n0/local-smoke/smoke-orch.out` -> 22 PASS, 0 FAIL. Orchestrator
  verified SIGTERM exit 143 after 3.18s (uvicorn re-raised the signal after
  `Application shutdown complete`), SIGINT exit 0 after 0.19s, port 8370
  released after each, and `--host 0.0.0.0` exit 2. This was local-only and
  inert, not an N0 internet PASS; no real game runtime or browser-cookie
  semantics were tested.

## Security and repository checks

- `gitleaks dir scripts/network_spike --no-banner --redact --exit-code 1` -> no
  leaks found (~322619 bytes scanned; included pycache, so the scan volume is
  not a substantive result size).
- `pre-commit run bandit --files scripts/network_spike/n0_driver.py` -> Passed (repository hook `-ll` threshold). Standalone builder Bandit found LOW findings, not a hook failure; no MEDIUM/HIGH findings.
- `tmp/n0/audit/.venv/bin/python -m pip_audit -r scripts/network_spike/requirements-spike.txt --strict --progress-spinner off` -> No known vulnerabilities found, exit 0; artifact `tmp/n0/pip-audit.txt`. Product requirements were not changed; this audits the spike only.
- `python3 scripts/check_ascii_compliance.py --summary-only` -> scanned 807 files, 0 violations.
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate --specs` -> 467 passed, 0 failed (existing warnings).
- `OPENSPEC_TELEMETRY=0 DO_NOT_TRACK=1 openspec validate v2-network-transport-feasibility --strict` -> valid.

## Semgrep (local, CI rule packs)

- Prior full current-then-code scan used `--timeout 0`, output `tmp/n0/semgrep/network_spike-t0.json`: 9 targets, 6 triaged findings, 0 errors, exit 0. This is historical and superseded by the fresh runtime-patch scan below.
- Fresh runtime-patch scan used the CI rule packs `p/flask`, `p/bandit`, `p/python`, and `p/secrets`, with `--metrics=off --disable-version-check --timeout 0`; XDG config/cache and `SEMGREP_SETTINGS_FILE`, `SEMGREP_LOG_FILE`, and `SEMGREP_VERSION_CACHE_PATH` were directed under `tmp/n0/semgrep/`. Artifact: `tmp/n0/semgrep/network_spike-runtime-patch.json`. Exit 0: 9 targets, 12 findings, 0 errors.
- Primary review inspected every finding: 9 `insecure-file-permissions` findings are explicit `0700` owner-only tightening; 1 is the deliberately `0750` wrong-mode negative-test fixture under disposable `tmp/n0`; `B404` is subprocess-import informational; and `dangerous-subprocess-use-tainted-env-args` is the `nono why` call, using list arguments, no shell, and fixed arguments. These were reviewed, not suppressed; no code changes or scan bypasses were made. CI remains authoritative.

## N0 status and boundaries

Current HEAD: `5519e87facc568fb4cac7e5c571300145dcfabfd`; branch:
`feature/v2-network`. Relevant worktree files are untracked. Linux owner runs
blocked after identity minting; see `../n0-verdict.md`. No real campaign or
gameplay was started. N0 has NOT passed.
