# Firelight G0 Gap Inventory

Audit basis: the fork plan and source, plus the read-only Firelight v0.1.0
checkout at `e807382cac6d`. No Firelight command was run. This is a G0 design
input, not runtime authorization; the plan requires an accepted ADR before the
Narrator P0 event envelope is ratified (`plans/v2-firelight.md:3,53-70,201`).

## 1. Authority, family registry, and boundaries

Python remains the host and canonical store: character JSON, `party_tracker`,
encounter files, and module areas. Mutations use `update_character_info()` and
`safe_write_json()`; a separate campaign-scoped Firelight document is written
atomically (`plans/v2-firelight.md:53-63`). Firelight is stateless and does not
open files (Firelight docs/PROTOCOL.md, "opening"; docs/LIVE_STATE.md,
"Facts and totals").

The intended family sequence is:

- G3: storage/custody, trade/catalogue/stock, charged items and recharge.
- G4: coins, inventory possession, equipment, worn effects and AC.
- G5: HP/resources, slots, rests, timed conditions/concentration, ammunition,
  saves outside combat, and clock. Combat bookkeeping is SC-owned.
- G6: XP/level tables, quest state/logs, and location occupants.
- Track F owns scene layout, zones, cover and sightlines. Firelight routes and
  travel are a separate cross-track seam.
- Do not adopt Firelight journal or relationships in v0.1.0. Keep attack
  resolution, tactical decisions, enemy/ally control, and scene checks in
  Python.

These boundaries follow `plans/v2-firelight.md:42-47,104-113,185-195,213-225`.
G0 must design one registry with `python`, `shadow`, or `engine` per family,
the engine version, replaced Python guards/validator sections, and the
migration change (`plans/v2-firelight.md:178-183`). Character checks,
proficiency, and derived stats appear in the family list, but the phase table
does not assign them explicitly; the registry must settle that.

## 2. Character-sheet projection

- **Identity:** NQL uses typed, stable IDs; display names are not identities
  (`Firelight docs/GRAMMAR.md, "M1 grammar and semantics"`). The fork schema
  has an optional `character_id`, but it is not in the required field list;
  `party_tracker.json` refers to members by name. Define durable IDs and
  collision/rename handling before projecting a world
  (`schemas/char_schema.json:455,553-559`; `party_tracker.json:3-9`).
- **Stats:** Project source facts such as level, speed, ability scores, XP,
  proficiencies and features. Firelight derives proficiency, skills, saves,
  initiative, passive Perception and spell totals; do not project those same
  totals as independent bases. Fork sheets already carry derived values such
  as proficiency bonus and spell attack/save bonuses
  (`schemas/char_schema.json:24-125,336-342`;
  `characters/acheron.json:7-39,512-515`). Firelight leaves class entitlement,
  advancement choices and HP rolls to the host
  (Firelight docs/CHARACTER_STATS.md, "Updating a character" and "Limits").
- **Health:** Map `hitPoints` and `maxHitPoints` to bounded `hp` Resource
  current/maximum; retain the fork's death/resurrection policy at the host
  boundary. No explicit temporary-HP field is declared in the character
  schema, although the Firelight plan includes temporary HP
  (`schemas/char_schema.json:57-75,553-559`; `plans/v2-firelight.md:104-110`).
- **Slots and feature uses:** `spellSlots.levelN.current/max` and
  `classFeatures[].usage` are sheet state. The fork computes slot maxima by
  class/level; Firelight's generic Resources and Conditions need a projection
  that preserves those maxima and refresh rules, not a new progression table
  (`schemas/char_schema.json:162-181,336-438`;
  `utils/spell_slot_utils.py:181-265`).
- **XP:** Map `experience_points` to `xp`; Firelight can derive
  `xp:next`/`xp:pending`, but the host still awards/splits XP and applies the
  actual level. Reconcile those derived values with the fork's
  `exp_required_for_next_level` in G6 (`schemas/char_schema.json:449-454`;
  Firelight docs/CHARACTER_STATS.md, "Experience points" and
  "Hosts that keep character sheets").

## 3. Inventory, currency, and equipment

- **Item identity:** Fork equipment rows are named records with quantity and
  an `equipped` flag; ammo is a separate name/quantity list. The possession
  authority also searches by item name. Generate and persist stable IDs rather
  than deriving identity from names (`schemas/char_schema.json:260-318`;
  `utils/inventory_possession_authority.py:55-110,167-179`). Firelight
  requires unique item IDs and distinguishes owner, custody, and wearer;
  duplicate display names are allowed (Firelight docs/DESIGN.md, "Owner";
  docs/ITEM_CATALOG.md, "Data contract" and "Host write-back").
