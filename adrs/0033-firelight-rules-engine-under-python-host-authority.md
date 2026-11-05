# ADR-0033: Firelight Rules Engine Under Python Host Authority

- Date: 2026-11-05
- Status: Proposed (owner acceptance required before Narrator P0 ratifies the
  committed event envelope; `plans/v2-firelight.md` s7 G0)
- Supersedes: None
- Superseded by: None
- Amends: None. Relates to ADR-0027, ADR-0031 and ADR-0032.

## Context

Upstream moved its mechanics into a separate, public, versioned engine:
Firelight Engine v0.1.0, by Eternal Tavern (`github.com/MoonlightByte/firelight`,
tag `v0.1.0`, commit `e807382cac6d8686a664b5a53f4621ea4b9865ff`, 2026-10-24).
It is a stateless Go binary with a versioned JSON protocol: one request on
stdin, one response on stdout, atomic transactions with typed receipts, typed
refusals, and an optional `expected_revision` fence.

ADR-0031 made the fork independent; upstream code enters only through approved,
attributed ports. A binary with a stable protocol lets the fork share
upstream's rules work without re-merging upstream's Python host layer
(`core/nql/`). Players notice ledger drift - arrows that come back, wands that
never empty, coins that appear - and those contradictions damage the shared
picture (overview s2.1 item 1).

The owner decided on 2026-11-04 (`plans/v2-firelight.md` s2): Track G is its
own track; binaries are built from a pinned source commit with a pinned Go
toolchain, not vendored from upstream NEQ's `bin/`; the Fair Source 1.0 terms
fit this fork, including remote testers over OpenTunnel; in combat the engine
does bookkeeping only; prompt compression is phased into other tracks.

## Decision

### Authority

- Python is the host and the canonical store. Firelight is a deterministic
  rules function the host calls through a fork-native bridge (candidate
  `core/rules/firelight/`). The engine never opens files or the network.
- Canonical owners are unchanged: character JSON, `party_tracker.json`,
  encounter files and module areas. Committed receipts are applied through
  `update_character_info()` and `safe_write_json()`. The engine's live-state
  document is a new campaign-scoped record written atomically by the host
  following the engine's documented write order. No ad hoc JSON and no direct
  SQL.
- A pending-receipt record is written before canonical writeback and cleared
  after the document write. It is part of correctness: an already-applied
  live-state retry returns no receipt and item-only changes leave no retry
  record, so the host cannot recover them from the engine.
- The engine needs stable typed identities; the fork keys characters and
  items by name. No family enters `shadow` before characters, items, places,
  quests and condition instances have stable host IDs, assigned through
  canonical APIs.
- Flow, consistent with ADR-0027 and overview s2: proposal -> engine
  validation -> host commit -> disclosure. Narration happens after commit.
- For each migrated family, the engine verdict replaces the Python guard and
  the LLM validator section in the same change. The LLM never overrides a
  refusal by assertion. A refusal is returned once to the proposer for a
  corrected proposal; a second refusal is narrated as the world refusing.
- In combat the engine does bookkeeping only (damage, healing, hit points,
  conditions, concentration, saves, resource spend as committed receipts).
  Attack resolution, the tactical brain, enemy resolution and the ally
  controller stay in `core/combat/`, which keeps one owner (SC).
- Not adopted in v0.1.0: the engine's journal and relationship families. Each
  is evaluated at an upgrade review against the Narrator, Pilot and TITAN
  owners' contracts. Scene layout, zones, cover and sightlines stay with Track
  F; module validation, publication gates and narrative checks stay in Python.

### Family registry

One registry records, per rule family: mode (`python`, `shadow`, `engine`),
engine version, the Python guards and validator sections it replaces, and the
migrating change. Prompts and validators read the registry, so a section is
removed exactly when its family reaches `engine`. A family moves to `engine`
only through a reviewed OpenSpec change with 1-PC and 4-PC focused tests and
the live gate its plan requires. No party-size gates; `MULTIPLAYER_MODE` is
untouched.

### Failure behavior

- Exit 2 or 3, timeout, oversize output or checksum mismatch on a migrated
  family: fail closed, commit nothing, log under a dedicated category, surface
  a host-only status. The turn continues without the mechanical change and the
  Narrator describes less rather than inventing an outcome.
