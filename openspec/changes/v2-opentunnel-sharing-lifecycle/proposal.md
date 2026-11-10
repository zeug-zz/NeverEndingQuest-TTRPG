# Proposal

## Why

N0 established a guarded, isolated OpenTunnel v0.6.2 foreground transport, and N1/N2 provide the loopback-only player application, authentication, and client contracts. Production sharing still lacks an explicit facilitator-owned lifecycle, supervised recovery, and revocation path; the current N2 environment opt-in is development-only and must not become an unattended or implicitly public service.

## What Changes

- Add the production path/profile contract for an NEQ-managed OpenTunnel v0.6.2 companion without downloading it or adding installers; keep the binary install-relative and separate from `.venv`/`venv`. The only approved platform pairs are macOS arm64 and Linux arm64; a later packaging change supplies the pinned asset-stem/SHA-256 manifest. Use dedicated per-profile XDG state outside the repository and campaign data.
- Replace development-only listener activation for production sharing with facilitator-local Initialize sharing identity, Start sharing, Copy invitation, status/diagnostics, Rotate/revoke access, and Stop sharing controls. Identity initialization is an explicit once-per-profile facilitator action. Sharing remains explicit consent; the invitation contains no password or credential.
- Specify a fail-closed readiness state machine and foreground process supervision. A ready invitation requires verified player assets, a live loopback player listener, configured authentication, healthy tunnel reachability, and an exact generation-bound HTTPS origin accepted by N1 validation; sharing off, a down game, or partial startup exposes no player service.
- Define bounded relay reconnect, cleanup and owned-orphan reconciliation across stop, exit, launcher restart, startup failure, and crash recovery. Retain local gameplay and never replay gameplay input after recovery.
- Reuse N1 sessions, authentication, cookie, and CSRF rules. Store only the existing N1 verifier in private 0600 storage; generate and show the plaintext credential once per issuance, never persist or disclose it elsewhere, and use rotation as recovery. Bind only the exact HTTPS origin reported by companion status to N1 Host/Origin validation for the active generation.
- Use fake-companion and provider-free tests only in this change. Do not connect to a real tunnel or relay or create public exposure; any live tunnel run requires a separate booking.
- Define, but do not run here, one primary-orchestrator-owned N3 lifecycle gate with a provider-free OD-6 preflight, exact-SHA booking, port/evidence discipline, frozen run caps, and evidence under `tmp/router-rollout/v2-network/n3/`.

### Binding Non-Goals

- Installers, downloads, prebuilt asset distribution, update/rollback tooling, or packaged clean-install claims (later `v2-network-packaging-release`).
- N4 external-network gameplay/browser scenarios, relay self-hosting, custom domains, or an OpenTunnel fork.
- Windows server support, any OS/architecture pair other than macOS arm64 and Linux arm64, Node runtime requirements, LAN fallback, OS-keychain integration, or changes to `MULTIPLAYER_MODE` or party-size gates.
- Host controls on the player listener/tunnel, authentication weakening, a second runtime, or automatic sharing at install/login/startup.

## Capabilities

### New Capabilities

None. This change extends existing network and player-boundary contracts.

### Modified Capabilities

- `network-deployment`: specify the production companion path/profile, explicit sharing lifecycle, readiness, supervision, and recovery contract.
- `player-capabilities`: require facilitator lifecycle controls to remain host-only and extend the existing route/event inventory test to prove they are absent from the player application and tunnel target.
- `player-access`: specify private storage and one-time display for the existing N1 verifier/credential, exact generation-bound HTTPS Host/Origin binding, and rotation/revocation of existing sessions and sockets while preserving N1 authentication, cookie, and CSRF rules.

## Impact

Expected implementation surfaces are new or extended modules under `web/extensions/` and `web/extensions/player/`, narrowly marked `# TABLETOP MODE:` host integration/UI changes, and provider-free tests under `scripts/`. Python remains authoritative; React remains presentation-only. Host and player listeners remain separate and loopback-bound (`127.0.0.1`, with the player listener on port 8370); only the player listener may be the OpenTunnel target. Shared runtime behavior remains compatible with 1-PC and 4-PC parties. No dependency, installer, or product binary is added by this change. Gitleaks, Bandit, and strict pip-audit checks apply to implementation.
