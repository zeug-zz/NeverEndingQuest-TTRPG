## Why

The V2 network plan (`plans/v2-server-client-network.md`, Phase 0) must prove,
before any player boundary, React client, or sharing UX is built, that a
macOS/Linux host can serve an authenticated Socket.IO application over the
upstream OpenTunnel relay and that a player listener can coexist with the one
authoritative Python runtime. Gate N0 evidences this with an inert fixture and
records the architectural decisions later changes depend on.

## What Changes

- Add a host surface inventory (`inventory.md`) of every HTTP route, Socket.IO
  handler and emission, state owners, GUI extraction seams, and installer paths,
  with initial capability classes.
- Record decisions in `design.md`: pinned OpenTunnel v0.6.2 usage and isolation,
  player-listener/runtime integration, serving stack, spike dependency policy.
- Add an inert, standalone authenticated fixture under `scripts/network_spike/`
  (no game data, no campaign files, loopback `127.0.0.1:8370` only) with
  provider-free unit tests for its auth and origin checks.
- Add a feasibility driver that records JSON evidence for macOS and Linux
  under `tmp/router-rollout/v2-network/n0-<platform>-<run-id>/`.
- Define the orchestrator-owned N0 gate verdict per platform.

## Capabilities

### New Capabilities

- `network-deployment`: requirements for how the player network surface is
  reached and isolated (tunnel pinning/isolation, loopback-only listeners,
  authenticated transport behaviour, feasibility evidence). Later changes
  (`v2-opentunnel-sharing-lifecycle`) extend this same capability.

### Modified Capabilities

None.

## Non-Goals (binding)

- No product runtime changes: no edits to `web/`, `main.py`, `run_web.py`,
  installers, `requirements*.txt`, or `requirements-lock.txt`.
- No real campaign, character, or game data; no unfiltered host surface exposed.
- No player allowlist, session policy, React client, sharing UX, packaging, or
  tunnel lifecycle management (Phases 1-4).
- No upstream React `/play` review (N2 task).
- No Windows server, offline LAN transport, relay self-hosting, or tunnel fork.

## Impact

- New files only: `openspec/changes/v2-network-transport-feasibility/**`,
  `scripts/network_spike/**`, `scripts/test_network_spike_fixture.py`.
- Spike-only third-party dependencies (ASGI server, Socket.IO client transport)
  are installed into a scratch venv under `tmp/n0/`, never the repo `.venv` or
  lock files; adding runtime dependencies is a later, separately reviewed step
  that requires lock updates and `pip-audit` (design D3).
- External dependency: the public OpenTunnel relay (rate limits and certificate
  issuance). Relay unavailability, an unavailable Linux leg, or an unsolved
  runtime ownership design leaves N0 BLOCKED for owner plan review; it is never
  waived.
- 1-PC and multi-PC compatibility: no shared runtime path is touched, so no
  party-size regression is introduced; design D2 constrains Phase 1 to keep the
  shared runtime single and party-size neutral.
- No LLM plumbing is touched (provider-free); no provider outage behaviour applies.