- **Possession and wear:** A character-sheet row can seed owner/custody as
  that character and map `equipped=true` to a wearer, but the fork has no
  separate custody/container field. Shared stashes, transfers, splits and
  item-at-place state need explicit ownership rules. Firelight's owner,
  custody, and wearer are distinct; one does not imply another
  (`characters/acheron.json:196-282`; Firelight docs/DESIGN.md, "Owner";
  docs/ITEM_CATALOG.md, "Host write-back").
- **Definitions and effects:** Fork items contain free-text descriptions and
  optional effect records. Firelight catalogue definitions do not infer
  mechanics from names/descriptions; custom items need reviewed definition
  and effect mappings. Acheron has effects both on item rows and in the
  top-level `equipment_effects` list, so projecting both blindly can double
  count one effect (`characters/acheron.json:145-194,258-272,294-309`;
  Firelight docs/ITEM_CATALOG.md, "Data contract").
- **Charges:** The fork schema has `charges.current/max` and a string
  `rechargeRate`; Firelight definitions require explicit charge/recharge
  policy, time anchor, and sometimes a random seed. Resolve legacy values and
  item IDs before G3 (`schemas/char_schema.json:274-282`;
  Firelight docs/ITEM_CHARGES.md, "Data contract" and
  "Where the state comes from").
- **Ammunition:** Map each fork ammunition row to a stock item. Firelight
  tracks `recoverable` shots and computes half recovery only when the host
  submits `recover`; the fork schema has no pending-per-fight recovery count.
  Keep attack resolution in combat and agree with SC on who records shots and
  recovery (`schemas/char_schema.json:308-318`;
  Firelight docs/AMMUNITION.md, "Hosts that keep an ammunition list";
  `plans/v2-firelight.md:42-45,206,213-215`).
- **Currency:** The fork has integer gold/silver/copper totals and a
  `currency_delta` operation for those denominations. Map them to distinct
  bounded Resources only after defining how loose coin items are reconciled;
  do not count the same coins as both resources and inventory. Firelight has
  no automatic currency conversion or purchase action. Its catalogue example
  leaves price/lot arithmetic and authorization to the host
  (`schemas/char_schema.json:440-447`;
  `updates/update_character_info.py:2015-2040`;
  `core/validation/character_validator.py:1811-1852,2217-2244`;
  `openspec/specs/tt-currency-correction-state-sync/spec.md:6-17`;
  `Firelight docs/ITEM_CATALOG.md, "Declare definitions, state intent"`).

The currency correction contract requires an executable character update when
a response claims bookkeeping has already changed; preserve that commit-vs-
clarification distinction until G4 replaces the relevant validator sections
(`openspec/specs/tt-currency-correction-state-sync/spec.md:6-33`;
`plans/v2-firelight.md:205`).

## 4. Effects, rests, time, maps, and quests

- **Effects:** The fork has descriptive `temporaryEffects`, item/top-level
  effects, and a separate `modules/effects_tracker.json` keyed by character
  name. The tracker stores stat/value/source and time/rest expiry; expiration
  later generates character-update prose. Firelight needs typed Conditions
  with stable instance IDs. Define one source of truth, identity scope,
  semantic mappings, and expiry conversion; arbitrary descriptions are not
  executable effect rules (`characters/acheron.json:136-194`;
  `updates/update_character_effects.py:36,78-115,255-301,303-361`;
  `updates/process_effect_expirations.py:20-49`). Firelight needs typed
  Conditions and stable instance IDs (Firelight docs/CHARACTER_STATS.md,
  "Effects" and "Conditions"; docs/TIMED_EFFECTS.md, "The pieces").
- **Clock mismatch:** `party_tracker.worldConditions` stores year/month/day,
  time, weather, season and other scene context. Its month is 28 days, and
  `update_world_time` advances that calendar. The effects helper instead
  counts 30-day months using process-local counters and does not use the
  stored month/year. Choose one campaign epoch and exact seconds conversion;
  test rollover and expiry before projecting timed effects
  (`schemas/party_schema.json:34-112`;
  `updates/update_world_time.py:17-71`;
    `updates/update_character_effects.py:38-75`). Firelight uses a monotonic
  clock tick; the host supplies its unit and keeps the calendar/context
  fields Firelight does not own (Firelight docs/TIMED_EFFECTS.md,
  "Host loop (stateless genesis)"; docs/LIVE_STATE.md, "The clock").