- Unmigrated families keep the existing Python path. The bridge never falls
  back to Python for a family in `engine` mode.

### Pin, build and upgrade policy

- Pin record: `third_party/firelight/PIN.json`, holding tag, full commit SHA,
  Go toolchain (`go1.27.1` for v0.1.0), build flags, binary name
  (`firelight-apply`) and expected SHA-256 per platform from the upstream
  `SHA256SUMS`. `GO_VERSION` is not checksum-pinned because it names the
  build host.
- Build: a fork script builds from the pinned commit with the engine's own
  reproducible flags (`CGO_ENABLED=0`, `-trimpath -buildvcs=false -ldflags
  "-s -w -buildid="`) and the pinned toolchain. The output must reproduce the
  upstream checksum for each published platform; a mismatch blocks adoption.
- Supported host platforms are those upstream publishes and the fork has
  reproduced: darwin-arm64 and linux-amd64 for v0.1.0 (windows-amd64 is
  published but hosting on Windows is out of scope; Network plan s10).
  Hosts on unpublished platforms keep every family in `python` mode until a
  later decision.
- Binaries are never committed to git. They are built from the pin locally or
  in fork CI; Network N3 installers bundle a CI-built binary verified against
  the pin. Testers on thin clients need no binary.
- The bridge refuses to start the engine when the binary checksum differs from
  the pin.
- Upgrades (GU) are small reviewed OpenSpec changes: read the changelog and
  protocol diff, rebuild and verify checksums, rerun bridge fixtures and the
  shadow corpus, then enable new families through the registry. A breaking
  protocol change is a blocked upgrade until reviewed.

### Latency

The engine call is on the turn's critical path. Proposed budget, confirmed or
revised by the G1 offline spike on 1-PC and 4-PC Capture Arena worlds: p95
engine call at most 250 ms and p50 at most 100 ms, measured end to end
(projection, process call, canonical writeback); per-stage budgets are in
`plans/v2-firelight-g0/design.md` s7. At most two calls per player turn
outside combat. If `live_state` mode misses
the budget, the plan's checkpoint-mode fallback is evaluated before any
cutover.

### Licensing and attribution

Firelight is Fair Source 1.0, Copyright (c) 2026 Eternal Tavern. Third-party
notices carry "Firelight Engine, by Eternal Tavern" and the license text with
the pinned version. Any ported fork code (for example the subprocess bridge
pattern from `examples/python/firelight_host.py`) keeps upstream attribution.

## Consequences

- On acceptance, `AGENTS.md` gains one durable rule: mechanical legality for
  migrated rule families is decided by the pinned Firelight engine through the
  Python bridge. No `AGENTS.md` edit before acceptance.
- Narrator P0 adopts the receipt-to-envelope seam (revision, request id, typed
  events with before/after values) when it ratifies the event envelope; the
  live-state document joins the Narrator P2 save manifest.
- New state (storage, trade stock, charges) is engine-owned from G3; existing
  state migrates family by family through shadow, never wholesale.
- A host without Go or a supported platform still runs the game; it just keeps
  unmigrated behavior.
- The fork carries a dependency on an external release cadence. Pinned source
  builds keep working if upstream stops; the license permits a fork patch
  branch.

## Alternatives considered

- Port upstream `core/nql/` (about 700 KB of Python host code): rejected; it is
  tied to upstream's redesign and is a re-merge (ADR-0031).
- Keep extending Python guards and validator prompts: rejected as the default;
  it is the source of today's ledger drift and validator token cost.
- Vendor upstream binaries without rebuilding: rejected by the owner decision
  of 2026-11-04.
- Checkpoint mode as the default: kept as a fallback; `live_state` keeps
  canonical owners primary and avoids a second history.

## Sources

- `plans/v2-firelight.md` (s2-s7, s11, s15).
- `plans/v2-firelight-g0/gap-inventory.md` and `design.md` (pin record,
  build script, family registry, receipt-to-envelope seam, write order,
  latency budget, G1 corpus).
- `plans/v2-narrative-overview.md` s2, s8.3.
- Firelight `docs/PROTOCOL.md`, `docs/LIVE_STATE.md`, `scripts/release.sh`,
  `LICENSE`, release `v0.1.0` `SHA256SUMS` and `GO_VERSION`.
- ADR-0027, ADR-0031, ADR-0032.
