# Tasks: Ancients Lab Lovecraftian Narrative Enhancement

## Phase 1: NPC Foundation (est. 2h)

- [x] **1.1** Populate `the_thing.description` in `module_context.json` (~400 chars, multi-interpretation entity description)
- [x] **1.2** Populate `facility_security_system.description` (~300 chars, Aegis as fractured AI)
- [x] **1.3** Populate `mutated_scavenger_leader.description` (~250 chars, Varn's playline-specific truth)
- [x] **1.4** Populate `security_construct.description` (~250 chars, Warden-3's corrupted memory)
- [x] **1.5** Populate `mutant_scavenger_lieutenant.description` (~300 chars, Grahl's multi-state condition)
- [x] **1.6** Populate `edda_coppervein.description` (~250 chars, post-survival interpretation)
- [x] **1.7** Expand `rambling_dwarven_survivor.description` (208 -> ~350 chars)
- [x] **1.8** Expand `archivist_automaton.description` (221 -> ~400 chars)
- [x] **1.9** Expand `damaged_security_overseer.description` (208 -> ~350 chars)
- [x] **1.10** Populate all 9 NPC `role` fields (~80 chars each)
- [x] **1.11** Populate all 9 NPC `faction` fields (~40 chars each)
- [x] **1.12** Verify: JSON syntax valid, all descriptions > 150 chars

## Phase 2: Plot Point Enrichment (est. 3h)

- [x] **2.1** Expand `mainObjective` in `module_plot_BU.json` (284 -> ~600 chars)
- [x] **2.2** Enrich PP004 `description` (~700 chars) and `plotImpact` (~350 chars)
- [x] **2.3** Enrich PP007 `description` (~650 chars) and `plotImpact` (~300 chars)
- [x] **2.4** Enrich PP008 `description` (~700 chars) and `plotImpact` (~350 chars)
- [x] **2.5** Enrich PP009 `description` (~700 chars) and `plotImpact` (~400 chars)
- [x] **2.6** Enrich PP012 `description` (~800 chars) and `plotImpact` (~400 chars)
- [x] **2.7** Enrich PP013 `description` (~1200 chars) and `plotImpact` (~500 chars) -- ending matrix
- [x] **2.8** Enrich PP010 and PP011 `description` and `plotImpact` (minor expansion, ~500 chars each)
- [x] **2.9** Enrich prioritized side quest descriptions (SQ002, SQ006, SQ008, SQ012-SQ024, min 12 of 24)
- [x] **2.10** Verify: JSON syntax valid, PP013 contains ending framework

## Phase 3: dmInstructions Primary Layer (est. 4h)

- [x] **3.1** Expand BA001 I01 `dmInstructions` (330 -> ~800 chars) - Shattered Forge Approach
- [x] **3.2** Expand BA001 I02 `dmInstructions` (330 -> ~750 chars) - Abyssal Fracture
- [x] **3.3** Expand BA001 I03 `dmInstructions` (330 -> ~850 chars) - Forsaken Outrider Encampment
- [x] **3.4** Expand FG001 I01 `dmInstructions` (330 -> ~900 chars) - Fused Iron Antechamber
- [x] **3.5** Expand FG001 I02 `dmInstructions` (330 -> ~950 chars) - Throne of Twisted Lineage
- [x] **3.6** Expand FG001 I03 `dmInstructions` (330 -> ~1000 chars) - Forgotten Splice Vault
- [x] **3.7** Expand AC001 I01 `dmInstructions` (363 -> ~950 chars) - Warped Sentinel Vestibule
- [x] **3.8** Expand AC001 I02 `dmInstructions` (363 -> ~1000 chars) - Fleshforged Observation Nook
- [x] **3.9** Expand AC001 I03 `dmInstructions` (330 -> ~1100 chars) - Huskbound Termination Cell
- [x] **3.10** Expand TTL001 I01 `dmInstructions` (407 -> ~1200 chars) - Twisted Forge Atrium
- [x] **3.11** Expand TTL001 I02 `dmInstructions` (407 -> ~1100 chars) - Bygone Mutation Vault
- [x] **3.12** Expand TTL001 I03 `dmInstructions` (407 -> ~1200 chars) - Runebound Isolation Cell (convergence point)
- [x] **3.13** Expand area-level `areaDescription` in all 4 area BU files (~500-650 chars each)
- [x] **3.14** Enrich `adventureSummary` on key locations where relevant
- [x] **3.15** Verify: All 12 locations have dmInstructions > 750 chars, standardized template

## Phase 4: Continuity Entry Framing (est. 30m)

- [x] **4.1** Expand `continuity.entry_state_variants.cold_start.summary` in `module_context.json`
- [x] **4.2** Expand `continuity.entry_state_variants.partial_context.summary`
- [x] **4.3** Expand `continuity.entry_state_variants.late_arc.summary`
- [x] **4.4** Verify: JSON syntax valid, entry summaries enriched

## Phase 5: LOVECRAFTIAN_NARRATOR_GUIDE.md (est. 2h)

- [x] **5.1** Create `modules/The_Ancients_Lab/LOVECRAFTIAN_NARRATOR_GUIDE.md` document structure
- [x] **5.2** Write 15 ending narration drafts (300-500 words each)
- [x] **5.3** Write playline transition matrix
- [x] **5.4** Write area-by-area atmospheric guide for each playline
- [x] **5.5** Write NPC quick reference table with per-playline interpretation
- [x] **5.6** Write atmospheric phrase bank
- [x] **5.7** Verify: Document complete, all 15 endings have drafts

## Phase 6: Validation (est. 30m)

- [x] **6.1** JSON parse check: all 6 modified JSON files
- [x] **6.2** Schema validation: `.venv/bin/python core/validation/validate_module_files.py --module The_Ancients_Lab`
- [x] **6.3** No-new-fields audit: diff against original to confirm no new keys
- [x] **6.4** ASCII compliance: no Unicode in enriched text
- [x] **6.5** Smoke test: module loads in-game without errors