- **Rests:** Fork rest handling directly restores long-rest HP/slots, resets
  eligible features, and reduces exhaustion; short-rest behavior includes
  Warlock slot recovery and no automatic HP healing. Hit Dice are present in
  the sheet schema, while the character-update prompt says not to implement
  them. Firelight has resource restore and timed-effect operations, not a
  rest scheduler: the host must compose duration, eligibility, resource and
  condition changes atomically. Reconcile the Hit Dice contract and rest
  differences before G5 (`core/ai/action_handler.py:3782-3963`;
  `schemas/char_schema.json:71-74`;
  `updates/update_character_info.py:2523-2524`;
  `Firelight docs/GRAMMAR.md, "Native recovery"`).
- **Maps and occupants:** Fork maps carry room connections and spatial layout;
  Firelight routes require positive durations in clock ticks. Capture Arena
  connections have no travel durations. Add stable world-qualified place IDs
  and authored route times in a fixture; leave grid, zones and cover with
  Track F. Sheetless area NPCs/creatures can map to occupants, but a recruited
  character must become a Character, not a duplicate occupant
  (`schemas/map_schema.json:35-96`;
  `modules/Capture_Arena/map_CTR001.json:7-50`;
  `modules/Capture_Arena/areas/CTR001.json:54-60,97-109`;
  Firelight docs/WORLD_MAP.md, "Setting up a world" and "The travel rule";
  docs/LOCATIONS.md, "Why they left, and coming back").
- **Quests:** Fork plot points keep a current status and impact; Firelight
  quests keep an ordered status log and requirements. The party schema's
  `activeQuests` is explicitly deprecated. G6 needs stable quest IDs,
  prerequisite mapping, and an import rule for existing status/impact without
  inventing history (`modules/Capture_Arena/module_plot.json:4-13`;
  `schemas/party_schema.json:114-140`;
  `Firelight docs/QUESTS.md, "Hosts with their own plot files"`).

## 5. Protocol, receipts, and live-state recovery

An action request needs `actor` and an idempotency `request`; optionally fence
it with `expected_revision`. Exit 0 can be success or refusal, exit 2 is
unreadable/unknown input, and exit 3 is an engine panic with no checkpoint.
Refusals publish no events; the host must not commit or narrate them as facts
(Firelight docs/PROTOCOL.md, "Exit codes", "Request", "Response", and
"Versioning"). The `actor` is attribution, not authorization.

The receipt is `{revision, request, events}`. Each event has local event ID,
revision, event-level `request_id`, actor, operation index, kind, and typed
before/after body. Do not conflate receipt `request` with event `request_id`.
Firelight event IDs are local to one initial world, not global identities
(Firelight docs/PROTOCOL.md, "Response"; docs/GRAMMAR.md,
"M1 grammar and semantics").

The Narrator envelope additionally requires campaign/world references,
worldline/generation, turn/commit ID, schema version, in-game/recording time,
provenance, semantics, and perspective. The bridge must join those host-owned
fields to committed Firelight events; rejected proposals are not events.
Ratify exact ID and timestamp mapping with Narrator P0 before implementation
(`plans/v2-narrator.md:222-240`; `plans/v2-firelight.md:221-222`).

In `live_state`, the host still sends a fresh world from canonical records.
The document holds occupants, quest status/logs, journal, map position/state,
clock, and the last 64 state-changing request IDs; it does not replace
character sheets or item inventory. Persist each response in this order:
atomically write pending response/receipt/document; apply receipt after-values
to canonical host records and replace the document; delete pending. On restart,
reapply the pending receipt using absolute after-values
(Firelight docs/LIVE_STATE.md, "Facts and totals", "Retries", and
"The host's write order").

Important retry edge: an already-applied live-state retry has no receipt, and
item-only changes do not create a live-state retry record. The pending file
and canonical writeback are therefore part of correctness, not optional
logging (Firelight docs/LIVE_STATE.md, "Retries"; docs/ITEM_CATALOG.md,
"Execution, persistence and retries").

## 6. Pin, build facts, limits, and latency

