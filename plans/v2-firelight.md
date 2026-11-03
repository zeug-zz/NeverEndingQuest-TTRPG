# V2 Firelight: A Rules Engine Under Python Host Authority

Status: Master plan for owner review; not implementation authorization.
Date: 2026-11-04.
Track: G (Firelight rules engine). Program index: [V2 narrative overview](v2-narrative-overview.md).
Owner decisions recorded 2026-11-04 (s2). ADR required before G2 (s3).

## 1. Purpose: piggyback on upstream's rules engine

Tabletop mode was built as a plugin so the fork could keep taking upstream
updates. That worked for a few merges and stopped as the codebases diverged
(ADR-0030, ADR-0031). Upstream has now moved its mechanics into a separate,
public, versioned engine: **Firelight Engine v0.1.0, by Eternal Tavern**
(github.com/MoonlightByte/firelight). This gives the fork a clean way to share
upstream's rules work again without re-merging any upstream code.

What is shared is a **binary with a versioned JSON protocol**, not Python files:

- Upstream develops and tests the rules: inventory, storage, trade, charged
  items, conditions, rests, ammunition, quests, a travel map and, in future
  releases, travel and encumbrance.
- The fork owns a thin bridge, picks an engine version, rebuilds it from pinned
  source, reruns its own fixtures and enables rule families when it chooses.
- Upstream's Python host layer (`core/nql/`, about 700 KB) stays out of the fork.
  It is tied to upstream's redesign and porting it would be a re-merge.

Players notice ledger drift: an arrow count that goes up, a wand that never runs
out, coins that appear, a rest that restores nothing. These are contradictions
in the shared picture (overview s2.1 item 1). Firelight makes "Python decides,
the LLM shows" structural for bookkeeping, and frees the Narrator to narrate.
It also brings capabilities the fork lacks (storage, trade, charged items)
without waiting for the rest of v2.

## 2. Owner decisions (2026-11-04)

1. Track G is its own track and worktree, not folded into the Narrator build.
2. Binaries are built from a pinned source commit with a pinned Go toolchain,
   not vendored from upstream NEQ's `bin/`.
3. The Fair Source 1.0 terms of Firelight are confirmed as fit for this fork,
   including remote testers over OpenTunnel. Attribution "Firelight Engine, by
   Eternal Tavern" is kept in third-party notices.
4. In combat the engine does **bookkeeping only**: damage, healing, hit points,
   conditions, concentration, saves and resource spend as committed receipts.
   Attack resolution, the tactical brain, enemy resolution and the ally
   controller stay in `core/combat/`.
5. Prompt compression gets no separate build. It is phased into Narrator,
   Spatial and Track G phases (s9).

## 3. Authority and scope

- Precedence: `AGENTS.md` > accepted ADRs > active OpenSpec changes > master
  plans > the index. This plan proposes changes and goals; it authorizes none.
- **ADR needed (G0):** "Firelight rules engine under Python host authority". It
  records:
  - Python is the host and the canonical store. Firelight is a deterministic,
    stateless rules function that the host calls. It never opens files.
  - Canonical owners are unchanged: character JSON, `party_tracker.json`,
    encounter files and module areas. Writes go through `update_character_info()`
    and `safe_write_json()`; the engine document is a new campaign-scoped record
    written atomically, never ad hoc JSON or direct SQL.
  - For each migrated rule family, the engine's verdict replaces the Python
    guard and the LLM validator section. The LLM never overrides a refusal by
    assertion.
  - Which families have migrated (a registry per family; s6.4).
  - The binary, pin and upgrade policy (s5).
  - How it fits the prime directive (overview s2): proposal -> engine
    validation -> commit -> disclosure.
- On acceptance, `AGENTS.md` gets a durable one-line rule that mechanical
  legality for migrated families is decided by the pinned engine through the
  Python bridge. No `AGENTS.md` edit happens before the ADR is accepted.
- Shared paths keep 1-PC and 4-PC regression checks. No party-size gates; do not
  touch `MULTIPLAYER_MODE`.
- Upstream code enters only through approved OpenSpec changes with attribution
  (ADR-0031). Candidate selective ports: the subprocess bridge pattern
  (`examples/python/firelight_host.py` in the engine repo is a small reference)
  and SRD item/attack data written as NQL source. Never `core/nql/` wholesale.

