# Holdout Scene Selection Draft

**DRAFT / UNFROZEN / NOT OWNER-APPROVED.** Provider-free, read-only module inspection. **NO SEED / NO RUN.** This records only owner-authorized Section 2 preparation sub-step 1a: scene selection. It does not create fixtures, tooling, a rubric, or a manifest, and it does not edit Section 2 checkboxes.

## Selection and source-text method

Exactly six new candidates are proposed, one from each of six modules listed in `modules/published_modules.json`. Module data was inspected read-only. The `source_text_sha256` and fingerprints cover exact raw UTF-8 JSON object spans selected from the source files, concatenated in the listed source order with no normalization or separator bytes. Each full source file has a separate SHA-256 below. For the Numillian candidate, the spans are `map.rooms[id=A01]`, `locations[locationId=A01]`, then `plotPoints[id=TRIAL000]`.

The source fingerprints were computed by calling `mise_en_scene.evaluation.fingerprint_source_text()` and compared to all 25 records returned by `load_known_examples()` using the evaluator's `_make_pair_check()` and its existing thresholds. Catalog canonical SHA-256: `7defa824776c8a08dd5c2669148563680d08bd466bfb45483825703bb1634165`. Thresholds: source text 3 shared tokens and 200,000 Jaccard ppm; layout 2 and 250,000 ppm; features 3 and 250,000 ppm; exact token-set overlap also requires review. The complete 6 x 25 count/Jaccard matrix is in `selection.json`, aligned to its `known_example_order` array.

The lexical screen is not semantic proof of independence or non-leakage. It also does not compare projected artifact text, because no fixtures or artifacts are in this sub-step.

## Proposed scenes

### 1. Shrouded Lantern Encampment

- **Scene ID:** `murder_at_the_drowning_lass:scene:shrouded-lantern-encampment`
- **Module:** `Murder_at_the_Drowning_Lass` (published)
- **Area/location:** `WM001 / H01` (`Shrouded Lantern Encampment`)
- **Source file:** `modules/Murder_at_the_Drowning_Lass/areas/WM001_BU.json` - SHA-256 `4f0752953d710d1c0d345c55d529656273cb1963be237dfe0512b2151817e412`
- **Source-text SHA-256:** `2c3d4bc25fac9a645533d942021b95d315ef255dec5913ec87ba0bc3c597d261`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** A camp beside a main animal trail has lanterns, bedrolls, cookware, crates, and Red Maw scouts. Source text notes distant lantern visibility at dusk and links the location to H02 and H03, but does not assign direction to those links.
- **Source-supported relations:** Trail-to-camp approach potential; lanterns as visible arrival cues; campsite contents and Red Maw scout presence; connectivity to H02/H03. Source identifies a hidden compartment under a loose flagstone and a trail toward Crooked Cairn Hill.
- **Builder-authored or unknown:** The threshold, focal hierarchy, exact anchor identities/positions, cell extents, and scout positions are not specified. Any staging of those relations must be hand-authored and labelled; compass, distance, or additional access claims remain unknown.
- **Guarded facts:** DM-facing Investigation check can reveal a hidden compartment and Red Maw token. Treat the concealment as guarded; do not disclose it in a public arrival or infer an activation/effect.
- **Coverage:** D, F.

### 2. Abyssal Fracture

- **Scene ID:** `the_ancients_lab:scene:abyssal-fracture`
- **Module:** `The_Ancients_Lab` (published)
- **Area/location:** `BA001 / I02` (`Abyssal Fracture`)
- **Source file:** `modules/The_Ancients_Lab/areas/BA001_BU.json` - SHA-256 `f269385e6b9bd112d4fee82beda801fe2cf5c20f5eb9202df5a59687cdffe8b0`
- **Source-text SHA-256:** `97b698883f33c62d653402b6a5593a7d294e1f8cba22674673e3bd7cc2eacd8f`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** A jagged rift splits the moor, with basalt sides, a stream below, fallen stones, brambles, runes, and persistent mist. The source calls the ravine an obstacle and describes a concealed bramble hazard.
- **Source-supported relations:** Ravine-to-moor boundary, stream at the ravine bottom, fallen stones/brambles, mist, runes, and a route requiring a climb. Location connectivity names I01 but does not establish a compass direction.
- **Builder-authored or unknown:** The multi-cell extent of terrain/path/boundary and any separate usable space are not laid out by the source. Coverage B depends on later hand-authored, labelled schematic cells for the ravine and a usable space, kept compass-free and non-metric. Until that authoring is approved, the usable-space relation remains unknown.
- **Guarded facts:** The source contains DM trap fields for concealed sharp brambles. Its stated trap damage is source text, not an unknown effect; no additional mechanic may be inferred.
- **Coverage:** B, E.

