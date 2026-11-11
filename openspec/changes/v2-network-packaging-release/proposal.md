# Proposal

## Why

N0 verified OpenTunnel v0.6.2 only in scratch space, while the production sharing lifecycle intentionally fails closed until a pinned, install-relative companion and runtime manifest are supplied. The player build is also gitignored and requires Node to generate, so a clean tester install currently has neither a distributable companion nor the prebuilt player assets required for sharing.

## What Changes

- Add a committed OpenTunnel v0.6.2 source manifest for macOS arm64 and Linux arm64 only, pinning each upstream archive and extracted executable, recording the immutable upstream tag/SHA256SUMS provenance, and preserving the MIT license notice.
- Add an explicitly invoked, offline-testable fetch/verify/install action that verifies before extraction, installs a non-symlink 0755 executable under the install-relative `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel` path, and supplies the strict runtime manifest consumed by sharing. The action is never part of ordinary launch, uses no PATH installation or service registration, and is unavailable for all other platform pairs.
- Decide and implement a digest-pinned distribution path for prebuilt React player assets, validating the existing `player-manifest.json` and installing into `web/frontend/dist` without requiring Node on tester machines. Record owner approval as a prerequisite for any release-publishing workflow or tracked build-output change.
- Add default-off optional network-sharing component installation to the macOS installer and a new Linux installer, preserving the existing Git update workflow and local play. Updates and rollback retain prior verified companion/assets until the replacement has passed checks.
- Add update/rollback coverage with fake downloaders, operational facilitator/player guides, security and clean-install/update verification, and a primary-owned N3 evidence gate for both supported platform pairs.

### Binding Scope and Non-Goals

- Supported server pairs are only macOS arm64 (`darwin-arm64`) and Linux arm64 (`linux-arm64`); every other OS/architecture fails closed.
- Installation is an explicit facilitator/installer action and does not start sharing. Local play remains usable without OpenTunnel or internet access; updates preserve campaigns, characters, party state, and unrelated tunnel profiles.
- No Windows server packaging, direct LAN fallback, required Node runtime for testers, relay self-hosting, custom domains, OpenTunnel fork, ADR change, security relaxation, `MULTIPLAYER_MODE` edit, or party-size gate change.
- No network fetch, tunnel/relay activity, or live gate is performed while authoring this change.

## Capabilities

### New Capabilities

- `network-distribution`: pinned companion and player-asset distribution, explicit optional installation, platform failure behavior, update/rollback safety, and N3 packaging evidence.

### Modified Capabilities

None. The existing `network-deployment` and player lifecycle contracts remain authoritative; this capability supplies the packaged companion and assets those contracts consume.

## Impact

Expected implementation surfaces are `packaging/opentunnel-v0.6.2.manifest.json`, the OpenTunnel acquisition/verification helper, a strict runtime-manifest loader in `web/extensions/opentunnel_sharing/service.py`, `install_neverendingquest_macos.sh`, a new `install_neverendingquest_linux.sh`, and the prebuilt-asset release/install pipeline. Runtime payloads remain install-local and gitignored; player assets continue to be checked by `web/extensions/player/assets.py`. Tests cover archive and executable digest mismatch, unsafe extraction, unsupported platforms, update/rollback, and existing Git-based update/runtime-state contracts. Operational docs are proposed under `docs/network/`. Shared gameplay state and its 1-PC regression floor and multi-PC compatibility are unchanged. No product code or documentation is authorized by this proposal alone.
