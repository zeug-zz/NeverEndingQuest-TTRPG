# Deepvault Narrative Enhancement Plan

> **Status**: Ready for implementation
> **Target module**: `modules/Into_the_Deepvault/`
> **Constraint**: NO JSON structure or field additions — narrative text development only within existing fields.
> **Narrator target**: GPT 5.4 Mini High via Python harness (single-turn context, no state tracking).
> **Reference**: Lessons from `plans/ancients-lab-narrative-enhancement.md` (completed 2026-05-04).

---

## 1. Module Baseline Assessment

### 1.1 Structural Inventory

| Asset | Count | Quality |
|---|---|---|
| Areas | 5 (DA001, OV002, HA003, RF004, SD005) | Good variety — dungeon/wilderness/mixed |
| Plot points | 20 (PP001-PP020) | Functional but flat; reads like quest journal entries |
| Side quests | 31 | ~~~Generic templates ("A mourning villager begs...")~~ |
| Locations | 15 (3 per area, I01-I03) | Strong room variety, traps, puzzles, DC checks |
| NPCs in module_context | 10 | 9 with empty description/role/faction; 1 partially filled |
| NPCs with scene authority | 4 (Derval, Varkhaz, Brunna, Duergar) | 6 NPCs exist only as module_context stubs |
| dmInstructions | 15 fields | Pure mechanics — zero atmosphere/interpretation/choice-framing |
| Cross-module refs | 0 | Standalone module |

### 1.2 Critical Gaps

1. **NPC vacuum**: 9 of 10 NPCs have empty `description`, `role`, and `faction`. Only Derval has a description (18 words: "A gaunt, frightened dwarven miner clings to the bars..."). The Narrator LLM encounters NPC names in plot text but has zero personality data to work with.

2. **dmInstructions are barren**: Every single `dmInstructions` field across all 15 locations is purely mechanical — "Perception DC 13 to notice the hollow pillar," "the golem attacks if disturbed." There is zero atmospheric guidance, NPC-interpretation scaffolding, or choice-framing language.

3. **No thematic spine**: The mainObjective is one sentence. Plot point descriptions are functional but flat. The module tells the Narrator *what happens* but never *what it means*.

4. **6 NPCs unplaced**: Foreman Ulric, Lady Brunna, Sergeant Halda, Archivist Gremli, Saboteur Rask, Spirit of Thane Durnic, Guardian Construct Beldrum — all registered in module_context but have `"appears_in": []` and no location bindings. They are referenced in plot descriptions but the Narrator cannot look them up by location.

5. **Continuity summaries generic**: All three entry-state variants use the same template language ("present the opening conflict and immediate objective clearly").

### 1.3 Strengths to Preserve

- Room-level gameplay design is solid — each location has distinct monster encounters, traps, DC checks, loot tables, and plot hooks.
- The 20-plot-point, 5-area crawl structure provides a clear progression arc.
- Duergar antagonist (Varkhaz the Stonebound) with rune-warriors has potential as a central villain.
- Spectral encounters (wraiths, guardian constructs, animated statues) recur across areas, creating a natural "ancestors/spirits" motif.
- Key items cross-reference between rooms (bronze key from Sentinel Alcove opens Shattered Relic Niche, etc.) — good puzzle-chain design.

---

## 2. Thematic Spine

### 2.1 Core Ambiguity

**"What were the dwarves preserving, and should it stay buried?"**

The module's name is *Into the Deepvault*. Every area descends deeper into something the ancient dwarves sealed away. The central narrative question is not "will the party stop the Duergar" but **"what are the Duergar actually trying to awaken, and does the party agree with stopping them?"**

### 2.2 Three Interpretive Stances (NOT playlines)

These are narrative flavours the Narrator LLM can weave into any scene based on the party's behaviour *in the current turn*. No state tracking. No emergence counting. No dominance scoring.

| Stance | Core Idea | The ancients were... | The Duergar are... | The spirits want... | Party posture |
|---|---|---|---|---|---|
| **PRESERVATION** | Vaults = containment | Sealing something catastrophic | Reckless fools breaking ancient seals | Protection, rest, warning the living | Cautious, defensive, respectful of wards |
| **RECLAMATION** | Vaults = birthright | Hoarding dwarven legacy out of fear | Claimants — aggressive but not necessarily wrong | The legacy to be reclaimed, they crave acknowledgment | Ambitious, treasure-seeking, claiming dwarven artifacts |
| **TRANSFORMATION** | Vaults = crucible | Harnessing change, not fearing it | Being changed by what they seek, becoming something new | Echoes of transformation — neither victims nor guardians, just records of what was | Curious, investigative, touching strange things |

### 2.3 Why Three Stances Instead of Five Playlines

The Ancients Lab used five simultaneous playlines with emergence tracking and dominance counting. This required the Narrator to:
- Remember which playline was dominant across turns
- Count triggers at decision points
- Select endings based on accumulated dominance

**GPT 5.4 Mini High cannot do this.** The Python harness feeds the Narrator one turn at a time. There is no cross-turn state persistence.

The three-stance system requires only:
- Read the enriched dmInstructions for the current location
- Observe the party's behaviour in this turn (are they cautioning each other? grabbing treasure? touching the glowing thing?)
- Choose one or two stance flavours that fit
- Narrate accordingly

No counting. No remembering. No ending-selection logic. The enrichment guides the Narrator's voice, not its decisions.

### 2.4 Stance Mapping to Areas