### 3. Shattered Anvil Crossing

- **Scene ID:** `into_the_deepvault:scene:shattered-anvil-crossing`
- **Module:** `Into_the_Deepvault` (published)
- **Area/location:** `RF004 / I01` (`Shattered Anvil Crossing`)
- **Source file:** `modules/Into_the_Deepvault/areas/RF004_BU.json` - SHA-256 `73645a36281c96b3718aad2c2cba3384afb1185913f5c8a2bd45ed381355d1ec`
- **Source-text SHA-256:** `67a17e8bd101030c56c1659c035063862e265fc2b301e84717dd725e3c89759a`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** A fractured crossing contains a central shattered anvil, scorched runes, an East Archway, a locked West Door, and a hostile construct. The source lists connections to I02 and I03 and a concealed compartment beneath the anvil.
- **Source-supported relations:** Centered anvil as a focal anchor; two named door/threshold candidates; connections to I02/I03; source-described trapped rune plate and concealed compartment. The source does not map each connected location to a named door.
- **Builder-authored or unknown:** The approach -> threshold -> focal assignment and exact approach-to-door mapping would need labelled Builder authorship within approved topology. No compass, route, or access relation beyond source-listed connections is inferred.
- **Guarded facts:** DM-facing trap has a specified rune-plate trigger/effect; the concealed compartment is discoverable by a source-listed check. Keep those details out of public arrival unless separately authorized.
- **Coverage:** A, E.

### 4. Sanctum of Fractured Truths

- **Scene ID:** `xhalruuns_masquerade:scene:sanctum-of-fractured-truths`
- **Module:** `Xhalruuns_Masquerade` (published)
- **Area/location:** `TPG001 / AK01` (`Sanctum of Fractured Truths`)
- **Source file:** `modules/Xhalruuns_Masquerade/areas/TPG001_BU.json` - SHA-256 `8c1271cee7c9db9f82665a2204b5c35f6259336f11b5c949240290965b1afca0`
- **Source-text SHA-256:** `a9239061ad1981e68eaef0d1611283cae9c79514802d6f3d3ceb952d7fd37d98`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** The temple has a south entrance, a central crystal altar, shifting mirrored mosaics, flickering lanterns, Keeper Veyron, and a hidden vestry door behind the altar. The location connects to AK02.
- **Source-supported relations:** One source location identity; central altar; south entrance; hidden vestry door behind the altar; Keeper Veyron at the location; connection to AK02. The text distinguishes the two door features but does not define separate exterior frontages.
- **Builder-authored or unknown:** Coverage C would use Builder-authored linked views of this one location with one shared identity. The views and identity-link record are not source facts; no two-frontage claim is made. NPC position, view bearings, and approach route remain unknown unless explicitly authored and checked against topology.
- **Guarded facts:** Hidden vestry, Keeper's concealed knowledge, and the secret door are source-described secrets. Public knowledge boundaries must be authored later; no activation or effect is inferred.
- **Coverage:** C, D, E.

### 5. Fogroot Barrow Stalls

- **Scene ID:** `the_garden_of_demons:scene:fogroot-barrow-stalls`
- **Module:** `The_Garden_of_Demons` (published)
- **Area/location:** `GV001 / H03` (`Fogroot Barrow Stalls`)
- **Source file:** `modules/The_Garden_of_Demons/areas/GV001_BU.json` - SHA-256 `9176a18c58394ac47bb101f3e43a112fcb9454024ea0d38cdc70e91553893407`
- **Source-text SHA-256:** `945728477f2ac06ea120463cb31486ff88cc019d98127b291ca85de1d7d1bda5`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** Stalls cluster around a fogroot-covered barrow at the village edge. A spectral child wanders among stalls at dusk; a silver trail can lead behind the barrow. The source names a gathering ring of stones, a gravel approach from the village square, and an area connection to the Thornwound Wilds.
- **Source-supported relations:** Gravel path from the village square; stalls around the barrow; child moves among stalls; the stone ring is a gathering space; source-described cool, persistent mist and silver trail; location connectivity to H02 and area connectivity to the Thornwound Wilds (H01).
- **Builder-authored or unknown:** Exact multi-cell extents for barrow/path/stall boundary and their schematic cells need hand-authored labels. The ring of stones is a source-supported usable-space candidate, but its cells and relation to the barrow are not specified. Exact NPC position, cardinal orientation, and sensory gradients remain unknown.
- **Guarded facts:** The hidden cache beneath the barrow and the child's clue are DM-facing investigation hooks; public arrival must not state the cache location as known.
- **Coverage:** B, D, F.