## 4. Firelight v0.1.0 at a glance

Pinned reference: tag `v0.1.0`, commit `e807382cac6d` (2026-10-24), module
`github.com/MoonlightByte/firelight`, `go 1.23`, standard library only. The
release was built with `go1.27.1` and publishes darwin-arm64, linux-amd64 and
windows-amd64 binaries with `SHA256SUMS`. Upstream NEQ ships the same public
v0.1.0 (`bin/FIRELIGHT_ENGINE_VERSION.txt`). `nql-apply` is the same build
under its old name.

- **Protocol (`docs/PROTOCOL.md`):** one JSON document on stdin, one on stdout.
  One call builds a world, runs at most one transaction and answers read-only
  views. Exit 0 is a complete response with `ok` true or a refusal; exit 2 is
  unreadable input (no world touched); exit 3 is an engine panic (store
  nothing). Unknown fields are refused. `actor` and `request` (idempotency key)
  are required with actions; `expected_revision` is optional optimistic
  concurrency.
- **Atomic transactions with receipts:** each committed transaction returns a
  revision, the request id and typed events with before/after values. Retries
  with the same request id are safe. Refusals are typed diagnostics the model
  can act on.
- **Two state modes:** keep the returned checkpoint (history replay each call),
  or `live_state` (`docs/LIVE_STATE.md`): the host sends a fresh world source
  built from its own records each call, plus a document holding only what the
  engine alone writes (occupants, quest status and logs, journal, map position
  and map state, clock). The engine test suite checks both modes give identical
  answers.
- **Families in v0.1.0:** coins, trade, item catalogue and stock; storage and
  custody; equipment, worn effects and AC; character stats, checks and
  proficiency; hit points, temporary hit points, resources, spell slots and
  feature uses; rests; ammunition and recovery; timed conditions and
  concentration; damage, healing and saves; charged items and recharge; XP and
  level-up tables; quests; occupants; journal; relationships with decay;
  world map and party travel with a clock.
- **Map (`docs/WORLD_MAP.md`):** a route graph with travel times, visited
  places, hazards and closed routes. `travel party to` finds the path, moves the
  party and advances the clock. It has no scene layout, zones or cover.

## 5. Binary, pin and upgrade policy

- A pin record (path decided in G0, for example `third_party/firelight/PIN`)
  holds: tag, full commit SHA, Go toolchain version, build flags and expected
  SHA256 per platform.
- A fork script builds from the pinned commit with the engine's own reproducible
  flags (`CGO_ENABLED=0`, `-trimpath -buildvcs=false -ldflags "-s -w -buildid="`,
  as in its `scripts/release.sh`). The build must reproduce the upstream
  `SHA256SUMS` entry for each platform; a mismatch blocks adoption.
- Where binaries live, and whether they are committed or built at install, is
  decided in G0 together with Network N3 packaging. Testers on thin clients need
  no binary; only the host does.
- The bridge refuses to start the engine if the binary's checksum differs from
  the pin, and falls back to the existing Python path for unmigrated families
  only. A migrated family fails closed (s6.3).
- **Upgrade procedure (GU):** each new Firelight release is a small reviewed
  OpenSpec change. Read the engine changelog and protocol diff, rebuild and
  verify checksums, rerun bridge fixtures and the shadow corpus, then enable any
  new family through the family registry with its own focused tests. Protocol
  changes upstream are additive by policy; treat any breaking change as a
  blocked upgrade until reviewed.

## 6. Integration architecture

### 6.1 Bridge

A fork-native package (candidate `core/rules/firelight/`) owns:

- process invocation with timeout, size limits and exit-code handling;
- request ids derived from the committed turn identity, so retries are safe;
- `expected_revision` fencing against the stored document;
- typed results: receipt (revision, events), refusal (diagnostics) or failure.

It follows repository conventions: SPDX header, ASCII source, type hints,
`utils.enhanced_logger`, no shell execution of user input.

### 6.2 World projection and the live-state document

`live_state` mode is the default (G1 confirms it). Each call:

1. Python builds the NQL world source from canonical records (character sheets,
   party, module areas and routes, item catalogue). This projection is pure and
   deterministic, and is cached per campaign revision.
