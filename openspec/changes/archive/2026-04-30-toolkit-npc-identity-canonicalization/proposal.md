# Why

The module toolkit can persist NPC identities using the full authored display phrase as the durable compendium key. In `The_Hidden_City_of_Numillian`, labels such as `Arannis, vault scholar and alarmed archivist` became slugs like `arannis,_vault_scholar_and_alarmed_archivist`, which duplicates a single person across role-description variants and pollutes `data/bestiary/npc_compendium.json`.

# What Changes

- Add a shared NPC identity canonicalization helper for toolkit/module-builder ingestion paths.
- Derive durable NPC IDs from the clean identity only, not appositive description text.
- Preserve the original source label and role/appositive text as metadata so descriptive authoring is not lost.
- Canonicalize toolkit NPC list, description generation, manual description save/read, and unified asset generation write boundaries.
- Add regression coverage for Numillian-style descriptive labels and duplicate single-name variants.

# Capability Scope

- Toolkit NPC extraction from module area files.
- NPC compendium description persistence.
- Temporary NPC description cache persistence.
- Unified asset generation NPC description and media identity handling.

# Non-Goals

- Do not change monster/bestiary normalization helpers used by LLM classification.
- Do not rewrite authored module text or remove descriptive labels from area files.
- Do not attempt broad fuzzy entity resolution beyond conservative comma/appositive canonicalization.
- Do not migrate the existing compendium data in this change; remediation can be a follow-up tool.

# Impact

- New NPC compendium keys use canonical slugs such as `arannis`, `elaris`, `ilyra`, `kobe`, and `letharel`.
- Existing API consumers continue to receive `id` and `name`; additional metadata fields are additive.
- Existing bad keys remain readable where compatibility lookup can canonicalize incoming requests.

# Risks

- Over-aggressive canonicalization could collapse generic group labels incorrectly.
- Existing media generated under old descriptive filenames may not be found by new canonical IDs.
- Existing bad compendium keys may coexist until a remediation pass merges them.

# Fallback

- If identity parsing is uncertain, use the original label as the canonical name and only sanitize the slug.
- Preserve source labels and source IDs so manual recovery remains possible.
- Fail open for missing metadata; never block description generation solely because canonical metadata cannot be added.

# Merge Safety and SP/MP Impact

- Keep logic in a new utility module and thin TABLETOP MODE hooks in `web/web_interface.py`.
- Preserve upstream route structure and response shapes.
- Single-player gameplay is unaffected; this targets module toolkit/build-time assets.
