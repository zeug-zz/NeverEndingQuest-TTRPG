# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free exact-head, approval, and no-bypass preflight tests."""

from __future__ import annotations

from contextlib import ExitStack
import builtins
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.request

_SCRIPT_PATH = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(_SCRIPT_PATH)))

from scripts.mise_en_scene.llm_staging_study3b import preflight, protocol
from scripts.mise_en_scene.llm_staging_study3b.isolation import PREP_ROOT_RELATIVE


REPO_ROOT = Path(os.path.dirname(os.path.dirname(_SCRIPT_PATH)))
GOOD_SHA = "a" * 40
GOOD_CI_SHA256 = "b" * 64


def _valid_check_runs(head_sha: str = GOOD_SHA) -> dict[str, object]:
    rows = []
    for name in preflight.REQUIRED_CI_CHECK_NAMES:
        slug, app_name, app_id = preflight._CI_APP_BY_CHECK[name]
        rows.append(
            {
                "name": name,
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": "success",
                "app": {"id": app_id, "slug": slug, "name": app_name},
            }
        )
    return {"total_count": len(rows), "check_runs": rows}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")


def _synthetic_ruling_source() -> tuple[bytes, bytes]:
    section = (
        b"## Ruling: "
        + preflight.DISPATCH_RULING_ID.encode("ascii")
        + b"\n"
        + b"\n".join(preflight._RULING_REQUIRED_SCOPE)
        + b"\n"
    )
    return section + b"<!-- /ruling -->\n", section


def _synthetic_continuation_ruling_source() -> tuple[bytes, bytes]:
    section = (
        b"## Ruling: "
        + preflight.CONTINUATION_RULING_ID.encode("ascii")
        + b"\nSynthetic Study 3b continuation authorization fixture.\n"
    )
    return section + b"<!-- /ruling -->\n", section


def _verified_readiness_fixture() -> preflight.ReadinessVerification:
    return preflight.ReadinessVerification(
        status="READY",
        reason_codes=(),
        study_id=protocol.STUDY_ID,
        expected_head_sha=GOOD_SHA,
        current_head_sha=GOOD_SHA,
        ci_check_count=len(preflight.REQUIRED_CI_CHECK_NAMES),
        preflight_gate_count=len(preflight.REQUIRED_PREFLIGHT_COMMANDS),
        external_provenance_verified=True,
        live_dispatch_permitted=True,
        ruling_id=preflight.DISPATCH_RULING_ID,
        ruling_section_sha256=preflight.PINNED_RULING_SECTION_SHA256,
        ci_evidence_path=PREP_ROOT_RELATIVE + "/synthetic-ci.json",
        ci_evidence_sha256=GOOD_CI_SHA256,
        evidence_relative_path=PREP_ROOT_RELATIVE + "/readiness/synthetic.json",
        evidence_sha256="c" * 64,
        _proof=preflight._CONTINUATION_READY_PROOF,
    )


def _pinned_ruling_summary() -> dict[str, object]:
    return {
        "ruling_id": preflight.DISPATCH_RULING_ID,
        "section_sha256": preflight.PINNED_RULING_SECTION_SHA256,
        "authority": "OVERSEER_STANDING_AUTHORITY; NO_NEW_OWNER_APPROVAL_REQUESTED",
        "approved_study_id": protocol.STUDY_ID,
        "approved_protocol_sha256": protocol.PROTOCOL_SHA256,
        "approved_generation_config_sha256": protocol.GENERATION_CONFIG_SHA256,
        "approved_final_head_sha": "BOUND_AT_PREFLIGHT_TO_EXACT_LOCAL_HEAD",
        "attempt_cap": 3,
        "attempts_per_scene": 1,
        "max_tokens": 16384,
        "timeout_seconds": 720,
        "hard_ceiling_usd": "0.05",
    }