2. Python passes the stored live-state document, the actions and the actor.
3. On commit, Python applies the receipt's events to canonical records through
   canonical APIs, then writes the new document atomically, following the
   engine's documented host write order (`docs/LIVE_STATE.md`, "The host's
   write order").

Ordering and recovery rules (crash between steps, retry after a partial host
write) are specified in G2 and tested with fault injection.

### 6.3 Failure behavior

- Refusal: the action does not happen. The diagnostics go back to the proposing
  model once, for a corrected proposal; a second refusal is narrated as the
  world refusing (for example "you have no arrows left"), never silently
  ignored.
- Exit 2 or 3, timeout or checksum failure on a migrated family: fail closed,
  commit nothing, log with a dedicated category, and surface a host-only
  status. The turn continues without the mechanical change; the Narrator
  describes less rather than inventing an outcome (overview s2.1 item 3).

### 6.4 Family registry

One registry records, per rule family: mode (`python`, `shadow`, `engine`),
engine version, the Python guards and validator sections it replaces, and the
change that migrated it. Prompts and validators read this registry so a section
is removed exactly when its family moves to `engine`.

### 6.5 What stays in Python

- Module and schema validation (`core/validation/validate_module_files.py`),
  publication gates and the continuity contract.
- Scene and narrative checks: location exclusivity, NPC presence, combat
  narration consistency, phase integrity.
- Spatial authority (Track F): scene layout, zone ledger, cover, sightlines.
- Combat attack resolution, tactical brain, enemy and ally resolution (s2 item 4).
- Memory, relationships and agendas owned by Narrator, Pilot and TITAN. The
  engine's journal and relationship families are **not adopted** in v0.1.0; each
  is evaluated at an upgrade review against those owners' contracts.

## 7. Phases and gates

| Phase | Where | Content | Gate |
| --- | --- | --- | --- |
| **G0 ADR, audit and pin** | Docs in main | ADR (s3); pin record and build script design (s5); gap inventory mapping the fork's sheets, inventory, currency, effects and time to NQL; the receipt-to-envelope seam handed to Narrator P0; family registry design; latency budget proposal | Owner accepts the ADR **before Narrator P0 ratifies the event envelope** |
| **G1 offline spike** | `scripts/` and `tmp/` only; no runtime hook | Build from pin and verify checksums; project worlds from seeded Capture Arena copies (1-PC and 4-PC); measure p50/p95 call latency and world-source size; replay a recorded session's inventory and resource changes; report gaps | Latency fits the turn budget; gap list reviewed by the owner |
| **G2 bridge and shadow** | Worktree G | Bridge, world projection, live-state document in campaign storage, family registry; every committed Python change in candidate families is replayed through the engine and disagreements are logged; no authority change | Disagreement report per family from live captures; fault-injection tests pass |
| **G3 new capabilities** | Worktree G | Engine-authoritative from the start, since Python has no equivalent: storage and custody, trade with item catalogue and stock, charged items and recharge. LLM proposals map to NQL actions; refusals surface in narration; host and player views show the results | 1-PC and 4-PC focused tests; live capture covering a shop visit, a stash and a charged item; owner rating on the experience rubric |
| **G4 first cutover** | Worktree G | Coins, inventory possession, equipment, worn effects and AC move to `engine`; retire the matching parts of `inventory_possession_authority.py`, `tt-currency-correction-state-sync` and the validator sections; measure validator token use before and after | Shadow disagreement resolved or explained; focused tests; live capture |
| **G5 second cutover** | Worktree G, coordinated with SC0 | Hit points outside combat, resources, spell slots, rests, timed conditions and concentration, ammunition, saves outside combat, the clock; retire the matching parts of `updates/process_effect_expirations.py`, `updates/update_world_time.py`, `spell_slot_utils.py`, the ammo, slot and rest guards and prechecks; combat bookkeeping routes through the engine as SC0 decides | Same as G4, plus affected archived combat gates rerun by SC |
| **G6 third cutover** | Worktree G | XP and level-up tables, quest status and logs, location occupants; coordinate with plot, scene presence and Spatial S1 owners | Same as G4 |
| **GU upgrades** | Small changes in main | Per s5 | Per upgrade change |

G3 may precede G4 because nothing needs shadowing, but it needs the G2 bridge
and the G0 ADR, since the engine then owns that state.

