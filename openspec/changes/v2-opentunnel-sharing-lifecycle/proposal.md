# Proposal

## Why

N0 established a guarded, isolated OpenTunnel v0.6.2 foreground transport, and N1/N2 provide the loopback-only player application, authentication, and client contracts. Production sharing still lacks an explicit facilitator-owned lifecycle, supervised recovery, and revocation path; the current N2 environment opt-in is development-only and must not become an unattended or implicitly public service.

## What Changes

- Add the production path/profile contract for an NEQ-managed, pinned OpenTunnel companion without downloading it or adding installers; keep the binary install-relative and separate from `.venv`/`venv`, with dedicated private per-profile XDG state and OS-appropriate private credential storage.
- Replace development-only listener activation for production sharing with facilitator-local Start sharing, Copy invitation, status/diagnostics, Rotate/revoke access, and Stop sharing controls. Sharing remains explicit consent; the invitation contains no password or credential.
- Specify a fail-closed readiness state machine and foreground process supervision. A ready invitation requires verified player assets, a live loopback player listener, configured authentication, and healthy tunnel reachability; sharing off, a down game, or partial startup exposes no player service.
- Define bounded relay reconnect, cleanup and owned-orphan reconciliation across stop, exit, launcher restart, startup failure, and crash recovery. Retain local gameplay and never replay gameplay input after recovery.
- Reuse N1 sessions, authentication, cookie, Host/Origin, and CSRF rules; define rotation/revocation against active sessions and add provider-free fake-companion/fake-supervisor failure-injection coverage.
- Define, but do not run here, one primary-orchestrator-owned N3 lifecycle gate with a provider-free OD-6 preflight, exact-SHA booking, port/evidence discipline, frozen run caps, and evidence under `tmp/router-rollout/v2-network/n3/`.

### Binding Non-Goals

- Installers, downloads, prebuilt asset distribution, update/rollback tooling, or packaged clean-install claims (later `v2-network-packaging-release`).
- N4 external-network gameplay/browser scenarios, relay self-hosting, custom domains, or an OpenTunnel fork.
- Windows server support, Node runtime requirements, LAN fallback, or changes to `MULTIPLAYER_MODE` or party-size gates.
- Host controls on the player listener/tunnel, authentication weakening, a second runtime, or automatic sharing at install/login/startup.

## Capabilities

### New Capabilities

None. This change extends existing network and player-boundary contracts.

### Modified Capabilities

- `network-deployment`: specify the production companion path/profile, explicit sharing lifecycle, readiness, supervision, and recovery contract.
- `player-capabilities`: require facilitator lifecycle controls to remain host-only and extend the existing route/event inventory test to prove they are absent from the player application and tunnel target.
- `player-access`: specify that access rotation/revocation invalidates existing sessions and sockets without changing N1 authentication or request-validation rules.

## Impact

Expected implementation surfaces are new or extended modules under `web/extensions/` and `web/extensions/player/`, narrowly marked `# TABLETOP MODE:` host integration/UI changes, and provider-free tests under `scripts/`. Python remains authoritative; React remains presentation-only. Host and player listeners remain separate and loopback-bound (`127.0.0.1`, with the player listener on port 8370); only the player listener may be the OpenTunnel target. Shared runtime behavior remains compatible with 1-PC and 4-PC parties. No dependency, installer, or product binary is added by this change. Gitleaks, Bandit, and strict pip-audit checks apply to implementation.