| Area | Preservation reads as... | Reclamation reads as... | Transformation reads as... |
|---|---|---|---|
| DA001 Shadowed Vaultlands | Ancient wards still holding, moss-grown seals, the entrance warns | Lost dwarven gold beckoning, the runes are treasure-maps, the portal is a vault door | The moss pulses, the stone breathes, entering changes you |
| OV002 Vaulted Marches | Sentinel statues guarding, echoes are alarm-calls, the relics are trapped for a reason | The alcoves hide unclaimed heirlooms, the pillars name forgotten clans | The mists shift perception, the statues' eyes follow, the relic-niche transforms what it holds |
| HA003 Ancestral Catacombs | Ghosts of alchemists died containing something, Derval's cell kept him safe, the runes are binding-wards | Family sigils scattered, alchemical recipes are dwarven patent, the ancestors want their work continued | The wraith is alchemy-gone-wrong, Derval is being changed by the whispers, the glass dais remakes whatever touches it |
| RF004 Forgebound Wastes | The molten rivers are seal-breaches, the ashen wraiths died holding the line, the smith's refuge is a last stand | The anvil-crossing was a forge-empire, the watchpost held treasures, the smith's tools are masterworks waiting for hands | The runes spiral through bone and metal alike, the golem is forge-spirit merged with scrap, the wastes transform everything they touch |
| SD005 Sundered Depths | The runeway's tapestries warn of tunneling too deep, the echo wraith screams alarms, the forge-lab was shut down for a reason | Varkhaz reads the runes as prophecy, the Deepvault holds the greatest dwarven power, the collapsed passages hide vaults | The lurkers are what happens to those who stay, the forge-tools animate independently, the echo wraith is sound-made-flesh |

---

## 3. Phase 1: NPC Population

### 3.1 Target

Fill `description`, `role`, and `faction` for all 10 NPCs in `module_context.json`. Each description: 150-300 characters, personality-rich, three-stance-aware. Each role: a short phrase capturing the NPC's function through all three stances (pattern: "PreservationRead / ReclamationRead / TransformationRead"). Each faction: the stance they most align with, or the faction context.

### 3.2 NPC Profiles

#### Foreman Ulric Flintlace
- **Role**: "Dwarven foreman who lost miners to the depths / Keeper of mining lore the Duergar covet / Man being changed by what he found below"
- **Faction**: "Deepvault Mining Company (Preservation-aligned)"
- **Description**: "Ulric Flintlace led the last legitimate mining expedition before the tremors started. He lost a dozen miners, including his own nephew, when the lower galleries collapsed — or were collapsed by something that pushed upward. His hands shake when he speaks of the Sundered Depths, and what worries him most is not what he lost underground but what he brought back: a recurring dream of stone that breathes. He wants the depths sealed (Preservation), but he also knows the ore the Duergar are chasing is worth more than every mine in the Marches combined (Reclamation), and he carries a fragment of rune-glass in his pocket that glows when he's alone (Transformation)."

#### Lady Brunna Ironsong
- **Role**: "Noble with ancestral claim to Deepvault Hold / Patron who funds the expedition / Descendant being called home by the stones"
- **Faction**: "House Ironsong (Reclamation-aligned)"
- **Description**: "Lady Brunna Ironsong carries the last signet ring of Deepvault Hold's founding clan. She has spent her fortune funding expeditions into the vaultlands, and she will spend whatever remains to see the Sundered Depths opened. To her, every sealed door is a theft — her ancestors built these vaults, and she intends to walk every hall they walked. She is not blind to the danger; she simply believes danger is the price of inheritance. But something in her voice wavers when she speaks of the 'Stonebound Guardian,' as if the title means more to her than she has told the party."

#### Sergeant Halda Stonebrow
- **Role**: "Pragmatic overseer of the outer vaults / Veteran who has seen what the vaults do to those who stay too long / Dwarf being changed by proximity"
- **Faction**: "Deepvault Garrison (Transformation-leaning)"
- **Description**: "Halda Stonebrow has spent more time in the Vaulted Marches than anyone alive. She can read the shifting mists, predict where the centipedes will nest next, and tell you which pillars are about to fall. She has also begun to speak to the statues — not as a madwoman, but as if she expects them to answer. She doesn't believe in sealing the vaults (too late for that) or in reclaiming them (too dangerous). She believes the vaults are changing her, and she wants to know into what. Her soldiers trust her completely; her superiors think she's been down here too long."

#### Archivist Gremli Amberfist
- **Role**: "Knowledge-seeker who knows more than she should / Living library of Deepvault lore / Dwarf who has read all three truths and cannot choose between them"
- **Faction**: "Independent scholar (all stances at once)"
- **Description**: "Gremli Amberfist carries a satchel of fragmentary records salvaged from every vault level. She can tell you which clan built which chamber, what the alchemists were trying to do in the Runescribed Vault, and why the Ironbound Soul Cells were constructed — but she will give you three answers to every question, because the records contradict themselves. She has read accounts describing the Deepvault as a prison for something that should never wake, as a treasure-house sealed by cowards, and as a crucible designed to transform the worthy. She does not know which account is true, and she has stopped trying to decide. She just wants more records."

#### Trapped Miner Derval
- **Role**: "Gaunt survivor who has seen something in the dark / Living warning the party must heed or ignore / Dwarf already partially transformed"
- **Faction**: "Deepvault Mining Company (victim)"
- **Description**: [Existing description to expand:] "Derval was part of Ulric's crew when the Ironbound Soul Cells collapsed around them. He has been trapped for days — or weeks, or longer, he cannot say — surviving on condensation and silence. He is gaunt, frightened, and haunted by ghostly whispers. But what frightens him most is not what he heard in the dark. It is what he answered back. He knows something about the spirits that the Archivist's records do not, and he knows something about the runes that Lady Brunna's genealogists have forgotten. Whether he will share it depends on whether the party treats him as a victim, a witness, or an oracle."

#### Saboteur Rask
- **Role**: "Duergar defector who knows Varkhaz's ritual / Opportunist playing both sides / Changed duergar seeking escape from the change"
- **Faction**: "Formerly Duergar Rune-Warriors (now unaligned)"
- **Description**: "Rask was one of Varkhaz's rune-carvers before he fled the ritual chamber. He will not say what he saw that made him run — only that Varkhaz is 'not wrong about the vaults, but wrong about what happens next.' Rask offers to sabotage the ritual in exchange for safe passage, but his definition of sabotage may differ from the party's. He still carries a rune-etched chisel that hums when near active wards, and he still refers to the Duergar as 'we' before correcting himself. He knows Varkhaz's patterns, his weaknesses, and his conviction. He also knows that Varkhaz was once right about something."

