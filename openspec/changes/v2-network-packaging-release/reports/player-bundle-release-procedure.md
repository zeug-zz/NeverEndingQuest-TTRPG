# Player Bundle Release Procedure

This procedure is for the repository owner or an authorized Overseer. Workers
may build and test the publisher workflow, but must not create or push release
tags. Do not replace release assets; publish fixes under a new version.

## Configure publisher authorization

In the fork repository settings, define the repository variable
`PLAYER_BUNDLE_PUBLISHERS` as a comma-separated list of one to ten Overseer
GitHub logins. Use login characters only (letters, digits, and hyphens), with
no spaces. The repository owner is also authorized by owner equality, but the
variable must still be set and non-empty; an unset variable fails closed.
This is a repository variable, not a secret.

## Create a release tag from main

Choose a new semantic version. Confirm the selected full commit SHA is already
an ancestor of the fork's `origin/main`; the publisher repeats this check after
checkout. The Actions tag filter is the GitHub glob `v*.*.*`; the first shell
step applies the strict regex `^v[0-9]+\.[0-9]+\.[0-9]+$` before checkout,
build, or release-token use, so matching malformed tags fail closed.
The publish job also requires a newly created tag push; an update to an
existing tag is skipped.

The owner or Overseer creates an annotated tag from that reviewed main commit
and pushes only the tag to the fork's `origin`:

```bash
TAG=v1.2.3
RELEASE_COMMIT="<full-40-hex-commit-already-on-origin-main>"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$RELEASE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]
git fetch origin main
git merge-base --is-ancestor "$RELEASE_COMMIT" origin/main
git tag -a "$TAG" "$RELEASE_COMMIT" -m "Player bundle $TAG"
git push origin "$TAG"
```

Use a version that has never been released. Do not move or recreate a release
tag. The workflow also accepts a lightweight tag, but an annotated tag is the
recommended operator procedure. The workflow runs only on tag pushes in
`zeug-zz/NeverEndingQuest-TTRPG`, checks the actor, tag target, and `origin/main`,
then runs the frontend checks and deterministic bundle builder.

## Review workflow output

The workflow uses Node 22 to run `npm ci`, frontend typechecking, the frontend
test suite, manifest tests, and the production build. It packages the validated
`web/frontend/dist/` tree without installing Python dependencies. A successful
run creates or uses the matching GitHub Release and uploads exactly:

- `neq-player-bundle-<version>.tar.gz`
- `neq-player-bundle-<version>.metadata.json`

The sidecar records the version, tag, full source commit, tarball SHA-256 and
size, player-manifest SHA-256, and `client_build_id`. If either expected asset
name already exists on the Release, the workflow fails without replacing it.

## Add the version pin through a PR

After the release workflow succeeds, download and inspect the sidecar asset:

```bash
TAG=v1.2.3
mkdir -p tmp/player-bundle-metadata
gh release download "$TAG" \
  --repo zeug-zz/NeverEndingQuest-TTRPG \
  --pattern "neq-player-bundle-${TAG#v}.metadata.json" \
  --dir tmp/player-bundle-metadata
cat "tmp/player-bundle-metadata/neq-player-bundle-${TAG#v}.metadata.json"
```

Open a PR that adds one entry under `versions` in
`packaging/player-assets.manifest.json`. Copy `tag`, `source_commit`,
`outer_sha256`, `player_manifest_sha256`, and `client_build_id` from the
sidecar. Map sidecar `outer_size` to registry field `size`. Set
`release_asset_name` to `neq-player-bundle-<version>.tar.gz` and
`metadata_asset_name` to `neq-player-bundle-<version>.metadata.json`. Preserve
the registry's exact field set and the metadata values; do not infer or
recalculate a digest from an unverified local build. Run the focused offline
player-asset distribution tests and obtain review before merging the PR.

No worker creates tags or releases, and this procedure does not authorize
creating a tag as part of implementation or test verification.