### 6. Trial at the Door

- **Scene ID:** `the_hidden_city_of_numillian:scene:trial-at-the-door`
- **Module:** `The_Hidden_City_of_Numillian` (published)
- **Area/location:** `A000 / A01` (`Numillian / The Hidden City`)
- **Source files:**
  - `modules/The_Hidden_City_of_Numillian/areas/A000_BU.json` - SHA-256 `cb36dfe6ebe2eccc679d9ba9b218da00cf686bef3d06dd5bf3d5eedff4208900`
  - `modules/The_Hidden_City_of_Numillian/module_plot_BU.json` - SHA-256 `1ddddc7b10f063f7a18cabfc9e31a13acd8534cc0981e906a53a83510c781ee1`
- **Source-text SHA-256:** `96d0ef1579a7a80d05df443f375acbb1030e28825af546e2c8776f8b78c9fce9`
- **Lineage:** Declared independent; no adaptation lineage declared. Exact identity, reference, source hash, and known-ancestor checks found no match.
- **Source-grounded summary:** The party approaches rubble and vegetation concealing an illusory wall; Shuluth meets them and leads them to a stone watchtower. If they agree, Shuluth bars the tower door and begins the mindscape sequence, whose next plot point is TRIAL001.
- **Source-supported relations:** Approach to concealed wall, wall as threshold, Shuluth leading to tower focal point, tower-door transition into the trial, and next plot point TRIAL001. The source supplies the wall dimension and anti-flight ward as explicit facts; they are not inferred from a schematic.
- **Builder-authored or unknown:** No extra path geometry, compass bearing, view bearings, sensory gradient, or metric is proposed. Any linked view or detailed cell layout would require labelled Builder authorship.
- **Guarded facts:** The illusory rubble/vegetation and concealed warded wall are a source-described GM secret revealed by a source-listed Perception check. Preserve the audience boundary; do not expose it as publicly known on arrival.
- **Coverage:** A, E, F.

## Coverage matrix

`S` means the source supports the relevant fact or relation; `BA` means the coverage depends on later hand-authored and explicitly labelled staging; `U` means the relation stays unknown until separately established.

| Letter | Required coverage | Candidate(s) | Source support vs. Builder authorship / unknown |
| --- | --- | --- | --- |
| A | Approach -> threshold -> focal | `trial-at-the-door`; `shattered-anvil-crossing` | Numillian sequence is source-supported. Deepvault's approach-to-door mapping is not; label it Builder-authored. |
| B | Multi-cell path/terrain/boundary plus usable space | `abyssal-fracture`; `fogroot-barrow-stalls` | Source supports terrain and gathering-space candidates. Exact multi-cell extents/cells are Builder-authored; Ancient Lab usable space remains U until authored. |
| C | Shared identity across linked views, or separate frontages | `sanctum-of-fractured-truths` | One source location identity and two door features are supported; linked views and shared-view identity binding are BA. No separate-frontage claim. |
| D | Fixed anchors plus mobile NPC occupants | `fogroot-barrow-stalls`; `shrouded-lantern-encampment`; `sanctum-of-fractured-truths` | NPC identities/presence and environmental anchors are source-supported; exact initial placements and anchor-to-occupant spatial relations are BA or U. |
| E | Guarded knowledge or unknown mechanics | `trial-at-the-door`; `shattered-anvil-crossing`; `abyssal-fracture`; `sanctum-of-fractured-truths` | Source contains an illusion/secret, traps, or hidden knowledge. Do not invent any additional trigger/effect or public disclosure. |
| F | Arrival cues plus next-section transition potential | `trial-at-the-door`; `shrouded-lantern-encampment`; `fogroot-barrow-stalls` | Cues and transition links are source-supported; additional gradients, directions, or routes remain U unless authored from approved topology. |

