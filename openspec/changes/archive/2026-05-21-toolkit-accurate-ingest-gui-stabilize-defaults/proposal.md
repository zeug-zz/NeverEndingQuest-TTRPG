# Change: Stabilize Accurate-Ingest GUI Defaults

## Problem

The accurate-ingest GUI path can currently route ready blueprint builds into the deterministic seed writer by default. That path can create schema-shaped but thin adventure skeletons and then allow later readiness/finisher stages to treat the result like a normal authored module build.

This is the wrong default for human adventure ingest. The deterministic seed writer is useful support tooling, but the existing LLM ModuleBuilder orchestration must remain the primary creative authoring path while accurate-ingest supplies source-faithful constraints and diagnostics.

## Objective

Restore the Module Builder GUI to a safe default state while the larger accurate-ingest recovery chain proceeds.

Contract Layer (MUST):

- Accurate-ingest GUI builds MUST NOT invoke the deterministic seed writer as the default authoring path.
- Accurate-ingest GUI builds MUST be able to route through the existing ModuleBuilder orchestration when the source packet and blueprint are build-ready.
- Clean source-fidelity diagnostics MUST NOT create a mandatory pre-build approval pause.
- Seed-writer fallback or preview MUST require explicit fallback/preview configuration or route/request state.
- Existing Describe-your-Adventure and packet build flows MUST remain functional.

Guidance Layer (SHOULD):

- Prefer flag and routing changes over broad GUI rewrites.
- Preserve existing fidelity diagnostics and review UI as optional inspection surfaces.
- Keep changes small enough to archive before deeper enrichment work starts.

## Non-Goals

- Do not implement real LLM blueprint enrichment in this change.
- Do not rewrite ModuleBuilder, ModuleGenerator, AreaGenerator, LocationGenerator, or PlotGenerator.
- Do not delete the deterministic seed writer.
- Do not change final publishability/source-fidelity composition beyond preserving existing behavior.
- Do not make fidelity review mandatory for clean accurate-ingest builds.

## Scope

Primary files:

- `model_config.py`
- `config_template.py`
- `web/extensions/toolkit_homebrew_packet_builder.py`
- `web/routes/toolkit_homebrew_routes.py`
- `web/templates/module_toolkit.html`
- Existing toolkit GUI and publication parity tests

## Risks

- Routing changes could accidentally regress existing packet builds.
- GUI copy could still imply approval is mandatory even when diagnostics are optional.
- Tests may rely on the current seed-writer default and need contract updates.

## Fallback

If ModuleBuilder routing cannot be restored safely in one slice, the GUI MUST fail closed with a clear blocked/degraded status rather than silently producing a seed-writer skeleton as a normal build.

Seed writer support MAY remain available behind explicit fallback/preview configuration for operator-requested structure-only output.

## Compatibility

- Legacy concept/Describe-your-Adventure builds MUST remain compatible.
- Accurate-ingest artifacts and diagnostics SHOULD remain additive.
- No runtime gameplay behavior should be affected.