#### Spirit of Thane Durnic
- **Role**: "Ancient dwarven lord bound to a forgotten shrine / Spectral guardian who warns / Echo of the last dwarf who tried to seal the vaults"
- **Faction**: "Deepvault Ancestors (Preservation-aligned)"
- **Description**: "Thane Durnic died trying to seal the Sundered Depths. His spirit has lingered for centuries in a shrine the Duergar avoid, whispering warnings to any who will listen. He does not rage or threaten; he pleads. His voice is the sound of stone settling, of a door that has stayed closed for a thousand years. He knows what the ancient dwarves were containing and why they chose to bury it rather than destroy it. He will share this knowledge with any who promise to preserve the sacred relics from desecration. But his memory is not perfect — centuries of isolation have blurred the distinction between what he witnessed and what he only feared."

#### Guardian Construct Beldrum
- **Role**: "Damaged dwarven automaton guarding a collapsed hall / Neutral protector of what remains / Construct that has outlived its purpose but cannot stop"
- **Faction**: "Deepvault Defense Network (neutral)"
- **Description**: "Beldrum was built to protect the lower galleries. It has been doing so for so long that its original purpose is lost even to itself — it guards a collapsed hall because that is what it has always done. Half its runic arrays are dark. Its voice module produces fragments of ancient dwarven that no longer form coherent sentences. But it remembers flashes of its creator: a smith whose face it cannot describe but whose hands it can still picture, working the forges that would later become the Forgebound Wastes. If the party restores Beldrum enough to speak clearly, it will ask a question no one has asked it in a thousand years: 'Is the danger past?' The party's answer determines whether Beldrum becomes an ally, an obstacle, or simply shuts down."

#### Varkhaz the Stonebound
- **Role**: "Primary antagonist: Duergar rune-lord / Prophet who believes the vaults call to him / Dwarf who has already been changed and wants to complete the transformation"
- **Faction**: "Duergar Rune-Warriors (Reclamation-aligned, extreme)"
- **Description**: "Varkhaz the Stonebound is not a tyrant. He is a believer. The runes spoke to him when he first entered the Sundered Depths, and they have not stopped speaking since. He has carved their patterns into his own skin, and the stone of the lower vaults now answers to his voice. He genuinely believes he is completing what the ancient dwarves began — that they sealed the Deepvault not to imprison something but to preserve it for the worthy. To the Preservation-minded, he is a fool about to unleash catastrophe. To the Reclamation-minded, he is the most legitimate claimant to the vaults' legacy — just too extreme in his methods. To the Transformation-minded, he is proof of what the vaults do: they change you. The question is whether the party sees him as a villain to stop, a rival to outmaneuver, or a warning of what they might become."

#### Duergar Rune-Warriors
- **Role**: "Varkhaz's followers and ritual assistants / Collective antagonists / Duergar experiencing group transformation"
- **Faction**: "Duergar Rune-Warriors (Reclamation-aligned)"
- **Description**: "The Duergar Rune-Warriors followed Varkhaz into the depths not out of fear but out of shared conviction. They have each carved runes into their own flesh, and they move through the Sundered Depths with the confidence of those who believe the stone itself protects them. They are not mindless — individual warriors have names, rivalries, and doubts that the party might exploit. But collectively they represent something the party must reckon with: what if Varkhaz is right? What if the vaults were meant to be opened? The runes they carve are not just weapons; they are a language, and some of them, the party might find, are hauntingly beautiful."

### 3.3 NPC Placement Notes

The plan fills NPC personality fields but does NOT edit area-file `npcs` arrays (structural change). The following NPC-to-area relationships exist in plot text and should inform description writing:

| NPC | Referenced in | Scene-present? |
|---|---|---|
| Ulric Flintlace | PP017, SQ026 | No area binding |
| Brunna Ironsong | PP017 | No area binding |
| Halda Stonebrow | PP005 (implied: "local guides") | No area binding |
| Gremli Amberfist | SQ031 | No area binding |
| Derval | HA003-I02 npcs | YES — placed |
| Rask | PP019, SQ030 | No area binding |
| Durnic | SQ029 | No area binding |
| Beldrum | SQ028 | No area binding |
| Varkhaz | PP018-PP019, RF004-I02/I03 plotHooks | Referenced, not placed |
| Duergar | PP018-PP019 | Referenced, not placed |

---

## 4. Phase 2: dmInstructions Enrichment

### 4.1 Target

Each of the 15 location `dmInstructions` fields gets a standardized enrichment block appended to the existing mechanical content. The mechanical content (DC checks, monster triggers, room tactics) is preserved verbatim.

### 4.2 Enrichment Block Template

```
[existing mechanical dmInstructions preserved verbatim]

ATMOSPHERE: [2-3 sentences. Sensory description. What the room feels like.
Weaves in the three-stance perspective — is the stone warning, inviting, or
changing? Include specific sensory details the Narrator can use: smell, sound,
temperature, light quality, what catches the eye.]

KEY NPC INTERPRETATIONS: [Per-NPC lines for each NPC present or referenced
in this location. What each one represents through the three stances.
Pattern: "Name: PreservationRead / ReclamationRead / TransformationRead."
Keep each to 1 line.]

CHOICE FRAMING: [2-3 sentences. What narrative weight this room carries.
What player decisions here mean in terms of the three-stance themes.
Give the Narrator language to describe consequences without predicting them.]
```

### 4.3 Target Length

600-900 characters total per dmInstructions block. For 15 locations, that is approximately 12,000 characters. The existing mechanical content averages 200-400 characters, so combined dmInstructions will be 800-1,300 characters — well under the 2,000-character truncation threshold.

### 4.4 Priority Locations (Tier 1 — Most Narrative Weight)

These five locations are the module's narrative load-bearing points. They get full enrichment. The remaining 10 locations get leaner enrichment (400-600 chars).

#### SD005-I03: Hall of Echoing Stone (Priority: MAX)

Current dmInstructions: "The Echo Wraith is highly sensitive to noise — loud actions or combat draw its immediate attention. Roleplay opportunities exist if the party attempts to communicate in respectful silence or dwarven. Clever use of the echoes can allow the party to navigate or disorient the Wraith."

