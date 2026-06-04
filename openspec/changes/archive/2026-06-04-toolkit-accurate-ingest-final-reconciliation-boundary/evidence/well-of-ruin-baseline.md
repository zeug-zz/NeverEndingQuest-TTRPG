# Well_of_Ruin Build-Fidelity Baseline Evidence

Captured: 2026-06-02
Workspace: `user_uploads/toolkit/homebrew_md/89c5a083-ad1c-4059-9994-2a3659d6174c/`
Build mode: `source_enhanced_modulebuilder`

## Build Fidelity Report

- **status**: `blocked`
- **can_continue**: `false`
- **refusal_reason**: `Required location 'Trigger' not found in module; Required location 'Passive Element' not found in module; Required location 'Active Element' not found in module`
- **blocker count**: 12 (all category=`location`)

### All 12 Blockers

| # | Category | Message |
|---|----------|---------|
| 0 | location | Required location 'Trigger' not found in module |
| 1 | location | Required location 'Passive Element' not found in module |
| 2 | location | Required location 'Active Element' not found in module |
| 3 | location | Required location 'Echoes of Calamity' not found in module |
| 4 | location | Required location 'Deciphering Ruin' not found in module |
| 5 | location | Required location '**Well**spring of Legend' not found in module |
| 6 | location | Required location 'Celestial' not found in module |
| 7 | location | Required location 'Draconic' not found in module |
| 8 | location | Required location 'Orcish' not found in module |
| 9 | location | Required location 'Infernal' not found in module |
| 10 | location | Required location 'Primordial' not found in module |
| 11 | location | Required location 'Abyssal' not found in module |

## Source Fidelity Report

- **status**: `blocked`

## Source Graph Atom Classification

| Term | Atom ID | Type | Criticality | Source Manifest Classification |
|------|---------|------|-------------|-------------------------------|
| Trigger | `a671174c7560b3b4_loc_trigger_17_a51765e9` | `location` | `required` | `location_candidates` (heading_location) |
| Passive Element | `a671174c7560b3b4_loc_passive_element_22_1a3fb2e6` | `location` | `required` | `location_candidates` (heading_location) |
| Active Element | `a671174c7560b3b4_loc_active_element_41_bb2498da` | `location` | `required` | `location_candidates` (heading_location) |

Additional duplicate/variant atoms exist for "Active Element" (type=`unknown`, criticality=`ambiguous`) but the `location`-typed atom is what drives the build-fidelity blocker.

## Source Markdown Heading Context

All three terms appear as `### H3` headings in `source_original.md` under the `# Well of Ruin` complex trap (level 11-16, Deadly):

- **Line 17**: `### Trigger` -- "Has a powerful spell been cast in the vicinity? Did an adventurer touch a big red button..."
- **Line 22**: `### Passive Element` -- "On initiative count 20, roll 1d8 to determine a complication for the round..."
- **Line 41**: `### Active Element` -- "On initiative count 10, roll 1d8 to see which Rune is activated..."

These are **trap mechanic sub-headings** within a single complex trap encounter, not playable module locations. The actual playable location is "Well of Ruin" (the trap room itself).

The remaining 9 blockers (Echoes of Calamity, Deciphering Ruin, Wellspring of Legend, Celestial, Draconic, Orcish, Infernal, Primordial, Abyssal) are similarly heading-derived: H3/H4 sub-headings for trap phases, rune lore sections, and rune variant tables -- not playable locations.

## Normalized Packet

The normalized packet contains 63 `locations` entries, including all 12 blocker terms. The packet inherits the source graph's heading-as-location misclassification without correction.

## Module Directory

- `modules/Well_of_Ruin` exists: **false** (build was blocked before module emission completed, or module was cleaned up)

## Build Result

- **status**: `blocked`
- **error**: `build_fidelity_blocked:Required location 'Trigger' not found in module; ...`
- **build_mode**: `source_enhanced_modulebuilder`

## Conclusion

All 12 build-fidelity blockers are **editorial/source-fidelity** in nature: the source graph extractor classified markdown headings (trap mechanics, lore sub-sections, table column headers) as `location` atoms, which propagated through the normalized packet and build-fidelity gate as required-location blockers. None represent fatal structural failures. This is the canonical case for the final reconciliation boundary.

## No Production Code Changed

This evidence file is read-only documentation of existing workspace artifacts.
