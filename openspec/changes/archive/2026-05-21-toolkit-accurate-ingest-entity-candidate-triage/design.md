## Overview

This change introduces a candidate triage layer between deterministic source extraction/identity resolution and builder blueprint generation. Deterministic extraction may continue to discover broad candidates, but candidates are not canonical entities until a triage decision marks them as kept and typed.

The immediate recovery target is Numillian: `but_this_is_not_true` must be rejected or reclassified as narrative/plot/tone text, while Dog-Growl, Book-shut, and Deflation must remain valid source NPCs with Rookery bindings.

## Contract Layer (MUST)

- Candidate triage SHALL run before builder blueprint NPC roster generation consumes deterministic NPC candidates.
- Each triage decision SHALL include candidate text, candidate slug/id, proposed type, adjudicated type, decision, reason, and source reference when source evidence exists.
- Allowed decisions SHALL be explicit and bounded: `keep`, `reject`, or `reclassify`.
- Allowed adjudicated types SHALL include at least: `true_npc`, `scene_actor`, `monster_actor`, `item_or_clue`, `location_name`, `faction_name`, `plot_note`, `tone_marker`, `narrative_phrase`, and `unknown`.
- Rejected candidates SHALL NOT appear in `builder_blueprint.json#npc_roster`, module context NPCs, area NPC lists, media queues, or source-fidelity expected NPC lists.
- Narrative phrases SHALL NOT become actor records. They MAY be preserved as plot notes, DM instructions, clue text, or tone markers if source-backed.
- Kept NPC candidates SHALL include at least one of: location binding, plot binding, faction binding, or explicit source role.
- Triage decisions SHALL be persisted in a reviewable workspace artifact, either `entity_candidate_triage_report.json` or an equivalent nested section of `identity_resolution_report.json` with stable keys.
- Blueprint generation SHALL remain compatible when no triage artifact is present by using conservative legacy behavior and reporting a warning, not crashing.
- Provider failures in any LLM adjudication seam SHALL degrade safely and SHALL NOT corrupt source graph, identity, or blueprint artifacts.

## Guidance Layer (SHOULD)

- Prefer a new helper module, `utils/toolkit_entity_candidate_triage.py`, to keep triage logic isolated from blueprint construction.
- Start with deterministic prefilters for obvious narrative phrases and underbound NPC warnings before adding any provider-backed adjudication seam.
- Reuse existing identity-resolution artifacts rather than duplicating alias canonicalization logic.
- Keep report payloads compact and JSON-serializable with ASCII-safe status strings.
- Add source-contract tests before broad route tests so regressions are easy to diagnose.

## Architecture Boundaries

- `source_graph.json` remains a broad evidence-candidate store; it does not need to be perfectly canonical.
- `identity_resolution_report.json` remains responsible for aliases, duplicates, and ambiguity summaries.
- Candidate triage is responsible for deciding whether a candidate can become an entity and what canonical semantic category it belongs to.
- `builder_blueprint.json` only consumes kept or validly reclassified candidates for actor/entity rosters.
- Build fidelity continues to compare source expectations against completed module output after builder execution.

## Migration And Rollback

- The change is additive. Existing workspaces without a triage report continue through the legacy blueprint path with a warning.
- If triage integration causes a build regression, routing can ignore the triage report and revert to pre-change blueprint candidate consumption.
- The first implementation step should add report/schema helpers and tests without changing builder blueprint output.

## Risks

- Over-filtering may drop real minor NPCs. Mitigation: keep underbound NPCs as warnings unless they are clearly narrative phrases, and add Dog-Growl/Book-shut/Deflation regression coverage.
- Under-filtering may preserve prose fragments. Mitigation: explicit narrative phrase decisions and `but_this_is_not_true` regression.
- LLM adjudication may be unstable. Mitigation: deterministic prefilter and cached/provider seam with fail-open behavior.
