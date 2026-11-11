# Proposal

## Why

The N1 player boundary and typed synchronization contracts exist, but there is no fork-owned browser client that lets invited players use them. Gate N2 needs one bounded React gameplay slice that shares canonical host state without exposing the facilitator surface or making local play depend on the client build.

## What Changes

- Add a small React/TypeScript player application for login, shared transcript, active-PC selection, read-only sheets, initiative/combat, gameplay input, busy state, and typed receipt feedback.
- Serve hashed, versioned client assets only through the existing player ASGI routes and enforce a client/protocol compatibility check. Keep the N1 route/event allowlist unchanged; register the remaining already-allowlisted player events.
- Publish host transcript, active-PC, and combat changes to players as safe, ordered `player.event` projections read from canonical state, using narrow `# TABLETOP MODE:` host integration hooks rather than host-global emissions.
- Keep the Node toolchain build-time only. The bundle is generated and gitignored in N2; normal host startup remains independent of Node and the bundle. Add an off-by-default, loopback-only development/test opt-in for starting the listener; N3 sharing UX replaces it.
- Extend provider-free tests and prepare the orchestrator-owned N2 multi-browser gate, including explicit missing/broken-build and host-only leakage checks.

Per the Overseer and the program ledger entry "N2 React vertical slice," this ONE change covers both `v2-react-player-foundation` and `v2-player-gameplay-resync` in plan section 10; it is not split into two change sets.

## Capabilities

### New Capabilities
- `react-player`: Fork-owned player UI, client asset build/serving, compatibility checks, and client-side presentation of the existing player protocol.

### Modified Capabilities
- `gameplay-sync`: Add the N2 contract for publishing host-originated changes as ordered, server-projected player events. Existing N1 envelope, cursor, receipt, retry, and active-PC requirements remain unchanged.

## Impact

Expected implementation surfaces are `web/frontend/`, `web/extensions/player/`, narrow host runtime integration points marked `# TABLETOP MODE:`, the listed player regression suites, `.gitignore`, and the existing security workflow for the frontend dependency audit. No tunnel, installer, facilitator UI rewrite, product code, or `plans/` change is part of this proposal. The primary-owned browser gate uses an isolated `Capture_Arena` copy with host port 8360 and player listener loopback port 8370; it never uses port 8357 or the installed campaign.