class Study3bPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = {"network": 0, "provider_import": 0, "credential": 0}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

        def block_network(*_args: object, **_kwargs: object) -> None:
            self.calls["network"] += 1
            raise AssertionError("preflight tests must not use network")

        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object):
            if name.split(".", 1)[0] in {"openai", "requests", "httpx", "anthropic"}:
                self.calls["provider_import"] += 1
                raise AssertionError("provider imports are forbidden")
            return original_import(name, *args, **kwargs)

        original_getenv = os.getenv

        def guarded_getenv(key: str, default: object = None):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("provider credentials are forbidden")
            return original_getenv(key, default)

        environ_type = type(os.environ)
        original_env_get = environ_type.get
        original_env_getitem = environ_type.__getitem__

        def guarded_env_get(env: object, key: object, default: object = None):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("provider credentials are forbidden")
            return original_env_get(env, key, default)

        def guarded_env_getitem(env: object, key: object):
            if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
                self.calls["credential"] += 1
                raise AssertionError("provider credentials are forbidden")
            return original_env_getitem(env, key)

        for target, attribute in (
            (socket, "create_connection"),
            (socket, "getaddrinfo"),
            (socket.socket, "connect"),
            (urllib.request, "urlopen"),
        ):
            self.stack.enter_context(
                patch.object(target, attribute, side_effect=block_network)
            )
        self.stack.enter_context(patch.object(builtins, "__import__", guarded_import))
        self.stack.enter_context(patch.object(os, "getenv", guarded_getenv))
        self.stack.enter_context(
            patch.object(environ_type, "get", guarded_env_get)
        )
        self.stack.enter_context(
            patch.object(environ_type, "__getitem__", guarded_env_getitem)
        )
        self.addCleanup(self._assert_no_external_activity)

    def _assert_no_external_activity(self) -> None:
        self.assertEqual(
            self.calls,
            {"network": 0, "provider_import": 0, "credential": 0},
        )

    def _install_synthetic_ruling_syscalls(
        self,
        stack: ExitStack,
        *,
        symlink_at: str | None = None,
    ) -> dict[str, object]:
        campaign_fd = 41
        rulings_fd = 42
        file_fd = 43
        contents, _section = _synthetic_ruling_source()
        reads = {"offset": 0}
        opened: list[tuple[object, int | None]] = []
        statted: list[tuple[object, int]] = []
        closed: list[int] = []

        def metadata(mode: int, inode: int, *, size: int = 0, links: int = 2):
            return os.stat_result(
                (
                    mode,
                    inode,
                    7,
                    links,
                    os.geteuid(),
                    os.getegid(),
                    size,
                    1,
                    1,
                    1,
                )
            )

        root_info = metadata(stat.S_IFDIR | 0o755, 101)
        rulings_info = metadata(
            stat.S_IFLNK | 0o777 if symlink_at == "rulings" else stat.S_IFDIR | 0o755,
            102,
        )
        file_info = metadata(
            stat.S_IFLNK | 0o777 if symlink_at == "B.md" else stat.S_IFREG | 0o600,
            103,
            size=len(contents),
            links=1,
        )

        def fake_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            directory_fd = kwargs.get("dir_fd")
            opened.append((path, directory_fd))
            self.assertTrue(flags & getattr(os, "O_NOFOLLOW", 0))
            if Path(path) == preflight.RULING_CAMPAIGN_TREE_ROOT:
                self.assertIsNone(directory_fd)
                self.assertTrue(flags & getattr(os, "O_DIRECTORY", 0))
                return campaign_fd
            if path == "rulings" and directory_fd == campaign_fd:
                self.assertTrue(flags & getattr(os, "O_DIRECTORY", 0))
                return rulings_fd
            if path == "B.md" and directory_fd == rulings_fd:
                return file_fd
            raise AssertionError("ruling open escaped the exact campaign-tree anchor")

        def fake_stat(
            path: object,
            *,
            dir_fd: int | None = None,
            follow_symlinks: bool = True,
        ):
            statted.append((path, dir_fd))
            self.assertFalse(follow_symlinks)
            if path == "rulings" and dir_fd == campaign_fd:
                return rulings_info
            if path == "B.md" and dir_fd == rulings_fd:
                return file_info
            raise AssertionError("ruling stat escaped the exact campaign-tree anchor")

        def fake_fstat(descriptor: int):
            if descriptor == campaign_fd:
                return root_info
            if descriptor == rulings_fd:
                return rulings_info
            if descriptor == file_fd:
                return file_info
            raise AssertionError("unexpected ruling file descriptor")

        def fake_read(descriptor: int, size: int) -> bytes:
            self.assertEqual(descriptor, file_fd)
            start = reads["offset"]
            end = min(start + size, len(contents))
            reads["offset"] = end
            return contents[start:end]

        def fake_close(descriptor: int) -> None:
            closed.append(descriptor)

        for name, replacement in (
            ("open", fake_open),
            ("stat", fake_stat),
            ("fstat", fake_fstat),
            ("read", fake_read),
            ("close", fake_close),
        ):
            stack.enter_context(patch.object(preflight.os, name, side_effect=replacement))
        return {
            "opened": opened,
            "statted": statted,
            "closed": closed,
            "contents": contents,
        }

    def _write_ci_fixture(self, payload: object, *, mtime: float | None = None) -> str:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="study3b-preflight-test-",
            dir=REPO_ROOT / PREP_ROOT_RELATIVE,
        )
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "check-runs.json"
        path.write_bytes(_canonical_json(payload))
        os.chmod(path, 0o600)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path.relative_to(REPO_ROOT).as_posix()

    def test_valid_ci_requires_all_eleven_same_head_and_exact_producers(self) -> None:
        summary = preflight._validate_check_runs(
            _canonical_json(_valid_check_runs()),
            GOOD_SHA,
        )
        self.assertEqual(summary["required_check_count"], 11)
        self.assertEqual(
            summary["app_identities"]["github-actions"]["id"],
            15368,
        )
        self.assertEqual(
            summary["app_identities"]["github-advanced-security"]["id"],
            57789,
        )
        self.assertTrue(
            all(row["head_sha"] == GOOD_SHA for row in summary["required_checks"])
        )

    def test_forged_nonrequired_producer_cannot_supply_required_check(self) -> None:
        payload = _valid_check_runs()
        checks = payload["check_runs"]
        assert isinstance(checks, list)
        forged = checks[0]
        assert isinstance(forged, dict)
        forged["app"] = {"id": 99999, "slug": "third-party", "name": "Other CI"}
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_check_runs(_canonical_json(payload), GOOD_SHA)
        self.assertEqual(
            blocked.exception.code,
            "CI_REQUIRED_CHECK_PRODUCER_STATE_OR_SHA_INVALID",
        )

    def test_missing_required_check_is_rejected(self) -> None:
        payload = _valid_check_runs()
        checks = payload["check_runs"]
        assert isinstance(checks, list)
        checks.pop()
        payload["total_count"] = len(checks)
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_check_runs(_canonical_json(payload), GOOD_SHA)
        self.assertEqual(blocked.exception.code, "CI_REQUIRED_CHECK_SET_INCOMPLETE")

    def test_non_sha_and_reused_head_evidence_are_rejected(self) -> None:
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_check_runs(
                _canonical_json(_valid_check_runs()),
                "not-a-sha",
            )
        self.assertEqual(blocked.exception.code, "CI_EVIDENCE_SIZE_OR_HEAD_INVALID")

        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_check_runs(
                _canonical_json(_valid_check_runs("c" * 40)),
                GOOD_SHA,
            )
        self.assertEqual(
            blocked.exception.code,
            "CI_REQUIRED_CHECK_PRODUCER_STATE_OR_SHA_INVALID",
        )

    def test_stale_ci_file_is_rejected(self) -> None:
        old_time = time.time() - preflight.MAX_CI_EVIDENCE_AGE_SECONDS - 30
        relative_path = self._write_ci_fixture(_valid_check_runs(), mtime=old_time)
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._read_ci_evidence(relative_path)
        self.assertEqual(blocked.exception.code, "CI_EVIDENCE_STALE")

    def test_wrong_ruling_id_and_altered_authoritative_section_are_rejected(self) -> None:
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_inputs(
                expected_head_sha=GOOD_SHA,
                ci_evidence_path=PREP_ROOT_RELATIVE + "/ci.json",
                ci_evidence_sha256=GOOD_CI_SHA256,
                dispatch_ruling_id="neq-s-study3-unblock-20261111",
            )
        self.assertEqual(blocked.exception.code, "DISPATCH_RULING_ID_MISMATCH")

        altered = (
            b"## Ruling: "
            + preflight.DISPATCH_RULING_ID.encode("ascii")
            + b"\nChanged authorization.\n<!-- /ruling -->\n"
        )
        with patch.object(preflight, "_read_ruling_source", return_value=altered):
            with self.assertRaises(preflight.ReadinessBlocked) as blocked:
                preflight._verify_adjudication_ruling()
        self.assertEqual(
            blocked.exception.code,
            "ADJUDICATION_RULING_SECTION_HASH_MISMATCH",
        )

    def test_missing_ci_path_and_digest_mismatch_fail_before_remote_or_local_gates(self) -> None:
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._validate_inputs(
                expected_head_sha=GOOD_SHA,
                ci_evidence_path=None,
                ci_evidence_sha256=GOOD_CI_SHA256,
                dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
            )
        self.assertEqual(blocked.exception.code, "CI_EVIDENCE_PATH_REQUIRED")

        relative_path = self._write_ci_fixture(_valid_check_runs())
        with patch.object(
            preflight,
            "_read_local_git_state",
            return_value=(GOOD_SHA, b""),
        ), patch.object(
            preflight, "_validate_fixed_study_and_cost", return_value={}
        ), patch.object(preflight, "_assert_fresh_run_root"), patch.object(
            preflight,
            "_verify_adjudication_ruling",
            return_value={
                "ruling_id": preflight.DISPATCH_RULING_ID,
                "section_sha256": preflight.PINNED_RULING_SECTION_SHA256,
            },
        ), patch.object(
            preflight,
            "_verify_pull_request_head",
            side_effect=AssertionError("CI digest mismatch must stop before PR query"),
        ), patch.object(
            preflight,
            "_run_provider_free_preflight",
            side_effect=AssertionError("CI digest mismatch must stop before local gates"),
        ), patch.object(
            preflight,
            "_write_immutable_evidence",
            return_value=(PREP_ROOT_RELATIVE + "/readiness/blocked.json", "c" * 64),
        ):
            result = preflight.verify_live_readiness(
                expected_head_sha=GOOD_SHA,
                ci_evidence_path=relative_path,
                ci_evidence_sha256="d" * 64,
                dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
            )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("CI_EVIDENCE_SHA256_MISMATCH", result.reason_codes)
        self.assertFalse(preflight.is_verified_readiness(result))

    def test_authoritative_ruling_is_pinned_and_scope_matches_study3b(self) -> None:
        raw, section = _synthetic_ruling_source()
        fixture_sha256 = hashlib.sha256(section).hexdigest()
        self.assertEqual(
            preflight.PINNED_RULING_SECTION_SHA256,
            "950ed79edc700cd1e81b58d9d8e1a43241c1348e975416cfeb324ff18b9917ca",
        )
        with patch.object(preflight, "_read_ruling_source", return_value=raw), patch.object(
            preflight,
            "PINNED_RULING_SECTION_SHA256",
            fixture_sha256,
        ):
            summary = preflight._verify_adjudication_ruling()
        self.assertEqual(summary["ruling_id"], preflight.DISPATCH_RULING_ID)
        self.assertEqual(
            summary["section_sha256"],
            fixture_sha256,
        )
        self.assertEqual(summary["approved_study_id"], protocol.STUDY_ID)
        self.assertEqual(summary["approved_protocol_sha256"], protocol.PROTOCOL_SHA256)
        self.assertEqual(
            summary["approved_generation_config_sha256"],
            protocol.GENERATION_CONFIG_SHA256,
        )
        self.assertEqual(summary["hard_ceiling_usd"], "0.05")

    def test_continuation_ruling_is_uniquely_hash_pinned(self) -> None:
        raw, section = _synthetic_continuation_ruling_source()
        fixture_sha256 = hashlib.sha256(section).hexdigest()
        self.assertEqual(
            preflight.CONTINUATION_RULING_ID,
            "neq-s-study3b-adjudication-20261111",
        )
        self.assertEqual(
            preflight.PINNED_CONTINUATION_RULING_SECTION_SHA256,
            "b9e2a414e7b5234bd3453bd42b689515a3215ab2e6690580c6abe91c7746fce8",
        )
        with patch.object(preflight, "_read_ruling_source", return_value=raw), patch.object(
            preflight,
            "PINNED_CONTINUATION_RULING_SECTION_SHA256",
            fixture_sha256,
        ):
            summary = preflight._verify_study3b_continuation_ruling()
        self.assertEqual(
            summary,
            {
                "ruling_id": preflight.CONTINUATION_RULING_ID,
                "section_sha256": fixture_sha256,
            },
        )

        altered = raw.replace(b"authorization fixture", b"altered fixture")
        with patch.object(preflight, "_read_ruling_source", return_value=altered):
            with self.assertRaises(preflight.ReadinessBlocked) as blocked:
                preflight._verify_study3b_continuation_ruling()
        self.assertEqual(
            blocked.exception.code,
            "STUDY3B_CONTINUATION_RULING_HASH_MISMATCH",
        )

    def test_continuation_readiness_requires_verified_object_and_rechecks_gates(self) -> None:
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight.assert_study3b_continuation_readiness_current(True)
        self.assertEqual(
            blocked.exception.code,
            "LIVE_CONTINUATION_READINESS_PROOF_REQUIRED",
        )

        readiness = _verified_readiness_fixture()
        self.assertTrue(preflight.is_verified_continuation_readiness(readiness))
        prior_readiness = replace(readiness, _proof=preflight._READY_PROOF)
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight.assert_study3b_continuation_readiness_current(prior_readiness)
        self.assertEqual(
            blocked.exception.code,
            "LIVE_CONTINUATION_READINESS_PROOF_REQUIRED",
        )
        ruling = {
            "ruling_id": preflight.CONTINUATION_RULING_ID,
            "section_sha256": preflight.PINNED_CONTINUATION_RULING_SECTION_SHA256,
        }
        with patch.object(
            preflight, "_assert_dispatch_readiness_current"
        ) as current, patch.object(
            preflight,
            "_verify_study3b_continuation_ruling",
            return_value=ruling,
        ):
            self.assertEqual(
                preflight.assert_study3b_continuation_readiness_current(readiness),
                ruling,
            )
        current.assert_called_once_with(
            readiness,
            require_fresh_run_root=False,
        )

    def test_continuation_readiness_rechecks_exact_head_ci_and_persisted_proof(self) -> None:
        raw = _canonical_json(_valid_check_runs())
        readiness = replace(
            _verified_readiness_fixture(),
            ci_evidence_sha256=hashlib.sha256(raw).hexdigest(),
        )
        ci_summary = preflight._validate_check_runs(raw, GOOD_SHA)
        baseline_pin = preflight._BaselinePin(
            evidence_sha256="d" * 64,
            inventory_sha256="e" * 64,
            file_count=1,
            opaque_bytes_count=0,
            files=(),
        )
        persisted_evidence = {
            "ci_evidence": {
                "required_checks": ci_summary["required_checks"],
                "app_identities": ci_summary["app_identities"],
            }
        }
        continuation_ruling = {
            "ruling_id": preflight.CONTINUATION_RULING_ID,
            "section_sha256": preflight.PINNED_CONTINUATION_RULING_SECTION_SHA256,
        }
        with patch.object(
            preflight,
            "_read_local_git_state",
            side_effect=[(GOOD_SHA, b""), (GOOD_SHA, b"")],
        ) as local_state, patch.object(
            preflight, "_validate_fixed_study_and_cost"
        ), patch.object(
            preflight,
            "_verify_adjudication_ruling",
            return_value=_pinned_ruling_summary(),
        ), patch.object(
            preflight, "_assert_fresh_run_root"
        ) as fresh_root, patch.object(
            preflight, "_read_ci_evidence", return_value=(raw, None)
        ) as read_ci, patch.object(
            preflight,
            "_verify_pull_request_head",
            return_value={"number": 127, "is_draft": True, "head_sha": GOOD_SHA},
        ) as verify_pr, patch.object(
            preflight, "_load_baseline_pin", return_value=baseline_pin
        ), patch.object(
            preflight, "_assert_baseline_unchanged"
        ), patch.object(
            preflight,
            "_verify_persisted_readiness_evidence",
            return_value=persisted_evidence,
        ) as verify_evidence, patch.object(
            preflight,
            "_verify_study3b_continuation_ruling",
            return_value=continuation_ruling,
        ):
            result = preflight.assert_study3b_continuation_readiness_current(
                readiness
            )

        self.assertEqual(result, continuation_ruling)
        self.assertEqual(local_state.call_count, 2)
        read_ci.assert_called_once_with(readiness.ci_evidence_path)
        verify_pr.assert_called_once_with(GOOD_SHA)
        verify_evidence.assert_called_once()
        fresh_root.assert_not_called()

    def test_ruling_reader_uses_exact_campaign_root_and_relative_no_follow_walk(self) -> None:
        expected_root = Path(
            "/Users/zeug/Projects/NeverEndingQuest/.git/overseer-relay/campaigns/neq-current-build"
        )
        self.assertEqual(preflight.RULING_CAMPAIGN_TREE_ROOT, expected_root)
        with ExitStack() as stack:
            calls = self._install_synthetic_ruling_syscalls(stack)
            raw = preflight._read_ruling_source()
        self.assertEqual(raw, calls["contents"])
        self.assertEqual(
            calls["opened"],
            [
                (expected_root, None),
                ("rulings", 41),
                ("B.md", 42),
            ],
        )
        self.assertTrue(
            all(path in {"rulings", "B.md"} for path, _fd in calls["statted"])
        )
        self.assertEqual(calls["closed"], [43, 42, 41])

    def test_ruling_reader_rejects_symlinked_directory_and_file(self) -> None:
        for symlink_at, expected_open_count in (("rulings", 1), ("B.md", 2)):
            with self.subTest(symlink_at=symlink_at), ExitStack() as stack:
                calls = self._install_synthetic_ruling_syscalls(
                    stack,
                    symlink_at=symlink_at,
                )
                with self.assertRaises(preflight.ReadinessBlocked) as blocked:
                    preflight._read_ruling_source()
            self.assertEqual(
                blocked.exception.code,
                "ADJUDICATION_RULING_SOURCE_UNSAFE",
            )
            self.assertEqual(len(calls["opened"]), expected_open_count)
            expected_closed = [41] if symlink_at == "rulings" else [42, 41]
            self.assertEqual(calls["closed"], expected_closed)

    def test_pr_query_uses_supported_repo_scoped_gh_command(self) -> None:
        output = _canonical_json(
            {
                "number": 127,
                "state": "OPEN",
                "isDraft": True,
                "headRefOid": GOOD_SHA,
            }
        )
        with patch.object(preflight, "_resolve_trusted_executable", return_value="/usr/bin/gh"), patch.object(
            preflight,
            "_run_process",
            return_value=preflight._CommandResult(0, output, b""),
        ) as run:
            result = preflight._verify_pull_request_head(GOOD_SHA)
        argv = run.call_args.args[0]
        self.assertIn("--repo", argv)
        self.assertIn(preflight.GITHUB_REPOSITORY, argv)
        self.assertEqual(result["head_sha"], GOOD_SHA)
        self.assertIs(result["is_draft"], True)

    def test_baseline_is_hash_verified_and_metadata_only(self) -> None:
        baseline_raw, _metadata = preflight._read_preparation_file(
            preflight.BASELINE_PATH_RELATIVE,
            max_bytes=32 * 1024 * 1024,
            kind="PRIOR_STUDY_BASELINE",
        )
        self.assertEqual(
            hashlib.sha256(baseline_raw).hexdigest(),
            preflight.PINNED_PRIOR_STUDY_BASELINE_SHA256,
        )
        pin = preflight._load_baseline_pin()
        self.assertEqual(len(pin.evidence_sha256), 64)
        self.assertEqual(
            pin.evidence_sha256,
            preflight.PINNED_PRIOR_STUDY_BASELINE_SHA256,
        )
        self.assertEqual(len(pin.inventory_sha256), 64)
        self.assertGreater(pin.file_count, 0)
        self.assertGreaterEqual(pin.opaque_bytes_count, 0)
        self.assertTrue(all(set(row) == {"path", "size_bytes", "sha256", "scope", "opaque_bytes"} for row in pin.files))
        preflight._assert_baseline_unchanged(pin)
        baseline_after, _metadata = preflight._read_preparation_file(
            preflight.BASELINE_PATH_RELATIVE,
            max_bytes=32 * 1024 * 1024,
            kind="PRIOR_STUDY_BASELINE",
        )
        self.assertEqual(baseline_after, baseline_raw)

    def test_replaced_prior_study_baseline_is_rejected(self) -> None:
        with patch.object(
            preflight,
            "_read_preparation_file",
            return_value=(b"{}", None),
        ):
            with self.assertRaises(preflight.ReadinessBlocked) as blocked:
                preflight._load_baseline_pin()
        self.assertEqual(
            blocked.exception.code,
            "PRIOR_STUDY_BASELINE_SHA256_MISMATCH",
        )

    def test_each_gate_rechecks_old_inventory_before_next_gate(self) -> None:
        pin = preflight._BaselinePin(
            evidence_sha256="a" * 64,
            inventory_sha256="b" * 64,
            file_count=1,
            opaque_bytes_count=0,
            files=(),
        )
        with patch.object(preflight, "_assert_git_state"), patch.object(
            preflight, "_assert_fresh_run_root"
        ), patch.object(
            preflight,
            "_assert_baseline_unchanged",
            side_effect=[None, preflight.ReadinessBlocked("PRIOR_STUDY_INVENTORY_CHANGED")],
        ), patch.object(
            preflight,
            "_run_process",
            return_value=preflight._CommandResult(0, b"ok", b""),
        ) as run:
            summary = preflight._run_provider_free_preflight(GOOD_SHA, pin)
        self.assertEqual(run.call_count, 1)
        self.assertIn(
            "PRIOR_STUDY_INVENTORY_CHANGED",
            summary.infrastructure_failures,
        )
        self.assertIn("PREFLIGHT_GATE_SET_INCOMPLETE", summary.infrastructure_failures)

    def test_continuation_preflight_gates_keep_exact_head_without_fresh_root_gate(
        self,
    ) -> None:
        pin = preflight._BaselinePin(
            evidence_sha256="a" * 64,
            inventory_sha256="b" * 64,
            file_count=1,
            opaque_bytes_count=0,
            files=(),
        )
        with patch.object(preflight, "_assert_git_state") as git_state, patch.object(
            preflight, "_assert_fresh_run_root"
        ) as fresh_root, patch.object(
            preflight, "_assert_baseline_unchanged"
        ), patch.object(
            preflight,
            "_run_process",
            return_value=preflight._CommandResult(0, b"ok", b""),
        ) as run:
            summary = preflight._run_provider_free_preflight(
                GOOD_SHA,
                pin,
                require_fresh_run_root=False,
            )
        self.assertEqual(len(summary.checks), len(preflight.REQUIRED_PREFLIGHT_COMMANDS))
        self.assertEqual(summary.gate_failures, ())
        self.assertEqual(summary.infrastructure_failures, ())
        self.assertEqual(run.call_count, len(preflight.REQUIRED_PREFLIGHT_COMMANDS))
        self.assertEqual(git_state.call_count, 2 * len(preflight.REQUIRED_PREFLIGHT_COMMANDS))
        fresh_root.assert_not_called()

    def test_preflight_gate_uses_lexical_repo_venv_python(self) -> None:
        command = dict(preflight.REQUIRED_PREFLIGHT_COMMANDS)[
            "study3b-provider-free-tests"
        ]
        self.assertEqual(command[0], ".venv/bin/python")
        self.assertNotEqual(
            command[0], os.path.abspath(os.path.join(REPO_ROOT, command[0]))
        )
        self.assertIn("test_mise_en_scene_study3b_*.py", command)

    def test_ready_record_pins_ruling_protocol_config_study_and_head(self) -> None:
        ruling = _pinned_ruling_summary()
        ci_summary = preflight._validate_check_runs(
            _canonical_json(_valid_check_runs()),
            GOOD_SHA,
        )
        record = preflight._readiness_record(
            status="READY",
            expected_head_sha=GOOD_SHA,
            current_head_sha=GOOD_SHA,
            dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
            ruling_summary=ruling,
            ci_evidence_path=PREP_ROOT_RELATIVE + "/check-runs.json",
            ci_evidence_sha256=GOOD_CI_SHA256,
            ci_summary=ci_summary,
            pr_summary={"number": 127, "is_draft": True, "head_sha": GOOD_SHA},
            baseline_pin=None,
            gate_summary=None,
            reason_codes=(),
            external_provenance_verified=True,
        )
        self.assertEqual(record["run_fence"]["study_id"], protocol.STUDY_ID)
        self.assertEqual(record["run_fence"]["protocol_sha256"], protocol.PROTOCOL_SHA256)
        self.assertEqual(
            record["run_fence"]["generation_config_sha256"],
            protocol.GENERATION_CONFIG_SHA256,
        )
        self.assertEqual(record["run_fence"]["final_head_sha"], GOOD_SHA)
        self.assertEqual(record["run_fence"]["ruling_id"], preflight.DISPATCH_RULING_ID)
        self.assertEqual(record["ci_evidence"]["required_check_count"], 11)
        self.assertEqual(
            record["ci_evidence"]["source_repository"],
            preflight.GITHUB_REPOSITORY,
        )
        self.assertEqual(record["ci_evidence"]["pull_request_number"], 127)
        self.assertEqual(
            record["ci_evidence"]["source_url"],
            "https://api.github.com/repos/"
            + preflight.GITHUB_REPOSITORY
            + "/commits/"
            + GOOD_SHA
            + "/check-runs?per_page=100",
        )
        self.assertIs(record["ledger_initialized"], False)
        self.assertIs(record["credentials_loaded"], False)
        self.assertIs(record["http_dispatched"], False)

    def test_blocked_evidence_does_not_echo_untrusted_input_strings(self) -> None:
        secret_like = "OPENROUTER_API_KEY=must-not-be-persisted"
        record = preflight._readiness_record(
            status="BLOCKED",
            expected_head_sha=secret_like,
            current_head_sha=None,
            dispatch_ruling_id=secret_like,
            ruling_summary=None,
            ci_evidence_path=secret_like,
            ci_evidence_sha256=secret_like,
            ci_summary=None,
            pr_summary=None,
            baseline_pin=None,
            gate_summary=None,
            reason_codes=("EXACT_FINAL_HEAD_SHA_REQUIRED",),
            external_provenance_verified=False,
        )
        encoded = _canonical_json(record)
        self.assertNotIn(secret_like.encode("ascii"), encoded)
        self.assertIsNone(record["head_sha"])
        self.assertIsNone(record["run_fence"]["ruling_id"])
        self.assertIsNone(record["ci_evidence"]["path"])
        self.assertIsNone(record["ci_evidence"]["sha256"])
        self.assertIsNone(record["ci_evidence"]["source_url"])

    def test_dispatch_rechecks_persisted_metadata_evidence_hash_and_pins(self) -> None:
        baseline_pin = preflight._load_baseline_pin()
        ci_summary = preflight._validate_check_runs(
            _canonical_json(_valid_check_runs()),
            GOOD_SHA,
        )
        ruling_summary = _pinned_ruling_summary()
        pr_summary = {
            "number": preflight.GITHUB_PR_NUMBER,
            "state": "OPEN",
            "is_draft": True,
            "head_sha": GOOD_SHA,
            "repository": preflight.GITHUB_REPOSITORY,
        }
        checks = tuple(
            {
                "gate_id": gate_id,
                "argv": list(command),
                "exit_code": 0,
                "stdout_sha256": "f" * 64,
                "stderr_sha256": "0" * 64,
            }
            for gate_id, command in preflight.REQUIRED_PREFLIGHT_COMMANDS
        )
        gate_summary = preflight._GateSummary(
            checks=checks,
            gate_failures=(),
            infrastructure_failures=(),
            inventory_sha256=baseline_pin.inventory_sha256,
        )
        ci_path = PREP_ROOT_RELATIVE + "/check-runs-" + GOOD_SHA + ".json"
        ci_sha = hashlib.sha256(_canonical_json(_valid_check_runs())).hexdigest()
        record = preflight._readiness_record(
            status="READY",
            expected_head_sha=GOOD_SHA,
            current_head_sha=GOOD_SHA,
            dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
            ruling_summary=ruling_summary,
            ci_evidence_path=ci_path,
            ci_evidence_sha256=ci_sha,
            ci_summary=ci_summary,
            pr_summary=pr_summary,
            baseline_pin=baseline_pin,
            gate_summary=gate_summary,
            reason_codes=(),
            external_provenance_verified=True,
        )
        evidence_path, evidence_sha = preflight._write_immutable_evidence(record)
        absolute_path = REPO_ROOT / evidence_path
        self.addCleanup(lambda: absolute_path.unlink(missing_ok=True))
        verification = preflight.ReadinessVerification(
            status="READY",
            reason_codes=(),
            study_id=protocol.STUDY_ID,
            expected_head_sha=GOOD_SHA,
            current_head_sha=GOOD_SHA,
            ci_check_count=11,
            preflight_gate_count=len(preflight.REQUIRED_PREFLIGHT_COMMANDS),
            external_provenance_verified=True,
            live_dispatch_permitted=True,
            ruling_id=preflight.DISPATCH_RULING_ID,
            ruling_section_sha256=preflight.PINNED_RULING_SECTION_SHA256,
            ci_evidence_path=ci_path,
            ci_evidence_sha256=ci_sha,
            evidence_relative_path=evidence_path,
            evidence_sha256=evidence_sha,
        )
        verified_record = preflight._verify_persisted_readiness_evidence(
            verification,
            ci_summary=ci_summary,
            pr_summary=pr_summary,
            ruling_summary=ruling_summary,
            baseline_pin=baseline_pin,
        )
        self.assertEqual(verified_record["head_sha"], GOOD_SHA)
        self.assertEqual(verified_record["ci_evidence"]["required_check_count"], 11)

        absolute_path.write_bytes(absolute_path.read_bytes() + b"\n")
        with self.assertRaises(preflight.ReadinessBlocked) as blocked:
            preflight._verify_persisted_readiness_evidence(
                verification,
                ci_summary=ci_summary,
                pr_summary=pr_summary,
                ruling_summary=ruling_summary,
                baseline_pin=baseline_pin,
            )
        self.assertEqual(blocked.exception.code, "READINESS_EVIDENCE_SHA256_MISMATCH")

    def test_readiness_requires_private_proof_after_fresh_provider_free_gates(self) -> None:
        raw = _canonical_json(_valid_check_runs())
        relative_path = self._write_ci_fixture(_valid_check_runs())
        ci_sha = hashlib.sha256(raw).hexdigest()
        ruling = {
            "ruling_id": preflight.DISPATCH_RULING_ID,
            "section_sha256": preflight.PINNED_RULING_SECTION_SHA256,
            "authority": "OVERSEER_STANDING_AUTHORITY; NO_NEW_OWNER_APPROVAL_REQUESTED",
            "approved_study_id": protocol.STUDY_ID,
            "approved_protocol_sha256": protocol.PROTOCOL_SHA256,
            "approved_generation_config_sha256": protocol.GENERATION_CONFIG_SHA256,
        }
        baseline = preflight._BaselinePin(
            evidence_sha256="d" * 64,
            inventory_sha256="e" * 64,
            file_count=3,
            opaque_bytes_count=0,
            files=(),
        )
        gates = preflight._GateSummary(
            checks=tuple(
                {
                    "gate_id": gate_id,
                    "argv": list(command),
                    "exit_code": 0,
                    "stdout_sha256": "f" * 64,
                    "stderr_sha256": "0" * 64,
                }
                for gate_id, command in preflight.REQUIRED_PREFLIGHT_COMMANDS
            ),
            gate_failures=(),
            infrastructure_failures=(),
            inventory_sha256=baseline.inventory_sha256,
        )
        with patch.object(preflight, "_read_local_git_state", return_value=(GOOD_SHA, b"")), patch.object(
            preflight, "_validate_fixed_study_and_cost", return_value={}
        ), patch.object(preflight, "_assert_fresh_run_root") as fresh_root, patch.object(
            preflight, "_verify_adjudication_ruling", return_value=ruling
        ), patch.object(
            preflight, "_verify_pull_request_head", return_value={"number": 127, "is_draft": True, "head_sha": GOOD_SHA}
        ), patch.object(preflight, "_load_baseline_pin", return_value=baseline), patch.object(
            preflight, "_assert_baseline_unchanged"
        ), patch.object(preflight, "_run_provider_free_preflight", return_value=gates) as run_gates, patch.object(
            preflight, "_write_immutable_evidence", return_value=(PREP_ROOT_RELATIVE + "/readiness/test.json", "1" * 64)
        ), patch.object(
            preflight, "_verify_persisted_readiness_evidence", return_value={}
        ):
            result = preflight.verify_live_readiness(
                expected_head_sha=GOOD_SHA,
                ci_evidence_path=relative_path,
                ci_evidence_sha256=ci_sha,
                dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
            )
            continuation_result = preflight.verify_live_readiness(
                expected_head_sha=GOOD_SHA,
                ci_evidence_path=relative_path,
                ci_evidence_sha256=ci_sha,
                dispatch_ruling_id=preflight.DISPATCH_RULING_ID,
                _allow_existing_run_root=True,
            )
        self.assertTrue(preflight.is_verified_readiness(result))
        self.assertFalse(preflight.is_verified_continuation_readiness(result))
        self.assertTrue(
            preflight.is_verified_continuation_readiness(continuation_result)
        )
        self.assertEqual(run_gates.call_count, 2)
        self.assertIs(
            run_gates.call_args_list[0].kwargs["require_fresh_run_root"], True
        )
        self.assertIs(
            run_gates.call_args_list[1].kwargs["require_fresh_run_root"], False
        )
        self.assertEqual(fresh_root.call_count, 2)
        self.assertTrue(result.live_dispatch_permitted)
        self.assertEqual(result.ci_check_count, 11)
        self.assertEqual(
            result.preflight_gate_count,
            len(preflight.REQUIRED_PREFLIGHT_COMMANDS),
        )
        self.assertEqual(result.ruling_id, preflight.DISPATCH_RULING_ID)

    def test_readiness_evidence_is_exclusive_metadata_only_and_inside_prep(self) -> None:
        record = {
            "schema": "neq.llm_staging_study3b_exact_head_preflight.v1",
            "status": "BLOCKED",
            "head_sha": None,
            "reason_codes": ["CI_EVIDENCE_PATH_REQUIRED"],
        }
        collision_time = 998877665544332211
        with patch.object(preflight.time, "time_ns", return_value=collision_time):
            relative_path, digest = preflight._write_immutable_evidence(record)
            absolute_path = REPO_ROOT / relative_path
            self.addCleanup(lambda: absolute_path.unlink(missing_ok=True))
            self.assertEqual(hashlib.sha256(absolute_path.read_bytes()).hexdigest(), digest)
            self.assertEqual(absolute_path.stat().st_mode & 0o777, 0o600)
            self.assertTrue(relative_path.startswith(PREP_ROOT_RELATIVE + "/readiness/"))
            self.assertNotIn(b"OPENROUTER_API_KEY", absolute_path.read_bytes())
            with self.assertRaises(preflight.ReadinessBlocked) as blocked:
                preflight._write_immutable_evidence(record)
        self.assertEqual(blocked.exception.code, "READINESS_EVIDENCE_ALREADY_EXISTS")


if __name__ == "__main__":
    unittest.main()
