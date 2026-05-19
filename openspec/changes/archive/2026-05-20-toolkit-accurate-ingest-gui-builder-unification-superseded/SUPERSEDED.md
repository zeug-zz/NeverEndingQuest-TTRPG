# Superseded: Toolkit Accurate-Ingest GUI Builder Unification

**Status:** Superseded -- not accepted as final architecture.

**Date archived:** 2026-05-20

## Reason

This change incorrectly promoted the deterministic blueprint seed writer from a support/fallback tool to the primary GUI build path for accurate-ingest uploads (`ENABLE_ACCURATE_INGEST_GUI_BLUEPRINT_BUILD`). The default accurate-ingest GUI path called `materialize_module_from_blueprint(...)` instead of the existing LLM `ModuleBuilder` orchestration, while LLM enrichment was still a no-op placeholder. This produced source-named but thin/unplayable skeletal module artifacts with empty prose fields, then sent them through readiness and finisher gates as if they were complete adventure builds.

The intended accurate-ingest contract is: **enhance the existing ModuleBuilder with source-faithful context, not replace it with a deterministic Python template.**

## Recovery

Superseded by `plans/accurate-ingest-fix.md` and the forthcoming `toolkit-accurate-ingest-modulebuilder-recovery` OpenSpec chain (see Change 0 through Change 9 in the recovery plan).

## Preserved Value

The following artifacts and tests from this change should be mined when building the recovery chain:

- `utils/toolkit_builder_blueprint.py` -- blueprint v2 contract and validation helpers.
- `utils/toolkit_blueprint_seed_writer.py` -- seed writer as preview/fallback/fixture/comparator/support tooling.
- `utils/toolkit_blueprint_enrichment.py` -- patch validation and honest status semantics.
- `utils/toolkit_homebrew_packet_builder.py` -- the `_execute_seed_writer_build(...)` path reclassified as fallback.
- `web/routes/toolkit_homebrew_routes.py` -- accurate-ingest GUI state surfacing.
- `scripts/test_toolkit_blueprint_v2_contract.py`
- `scripts/test_toolkit_blueprint_seed_writer.py`
- `scripts/test_toolkit_blueprint_enrichment_patches.py`
- `scripts/test_toolkit_homebrew_gui_unified_flow.py`
- `scripts/test_toolkit_module_summary_finisher_contract.py`
- `scripts/test_accurate_ingest_numillian_end_to_end.py`

## Do Not Sync

The delta specs from this change must not be promoted as canonical main specs without revision. The architecture decisions they encode (especially deterministic seed writer as primary authoring path, mandatory pre-build review approval, and silent enrichment-complete status) are architecturally rejected by the recovery plan.
