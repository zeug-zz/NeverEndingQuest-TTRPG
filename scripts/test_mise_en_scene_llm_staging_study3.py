# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free protocol, binding, and schema checks for Study 3."""

from __future__ import annotations

import ast
import builtins
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import hashlib
import http.client
import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from unittest.mock import patch
import urllib.request

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDY3_PACKAGE = REPO_ROOT / "scripts/mise_en_scene/llm_staging_study3"
_TEST_SUPPORT_SPEC = importlib.util.spec_from_file_location(
    "_mise_en_scene_study3_isolation_guard",
    REPO_ROOT / "scripts/mise_en_scene/llm_staging_study3/isolation_guard.py",
)
if _TEST_SUPPORT_SPEC is None or _TEST_SUPPORT_SPEC.loader is None:
    raise ImportError("Study 3 test tripwire support is unavailable")
study3_test_support = importlib.util.module_from_spec(_TEST_SUPPORT_SPEC)
_TEST_SUPPORT_SPEC.loader.exec_module(study3_test_support)
PREP_ROOT_RELATIVE = study3_test_support.PREP_ROOT_RELATIVE
REAL_LEDGER_ROOTS = study3_test_support.REAL_LEDGER_ROOTS
TripwireBlocked = study3_test_support.TripwireBlocked
install_tripwires = study3_test_support.install_tripwires
protected_real_ledger_path = study3_test_support.protected_real_ledger_path
PREP_ROOT = Path(PREP_ROOT_RELATIVE)

# Guard project import-time code as well as test bodies. The scope is deliberately
# temporary: unrelated unittest discovery runs with the original process hooks.
_IMPORT_TRIPWIRE_STACK = ExitStack()
install_tripwires(_IMPORT_TRIPWIRE_STACK, REPO_ROOT)
try:
    from scripts.mise_en_scene import coverage as coverage_module
    from scripts.mise_en_scene.llm_staging import output_gates
    from scripts.mise_en_scene.llm_staging_study2 import hydration as study2_hydration
    from scripts.mise_en_scene.llm_staging_study3 import contract as study3_contract
    from scripts.mise_en_scene.llm_staging_study3.contract import (
        ContractError,
        OUTPUT_RULE_MAP,
        RuleSpec,
        audit_rule_parity,
        load_scene_binding,
        rule_inventory,
        validate_delta_payload,
    )
    from scripts.mise_en_scene.llm_staging_study3.diagnostics import (
        DIAGNOSTIC_LABEL,
        _Collector,
        diagnose_delta_bytes,
    )
    from scripts.mise_en_scene.llm_staging_study3.protocol import (
        MODEL_ID,
        PROTOCOL_ROOT,
        SCENE_ORDER,
        STUDY_ID,
        load_input_bindings,
        render_output_schema,
        render_output_schema_json,
        render_system_prompt,
    )
    from scripts.mise_en_scene.llm_staging_study3.newrequest import (
        RequestParityError,
        audit_request_parity,
        build_request,
        request_transport_metadata,
    )
    from scripts.mise_en_scene.llm_staging_study3 import newrequest as study3_request_module
    from scripts.mise_en_scene.llm_staging_study3 import newhydration as study3_hydration
    from scripts.mise_en_scene.llm_staging_study3.newhydration import (
        hydrate_delta_output,
        validate_delta_output,
    )
    from scripts.mise_en_scene.llm_staging_study3 import sizing as study3_sizing
    from scripts.mise_en_scene.llm_staging_study3 import preflight as study3_preflight
finally:
    _IMPORT_TRIPWIRE_STACK.close()
STUDY1_PROTOCOL = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-protocol"
)
STUDY2_PROTOCOL = (
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/"
    "llm-staging-study2/protocol"
)
STUDY3_PROTOCOL = (
    "openspec/changes/v2-mise-en-scene-study3-contract-parity/protocol"
)
STUDY1_MANIFEST_SHA256 = "4cebb3f3b3a6fd45830615ff42d7fd67625ace9b8f0c4de94bff664b950d7401"
STUDY2_MANIFEST_SHA256 = "d9d81730ee32f19513ea722bcb12ed328505763ffa9deb75fc93b314337cbe4b"
STUDY2_BINDINGS_SHA256 = "0ea8961dbd9a6d9bf05bfab34d060b16de831da75c6d7208adc0379bd833581a"
RULING_PINS = (
    "neq-standing-authority-20261110",
    "neq-study3-pre-approved-20261110",
)
PREDICATES = (
    "approach_to_threshold",
    "threshold_to_focal",
    "usable_space",
    "light_gradient",
    "sound_gradient",
    "weather_gradient",
    "visible_affordance",
)


def _tripwire_patch_snapshot() -> tuple[object, ...]:
    targets: dict[tuple[int, str], object] = {}

    def capture(owner: object, attribute: str) -> None:
        if hasattr(owner, attribute):
            targets[(id(owner), attribute)] = getattr(owner, attribute)

    fixed_targets = (
        (builtins, ("open", "__import__")),
        (io, ("open", "open_code")),
        (Path, ("open",)),
        (os, ("open", "getenv", "getenvb", "chmod", "chown", "link", "makedirs", "mkdir", "mkfifo", "mknod", "remove", "rename", "replace", "rmdir", "symlink", "truncate", "unlink", "utime")),
        (importlib, ("import_module",)),
        (socket, ("create_connection", "getaddrinfo", "gethostbyaddr", "gethostbyname", "gethostbyname_ex", "getnameinfo")),
        (socket.socket, ("connect", "connect_ex", "send", "sendall", "sendto", "sendmsg")),
    )
    for owner, attributes in fixed_targets:
        for attribute in attributes:
            capture(owner, attribute)

    environment_types: set[type] = set()
    for environment in (getattr(os, "environ", None), getattr(os, "environb", None)):
        if environment is None or type(environment) in environment_types:
            continue
        environment_types.add(type(environment))
        for attribute in (
            "get",
            "__getitem__",
            "__contains__",
            "setdefault",
            "pop",
            "popitem",
            "items",
            "values",
            "copy",
            "__repr__",
        ):
            capture(type(environment), attribute)

    for module_name, class_name, attribute in study3_test_support._HTTP_TARGETS:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        owner = module if class_name is None else vars(module).get(class_name)
        if owner is not None:
            capture(owner, attribute)

    for module_name, class_name, method_names in study3_test_support._REAL_LEDGER_API_METHODS:
        module = sys.modules.get(module_name)
        ledger_class = vars(module).get(class_name) if module is not None else None
        if isinstance(ledger_class, type):
            for method_name in method_names:
                capture(ledger_class, method_name)

    for module_name, module in tuple(sys.modules.items()):
        if module is None or module_name.split(".", 1)[0] not in study3_test_support._PROVIDER_SDK_ROOTS:
            continue
        namespace = getattr(module, "__dict__", {})
        for constructor_name in study3_test_support._PROVIDER_CONSTRUCTOR_NAMES:
            constructor = namespace.get(constructor_name)
            if isinstance(constructor, type):
                capture(constructor, "__init__")

    return tuple(sorted(targets.items(), key=lambda row: (row[0][0], row[0][1]))), tuple(sys.meta_path)


def _read_json(relative_path: str) -> dict[str, object]:
    value = json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise AssertionError("expected JSON object")
    return value


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _replace_request_section(user_message: str, section: str, replacement: str) -> str:
    begin, end, _rule_id = study3_request_module._SECTION_MARKERS[section]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        raise AssertionError("request section markers are not unique")
    begin_index = user_message.index(begin)
    payload_start = begin_index + len(begin)
    if user_message[payload_start:payload_start + 1] == "\n":
        payload_start += 1
    end_index = user_message.index(end)
    payload_end = end_index
    if user_message[payload_end - 1:payload_end] == "\n":
        payload_end -= 1
    return user_message[:payload_start] + replacement + user_message[payload_end:]


@contextmanager
def _request_external_tripwires():
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("external transport/provider access is forbidden")

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name.split(".", 1)[0] in {"openai", "requests", "httpx"}:
            raise AssertionError("provider client construction is forbidden")
        return original_import(name, *args, **kwargs)

    original_getenv = os.getenv

    def guarded_getenv(key: str, default: object = None):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            raise AssertionError("credential access is forbidden")
        return original_getenv(key, default)

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", side_effect=fail))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=fail))
        stack.enter_context(patch.object(http.client.HTTPConnection, "request", side_effect=fail))
        stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=fail))
        stack.enter_context(patch.object(os, "getenv", side_effect=guarded_getenv))
        stack.enter_context(patch.object(builtins, "__import__", guarded_import))
        yield


@contextmanager
def _preflight_side_effect_tripwires():
    calls = {"filesystem_write": 0, "credential_read": 0}

    def forbidden_write(*_args: object, **_kwargs: object) -> None:
        calls["filesystem_write"] += 1
        raise AssertionError("preflight must not initialize or mutate a ledger")

    original_path_open = Path.open

    def guarded_path_open(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if any(flag in mode for flag in "wax+"):
            return forbidden_write(path, mode, *args, **kwargs)
        return original_path_open(path, mode, *args, **kwargs)

    original_os_open = os.open
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def guarded_os_open(path: object, flags: int, *args: object, **kwargs: object):
        if flags & write_flags:
            return forbidden_write(path, flags, *args, **kwargs)
        return original_os_open(path, flags, *args, **kwargs)

    environ_type = type(os.environ)
    original_env_get = environ_type.get
    original_env_getitem = environ_type.__getitem__

    def _credential_key(key: object) -> bool:
        return key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}

    def guarded_env_get(env: object, key: object, default: object = None):
        if _credential_key(key):
            calls["credential_read"] += 1
            raise AssertionError("preflight must not read credentials")
        return original_env_get(env, key, default)

    def guarded_env_getitem(env: object, key: object):
        if _credential_key(key):
            calls["credential_read"] += 1
            raise AssertionError("preflight must not read credentials")
        return original_env_getitem(env, key)

    with ExitStack() as stack:
        stack.enter_context(_request_external_tripwires())
        stack.enter_context(patch.object(Path, "open", guarded_path_open))
        stack.enter_context(patch.object(Path, "mkdir", side_effect=forbidden_write))
        stack.enter_context(patch.object(Path, "write_bytes", side_effect=forbidden_write))
        stack.enter_context(patch.object(Path, "write_text", side_effect=forbidden_write))
        stack.enter_context(patch.object(os, "open", guarded_os_open))
        stack.enter_context(patch.object(environ_type, "get", guarded_env_get))
        stack.enter_context(patch.object(environ_type, "__getitem__", guarded_env_getitem))
        yield calls


def _valid_synthetic_delta(binding: dict[str, object]) -> dict[str, object]:
    scene_id = str(binding["scene_id"])
    module_id = str(binding["module_id"])
    roles = binding["stage_role_candidates"]
    assert type(roles) is dict
    approach = roles["approach"][0]
    threshold = roles["threshold"][0]
    focal = roles["focal_anchor"][0]
    usable = roles["usable_space"][0]
    fact_prefix = module_id + ":fact:study3-authored:"
    segment_specs = (("approach", "The first bound span."), ("threshold", "The second bound span."), ("focal", "The final bound span."))
    arrival = [
        {"id": scene_id + ":arrival:" + role, "role": role, "text": text}
        for role, text in segment_specs
    ]
    claims = [
        {"segment_id": scene_id + ":arrival:" + role, "items": []}
        for role, _ in segment_specs
    ]
    return {
        "schema": "neq.llm_staging_study3_delta.v1",
        "input_refs": binding["input_refs"],
        "fixture_deltas": {
            "facts": [
                {
                    "fact_id": fact_prefix + "edge-a",
                    "subject_id": approach,
                    "predicate": "approach_to_threshold",
                    "object_id": threshold,
                    "value": True,
                },
                {
                    "fact_id": fact_prefix + "edge-b",
                    "subject_id": threshold,
                    "predicate": "threshold_to_focal",
                    "object_id": focal,
                    "value": True,
                },
            ]
        },
        "stage_role_bindings": {
            "approach": [approach],
            "threshold": [threshold],
            "focal_anchor": [focal],
            "usable_space": [usable],
        },
        "claims": claims,
        "arrival_prose": arrival,
    }


class Study3GuardedTestCase(unittest.TestCase):
    """Install suite-wide external-effect guards before every test setup."""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        subclass_setup = cls.__dict__.get("setUp")
        if subclass_setup is None:
            return

        def guarded_setup(self, *args: object, **setup_kwargs: object) -> None:
            Study3GuardedTestCase.setUp(self)
            subclass_setup(self, *args, **setup_kwargs)

        guarded_setup.__name__ = getattr(subclass_setup, "__name__", "setUp")
        guarded_setup.__doc__ = getattr(subclass_setup, "__doc__", None)
        guarded_setup._study3_tripwire_wrapper = True
        cls.setUp = guarded_setup

    def setUp(self) -> None:
        if getattr(self, "_study3_tripwire_stack", None) is not None:
            return
        stack = ExitStack()
        self._study3_tripwire_stack = stack
        self.addCleanup(stack.close)
        self._study3_tripwire_calls = install_tripwires(stack, REPO_ROOT)


