# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Synthetic-only privacy tests for the Study 3b primary diagnostic."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import builtins
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request

_SCRIPT_PATH = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(_SCRIPT_PATH)))

from scripts.mise_en_scene.llm_staging_study3b import diagnostic


_PRIVATE_MARKER = "SYNTHETIC_PRIVATE_MARKER_MUST_NOT_BE_OUTPUT"
_OTHER_MARKER = "SYNTHETIC_OTHER_GUARDED_MARKER"
_ANNOTATION_ID = "synthetic-guarded-annotation-1"
_AUTO_HASH = object()


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _request(annotations: list[dict[str, str]], *, unguarded_suffix: str = ""):
    expected_bundle = {
        "protected_unknowns": {
            "guarded_content_markers": annotations,
        }
    }
    begin, end, _rule_id = diagnostic.study3_request._SECTION_MARKERS[
        "expected_bundle"
    ]
    user_message = (
        begin
        + "\n"
        + _canonical(expected_bundle)
        + "\n"
        + end
        + unguarded_suffix
    )
    return {
        "model": "synthetic-model",
        "messages": [
            {"role": "system", "content": "SYNTHETIC SYSTEM"},
            {"role": "user", "content": user_message},
        ],
    }, expected_bundle


def _annotation(value: str) -> dict[str, str]:
    return {"annotation_id": _ANNOTATION_ID, "exact_value": value}


def _request_hash(request: dict[str, object]) -> str:
    return hashlib.sha256(
        diagnostic._transport_canonical_bytes(request)
    ).hexdigest()


@contextmanager
def _side_effect_tripwires():
    calls = {
        "file_read": 0,
        "file_write": 0,
        "network": 0,
        "credential": 0,
        "provider_import": 0,
    }

    def blocked_read(*_args: object, **_kwargs: object) -> None:
        calls["file_read"] += 1
        raise AssertionError("diagnostic tests must not read files")

    def blocked_write(*_args: object, **_kwargs: object) -> None:
        calls["file_write"] += 1
        raise AssertionError("diagnostic tests must not write files")

    def blocked_network(*_args: object, **_kwargs: object) -> None:
        calls["network"] += 1
        raise AssertionError("diagnostic tests must not use the network")

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name.split(".", 1)[0] in {"openai", "requests", "httpx", "anthropic"}:
            calls["provider_import"] += 1
            raise AssertionError("provider imports are forbidden")
        return original_import(name, *args, **kwargs)

    original_getenv = os.getenv

    def guarded_getenv(key: str, default: object = None):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden")
        return original_getenv(key, default)

    environ_type = type(os.environ)
    original_env_get = environ_type.get
    original_env_getitem = environ_type.__getitem__

    def guarded_env_get(env: object, key: object, default: object = None):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden")
        return original_env_get(env, key, default)

    def guarded_env_getitem(env: object, key: object):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden")
        return original_env_getitem(env, key)

    with ExitStack() as stack:
        stack.enter_context(patch.object(builtins, "open", side_effect=blocked_read))
        stack.enter_context(patch.object(io, "open", side_effect=blocked_read))
        stack.enter_context(patch.object(Path, "open", side_effect=blocked_read))
        stack.enter_context(patch.object(Path, "read_bytes", side_effect=blocked_read))
        stack.enter_context(patch.object(Path, "read_text", side_effect=blocked_read))
        stack.enter_context(patch.object(os, "open", side_effect=blocked_read))
        stack.enter_context(patch.object(os, "write", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "remove", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "unlink", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "rename", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "replace", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "mkdir", side_effect=blocked_write))
        stack.enter_context(patch.object(os, "rmdir", side_effect=blocked_write))
        stack.enter_context(patch.object(Path, "write_bytes", side_effect=blocked_write))
        stack.enter_context(patch.object(Path, "write_text", side_effect=blocked_write))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=blocked_network))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=blocked_network))
        stack.enter_context(
            patch.object(http.client.HTTPConnection, "request", side_effect=blocked_network)
        )
        stack.enter_context(
            patch.object(urllib.request, "urlopen", side_effect=blocked_network)
        )
        stack.enter_context(patch.object(builtins, "__import__", guarded_import))
        stack.enter_context(patch.object(os, "getenv", guarded_getenv))
        stack.enter_context(patch.object(environ_type, "get", guarded_env_get))
        stack.enter_context(
            patch.object(environ_type, "__getitem__", guarded_env_getitem)
        )
        yield calls


