# Design

## Context

See `proposal.md` for motivation and `specs/network-distribution/spec.md` for the observable contract. Phase 3 in `plans/v2-server-client-network.md` limits the initial host matrix to macOS arm64 and Linux arm64 and requires verified pinned companion packaging, prebuilt React assets, explicit installation, and clean-install/update evidence.

The archived N0 design pins OpenTunnel v0.6.2 at tag commit `1ad859e17924ec3f6741cbc4cdb54ce381c9007c`. The approved assets are `opentunnel-darwin-arm64.tar.gz` and `opentunnel-linux-arm64.tar.gz`, distributed under the v0.6.2 release URL and MIT license. N0 recorded these archive/executable SHA-256 pairs:

| Platform | Archive SHA-256 (also pinned in upstream `SHA256SUMS`) | Extracted executable SHA-256 |
| --- | --- | --- |
| `darwin-arm64` | `3f4cf4d316db0e341b2995fd5cd44ba79a78aaee534f32199969152397c9e504` | `39991ec74bc79e13917d5e7bc309870f7925d364808b33ec535fef2fc29eeaf8` |
| `linux-arm64` | `3136e3b66157db18e2f2b86bdcbf1c88016b2daeee70c0396a5c9d188eb6f293` | `7876ca698377c11b56781e5577258aa6b73ae763a062fbcdebfa14df2d9edac1` |

The existing resolver accepts a mapping from platform key to exactly `asset_stem` and `sha256`, and validates the executable at `runtime/opentunnel/v0.6.2/<asset-stem>/opentunnel`; it does not search PATH. However, the current `web/extensions/opentunnel_sharing/service.py` production factory accepts an optional injected `companion_manifest` and fails closed when it is absent. No `load_companion_manifest` function or runtime manifest reader is present in the inspected tree. Task 1.3 therefore adds that loader and wires the default production composition to it rather than assuming the loader already exists.

The player asset loader requires a complete `web/frontend/dist/player-manifest.json` and verifies the shell and each listed asset before listener startup. `web/frontend/package.json` builds it with Node 22 and `web/frontend/.gitignore` ignores `dist/`. The existing macOS Git installer updates with `git fetch` and `git pull --ff-only origin main`, creates `.venv`, and preserves existing runtime files; there is no Linux installer. The five existing install/update regression suites named in the task list cover update readiness, runtime cleanliness, docs, fork update routing, and install-root boundaries. `scripts/network_spike/run_linux_leg.sh` is the existing owner-run Linux arm64 Docker mechanism. No `.github/workflows/*` publisher was found.

One further baseline discrepancy is that `git check-ignore` currently ignores `web/frontend/dist/` but returns no ignore rule for `runtime/opentunnel/v0.6.2/manifest.json`. Task 1.1 adds a `/runtime/` ignore rule while keeping the tracked source manifest under `packaging/` visible.

## Goals / Non-Goals

**Goals:**

- Make the committed source manifest the authority for both archive and executable digests; fetched `SHA256SUMS` corroborates but never replaces the local pin.
- Keep download, extraction, and replacement behind an explicit opt-in installer action, with no sharing start, profile initialization, service registration, PATH install, or runtime download.
- Keep previous verified component directories until the replacement executable, runtime manifest, and player bundle have all passed validation.
- Test download, verification, extraction, update, and rollback offline with injected fake downloaders; all scratch and evidence paths are project-relative under `tmp/`.

**Non-Goals:**

- No support certification for x64, Windows server, direct LAN, or any platform pair outside the approved two-entry matrix.
- No change to gameplay mechanics, player auth/lifecycle policy, party-size gates, `MULTIPLAYER_MODE`, or the existing Git update source contract.
- No relay action, tunnel start, service registration, or live evidence during implementation by a builder or during this planning work.

## Decisions

### 1. Separate the committed provenance manifest from the runtime resolver manifest

Track `packaging/opentunnel-v0.6.2.manifest.json` as the source of truth. Its strict schema carries the upstream repository, tag and resolved commit, release and `SHA256SUMS` URLs, MIT license notice, the exact pinned checksum records, and exactly two platform entries. Each platform entry carries the release archive filename, asset stem, archive digest, and extracted-binary `sha256`. The asset stems are `opentunnel-darwin-arm64` and `opentunnel-linux-arm64`.

The explicit installer downloads only from `https://github.com/anomalyco/opentunnel/releases/download/v0.6.2/`, using bounded streaming and timeouts. It checks the local archive pin and the exact matching filename/digest in the fetched `SHA256SUMS` before extraction, safely rejects traversal and non-regular/symlink executable candidates, hashes the extracted binary against the separate executable pin, and sets mode 0755. Fetched checksum text is provenance evidence, not a trust root: a mismatch with the committed pin stops installation. No signature is assumed because N0 found none. All pairs outside macOS arm64 and Linux arm64 fail before download.