Combat bookkeeping (G5) is the only Firelight work that touches
`core/combat/`. It is implemented in the SC worktree or as an SC-owned change,
using the G2 bridge, so `core/combat/` keeps one owner.

## 8. Cross-track seams

| Track | Seam | When |
| --- | --- | --- |
| Narrator (B) | Engine receipts carry commit identity for the P1 event envelope; the live-state document joins the P2 save manifest; `expected_revision` supports generation fencing; committed engine events are clean retention inputs for Hindsight | G0 hands the seam to P0; P1/P2 consume it |
| Spatial (F) | The SP4 spatial ADR evaluates the engine map as the backend for S1 routes and visited places and S5 travel time; layout, zones and cover stay in Python | SP4 and S1 |
| Combat baseline / SC | SC0 records bookkeeping-only routing; SC4 reruns affected archived gates | SC0 |
| Network (A) | Player views of inventory, storage and resources come through the Network P1 projection; binary placement coordinated with N3 packaging | N1 reserves views; N3 |
| Builder (E) | MB1/MB2 emit route times, item catalogue and stock references the engine can load | MB0 adopts the projection draft |
| TITAN (D) | Intervention operations with mechanical effects compile to engine actions and accept engine refusals | TITAN P0 records the seam |

## 9. Context and prompt compression (phased, no separate build)

The upstream README "Performance Metrics Summary" (92% system prompt, 87%
validation, 90%+ conversation) dates from 2025-08-30, before the fork. The fork
already runs those techniques: tagged notation, `system_prompt_compressed.txt`,
`validation_prompt_compressed.txt` and the conversation compressors. Upstream's
compressed prompts have since grown (system 66.3 KB, validation 50.6 KB on
upstream main, 2026-11-03) and are larger than the fork's (36.9 KB, 26.6 KB).
There is no new compression technique to port under that name.

