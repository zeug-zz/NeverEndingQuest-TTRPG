## 1. Adaptation Gate Integration

- [x] 1.1 Apply the existing `_maybe_relax_toolkit_media_only_gameplay_gate()` policy to the extracted gameplay payload in `run_adaptation_gate_composer()` before normalization, without changing non-adaptation readiness behavior.
- [x] 1.2 Update adaptation gate normalization to preserve a nonzero raw gameplay exit code as telemetry while honoring only the explicit `manual_handoff_only` passing result.

## 2. Regression Coverage

- [x] 2.1 Add provider-free positive coverage for media-only gameplay blockers with structural `provider_disabled_missing` findings, asserting `effective_status=pass`, manual-handoff reason, visible debt, and preserved raw exit code.
- [x] 2.2 Add negative coverage for mixed media/non-media blockers, missing monster JSON, unknown outcomes, and malformed gameplay payloads; all MUST remain blocked and eligible for the existing bounded revision policy.
- [x] 2.3 Add reporting/runtime coverage proving the media-only result does not become `semantic_revision` or expose raw provider payloads, while live module, registry, campaign, and runtime state remain unchanged.

## 3. Verification And Replay

- [x] 3.1 Run focused adaptation gate, semantic-failure runtime, job-reporting, gameplay/readiness, syntax, and strict OpenSpec validation suites.
- [x] 3.2 Replay the reported Amphail staging shape with provider calls disabled and confirm media-only debt is manual handoff rather than a mechanical readiness blocker.