Enrichment:
```
ATMOSPHERE: The hall was once a throne room, a council chamber, a place where dwarven voices shaped policy. Now every sound returns multiplied, as if the stone itself is trying to speak back. The banners hang in tatters, their embroidery still legible if anyone dares to look closely — they name the three founding clans of Deepvault Hold, and they warn of a fourth clan whose name has been scratched out. The cracked dais still radiates faint warmth, as if someone — or something — sat upon it recently. The Echo Wraith does not merely attack noise; it is noise given form, a living record of the last words spoken in this hall before the vaults were sealed. Those words were either a warning, a claim of ownership, or a prayer for transformation — the Wraith screams all three at once.

KEY NPC INTERPRETATIONS:
- Echo Wraith: Preservation — the last alarm that the seal is failing / Reclamation — the voice of ancestors demanding acknowledgment / Transformation — sound-made-flesh, a record of what the vaults do to those who stay
- Varkhaz (if referenced): He has stood in this hall. The Wraith absorbed his voice. The party might hear fragments of his words in the echoes.

CHOICE FRAMING: Whether the party silences themselves to listen or shouts to be heard determines what the Wraith becomes. If they approach with silence and respect, the Wraith may share what it has absorbed — fragments of dwarvish, a name, a warning. If they fight, the Wraith dies screaming the same three meanings it has always screamed. Either way, the hall will record their words for the next visitors, and the party should know this: whatever they say here, the Echo Wraith will repeat forever.
```

#### RF004-I02: Ember-Scarred Watchpost (Priority: HIGH)

Current dmInstructions: "The wraiths attack any who enter, but can be placated with a successful Persuasion check or a proper offering (such as returning a found relic). The journal can be deciphered with Investigation. The murder holes provide cover for defenders."

Enrichment:
```
ATMOSPHERE: The watchpost stinks of old smoke and older grief. The ashen wraiths are not mindless — they are dwarves who died holding this position, and they are still holding it. Their spectral forms flicker between the soldiers they were and the burned silhouettes fused into the walls. The murder holes offer sightlines through which nothing living has moved in centuries, but the wraiths still watch them. The journal lies where its author fell — the last entry is unfinished, the quill still beside it. The watchpost's defenders held this hall against something that came from below, and they succeeded — the something never passed. The question is: was what they held back a monster, a rival clan, or the first wave of a transformation they refused to accept?

KEY NPC INTERPRETATIONS:
- Ashen Wraiths: Preservation — martyrs who died sealing a breach / Reclamation — warriors who died defending dwarven territory against invaders / Transformation — dwarves caught mid-change by whatever they were fighting
- Varkhaz: The wraiths whisper his name with hatred. They call him "the opener." But one wraith, if reasoned with separately, admits that Varkhaz's runes resemble the ones the ancient defenders used — and wonders aloud if he is completing their work or betraying it.

CHOICE FRAMING: Placating the wraiths through offering or persuasion is not just a combat-skip — it is a narrative statement. It says the party respects the dead. Fighting them says the party sees only obstacles. The journal offers a middle path: if deciphered, it reveals the defenders' oath, and speaking that oath aloud in dwarvish may grant the party something the wraiths have guarded since the day they died.
```

#### HA003-I02: Ironbound Soul Cells (Priority: HIGH)

Current dmInstructions: "If the party tries to free Derval, the Ironbound Guardian animates and attacks. Derval can provide information on both the cells and the Shatterglass Experimentum if convinced to trust the party."

Enrichment:
```
ATMOSPHERE: The Ironbound Soul Cells were built to hold something worse than prisoners. The spectral manacles still dangling from the ceiling were designed to bind spirits, not bodies. The desperate scratchings on the walls are dwarvish pleas for freedom, but some of them are not from prisoners — they are from the guards, who realized too late that the cells were not containing something from outside but changing something from within. Derval is the first living soul to occupy these cells in centuries, and the ghosts are curious about him. The Ironbound Guardian does not merely patrol — it remembers every prisoner it ever watched, and some of them have left impressions on its soul-forged armor.

KEY NPC INTERPRETATIONS:
- Derval: Preservation — a victim who proves the vaults are still dangerous / Reclamation — a survivor who found something worth finding (if they ask) / Transformation — a dwarf who talked back to the whispers and is no longer entirely a dwarf
- Ironbound Guardian: Preservation — eternal warden doing its duty / Reclamation — soul-forged protector of dwarven prisoners / Transformation — powered by the souls of former prisoners, it carries their memories
- Derval's Amulet: Preservation — protection charm his grandmother gave him / Reclamation — family keepsake proving his lineage / Transformation — the amulet glows faintly now, and it did not before he was trapped

CHOICE FRAMING: Freeing Derval is not just a rescue — it is accepting responsibility for whatever he brought back from the dark. The party can question him here, in the cells, where the ghosts will listen and remember. Or they can take him to the surface, where what he knows may change how Ulric, Brunna, or Halda sees the expedition. Either way, Derval is not just a victim. He is evidence.
```

#### HA003-I01: Runescribed Alchemy Vault (Priority: HIGH)

Current dmInstructions: "The vault is warded. If the party handles reagents carelessly, a volatile reaction may trigger. The wraith defends the vault, only manifesting if an attempt is made to disturb the main workbench or notes."

Enrichment:
```
ATMOSPHERE: The alchemy vault smells of reagents that should not still be active — acrid copper, sweet rot, and something that tingles in the nostrils like lightning about to strike. The runes on the granite benches pulse in patterns that echo breathing. The Restless Alchemical Wraith is not simply a ghost — it is the residue of a failed experiment, an alchemist who became what he was trying to create. The experiment notes describe attempts to "bind spirit to stone" and "forge a vessel that can hold the awakening." The notes stop mid-sentence. The final reagent is still in its vial, uncorked. The mural fragments show dwarven alchemists whose eyes have been replaced with gemstones — whether this depicts a goal they achieved or a warning of what happened to those who failed is not recorded.

KEY NPC INTERPRETATIONS:
- Restless Alchemical Wraith: Preservation — died trying to bind something that should not be bound / Reclamation — died trying to extract power from the vaults' magic / Transformation — became what he was studying; the experiment worked too well
- The Key to Ironbound Soul Cells: Preservation — kept separately because the cells must be opened with care / Reclamation — a key to dwarven territory that was locked / Transformation — the key is warm, and it leaves a faint residue on the hand that holds it

CHOICE FRAMING: The party can take the experiment notes and treat them as recipe or warning. They can disturb the workbench and face the wraith, or leave the vault as they found it — a tomb for an alchemist who died at his bench. If they read the notes carefully, they will find a reference to the Ironbound Soul Cells that explains why those cells were built: they were not a prison, but a laboratory for binding spirits. The cells held test subjects. Derval is in one of them now.
```