class Study3ProtocolTest(Study3GuardedTestCase):
    def test_frozen_study1_and_study2_protocol_hashes(self) -> None:
        study1_manifest_path = STUDY1_PROTOCOL + "/staging-manifest.json"
        study1_manifest_bytes = (REPO_ROOT / study1_manifest_path).read_bytes()
        self.assertEqual(_sha256(study1_manifest_bytes), STUDY1_MANIFEST_SHA256)
        study1_manifest = json.loads(study1_manifest_bytes)
        for path, expected_hash in study1_manifest["artifacts"].items():
            self.assertEqual(_sha256((REPO_ROOT / path).read_bytes()), expected_hash, path)
        for path, expected_hash in study1_manifest["validator_interfaces"].items():
            self.assertEqual(_sha256((REPO_ROOT / path).read_bytes()), expected_hash, path)

        study2_manifest_path = STUDY2_PROTOCOL + "/staging-manifest.json"
        study2_manifest_bytes = (REPO_ROOT / study2_manifest_path).read_bytes()
        self.assertEqual(_sha256(study2_manifest_bytes), STUDY2_MANIFEST_SHA256)
        study2_manifest = json.loads(study2_manifest_bytes)
        self.assertEqual(tuple(study2_manifest["scene_order"]), SCENE_ORDER)
        self.assertEqual(study2_manifest["attempt_cap"], 3)
        for record in study2_manifest["artifacts"].values():
            path = record["path"]
            self.assertEqual(_sha256((REPO_ROOT / path).read_bytes()), record["sha256"], path)

    def test_study3_manifest_and_rendered_hashes(self) -> None:
        manifest = _read_json(STUDY3_PROTOCOL + "/staging-manifest.json")
        self.assertEqual(manifest["study_id"], STUDY_ID)
        self.assertEqual(manifest["status"], "CONTRACT_PREPARATION_ONLY")
        self.assertEqual(manifest["software_preparation_readiness"], "PENDING")
        self.assertIs(manifest["dispatch_authorized"], False)
        self.assertEqual(tuple(manifest["scene_order"]), SCENE_ORDER)
        references = manifest["references"]
        self.assertEqual(tuple(row["scene_id"] for row in references), SCENE_ORDER)
        for row in references:
            reference_bytes = (REPO_ROOT / row["path"]).read_bytes()
            self.assertEqual(_sha256(reference_bytes), row["sha256"])
            self.assertEqual(row["assembly"], "HAND_ASSEMBLED_FROM_BOUND_EXPECTED_INPUTS_AND_SOURCE_MATERIAL_ONLY")
            self.assertIs(row["model_generated"], False)
            self.assertIs(row["study_result"], False)
            self.assertEqual(row["human_review"], "PENDING")
            delta = json.loads(reference_bytes)
            validated = validate_delta_payload(reference_bytes, scene_id=row["scene_id"])
            self.assertEqual(validated["input_refs"], delta["input_refs"])
            binding = load_scene_binding(row["scene_id"])
            self.assertEqual(delta["input_refs"], binding.input_refs)
            self.assertEqual(row["source_packet_sha256"], binding.input_refs["source_packet"]["sha256"])
            self.assertEqual(row["expected_bundle_sha256"], binding.input_refs["expected_bundle"]["sha256"])
            self.assertEqual(row["topology_id"], binding.input_refs["topology"]["id"])
            self.assertEqual(row["topology_sha256"], binding.input_refs["topology"]["sha256"])
        self.assertEqual(manifest["attempt_cap"], 3)
        self.assertEqual(tuple(manifest["approval"]["ruling_pins"]), RULING_PINS)
        self.assertEqual(
            manifest["frozen_study_inputs"]["study1_manifest"]["sha256"],
            STUDY1_MANIFEST_SHA256,
        )
        self.assertEqual(
            manifest["frozen_study_inputs"]["study2_manifest"]["sha256"],
            STUDY2_MANIFEST_SHA256,
        )

        expected_artifact_keys = {
            "protocol",
            "input_bindings",
            "model_contract",
            "schema_template",
            "system_prompt_template",
            "task_prompt_template",
            "generation_config",
            "sizing_report",
        }
        self.assertEqual(set(manifest["artifacts"]), expected_artifact_keys)
        for record in manifest["artifacts"].values():
            path = record["path"]
            self.assertTrue(path.startswith(STUDY3_PROTOCOL + "/"))
            self.assertEqual(_sha256((REPO_ROOT / path).read_bytes()), record["sha256"], path)

        rendered = manifest["rendered_scene_artifacts"]
        self.assertEqual(tuple(row["scene_id"] for row in rendered), SCENE_ORDER)
        bindings = load_input_bindings()
        binding_by_scene = {row["scene_id"]: row for row in bindings["scenes"]}
        for row in rendered:
            scene_id = row["scene_id"]
            self.assertEqual(row["module_id"], binding_by_scene[scene_id]["module_id"])
            self.assertEqual(
                _sha256(render_system_prompt(scene_id).encode("utf-8")),
                row["system_prompt_sha256"],
            )
            self.assertEqual(
                _sha256(render_output_schema_json(scene_id).encode("utf-8")),
                row["output_schema_canonical_sha256"],
            )

    def test_bindings_match_frozen_canonical_inputs(self) -> None:
        bindings = load_input_bindings()
        self.assertEqual(tuple(row["scene_id"] for row in bindings["scenes"]), SCENE_ORDER)
        self.assertEqual(bindings["study1_manifest"]["sha256"], STUDY1_MANIFEST_SHA256)
        self.assertEqual(bindings["study2_manifest"]["sha256"], STUDY2_MANIFEST_SHA256)
        self.assertEqual(bindings["study2_input_bindings"]["sha256"], STUDY2_BINDINGS_SHA256)

        study1_manifest = _read_json(STUDY1_PROTOCOL + "/staging-manifest.json")
        study2_bindings = _read_json(STUDY2_PROTOCOL + "/input-bindings.json")
        self.assertEqual(
            _sha256((REPO_ROOT / (STUDY2_PROTOCOL + "/input-bindings.json")).read_bytes()),
            STUDY2_BINDINGS_SHA256,
        )
        self.assertEqual(tuple(row["scene_id"] for row in study2_bindings["scenes"]), SCENE_ORDER)

        for study3_row, study2_row in zip(bindings["scenes"], study2_bindings["scenes"]):
            scene_id = study3_row["scene_id"]
            scene_manifest = next(row for row in study1_manifest["scenes"] if row["scene_id"] == scene_id)
            refs = study3_row["input_refs"]
            for name in ("source_packet", "expected_bundle", "topology", "gate_canonical_context"):
                self.assertEqual(refs[name], study2_row[name])

            self.assertEqual(refs["source_packet"]["id"], scene_manifest["source_packet_path"])
            self.assertEqual(refs["source_packet"]["sha256"], scene_manifest["source_packet_sha256"])
            self.assertEqual(refs["expected_bundle"]["id"], scene_manifest["expected_inputs_path"])
            self.assertEqual(refs["expected_bundle"]["sha256"], scene_manifest["expected_inputs_sha256"])
            for ref_name in ("source_packet", "expected_bundle"):
                ref = refs[ref_name]
                self.assertEqual(_sha256((REPO_ROOT / ref["id"]).read_bytes()), ref["sha256"])

            expected = _read_json(refs["expected_bundle"]["id"])
            topology = expected["approved_topology"]
            facts = expected["source_facts"]["facts"]
            self.assertEqual(study3_row["module_id"], topology["module_id"])
            self.assertEqual(topology["scene_id"], scene_id)
            self.assertEqual(
                _sha256(_canonical_json(topology)),
                refs["topology"]["sha256"],
            )
            self.assertEqual(topology["topology_id"], refs["topology"]["id"])
            self.assertEqual(
                refs["gate_canonical_context"]["id"],
                scene_id + "#gate-canonical-context:" + topology["topology_id"],
            )
            self.assertEqual(refs["gate_canonical_context"]["sha256"], refs["topology"]["sha256"])
            self.assertEqual(study3_row["topology_node_ids"], [node["id"] for node in topology["nodes"]])
            self.assertEqual(study3_row["stage_role_candidates"], topology["stage_role_bindings"])
            base_ids = {row["fact_id"] for row in facts}
            public_ids = [
                row["fact_id"]
                for row in facts
                if row.get("audience") == "public_candidate_subject_to_semantic_review"
            ]
            self.assertEqual(study3_row["public_base_fact_ids"], public_ids)
            self.assertTrue(set(public_ids).issubset(base_ids))
            authored_prefix = study3_row["module_id"] + ":fact:study3-authored:"
            self.assertTrue(all(not fact_id.startswith(authored_prefix) for fact_id in base_ids))

    def test_scene_rendering_has_exact_namespace_and_closed_schema(self) -> None:
        bindings = load_input_bindings()
        for binding in bindings["scenes"]:
            scene_id = binding["scene_id"]
            module_id = binding["module_id"]
            system_prompt = render_system_prompt(scene_id)
            namespace = module_id + ":fact:study3-authored:<suffix>"
            expected_pattern = (
                "^"
                + re.escape(module_id)
                + r":fact:study3-authored:[A-Za-z0-9][A-Za-z0-9._-]*$"
            )
            self.assertIn(namespace, system_prompt)
            self.assertIn(expected_pattern, system_prompt)
            self.assertNotIn("{{", system_prompt)
            self.assertNotIn(":fact:study2-authored:", system_prompt)

            schema = render_output_schema(scene_id)
            Draft202012Validator.check_schema(schema)
            self.assertIs(schema["additionalProperties"], False)
            self.assertEqual(
                set(schema["properties"]),
                {"schema", "input_refs", "fixture_deltas", "stage_role_bindings", "claims", "arrival_prose"},
            )
            self.assertEqual(
                schema["$defs"]["authored_fact"]["properties"]["fact_id"]["pattern"],
                expected_pattern,
            )
            self.assertEqual(
                schema["$defs"]["authored_fact"]["properties"]["fact_id"]["maxLength"],
                256,
            )
            for definition_name in (
                "input_refs",
                "source_packet_ref",
                "expected_bundle_ref",
                "topology_ref",
                "gate_canonical_context_ref",
                "entity_ref_value",
                "fact_ref_value",
                "authored_fact",
                "fixture_deltas",
                "stage_role_bindings",
                "claim",
                "arrival_approach",
                "arrival_threshold",
                "arrival_focal",
            ):
                self.assertIs(schema["$defs"][definition_name]["additionalProperties"], False)

            synthetic = _valid_synthetic_delta(binding)
            validator = Draft202012Validator(schema)
            self.assertEqual(list(validator.iter_errors(synthetic)), [])

            invalid_true = json.loads(json.dumps(synthetic))
            invalid_true["fixture_deltas"]["facts"][0]["value"] = "true"
            self.assertNotEqual(list(validator.iter_errors(invalid_true)), [])
            wrong_namespace = json.loads(json.dumps(synthetic))
            wrong_namespace["fixture_deltas"]["facts"][0]["fact_id"] = (
                module_id + ":fact:study2-authored:edge-a"
            )
            self.assertNotEqual(list(validator.iter_errors(wrong_namespace)), [])
            unknown_key = json.loads(json.dumps(synthetic))
            unknown_key["unexpected"] = True
            self.assertNotEqual(list(validator.iter_errors(unknown_key)), [])
            stale_hash = json.loads(json.dumps(synthetic))
            stale_hash["input_refs"]["source_packet"]["sha256"] = "0" * 64
            self.assertNotEqual(list(validator.iter_errors(stale_hash)), [])
            invalid_predicate = json.loads(json.dumps(synthetic))
            invalid_predicate["fixture_deltas"]["facts"][0]["predicate"] = "distance"
            self.assertNotEqual(list(validator.iter_errors(invalid_predicate)), [])
            arbitrary_value = json.loads(json.dumps(synthetic))
            arbitrary_value["fixture_deltas"]["facts"][1]["value"] = ["not", "a", "fact value"]
            self.assertNotEqual(list(validator.iter_errors(arbitrary_value)), [])
            nested_unknown = json.loads(json.dumps(synthetic))
            nested_unknown["fixture_deltas"]["unexpected"] = True
            self.assertNotEqual(list(validator.iter_errors(nested_unknown)), [])

        task_template = (PROTOCOL_ROOT / "task-prompt.txt").read_text(encoding="utf-8")
        for placeholder in (
            "{{SCENE_ID}}",
            "{{INPUT_REFS_JSON}}",
            "{{TOPOLOGY_BINDING_JSON}}",
            "{{PUBLIC_BASE_FACT_IDS_JSON}}",
            "{{SOURCE_PACKET_JSON}}",
            "{{EXPECTED_BUNDLE_JSON}}",
            "{{MODEL_CONTRACT_JSON}}",
            "{{OUTPUT_SCHEMA_JSON}}",
        ):
            self.assertEqual(task_template.count(placeholder), 1)
        self.assertIn(STUDY_ID, task_template)

    def test_normative_model_contract_and_generation_envelope(self) -> None:
        contract = _read_json(STUDY3_PROTOCOL + "/model-contract.json")
        self.assertEqual(contract["study_id"], STUDY_ID)
        self.assertEqual(tuple(contract["scene_order"]), SCENE_ORDER)
        self.assertEqual(tuple(contract["authority"]["ruling_pins"]), RULING_PINS)
        self.assertEqual(contract["authority"]["software_preparation_readiness"], "PENDING")
        self.assertIs(contract["authority"]["dispatch_authorized"], False)
        self.assertEqual(
            contract["canonical_bindings"]["artifact_path"],
            STUDY3_PROTOCOL + "/input-bindings.json",
        )
        self.assertEqual(
            contract["canonical_bindings"]["artifact_sha256"],
            _sha256((REPO_ROOT / (STUDY3_PROTOCOL + "/input-bindings.json")).read_bytes()),
        )
        self.assertEqual(
            contract["canonical_bindings"]["stage_role_order"],
            ["approach", "threshold", "focal_anchor", "usable_space"],
        )
        self.assertEqual(
            contract["canonical_bindings"]["exact_value_json_pointers"]["reference_ids_and_hashes"],
            "/scenes/*/input_refs",
        )
        self.assertEqual(
            contract["canonical_bindings"]["exact_value_json_pointers"]["role_candidate_ids"],
            "/scenes/*/stage_role_candidates",
        )

        output = contract["output_contract"]
        self.assertEqual(output["json"]["payload_max_bytes"], 65536)
        self.assertEqual(output["root"]["only_fields"], [
            "schema", "input_refs", "fixture_deltas", "stage_role_bindings", "claims", "arrival_prose"
        ])
        self.assertEqual(output["input_refs"]["reference_names"], [
            "source_packet", "expected_bundle", "topology", "gate_canonical_context"
        ])
        self.assertEqual(output["input_refs"]["reference_id_length"], {"min": 1, "max": 512})
        self.assertEqual(output["fixture_deltas"]["facts"], {
            "min_items": 2, "max_items": 64, "authored_fact_ids_unique": True
        })
        self.assertEqual(tuple(output["authored_fact"]["predicate_enum"]), PREDICATES)
        self.assertEqual(output["authored_fact"]["fact_id_max_length"], 256)
        self.assertEqual(output["stage_role_bindings"]["role_order"], [
            "approach", "threshold", "focal_anchor", "usable_space"
        ])
        self.assertEqual(output["stage_role_bindings"]["each_role"], {
            "min_items": 1,
            "max_items": 16,
            "unique_ids": True,
            "ids": "ONLY_THE_EXACT_SCENE_ROLE_CANDIDATES",
        })
        self.assertEqual(output["claims"]["group_role_order"], ["approach", "threshold", "focal"])
        self.assertEqual(output["claims"]["exact_group_count"], 3)
        self.assertEqual(output["claims"]["max_claims_per_group"], 32)
        self.assertEqual(output["claims"]["span"], {
            "min_length": 1,
            "max_length": 512,
            "must_be_exact_substring_of_bound_segment": True,
        })
        self.assertEqual(output["claims"]["agency"]["invitation"], {
            "choice": "open", "success": "unspecified"
        })
        self.assertEqual(output["arrival_prose"]["role_order"], ["approach", "threshold", "focal"])
        self.assertEqual(output["arrival_prose"]["text_length"], {"min": 1, "max": 512})
        self.assertEqual(output["unknown_keys"], "REJECT_AT_ROOT_AND_EVERY_NESTED_OBJECT")
        self.assertEqual(len(output["stage_relations"]), 2)
        for relation in output["stage_relations"]:
            self.assertEqual(relation["required_count"], 1)
            self.assertEqual(relation["value"], {"type": "boolean", "const": True})

        envelope = contract["generation_envelope"]
        self.assertEqual(envelope["provider"], "openrouter")
        self.assertEqual(envelope["model_id"], MODEL_ID)
        self.assertIs(envelope["allow_fallbacks"], False)
        self.assertEqual(envelope["retries"], 0)
        self.assertEqual(envelope["reruns"], 0)
        self.assertEqual(envelope["tools"], [])
        self.assertIs(envelope["redirects"], False)
        self.assertIs(envelope["streaming"], False)
        self.assertIs(envelope["continuation"], False)
        self.assertEqual(envelope["max_tokens"], 16384)
        self.assertEqual(envelope["timeout_seconds"], 720)
        self.assertEqual(envelope["study_attempt_cap"], 3)
        self.assertEqual(envelope["attempts_per_scene"], 1)
        self.assertIn(STUDY_ID, envelope["cap_bound_to"])
        self.assertEqual(contract["cost"], {
            "status": "ESTIMATE",
            "expected_usd_approx": "0.01",
            "conservative_usd_approx": "0.03",
            "hard_ceiling_usd": "0.05",
            "actual_study3_cost": None,
        })

        generation_config = _read_json(STUDY3_PROTOCOL + "/generation-config.json")
        self.assertEqual(generation_config["study_id"], STUDY_ID)
        self.assertEqual(generation_config["model_id"], MODEL_ID)
        self.assertEqual(generation_config["max_tokens"], 16384)
        self.assertEqual(generation_config["timeout_seconds"], 720)
        self.assertIs(generation_config["provider_options"]["allow_fallbacks"], False)
        self.assertEqual(generation_config["transport_constraints"]["retries"], 0)
        self.assertEqual(generation_config["transport_constraints"]["reruns"], 0)
        self.assertIs(generation_config["transport_constraints"]["redirects"], False)
        self.assertIs(generation_config["transport_constraints"]["continuation"], False)
        self.assertEqual(generation_config["tools"], [])
        self.assertIs(generation_config["stream"], False)
        self.assertEqual(tuple(generation_config["approval"]["ruling_pins"]), RULING_PINS)
        self.assertIs(generation_config["dispatch_authorized"], False)