The useful upstream work is its "context views" programme (upstream PRs #554,
#556, #559) and handing mechanics to the engine:

| Step | Owner | When |
| --- | --- | --- |
| Per-block byte counts and cached-token logging (C7) | Narrator P0 baseline tooling | Before the P0 reference captures |
| Compact `KEY=value` validator evidence (C1); one mention per fact in the DM call and validation (C2/C3, excluding exits and atlas); fixed per-turn instructions moved into the system prompt (D4); typed history markers | A small `v2-context-views` change in main, or the first task in worktree R | After pilot SP3 and after the P0 baseline is recorded, so neither is confounded |
| Atlas built once per revision; one mention for adjacency and exits (C4) | Spatial S2 | S2 |
| Stable prompt prefix and prompt-cache key (C5) | Narrator P4 layered assembler | P4 |
| Rules removed from prompts and validator | Each Track G cutover (G4-G6), via the family registry | After each cutover |
| Location-summary and history-compression summarisers replaced by the Archivist; upstream #400 failure modes become fixtures; no silent truncation ("No-Limits") | Narrator P4 | P4 |

Story context is not squeezed for its own sake. Dense notation suits rules;
over-compressed story context makes the shared picture less vivid (overview
s2). Budgets come from the fork's own Narrator P0 baseline.

## 10. Timeline and worktree

Week 0 is 2026-10-28, as in the overview. Gates, not dates, decide completion.

| Weeks | Track G work |
| --- | --- |
| 0-3 | G0 docs in main alongside Narrator P0 contracts; ADR accepted before P0 ratifies the envelope |
| 2-5 | G1 offline spike in `scripts/` and `tmp/` (no port 8360 needed) |
| 5-8 | Worktree G `feature/v2-firelight` opens after pilot SP3 finishes; G2 bridge and shadow |
| 8-10 | G3 new capabilities; may join the tester build only if merged to `main` before the tagged tester SHA; never a gate for Network N4 |
| 10-13 | G4 first cutover |
| 13-16 | G5 second cutover, with SC0/SC1 |
| 16-19 | G6 third cutover |
| ongoing | GU upgrades as upstream releases |

File ownership while G is open:

- G owns `core/rules/firelight/`, `updates/` mechanics paths, the mechanics
  guards and prechecks, and validator rules sections.
- R owns Narrator prompt regions; S2 owns the DM-note exits block and atlas
  injection; SC owns `core/combat/`.
- `main.py` and the prompt files are hotspots: small PRs, rebase after each
  merge. Live captures stay serialized on port 8360.

## 11. Verification

- Bridge fixtures without a provider: protocol exit codes, refusal mapping,
  idempotent retry, `expected_revision` conflicts, checksum refusal, timeout.
- World-projection determinism: the same canonical records give byte-identical
  world source.
- Fault injection across the host write order.
- Shadow disagreement rate per family on live captures, with each disagreement
  classified (engine right, Python right, projection gap).
- 1-PC and 4-PC focused tests for every family moved to `engine`.
- Orchestrator-owned live captures (Capture Arena, port 8360, isolated copy)
  at G3-G6, evidence under `tmp/router-rollout/firelight/<gate>/<run-id>/`.
- Experience measure: ledger contradictions per session (counts, charges, coins,
  slots, conditions) before and after each cutover, plus the owner rating on the
  overview s2 rubric. Validator token use is a secondary measure.
- Latency: engine call p95 within the budget set in G0; a long pause breaks the
  scene (overview s2.1 item 5).
- Module validator and ASCII compliance on every change.

## 12. OpenSpec outline (candidate names)

| Phase | Candidate change |
| --- | --- |
| G0 | ADR only (no OpenSpec runtime change) |
| G1 | `firelight-offline-spike` (scripts and tmp only) |
| G2 | `firelight-bridge-and-shadow` |
| G3 | `firelight-storage-trade-charges` |
| G4 | `firelight-cutover-inventory-equipment` |
| G5 | `firelight-cutover-resources-conditions-clock` (combat bookkeeping as an SC-owned companion) |
| G6 | `firelight-cutover-progression-quests-occupants` |
| GU | `firelight-upgrade-<version>` |
| s9 | `v2-context-views` |

Each change states scope, non-goals, budgets, failure and rollback behavior,
1-PC and 4-PC verification and live-gate requirements.

## 13. Candidate goal

| Worktree | Objective basis | When |
| --- | --- | --- |
| G `feature/v2-firelight` | Deliver G2-G6 so that bookkeeping the players rely on (coins, items, storage, charges, slots, rests, conditions, ammunition, progression) never contradicts itself across turns and sessions, decided by the pinned Firelight engine under Python host authority, with live 1-PC and 4-PC gates at G3-G6 | After the G0 ADR, the G1 gate and pilot SP3 |

## 14. Risks

| Risk | Mitigation |
| --- | --- |
| Projection gaps between fork sheets and NQL | G0 gap inventory; G1 replay; shadow before cutover |
| Per-call latency from rebuilding the world in `live_state` mode | G1 measurement; cache world source per revision; checkpoint mode as fallback if G1 fails |
| Protocol churn upstream | Pinned versions; additive-only policy upstream; GU is a reviewed change |
| Upstream stops maintaining the engine | Pinned source builds keep working; the fork may maintain its own patch branch under the license |
| Narration drifting from engine verdicts | Commit before narrate; refusals fed back; contradiction measure |
| Two owners for combat state | SC owns combat changes; G supplies only the bridge |

## 15. Non-goals

- Re-merging upstream or porting `core/nql/`.
- Engine-owned attack resolution or tactical decisions.
- Engine-owned scene layout, zones, cover or sightlines.
- Adopting the engine's journal or relationship families without a reviewed
  owner decision.
- A separate prompt-compression build.
- Changing `MULTIPLAYER_MODE` or party-size checks.

## 16. References

- Firelight repository and docs: `README.md`, `docs/PROTOCOL.md`,
  `docs/LIVE_STATE.md`, `docs/WORLD_MAP.md`, `docs/SAVES.md`, `docs/DESIGN.md`,
  `CONTRIBUTING.md`, `LICENSE` at commit `e807382cac6d`.
- Upstream NEQ: README "Rules first: the Firelight Engine"; CHANGELOG entry
  #1409; context-views PRs #554, #556, #559; history-compression follow-up #400;
  "No-Limits" rule #262.
- Fork: ADR-0030, ADR-0031, ADR-0032; `plans/v2-narrator.md` s7 and s14;
  `plans/v2-spatial.md` s7-s8; `plans/v2-mapping-pilot.md`.