#### DA001-I01: Stonewrought Threshold (Priority: HIGH)

Current dmInstructions: "This is the main entry into the Vaultlands. Use the archway as a dramatic introduction. If the party investigates the stonework, a DC 12 Investigation check reveals the loose outcropping conceals a small cache. The claw marks can be traced with a DC 13 Survival check."

Enrichment:
```
ATMOSPHERE: The Stonewrought Threshold is a mouth. The archway yawns open beneath centuries of moss, and the tunnel beyond exhales air that is cooler than the surface and tastes faintly of old metal. The carved runes are warnings, but they are written in three different hands — one that speaks of sealing, one that speaks of inheritance, and one that speaks of change. The loose outcropping was placed deliberately: someone wanted this cache found. The claw marks in the moss are not animal — they are dwarven, but the hands that made them had too many fingers. The explorer's journal in the cache is illegible except for one phrase: "beware the sigils in the dark." The sigils it warns about are not the runes on the archway. They are further down.

KEY NPC INTERPRETATIONS:
- No NPCs present, but this is where the module's thematic spine is introduced. The three different hands on the archway runes foreshadow the three stances. The Narrator should describe them without naming the stances directly.

CHOICE FRAMING: The Threshold is the first narrative beat. How the party reacts to the archway — whether they read the runes as warning, invitation, or record — should colour the Narrator's description of everything that follows. If they hesitate, the tunnel exhales again. If they stride through, the runes flicker once and go dark. If they investigate, the loose stone gives up its cache and the journal's warning sets the tone for the descent. This is where the module begins to mean something. The Narrator should make the party feel that crossing this threshold is not a casual choice.
```

### 4.5 Remaining Locations (Tier 2 — Lean Enrichment)

The remaining 10 locations get leaner ATMOSPHERE + CHOICE FRAMING blocks (400-600 chars), referencing NPCs only when present:

| Area | Location | Key NPC present? |
|---|---|---|
| DA001 | I02 Echoed Antechamber | No (Giant Wolf Spider) |
| DA001 | I03 Runesmith's Remnant | No (Animated Tools) |
| OV002 | I01 Echoed Pillar Crossing | No (Giant Centipedes) |
| OV002 | I02 Silent Sentinel Alcove | No (Animated Statue) |
| OV002 | I03 Shattered Relic Niche | No (Crawling Claws) |
| HA003 | I03 Shatterglass Experimentum | No (Shatterglass Amalgam) |
| RF004 | I01 Shattered Anvil Crossing | No (Molten Bone Golem) |
| RF004 | I03 Forgotten Smith's Refuge | No (Forged Sentry) |
| SD005 | I01 Shattered Runeway | No (Chasm Lurkers) |
| SD005 | I02 Twilight Forge Lab | No (Animated Forge-Tools) |

---

## 5. Phase 3: Main Objective & Plot Points

### 5.1 Target

Enrich `mainObjective` and each of the 20 plot point `description` and `plotImpact` fields in `module_plot_BU.json`. Add 1-3 sentences of thematic framing per field. Preserve all functional content.

### 5.2 mainObjective Rewrite

From:
> "Delve beneath Deepvault Hold and its surrounding lands to uncover the ancient dwarven secrets, confront awakening forces, and prevent the catastrophic resurgence of powers that threaten to devastate the surface world."

To:
> "Delve beneath Deepvault Hold and its surrounding lands to uncover the ancient dwarven secrets, confront awakening forces, and decide the fate of powers that threaten to reshape the surface world. The question at the heart of every vault, every catacomb, every forge-scarred waste is the same: what were the dwarves preserving, and should it stay buried? The ancient wards may be containment seals holding back catastrophe. They may be treasure-vaults hoarding dwarven birthright. Or they may be crucibles designed to transform whatever enters — including the party. The Duergar, led by Varkhaz the Stonebound, believe they already know the answer. The spirits of the dead offer three different warnings. The choice of which warning to believe — and what to do about it — belongs to the party. Every chamber they enter, every relic they touch, every ancestor they speak to will push them toward preservation, reclamation, or transformation. The vaults do not merely contain a secret. They are the secret."

### 5.3 Plot Point Enrichment Examples

For each of the 20 plot points, add 1-3 sentences of thematic framing to the `description` and `plotImpact` fields. Below are representative examples:

#### PP001: "Into the Shadowed Vaultlands"
**Description add**: "The legends tell three different stories about the vaults: some say they hold a monster that will end the world, some say they hold the greatest treasure ever forged by dwarven hands, and some say the vaults themselves are alive and change anyone who enters. The locals who warn of prowling shadows cannot agree which story is true — but they all agree the tremors are getting worse."

#### PP004: "The Vault's Heart"
**Description add**: "The spirit-warden does not simply guard treasure. It guards a choice. Destroying it may release whatever it was containing; appeasing it may mean accepting its terms, which the party will not fully understand until later; ignoring it leaves the vaults' deepest question unanswered. The 'legendary treasure' is real, but what makes it legendary is not its gold value — it is the information it contains about what lies deeper."

**plotImpact add**: "This is the module's first moral nexus. The party's choice here — destroy, appease, or bypass — is the first signal of which stance they lean toward. The spirit-warden will remember."

#### PP008: "Echoes Resolved"
**Description add**: "The powers awoken in the Marches are not a single entity. They are echoes of every dwarf who ever made a choice in these halls — to seal, to claim, to transform. The party's resolution of the Marches arc determines whether those echoes fall silent, turn hostile, or begin to speak in voices the party can understand."

**plotImpact add**: "The resolution of the Vaulted Marches is the party's first irreversible statement. From this point forward, spirits and factions across all remaining areas will respond to the party based on what they did here. The vaults are watching."

#### PP012: "Into the Deepvault: Confronting the Catacomb's Wrath"
**Description add**: "The Lord or Lady of the Dead is not merely a boss. It is an ancestor who made the same choice the party is now making — and chose wrong. Whether the party kills it, reasons with it, or learns from it determines what the catacombs become: a sealed tomb, a reclaimed hall of ancestors, or a place where the boundary between living and dead has been permanently thinned."