class Study3bPrivacyDiagnosticTests(unittest.TestCase):
    def _run_synthetic(
        self,
        *,
        request_annotations: list[dict[str, str]],
        canonical_annotations: list[dict[str, str]] | None = None,
        marker: object = _PRIVATE_MARKER,
        recorded_hash: object = _AUTO_HASH,
        unguarded_suffix: str = "",
    ):
        request, request_bundle = _request(
            request_annotations, unguarded_suffix=unguarded_suffix
        )
        canonical_rows = (
            request_annotations
            if canonical_annotations is None
            else canonical_annotations
        )
        expected_bundle = {
            "protected_unknowns": {
                "guarded_content_markers": canonical_rows,
            }
        }
        if recorded_hash is _AUTO_HASH:
            recorded_hash = _request_hash(request)
        binding = SimpleNamespace(
            expected_bundle=expected_bundle,
            guarded_markers=tuple(row["exact_value"] for row in canonical_rows),
        )
        with patch.object(
            diagnostic.study3_request, "build_request", return_value=request
        ) as request_builder:
            with patch.object(
                diagnostic.study3_contract,
                "load_scene_binding",
                return_value=binding,
            ) as binding_loader:
                report = diagnostic.run_primary_only_ha003_marker_diagnostic(
                    preserved_response_marker=marker,
                    recorded_transport_request_sha256=recorded_hash,
                )
        return report, request_builder, binding_loader, request_bundle

    def test_exact_marker_requires_hash_bound_guarded_annotation(self) -> None:
        annotations = [_annotation(_PRIVATE_MARKER)]
        output = io.StringIO()
        errors = io.StringIO()
        with _side_effect_tripwires() as calls:
            with redirect_stdout(output), redirect_stderr(errors):
                report, request_builder, binding_loader, _bundle = self._run_synthetic(
                    request_annotations=annotations
                )

        self.assertIs(report["result"], True)
        self.assertIsNone(report["ambiguity_code"])
        self.assertEqual(report["scene_id"], diagnostic.HA003_SCENE_ID)
        self.assertEqual(request_builder.call_args.args, (diagnostic.HA003_SCENE_ID,))
        self.assertEqual(binding_loader.call_args.args, (diagnostic.HA003_SCENE_ID,))
        self.assertEqual(
            report["hashes"]["canonical_guarded_annotations_sha256"],
            report["hashes"]["request_guarded_annotations_sha256"],
        )
        serialized = json.dumps(report, sort_keys=True)
        self.assertNotIn(_PRIVATE_MARKER, serialized)
        self.assertNotIn("SYNTHETIC SYSTEM", serialized)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(
            calls,
            {
                "file_read": 0,
                "file_write": 0,
                "network": 0,
                "credential": 0,
                "provider_import": 0,
            },
        )

    def test_unguarded_occurrence_does_not_count_as_guarded(self) -> None:
        report, _builder, _binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_OTHER_MARKER)],
            unguarded_suffix="\nSYNTHETIC_PRIVATE_MARKER_MUST_NOT_BE_OUTPUT",
        )

        self.assertIs(report["result"], False)
        self.assertIsNone(report["ambiguity_code"])

    def test_hash_mismatch_is_indeterminate_before_annotation_inspection(self) -> None:
        annotations = [_annotation(_PRIVATE_MARKER)]
        wrong_hash = "0" * 64
        request, _bundle = _request(annotations)
        if _request_hash(request) == wrong_hash:
            wrong_hash = "1" * 64
        with patch.object(
            diagnostic.study3_request, "build_request", return_value=request
        ) as request_builder:
            with patch.object(
                diagnostic.study3_contract, "load_scene_binding"
            ) as binding_loader:
                report = diagnostic.run_primary_only_ha003_marker_diagnostic(
                    preserved_response_marker=_PRIVATE_MARKER,
                    recorded_transport_request_sha256=wrong_hash,
                )

        self.assertIsNone(report["result"])
        self.assertEqual(
            report["ambiguity_code"], "TRANSPORT_REQUEST_HASH_MISMATCH"
        )
        self.assertEqual(request_builder.call_count, 1)
        binding_loader.assert_not_called()

    def test_duplicate_exact_guarded_annotations_are_ambiguous(self) -> None:
        duplicates = [_annotation(_PRIVATE_MARKER), _annotation(_PRIVATE_MARKER)]
        report, _builder, _binding, _bundle = self._run_synthetic(
            request_annotations=duplicates
        )

        self.assertIsNone(report["result"])
        self.assertEqual(report["ambiguity_code"], "GUARDED_MARKER_MATCH_AMBIGUOUS")

    def test_request_annotation_mismatch_is_indeterminate(self) -> None:
        report, _builder, _binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_PRIVATE_MARKER)],
            canonical_annotations=[_annotation(_OTHER_MARKER)],
        )

        self.assertIsNone(report["result"])
        self.assertEqual(
            report["ambiguity_code"], "REQUEST_GUARDED_ANNOTATIONS_MISMATCH"
        )

    def test_missing_or_malformed_inputs_are_indeterminate_and_hash_only(self) -> None:
        missing_marker, builder, binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_PRIVATE_MARKER)], marker=None
        )
        self.assertIsNone(missing_marker["result"])
        self.assertEqual(missing_marker["ambiguity_code"], "RESPONSE_MARKER_MISSING")
        self.assertEqual(builder.call_count, 0)
        self.assertEqual(binding.call_count, 0)

        missing_hash, builder, _binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_PRIVATE_MARKER)], recorded_hash=None
        )
        self.assertIsNone(missing_hash["result"])
        self.assertEqual(
            missing_hash["ambiguity_code"], "TRANSPORT_REQUEST_HASH_MISSING"
        )
        self.assertEqual(builder.call_count, 0)

        invalid_hash, builder, _binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_PRIVATE_MARKER)],
            recorded_hash="not-a-hash",
        )
        self.assertIsNone(invalid_hash["result"])
        self.assertEqual(
            invalid_hash["ambiguity_code"], "TRANSPORT_REQUEST_HASH_INVALID"
        )
        self.assertEqual(builder.call_count, 0)
        self.assertNotIn(_PRIVATE_MARKER, json.dumps(invalid_hash))

    def test_reconstruction_failure_returns_no_exception_text(self) -> None:
        with patch.object(
            diagnostic.study3_request,
            "build_request",
            side_effect=RuntimeError(_PRIVATE_MARKER),
        ):
            report = diagnostic.run_primary_only_ha003_marker_diagnostic(
                preserved_response_marker=_PRIVATE_MARKER,
                recorded_transport_request_sha256="a" * 64,
            )

        self.assertIsNone(report["result"])
        self.assertEqual(
            report["ambiguity_code"], "REQUEST_RECONSTRUCTION_UNAVAILABLE"
        )
        self.assertNotIn(_PRIVATE_MARKER, json.dumps(report))

    def test_report_contains_only_allowlisted_metadata(self) -> None:
        report, _builder, _binding, _bundle = self._run_synthetic(
            request_annotations=[_annotation(_PRIVATE_MARKER)]
        )

        self.assertEqual(set(report), {"scene_id", "result", "ambiguity_code", "hashes"})
        self.assertEqual(
            set(report["hashes"]),
            {
                "response_marker_sha256",
                "recorded_transport_request_sha256",
                "reconstructed_transport_request_sha256",
                "canonical_guarded_annotations_sha256",
                "request_guarded_annotations_sha256",
            },
        )
        for digest in report["hashes"].values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
