# Phase 2 LLM-Assisted Narrative Classification

## Problem

The module builder pipeline converts homebrew markdown into structured NEQ modules via deterministic Python extraction. However, authored adventure text often contains ambiguous narrative intent that deterministic extraction cannot disambiguate:

1. **Entity ambiguity**: "spectral servants appear" could mean combatant monsters, illusion-only scene dressing, or narrator flavor — deterministic extraction treats them all as combatants, polluting monster catalogs with non-combat entities.
2. **Travel phrase ambiguity**: "the path leads to the great hall" is a travel alias, but "the great hall awaits" is evocative prose — deterministic extraction feeds both into travel authority maps, causing false probe failures.
3. **NPC visibility ambiguity**: "you hear whispers from the shadows" may imply a visible NPC, a hidden/reveal NPC, or lore-only reference — deterministic extraction marks all NPC mentions as visible, causing probe confusion.
4. **Remediation blindness**: when blocker reports surface, the author must manually invent fixes — the system cannot suggest concrete remediation actions.

## Objective

Add bounded LLM assistance at four review-time decision points to classify ambiguous authored narrative intent. The LLM is advisory only: it proposes classifications, Python validates them against module schema constraints, and the human author reviews and approves in the GUI.

## Non-Goals

- The LLM does NOT generate new narrative content (this is generative enrichment, deferred to v2 narrative track Phase 4).
- The LLM does NOT replace deterministic extraction — it only classifies ambiguity that extraction already flagged.
- The LLM is NOT the final authority — Python is always the gatekeeper.
- Phase 1 structural flows (monster materialization, spatial contract, continuity enrichment) are unchanged.
- Single-player mode is unaffected — classification only activates in the toolkit build path.

## Risks

| Risk | Mitigation |
|---|---|
| LLM hallucinates classification labels | Python validates against allowed enum values; unrecognized labels fall back to `narrator_flavor` / `evocative_prose` / `lore_only` (safest default) |
| LLM API failure blocks build | All classification calls are fail-open: API failure falls back to safest deterministic default (e.g., treat as combatant, visible, prose) |
| LLM reclassifies deterministic-truth entities | Pre-filter: only entities flagged as ambiguous by deterministic extraction are sent to LLM |
| Cost overrun | Bounded batch calls: one classification call per ambiguity batch, not per entity |
| Classification drift between reruns | Cache classification results by content hash; reclassify only when authored text changes |

## Fallback

All classification paths are fail-open:
- **Entity triage failure** → `combatant` (treat as real, let readiness gate enforce schema)
- **Destination classification failure** → `canonical_alias` (treat as alias, be permissive)
- **NPC visibility failure** → `visible` (treat as visible, be permissive)
- **Remediation proposal failure** → return empty proposals (no LLM suggestions)