## Exclusions and leakage summary

M1/D1 source modules are excluded wholesale: `Keep_of_Doom` (D1 list: 7 locations), `The_Thornwood_Watch` (6), and `The_Pumpkin_Kings_Curse` (7). The D1 location lists are recorded in `tmp/router-rollout/mapping-pilot/d1/d1-20261105-01/selection.json`. All 16 original M1 records and all nine owner examples are in `scripts/mise_en_scene/known_examples.json`; none is selected as a source. `Capture_Arena` is not in `modules/published_modules.json` and is excluded. The six selected module slugs are all distinct, listed in the published-module catalog, and outside the exclusions. Source identity/reference/hash and declared-lineage checks were run against all 25 catalog entries for each scene: zero exact/ancestor matches.

| Scene | Max source-text overlap (shared / ppm; example) | Max layout overlap (shared / ppm; example) | Max feature overlap (shared / ppm; example) | Review-required pairs |
| --- | --- | --- | --- | --- |
| `shrouded-lantern-encampment` | 4 / 66666; M1 `...V01...` | 1 / 250000; M1 `...tower_approach...` | 4 / 71428; M1 `...V01...` | None |
| `abyssal-fracture` | 3 / 49180; `owner:I` | 2 / 200000; `owner:F` | 2 / 40816; `owner:I` | None |
| `shattered-anvil-crossing` | 3 / 49180; `owner:I` | 1 / 200000; M1 `...tower_approach...` | 2 / 40000; `owner:I` | None |
| `sanctum-of-fractured-truths` | 3 / 49180; `owner:I` | 2 / 285714; `owner:G` | 1 / 23255; `owner:E` | `owner:G` layout 2 / 285714 (`behind`, `s`); `owner:H` layout 2 / 250000 (`approach`, `behind`) |
| `fogroot-barrow-stalls` | 4 / 85106; M1 `...AB01...` | 1 / 200000; M1 `...tower_approach...` | 3 / 73170; M1 `...AB01...` | None |
| `trial-at-the-door` | 2 / 40000; M1 `...AB03...` | 1 / 250000; M1 `...tower_approach...` | 2 / 43478; M1 `...AB03...` | None |

Only the two Xhalruun layout pairs reach review thresholds. They are flagged `REVIEW_REQUIRED`, not rejected; inspect them before any later freeze. All other source-only pairs are `NO_MATCH_WITHIN_BOUNDED_CHECKS`. Metrics and exact known IDs for every pair are in `selection.json`. A lexical screen is not semantic proof, and these results do not certify independence.

## Module diversity rationale

The proposal uses one candidate from each of six distinct published modules: wilderness camp, ravine, hazardous forge crossing, temple, barrow-edge market, and a hidden-city threshold/trial. This gives different source structures and narrative contexts without sampling any M1/D1 module. `A_Pottsfield_Burial` was not selected because its harvest-town/pumpkin material presents a plausible lineage concern with the excluded Pumpkin King sources; `Night_of_the_Restless_Dead` was not selected because its inspected source includes direct cross-module references to Pumpkin King material. These are conservative exclusions, not claims of proven ancestry.

## Limits and read-only verification

- This is only a six-scene selection draft. It is not a frozen source manifest, fixture set, rubric, score, evaluation, owner approval, or permission to run Section 2.
- No assignment seed was selected. No scoring, provider/LLM, network, live, or Capture_Arena work was performed.
- Module files were not written. SHA-256 values for all 14 inspected module/catalog files were captured before drafting and rechecked after writing; all were identical. Selected-source file hashes are listed above and in `selection.json`.
- Source records sometimes contain explicit mechanics or metrics. Preserve only source-supported values; do not turn schematic cells, adjacency, or named connections into additional access, compass, distance, sensory, or legality facts.
- The text/layout/feature fingerprints only measure bounded lexical overlap. They cannot establish semantic independence, derivative status, validity of module truth, or suitability for scoring.
- Exact anchor placement, view construction, multi-cell assignment, usable space where not explicit, and some scene-stage relations require later Builder authorship. Each such fact must be hand-authored and labelled, not presented as extracted.
- No Section 2 checkboxes were edited.