- The plan pins tag `v0.1.0`, commit `e807382cac6d`; the module declares Go
  1.23, while the plan records the upstream release toolchain as Go 1.27.1
  (`plans/v2-firelight.md:80-85`; `tmp/ref/firelight/go.mod:1-3`).
- `scripts/release.sh` builds linux/amd64, windows/amd64 and darwin/arm64,
  with `CGO_ENABLED=0`, `-trimpath`, `-buildvcs=false`, and
  `-ldflags "-s -w -buildid="`; it emits four executable names, `GO_VERSION`
  and `SHA256SUMS` (`tmp/ref/firelight/scripts/release.sh:6-15`). G1 must
  verify the fork build against the pinned release checksums; no build or
  checksum comparison was performed for this audit.
- Firelight's Fair Source 1.0 license names Eternal Tavern and restricts
  competing services for five years from first publication; the plan records
  the owner decision and requires attribution in third-party notices
  (`tmp/ref/firelight/LICENSE:1-23`; `plans/v2-firelight.md:34-41`).
- Source limits include 16 MiB world source, 1 MiB action source, 256 MiB
  protocol input, 4,096 characters/locations/Condition definitions, 32,768
  items/Conditions, and 64 active timed Conditions (Firelight
  docs/WORLD_SIZE.md, "Limits").
- Upstream measurements: at 1,000 stored items, source is 200,285 bytes and
  the world-call median is 22 ms; at 10,000 items, 1,653,785 bytes and
  140 ms. The separate character test is 25 ms for four characters on its
  1,000-item world, rising to 76 ms for 68 characters. Map calls are about
  3 ms for 36 places/87 routes and 160 ms for 4,096 places/32,768 routes
  (Firelight docs/WORLD_SIZE.md, "Cost of a call" and "Characters and
  Conditions"; docs/WORLD_MAP.md, "Limits"). These are upstream medians,
  not fork projection or end-to-end turn timings.
- The world-size runs used Linux 6.6 under WSL2 on an Intel i9-13900H and
  median-of-three calls including encoding, process start and decode. Their
  host build flags differ slightly from `release.sh`
  (Firelight docs/WORLD_SIZE.md, "How the numbers were measured").
- The Firelight plan requires G1 p50/p95 call latency and world-source size,
  but sets no numeric p95 acceptance threshold. Narrator P0 requires numeric
  turn-latency/cost caps before dependent work; upstream medians cannot set
  the fork budget by themselves (`plans/v2-firelight.md:201-203,293-295`;
  `plans/v2-narrator.md:380-384,744-750`).

## 7. G1 offline-spike questions

1. Which stable, namespaced IDs map existing PCs, NPC sheets, items, places,
   quests and effect instances? How are duplicate names and renamed content
   handled without changing identity?
2. Which sheet fields are source facts and which are Firelight-derived
   totals? How are legacy/homebrew totals, temp HP, death state, slot maxima,
   and feature uses represented without double counting?
3. What is the canonical split between currency Resources and physical coin
   items? Which conversion and merchant authorization rules stay in Python?
4. Which free-text and tracked effects have reviewed typed mappings? How are
   the 28-day calendar, 30-day effect counter, timed expiries, concentration,
   rests, and Hit Dice reconciled?
5. Who records ammunition spends/recovery during combat, and what exact
   receipt after-values update the separate ammo list and equipment sheets?
6. What host commit ID forms the Firelight `request`, and how does each
   accepted event fill Narrator's commit envelope and survive a crash between
   the pending write, canonical writes, and live-state replacement?
7. What reproducible 1-PC and 4-PC Capture Arena copies, item/effect counts,
   route sizes and replayed changes define the G1 corpus? What numeric p50/p95
   budget applies to projection, process call, writeback, and total turn?

10-line summary of key gaps and surprises:

1. Character IDs are optional in the fork; party membership is name-based.
2. Item names, not stable item IDs, drive current possession checks.
3. Fork sheets store totals that Firelight expects to derive from facts.
4. Item effects can be duplicated across item and character-level fields.
5. Currency needs host conversion rules; Firelight does not convert coins.
6. Firelight live-state does not own the host's sheets or inventory.
7. Live-state retries may have no receipt; item-only changes are not retained.
8. The fork calendar has 28-day months; effect time counts 30-day months.
9. Firelight has no rest scheduler; route durations are also absent in maps.
10. Upstream latency is not the fork p95 budget or end-to-end measurement.
