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

A clean install MUST receive a verified prebuilt bundle from the approved release metadata; tester setup MUST NOT require Node.

#### Scenario: A tester installs a valid prebuilt bundle
- **WHEN** the installer obtains the bundle identified by the committed release metadata
- **THEN** it downloads the versioned `neq-player-bundle-<version>.tar.gz` from a GitHub Release on `zeug-zz/NeverEndingQuest-TTRPG`, verifies its sidecar and tracked registry pin, installs the complete bundle, and the Python player asset loader accepts it without invoking Node

#### Scenario: A bundle is stale, corrupt, or incomplete
- **WHEN** its outer digest, player manifest, build identity, or listed asset bytes do not match
- **THEN** the candidate bundle is rejected, the previous verified bundle is retained, and sharing readiness remains unavailable

### Requirement: The player asset registry SHALL strictly pin release identity

The tracked registry SHALL bind each release version to its exact player asset names and digests using a fixed fork release URL.

#### Scenario: The initial registry and a release entry are read
- **WHEN** the strict registry loader reads the initial or populated `packaging/player-assets.manifest.json`
- **THEN** the initial document is exactly `{"versions": {}}`; each entry has exactly `{tag, source_commit, outer_sha256, size, player_manifest_sha256, client_build_id, release_asset_name, metadata_asset_name}`; tags match `^v[0-9]+\.[0-9]+\.[0-9]+$`, source commits have 40 hex digits, SHA-256 values have 64 lowercase hex digits, asset names match only the tarball and `.metadata.json` patterns for a numeric semantic version, and download URLs use only `https://github.com/zeug-zz/NeverEndingQuest-TTRPG/releases/download/<tag>/`

#### Scenario: A registry or metadata document is malformed
- **WHEN** either document has duplicate JSON keys, missing/extra fields, invalid digests or tags, or a disallowed asset name
- **THEN** the loader rejects it before download or installation; the sidecar has exactly `{schema, version, git_tag, source_commit, outer_sha256, outer_size, player_manifest_sha256, client_build_id}` and no `built_at`

### Requirement: The bundle builder SHALL produce a reproducible validated archive

The builder SHALL consume an already-built player tree and shall not invoke npm.

#### Scenario: A valid prebuilt player tree is packaged
- **WHEN** the builder receives a complete `web/frontend/dist/` tree
- **THEN** it validates the full `player-manifest.json`, `client_build_id`, and every listed asset using `web.extensions.player.assets.load_player_client_assets`; emits `neq-player-bundle-<version>.tar.gz` and its `.metadata.json` sidecar; binds the sidecar to the version, Git tag, full 40-hex source commit, outer SHA-256 and size, player-manifest SHA-256, and build ID; and omits `built_at`

#### Scenario: The same player tree is packaged twice
- **WHEN** the same validated tree and release identity are built twice
- **THEN** the tarball SHA-256 is identical, with sorted archive paths and normalized mtime, uid, gid, modes, and ordering

#### Scenario: A tag or source commit argument is invalid
- **WHEN** a build argument does not match `^v[0-9]+\.[0-9]+\.[0-9]+$` or a full 40-hex commit
- **THEN** the builder refuses to produce release artifacts

### Requirement: Player bundle installation SHALL be explicit, bounded, and atomic

Installation SHALL verify the full bundle before replacing the installed player tree.

#### Scenario: A release bundle is installed explicitly
- **WHEN** the installer is invoked with `--install --version X` for a version in the strict registry
- **THEN** it reuses the OpenTunnel downloader guards; uses HTTPS, the GitHub host and existing CDN redirect allowlist, bounded time/size, no environment proxies, and mode-0700 `.part` staging; verifies the outer SHA-256 against the registry and sidecar; rejects traversal, links, devices, and over-cap files; validates every listed asset and the pinned `client_build_id`; and does not touch campaign data

#### Scenario: A verified bundle is already installed
- **WHEN** the installed bundle already matches the selected registry pin
- **THEN** installation is idempotent and does not replace the matching bundle

#### Scenario: An install fails during replacement
- **WHEN** validation or any step after the atomic swap fails
- **THEN** the installer atomically replaces `web/frontend/dist`, retains the previous bundle as `dist.previous` until the replacement is verified and loadable, restores it on failure, and refuses install roots under `.venv` or `venv`

### Requirement: The player-bundle publisher SHALL enforce immutable release authority

The publisher SHALL enforce the authorized immutable release boundary and shall never replace published assets.

#### Scenario: An authorized release tag is published
- **WHEN** the Overseer or repository owner publishes an immutable `v<semver>` tag pointing to a commit on `main`
- **THEN** the workflow on `zeug-zz/NeverEndingQuest-TTRPG` builds/tests the web client, invokes the deterministic bundle builder, and uploads the tarball and metadata sidecar to that fork's matching GitHub Release using only the default `GITHUB_TOKEN` with `contents: write`; every Actions dependency is pinned by full commit SHA and no other secret is used

#### Scenario: A tag or workflow trigger is unauthorized
- **WHEN** the workflow is triggered by a pull request, fork, non-authorized actor, mutable/non-semver tag, or tag not resolving to a commit on `main`
- **THEN** it does not publish assets; workers may build and test the workflow but do not create release tags

#### Scenario: A release asset already exists
- **WHEN** a publication attempts to use an existing release asset name
- **THEN** the workflow fails without replacing the existing asset; a fix requires a new version and tag

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