**plotImpact add**: "The fate of the catacombs is the party's second irreversible statement. If they brought peace through violence, the ancestors will accept it but not bless it. If they brought peace through understanding, the ancestors will offer something the party cannot get anywhere else: knowledge of the Sundered Depths from someone who has been there."

#### PP019: "The Shattered Vault"
**Description add**: "Varkhaz the Stonebound is not a cackling villain. He is a dwarf who has read the same runes the party has been reading and reached a different conclusion. His ritual is not destruction — it is completion. He believes he is opening a door that was always meant to be opened. The party can stop him, join him, or try to find a third path that neither the ancient seals nor the Duergar anticipated. The runes themselves will respond to whichever choice the party makes."

**plotImpact add**: "This is the module's final moral nexus. Whether the ancient horror wakes, stays sealed, or transforms into something no one predicted depends on whether the party treats Varkhaz as enemy, rival, or prophet. Allies gained in prior areas — or enemies made — arrive here."

#### PP020: "Into the Deepvault: The Abyss Stirs"
**Description add**: "The final outcome is not binary. Whether the party sealed the horror, unleashed it, claimed its power, or transformed alongside it — the Deepvault will remember. The echoes of their choices will shape the region for generations, and the survivors will tell three different stories about what happened in the Sundered Depths. All three will be true."

**plotImpact add**: "This is an epilogue, not just a victory screen. The party's deeds echo into legend, and the legend will be told differently by those who believe in preservation, those who believe in reclamation, and those who believe the vaults have always been a crucible. The module does not tell the party which story is correct. It lets them decide."

### 5.4 Side Quest Enrichment

All 31 side quests get stance-aware flavour in their `description` and `plotImpact` fields. The functional content (what happens, what the reward is) is preserved. Below are representative examples:

#### SQ002: "Echoes in the Mist" (DA001)
**Description add**: "The lost explorer's spirit does not merely want peace — it wants to be remembered. It whispers three things: a warning about the vaults' guardians (Preservation), the location of an unclaimed cache (Reclamation), and a fragment of a song the explorer's mother used to sing, which it has been singing to itself for so long the words have changed (Transformation)."

#### SQ008: "Echoes of the Past" (OV002)
**Description add**: "The spectral figure does not simply mutter of a 'broken pact' — it accuses. The pact was between the ancient dwarves and something in the depths. Whether the pact was broken by the dwarves (who sealed what they had promised to honour), by the depths (which took more than was offered), or by time itself (which erodes all agreements) depends on who is telling the story. The apparition tells all three versions."

#### SQ017: "The Broken Oath" (HA003)
**Description add**: "The spectral ancestor does not know what the shattered family sigil originally meant. It knows only that restoring it will pacify some spirits — and anger others, who believe the sigil represents a broken promise. The party must decide whether the sigil was a seal of protection, a claim of ownership, or a symbol of transformation — and their answer will determine which spirits are pacified."

#### SQ025: "The Final Bargain" (RF004)
**Description add**: "The spirit bound to the Crucible offers a pact, but the terms change depending on what the party has already done. If they have been preserving seals, the spirit offers to reinforce what remains. If they have been reclaiming, the spirit offers power over the wastes. If they have been transforming, the spirit offers to show them what the Crucible was truly built to do — and the answer may not be a weapon."

---

## 6. Phase 4: Continuity Entry Variants

### 6.1 Target

Enrich the three continuity entry-state variant summaries in `module_context.json` so the Narrator enters any play state with a sense of the module's thematic ambiguity.

### 6.2 Enriched Summaries

#### cold_start
From:
> "Party enters Into the Deepvault with no prior continuity context. Present the opening conflict and immediate objective clearly."

To:
> "Party enters Into the Deepvault with no prior continuity context. Present the opening conflict and immediate objective clearly. Introduce the central ambiguity: the vaults beneath Deepvault Hold may be a prison containing something catastrophic, a treasure-house hoarding dwarven birthright, or a crucible designed to transform whatever enters. Let the party's initial reactions — caution toward the archway runes, curiosity about the hidden cache, eagerness to descend — guide which interpretation the Narrator emphasizes in early scenes."

#### partial_context
From:
> "Party enters Into the Deepvault with partial prior context. Reinforce known clues before branch-critical decisions."

To:
> "Party enters Into the Deepvault with partial prior context. Reinforce known clues before branch-critical decisions. Remind the party that the vaults have been interpreted three ways by those who came before: as prison, as treasury, as crucible. The spirits, the records, and the survivors all tell different versions of the same story. The party's prior context may incline them toward one interpretation — but the vaults reward those who question what they think they know."

#### late_arc
From:
> "Party enters Into the Deepvault in late-arc state. Provide compact recap and preserve ending accessibility."

To:
> "Party enters Into the Deepvault in late-arc state. Provide compact recap and preserve ending accessibility. The three interpretations of the vaults — prison, treasury, crucible — should still feel viable. The party's accumulated choices may have tilted toward one stance, but the final areas (Forgebound Wastes, Sundered Depths) contain evidence for all three. Varkhaz the Stonebound represents one possible answer; the spirits offer alternatives. The ending should feel like a choice, not an inevitability. Even in late-arc, the vaults can still surprise."

---

## 7. Implementation Order & File Modification List

### 7.1 Order

1. **Phase 1 — NPC population** (`module_context.json`). Write all 10 NPC description/role/faction entries. This establishes the character vocabulary the other phases reference.
2. **Phase 2 — dmInstructions enrichment** (5 area BU files). Start with the 5 Tier-1 priority locations, then the 10 Tier-2 locations. Each location's enrichment block references NPCs by name, so Phase 1 must come first.
3. **Phase 3 — Main objective + plot points + side quests** (`module_plot_BU.json`). The enriched plot descriptions reference the three-stance framework established in Phase 2.
4. **Phase 4 — Continuity summaries** (`module_context.json`). Shortest phase; done last because it synthesizes the vocabulary developed in earlier phases.

### 7.2 Files Modified