Stage under a private install-relative `runtime/.network-staging/` directory on the same filesystem, never in `.venv`/`venv`. Promote only after validation; keep the old versioned directory as a rollback candidate until every component is ready. Then atomically replace the runtime resolver manifest at `runtime/opentunnel/v0.6.2/manifest.json`. It contains only the two supported platform keys, each with exactly `asset_stem` and executable `sha256`, matching the current resolver contract. `load_companion_manifest` will read from the resolved install root, reject unknown/missing/duplicate fields and unsupported entries, and feed the existing `resolve_companion` path. The normal runtime only reads local files and never downloads.

**Simplest alternative considered:** pass hard-coded mappings to the service factory. Rejected because it duplicates pins in code, does not create the required runtime manifest, and cannot give the installer and resolver one auditable source of truth.

### 2. Approved immutable GitHub Release player bundle

The Overseer ruling `neq-n3-packaging-release-route-20261111` approves option 2: publish a versioned player-bundle tarball as a GitHub Release asset on this fork, `zeug-zz/NeverEndingQuest-TTRPG`, built and uploaded by a new GitHub Actions publisher workflow. The workflow's Actions references must be pinned to full commit SHAs. Do not commit `web/frontend/dist/`, and do not add a tester-side Node build fallback. Node is a maintainer/CI build prerequisite only.

The deterministic bundle builder consumes an already-built `web/frontend/dist/`; it does not run npm. The publisher workflow owns the Node build and then invokes the bundle builder. Each release includes `neq-player-bundle-<version>.tar.gz` and a `.metadata.json` sidecar. The sidecar binds the version, Git tag, full source commit, outer SHA-256 and size, player-manifest SHA-256, and `client_build_id`; it has no `built_at` field. The tracked `packaging/player-assets.manifest.json` registry binds the same identity to the release asset names and starts with an empty `versions` object. The installer validates the complete extracted tree through the existing Python player asset loader and uses an atomic replacement that retains the prior verified bundle for rollback.

Release tags are immutable `v<semver>` tags created only from a commit on `main`; a fix ships as a new version and release assets are never replaced. The publisher is authorized only for a release tag created by the Overseer or repository owner, uses only the default `GITHUB_TOKEN` with `contents: write`, requires no other secrets, and never runs for pull requests or forks. Workers may build and test the workflow but may not create release tags. The release-asset route keeps generated output out of source history while independently checking source, bundle, manifest, and build identity. Do not treat the player manifest alone as an authenticity pin: it validates bundle consistency, while the tracked registry and sidecar bind the accepted release identity.

**Simplest alternative considered:** commit `web/frontend/dist/` or build it on tester machines. Both are rejected: committing generated output creates review/merge churn, while a tester-side build makes Node a runtime prerequisite and breaks the approved release route.

### 3. Keep the installer action opt-in and keep Git updates separate from component transactions

Add an explicit `--install-network-sharing` opt-in to both platform installers; absence of the flag means no component download or mutation. The action installs files only and does not initialize a tunnel profile, launch the service, register a service, or change PATH. The macOS installer keeps its existing fork/origin and fast-forward behavior. The Linux counterpart follows the same Git update boundary and is limited to the approved Linux arm64 host pair.

Update the companion and player bundle in a transaction separate from `git pull`. Stage candidates on the installation filesystem, validate all candidates before activation, write the runtime manifest last, and retain the previous verified companion and player bundle until activation checks succeed. On failure, restore both prior payloads and the matching runtime metadata; do not delete or overwrite campaign data, `modules/`, `characters/`, `party_tracker.json`, or unrelated profile state. Local startup remains available even if optional component installation or update fails. No campaign migration is introduced.

**Simplest alternative considered:** install components unconditionally with the Git update. Rejected because software updates must not imply consent to download a network companion or change network capability.

### 4. Define the N3 evidence as a composed, primary-owned gate

Run all provider-free fake-downloader, digest, installer, rollback, and regression tests before any live booking. First finish packaging tasks 1.1-1.6 and produce a clean exact-SHA installation containing the actual v0.6.2 executable, runtime manifest, and verified player bundle. Then the primary orchestrator may book and run `v2-opentunnel-sharing-lifecycle` task 6.2 against that installed package. Task 6.2 is not valid against an injected test manifest or a scratch-only N0 executable.

