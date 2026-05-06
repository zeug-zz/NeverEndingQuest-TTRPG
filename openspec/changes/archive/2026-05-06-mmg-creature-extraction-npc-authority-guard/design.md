## Context

The MMG unified-assets endpoint scans module area `_BU.json` files and returns a combined asset list for NPCs and monsters. It historically used:

- `location.npcs` for NPC discovery
- structured `location.monsters` for monster discovery

The endpoint was recently extended to also parse:

- `location.creatures`, a comma-separated prose-ish field that can contain both monsters and NPC role labels
- `location.visibleHostiles`, a structured hostile display field that can contain named combatants

That extension is useful, but the current broad suppression order is unsafe. If all extracted monster candidates are added to `monster_authority_slugs`, a weak `creatures` token such as `Blarg (berserker)` can suppress the authored NPC row for Blarg. This complicates module independence and actor authority because a prose scene-inhabitant field is being treated like statblock/media authority.

This change revises the plan and contract. Runtime code should not be considered complete until the source-aware resolver and tests below are implemented.

## Goals / Non-Goals

### Goals

- Preserve added discovery from `creatures` and `visibleHostiles`.
- Separate explicit module monster authority from weak monster candidates.
- Preserve existing Thornwood behavior where same-slug monster-authoritative actors appear as monster assets only.
- Preserve Night-style NPCs when their only monster evidence is a weak `creatures` or `visibleHostiles` reference.
- Keep toolkit MMG decisions module-local and independent of current campaign runtime files.
- Make report generation use the same authority decision as the endpoint.

### Non-Goals

- Do not remove `creatures` or `visibleHostiles` extraction wholesale.
- Do not change runtime combat authorization or encounter creation behavior.
- Do not modify module JSON data as part of this change.
- Do not reintroduce duplicate delegated NPC rows for monster-authoritative actors.
- Do not use fuzzy matching or provider calls for authority resolution.

## Authority Model

### Explicit Monster Authority

A slug is explicitly module monster-authoritative when it appears in module-local monster authority sources:

1. `modules/<module>/monsters/<slug>.json`
2. Structured `location.monsters` entries in scanned module area files
3. Existing module-local monster seed/closure artifacts if already used by `build_module_monster_authority()` and not dependent on runtime campaign state

Explicit monster authority means the monster row wins over same-slug NPC hint data.

### Weak Monster Candidate

A slug is a weak monster candidate when it is discovered only from:

1. `location.creatures`
2. `location.visibleHostiles`

Weak candidates improve media discovery, but they do not by themselves establish actor/media authority over an authored NPC.

### NPC Authority

A slug is NPC-authoritative when it is found in module-local NPC sources:

1. `module_context.json -> npcs`
2. `module_context_BU.json -> npcs`, when present
3. `npcs_seed.json`, when present
4. Area `location.npcs[].name` in scanned backup and/or live module area files used by MMG

Identity normalization must include canonical slugs plus safe aliases:

- Parenthetical labels contribute a bare-prefix alias, e.g. `Ma (Margaret Thornfield)` -> `ma`.
- Comma/appositive labels contribute a canonical prefix alias, e.g. `Arannis, vault scholar` -> `arannis`.
- The full normalized label may be retained as a compatibility lookup key, but it must not be the only key.

## Conflict Resolution

Apply these rules after all module-local sources are scanned:

| Conflict | Resolution |
| --- | --- |
| Explicit monster authority + NPC authority | Keep monster row; suppress NPC asset row as descriptive hint only. |
| Weak monster candidate + NPC authority | Keep NPC row; drop weak monster candidate. |
| Explicit monster authority + weak candidate | Keep monster row; weak source may be recorded as provenance only. |
| Weak candidate only | Keep monster row, because no NPC authority conflicts. |
| NPC authority only | Keep NPC row. |

The endpoint should not run `monster_authority_slugs.update(monsters.keys())` unless `monsters.keys()` has already been narrowed to explicit monster-authoritative sources. Weak candidates must not promote themselves to authority.

## Decisions

### Decision 1: Source-aware provenance is required

Each discovered monster candidate should retain source provenance. A single flat `monsters` dict is not enough to decide whether the monster row should beat an NPC row.

### Decision 2: Module-local helper preferred

The MMG endpoint and report builder should share a small module-local helper, or equivalent logic, that returns explicit monster authority, weak monster candidates, NPC authority, and final asset rows. The helper must not read `party_tracker.json` or other current-campaign runtime state.

### Decision 3: `module_context` is part of NPC authority

Use `module_context.json` and `module_context_BU.json` as NPC identity sources. They are module-local canonical authored metadata and close gaps where a creature token uses a short alias while area data uses a fuller name.

### Decision 4: Reports mirror endpoint authority

`module_media_generator_report.py` must not globally prefer monster rows for every same-slug collision. It should prefer monster rows only when the slug is explicitly module monster-authoritative; otherwise NPC rows win over weak candidates.

## Risks / Trade-offs

### Risk: Legitimate same-name NPC and monster

Example: an NPC named `Goblin` and actual Goblin monsters. The source-aware rules handle this if Goblin appears in structured `location.monsters` or has a module monster JSON. If it only appears in weak `creatures` text, NPC wins and the module should author the monster explicitly.

### Risk: visibleHostiles may contain true named monsters

If a named hostile is also explicitly monster-authoritative, monster wins. If it is only in `visibleHostiles` and has no NPC authority, it remains a monster candidate. If it conflicts with NPC authority, NPC wins until the module provides explicit monster authority.

### Risk: Helper divergence from existing `build_module_monster_authority()`

The existing helper has runtime-oriented behavior and reads party state through known-NPC loading. For MMG, use a module-local mode or a separate helper to avoid runtime/campaign-dependent toolkit output.

### Rollback

Do not revert all extraction. If issues arise, disable only weak-source elevation (`creatures` and `visibleHostiles`) while preserving structured `location.monsters` and existing monster-authoritative suppression.