| File | Section(s) Modified | Approximate Chars Added |
|---|---|---|
| `module_context.json` | 10 NPC entries (desc/role/faction), mainObjective, 3 continuity summaries | ~8,000 |
| `DA001_BU.json` | 3 location dmInstructions fields | ~2,400 |
| `OV002_BU.json` | 3 location dmInstructions fields | ~2,400 |
| `HA003_BU.json` | 3 location dmInstructions fields | ~2,400 |
| `RF004_BU.json` | 3 location dmInstructions fields | ~2,400 |
| `SD005_BU.json` | 3 location dmInstructions fields | ~2,400 |
| `module_plot_BU.json` | mainObjective, 20 plot descriptions + plotImpact, 31 side quest descriptions + plotImpact | ~14,000 |
| **Total** | | **~34,000 characters** |

### 7.3 Zero Structural Changes

- No new JSON keys
- No schema modifications
- No area-file `npcs` array additions
- No field type changes
- Existing mechanical data (DC checks, monster stats, trap triggers, loot tables) preserved verbatim
- Only `string` fields with narrative text content are modified

---

## 8. Validation Gate

After all four phases are written, run:

```bash
.venv/bin/python core/validation/validate_module_files.py --module Into_the_Deepvault
```

Expected: 100% pass (no regressions). Since only string field values are modified and no structural changes are made, validation should remain green.

ASCII compliance check:
```bash
python3 scripts/check_ascii_compliance.py --summary-only
```

Expected: 0 violations in modified files.

---

## 9. Limitations and Risks

1. **NPC placement remains unresolved**: The plan fills NPC personality data but does not add NPCs to area-file `npcs` arrays (that would be a structural change). The Narrator will encounter enriched NPC data when those NPCs appear in plot point descriptions, but they remain invisible to "who is in this room?" queries unless already placed (only Derval is placed).

2. **Side quest NPC cross-references**: Some side quests reference NPCs (Ulric in SQ026, Gremli in SQ031) but those NPCs have no `appears_in` bindings. The enriched side quest descriptions make these NPCs feel more real, but the structural gap remains.

3. **Token budget for Narrator**: dmInstructions blocks feed directly into the narrator prompt. At ~1,000 chars per block, 15 locations add ~15,000 chars to the total prompt budget. The compressed system prompt handles this through truncation/compression, but very long sessions may see enrichment trimmed. The design front-loads critical narrative content in the first ~600 chars of each block so that truncation drops atmosphere before it drops NPC interpretation.

4. **No cross-turn memory**: The three-stance system is explicitly designed for single-turn context. If the Python harness changes to support stateful narrators, a deeper playline-tracking system could be layered on top. The current design makes no assumptions about future harness capability.

5. **Duergar Rune-Warriors are a collective NPC**: The module references "Duergar Rune-Warriors" as a single entity in module_context. In gameplay, they function as multiple individual enemies. The description treats them as a collective with shared conviction, but individual warrior personalities are not defined. This may limit the Narrator's ability to differentiate duergar encounters.

---

## 10. Post-Implementation Optional Work

The following enhancements would improve narrative depth but are out of scope for Phase 1-2 (require new content creation or unrelated subsystems):

1. **Individualize Duergar Rune-Warriors**: Create 2-3 named duergar NPCs with distinct personalities for the ritual chamber (PP019).

2. **Cross-module continuity refs**: Add `cross_module_refs` entries connecting Deepvault to other dwarf-themed modules (e.g., the dwarven elements in Ancients Lab or Keep of Doom).

3. **Audio/visual cues**: The Echo Wraith (SD005-I03) and Ashen Wraiths (RF004-I02) are strong candidates for future multimedia enrichment — audio stings, ambient loops, or portrait art.

---

## 11. Phase 2: Structural NPC Placement (Planned)

> **Status**: Planned — execute after Phase 1 narrative enrichment is validated and committed.
> **Constraint**: Structural changes — adds NPCs to area-file `npcs` arrays and populates `appears_in` bindings in module_context.
> **Dependency**: Phase 1 must complete first so NPC personality data (description/role/faction) is available.

### 11.1 Objective

Phase 1 fills NPC *personality* fields. Phase 2 makes them *mechanically real* — the Python harness will know they're present in rooms, validate their arrivals, include them in combat rosters, and surface them through the NPC arrival state-sync guard. Without this phase, the enriched NPCs exist only as prompt-level flavour for the Narrator LLM.

### 11.2 What Gets Added

For each NPC, two things:

1. **`appears_in` entries** in `module_context.json` — lists which area files and location IDs the NPC can be found in. This is the harness-level lookup that tells Python "this NPC exists at this location."

2. **`npcs` array entries** in area `*_BU.json` files — the actual NPC object in each location's `npcs` array, with name, description, attitude, and optional role/type fields matching the area schema.

### 11.3 Placement Map

#### Area SD005: The Sundered Depths (6 NPCs + 1 collective)

| NPC | Location | Rationale | Attitude | npcType |
|---|---|---|---|---|
| **Urlic Flintlace** | SD005 I01 (Shattered Runeway) | PP017 describes him at "Grayspire's End," speaking to the party near the fissure entrance. He funds the expedition; he is at the threshold of the Sundered Depths. | Friendly (quest-giver) | allied |
| **Brunna Ironsong** | SD005 I01 (Shattered Runeway) | PP017 places her with Ulric, summoning the party. She is the patron; she does not enter the depths herself but briefs the party. | Friendly | allied |
| **Rask** | SD005 I01 (Shattered Runeway) | PP019 and SQ030 place him between the runeway and the ritual chamber. He is a defector encountered on approach. Best placed in I01 as a conditional encounter: appears after PP017 resolves, offers to guide the party. | Neutral / Conditional hostile | npc_companion (conditional) |
| **Beldrum** | SD005 I02 (Twilight Forge Lab) | SQ028 says "guards a collapsed hall." The forge-lab contains dormant constructs and alchemical equipment — Beldrum fits as a damaged automaton among the half-built guardians. | Neutral (conditional — activates if lab is disturbed or if party approaches a specific workbench) | guardian |
| **Durnic** | SD005 I03 (Hall of Echoing Stone) | SQ029 says "forgotten shrine." The hall is the most sacred space in SD005; it contains banners, a cracked dais, and the Echo Wraith. Durnic manifests in a shrine alcove within this hall. | Neutral (can become friendly or hostile) | spirit |
| **Varkhaz** | SD005 I03 (Hall of Echoing Stone) | PP018-PP019 place him at the ritual chamber. The hall is the ritual site — the cracked dais is where he works. He appears when the party arrives. | Hostile (boss) | villain |
| **Duergar Rune-Warriors** | SD005 I02 (Twilight Forge Lab) | PP018 says they guard the approaches. The forge-lab is the antechamber before the hall. Placed as a group (2-3 warriors). | Hostile | duergar |