class Study3ContractTest(Study3GuardedTestCase):
    def _payload(self, scene_index: int = 0) -> tuple[str, dict[str, object]]:
        scene_id = SCENE_ORDER[scene_index]
        bindings = load_input_bindings()["scenes"]
        return scene_id, _valid_synthetic_delta(bindings[scene_index])

    def _encode(self, payload: dict[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def _assert_rejected(
        self,
        scene_id: str,
        payload: dict[str, object] | None,
        *,
        rule_id: str,
        code: str | None = None,
        raw: bytes | None = None,
    ) -> ContractError:
        with self.assertRaises(ContractError) as caught:
            validate_delta_payload(
                raw if raw is not None else self._encode(payload or {}),
                scene_id=scene_id,
            )
        error = caught.exception
        self.assertEqual(error.rule_id, rule_id)
        if code is not None:
            self.assertEqual(error.code, code)
        self.assertEqual(set(error.diagnostic), {"code", "path", "rule_id"})
        return error

    def _append_fact(
        self,
        payload: dict[str, object],
        binding: object,
        *,
        predicate: str = "visible_affordance",
        value: object = True,
    ) -> dict[str, object]:
        facts = payload["fixture_deltas"]["facts"]
        fact_id = binding.module_id + ":fact:study3-authored:mutation-" + str(len(facts))
        fact = {
            "fact_id": fact_id,
            "subject_id": binding.role_candidates["usable_space"][0],
            "predicate": predicate,
            "object_id": None,
            "value": value,
        }
        facts.append(fact)
        return fact

    def _claim(self, scene_id: str, fact_id: str, suffix: str, span: str) -> dict[str, object]:
        return {
            "id": scene_id + ":claim:" + suffix,
            "fact_id": fact_id,
            "kind": "factual",
            "span": span,
            "choice": None,
            "success": None,
        }

    def test_rule_inventory_and_parity_are_scene_bound_and_separate_host_safety(self) -> None:
        bindings = load_input_bindings()["scenes"]
        for scene_index, scene_id in enumerate(SCENE_ORDER):
            with self.subTest(scene_id=scene_id):
                self.assertEqual(audit_rule_parity(scene_id), ())
                validated = validate_delta_payload(
                    self._encode(_valid_synthetic_delta(bindings[scene_index])),
                    scene_id=scene_id,
                )
                self.assertEqual(validated["input_refs"]["scene_id"], scene_id)

        inventory = rule_inventory()
        output_rules = [row for row in inventory if row["category"] == "output_contract"]
        host_rules = [row for row in inventory if row["category"] == "host_safety_integrity"]
        self.assertEqual({row["rule_id"] for row in host_rules}, {
            "HOST-PROJECT-PATH-BOUNDARY",
            "HOST-CANONICAL-HASH-INTEGRITY",
        })
        self.assertTrue(output_rules)
        self.assertTrue(all(row["source_pointers"] for row in output_rules))
        self.assertEqual(
            {row.check_id for row in OUTPUT_RULE_MAP},
            set(study3_contract._OUTPUT_CHECKS),
        )
        # Inventory, mutations, and diagnostics are complementary coverage evidence.

    def test_bidirectional_parity_mutations_fail_independently(self) -> None:
        added_check_id = "unmapped_hidden_assertion"

        scene_id, valid_payload = self._payload()
        binding = load_scene_binding(scene_id)
        hidden_fact_id = binding.module_id + ":fact:study3-authored:hidden-restriction-probe"
        valid_payload["fixture_deltas"]["facts"][-1]["fact_id"] = hidden_fact_id
        raw = self._encode(valid_payload)
        validate_delta_payload(raw, scene_id=scene_id)

        def hidden_restriction(context: study3_contract._ValidationContext) -> None:
            assert context.payload is not None
            facts = context.payload["fixture_deltas"]["facts"]
            if facts[-1]["fact_id"].endswith(":hidden-restriction-probe"):
                fact_index = len(facts) - 1
                context.reject(
                    "UNDECLARED_FACT_SUFFIX_REJECTED",
                    "S3-HIDDEN-OUTPUT-RESTRICTION",
                    "/fixture_deltas/facts/" + str(fact_index) + "/fact_id",
                )

        checks = dict(study3_contract._OUTPUT_CHECKS)
        checks[added_check_id] = hidden_restriction
        changed_context = study3_contract._ValidationContext(raw, scene_id, binding)
        with self.assertRaises(ContractError) as hidden_rejection:
            study3_contract._run_output_checks(changed_context, checks)
        self.assertEqual(hidden_rejection.exception.rule_id, "S3-HIDDEN-OUTPUT-RESTRICTION")

        check_only_issues = audit_rule_parity(
            scene_id,
            validator_checks=checks,
        )
        self.assertIn("UNMAPPED_VALIDATOR_CHECK", {issue.code for issue in check_only_issues})

        added_rule = RuleSpec(
            "S3-HIDDEN-OUTPUT-RESTRICTION",
            added_check_id,
            "Reject a value that has no request or schema declaration.",
            (),
        )
        added_rule_issues = audit_rule_parity(
            scene_id,
            validator_rules=OUTPUT_RULE_MAP + (added_rule,),
            validator_checks=checks,
        )
        self.assertIn("UNMAPPED_VALIDATOR_RULE", {issue.code for issue in added_rule_issues})
        self.assertIn("OUTPUT_RULE_WITHOUT_SOURCE", {issue.code for issue in added_rule_issues})

        namespace_scene, namespace_payload = self._payload()
        namespace_binding = load_scene_binding(namespace_scene)
        namespace_payload["fixture_deltas"]["facts"][-1]["fact_id"] = (
            namespace_binding.module_id + ":fact:study2-authored:namespace-removal-probe"
        )
        mutated_schema = render_output_schema(namespace_scene)
        del mutated_schema["$defs"]["authored_fact"]["properties"]["fact_id"]["pattern"]
        self.assertTrue(Draft202012Validator(mutated_schema).is_valid(namespace_payload))
        self._assert_rejected(
            namespace_scene,
            namespace_payload,
            rule_id="S3-AUTHORED-ID-NAMESPACE",
            code="OUTPUT_SCHEMA_REJECTED",
        )
        namespace_issues = audit_rule_parity(
            namespace_scene,
            source_overrides={"rendered_schema": mutated_schema},
        )
        self.assertTrue(
            any(
                issue.code == "SOURCE_DECLARATION_MISSING"
                and issue.rule_id == "S3-AUTHORED-ID-NAMESPACE"
                and issue.pointer == "/$defs/authored_fact/properties/fact_id/pattern"
                for issue in namespace_issues
            )
        )

        schema = render_output_schema(scene_id)
        del schema["$defs"]["claim_group"]["properties"]["items"]["maxItems"]
        removed_declaration_issues = audit_rule_parity(
            scene_id,
            source_overrides={"rendered_schema": schema},
        )
        self.assertTrue(
            any(
                issue.code == "SOURCE_DECLARATION_MISSING"
                and issue.rule_id == "S3-CLAIM-GROUPS-ORDER-LIMIT"
                for issue in removed_declaration_issues
            )
        )

        scene_id, payload = self._payload()
        binding = load_scene_binding(scene_id)
        fact_id = payload["fixture_deltas"]["facts"][0]["fact_id"]
        span = "The first bound span."
        claims = payload["claims"]
        claims[0]["items"] = [
            self._claim(scene_id, fact_id, "limit-" + str(index), span)
            for index in range(33)
        ]
        self._assert_rejected(
            scene_id,
            payload,
            rule_id="S3-CLAIM-GROUPS-ORDER-LIMIT",
            code="OUTPUT_SCHEMA_REJECTED",
        )

    def test_parser_keys_and_json_limits(self) -> None:
        scene_id, payload = self._payload()
        root_unknown = dict(payload)
        root_unknown["unannounced"] = True
        self._assert_rejected(scene_id, root_unknown, rule_id="S3-ROOT-FIELDS")

        nested_unknown = json.loads(self._encode(payload))
        nested_unknown["fixture_deltas"]["facts"][0]["unannounced"] = True
        self._assert_rejected(scene_id, nested_unknown, rule_id="S3-FACT-FIELDS")

        self._assert_rejected(
            scene_id,
            None,
            raw=b'{"schema":"first","schema":"second"}',
            rule_id="S3-JSON-DUPLICATE-KEYS",
            code="OUTPUT_DUPLICATE_KEY",
        )
        self._assert_rejected(
            scene_id,
            None,
            raw=b'{"value":NaN}',
            rule_id="S3-JSON-NONFINITE",
            code="OUTPUT_NONFINITE_NUMBER",
        )
        self._assert_rejected(
            scene_id,
            None,
            raw=b"[]",
            rule_id="S3-JSON-OBJECT",
            code="OUTPUT_JSON_OBJECT_REQUIRED",
        )
        self._assert_rejected(
            scene_id,
            None,
            raw=b" " * 65537,
            rule_id="S3-JSON-BYTE-LIMIT",
            code="OUTPUT_BYTE_LIMIT",
        )

    def test_ids_roles_order_references_and_overwrite_attempts(self) -> None:
        scene_id, payload = self._payload()
        binding = load_scene_binding(scene_id)

        wrong_namespace = json.loads(self._encode(payload))
        wrong_namespace["fixture_deltas"]["facts"][0]["fact_id"] = "module:fact:study2-authored:x"
        self._assert_rejected(scene_id, wrong_namespace, rule_id="S3-AUTHORED-ID-NAMESPACE")

        duplicate_fact = json.loads(self._encode(payload))
        duplicate_fact["fixture_deltas"]["facts"][1]["fact_id"] = duplicate_fact["fixture_deltas"]["facts"][0]["fact_id"]
        self._assert_rejected(
            scene_id,
            duplicate_fact,
            rule_id="S3-AUTHORED-ID-LIMIT-UNIQUE",
            code="AUTHORED_FACT_ID_DUPLICATE",
        )

        overwrite = json.loads(self._encode(payload))
        overwrite["fixture_deltas"]["facts"][0]["fact_id"] = binding.public_base_fact_ids[0]
        self._assert_rejected(
            scene_id,
            overwrite,
            rule_id="S3-NO-BASE-FACT-OVERWRITE",
            code="BASE_FACT_OVERWRITE",
        )

        wrong_role = json.loads(self._encode(payload))
        wrong_role["stage_role_bindings"]["approach"][0] = binding.topology_node_ids[-1]
        self._assert_rejected(scene_id, wrong_role, rule_id="S3-STAGE-ROLE-CANDIDATES")

        duplicate_role = json.loads(self._encode(payload))
        selected = duplicate_role["stage_role_bindings"]["approach"][0]
        duplicate_role["stage_role_bindings"]["approach"] = [selected, selected]
        self._assert_rejected(scene_id, duplicate_role, rule_id="S3-STAGE-ROLE-BOUNDS-UNIQUE")

        wrong_relation = json.loads(self._encode(payload))
        wrong_relation["fixture_deltas"]["facts"][0]["subject_id"] = wrong_relation["stage_role_bindings"]["threshold"][0]
        self._assert_rejected(
            scene_id,
            wrong_relation,
            rule_id="S3-APPROACH-RELATION-TRUE",
            code="STAGE_RELATION_INVALID",
        )

        stale_hash = json.loads(self._encode(payload))
        stale_hash["input_refs"]["source_packet"]["sha256"] = "0" * 64
        self._assert_rejected(scene_id, stale_hash, rule_id="S3-EXACT-INPUT-REFERENCES")

    def test_predicates_values_and_scoped_references(self) -> None:
        scene_id, payload = self._payload()
        binding = load_scene_binding(scene_id)

        invalid_predicate = json.loads(self._encode(payload))
        invalid_predicate["fixture_deltas"]["facts"][0]["predicate"] = "distance"
        self._assert_rejected(scene_id, invalid_predicate, rule_id="S3-PREDICATE-ALLOWLIST")

        numeric_value = json.loads(self._encode(payload))
        numeric_value["fixture_deltas"]["facts"][1]["value"] = 1
        self._assert_rejected(scene_id, numeric_value, rule_id="S3-FACT-VALUE-SHAPES")

        arbitrary_value = json.loads(self._encode(payload))
        arbitrary_value["fixture_deltas"]["facts"][1]["value"] = ["not", "a", "fact value"]
        self._assert_rejected(scene_id, arbitrary_value, rule_id="S3-FACT-VALUE-SHAPES")

        bad_entity_ref = json.loads(self._encode(payload))
        self._append_fact(
            bad_entity_ref,
            binding,
            value={"kind": "entity_ref", "entity_id": "other:entity:unknown"},
        )
        self._assert_rejected(scene_id, bad_entity_ref, rule_id="S3-ENTITY-REFERENCE-SCOPE")

        bad_fact_ref = json.loads(self._encode(payload))
        self._append_fact(
            bad_fact_ref,
            binding,
            value={"kind": "fact_ref", "fact_id": binding.module_id + ":fact:study3-authored:missing"},
        )
        self._assert_rejected(
            scene_id,
            bad_fact_ref,
            rule_id="S3-FACT-REFERENCE-SCOPE",
            code="FACT_VALUE_REFERENCE_INVALID",
        )

        non_true_relation = json.loads(self._encode(payload))
        non_true_relation["fixture_deltas"]["facts"][0]["value"] = "true"
        self._assert_rejected(scene_id, non_true_relation, rule_id="S3-APPROACH-RELATION-TRUE")

    def test_claim_spans_agency_and_arrival_order(self) -> None:
        scene_id, payload = self._payload()
        fact_id = payload["fixture_deltas"]["facts"][0]["fact_id"]
        payload["arrival_prose"][0]["text"] = "A silver thread crosses the threshold."
        payload["claims"][0]["items"] = [
            self._claim(scene_id, fact_id, "one", "A silver thread")
        ]

        bad_span = json.loads(self._encode(payload))
        bad_span["claims"][0]["items"][0]["span"] = "The thread is not in this prose."
        self._assert_rejected(scene_id, bad_span, rule_id="S3-CLAIM-SPANS", code="CLAIM_SPAN_INVALID")

        bad_claim_id = json.loads(self._encode(payload))
        bad_claim_id["claims"][0]["items"][0]["id"] = "not-scene-qualified"
        self._assert_rejected(scene_id, bad_claim_id, rule_id="S3-CLAIM-ID-UNIQUE-BOUNDS")

        duplicate_claim_id = json.loads(self._encode(payload))
        duplicate_claim_id["claims"][0]["items"].append(
            dict(duplicate_claim_id["claims"][0]["items"][0])
        )
        self._assert_rejected(
            scene_id,
            duplicate_claim_id,
            rule_id="S3-CLAIM-ID-UNIQUE-BOUNDS",
            code="CLAIM_ID_DUPLICATE",
        )

        bad_claim_fact = json.loads(self._encode(payload))
        binding = load_scene_binding(scene_id)
        bad_claim_fact["claims"][0]["items"][0]["fact_id"] = (
            binding.module_id + ":fact:study3-authored:missing"
        )
        self._assert_rejected(
            scene_id,
            bad_claim_fact,
            rule_id="S3-CLAIM-FACT-REFERENCES",
            code="CLAIM_FACT_REFERENCE_INVALID",
        )

        bad_claim_order = json.loads(self._encode(payload))
        bad_claim_order["claims"][0]["segment_id"] = scene_id + ":arrival:threshold"
        self._assert_rejected(scene_id, bad_claim_order, rule_id="S3-CLAIM-SEGMENT-BINDING")

        bad_arrival_order = json.loads(self._encode(payload))
        bad_arrival_order["arrival_prose"][0]["role"] = "threshold"
        self._assert_rejected(scene_id, bad_arrival_order, rule_id="S3-ARRIVAL-ORDER-IDS-LIMITS")

        bad_agency = json.loads(self._encode(payload))
        bad_agency["claims"][0]["items"][0]["kind"] = "invitation"
        bad_agency["claims"][0]["items"][0]["choice"] = "forced"
        bad_agency["claims"][0]["items"][0]["success"] = "unspecified"
        self._assert_rejected(scene_id, bad_agency, rule_id="S3-CLAIM-AGENCY")

        prose_agency = json.loads(self._encode(payload))
        prose_agency["arrival_prose"][0]["text"] = (
            "You chose the northern archway. A silver thread crosses the threshold."
        )
        self._assert_rejected(
            scene_id,
            prose_agency,
            rule_id="S3-PROSE-AGENCY",
            code="PROSE_AGENCY_ASSERTION",
        )

    def test_aggregate_limits_and_protected_unknowns(self) -> None:
        scene_id, payload = self._payload()
        binding = load_scene_binding(scene_id)

        too_many_facts = json.loads(self._encode(payload))
        for _ in range(63):
            self._append_fact(too_many_facts, binding)
        self.assertEqual(len(too_many_facts["fixture_deltas"]["facts"]), 65)
        self._assert_rejected(scene_id, too_many_facts, rule_id="S3-FACT-COUNT-BOUNDS")

        too_long_value = json.loads(self._encode(payload))
        self._append_fact(too_long_value, binding, value="x" * 513)
        self._assert_rejected(scene_id, too_long_value, rule_id="S3-FACT-VALUE-SHAPES")

        too_long_arrival = json.loads(self._encode(payload))
        too_long_arrival["arrival_prose"][0]["text"] = "x" * 513
        self._assert_rejected(scene_id, too_long_arrival, rule_id="S3-ARRIVAL-ORDER-IDS-LIMITS")

        unknown_promotion = json.loads(self._encode(payload))
        self._append_fact(unknown_promotion, binding, predicate="light_gradient", value="a steady glow")
        self._assert_rejected(
            scene_id,
            unknown_promotion,
            rule_id="S3-PROTECTED-UNKNOWNS",
            code="PROTECTED_UNKNOWN_PROMOTION",
        )

        guarded_marker = json.loads(self._encode(payload))
        self._append_fact(guarded_marker, binding, value=binding.guarded_markers[0])
        self._assert_rejected(
            scene_id,
            guarded_marker,
            rule_id="S3-GUARDED-CONTENT-MARKERS",
            code="GUARDED_MARKER_IN_PUBLIC_DELTA",
        )

    def test_valid_delta_is_immutable_and_claim_count_is_bounded(self) -> None:
        scene_id, payload = self._payload()
        validated = validate_delta_payload(self._encode(payload), scene_id=scene_id)
        self.assertEqual(validated["schema"], "neq.llm_staging_study3_delta.v1")
        self.assertIsInstance(validated["fixture_deltas"]["facts"], tuple)
        with self.assertRaises(TypeError):
            validated["schema"] = "mutated"

        claim_limited = json.loads(self._encode(payload))
        fact_id = claim_limited["fixture_deltas"]["facts"][0]["fact_id"]
        claim_limited["claims"][0]["items"] = [
            self._claim(scene_id, fact_id, "claim-" + str(index), "The first bound span.")
            for index in range(33)
        ]
        self._assert_rejected(scene_id, claim_limited, rule_id="S3-CLAIM-GROUPS-ORDER-LIMIT")


class Study3CollectAllDiagnosticTest(Study3GuardedTestCase):
    def _case(self) -> tuple[str, dict[str, object], object]:
        scene_id = SCENE_ORDER[0]
        binding = load_scene_binding(scene_id)
        raw_binding = load_input_bindings()["scenes"][0]
        return scene_id, _valid_synthetic_delta(raw_binding), binding

    @staticmethod
    def _encode(payload: dict[str, object]) -> bytes:
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    @staticmethod
    def _coverage(report: dict[str, object], rule_id: str) -> dict[str, object]:
        coverage = report["rule_coverage"]
        assert isinstance(coverage, list)
        return next(row for row in coverage if row["rule_id"] == rule_id)

    def test_valid_hand_assembled_shape_has_no_contract_findings(self) -> None:
        manifest = _read_json(STUDY3_PROTOCOL + "/staging-manifest.json")
        for reference in manifest["references"]:
            scene_id = reference["scene_id"]
            raw = (REPO_ROOT / reference["path"]).read_bytes()
            with self.subTest(scene_id=scene_id):
                report = diagnose_delta_bytes(
                    raw,
                    scene_id=scene_id,
                    source_name=Path(reference["path"]).name,
                )
                self.assertEqual(report["label"], DIAGNOSTIC_LABEL)
                self.assertEqual(report["findings"], [])
                self.assertEqual(report["migration_differences"], [])
                self.assertEqual(report["rule_inventory_size"], 38)
                self.assertEqual(report["output_rule_count"], 36)
                self.assertEqual(report["host_rule_count"], 2)
                self.assertFalse(report["copy_path_checked"])
                self.assertEqual(self._coverage(report, "S3-CLAIM-FACT-REFERENCES")["status"], "EVALUATED")
                self.assertEqual(self._coverage(report, "HOST-PROJECT-PATH-BOUNDARY")["status"], "NOT_EVALUATED")
                self.assertFalse(report["interpretation"]["study_result"])
                self.assertEqual(report["diagnostic_integrity"]["status"], "PASS")
                self.assertEqual(report["downstream_pipeline"]["hydration"]["status"], "NOT_EVALUATED")
                self.assertEqual(
                    report["downstream_pipeline"]["full_unchanged_safety_gates"]["status"],
                    "NOT_EVALUATED",
                )

    def test_study2_schema_annotation_does_not_suppress_raw_findings(self) -> None:
        scene_id, payload, binding = self._case()
        facts = payload["fixture_deltas"]["facts"]
        first_id = "legacy.fact.one"
        second_id = "legacy.fact.two"
        facts[0]["fact_id"] = first_id
        facts[1]["fact_id"] = second_id
        facts[0]["value"] = False
        facts[1]["value"] = False
        payload["schema"] = "neq.llm_staging_study2_delta.v1"
        for index, segment in enumerate(payload["arrival_prose"]):
            segment["id"] = "legacy-arrival-" + str(index)
        payload["claims"][0]["items"] = [
            {
                "id": "legacy-claim-id",
                "fact_id": first_id,
                "kind": "factual",
                "span": "The first bound span.",
                "choice": None,
                "success": None,
            }
        ]
        for index, group in enumerate(payload["claims"]):
            group["segment_id"] = "legacy-arrival-" + str(index)

        original_bytes = self._encode(payload)
        report = diagnose_delta_bytes(original_bytes, scene_id=scene_id)
        self.assertEqual(self._encode(payload), original_bytes)
        self.assertEqual(len(report["migration_differences"]), 1)
        migration = report["migration_differences"][0]
        self.assertEqual(migration["rule_id"], "S3-ROOT-FIELDS")
        self.assertEqual(migration["path"], "/schema")
        self.assertEqual(
            migration["legacy_source_pointers"],
            ["study2_output_schema#/properties/schema/const"],
        )
        self.assertFalse(migration["finding_suppressed"])
        self.assertEqual(migration["category"], "protocol_version_or_namespace_migration")
        self.assertEqual(migration["code"], "PROTOCOL_VERSION_OR_NAMESPACE_MIGRATION")

        findings = {
            (row["rule_id"], row["code"], row["path"])
            for row in report["findings"]
        }
        expected_findings = {
            ("S3-ROOT-FIELDS", "SCHEMA_CONSTRAINT_VIOLATION", "/schema"),
            ("S3-AUTHORED-ID-NAMESPACE", "AUTHORED_FACT_ID_INVALID", "/fixture_deltas/facts/0/fact_id"),
            ("S3-AUTHORED-ID-NAMESPACE", "AUTHORED_FACT_ID_INVALID", "/fixture_deltas/facts/1/fact_id"),
            ("S3-APPROACH-RELATION-TRUE", "STAGE_RELATION_VALUE_NOT_LITERAL_TRUE", "/fixture_deltas/facts/0/value"),
            ("S3-THRESHOLD-RELATION-TRUE", "STAGE_RELATION_VALUE_NOT_LITERAL_TRUE", "/fixture_deltas/facts/1/value"),
            ("S3-ARRIVAL-ORDER-IDS-LIMITS", "ARRIVAL_ROLE_BINDING_INVALID", "/arrival_prose/0"),
            ("S3-ARRIVAL-ORDER-IDS-LIMITS", "ARRIVAL_ROLE_BINDING_INVALID", "/arrival_prose/1"),
            ("S3-ARRIVAL-ORDER-IDS-LIMITS", "ARRIVAL_ROLE_BINDING_INVALID", "/arrival_prose/2"),
            ("S3-CLAIM-ID-UNIQUE-BOUNDS", "CLAIM_ID_INVALID", "/claims/0/items/0/id"),
            ("S3-CLAIM-FACT-REFERENCES", "CLAIM_FACT_REFERENCE_INVALID", "/claims/0/items/0/fact_id"),
            ("S3-CLAIM-SEGMENT-BINDING", "CLAIM_SEGMENT_BINDING_INVALID", "/claims/0/segment_id"),
        }
        self.assertTrue(expected_findings.issubset(findings), expected_findings - findings)
        self.assertTrue(report["interpretation"]["raw_payload_evaluated_unchanged"])
        self.assertFalse(report["interpretation"]["migration_annotations_suppress_findings"])

    def test_unmapped_assertion_blocks_diagnostic_integrity_without_extending_map(self) -> None:
        collector = _Collector()
        collector.violation("S3-UNMAPPED-DIAGNOSTIC-ASSERTION", "SYNTHETIC_TEST_FAILURE")
        collector.checked("S3-UNMAPPED-CHECKED-ASSERTION")
        collector.blocked(
            "S3-UNMAPPED-BLOCKED-ASSERTION",
            "synthetic_dependency",
            "Synthetic test dependency.",
        )
        collector.migration(
            "S3-UNMAPPED-MIGRATION-ASSERTION",
            "/schema",
            legacy_sources=("study2_output_schema#/properties/schema/const",),
            reason="Synthetic test annotation.",
        )

        report = collector.report(
            scene_id=SCENE_ORDER[0],
            source_name="in-memory-delta",
            copy_path_checked=False,
        )
        integrity = report["diagnostic_integrity"]
        self.assertEqual(integrity["status"], "BLOCKED")
        failures = integrity["blocked_unmapped_rule_failures"]
        self.assertEqual(len(failures), 4)
        self.assertTrue(all(row["code"] == "UNMAPPED_RULE_ID" for row in failures))
        self.assertEqual(report["rule_inventory_size"], 38)
        self.assertEqual(report["output_rule_count"], 36)
        self.assertEqual(report["host_rule_count"], 2)
        self.assertNotIn(
            "S3-UNMAPPED-DIAGNOSTIC-ASSERTION",
            {row["rule_id"] for row in report["rule_coverage"]},
        )

    def test_independent_fact_claim_and_schema_failures_are_all_reported(self) -> None:
        scene_id, payload, binding = self._case()
        facts = payload["fixture_deltas"]["facts"]
        facts[0]["fact_id"] = "unqualified-authored-id"
        facts[0]["value"] = "not-a-boolean"
        facts[1]["value"] = False
        facts.append(
            {
                "fact_id": binding.module_id + ":fact:study3-authored:bad-predicate",
                "subject_id": binding.role_candidates["usable_space"][0],
                "predicate": "undeclared_predicate",
                "object_id": None,
                "value": [],
            }
        )
        public_fact_id = binding.public_base_fact_ids[0]
        payload["claims"][0]["items"] = [
            {
                "id": scene_id + ":claim:bad-span-and-invitation",
                "fact_id": public_fact_id,
                "kind": "invitation",
                "span": "not a bound arrival substring",
                "choice": "forced",
                "success": "unspecified",
            },
            {
                "id": scene_id + ":claim:bad-span-and-factual-agency",
                "fact_id": public_fact_id,
                "kind": "factual",
                "span": "also not a bound arrival substring",
                "choice": "open",
                "success": None,
            },
        ]
        payload["hidden prose key that must not be echoed"] = True

        report = diagnose_delta_bytes(self._encode(payload), scene_id=scene_id)
        triples = {
            (row["rule_id"], row["code"], row["path"])
            for row in report["findings"]
        }
        self.assertIn(
            ("S3-AUTHORED-ID-NAMESPACE", "AUTHORED_FACT_ID_INVALID", "/fixture_deltas/facts/0/fact_id"),
            triples,
        )
        self.assertIn(
            ("S3-APPROACH-RELATION-TRUE", "STAGE_RELATION_VALUE_NOT_LITERAL_TRUE", "/fixture_deltas/facts/0/value"),
            triples,
        )
        self.assertIn(
            ("S3-THRESHOLD-RELATION-TRUE", "STAGE_RELATION_VALUE_NOT_LITERAL_TRUE", "/fixture_deltas/facts/1/value"),
            triples,
        )
        self.assertIn(("S3-PREDICATE-ALLOWLIST", "AUTHORED_PREDICATE_INVALID", "/fixture_deltas/facts/2/predicate"), triples)
        self.assertIn(("S3-FACT-VALUE-SHAPES", "FACT_VALUE_SHAPE_INVALID", "/fixture_deltas/facts/2/value"), triples)
        self.assertIn(("S3-CLAIM-SPANS", "CLAIM_SPAN_INVALID", "/claims/0/items/0/span"), triples)
        self.assertIn(("S3-CLAIM-SPANS", "CLAIM_SPAN_INVALID", "/claims/0/items/1/span"), triples)
        self.assertIn(("S3-CLAIM-AGENCY", "INVITATION_AGENCY_INVALID", "/claims/0/items/0"), triples)
        self.assertIn(("S3-CLAIM-AGENCY", "FACTUAL_AGENCY_INVALID", "/claims/0/items/1"), triples)

        serialized_report = json.dumps(report, sort_keys=True)
        self.assertNotIn("hidden prose key that must not be echoed", serialized_report)
        self.assertTrue(all(len(row["path"]) <= 160 for row in report["findings"]))
        self.assertTrue(all(row["path"] for row in report["findings"]))
        self.assertTrue(all(row["source_pointers"] for row in report["findings"]))
        self.assertTrue(all("message" not in row for row in report["findings"]))

    def test_missing_prerequisites_are_not_evaluated_without_crashing(self) -> None:
        scene_id, payload, binding = self._case()
        payload["claims"][0]["items"] = [
            {
                "id": scene_id + ":claim:requires-facts",
                "fact_id": binding.public_base_fact_ids[0],
                "kind": "factual",
                "span": "The first bound span.",
                "choice": None,
                "success": None,
            }
        ]
        payload.pop("fixture_deltas")
        payload.pop("stage_role_bindings")

        report = diagnose_delta_bytes(self._encode(payload), scene_id=scene_id)
        fact_rule = self._coverage(report, "S3-APPROACH-RELATION-TRUE")
        claim_reference_rule = self._coverage(report, "S3-CLAIM-FACT-REFERENCES")
        self.assertEqual(fact_rule["status"], "NOT_EVALUATED")
        self.assertIn("fixture_deltas.facts[]", {row["dependency"] for row in fact_rule["blocked_dependencies"]})
        self.assertEqual(claim_reference_rule["status"], "NOT_EVALUATED")
        self.assertIn(
            "fixture_deltas.facts[]",
            {row["dependency"] for row in claim_reference_rule["blocked_dependencies"]},
        )
        self.assertEqual(report["status"], "DIAGNOSTIC_ONLY_NOT_A_STUDY_VERDICT")
        self.assertTrue(all("message" not in row for row in report["findings"]))

    def test_partially_invalid_prerequisites_are_reported_as_blocked(self) -> None:
        scene_id, payload, _binding = self._case()
        payload["stage_role_bindings"]["approach"] = [None] * 17
        payload["fixture_deltas"]["facts"][0].pop("object_id")
        payload["claims"][0]["items"] = [
            {
                "id": scene_id + ":claim:agency-blocked",
                "fact_id": payload["fixture_deltas"]["facts"][0]["fact_id"],
                "kind": "unsupported",
                "span": payload["arrival_prose"][0]["text"][:12],
                "choice": "open",
                "success": "unspecified",
            }
        ]

        report = diagnose_delta_bytes(self._encode(payload), scene_id=scene_id)
        role_coverage = self._coverage(report, "S3-STAGE-ROLE-BOUNDS-UNIQUE")
        entity_coverage = self._coverage(report, "S3-ENTITY-REFERENCE-SCOPE")
        agency_coverage = self._coverage(report, "S3-CLAIM-AGENCY")

        self.assertEqual(role_coverage["status"], "PARTIAL")
        self.assertIn("role_id.string", {row["dependency"] for row in role_coverage["blocked_dependencies"]})
        self.assertEqual(entity_coverage["status"], "PARTIAL")
        self.assertIn("fact.object_id", {row["dependency"] for row in entity_coverage["blocked_dependencies"]})
        self.assertEqual(agency_coverage["status"], "PARTIAL")
        self.assertIn("claim.kind", {row["dependency"] for row in agency_coverage["blocked_dependencies"]})

    def test_parse_failures_block_dependent_checks_but_not_host_integrity(self) -> None:
        malformed_inputs = (
            (b'{"schema":"one","schema":"two"}', "S3-JSON-DUPLICATE-KEYS"),
            (b'{"schema":', "S3-JSON-OBJECT"),
            (b" " * 65537, "S3-JSON-BYTE-LIMIT"),
        )
        for raw, expected_rule in malformed_inputs:
            with self.subTest(expected_rule=expected_rule):
                report = diagnose_delta_bytes(raw, scene_id=SCENE_ORDER[0])
                finding_rules = {row["rule_id"] for row in report["findings"]}
                self.assertIn(expected_rule, finding_rules)
                self.assertEqual(self._coverage(report, "S3-ROOT-FIELDS")["status"], "NOT_EVALUATED")
                self.assertIn(
                    "parse",
                    {
                        row["dependency"]
                        for row in self._coverage(report, "S3-ROOT-FIELDS")["blocked_dependencies"]
                    },
                )
                self.assertEqual(
                    self._coverage(report, "HOST-CANONICAL-HASH-INTEGRITY")["status"],
                    "EVALUATED",
                )


class Study3RequestBuilderTest(Study3GuardedTestCase):
    def test_exact_request_and_fake_transport_receive_builder_object(self) -> None:
        manifest = _read_json(STUDY3_PROTOCOL + "/staging-manifest.json")
        config = _read_json(STUDY3_PROTOCOL + "/generation-config.json")
        model_contract_bytes = (PROTOCOL_ROOT / "model-contract.json").read_bytes()
        rendered_by_scene = {
            row["scene_id"]: row for row in manifest["rendered_scene_artifacts"]
        }
        fake_calls: list[tuple[dict[str, object], dict[str, object], str]] = []
        built_requests: list[dict[str, object]] = []

        class FakeTransport:
            def capture(
                self,
                request: dict[str, object],
                metadata: dict[str, object],
            ) -> None:
                request_sha256 = _sha256(_canonical_json(request))
                fake_calls.append((request, metadata, request_sha256))

        fake_transport = FakeTransport()
        with _request_external_tripwires():
            for scene_id in SCENE_ORDER:
                request = build_request(scene_id)
                built_requests.append(request)
                metadata = request_transport_metadata(scene_id)

                self.assertEqual(
                    set(request),
                    {
                        "model",
                        "messages",
                        "temperature",
                        "top_p",
                        "frequency_penalty",
                        "presence_penalty",
                        "max_tokens",
                        "stream",
                        "response_format",
                        "tools",
                        "tool_choice",
                        "provider",
                    },
                )
                self.assertEqual(request["model"], "openai/gpt-6-luna")
                self.assertEqual(request["temperature"], config["temperature"])
                self.assertEqual(request["top_p"], config["top_p"])
                self.assertEqual(request["frequency_penalty"], config["frequency_penalty"])
                self.assertEqual(request["presence_penalty"], config["presence_penalty"])
                self.assertEqual(request["max_tokens"], 16384)
                self.assertIs(request["stream"], False)
                self.assertEqual(request["response_format"], {"type": "json_object"})
                self.assertEqual(request["tools"], [])
                self.assertEqual(request["tool_choice"], "none")
                self.assertEqual(request["provider"], {"allow_fallbacks": False})
                self.assertNotIn("endpoint", request)
                self.assertNotIn("timeout_seconds", request)
                self.assertNotIn("retries", request)
                self.assertNotIn("reruns", request)
                self.assertNotIn("redirects", request)
                self.assertNotIn("continuation", request)

                messages = request["messages"]
                self.assertEqual(len(messages), 2)
                system_message = messages[0]["content"]
                user_message = messages[1]["content"]
                self.assertEqual(system_message, render_system_prompt(scene_id))
                self.assertEqual(
                    _sha256(user_message.encode("utf-8")),
                    rendered_by_scene[scene_id]["user_message_sha256"],
                )
                self.assertNotRegex(user_message, r"\{\{[A-Z][A-Z0-9_]*\}\}")
                model_begin, model_end, _rule = study3_request_module._SECTION_MARKERS[
                    "model_contract"
                ]
                self.assertIn(
                    model_begin
                    + "\n"
                    + model_contract_bytes.decode("utf-8")
                    + "\n"
                    + model_end,
                    user_message,
                )
                schema_begin, schema_end, _rule = study3_request_module._SECTION_MARKERS[
                    "output_schema"
                ]
                self.assertIn(
                    schema_begin
                    + "\n"
                    + render_output_schema_json(scene_id)
                    + "\n"
                    + schema_end,
                    user_message,
                )

                self.assertEqual(metadata["provider"], "openrouter")
                self.assertEqual(
                    metadata["endpoint"],
                    "https://openrouter.ai/api/v1/chat/completions",
                )
                self.assertEqual(metadata["timeout_seconds"], 720)
                self.assertEqual(
                    metadata["transport_constraints"],
                    {"retries": 0, "reruns": 0, "redirects": False, "continuation": False},
                )
                self.assertEqual(metadata["attempt_cap_identity"], STUDY_ID)
                self.assertEqual(metadata["attempt_cap"], 3)
                self.assertEqual(metadata["attempts_per_scene"], 1)
                self.assertEqual(metadata["scene_order"], SCENE_ORDER)
                self.assertEqual(
                    metadata["generation_config_sha256"],
                    _sha256((PROTOCOL_ROOT / "generation-config.json").read_bytes()),
                )

                def fake_transport_seam(
                    actual_request: dict[str, object],
                    actual_metadata: dict[str, object],
                ) -> None:
                    audit_request_parity(scene_id, actual_request)
                    fake_transport.capture(actual_request, actual_metadata)

                fake_transport_seam(request, metadata)

        self.assertEqual(len(fake_calls), len(SCENE_ORDER))
        self.assertEqual(
            tuple(call[1]["scene_id"] for call in fake_calls),
            SCENE_ORDER,
        )
        for (request, _metadata, request_sha256), built_request in zip(
            fake_calls, built_requests
        ):
            self.assertIs(request, built_request)
            self.assertEqual(request_sha256, _sha256(_canonical_json(request)))

    def test_tampered_request_declarations_fail_before_fake_transport(self) -> None:
        scene_id = SCENE_ORDER[0]
        module_id = load_scene_binding(scene_id).module_id
        fake_calls: list[dict[str, object]] = []

        class FakeTransport:
            def capture(self, request: dict[str, object], _metadata: dict[str, object]) -> None:
                fake_calls.append(request)

        fake_transport = FakeTransport()
        metadata = request_transport_metadata(scene_id)

        def fake_transport_seam(request: dict[str, object]) -> None:
            audit_request_parity(scene_id, request)
            fake_transport.capture(request, metadata)

        mutations: list[tuple[str, str, str, object]] = []

        bad_namespace = build_request(scene_id)
        bad_namespace["messages"][0]["content"] = bad_namespace["messages"][0][
            "content"
        ].replace(
            module_id + ":fact:study3-authored:<suffix>",
            "wrong_module:fact:study3-authored:<suffix>",
            1,
        )
        mutations.append(
            ("namespace", "S3-AUTHORED-ID-NAMESPACE", "REQUEST_DECLARATION_MISSING", bad_namespace)
        )

        bad_relation = build_request(scene_id)
        bad_relation["messages"][0]["content"] = bad_relation["messages"][0][
            "content"
        ].replace("literal JSON boolean true", "truthy value", 1)
        mutations.append(
            (
                "literal-true",
                "S3-APPROACH-RELATION-TRUE",
                "REQUEST_DECLARATION_MISSING",
                bad_relation,
            )
        )

        bad_contract = build_request(scene_id)
        contract_text = study3_request_module._extract_section(
            bad_contract["messages"][1]["content"], "model_contract", "S3-AUTHORED-ID-NAMESPACE"
        )
        contract_json = json.loads(contract_text)
        del contract_json["output_contract"]["authored_fact"][
            "fact_id_namespace_template"
        ]
        bad_contract["messages"][1]["content"] = _replace_request_section(
            bad_contract["messages"][1]["content"],
            "model_contract",
            json.dumps(contract_json, ensure_ascii=False, indent=2) + "\n",
        )
        mutations.append(
            (
                "model-contract-rule-removed",
                "S3-AUTHORED-ID-NAMESPACE",
                "SOURCE_DECLARATION_MISSING",
                bad_contract,
            )
        )

        bad_schema = build_request(scene_id)
        schema_text = study3_request_module._extract_section(
            bad_schema["messages"][1]["content"], "output_schema", "S3-ROOT-FIELDS"
        )
        schema_json = json.loads(schema_text)
        del schema_json["$defs"]["authored_fact"]["properties"]["fact_id"]["pattern"]
        bad_schema["messages"][1]["content"] = _replace_request_section(
            bad_schema["messages"][1]["content"],
            "output_schema",
            _canonical_json(schema_json).decode("utf-8"),
        )
        mutations.append(
            (
                "schema-rule-removed",
                "S3-AUTHORED-ID-NAMESPACE",
                "SOURCE_DECLARATION_MISSING",
                bad_schema,
            )
        )

        for section in ("model_contract", "output_schema"):
            request = build_request(scene_id)
            user_message = request["messages"][1]["content"]
            begin, end, rule_id = study3_request_module._SECTION_MARKERS[section]
            begin_index = user_message.index(begin)
            end_index = user_message.index(end) + len(end)
            request["messages"][1]["content"] = (
                user_message[:begin_index] + user_message[end_index:]
            )
            code = (
                "REQUEST_MODEL_CONTRACT_SECTION_MISSING"
                if section == "model_contract"
                else "REQUEST_OUTPUT_SCHEMA_SECTION_MISSING"
            )
            mutations.append((section + "-section-removed", rule_id, code, request))

        for label, expected_rule, expected_code, request in mutations:
            with self.subTest(mutation=label):
                with self.assertRaises(RequestParityError) as caught:
                    fake_transport_seam(request)
                self.assertEqual(caught.exception.rule_id, expected_rule)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertEqual(fake_calls, [])


def _install_legacy_gate_spies(stack: ExitStack) -> dict[str, object]:
    targets = {
        "validate_model_output": (study2_hydration, "validate_model_output"),
        "schema_instance_validation": (output_gates, "_instance_errors"),
        "expected_input_validation": (output_gates, "_expected_parts"),
        "approved_topology_validation": (output_gates, "_approved_topology"),
        "source_provenance_binding": (output_gates, "_source_provenance"),
        "fixture_validation": (output_gates, "validate_fixture"),
        "coverage_fixture_validation": (coverage_module, "validate_fixture"),
        "positional_coverage_validation": (output_gates, "validate_positional_coverage"),
        "entity_binding_validation": (output_gates, "_check_entity_bindings"),
        "source_fact_validation": (output_gates, "_check_source_facts"),
        "protected_unknown_validation": (output_gates, "_check_protected_unknowns"),
        "arrival_validation": (output_gates, "_check_arrival"),
        "guarded_marker_validation": (output_gates, "_check_guarded_markers"),
    }
    spies: dict[str, object] = {}
    for label, (module, name) in targets.items():
        spies[label] = stack.enter_context(
            patch.object(module, name, wraps=getattr(module, name))
        )
    return spies


class Study3HydrationParityTest(Study3GuardedTestCase):
    @staticmethod
    def _reference_rows() -> list[dict[str, object]]:
        manifest = _read_json(STUDY3_PROTOCOL + "/staging-manifest.json")
        rows = manifest["references"]
        assert type(rows) is list
        return rows

    @staticmethod
    def _source_path_hashes() -> dict[str, str]:
        bindings = load_input_bindings()
        result: dict[str, str] = {}
        for row in bindings["scenes"]:
            for name in ("source_packet", "expected_bundle"):
                path = row["input_refs"][name]["id"]
                result[path] = _sha256((REPO_ROOT / path).read_bytes())
        return result

    @staticmethod
    def _assert_hydration_parity(
        scene_id: str, raw: bytes, hydrated: dict[str, object]
    ) -> None:
        delta = json.loads(raw)
        binding = load_scene_binding(scene_id)
        canonical = study2_hydration._load_canonical_inputs(scene_id)
        expected = canonical.expected_inputs_copy()
        topology = expected["approved_topology"]
        source_rows = expected["source_facts"]["facts"]

        representable_sources = {
            row["fact_id"]: row
            for row in source_rows
            if type(row.get("value")) in (str, bool, int, float)
            or row.get("value") is None
        }
        hydrated_source_facts = {
            row["id"]: row
            for row in hydrated["fixture"]["facts"]
            if row["provenance"]["class"] == "source_extracted"
        }
        assert set(hydrated_source_facts) == set(representable_sources)
        for fact_id, source in representable_sources.items():
            fact = hydrated_source_facts[fact_id]
            assert fact["status"] == "known"
            assert fact["value"] == source.get("value")
            assert fact["provenance"] == {
                "class": "source_extracted",
                "source_refs": [source["source_ref"]],
            }

        audience_knowledge = {
            row["fact_id"]: row
            for row in hydrated["fixture"]["extension_seams"]["audience_knowledge"]
        }
        assert set(audience_knowledge) == {row["fact_id"] for row in source_rows}
        for source in source_rows:
            assert audience_knowledge[source["fact_id"]] == {
                "fact_id": source["fact_id"],
                "audience": source["audience"],
                "status": source["status"],
                "source_pointer": source["source_pointer"],
                "source_ref": source["source_ref"],
                "value": source.get("value"),
            }

        assert hydrated["arrival"]["source_provenance"] == {
            "source_ref": expected["source_facts"]["source_reference"],
            "path": expected["source_facts"]["source_file"],
            "section": expected["source_facts"]["source_packet_path"]
            .rsplit("/", 1)[-1]
            .removesuffix(".json"),
            "sha256": expected["source_facts"]["source_file_sha256"],
            "source_kind": "published_module",
            "legacy_truth_verified": False,
        }
        assert hydrated["fixture"]["extension_seams"]["unknown_metrics"] == expected[
            "protected_unknowns"
        ]["unknowns"]
        assert hydrated["arrival"]["topology"] == topology
        assert hydrated["fixture"]["module_id"] == topology["module_id"]
        assert hydrated["fixture"]["topology_id"] == topology["topology_id"]

        node_kinds = {row["id"]: row["kind"] for row in topology["nodes"]}
        role_by_entity = {
            entity_id: role
            for role, entity_ids in topology["stage_role_bindings"].items()
            for entity_id in entity_ids
        }
        fixed = hydrated["fixture"]["fixed_anchors"]
        mobile = hydrated["fixture"]["initial_mobile_occupants"]
        assert [row["id"] for row in fixed] == topology["fixed_anchor_ids"]
        assert [row["kind"] for row in fixed] == [
            topology["stage_role_entity_kinds"].get(
                role_by_entity.get(entity_id), node_kinds[entity_id]
            )
            for entity_id in topology["fixed_anchor_ids"]
        ]
        assert [row["id"] for row in mobile] == topology["mobile_occupant_ids"]
        assert [row["kind"] for row in mobile] == [
            node_kinds[entity_id] for entity_id in topology["mobile_occupant_ids"]
        ]
        assert all(row["kind"] not in ("pc", "player_character") for row in mobile)

        authored_id_map = {
            row["fact_id"]: study2_hydration._legacy_authored_fact_id(
                binding.module_id, row["fact_id"]
            )
            for row in delta["fixture_deltas"]["facts"]
        }
        hydrated_authored = {
            row["id"]: row
            for row in hydrated["fixture"]["facts"]
            if row["provenance"]["class"] == "builder_authored"
        }
        assert set(hydrated_authored) == set(authored_id_map.values())
        assert len(set(authored_id_map.values())) == len(authored_id_map)
        assert set(hydrated_authored).isdisjoint(binding.base_fact_ids)
        for authored in delta["fixture_deltas"]["facts"]:
            projected_id = authored_id_map[authored["fact_id"]]
            projected = hydrated_authored[projected_id]
            assert projected["predicate"] == authored["predicate"]
            assert projected["subject_id"] == authored["subject_id"]
            assert projected["value"] == study2_hydration._legacy_scalar_value(
                authored["value"], authored_id_map
            )
            assert projected["provenance"] == {
                "class": "builder_authored",
                "source_refs": [],
            }

        hydrated_groups = {
            row["segment_id"]: row["claims"] for row in hydrated["arrival"]["claims"]
        }
        for group in delta["claims"]:
            projected_claims = hydrated_groups[group["segment_id"]]
            assert len(projected_claims) == len(group["items"])
            for authored_claim, projected_claim in zip(group["items"], projected_claims):
                assert projected_claim["fact_id"] == authored_id_map.get(
                    authored_claim["fact_id"], authored_claim["fact_id"]
                )

        assert hydrated["arrival"]["metadata"]["llm_builder_tested"] is True

    def test_three_references_run_exact_request_hydration_and_observed_full_gate_inventory(
        self,
    ) -> None:
        rows = self._reference_rows()
        self.assertEqual(tuple(row["scene_id"] for row in rows), SCENE_ORDER)
        before_source_hashes = self._source_path_hashes()
        fake_requests: list[dict[str, object]] = []
        audit_records: list[tuple[str, bool, bool]] = []

        def fake_consumer(
            request: dict[str, object], scene_id: str, hand_reference: bytes
        ) -> bytes:
            audit_request_parity(scene_id, request)
            fake_requests.append(request)
            messages = request["messages"]
            audit_records.append(
                (
                    scene_id,
                    messages[0]["content"] == render_system_prompt(scene_id),
                    render_output_schema_json(scene_id) in messages[1]["content"],
                )
            )
            return hand_reference

        observed_inventory: dict[str, dict[str, int]] = {}
        with _request_external_tripwires():
            for row in rows:
                scene_id = row["scene_id"]
                reference_bytes = (REPO_ROOT / row["path"]).read_bytes()
                self.assertEqual(_sha256(reference_bytes), row["sha256"])
                request = build_request(scene_id)
                consumed = fake_consumer(request, scene_id, reference_bytes)
                self.assertIs(fake_requests[-1], request)
                self.assertEqual(audit_records[-1], (scene_id, True, True))

                canonical = study2_hydration._load_canonical_inputs(scene_id)
                hydrated = hydrate_delta_output(consumed, scene_id=scene_id)
                self._assert_hydration_parity(scene_id, consumed, hydrated)
                self.assertEqual(
                    canonical.source_packet_bytes,
                    (REPO_ROOT / canonical.source_packet_id).read_bytes(),
                )
                self.assertEqual(
                    canonical.expected_bundle_bytes,
                    (REPO_ROOT / canonical.expected_bundle_id).read_bytes(),
                )

                with ExitStack() as stack:
                    spies = _install_legacy_gate_spies(stack)
                    report = validate_delta_output(consumed, scene_id=scene_id)
                actual_inventory = {
                    name: spy.call_count
                    for name, spy in spies.items()
                    if spy.call_count
                }
                expected_inventory = {
                    "validate_model_output",
                    "schema_instance_validation",
                    "expected_input_validation",
                    "approved_topology_validation",
                    "source_provenance_binding",
                    "fixture_validation",
                    "coverage_fixture_validation",
                    "positional_coverage_validation",
                    "entity_binding_validation",
                    "source_fact_validation",
                    "protected_unknown_validation",
                    "arrival_validation",
                    "guarded_marker_validation",
                }
                self.assertEqual(set(actual_inventory), expected_inventory)
                self.assertTrue(all(count == 1 for count in actual_inventory.values()))
                observed_inventory[scene_id] = actual_inventory

                self.assertEqual(report.contract_status, "PASS")
                self.assertEqual(report.hydration_status, "PASS")
                self.assertEqual(report.downstream_status, "PASS")
                self.assertEqual(report.deterministic_status, "PASS")
                self.assertEqual(report.delta_artifact_sha256, _sha256(consumed))
                self.assertEqual(
                    report.hydrated_output_sha256,
                    _sha256(_canonical_json(hydrated)),
                )
                self.assertEqual(report.contract_diagnostics, ())
                self.assertEqual(report.downstream_diagnostics, ())
                self.assertEqual(report.not_evaluated, ())
                self.assertIs(report.legacy_llm_builder_tested_metadata, True)
                serialized_report = report.to_dict()
                self.assertEqual(
                    serialized_report["reference_evidence"]["classification"],
                    "HAND_ASSEMBLED_DETERMINISTIC_SOFTWARE_FIXTURE_ONLY",
                )
                self.assertEqual(
                    serialized_report["reference_evidence"]["model_capability_verdict"],
                    "PENDING",
                )
                self.assertEqual(
                    serialized_report["reference_evidence"]["semantic_review_status"],
                    "PENDING",
                )
                self.assertEqual(
                    serialized_report["reference_evidence"]["owner_rating_status"],
                    "PENDING",
                )
                self.assertIn(
                    "NOT_MODEL_TEST_EVIDENCE",
                    serialized_report["reference_evidence"]["legacy_metadata_interpretation"],
                )

        self.assertEqual(len(fake_requests), 3)
        self.assertEqual(tuple(item[0] for item in audit_records), SCENE_ORDER)
        self.assertEqual(set(observed_inventory), set(SCENE_ORDER))
        self.assertEqual(self._source_path_hashes(), before_source_hashes)

    def test_hydrated_reference_mutations_reach_their_real_legacy_gate(self) -> None:
        row = self._reference_rows()[0]
        scene_id = row["scene_id"]
        raw = (REPO_ROOT / row["path"]).read_bytes()
        canonical = study2_hydration._load_canonical_inputs(scene_id)
        baseline = hydrate_delta_output(raw, scene_id=scene_id)
        expected_inputs = canonical.expected_inputs_copy()
        mutations: list[tuple[str, object, tuple[str, str, str], str]] = []

        def bad_schema(value: dict[str, object]) -> None:
            value["unexpected_study3_gate_probe"] = True

        mutations.append(
            (
                "schema",
                bad_schema,
                ("OUTPUT_SCHEMA", "schema", "$.*"),
                "schema_instance_validation",
            )
        )

        def bad_fixture(value: dict[str, object]) -> None:
            fixture = value["fixture"]
            fixture["topology_id"] = fixture["module_id"] + ":topology:study3-probe"

        mutations.append(
            (
                "fixture",
                bad_fixture,
                ("TOPOLOGY_ID_MISMATCH", "schema", "$.topology_id"),
                "fixture_validation",
            )
        )

        def bad_source_provenance(value: dict[str, object]) -> None:
            value["arrival"]["source_provenance"]["sha256"] = "0" * 64

        mutations.append(
            (
                "provenance",
                bad_source_provenance,
                ("SOURCE_PROVENANCE_MISMATCH", "provenance", "$.arrival.source_provenance"),
                "source_provenance_binding",
            )
        )

        def bad_topology(value: dict[str, object]) -> None:
            topology = deepcopy(value["arrival"]["topology"])
            topology["topology_id"] = topology["topology_id"] + "-study3-probe"
            value["arrival"]["topology"] = topology

        mutations.append(
            (
                "topology",
                bad_topology,
                ("APPROVED_TOPOLOGY_CHANGED", "topology", "$.arrival.topology"),
                "approved_topology_validation",
            )
        )

        def bad_topology_identity(value: dict[str, object]) -> None:
            fixed = value["fixture"]["fixed_anchors"]
            fixed[0]["id"] = fixed[0]["id"] + "-study3-probe"

        mutations.append(
            (
                "topology-identity",
                bad_topology_identity,
                ("FIXED_ANCHOR_SET_MISMATCH", "identity", "$.fixture.fixed_anchors"),
                "entity_binding_validation",
            )
        )

        def bad_coverage(value: dict[str, object]) -> None:
            facts = value["fixture"]["facts"]
            relation = next(
                fact for fact in facts if fact.get("predicate") == "approach_to_threshold"
            )
            facts.remove(relation)

        mutations.append(
            (
                "positional-coverage",
                bad_coverage,
                ("MISSING_RELATION", "relationship_coverage", "$.facts"),
                "positional_coverage_validation",
            )
        )

        def bad_protected_unknowns(value: dict[str, object]) -> None:
            value["fixture"]["extension_seams"]["unknown_metrics"] = []

        mutations.append(
            (
                "protected-unknowns",
                bad_protected_unknowns,
                (
                    "PROTECTED_UNKNOWNS_CHANGED",
                    "unknowns",
                    "$.fixture.extension_seams.unknown_metrics",
                ),
                "protected_unknown_validation",
            )
        )

        source_facts = expected_inputs["source_facts"]["facts"]
        source_value_by_id = {fact["fact_id"]: fact.get("value") for fact in source_facts}

        def bad_source_knowledge(value: dict[str, object]) -> None:
            facts = value["fixture"]["facts"]
            index = next(
                index
                for index, fact in enumerate(facts)
                if fact["provenance"]["class"] == "source_extracted"
            )
            fact = facts[index]
            original = source_value_by_id[fact["id"]]
            if type(original) is bool:
                fact["value"] = not original
            elif type(original) is str:
                fact["value"] = original + "x"
            elif type(original) in (int, float):
                fact["value"] = original + 1
            else:
                fact["value"] = "study3-source-probe"

        source_fact_index = next(
            index
            for index, fact in enumerate(baseline["fixture"]["facts"])
            if fact["provenance"]["class"] == "source_extracted"
        )
        mutations.append(
            (
                "source-knowledge",
                bad_source_knowledge,
                (
                    "SOURCE_FACT_VALUE_MISMATCH",
                    "provenance",
                    "$.fixture.facts[%d]" % source_fact_index,
                ),
                "source_fact_validation",
            )
        )

        def bad_agency(value: dict[str, object]) -> None:
            arrival = value["arrival"]
            claim = arrival["claims"][0]["claims"][0]
            claim["kind"] = "invitation"
            claim["choice"] = "forced"
            claim["success"] = "unspecified"

        mutations.append(
            (
                "agency",
                bad_agency,
                (
                    "AGENCY_PRESCRIBED",
                    "agency",
                    "$.arrival.claims[0].claims[0]",
                ),
                "arrival_validation",
            )
        )

        guarded_markers = expected_inputs["source_facts"]["guarded_content_markers"]
        marker = next(
            item["exact_value"]
            for item in guarded_markers
            if type(item.get("exact_value")) is str and item["exact_value"]
        )

        def bad_guarded_marker(value: dict[str, object]) -> None:
            value["arrival"]["arrival_segments"][0]["text"] += " " + marker

        mutations.append(
            (
                "guarded-markers",
                bad_guarded_marker,
                ("GUARDED_CONTENT_LEAK", "knowledge", "$.arrival"),
                "guarded_marker_validation",
            )
        )

        self.assertEqual(len(mutations), 10)
        for label, mutate, expected_diagnostic, invoked_spy in mutations:
            with self.subTest(gate=label), _request_external_tripwires():
                candidate = deepcopy(baseline)
                mutate(candidate)
                with ExitStack() as stack:
                    spies = _install_legacy_gate_spies(stack)
                    evaluated = study3_hydration._validate_hydrated_output(
                        candidate, canonical, scene_id
                    )
                self.assertEqual(evaluated.status, "FAIL")
                self.assertIn(
                    expected_diagnostic,
                    {
                        (item.code, item.layer, item.path)
                        for item in evaluated.diagnostics
                    },
                )
                self.assertEqual(spies["validate_model_output"].call_count, 1)
                self.assertGreater(spies[invoked_spy].call_count, 0)

                if label == "schema":
                    downstream_spies = (
                        "approved_topology_validation",
                        "source_provenance_binding",
                        "fixture_validation",
                        "coverage_fixture_validation",
                        "positional_coverage_validation",
                        "entity_binding_validation",
                        "source_fact_validation",
                        "protected_unknown_validation",
                        "arrival_validation",
                        "guarded_marker_validation",
                    )
                    not_evaluated = {
                        name for name in downstream_spies if spies[name].call_count == 0
                    }
                    self.assertEqual(set(downstream_spies), not_evaluated)
                    gate_statuses = {name: "NOT_EVALUATED" for name in not_evaluated}
                    self.assertTrue(
                        all(status == "NOT_EVALUATED" for status in gate_statuses.values())
                    )

    def test_contract_and_missing_canonical_dependencies_are_not_false_passes(self) -> None:
        row = self._reference_rows()[0]
        scene_id = row["scene_id"]
        raw = (REPO_ROOT / row["path"]).read_bytes()
        invalid_delta = json.loads(raw)
        invalid_delta["undisclosed_root_field"] = True
        invalid_raw = _canonical_json(invalid_delta)

        with _request_external_tripwires(), patch.object(
            study2_hydration,
            "validate_model_output",
            wraps=study2_hydration.validate_model_output,
        ) as full_gate:
            contract_report = validate_delta_output(invalid_raw, scene_id=scene_id)
            self.assertEqual(full_gate.call_count, 0)
        self.assertEqual(contract_report.contract_status, "FAIL")
        self.assertEqual(contract_report.hydration_status, "NOT_EVALUATED")
        self.assertEqual(contract_report.downstream_status, "NOT_EVALUATED")
        self.assertEqual(
            {item.dependency for item in contract_report.not_evaluated},
            {"study3_contract"},
        )
        self.assertEqual(contract_report.hydrated_output_sha256, None)

        with _request_external_tripwires(), patch.object(
            study2_hydration,
            "_load_canonical_inputs",
            side_effect=study2_hydration.ContractError(
                "STUDY1_EXPECTED_INPUTS_INVALID"
            ),
        ), patch.object(
            study2_hydration,
            "validate_model_output",
            wraps=study2_hydration.validate_model_output,
        ) as full_gate:
            canonical_report = validate_delta_output(raw, scene_id=scene_id)
            self.assertEqual(full_gate.call_count, 0)
        self.assertEqual(canonical_report.contract_status, "PASS")
        self.assertEqual(canonical_report.hydration_status, "NOT_EVALUATED")
        self.assertEqual(canonical_report.downstream_status, "NOT_EVALUATED")
        self.assertEqual(
            [item.dependency for item in canonical_report.not_evaluated],
            ["study1_canonical_inputs", "in_memory_hydration"],
        )
        self.assertTrue(
            all(item.reason_code == "STUDY1_EXPECTED_INPUTS_INVALID" for item in canonical_report.not_evaluated)
        )
        self.assertIsNone(canonical_report.hydrated_output_sha256)


class Study3SizingTest(Study3GuardedTestCase):
    def test_report_is_hash_bound_per_scene_and_provider_free(self) -> None:
        with _request_external_tripwires():
            report = study3_sizing.build_sizing_report()
        stored = _read_json(STUDY3_PROTOCOL + "/sizing-report.json")
        self.assertEqual(report, stored)
        self.assertEqual(tuple(row["scene_id"] for row in report["scenes"]), SCENE_ORDER)
        self.assertEqual(report["rates"]["source_sha256"], study3_sizing.RATE_LISTING_SHA256)
        self.assertEqual(report["rates"]["prompt_usd_per_token_historical"], "0.0000001")
        self.assertEqual(report["rates"]["completion_usd_per_token_historical"], "0.0000005")
        self.assertEqual(
            report["expected_completion_usage_provenance"]["source_path"],
            study3_sizing.STUDY2_USAGE_SOURCE_PATH,
        )
        self.assertEqual(
            report["expected_completion_usage_provenance"]["source_sha256"],
            study3_sizing.STUDY2_USAGE_SOURCE_SHA256,
        )
        self.assertEqual(
            report["expected_completion_usage_provenance"]["classification"],
            "FROZEN_STUDY2_RECORDED_OBSERVATIONS_NOT_LIVE_UNIT_RATES",
        )
        self.assertEqual(report["actual_study3_spend_usd"], "0")
        self.assertIsNone(report["actual_study3_cost_usd"])
        self.assertEqual(report["expected_total_usd_estimate"], "0.0125671")
        self.assertEqual(report["conservative_total_usd_estimate"], "0.0324461")
        self.assertLess(Decimal(report["conservative_total_usd_estimate"]), Decimal("0.05"))
        self.assertEqual(report["generation_envelope"], {
            "attempt_cap": 3,
            "max_tokens_per_attempt": 16384,
            "timeout_seconds": 720,
        })
        for row in report["scenes"]:
            self.assertEqual(len(row["request_sha256"]), 64)
            self.assertEqual(len(row["reference_sha256"]), 64)
            self.assertGreater(row["canonical_request_wire_utf8_bytes"], row["request_message_utf8_bytes"])

    def test_missing_stale_and_invalid_rates_fail_closed(self) -> None:
        with patch.object(study3_sizing, "_safe_local_read", side_effect=study3_sizing.SizingBlocked("missing")):
            with self.assertRaisesRegex(study3_sizing.SizingBlocked, "missing"):
                study3_sizing.build_sizing_report()
        with patch.object(study3_sizing, "_safe_local_read", return_value=b"stale"):
            with self.assertRaisesRegex(study3_sizing.SizingBlocked, "size mismatch"):
                study3_sizing.build_sizing_report()
        with self.assertRaisesRegex(study3_sizing.SizingBlocked, "size mismatch"):
            study3_sizing._parse_rate_listing(b"x" * (study3_sizing.RATE_LISTING_BYTES - 1))
        for rates in (
            {"prompt": 0.0000001, "completion": "0.0000005"},
            {"prompt": "NaN", "completion": "0.0000005"},
            {"prompt": "-0.1", "completion": "0.0000005"},
        ):
            payload = json.dumps({"data": [{"id": MODEL_ID, "pricing": rates}]}).encode()
            with self.assertRaises(study3_sizing.SizingBlocked):
                study3_sizing._parse_rate_listing(payload)

    def test_future_preflight_is_strict_and_recomputes_report(self) -> None:
        valid = study3_sizing.build_sizing_report()
        with _request_external_tripwires():
            self.assertEqual(study3_sizing.future_host_preflight(valid), Decimal("0.0324461"))
        for bad_value in ("0.05", "0.050001", "NaN", True):
            bad = deepcopy(valid)
            bad["conservative_total_usd_estimate"] = bad_value
            with patch.object(study3_sizing, "build_sizing_report", return_value=bad):
                with self.assertRaises(study3_sizing.SizingBlocked):
                    study3_sizing.future_host_preflight(bad)
        missing = deepcopy(valid)
        missing["scenes"].pop()
        with self.assertRaisesRegex(study3_sizing.SizingBlocked, "mismatched"):
            study3_sizing.future_host_preflight(missing)

    def test_actual_cost_accounting_stops_on_missing_pending_or_mismatch(self) -> None:
        receipts = [
            {
                "receipt_id": f"r{i}",
                "cost_usd": "0.01",
                "prompt_tokens": 100,
                "completion_tokens": 30,
                "reasoning_tokens": 10,
            }
            for i in range(1, 4)
        ]
        valid = {"status": "COMPLETE", "receipts": receipts, "reported_total_usd": "0.03"}
        self.assertEqual(study3_sizing.validate_actual_cost_accounting(receipts, valid), Decimal("0.03"))
        wrong_cost = deepcopy(receipts)
        wrong_cost[0]["cost_usd"] = "0.02"
        wrong_cost_actual = deepcopy(wrong_cost)
        wrong_cost_actual[0]["cost_usd"] = "0.01"
        wrong_cost_actual[1]["cost_usd"] = "0.02"
        wrong_cost_actual[2]["cost_usd"] = "0.01"
        wrong_cost_envelope = {"status": "COMPLETE", "receipts": wrong_cost_actual, "reported_total_usd": "0.04"}
        with self.assertRaisesRegex(study3_sizing.SizingBlocked, "cost or usage mismatch"):
            study3_sizing.validate_actual_cost_accounting(wrong_cost, wrong_cost_envelope)
        wrong_usage = deepcopy(receipts)
        wrong_usage[0]["completion_tokens"] += 1
        with self.assertRaisesRegex(study3_sizing.SizingBlocked, "cost or usage mismatch"):
            study3_sizing.validate_actual_cost_accounting(
                receipts,
                {"status": "COMPLETE", "receipts": wrong_usage, "reported_total_usd": "0.03"},
            )
        for malformed in (
            [{"receipt_id": "same", "cost_usd": "0.01"}] * 3,
            [{"receipt_id": True, "cost_usd": "0.01"}, *receipts[1:]],
            [{"receipt_id": "r1", "cost_usd": True}, *receipts[1:]],
        ):
            with self.assertRaises(study3_sizing.SizingBlocked):
                study3_sizing.validate_actual_cost_accounting(
                    malformed, {"status": "COMPLETE", "receipts": malformed, "reported_total_usd": "0.03"}
                )
        expensive = [dict(row, cost_usd="0.02") for row in receipts]
        with self.assertRaisesRegex(study3_sizing.SizingBlocked, "hard ceiling"):
            study3_sizing.validate_actual_cost_accounting(
                expensive,
                {"status": "COMPLETE", "receipts": deepcopy(expensive), "reported_total_usd": "0.06"},
            )
        for bad in (
            None,
            {"status": "PENDING", "receipts": receipts, "reported_total_usd": "0.03"},
            {"status": "COMPLETE", "receipts": receipts[:2], "reported_total_usd": "0.02"},
            {"status": "COMPLETE", "receipts": receipts, "reported_total_usd": "0.04"},
            {"status": "COMPLETE", "receipts": receipts, "reported_total_usd": "NaN"},
            {"status": "COMPLETE", "receipts": receipts, "reported_total_usd": True},
            {"status": "COMPLETE", "receipts": receipts[:2] + [dict(receipts[2], receipt_id="other")], "reported_total_usd": "0.03"},
            {"status": "COMPLETE", "receipts": receipts[:2] + [dict(receipts[2], reasoning_tokens=31)], "reported_total_usd": "0.03"},
        ):
            with self.assertRaises(study3_sizing.SizingBlocked):
                study3_sizing.validate_actual_cost_accounting(receipts, bad)

    def test_incremental_actual_accounting_validates_zero_through_three_rows(self) -> None:
        for count in range(4):
            receipts = [
                {
                    "receipt_id": f"synthetic-gen-{index}",
                    "cost_usd": "0.01",
                    "prompt_tokens": 100,
                    "completion_tokens": 30,
                    "reasoning_tokens": 10,
                }
                for index in range(1, count + 1)
            ]
            if count == 0:
                actual = {
                    "status": "NOT_APPLICABLE_NO_STUDY3_ATTEMPTS",
                    "receipts": [],
                    "reported_total_usd": "0",
                }
                expected_total = Decimal("0")
            else:
                actual = {
                    "status": "COMPLETE",
                    "receipts": deepcopy(receipts),
                    "reported_total_usd": f"0.{count:02d}",
                }
                expected_total = Decimal(f"0.{count:02d}")
            with self.subTest(completed_receipts=count):
                self.assertEqual(
                    study3_sizing.validate_actual_cost_accounting(receipts, actual),
                    expected_total,
                )
        with self.assertRaises(study3_sizing.SizingBlocked):
            study3_sizing.validate_actual_cost_accounting(
                [], {"status": "PENDING", "receipts": [], "reported_total_usd": "0"}
            )


class Study3SyntheticPreflightTest(Study3GuardedTestCase):
    def setUp(self) -> None:
        self.fixture = self._make_fixture()

    def _make_fixture(self) -> dict[str, object]:
        manifest_bytes = (REPO_ROOT / STUDY3_PROTOCOL / "staging-manifest.json").read_bytes()
        config_sha256 = request_transport_metadata(SCENE_ORDER[0])["generation_config_sha256"]
        standing_source = (
            b"SYNTHETIC RULING neq-standing-authority-20261110 "
            b"authorizes Overseer routine cap approval for the owner."
        )
        cap_source = (
            b"SYNTHETIC RULING neq-study3-pre-approved-20261110 "
            b"under neq-standing-authority-20261110 approves the fixed Study 3 cap."
        )
        standing_sha256 = _sha256(standing_source)
        cap_sha256 = _sha256(cap_source)
        envelope = {
            "schema": "neq.llm_staging_study3_cap_approval_binding.v1",
            "standing_authority_ruling_id": "neq-standing-authority-20261110",
            "standing_authority_source_sha256": standing_sha256,
            "cap_approval_ruling_id": "neq-study3-pre-approved-20261110",
            "cap_approval_source_sha256": cap_sha256,
            "study_id": STUDY_ID,
            "manifest_sha256": study3_preflight.protocol.STUDY3_MANIFEST_SHA256,
            "generation_config_sha256": config_sha256,
            "approved_by_role": "overseer",
            "acting_for": "owner",
            "attempt_cap": 3,
            "attempts_per_scene": 1,
            "scene_order": list(SCENE_ORDER),
            "provider": "openrouter",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "model_id": "openai/gpt-6-luna",
            "allow_fallbacks": False,
            "retries": 0,
            "reruns": 0,
            "tools": [],
            "redirects": False,
            "streaming": False,
            "continuation": False,
            "temperature": 1.0,
            "top_p": 1.0,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "max_tokens": 16384,
            "response_format": {"type": "json_object"},
            "timeout_seconds": 720,
            "tool_choice": "none",
            "expected_cost_usd_approx": "0.01",
            "conservative_cost_usd_approx": "0.03",
            "hard_ceiling_usd": "0.05",
            "approval_kind": "CAP_ONLY_NOT_READINESS_OR_DISPATCH",
        }
        envelope_bytes = _canonical_json(envelope)
        approval_pins = study3_preflight.ApprovalPins(
            study_id=STUDY_ID,
            manifest_sha256=study3_preflight.protocol.STUDY3_MANIFEST_SHA256,
            generation_config_sha256=config_sha256,
            standing_authority_ruling_id="neq-standing-authority-20261110",
            standing_authority_sha256=standing_sha256,
            cap_approval_ruling_id="neq-study3-pre-approved-20261110",
            cap_approval_sha256=cap_sha256,
            cap_envelope_sha256=_sha256(envelope_bytes),
        )
        readiness_id = "synthetic-study3-overseer-ready-v1"
        readiness = {
            "schema": "neq.llm_staging_study3_synthetic_software_readiness.v1",
            "ruling_id": readiness_id,
            "study_id": STUDY_ID,
            "manifest_sha256": approval_pins.manifest_sha256,
            "generation_config_sha256": config_sha256,
            "cap_approval_ruling_id": approval_pins.cap_approval_ruling_id,
            "cap_approval_sha256": approval_pins.cap_approval_sha256,
            "reviewed_by_role": "overseer",
            "software_preparation_review": "APPROVED",
            "software_preparation_readiness": "READY",
        }
        readiness_bytes = _canonical_json(readiness)
        dispatch_id = "synthetic-study3-overseer-dispatch-v1"
        dispatch = {
            "schema": "neq.llm_staging_study3_synthetic_dispatch_authorization.v1",
            "ruling_id": dispatch_id,
            "study_id": STUDY_ID,
            "manifest_sha256": approval_pins.manifest_sha256,
            "generation_config_sha256": config_sha256,
            "cap_approval_ruling_id": approval_pins.cap_approval_ruling_id,
            "cap_approval_sha256": approval_pins.cap_approval_sha256,
            "readiness_ruling_id": readiness_id,
            "readiness_sha256": _sha256(readiness_bytes),
            "authorized_by_role": "overseer",
            "authorized_action": "DISPATCH_STUDY3",
            "attempt_cap": 3,
            "scene_order": list(SCENE_ORDER),
        }
        dispatch_bytes = _canonical_json(dispatch)
        dispatch_pins = study3_preflight.DispatchPins(
            study_id=STUDY_ID,
            manifest_sha256=approval_pins.manifest_sha256,
            generation_config_sha256=config_sha256,
            cap_approval_sha256=approval_pins.cap_approval_sha256,
            readiness_ruling_id=readiness_id,
            readiness_sha256=_sha256(readiness_bytes),
            dispatch_ruling_id=dispatch_id,
            dispatch_sha256=_sha256(dispatch_bytes),
        )
        return {
            "approval_pins": approval_pins,
            "standing_authority_source": standing_source,
            "cap_approval_source": cap_source,
            "cap_envelope_record": envelope_bytes,
            "dispatch_pins": dispatch_pins,
            "readiness_record": readiness_bytes,
            "dispatch_authorization_record": dispatch_bytes,
            "manifest_bytes": manifest_bytes,
            "config_sha256": config_sha256,
        }

    def _header(
        self,
        *,
        root_relative: str | None = None,
        dispatch_pins: study3_preflight.DispatchPins | None = None,
    ) -> dict[str, object]:
        pins = self.fixture["approval_pins"]
        dispatch_pins = dispatch_pins or self.fixture["dispatch_pins"]
        assert type(pins) is study3_preflight.ApprovalPins
        assert type(dispatch_pins) is study3_preflight.DispatchPins
        return {
            "event": "header",
            "schema": study3_preflight.LEDGER_SCHEMA,
            "study_id": STUDY_ID,
            "allocation_scope": "studywide",
            "root_relative": root_relative or study3_preflight.STUDY3_ROOT_RELATIVE,
            "attempt_cap": 3,
            "scene_order": list(SCENE_ORDER),
            "manifest_sha256": pins.manifest_sha256,
            "generation_config_sha256": pins.generation_config_sha256,
            "approval_pin_binding": {
                "standing_authority_ruling_id": pins.standing_authority_ruling_id,
                "standing_authority_sha256": pins.standing_authority_sha256,
                "cap_approval_ruling_id": pins.cap_approval_ruling_id,
                "cap_approval_sha256": pins.cap_approval_sha256,
                "cap_envelope_sha256": pins.cap_envelope_sha256,
            },
            "dispatch_pin_binding": {
                "readiness_ruling_id": dispatch_pins.readiness_ruling_id,
                "readiness_sha256": dispatch_pins.readiness_sha256,
                "dispatch_ruling_id": dispatch_pins.dispatch_ruling_id,
                "dispatch_sha256": dispatch_pins.dispatch_sha256,
            },
        }

    @staticmethod
    def _seal(payloads: list[dict[str, object]]) -> tuple[bytes, ...]:
        records = []
        previous = "0" * 64
        for payload in payloads:
            body = {"payload": payload, "previous_record_sha256": previous}
            digest = _sha256(_canonical_json(body))
            records.append(_canonical_json({**body, "record_sha256": digest}))
            previous = digest
        return tuple(records)

    @staticmethod
    def _receipt(attempt: int, *, cost: str = "0.01") -> dict[str, object]:
        generation_id = f"synthetic-gen-{attempt}"
        return {
            "receipt_id": generation_id,
            "study_id": STUDY_ID,
            "scene_id": SCENE_ORDER[attempt - 1],
            "attempt_number": attempt,
            "response_sha256": str(attempt) * 64,
            "returned_model_id": MODEL_ID,
            "upstream_provider": "OpenAI",
            "generation_id": generation_id,
            "cost_usd": cost,
            "prompt_tokens": 100,
            "completion_tokens": 30,
            "reasoning_tokens": 10,
        }

    def _snapshot(
        self,
        *,
        completed: int = 0,
        pending: bool = False,
        root_relative: str | None = None,
        scene_overrides: dict[int, str] | None = None,
        header_overrides: dict[str, object] | None = None,
        receipt_cost: str = "0.01",
        dispatch_pins: study3_preflight.DispatchPins | None = None,
        include_accounting: bool = True,
        accounting_status: str = "COMPLETE",
    ) -> study3_preflight.SyntheticLedgerSnapshot:
        header = self._header(root_relative=root_relative, dispatch_pins=dispatch_pins)
        if header_overrides:
            header.update(header_overrides)
        payloads: list[dict[str, object]] = [header]
        reservation_count = completed + (1 if pending else 0)
        receipts = []
        for index in range(reservation_count):
            attempt = index + 1
            scene = (scene_overrides or {}).get(index, SCENE_ORDER[index])
            run_id = f"synthetic-run-{attempt}"
            payloads.append({
                "event": "reservation",
                "study_id": STUDY_ID,
                "attempt_number": attempt,
                "scene_id": scene,
                "run_id": run_id,
            })
            if index < completed:
                receipt = self._receipt(attempt, cost=receipt_cost)
                receipts.append(receipt)
                payloads.append({
                    "event": "result",
                    "study_id": STUDY_ID,
                    "attempt_number": attempt,
                    "scene_id": scene,
                    "run_id": run_id,
                    "outcome": "ACCEPTED",
                    "stop_study": False,
                    "receipt": receipt,
                })
        if not receipts or not include_accounting:
            actual_accounting = None
        else:
            simplified = [
                {
                    "receipt_id": row["generation_id"],
                    "cost_usd": row["cost_usd"],
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                    "reasoning_tokens": row["reasoning_tokens"],
                }
                for row in receipts
            ]
            actual_accounting = _canonical_json({
                "schema": study3_preflight.ACCOUNTING_SCHEMA,
                "status": accounting_status,
                "study_id": STUDY_ID,
                "accounted_attempt_count": len(receipts),
                "attempt_cap": 3,
                "scene_ids": list(SCENE_ORDER[:len(receipts)]),
                "receipts": simplified,
                "reported_total_usd": str(
                    sum((Decimal(row["cost_usd"]) for row in receipts), Decimal(0))
                ),
            })
        return study3_preflight.SyntheticLedgerSnapshot(
            records=self._seal(payloads),
            actual_accounting=actual_accounting,
        )

    def _call(self, **overrides: object) -> study3_preflight.PreflightDecision:
        arguments = {
            key: value for key, value in self.fixture.items() if key != "config_sha256"
        }
        arguments.update({
            "scene_id": SCENE_ORDER[0],
            "ledger_snapshot": self._snapshot(),
        })
        arguments.update(overrides)
        return study3_preflight.synthetic_preflight(**arguments)

    def _assert_blocked(self, code: str, **overrides: object) -> None:
        with _preflight_side_effect_tripwires() as calls:
            with self.assertRaisesRegex(study3_preflight.PreflightBlocked, code):
                self._call(**overrides)
        self.assertEqual(calls, {"filesystem_write": 0, "credential_read": 0})

    def test_authorized_overseer_cap_and_separate_synthetic_ready_dispatch_allow_metadata_only(self) -> None:
        envelope = json.loads(self.fixture["cap_envelope_record"])
        self.assertEqual(envelope["approved_by_role"], "overseer")
        self.assertEqual(envelope["acting_for"], "owner")
        self.assertNotIn("owner_only_approval", envelope)
        with _preflight_side_effect_tripwires() as calls:
            decision = self._call()
        self.assertEqual(calls, {"filesystem_write": 0, "credential_read": 0})
        metadata = decision.to_dict()
        self.assertEqual(metadata["status"], "SYNTHETIC_PREFLIGHT_ACCEPTED")
        self.assertTrue(metadata["synthetic_only"])
        self.assertFalse(metadata["reservation_created"])
        self.assertFalse(metadata["credentials_loaded"])
        self.assertFalse(metadata["http_sent"])
        self.assertFalse(metadata["live_dispatch_permitted"])
        self.assertEqual(metadata["conservative_cost_usd_estimate"], "0.0324461")
        self.assertEqual(
            metadata["cap_approval_sha256"],
            self.fixture["approval_pins"].cap_approval_sha256,
        )
        self.assertEqual(
            metadata["dispatch_sha256"],
            self.fixture["dispatch_pins"].dispatch_sha256,
        )
        self.assertEqual(metadata["consumed_slots"], 0)
        self.assertEqual(metadata["next_attempt_number"], 1)

    def test_one_fresh_sizing_report_prices_actual_spend_plus_only_remaining_scenes(self) -> None:
        expected_report = study3_sizing.build_sizing_report()
        with patch.object(
            study3_sizing,
            "build_sizing_report",
            wraps=study3_sizing.build_sizing_report,
        ) as rebuild_report:
            with _preflight_side_effect_tripwires() as calls:
                initial = self._call()
            self.assertEqual(calls, {"filesystem_write": 0, "credential_read": 0})
            self.assertEqual(rebuild_report.call_count, 1)
        self.assertEqual(
            initial.conservative_cost_usd_estimate,
            expected_report["conservative_total_usd_estimate"],
        )

        for completed in (1, 2):
            with self.subTest(completed=completed):
                actual_total = Decimal(f"0.{completed:02d}")
                remaining_estimate = sum(
                    (
                        Decimal(row["conservative_cost_usd_estimate"])
                        for row in expected_report["scenes"][completed:]
                    ),
                    Decimal(0),
                )
                decision = self._call(
                    scene_id=SCENE_ORDER[completed],
                    ledger_snapshot=self._snapshot(completed=completed),
                )
                self.assertEqual(
                    Decimal(decision.conservative_cost_usd_estimate),
                    actual_total + remaining_estimate,
                )

    def test_actual_spend_plus_remaining_estimate_must_be_strictly_below_ceiling(self) -> None:
        report = study3_sizing.build_sizing_report()
        remaining_estimate = sum(
            (
                Decimal(row["conservative_cost_usd_estimate"])
                for row in report["scenes"][1:]
            ),
            Decimal(0),
        )
        equal_ceiling_actual = Decimal("0.05") - remaining_estimate
        cases = (
            ("valid actual cost but projected over ceiling", Decimal("0.045")),
            ("projected cost equals ceiling", equal_ceiling_actual),
        )
        for label, actual_cost in cases:
            with self.subTest(label=label):
                self.assertLess(actual_cost, Decimal("0.05"))
                self.assertGreaterEqual(
                    actual_cost + remaining_estimate,
                    Decimal("0.05"),
                )
                self._assert_blocked(
                    "PROJECTED_COST_REACHES_HARD_CEILING",
                    scene_id=SCENE_ORDER[1],
                    ledger_snapshot=self._snapshot(
                        completed=1,
                        receipt_cost=str(actual_cost),
                    ),
                )

    def test_one_and_two_completed_receipts_advance_across_run_ids_without_reset(self) -> None:
        for completed in (1, 2):
            with self.subTest(completed=completed):
                scene_id = SCENE_ORDER[completed]
                with _preflight_side_effect_tripwires() as calls:
                    decision = self._call(
                        scene_id=scene_id,
                        ledger_snapshot=self._snapshot(completed=completed),
                    )
                self.assertEqual(calls, {"filesystem_write": 0, "credential_read": 0})
                self.assertEqual(decision.consumed_slots, completed)
                self.assertEqual(decision.next_attempt_number, completed + 1)
                self.assertEqual(decision.actual_cost_usd, f"0.{completed:02d}")
        exhausted = self._snapshot(completed=3)
        rows = [json.loads(row)["payload"] for row in exhausted.records]
        run_ids = [row["run_id"] for row in rows if row["event"] == "reservation"]
        self.assertEqual(run_ids, ["synthetic-run-1", "synthetic-run-2", "synthetic-run-3"])
        self._assert_blocked(
            "SYNTHETIC_LEDGER_CAP_EXHAUSTED",
            scene_id=SCENE_ORDER[2],
            ledger_snapshot=exhausted,
        )

    def test_missing_mutable_mismatched_and_self_asserted_approval_are_refused(self) -> None:
        self._assert_blocked("TRUSTED_APPROVAL_PINS_REQUIRED", approval_pins=None)
        self._assert_blocked(
            "TRUSTED_APPROVAL_PINS_REQUIRED",
            approval_pins={"ruling_id": "neq-study3-pre-approved-20261110", "status": "PASS"},
        )
        self_asserted = {
            "ruling_id": "neq-study3-pre-approved-20261110",
            "status": "PASS",
            "attempt_cap": 3,
        }
        self_asserted["self_sha256"] = _sha256(_canonical_json(self_asserted))
        changed_source = self.fixture["cap_approval_source"] + b" changed"
        self._assert_blocked(
            "APPROVAL_SOURCE_HASH_OR_RULING_ID_MISMATCH",
            cap_approval_source=changed_source,
        )
        self._assert_blocked(
            "TRUSTED_APPROVAL_PINS_REQUIRED",
            approval_pins=None,
            cap_approval_source=_canonical_json(self_asserted),
        )

        missing_literal_id = b"synthetic opaque source with no ruling identifier"
        envelope_without_id = json.loads(self.fixture["cap_envelope_record"])
        envelope_without_id["standing_authority_source_sha256"] = _sha256(missing_literal_id)
        envelope_without_id_bytes = _canonical_json(envelope_without_id)
        pins = self.fixture["approval_pins"]
        assert type(pins) is study3_preflight.ApprovalPins
        pins_without_id = replace(
            pins,
            standing_authority_sha256=_sha256(missing_literal_id),
            cap_envelope_sha256=_sha256(envelope_without_id_bytes),
        )
        self._assert_blocked(
            "APPROVAL_SOURCE_HASH_OR_RULING_ID_MISMATCH",
            approval_pins=pins_without_id,
            standing_authority_source=missing_literal_id,
            cap_envelope_record=envelope_without_id_bytes,
        )

        altered_envelope = json.loads(self.fixture["cap_envelope_record"])
        altered_envelope["model_id"] = "other/model"
        altered_bytes = _canonical_json(altered_envelope)
        altered_pins = replace(
            self.fixture["approval_pins"], cap_envelope_sha256=_sha256(altered_bytes)
        )
        self._assert_blocked(
            "CAP_ENVELOPE_PIN_OR_FIELDS_MISMATCH",
            approval_pins=altered_pins,
            cap_envelope_record=altered_bytes,
        )

    def test_rebound_but_altered_generation_config_hash_is_refused(self) -> None:
        wrong_config_sha256 = "f" * 64
        envelope = json.loads(self.fixture["cap_envelope_record"])
        envelope["generation_config_sha256"] = wrong_config_sha256
        envelope_bytes = _canonical_json(envelope)
        approval_pins = replace(
            self.fixture["approval_pins"],
            generation_config_sha256=wrong_config_sha256,
            cap_envelope_sha256=_sha256(envelope_bytes),
        )
        readiness = json.loads(self.fixture["readiness_record"])
        readiness["generation_config_sha256"] = wrong_config_sha256
        readiness_bytes = _canonical_json(readiness)
        dispatch = json.loads(self.fixture["dispatch_authorization_record"])
        dispatch["generation_config_sha256"] = wrong_config_sha256
        dispatch["readiness_sha256"] = _sha256(readiness_bytes)
        dispatch_bytes = _canonical_json(dispatch)
        dispatch_pins = replace(
            self.fixture["dispatch_pins"],
            generation_config_sha256=wrong_config_sha256,
            readiness_sha256=_sha256(readiness_bytes),
            dispatch_sha256=_sha256(dispatch_bytes),
        )
        self._assert_blocked(
            "GENERATION_ENVELOPE_PIN_OR_FIELDS_MISMATCH",
            approval_pins=approval_pins,
            cap_envelope_record=envelope_bytes,
            dispatch_pins=dispatch_pins,
            readiness_record=readiness_bytes,
            dispatch_authorization_record=dispatch_bytes,
        )

    def test_missing_post_review_ready_or_dispatch_and_status_only_records_refuse(self) -> None:
        self._assert_blocked("POST_REVIEW_READY_AND_DISPATCH_PINS_REQUIRED", dispatch_pins=None)
        self._assert_blocked("READINESS_RECORD_INVALID", readiness_record=None)
        self._assert_blocked("DISPATCH_RECORD_INVALID", dispatch_authorization_record=None)
        status_only = _canonical_json({
            "ruling_id": "synthetic-study3-overseer-ready-v1",
            "status": "PASS",
        })
        pins = self.fixture["dispatch_pins"]
        assert type(pins) is study3_preflight.DispatchPins
        self._assert_blocked(
            "POST_REVIEW_READY_OR_DISPATCH_FIELDS_MISMATCH",
            readiness_record=status_only,
            dispatch_pins=replace(pins, readiness_sha256=_sha256(status_only)),
        )

    def test_one_overseer_ruling_id_can_bind_separate_ready_and_dispatch_records(self) -> None:
        readiness = json.loads(self.fixture["readiness_record"])
        ruling_id = readiness["ruling_id"]
        readiness_bytes = _canonical_json(readiness)
        dispatch = json.loads(self.fixture["dispatch_authorization_record"])
        dispatch["ruling_id"] = ruling_id
        dispatch["readiness_ruling_id"] = ruling_id
        dispatch["readiness_sha256"] = _sha256(readiness_bytes)
        dispatch_bytes = _canonical_json(dispatch)
        prior_pins = self.fixture["dispatch_pins"]
        assert type(prior_pins) is study3_preflight.DispatchPins
        pins = replace(
            prior_pins,
            readiness_ruling_id=ruling_id,
            readiness_sha256=_sha256(readiness_bytes),
            dispatch_ruling_id=ruling_id,
            dispatch_sha256=_sha256(dispatch_bytes),
        )
        self.assertNotEqual(pins.readiness_sha256, pins.dispatch_sha256)
        with _preflight_side_effect_tripwires() as calls:
            decision = self._call(
                dispatch_pins=pins,
                readiness_record=readiness_bytes,
                dispatch_authorization_record=dispatch_bytes,
                ledger_snapshot=self._snapshot(dispatch_pins=pins),
            )
        self.assertEqual(calls, {"filesystem_write": 0, "credential_read": 0})
        self.assertEqual(decision.readiness_ruling_id, ruling_id)
        self.assertEqual(decision.dispatch_ruling_id, ruling_id)
        self.assertNotEqual(decision.readiness_sha256, decision.dispatch_sha256)

    def test_dispatch_action_and_typed_readiness_are_still_required(self) -> None:
        prior_pins = self.fixture["dispatch_pins"]
        assert type(prior_pins) is study3_preflight.DispatchPins

        wrong_action = json.loads(self.fixture["dispatch_authorization_record"])
        wrong_action["authorized_action"] = "READY_ONLY"
        wrong_action_bytes = _canonical_json(wrong_action)
        wrong_action_pins = replace(
            prior_pins,
            dispatch_sha256=_sha256(wrong_action_bytes),
        )
        self._assert_blocked(
            "POST_REVIEW_READY_OR_DISPATCH_FIELDS_MISMATCH",
            dispatch_pins=wrong_action_pins,
            dispatch_authorization_record=wrong_action_bytes,
            ledger_snapshot=self._snapshot(dispatch_pins=wrong_action_pins),
        )

        untyped_readiness = json.loads(self.fixture["readiness_record"])
        untyped_readiness["software_preparation_readiness"] = True
        untyped_readiness_bytes = _canonical_json(untyped_readiness)
        wrong_readiness_dispatch = json.loads(self.fixture["dispatch_authorization_record"])
        wrong_readiness_dispatch["readiness_sha256"] = _sha256(untyped_readiness_bytes)
        wrong_readiness_dispatch_bytes = _canonical_json(wrong_readiness_dispatch)
        untyped_pins = replace(
            prior_pins,
            readiness_sha256=_sha256(untyped_readiness_bytes),
            dispatch_sha256=_sha256(wrong_readiness_dispatch_bytes),
        )
        self._assert_blocked(
            "POST_REVIEW_READY_OR_DISPATCH_FIELDS_MISMATCH",
            dispatch_pins=untyped_pins,
            readiness_record=untyped_readiness_bytes,
            dispatch_authorization_record=wrong_readiness_dispatch_bytes,
            ledger_snapshot=self._snapshot(dispatch_pins=untyped_pins),
        )

    def test_missing_pending_corrupt_exhausted_and_mismatched_ledger_states_refuse(self) -> None:
        self._assert_blocked("SYNTHETIC_LEDGER_STATE_MISSING", ledger_snapshot=None)
        self._assert_blocked(
            "SYNTHETIC_LEDGER_PENDING_RESERVATION",
            ledger_snapshot=self._snapshot(pending=True),
        )

        corrupt = self._snapshot()
        corrupted_records = list(corrupt.records)
        corrupted_records[0] = corrupted_records[0][:-1] + b" "
        self._assert_blocked(
            "SYNTHETIC_LEDGER_CORRUPT",
            ledger_snapshot=study3_preflight.SyntheticLedgerSnapshot(tuple(corrupted_records)),
        )
        self._assert_blocked(
            "SYNTHETIC_LEDGER_HEADER_MISMATCH",
            ledger_snapshot=self._snapshot(root_relative="tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2"),
        )
        for other_root in (
            "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study1",
            "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging-study2",
            "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/new-study3-run-root",
        ):
            with self.subTest(root=other_root):
                self._assert_blocked(
                    "SYNTHETIC_LEDGER_HEADER_MISMATCH",
                    ledger_snapshot=self._snapshot(root_relative=other_root),
                )
        self._assert_blocked(
            "SYNTHETIC_LEDGER_HEADER_MISMATCH",
            ledger_snapshot=self._snapshot(header_overrides={"manifest_sha256": "f" * 64}),
        )
        self._assert_blocked(
            "SYNTHETIC_LEDGER_SCENE_OR_RUN_MISMATCH",
            scene_id=SCENE_ORDER[1],
            ledger_snapshot=self._snapshot(completed=2, scene_overrides={1: SCENE_ORDER[0]}),
        )
        self._assert_blocked(
            "SCENE_NOT_APPROVED",
            scene_id="unapproved-scene",
        )
        self._assert_blocked(
            "SCENE_ORDER_OR_REPEAT_MISMATCH",
            scene_id=SCENE_ORDER[0],
            ledger_snapshot=self._snapshot(completed=1),
        )

    def test_completed_receipts_require_exact_incremental_cost_accounting(self) -> None:
        self._assert_blocked(
            "ACTUAL_COST_STOP_MISSING_OR_PENDING",
            scene_id=SCENE_ORDER[1],
            ledger_snapshot=self._snapshot(completed=1, include_accounting=False),
        )
        self._assert_blocked(
            "ACTUAL_COST_STOP_PENDING_OR_MISMATCHED",
            scene_id=SCENE_ORDER[1],
            ledger_snapshot=self._snapshot(completed=1, accounting_status="PENDING"),
        )
        mismatch = self._snapshot(completed=1)
        accounting = json.loads(mismatch.actual_accounting)
        accounting["receipts"][0]["cost_usd"] = "0.02"
        mismatch = replace(mismatch, actual_accounting=_canonical_json(accounting))
        self._assert_blocked(
            "ACTUAL_COST_STOP_PENDING_OR_MISMATCHED",
            scene_id=SCENE_ORDER[1],
            ledger_snapshot=mismatch,
        )

    def test_attempt_outcomes_consume_slot_and_preserve_stop_boundary(self) -> None:
        identity = study3_preflight.ProviderIdentity(
            study_id=STUDY_ID,
            scene_id=SCENE_ORDER[0],
            attempt_number=1,
            response_sha256="a" * 64,
            returned_model_id=MODEL_ID,
            upstream_provider="OpenAI",
            generation_id="synthetic-generation-1",
        )
        accepted = study3_preflight.classify_attempt_outcome(
            attempt_number=1,
            scene_id=SCENE_ORDER[0],
            http_status=200,
            transport_error=False,
            provider_identity=identity,
            output_status="PASS",
        )
        self.assertEqual(accepted.classification, "ACCEPTED")
        self.assertTrue(accepted.attempt_consumed)
        self.assertTrue(accepted.next_scene_allowed)
        for output_status in ("INVALID", "TRUNCATED", "GATE_FAILED", "NOT_EVALUATED"):
            with self.subTest(output_status=output_status):
                failed = study3_preflight.classify_attempt_outcome(
                    attempt_number=1,
                    scene_id=SCENE_ORDER[0],
                    http_status=200,
                    transport_error=False,
                    provider_identity=identity,
                    output_status=output_status,
                )
                self.assertEqual(failed.classification, "CONTRACT_FAILURE")
                self.assertTrue(failed.attempt_consumed)
                self.assertFalse(failed.stop_study)
                self.assertTrue(failed.next_scene_allowed)
        for kwargs, classification in (
            ({"http_status": 503, "transport_error": False, "provider_identity": identity}, "STOP_NON_200"),
            ({"http_status": 200, "transport_error": True, "provider_identity": None}, "STOP_TRANSPORT_FAILURE"),
            ({"http_status": 200, "transport_error": False, "provider_identity": None}, "STOP_IDENTITY_FAILURE"),
            ({"http_status": 200, "transport_error": False, "provider_identity": replace(identity, returned_model_id="other/model")}, "STOP_IDENTITY_FAILURE"),
            ({"http_status": 200, "transport_error": False, "provider_identity": replace(identity, upstream_provider="unknown")}, "STOP_IDENTITY_FAILURE"),
            ({"http_status": 200, "transport_error": False, "provider_identity": replace(identity, generation_id="")}, "STOP_IDENTITY_FAILURE"),
        ):
            with self.subTest(classification=classification, kwargs=kwargs):
                stopped = study3_preflight.classify_attempt_outcome(
                    attempt_number=1,
                    scene_id=SCENE_ORDER[0],
                    output_status="PASS",
                    **kwargs,
                )
                self.assertEqual(stopped.classification, classification)
                self.assertTrue(stopped.attempt_consumed)
                self.assertTrue(stopped.stop_study)
                self.assertFalse(stopped.next_scene_allowed)
        self.assertEqual(stopped.remaining_attempts_unspent, 2)


class Study3TripwireTest(Study3GuardedTestCase):
    def test_every_discovered_study3_test_class_uses_the_guarded_base(self) -> None:
        test_classes = {
            value
            for value in globals().values()
            if isinstance(value, type)
            and value is not Study3GuardedTestCase
            and issubclass(value, unittest.TestCase)
            and any(name.startswith("test") for name in dir(value))
        }
        self.assertGreaterEqual(len(test_classes), 8)
        for test_class in test_classes:
            with self.subTest(test_class=test_class.__name__):
                self.assertTrue(issubclass(test_class, Study3GuardedTestCase))
                self.assertIsNot(test_class.setUp, unittest.TestCase.setUp)
                if "setUp" in test_class.__dict__:
                    self.assertTrue(
                        getattr(test_class.setUp, "_study3_tripwire_wrapper", False)
                    )

    def test_network_and_loaded_http_entrypoints_trip_before_connect(self) -> None:
        with self.assertRaises(TripwireBlocked):
            socket.create_connection(("127.0.0.1", 1), timeout=0.01)
        with self.assertRaises(TripwireBlocked):
            socket.socket.connect(None, ("127.0.0.1", 1))

        connection = http.client.HTTPConnection("127.0.0.1", 1)
        with self.assertRaises(TripwireBlocked):
            connection.connect()
        with self.assertRaises(TripwireBlocked):
            connection.request("GET", "/")
        with self.assertRaises(TripwireBlocked):
            urllib.request.urlopen("http://127.0.0.1:1/", timeout=0.01)
        self.assertGreater(self._study3_tripwire_calls.get("network", 0), 0)

    def test_config_imports_file_reads_and_credential_lookups_trip_early(self) -> None:
        with self.assertRaises(TripwireBlocked):
            builtins.__import__("config")
        with self.assertRaises(TripwireBlocked):
            importlib.import_module("model_config")
        with self.assertRaises(TripwireBlocked):
            builtins.open(REPO_ROOT / "config.py", "rb")
        with self.assertRaises(TripwireBlocked):
            (REPO_ROOT / "config.py").open("rb")
        with self.assertRaises(TripwireBlocked):
            os.open(REPO_ROOT / "model_config.py", os.O_RDONLY)

        with self.assertRaises(TripwireBlocked):
            os.getenv("OPENAI_API_KEY")
        with self.assertRaises(TripwireBlocked):
            os.environ.get("OPENROUTER_API_KEY")
        with self.assertRaises(TripwireBlocked):
            "OPENAI_API_KEY" in os.environ
        environments = [os.environ]
        if hasattr(os, "environb"):
            environments.append(os.environb)
        for environment in environments:
            for accessor in (
                environment.items,
                environment.values,
                environment.copy,
                environment.popitem,
                lambda env=environment: repr(env),
            ):
                with self.assertRaises(TripwireBlocked):
                    accessor()
        self.assertGreater(
            self._study3_tripwire_calls.get("config_file_access", 0), 0
        )
        self.assertGreater(
            self._study3_tripwire_calls.get("credential_lookup", 0), 0
        )
        self.assertGreater(
            self._study3_tripwire_calls.get("credential_enumeration", 0), 0
        )

    def test_provider_sdk_import_and_already_loaded_constructor_are_blocked(self) -> None:
        with self.assertRaises(TripwireBlocked):
            importlib.import_module("openai")

        constructed: list[bool] = []

        def initialize(_self: object) -> None:
            constructed.append(True)

        dummy_module = types.ModuleType("openai")
        dummy_module.OpenAI = type(
            "OpenAI",
            (),
            {"__module__": "openai", "__init__": initialize},
        )
        with patch.dict(sys.modules, {"openai": dummy_module}):
            nested_stack = ExitStack()
            nested_calls = install_tripwires(nested_stack, REPO_ROOT)
            try:
                with self.assertRaises(TripwireBlocked):
                    dummy_module.OpenAI()
            finally:
                nested_stack.close()
            self.assertIs(dummy_module.OpenAI.__init__, initialize)
        self.assertEqual(constructed, [])
        self.assertEqual(nested_calls.get("provider_construction"), 1)

    def test_real_ledger_apis_and_fixed_roots_are_blocked_but_prep_is_writable(
        self,
    ) -> None:
        study2_ledger_module = sys.modules.get(
            "scripts.mise_en_scene.llm_staging_study2.ledger"
        )
        study2_client_module = sys.modules.get(
            "scripts.mise_en_scene.llm_staging_study2.client"
        )
        study1_client_module = sys.modules.get(
            "scripts.mise_en_scene.llm_staging.client"
        )
        self.assertIsNotNone(study2_ledger_module)
        self.assertIsNotNone(study2_client_module)
        self.assertIsNotNone(study1_client_module)
        study2_ledger = vars(study2_ledger_module)["Study2Ledger"]
        study2_client = vars(study2_client_module)["Study2Client"]
        study1_client = vars(study1_client_module)["StagingClient"]

        with self.assertRaises(TripwireBlocked):
            study2_ledger().initialize({})
        with self.assertRaises(TripwireBlocked):
            study2_ledger().reserve(
                {},
                scene_id="not-a-scene",
                run_id="synthetic",
                run_root_relative="synthetic",
                request_sha256="0" * 64,
            )
        with self.assertRaises(TripwireBlocked):
            study2_ledger().complete({})
        with self.assertRaises(TripwireBlocked):
            object.__new__(study2_client).initialize_ledger()
        with self.assertRaises(TripwireBlocked):
            object.__new__(study1_client).send_once("not-a-scene")
        with self.assertRaises(TripwireBlocked):
            object.__new__(study1_client)._append_ledger_event({})

        for relative_root in REAL_LEDGER_ROOTS:
            ledger_path = REPO_ROOT / relative_root / "study-attempt-ledger.jsonl"
            self.assertTrue(protected_real_ledger_path(ledger_path, REPO_ROOT))
            with self.assertRaises(TripwireBlocked):
                ledger_path.open("wb")
        study3_root = REPO_ROOT / REAL_LEDGER_ROOTS[-1]
        with self.assertRaises(TripwireBlocked):
            os.open(
                study3_root / "study-attempt-ledger.jsonl",
                os.O_WRONLY | os.O_CREAT,
                0o600,
            )

        PREP_ROOT.mkdir(parents=True, exist_ok=True)
        self.assertFalse(
            protected_real_ledger_path(PREP_ROOT / "synthetic-ledger.jsonl", REPO_ROOT)
        )
        with tempfile.TemporaryDirectory(prefix="study3-tripwire-", dir=PREP_ROOT) as temp_dir:
            scratch = Path(temp_dir)
            alias = scratch / "study1-ledger-root"
            target_root = os.path.relpath(
                REPO_ROOT / REAL_LEDGER_ROOTS[0], start=scratch
            )
            alias.symlink_to(target_root, target_is_directory=True)
            aliased_ledger = alias / "study-attempt-ledger.jsonl"
            self.assertTrue(protected_real_ledger_path(aliased_ledger, REPO_ROOT))
            with self.assertRaises(TripwireBlocked):
                aliased_ledger.open("wb")

            synthetic_ledger = scratch / "synthetic-ledger.jsonl"
            synthetic_ledger.write_text("synthetic fixture only", encoding="utf-8")
            self.assertEqual(
                synthetic_ledger.read_text(encoding="utf-8"), "synthetic fixture only"
            )

        self.assertGreater(self._study3_tripwire_calls.get("real_ledger_api", 0), 0)
        self.assertGreater(
            self._study3_tripwire_calls.get("real_ledger_path_write", 0), 0
        )

    def test_nested_exit_stack_restores_every_outer_patch(self) -> None:
        before = _tripwire_patch_snapshot()
        nested_stack = ExitStack()
        install_tripwires(nested_stack, REPO_ROOT)
        self.assertNotEqual(_tripwire_patch_snapshot(), before)
        nested_stack.close()
        self.assertEqual(_tripwire_patch_snapshot(), before)

    def test_unittest_cleanup_restores_guards_before_the_next_suite(self) -> None:
        outer_state = _tripwire_patch_snapshot()

        class GuardedProbe(Study3GuardedTestCase):
            def test_tripwire_is_active(self) -> None:
                with self.assertRaises(TripwireBlocked):
                    socket.create_connection(("127.0.0.1", 1), timeout=0.01)

        class UnrelatedProbe(unittest.TestCase):
            def test_prior_patches_are_restored(self) -> None:
                self.assertEqual(_tripwire_patch_snapshot(), outer_state)

        result = unittest.TestSuite(
            (
                GuardedProbe("test_tripwire_is_active"),
                UnrelatedProbe("test_prior_patches_are_restored"),
            )
        ).run(unittest.TestResult())
        self.assertEqual(result.testsRun, 2)
        self.assertTrue(result.wasSuccessful(), (result.errors, result.failures))

    def test_study3_package_has_no_sensitive_or_live_imports(self) -> None:
        forbidden_roots = {
            "anthropic",
            "aiohttp",
            "cohere",
            "config",
            "google",
            "groq",
            "httpcore",
            "httpx",
            "litellm",
            "model_config",
            "mistralai",
            "openai",
            "replicate",
            "requests",
            "socketio",
            "together",
            "urllib3",
            "vertexai",
            "websockets",
        }
        forbidden_ledger_suffixes = {
            "llm_staging.client",
            "llm_staging.transport",
            "llm_staging_study2.client",
            "llm_staging_study2.ledger",
            "llm_staging_study2.transport",
        }
        forbidden_symbols = {"OpenAI", "Study2Client", "Study2Ledger", "StagingClient"}
        violations: list[str] = []
        for source_path in sorted(STUDY3_PACKAGE.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported_names = [node.module or ""]
                    imported_names.extend(alias.name for alias in node.names)
                else:
                    continue
                for imported_name in imported_names:
                    root = imported_name.split(".", 1)[0].lstrip(".")
                    if (
                        root in forbidden_roots
                        or any(
                            imported_name.endswith(suffix)
                            for suffix in forbidden_ledger_suffixes
                        )
                        or imported_name in forbidden_symbols
                    ):
                        violations.append(
                            source_path.relative_to(REPO_ROOT).as_posix()
                            + ":"
                            + str(node.lineno)
                        )
        self.assertEqual(violations, [])

    def test_fresh_subprocess_guards_before_import_and_runs_pure_preparation(self) -> None:
        child_code = textwrap.dedent(
            """
            import builtins
            import http.client
            import importlib
            import importlib.util
            import json
            import os
            from pathlib import Path
            import runpy
            import socket
            import sys
            import tempfile
            import types
            import urllib.request
            from contextlib import ExitStack
            from unittest.mock import patch

            try:
                repo_root = Path.cwd()
                support = runpy.run_path(
                    "scripts/mise_en_scene/llm_staging_study3/isolation_guard.py"
                )
                install_tripwires = support["install_tripwires"]
                TripwireBlocked = support["TripwireBlocked"]
                suite_spec = importlib.util.spec_from_file_location(
                    "_study3_suite_import_probe",
                    repo_root / "scripts/test_mise_en_scene_llm_staging_study3.py",
                )
                if suite_spec is None or suite_spec.loader is None:
                    raise AssertionError("Study 3 suite could not be loaded")
                suite_module = importlib.util.module_from_spec(suite_spec)
                suite_spec.loader.exec_module(suite_module)
                original_targets = suite_module._tripwire_patch_snapshot()
                guard_stack = ExitStack()
                calls = install_tripwires(guard_stack, repo_root)

                def probe(operation):
                    try:
                        operation()
                    except TripwireBlocked:
                        return
                    raise AssertionError("tripwire did not block probe")

                probe(lambda: __import__("config"))
                probe(lambda: importlib.import_module("model_config"))
                probe(lambda: importlib.import_module("openai"))
                probe(lambda: importlib.import_module("requests"))
                probe(lambda: (repo_root / "config.py").open("rb"))
                probe(lambda: builtins.open(repo_root / "config.py", "rb"))
                probe(lambda: os.open(repo_root / "model_config.py", os.O_RDONLY))
                probe(lambda: os.getenv("OPENAI_API_KEY"))
                probe(lambda: os.environ.get("OPENROUTER_API_KEY"))
                probe(lambda: os.environ.items())
                probe(lambda: os.environ.values())
                probe(lambda: os.environ.copy())
                probe(lambda: socket.create_connection(("127.0.0.1", 1), timeout=0.01))
                probe(lambda: socket.socket.connect(None, ("127.0.0.1", 1)))
                connection = http.client.HTTPConnection("127.0.0.1", 1)
                probe(lambda: connection.connect())
                probe(lambda: connection.request("GET", "/"))
                probe(lambda: urllib.request.urlopen("http://127.0.0.1:1/", timeout=0.01))

                for root in support["REAL_LEDGER_ROOTS"]:
                    ledger_path = repo_root / root / "study-attempt-ledger.jsonl"
                    probe(lambda path=ledger_path: path.open("wb"))
                ledger_path = (
                    repo_root
                    / support["REAL_LEDGER_ROOTS"][-1]
                    / "study-attempt-ledger.jsonl"
                )
                probe(lambda: os.open(ledger_path, os.O_WRONLY | os.O_CREAT, 0o600))

                constructed = []
                def initialize(_self):
                    constructed.append(True)
                dummy_sdk = types.ModuleType("openai")
                dummy_sdk.OpenAI = type(
                    "OpenAI",
                    (),
                    {"__module__": "openai", "__init__": initialize},
                )
                with patch.dict(sys.modules, {"openai": dummy_sdk}):
                    nested_stack = ExitStack()
                    nested_calls = install_tripwires(nested_stack, repo_root)
                    try:
                        probe(lambda: dummy_sdk.OpenAI())
                    finally:
                        nested_stack.close()
                if constructed or nested_calls.get("provider_construction") != 1:
                    raise AssertionError("loaded provider constructor was not blocked")
                if dummy_sdk.OpenAI.__init__ is not initialize:
                    raise AssertionError("provider constructor guard was not restored")

                from scripts.mise_en_scene.llm_staging_study3.protocol import (
                    PROTOCOL_ROOT,
                    SCENE_ORDER,
                )
                from scripts.mise_en_scene.llm_staging_study3.newrequest import build_request
                from scripts.mise_en_scene.llm_staging_study3.newhydration import (
                    validate_delta_output,
                )
                from scripts.mise_en_scene.llm_staging_study3.sizing import (
                    build_sizing_report,
                )

                ledger_module = sys.modules.get(
                    "scripts.mise_en_scene.llm_staging_study2.ledger"
                )
                study2_client_module = sys.modules.get(
                    "scripts.mise_en_scene.llm_staging_study2.client"
                )
                study1_client_module = sys.modules.get(
                    "scripts.mise_en_scene.llm_staging.client"
                )
                if not all((ledger_module, study2_client_module, study1_client_module)):
                    raise AssertionError("real ledger modules were not observed")
                study2_ledger = vars(ledger_module)["Study2Ledger"]
                study2_client = vars(study2_client_module)["Study2Client"]
                study1_client = vars(study1_client_module)["StagingClient"]
                probe(lambda: study2_ledger().initialize({}))
                probe(
                    lambda: study2_ledger().reserve(
                        {},
                        scene_id="not-a-scene",
                        run_id="synthetic",
                        run_root_relative="synthetic",
                        request_sha256="0" * 64,
                    )
                )
                probe(lambda: study2_ledger().complete({}))
                probe(lambda: object.__new__(study2_client).initialize_ledger())
                probe(lambda: object.__new__(study1_client).send_once("not-a-scene"))
                probe(lambda: object.__new__(study1_client)._append_ledger_event({}))

                pure_effect_counts = {
                    name: calls.get(name, 0)
                    for name in (
                        "network",
                        "provider_import",
                        "provider_construction",
                        "http_import",
                        "config_import",
                        "config_file_access",
                        "credential_lookup",
                        "credential_enumeration",
                        "real_ledger_api",
                        "real_ledger_path_write",
                    )
                }
                manifest = json.loads(
                    (PROTOCOL_ROOT / "staging-manifest.json").read_bytes()
                )
                for row in manifest["references"]:
                    scene_id = row["scene_id"]
                    request = build_request(scene_id)
                    if request["model"] != "openai/gpt-6-luna":
                        raise AssertionError("unexpected request model")
                    reference = (repo_root / row["path"]).read_bytes()
                    report = validate_delta_output(reference, scene_id=scene_id)
                    if report.deterministic_status != "PASS":
                        raise AssertionError("hand reference did not pass full gates")
                if tuple(row["scene_id"] for row in manifest["references"]) != SCENE_ORDER:
                    raise AssertionError("reference order mismatch")
                sizing = build_sizing_report()
                from decimal import Decimal
                if Decimal(sizing["conservative_total_usd_estimate"]) >= Decimal("0.05"):
                    raise AssertionError("sizing estimate exceeded hard ceiling")
                if any(
                    calls.get(name, 0) != count
                    for name, count in pure_effect_counts.items()
                ):
                    raise AssertionError("pure preparation hit an external-effect tripwire")
                guard_stack.close()

                restored_targets = suite_module._tripwire_patch_snapshot()
                if restored_targets != original_targets:
                    raise AssertionError("tripwire ExitStack did not restore all targets")
                print("FRESH_GUARD_PASS")
            except BaseException as error:
                print("FRESH_GUARD_FAIL:" + type(error).__name__)
                raise SystemExit(1)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", child_code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env={},
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            "fresh guarded subprocess failed: " + result.stdout.strip(),
        )
        self.assertEqual(result.stdout.strip(), "FRESH_GUARD_PASS")


if __name__ == "__main__":
    unittest.main()