The packaging N3 verdict composes: (a) clean-install and update/rollback evidence for each approved pair and proof that existing campaigns/unrelated profiles remain intact; and (b) the separately booked task 6.2 live lifecycle evidence for the same source SHA and package pins, proving local play, authenticated remote start/stop, relay loss/restart, revocation/cleanup, and no unintended exposure. The lifecycle live gate and any separately requested live packaging rerun require their own bookings; evidence is never reused across SHAs or bookings. Preserve exact expected-versus-observed assertions, platform/architecture, source SHA, manifest and artifact digests, commands, redacted logs, and teardown checks under `tmp/router-rollout/v2-network/n3/<run-id>/` before teardown. Do not record credentials, private keys, raw invitation URLs, or tokens.

The Linux arm64 N3 leg requires an owner-run Linux host or Docker arm64 execution using the isolation/evidence approach in `scripts/network_spike/run_linux_leg.sh`. An unavailable Docker/Linux host, unsupported architecture, missing row, failed assertion, or incomplete teardown is BLOCKED/FAIL; a macOS result, N0 container feasibility result, or driver exit code cannot waive it. Do not use port 8357 or the installed campaign as the live fixture.

**Simplest alternative considered:** count the N0 platform transport runs or unit tests as N3. Rejected because N0 used scratch binaries and an inert fixture; it did not prove native clean installation/update or the installed production lifecycle.

## Risks / Trade-offs

- [A release asset or fetched checksum file could be replaced] -> Require committed archive and executable pins, check the exact upstream checksum entry, bind player bundle metadata to a tagged source SHA, use immutable release tags/assets, and reject before activation on any mismatch.
- [An interrupted component update could leave mixed versions] -> Stage both payloads, validate them before activation, publish the runtime manifest last, and preserve prior verified payloads until the complete transaction succeeds.
- [A tarball could write outside its staging directory] -> Validate archive entries before extraction, reject traversal and unsafe links, and verify the final regular non-symlink executable remains under the install root.
- [The release-artifact route adds CI governance and permissions] -> Apply the approved actor/tag boundary, use only the default `GITHUB_TOKEN` with `contents: write`, use no other secrets, pin all action references to full commit SHAs, and never publish pull-request or fork builds.
- [Linux arm64 validation may be unavailable to the primary] -> Use the owner-run Linux/Docker mechanism and leave N3 BLOCKED with the exact blocker rather than substituting macOS evidence.

## Migration Plan

1. Add the committed source manifest, runtime ignore boundary, and offline pin/verifier tests.
2. Implement the explicit companion download/extract/install helper with fake downloader tests; add the strict runtime manifest writer/loader and wire production composition.
3. Obtain the task 2.1 owner decision before implementing the prebuilt player-bundle release path. For the recommended release-artifact option, implement the tagged-SHA build, committed artifact metadata, verification/install, and rollback.
4. Add default-off installer integration for macOS and Linux. Validate first installs, component updates, failures, rollback, Git update readiness, and unchanged user data using fake downloaders.
5. Add operational docs, run focused tests and scans, then prepare exact-SHA N3 evidence. Only the primary orchestrator can book and judge task 6.2/live evidence.
6. On failure, keep local play available, restore prior verified companion/assets and runtime manifest, leave unrelated profiles untouched, and record the bounded failure. No campaign data is removed or migrated.

## Rulings

### `neq-n3-packaging-release-route-20261111`

The Overseer approved both the distribution route and release identity policy:

1. **Player asset publication:** publish a versioned GitHub Release tarball on `zeug-zz/NeverEndingQuest-TTRPG`, built and uploaded by a new Actions publisher workflow pinned by commit SHA. Do not commit `web/frontend/dist/`; do not use a tester-side Node build fallback.
2. **Release identity and authority:** bind each bundle release through its sidecar and tracked registry entry to the immutable Git tag, full source commit, outer SHA-256 and size, player-manifest SHA-256, `client_build_id`, and asset names. Tags use immutable `v<semver>` naming and must point to a commit on `main`; fixes ship as new versions and published assets are never replaced. The publisher runs only for a release tag created by the Overseer or repository owner, uses only the default `GITHUB_TOKEN` with `contents: write`, requires no other secrets, and never runs on pull requests or from forks. Workers may build/test the workflow but do not create release tags.

Task 2.2 implements the offline bundle builder, strict empty-by-default pin registry, and explicit-action installer. A separate subsequent task owns the publisher workflow; no workflow file or release asset is created by this ruling task.

The service-loader and runtime-ignore discrepancies above are source findings, not owner decisions: tasks 1.1 and 1.3 explicitly close them before lifecycle use.