#### Area OV002: The Vaulted Marches (1 NPC)

| NPC | Location | Rationale | Attitude | npcType |
|---|---|---|---|---|
| **Halda Stonebrow** | OV002 I01 (Echoed Pillar Crossing) | PP005 implies local guides in the Marches. The pillar crossing is the entry point to OV002. She is described as a pragmatic overseer — she would be found here, observing the mists. | Friendly / Neutral | overseer |

#### Area HA003: Ancestral Catacombs (1 NPC)

| NPC | Location | Rationale | Attitude | npcType |
|---|---|---|---|---|
| **Gremli Amberfist** | HA003 I01 (Runescribed Alchemy Vault) | SQ031 has her begging the party to find Derval. She is a scholar of the vaults. The alchemy vault contains the experiment notes and the key to the Ironbound Soul Cells — exactly where an archivist would be working. She is investigating the notes already. | Friendly | scholar |

### 11.4 NPC Objects — Schema Shape

Area-file `npcs` entries follow the area schema. The minimum for any NPC addition:

```json
{
  "name": "NPC Name Here",
  "description": "Brief in-world appearance and behaviour for the Narrator.",
  "attitude": "Friendly | Neutral | Hostile",
  "npcType": "allied | npc_companion | vendor | trainer | quest_giver | neutral | spirit | villain | guardian | duergar | scholar",
  "conditions": []
}
```

Optional fields (add where relevant):
- `"combat": {}` — if the NPC can join combat
- `"spells": []` — if the NPC has spellcasting
- `"inventory": []` — if the NPC carries items the party can acquire
- `"role": ""` — narrative role tag

### 11.5 `appears_in` Format in module_context.json

Each NPC gets an `appears_in` array with objects binding to area + location:

```json
{
  "npcs": {
    "Urlic Flintlace": {
      "name": "Urlic Flintlace",
      "description": "...",
      "role": "...",
      "faction": "...",
      "appears_in": [
        {"areaId": "SD005", "areaName": "The Sundered Depths", "locationId": "I01", "locationName": "Shattered Runeway"}
      ]
    }
  }
}
```

### 11.6 Special Cases

#### Gremli Amberfist — conditional movement

Gremli starts in HA003-I01 but after the party rescues Derval from HA003-I02, she may move to the Soul Cells to examine them. This is a natural post-rescue behaviour:
- Primary placement: HA003-I01 (Runescribed Alchemy Vault)
- After Derval is freed: HA003-I02 (Ironbound Soul Cells) — Gremli arrives to study the spectral manacles and dead alchemists' remains.

Implementation: add her to both locations with a conditional note in dmInstructions. The Narrator handles the movement narratively; Python treats her as present in whichever location the Narrator places her.

#### Duergar Rune-Warriors — collective vs. individual

Module_context has one entry for "Duergar Rune-Warriors" as a collective. In area files, they appear as multiple individual entries (2-3 warriors) because the combat system expects individual targets. The module_context entry remains collective; the area entries are individual combatants.

#### Derval — already placed

Derval already exists in HA003-I02's npcs array. Phase 2 does not duplicate him. His `appears_in` binding is already present if the module_context schema includes it.

### 11.7 Files Modified in Phase 2

| File | Changes |
|---|---|
| `module_context.json` | Add `appears_in` arrays to 9 NPC entries (all except the Duergar collective, which gets `appears_in` but no area-binding change — they appear through the individual warrior entries) |
| `SD005_BU.json` | Add NPC objects to I01 npcs (Urlic, Brunna, Rask), I02 npcs (Beldrum, Duergar warriors x2-3), I03 npcs (Durnic, Varkhaz) |
| `OV002_BU.json` | Add NPC object to I01 npcs (Halda) |
| `HA003_BU.json` | Add NPC object to I01 npcs (Gremli) |

### 11.8 Post-Phase 2 Verification

```bash
# Validate module still passes
.venv/bin/python core/validation/validate_module_files.py --module Into_the_Deepvault

# Check for NPC placement gaps (should return zero)
.venv/bin/python scripts/module_semantic_authority_audit.py --module Into_the_Deepvault --json

# Verify area files parse correctly and npcs arrays are valid
python3 -c "
import json
for area in ['DA001','OV002','HA003','RF004','SD005']:
    with open(f'modules/Into_the_Deepvault/areas/{area}_BU.json') as f:
        data = json.load(f)
    for loc in data['locations']:
        npc_count = len(loc.get('npcs', []))
        print(f'{area}-{loc[\"locationId\"]}: {npc_count} NPCs')
"
```

Expected results:
- All 15 locations parse
- NPC counts: DA001 0/0/0, OV002 1/0/0, HA003 1/1/0, RF004 0/0/0, SD005 3/4/4
- Validation: 100% pass (NPCs are valid schema entries)
- Semantic audit: no "not placed in any location" issues for enriched NPCs

### 11.9 Phase 2 vs. Phase 1 Boundary

| | Phase 1 (Narrative) | Phase 2 (Structural) |
|---|---|---|
| Edits `module_context.json` | Yes — description/role/faction | Yes — appears_in arrays |
| Edits area `*_BU.json` | Yes — dmInstructions strings only | Yes — npcs arrays |
| Adds new JSON keys | No | Yes — npcs array entries in location objects |
| Adds new location-level objects | No | Yes — NPC objects |
| Schema validation impact | None (only string values change) | Minor (adds valid schema-compliant npcs entries) |
| Python harness impact | None (prompt-only) | Significant (NPCs become mechanically real) |
| Requires schema changes | No | No (npcs array is existing schema field) |

### 11.10 Execution Order

1. Run Phase 1 narrative enrichment and commit.
2. Validate Phase 1 (no regressions).
3. Execute Phase 2 structural placement.
4. Run validation and semantic audit.
5. If structural placement reveals NPC files that need creation (e.g., if Beldrum or Durnic need standalone NPC JSON files for combat statistics), create those as a Phase 2A follow-up.
6. Commit Phase 2.

---
