## Why

The Hostis adaptation can produce rich narrative and monster artifacts, but publication still fails when independent spatial, semantic, or content-integrity blockers remain. The builder needs one bounded finalization boundary that lets the Module Builder LLM finish an adapted staged module, while Python remains authoritative over structure, mechanics, provenance, and the final gate decision.

## What Changes

- Add an adaptation publication convergence stage after module generation and before readiness/publication gates.
- Treat convergence as the single bounded finalization loop for an adapted staging revision, with a fixed attempt budget and deterministic stop conditions.
- Normalize invalid map connectivity into the existing spatial topology contract without deleting authored travel intent.
- Generate and persist deterministic `semantic_authority` data from authored module/source artifacts.
- Resolve unique destination phrases through canonical aliases and source provenance.
- For ambiguous destination phrases, ask the configured Module Builder LLM for a bounded resolution proposal; Python MUST validate the proposal against canonical locations, topology, and source evidence before applying it.
- Allow the LLM to propose bounded repairs for approved content gaps, such as missing prose, encounter framing, or canonical stat completion, only through explicit whitelisted operations.
- Re-run the relevant deterministic checks after every accepted repair and re-run the complete final gate set before promotion.
- Keep unresolved or unsafe proposals as concrete blockers rather than guessing or silently dropping content.
- Re-run schema, readiness, gameplay, and publishability gates against the converged staging module.
- Preserve the existing adaptation monster guardrail as a preceding, independent stage.
- Preserve legacy ModuleBuilder behavior and generic monster closure defaults.
- Treat literal source fidelity as provenance for intentional adaptation, not as an automatic publication blocker when the module is structurally and mechanically playable.

## Capabilities

### New Capabilities

- `adaptation-publication-spatial-convergence`: Repair and validate authored map topology and connectivity in staging before publication gates.
- `adaptation-publication-semantic-authority`: Build deterministic module-local location, destination, NPC, and provenance authority for readiness and gameplay checks.
- `adaptation-publication-llm-resolution`: Produce bounded LLM proposals for ambiguous destination semantics and apply them only after deterministic Python validation.

### Modified Capabilities

- None. Existing spatial, semantic, and publication utilities are reused through focused convergence hooks; their existing legacy requirements are not globally rewritten.

## Impact

- Affected pipeline surfaces: adaptation packet building, staging finalization, spatial validation, semantic-authority enrichment, readiness, gameplay, and publishability reporting.
- Likely implementation files: `web/extensions/toolkit_homebrew_packet_builder.py`, existing spatial normalization utilities, `utils/module_semantic_authority.py`, and the adaptation/module finisher reporting seams.
- New provider use is limited to bounded finalization proposals in the adaptation publication stage. Provider outage, quota failure, invalid output, or timeout MUST leave the module at its current staging revision with a deterministic diagnostic and MUST NOT mutate live module files.
- All writes remain staging-local and atomic until every required gate passes.
- Single-player and legacy ModuleBuilder paths remain unchanged; TABLETOP MODE and adaptation behavior gain only the new staging convergence boundary.
- No new dependency is required.

## Corrective Follow-up: Production Destination-Resolution Closure

This existing publication-convergence capability also includes a narrowly scoped corrective production-wiring slice. It supplies the existing convergence callback with current staged semantic authority and a bounded repair request so genuinely ambiguous phrases, including the Amphail `softstone inn` case, can reach the already-specified Module Builder resolution contract. It does not change legacy/non-adaptation scope, regenerate modules, alter monster finalization, or create a new OpenSpec change.
