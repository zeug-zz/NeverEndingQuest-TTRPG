# Builder Prompt 1: Close Accurate-Ingest Pre-Build Review Deadlock

Implement the OpenSpec change `toolkit-accurate-ingest-prebuild-review-deadlock-closure`.

## MUST Contract

- Do not weaken final gates: schema validation, source-fidelity benchmark, toolkit build fidelity, publishability, playable-publication, and report-agreement checks remain authoritative and fail-closed.
- Do not add broad force approval or bypass strict fidelity review approval.
- Preserve strict required-review behavior when the backend explicitly marks a current required review state, stale signature, non-approvable payload, user rejection, malformed source, or missing artifact prerequisite.
- Make pre-build source-fidelity diagnostics nonblocking by default when source text and packet artifacts are readable and a bounded blueprint can be generated.
- Ensure degraded diagnostics continue into metadata/warnings rather than forcing `awaiting_review` or `blocked_by_fidelity` before `builder_blueprint.json` is produced.
- If `builder_blueprint.json` cannot be generated because prerequisites are missing or malformed, fail with explicit missing/malformed artifact diagnostics and do not render success.
- Fix GUI status guidance so `rejected`, `blocked`, `failed`, `quarantined`, and no-module states are not presented as successful completion.
- Gate MMG guidance on actual module folder existence and an MMG-eligible state.
- Add provider-free regression tests. Do not require live LLM/provider calls.

## SHOULD Guidance

- Keep the patch minimal and localized to accurate-ingest toolkit code.
- Prefer deterministic source atom classification improvements over adding new LLM repair attempts.
- Add source-contract tests for an Elden Ring-like markdown source pattern: `### Bridge of Sacrifice`, escaped numbered room headings like `#### 1\\. Chapel`, `Appendix A`, prose fragment `gathered around a`, NPC-like `Nomadic Merchant`, and creature names like `Guard Dog`, `Lesser Black Knife Assassin`, `Lion Guardian`.
- Preserve current optional diagnostics panel behavior, but label it as diagnostics/warnings unless required review is explicit.

## Suggested Files To Inspect First

- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html`
- `utils/toolkit_source_manifest.py`
- `utils/toolkit_normalization_fidelity.py`
- `utils/toolkit_builder_blueprint.py`
- `utils/toolkit_homebrew_normalizer.py`
- `utils/toolkit_report_agreement.py`
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `scripts/test_toolkit_blueprint_v2_contract.py`
- `scripts/test_accurate_ingest_numillian_benchmark.py`

## Expected Tests

- Add/extend accurate-ingest GUI/unified-flow tests for degraded diagnostics continuing to blueprint generation.
- Add/extend source atom classification tests for markdown headings, escaped rooms, appendix headings, prose fragments, NPC names, and creature names.
- Add GUI/source-contract tests proving rejected/no-module states do not show success or MMG guidance.
- Re-run targeted existing tests for blueprint handoff and report agreement gates.

## Verification Commands

Use `.venv/bin/python` for dependency-sensitive commands.

```bash
.venv/bin/python -m py_compile web/routes/toolkit_homebrew_routes.py utils/toolkit_source_manifest.py utils/toolkit_normalization_fidelity.py utils/toolkit_builder_blueprint.py utils/toolkit_homebrew_normalizer.py
.venv/bin/python -m unittest -q scripts.test_toolkit_homebrew_gui_unified_flow
.venv/bin/python -m unittest -q scripts.test_toolkit_blueprint_v2_contract
.venv/bin/python -m unittest -q scripts.test_accurate_ingest_numillian_benchmark
openspec validate toolkit-accurate-ingest-prebuild-review-deadlock-closure
```

If implementation touches report agreement or publishability composition, also run the relevant report agreement/publishability tests before completion.
