# Design: Numillian Source-Fidelity Fix

## Overview

This change implements three narrow fixes to unblock Numillian source-fidelity without weakening publication gates or altering the accurate-ingest architecture.

## Capability 1: Punctuation-Normalized Build Fidelity

### Root Cause

`utils/toolkit_build_fidelity.py:_normalize_name()` currently does:

```python
def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")
```

Markdown source atom labels from table cells such as `Red Skull:` retain their trailing colon. The comparison `_normalize_name("Red Skull:") == _normalize_name("Red Skull")` evaluates to `False` because `"red_skull:" != "red_skull"`.

### Fix

Add a single narrow punctuation-strip step to remove common trailing markdown/table punctuation before or during the existing normalization:

```python
def _normalize_name(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_").rstrip(",:;.!?")
```

### Acceptance

- `_normalize_name("Red Skull:")` == `_normalize_name("Red Skull")`
- `_normalize_name("Blue Skull:")` == `_normalize_name("Blue Skull")`
- `_normalize_name("Yellow Skull:")` == `_normalize_name("Yellow Skull")`
- `_normalize_name("Sister Mara")` == `_normalize_name("sister_mara")` unchanged
- Distinct names such as `"The Caretaker"` and `"The Caretaker / Procul"` remain distinct after normalization
- All existing build-fidelity tests continue to pass

## Capability 2: Puzzle Preservation in Synthetic Blueprint

### Root Cause

`scripts/rebuild_numillian_accurate_ingest.py:_build_synthetic_blueprint_from_packet()` hardcodes `puzzle_graph=[]` in the returned blueprint. In this rebuild path, the builder blueprint can be blocked by fidelity and therefore absent, but the workspace still has richer normalization artifacts such as `plot_topology_report.json`. The current synthetic fallback reads only the normalized packet, so puzzle chains from topology are discarded before seed writing and benchmarking.

### Fix

Load `plot_topology_report.json` in `rebuild_numillian()` before invoking the synthetic fallback and pass it into `_build_synthetic_blueprint_from_packet(...)` or a helper. Populate `puzzle_graph` from the first available source in this order:

1. `plot_topology_report["puzzle_chains"]`
2. `plot_topology_report["trials"]` when those entries represent puzzle/trial mechanics
3. normalized packet fields such as `puzzle_seeds`, `puzzles`, `puzzle_chains`, or `trials`

Each puzzle entry should carry:

- `chain_id` or `beat_id` or deterministic fallback id
- `title` or `name`
- `setup`, `rules`, `solution`, `failure_consequences` when present
- `source_descriptions` or `source_refs` excerpts when available
- puzzle/trial type hint if available

If topology and packet sources do not contain puzzle data, preserve `puzzle_graph=[]` but append a warning about the fidelity gap to the synthetic blueprint warnings. Do not invent puzzle content.

### Acceptance

- After rebuild, `skull_riddle` and `kill_the_dog_mindscape` appear in benchmark output
- `flooding_room` remains found
- Synthetic blueprint carries puzzle atoms when topology or packet provides them
- `coverage["puzzles_in_blueprint"]` matches `len(puzzle_graph)`
- No regression for modules without puzzle data

## Capability 3: Prose Phrase Actor Filtering

### Root Cause

The accurate-ingest pipeline already contains an entity-candidate triage layer that can reject narrative phrases. The production Numillian rebuild path can still emit `but this is not true` because the fidelity-blocked synthetic fallback builds an NPC roster directly from `packet["npc_seeds"]` and does not guarantee triage filtering is applied at that fallback boundary.

### Fix

Reuse existing triage helpers rather than creating a second broad classifier:

- Prefer loading `entity_candidate_triage_report.json` in the synthetic rebuild path.
- Exclude any packet NPC seed whose normalized slug appears in a triage decision with `decision="reject"` or non-actor adjudicated type such as `narrative_phrase`, `plot_note`, `tone_marker`, or `unknown`.
- If no triage decision exists for a packet NPC seed, apply the existing deterministic `looks_like_narrative_phrase(...)` / `build_prefilter_decision(...)` seam from `utils/toolkit_entity_candidate_triage.py` as a fallback.
- Record filtered candidates in synthetic blueprint warnings or artifact metadata so the exclusion is auditable.

Do not implement a general "lowercase names are invalid" rule. Valid source names may contain lowercase words or hyphenated/compound forms. Filtering should be evidence/context based or use existing narrative-phrase prefixes, not typography alone.

### Acceptance

- `but this is not true` does not appear in `module_context.json` NPC entries
- `but this is not true` does not appear in `npcs_seed.json`
- `but this is not true` does not appear in semantic `npc:but this is not true` references
- Legitimate NPCs containing short/lowercase segments (e.g., `Alms-plate`, `Book-shut`) remain unaffected
- Dog-Growl, Book-shut, Deflation remain preserved
- Existing triage tests continue to pass

## Capability 4: Regression Locks

All three fixes MUST have deterministic regression tests that exist before the fixes are applied (source-contract) or that pass after the fixes (behavioral).

Regression coverage:

1. Build fidelity: `Red Skull:` matches `Red Skull`; `Blue Skull:` matches `Blue Skull`; `Yellow Skull:` matches `Yellow Skull`
2. Entity pollution: `but this is not true` is filtered by triage-aware synthetic fallback and is not emitted as NPC/actor
3. Benchmark blockers: `skull_riddle` and `kill_the_dog_mindscape` are documented as currently-blocked

## Capability 5: Rebuild and Reassessment

After pipeline fixes:

1. Run `scripts/rebuild_numillian_accurate_ingest.py --json`
2. Run `scripts/benchmark_accurate_ingest.py --module The_Hidden_City_of_Numillian --json`
3. Run `scripts/audit_module_publishability.py --module The_Hidden_City_of_Numillian --json`
4. Run `core/validation/validate_module_files.py --module The_Hidden_City_of_Numillian`
5. Report `source_fidelity_status` and dirty file count

## Rollback

If fixes cause regressions in other modules, revert the specific fix. The three fixes are independent and can be reverted separately.

## Dependencies

- The archived `toolkit-accurate-ingest-llm-blueprint-enrichment` is completed background. This change does not depend on its runtime behavior.
- The Numillian benchmark fixture at `data/benchmarks/The_Hidden_City_of_Numillian_benchmark.json` is authoritative and MUST NOT be changed by this fix.
