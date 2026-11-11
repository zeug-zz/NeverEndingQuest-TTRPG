# Spec Delta

## Purpose

Defines how supported clean installs receive verified network-sharing components and how their distribution, updates, rollback, and N3 evidence remain safe and reproducible.

## ADDED Requirements

### Requirement: The companion source manifest SHALL pin only approved platform assets

The committed OpenTunnel v0.6.2 source manifest SHALL identify exactly `darwin-arm64` and `linux-arm64`, with each asset stem, upstream archive name, archive SHA-256, extracted executable SHA-256, immutable release-tag provenance, matching upstream `SHA256SUMS` provenance, and MIT license notice. Every other OS/architecture pair SHALL fail closed.

#### Scenario: An approved platform is selected
- **WHEN** the installer runs on macOS arm64 or Linux arm64
- **THEN** it selects only that platform's committed asset stem and digests from the v0.6.2 manifest

#### Scenario: An unapproved platform is selected
- **WHEN** the installer runs on any other OS/architecture pair
- **THEN** it refuses companion installation before download and leaves local play available

### Requirement: Companion installation SHALL require explicit consent and verify before activation

Companion acquisition SHALL occur only after an explicit installer/facilitator action, never during ordinary launch or runtime recovery. The installer SHALL verify the downloaded archive against both the committed digest and the exact upstream `SHA256SUMS` entry before safe extraction, then verify the extracted executable against its committed digest before installation.

#### Scenario: Network components are not selected during installation
- **WHEN** the installer runs with its default options
- **THEN** it does not fetch or install OpenTunnel, start sharing, register a service, modify PATH, or prevent local play

#### Scenario: An explicitly requested archive or executable does not match its pin
- **WHEN** either the archive, its `SHA256SUMS` entry, or the extracted executable differs from the committed pin
- **THEN** the candidate is rejected before activation, the prior verified version remains available, and sharing remains off

#### Scenario: A verified executable is installed
- **WHEN** both archive and executable digests match
- **THEN** the regular non-symlink executable is installed with mode 0755 at `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel` beneath the installation root and outside `.venv`/`venv`

### Requirement: The installed companion manifest SHALL be strict and install-relative

The installer SHALL write `runtime/opentunnel/v0.6.2/manifest.json` from the committed source manifest, and production sharing SHALL consume that runtime manifest without downloading or searching PATH. Invalid, missing, extra-platform, or mismatched fields SHALL fail closed.

#### Scenario: A valid runtime manifest is loaded
- **WHEN** production sharing resolves the companion on an approved platform
- **THEN** it reads that installation's runtime manifest and resolves only the manifest-selected executable and digest

#### Scenario: The runtime manifest is missing or malformed
- **WHEN** the runtime manifest is absent or fails the strict schema or supported-platform checks
- **THEN** sharing reports a bounded unavailable state, starts no companion, and performs no network or PATH lookup

### Requirement: A clean install SHALL receive verified prebuilt player assets without Node

The approved distribution SHALL identify a prebuilt player bundle by tagged source SHA, outer artifact digest, and the existing player manifest/build identity. Installation SHALL verify the outer pin and validate the complete bundle through the player asset contract before replacing `web/frontend/dist`; tester installation and runtime SHALL NOT require Node.

#### Scenario: A tester installs a valid prebuilt bundle
- **WHEN** the installer obtains the bundle identified by the committed release metadata
- **THEN** it verifies the artifact and player manifest, installs the complete bundle, and the player asset loader accepts it without invoking Node

#### Scenario: A bundle is stale, corrupt, or incomplete
- **WHEN** its outer digest, player manifest, build identity, or listed asset bytes do not match
- **THEN** the candidate bundle is rejected, the previous verified bundle is retained, and sharing readiness remains unavailable

### Requirement: Installer updates and rollback SHALL preserve local campaign state

macOS and Linux installers SHALL offer network-sharing components as an optional default-off action. Repository updates SHALL retain the existing fast-forward Git workflow; component update failure SHALL restore the last verified companion, manifest, and player bundle while leaving local gameplay and user data intact.

#### Scenario: Optional component installation is declined
- **WHEN** a clean install or update uses default options or the facilitator declines the network-sharing action
- **THEN** local play remains available and no companion, public route, or start-at-login service is activated

#### Scenario: A component update fails after a prior version is installed
- **WHEN** download, verification, extraction, install, or player bundle validation fails
- **THEN** the previous verified components remain usable, existing campaigns and characters and `party_tracker.json` are unchanged, and unrelated OpenTunnel profiles are untouched

#### Scenario: A repository update is applied
- **WHEN** the Git installer updates an existing installation
- **THEN** it uses the existing origin/fast-forward update boundary and does not require stashing or resetting gameplay state

### Requirement: Operational guides SHALL explain supported installation and recovery

The release SHALL provide facilitator and player guidance for supported platforms, joining and reconnecting, network/privacy limits, failure recovery, and private issue reporting; the guides SHALL not claim Windows hosting or direct LAN fallback.

#### Scenario: A facilitator prepares remote play
- **WHEN** the facilitator follows the quickstart for a supported host
- **THEN** it explains the explicit opt-in install/start sequence, supported platform matrix, local-play behavior, and safe stop/recovery actions

#### Scenario: A player loses the remote session
- **WHEN** a player follows the join/reconnect guide after disconnect or relay loss
- **THEN** the guide explains rejoin/reconnect behavior, facilitator escalation, privacy limitations, and private issue-reporting without asking for credentials or public tunnel URLs

### Requirement: N3 packaging evidence SHALL be primary-owned and platform-complete

The primary orchestrator SHALL judge clean-install and update evidence for macOS arm64 and Linux arm64. The gate SHALL compose with lifecycle task 6.2 using the companion and runtime manifest produced by this capability; missing required evidence SHALL be BLOCKED or FAIL, never waived.

#### Scenario: Both supported platforms complete N3
- **WHEN** the primary reviews clean-install/update evidence and the separately booked lifecycle task 6.2 evidence from the packaged installs
- **THEN** the verdict records local play, authenticated remote start/stop, relay-loss/restart recovery, absence of unintended exposure, campaign preservation, unrelated-profile preservation, expected-versus-observed results, and artifact paths under `tmp/router-rollout/v2-network/n3/<run-id>/`

#### Scenario: The Linux owner-run leg is unavailable
- **WHEN** the Linux arm64 Docker/Linux-host run cannot be performed or its required evidence is missing
- **THEN** N3 remains BLOCKED with the exact blocker and no macOS result substitutes for the Linux leg
