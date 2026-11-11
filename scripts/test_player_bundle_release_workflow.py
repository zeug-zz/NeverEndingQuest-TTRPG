"""Offline contract checks for the fork-only player bundle publisher."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/player-bundle-release.yml"
PROCEDURE_PATH = (
    REPO_ROOT
    / "openspec/changes/v2-network-packaging-release/reports/player-bundle-release-procedure.md"
)
BUILDER_PATH = REPO_ROOT / "scripts/network_packaging/build_player_bundle.py"
EXPECTED_TRIGGER = [
    "on:",
    "  push:",
    "    tags:",
    "      - 'v*.*.*'",
]
EXPECTED_ACTIONS = {
    "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803",
    "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
}
SEMVER_REGEX = r"^v[0-9]+\.[0-9]+\.[0-9]+$"


def _significant_lines(lines: list[str]) -> list[str]:
    return [line.rstrip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _root_block(workflow_text: str, key: str) -> list[str]:
    lines = workflow_text.splitlines()
    header = key + ":"
    starts = [index for index, line in enumerate(lines) if line.rstrip() == header]
    if len(starts) != 1:
        return []
    start = starts[0]
    result = [lines[start].rstrip()]
    for line in lines[start + 1 :]:
        if line.strip() and not line[0].isspace():
            break
        result.append(line.rstrip())
    return _significant_lines(result)


def _nested_block(lines: list[str], header: str, indent: int) -> list[str]:
    starts = [
        index
        for index, line in enumerate(lines)
        if len(line) - len(line.lstrip()) == indent and line.strip() == header
    ]
    if len(starts) != 1:
        return []
    start = starts[0]
    result = [lines[start].rstrip()]
    for line in lines[start + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        result.append(line.rstrip())
    return _significant_lines(result)


def _run_blocks(workflow_text: str) -> list[tuple[int, str]]:
    lines = workflow_text.splitlines()
    blocks: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if re.fullmatch(r" {8}run:\s*\|\s*", lines[index]):
            start = index
            index += 1
            body: list[str] = []
            while index < len(lines):
                line = lines[index]
                if line.strip() and len(line) - len(line.lstrip()) <= 8:
                    break
                if line.strip():
                    body.append(line[10:] if line.startswith(" " * 10) else line.lstrip())
                index += 1
            blocks.append((start, "\n".join(body)))
            continue
        index += 1
    return blocks


def _publish_job_block(workflow_text: str) -> list[str]:
    jobs = _root_block(workflow_text, "jobs")
    return _nested_block(jobs, "publish:", 2)


def _has_exact_permissions(workflow_text: str) -> tuple[bool, bool]:
    top_lines = workflow_text.splitlines()
    top_permission_lines = [
        line.rstrip()
        for line in top_lines
        if not line[:1].isspace() and line.startswith("permissions:")
    ]
    top_ok = top_permission_lines == ["permissions: {}"]
    job = _publish_job_block(workflow_text)
    job_permissions = _nested_block(job, "permissions:", 4)
    job_ok = job_permissions == ["    permissions:", "      contents: write"]
    return top_ok, job_ok


def _workflow_contract_errors(
    workflow_text: str,
    repo_root: Path,
    builder_help: str,
) -> set[str]:
    errors: set[str] = set()
    trigger_lines = _root_block(workflow_text, "on")
    if trigger_lines != EXPECTED_TRIGGER or any(
        re.match(r"\s*(pull_request(?:_target)?|workflow_dispatch|schedule)\s*:", line)
        for line in trigger_lines
    ):
        errors.add("trigger")

    top_permissions_ok, job_permissions_ok = _has_exact_permissions(workflow_text)
    if not top_permissions_ok:
        errors.add("top_permissions")
    if not job_permissions_ok:
        errors.add("job_permissions")

    job = _publish_job_block(workflow_text)
    if (
        "    if: github.repository == 'zeug-zz/NeverEndingQuest-TTRPG' && github.event_name == 'push' && github.event.created == true"
        not in job
    ):
        errors.add("repository_event_guard")

    run_blocks = _run_blocks(workflow_text)
    if len(run_blocks) != 10:
        errors.add("run_blocks")
    if any("${{" in body for _, body in run_blocks):
        errors.add("expressions_in_run")
    if any(not body.splitlines() or body.splitlines()[0] != "set -euo pipefail" for _, body in run_blocks):
        errors.add("strict_shell")

    first_run = run_blocks[0][1] if run_blocks else ""
    if SEMVER_REGEX not in first_run:
        errors.add("tag_regex_first")
    elif not re.search(
        r"if \[\[ ! \"\$RELEASE_TAG\" =~ .*?\]\];\s*then(?:(?!\nfi).)*?\bexit 1\b",
        first_run,
        flags=re.DOTALL,
    ):
        errors.add("tag_regex_fail_closed")
    if run_blocks:
        first_run_position = run_blocks[0][0]
        checkout_position = workflow_text.find("uses: actions/checkout@")
        build_position = workflow_text.find("build_player_bundle.py")
        upload_position = workflow_text.find("gh release upload")
        if not (
            checkout_position >= 0
            and build_position >= 0
            and upload_position >= 0
            and first_run_position < workflow_text[:checkout_position].count("\n")
            and first_run_position < workflow_text[:build_position].count("\n")
            and first_run_position < workflow_text[:upload_position].count("\n")
        ):
            errors.add("tag_regex_order")

    if (
        "PLAYER_BUNDLE_PUBLISHERS: ${{ vars.PLAYER_BUNDLE_PUBLISHERS }}" not in workflow_text
        or "REPOSITORY_OWNER: ${{ github.repository_owner }}" not in workflow_text
        or "ACTOR: ${{ github.actor }}" not in workflow_text
    ):
        errors.add("actor_environment")
    actor_runs = [body for _, body in run_blocks if "PLAYER_BUNDLE_PUBLISHERS" in body]
    actor_body = actor_runs[0] if actor_runs else ""
    if not (
        '-z "$PLAYER_BUNDLE_PUBLISHERS"' in actor_body
        and "exit 1" in actor_body
        and '"$REPOSITORY_OWNER" != "zeug-zz"' in actor_body
        and '"${ACTOR,,}" != "${REPOSITORY_OWNER,,}"' in actor_body
        and '"${publisher,,}" == "${ACTOR,,}"' in actor_body
        and re.search(r"\$\{#allowed_publishers\[@\]\}\s*>\s*10(?:\s|\))", actor_body)
        and "${#PLAYER_BUNDLE_PUBLISHERS} -gt 400" in actor_body
    ):
        errors.add("actor_guard")

    action_refs = re.findall(r"(?m)^\s*uses:\s*([^\s#]+)", workflow_text)
    if (
        len(action_refs) != 2
        or set(action_refs) != EXPECTED_ACTIONS
        or any(re.fullmatch(r"actions/(?:checkout|setup-node)@[0-9a-fA-F]{40}", ref) is None for ref in action_refs)
    ):
        errors.add("action_pins")
    if re.search(r"\$\{\{\s*secrets\.", workflow_text):
        errors.add("no_secrets")
    if (
        len(re.findall(r"\$\{\{\s*github\.token\s*\}\}", workflow_text)) != 1
        or "GH_TOKEN: ${{ github.token }}" not in workflow_text
    ):
        errors.add("default_token_only")
    if "--clobber" in workflow_text:
        errors.add("no_clobber")

    checkout = _nested_block(workflow_text.splitlines(), "- name: Check out source and tags", 6)
    if (
        "uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0" not in workflow_text
        or "fetch-depth: 0" not in workflow_text
        or not any("persist-credentials: false" in line for line in checkout)
    ):
        errors.add("checkout_settings")

    ancestry_runs = [body for _, body in run_blocks if "git merge-base --is-ancestor" in body]
    ancestry_body = ancestry_runs[0] if ancestry_runs else ""
    if not (
        'git cat-file -t "$tag_ref"' in ancestry_body
        and '"$tag_object_type" != "tag"' in ancestry_body
        and '"$tag_object_type" != "commit"' in ancestry_body
        and 'git rev-parse --verify "${tag_ref}^{commit}"' in ancestry_body
        and '"$TAG_COMMIT" != "$SOURCE_COMMIT"' in ancestry_body
        and 'git merge-base --is-ancestor "$TAG_COMMIT" origin/main' in ancestry_body
    ):
        errors.add("tag_ancestry")

    frontend_commands = (
        "npm --prefix web/frontend ci",
        "npm --prefix web/frontend run typecheck",
        "npm --prefix web/frontend test -- --run",
        "npm --prefix web/frontend run test:manifest",
        "npm --prefix web/frontend run build",
    )
    if any(command not in workflow_text for command in frontend_commands):
        errors.add("frontend_commands")
    package_path = repo_root / "web/frontend/package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
        node_engine = package["engines"]["node"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        node_engine = ""
    if node_engine != ">=22 <23" or "node-version: '22'" not in workflow_text:
        errors.add("node_version")

    if (
        not BUILDER_PATH.is_file()
        or "python3 -m venv .venv" not in workflow_text
        or "build_player_bundle.py" not in workflow_text
        or "--tag \"$RELEASE_TAG\"" not in workflow_text
        or "--source-commit \"$SOURCE_COMMIT\"" not in workflow_text
        or "--output-dir tmp/player-bundle-release" not in workflow_text
        or not all(flag in builder_help for flag in ("--tag", "--source-commit", "--output-dir", "--dist"))
    ):
        errors.add("builder_cli")

    release_runs = [body for _, body in run_blocks if "gh release upload" in body]
    release_body = release_runs[0] if release_runs else ""
    asset_view = release_body.find("--json assets")
    upload = release_body.find("gh release upload")
    if not (
        "gh release create \"$RELEASE_TAG\"" in release_body
        and "--verify-tag" in release_body
        and "if ! gh release view \"$RELEASE_TAG\"" in release_body
    ):
        errors.add("create_release_if_missing")
    if not (
        asset_view >= 0
        and upload > asset_view
        and '"$asset_name" == "$TARBALL_NAME"' in release_body
        and '"$asset_name" == "$METADATA_NAME"' in release_body
        and "exit 1" in release_body[asset_view:upload]
    ):
        errors.add("existing_asset_guard")
    if not (
        "TARBALL_PATH=\"tmp/player-bundle-release/${TARBALL_NAME}\"" in release_body
        and "METADATA_PATH=\"tmp/player-bundle-release/${METADATA_NAME}\"" in release_body
        and "gh release upload \"$RELEASE_TAG\" \"$TARBALL_PATH\" \"$METADATA_PATH\"" in release_body
    ):
        errors.add("release_assets")

    concurrency = _root_block(workflow_text, "concurrency")
    if not any("group: player-bundle-release-${{ github.ref }}" in line for line in concurrency) or not any(
        "cancel-in-progress: false" in line for line in concurrency
    ):
        errors.add("concurrency")
    if "    timeout-minutes: 30" not in _publish_job_block(workflow_text):
        errors.add("timeout")
    return errors


def _builder_help() -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, str(BUILDER_PATH), "--help"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _mutations() -> list[tuple[str, str, str, str]]:
    return [
        ("tag glob", "      - 'v*.*.*'", "      - 'v*'", "trigger"),
        ("forbidden trigger", "  push:\n", "  pull_request:\n  push:\n", "trigger"),
        ("top permissions", "permissions: {}", "permissions:\n  contents: read", "top_permissions"),
        (
            "job permissions",
            "      contents: write",
            "      contents: write\n      actions: read",
            "job_permissions",
        ),
        (
            "repository guard",
            "github.repository == 'zeug-zz/NeverEndingQuest-TTRPG'",
            "github.repository == 'other/fork'",
            "repository_event_guard",
        ),
        (
            "event guard",
            "github.event_name == 'push'",
            "github.event_name == 'workflow_dispatch'",
            "repository_event_guard",
        ),
        (
            "tag update guard",
            "github.event.created == true",
            "github.event.created == false",
            "repository_event_guard",
        ),
        (
            "tag regex",
            SEMVER_REGEX,
            r"^v.+$",
            "tag_regex_first",
        ),
        (
            "tag gate fails open",
            'echo "Release tag must match v<major>.<minor>.<patch>." >&2\n            exit 1',
            'echo "Release tag must match v<major>.<minor>.<patch>." >&2\n            exit 0',
            "tag_regex_fail_closed",
        ),
        (
            "tag gate moved",
            "      - name: Validate release tag",
            "      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0\n      - name: Validate release tag",
            "tag_regex_order",
        ),
        (
            "missing shell block",
            "        run: |",
            "        shell: bash",
            "run_blocks",
        ),
        (
            "tag ancestry check moved after upload",
            '          existing_assets="$(gh release view "$RELEASE_TAG"',
            '          gh release upload "$RELEASE_TAG" "$TARBALL_PATH" "$METADATA_PATH" --repo "$GH_REPOSITORY"\n          existing_assets="$(gh release view "$RELEASE_TAG"',
            "existing_asset_guard",
        ),
        (
            "unset publisher list",
            'if [[ -z "$PLAYER_BUNDLE_PUBLISHERS" || ${#PLAYER_BUNDLE_PUBLISHERS} -gt 400 ]]; then',
            'if [[ ${#PLAYER_BUNDLE_PUBLISHERS} -gt 400 ]]; then',
            "actor_guard",
        ),
        (
            "unbounded publisher list",
            "${#allowed_publishers[@]} > 10",
            "${#allowed_publishers[@]} > 100",
            "actor_guard",
        ),
        (
            "actor source",
            "ACTOR: ${{ github.actor }}",
            "ACTOR: ${{ github.repository }}",
            "actor_environment",
        ),
        (
            "action not pinned",
            "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1",
            "actions/setup-node@v7",
            "action_pins",
        ),
        (
            "unapproved action",
            "      - name: Set up Node.js",
            "      - name: Set up Node.js\n        uses: actions/cache@0123456789012345678901234567890123456789",
            "action_pins",
        ),
        (
            "secret reference",
            "GH_TOKEN: ${{ github.token }}",
            "GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
            "no_secrets",
        ),
        (
            "wrong token source",
            "GH_TOKEN: ${{ github.token }}",
            "GH_TOKEN: ${{ github.actor }}",
            "default_token_only",
        ),
        (
            "clobber upload",
            '--repo "$GH_REPOSITORY"\n',
            '--repo "$GH_REPOSITORY" --clobber\n',
            "no_clobber",
        ),
        (
            "asset replacement guard",
            'if [[ "$asset_name" == "$TARBALL_NAME" || "$asset_name" == "$METADATA_NAME" ]]; then',
            'if [[ "$asset_name" == "$TARBALL_NAME" ]]; then',
            "existing_asset_guard",
        ),
        (
            "persist credentials",
            "persist-credentials: false",
            "persist-credentials: true",
            "checkout_settings",
        ),
        (
            "shallow checkout",
            "fetch-depth: 0",
            "fetch-depth: 1",
            "checkout_settings",
        ),
        (
            "shell expression interpolation",
            "set -euo pipefail",
            "set -euo pipefail\n          echo '${{ github.actor }}'",
            "expressions_in_run",
        ),
        (
            "tag ancestry",
            'git merge-base --is-ancestor "$TAG_COMMIT" origin/main',
            'git merge-base --is-ancestor "$TAG_COMMIT" other/main',
            "tag_ancestry",
        ),
        (
            "frontend command",
            "npm --prefix web/frontend run test:manifest",
            "npm --prefix web/frontend run lint",
            "frontend_commands",
        ),
        (
            "Node engine mismatch",
            "node-version: '22'",
            "node-version: '20'",
            "node_version",
        ),
        (
            "builder CLI flag",
            "--source-commit \"$SOURCE_COMMIT\"",
            "--commit \"$SOURCE_COMMIT\"",
            "builder_cli",
        ),
        (
            "release asset paths",
            "TARBALL_PATH=\"tmp/player-bundle-release/${TARBALL_NAME}\"",
            "TARBALL_PATH=\"tmp/other/${TARBALL_NAME}\"",
            "release_assets",
        ),
        (
            "release creation",
            'gh release create "$RELEASE_TAG"',
            'gh release edit "$RELEASE_TAG"',
            "create_release_if_missing",
        ),
        (
            "concurrency cancellation",
            "cancel-in-progress: false",
            "cancel-in-progress: true",
            "concurrency",
        ),
        (
            "timeout",
            "timeout-minutes: 30",
            "timeout-minutes: 0",
            "timeout",
        ),
        (
            "strict shell setup",
            "set -euo pipefail",
            "set -euo pipefail ",
            "strict_shell",
        ),
    ]


class PlayerBundleReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.procedure_text = PROCEDURE_PATH.read_text(encoding="utf-8")
        cls.builder_help = _builder_help()

    def test_workflow_contract(self) -> None:
        errors = _workflow_contract_errors(self.workflow_text, REPO_ROOT, self.builder_help)
        self.assertEqual(errors, set(), "workflow contract failures: " + ", ".join(sorted(errors)))

    def test_procedure_documents_tag_and_registry_handoff(self) -> None:
        self.assertIn("v*.*.*", self.procedure_text)
        self.assertIn(SEMVER_REGEX, self.procedure_text)
        self.assertIn("must not create or push release", self.procedure_text)
        for required in (
            "origin/main",
            "git push origin",
            "neq-player-bundle-<version>.tar.gz",
            "neq-player-bundle-<version>.metadata.json",
            "packaging/player-assets.manifest.json",
            "outer_size",
            "Open a PR",
        ):
            self.assertIn(required, self.procedure_text)

    def test_negative_mutations_trip_contract_guards(self) -> None:
        for label, old, new, expected_error in _mutations():
            with self.subTest(mutation=label):
                self.assertIn(old, self.workflow_text, "mutation fixture was not found")
                mutated = self.workflow_text.replace(old, new, 1)
                errors = _workflow_contract_errors(mutated, REPO_ROOT, self.builder_help)
                self.assertIn(expected_error, errors)


if __name__ == "__main__":
    unittest.main()
