# Design: Accurate-Ingest ModuleBuilder Handoff

## Architecture Boundary

The packet builder remains the GUI build facade. It decides whether to run ModuleBuilder or seed writer support mode based on explicit configuration and request state.

Hard ownership boundaries:

- `web/extensions/toolkit_homebrew_packet_builder.py` owns packet build routing, builder input persistence, and build-mode reporting.
- `core/generators/module_builder.py` remains the creative authoring executor.
- `utils/toolkit_blueprint_seed_writer.py` remains support/fallback tooling only.
- Source-fidelity benchmark and build-fidelity scanners remain deterministic validators and SHALL NOT be weakened.

## Key Decisions

### Decision 1: ModuleBuilder Is Default Authoring Path

Default accurate-ingest GUI builds MUST call `_execute_module_builder(...)` when no explicit seed writer mode is supplied.

Rationale: The recovery plan's central constraint is that Python should preserve and verify source truth, while the LLM ModuleBuilder path interprets and writes playable adventure content within evidence bounds.

### Decision 2: Seed Writer Requires Explicit Mode

Seed writer execution MUST require explicit `seed_writer_mode` (`fallback`, `preview`, or `support`) or explicit fallback authorization.

Rationale: The seed writer can produce valid skeletal artifacts, but should not silently replace the creative ModuleBuilder path for human-authored adventure content.

### Decision 3: Builder Handoff Is the Testable Contract

Before changing generator prompts, this change MUST prove that the required source contract enters `builder_input.json` or `builder_narrative.md` before ModuleBuilder runs.

Required source contract content includes:

- source hash and source identity
- build mode
- required source NPC names
- required source location names
- required puzzle/challenge identifiers or descriptions
- tone requirements
- forbidden-invention guidance

### Decision 4: Verification Is Provider-Free

All Step 1 source-contract tests MUST be deterministic and provider-free. They SHOULD use fixture workspaces and patched executor functions rather than live LLM calls.

## Migration Sequence

1. Add source-contract tests around default ModuleBuilder route and builder handoff artifact content.
2. Expand handoff serialization only if tests prove current artifact is insufficient.
3. Keep seed writer explicit mode tests green.
4. Defer generator prompt hardening to a follow-up OpenSpec change.

## Rollback Strategy

If routing or serialization changes break existing GUI builder behavior, revert only the changed routing/serialization logic and keep failing source-contract tests as evidence for the next minimal fix.

## Observability

Build results SHOULD continue to report `build_mode`, `builder_input_path`, `build_result_path`, and `seed_writer_mode` when applicable. Default ModuleBuilder handoff SHOULD report `source_enhanced_modulebuilder` for accurate-ingest v2 workspaces.

## Compatibility

- Non-source concept-builder flows MUST remain functional.
- Existing packet workspace validation MUST remain fail-closed for malformed packets.
- Seed writer support mode MUST remain available for rebuild proof scripts and explicit GUI route payloads.
