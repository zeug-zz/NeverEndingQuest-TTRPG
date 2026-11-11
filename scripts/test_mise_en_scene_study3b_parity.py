# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free Study 3b request, contract, and hydration parity tests."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from copy import deepcopy
import builtins
from dataclasses import FrozenInstanceError, replace
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sys
import unittest
import urllib.request
from unittest.mock import patch

_SCRIPT_PATH = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(_SCRIPT_PATH))

from jsonschema import Draft202012Validator

from scripts.mise_en_scene.llm_staging_study2 import hydration as study2_hydration
from scripts.mise_en_scene.llm_staging_study3b.study3_compat import (
    contract as study3_contract,
    newrequest as study3_request,
    protocol as study3_protocol,
)
from scripts.mise_en_scene.llm_staging_study3b import contract as study3b_contract
from scripts.mise_en_scene.llm_staging_study3b import hydration as study3b_hydration
from scripts.mise_en_scene.llm_staging_study3b import newrequest as study3b_request
from scripts.mise_en_scene.llm_staging_study3b import inventory as inventory_module
from scripts.mise_en_scene.llm_staging_study3b.isolation import (
    BASELINE_PATH_RELATIVE,
    build_prior_study_baseline,
    read_baseline_metadata,
)
from scripts.mise_en_scene.llm_staging_study3b.inventory import (
    FactInventoryError,
    PUBLIC_AUDIENCE,
    SceneFactInventory,
    load_scene_inventory,
)

ContractError = study3_contract.ContractError


REPO_ROOT = Path(os.path.dirname(os.path.dirname(_SCRIPT_PATH)))
BASELINE_PATH = REPO_ROOT / BASELINE_PATH_RELATIVE
_PUBLIC_FACTS_BEGIN = "<<<STUDY3B_PUBLIC_FACT_INVENTORY_JSON_BEGIN>>>"
_PUBLIC_FACTS_END = "<<<STUDY3B_PUBLIC_FACT_INVENTORY_JSON_END>>>"


@contextmanager
def _provider_free_tripwires():
    calls = {"network": 0, "credential": 0, "provider_import": 0}

    def block_network(*_args: object, **_kwargs: object) -> None:
        calls["network"] += 1
        raise AssertionError("network access is forbidden in Study 3b parity tests")

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object):
        if name.split(".", 1)[0] in {"openai", "requests", "httpx", "anthropic"}:
            calls["provider_import"] += 1
            raise AssertionError("provider imports are forbidden in parity tests")
        return original_import(name, *args, **kwargs)

    original_getenv = os.getenv

    def guarded_getenv(key: str, default: object = None):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden in parity tests")
        return original_getenv(key, default)

    environ_type = type(os.environ)
    original_env_get = environ_type.get
    original_env_getitem = environ_type.__getitem__

    def guarded_env_get(env: object, key: object, default: object = None):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden in parity tests")
        return original_env_get(env, key, default)

    def guarded_env_getitem(env: object, key: object):
        if key in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            calls["credential"] += 1
            raise AssertionError("credential access is forbidden in parity tests")
        return original_env_getitem(env, key)

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket, "create_connection", side_effect=block_network))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=block_network))
        stack.enter_context(
            patch.object(http.client.HTTPConnection, "request", side_effect=block_network)
        )
        stack.enter_context(patch.object(urllib.request, "urlopen", side_effect=block_network))
        stack.enter_context(patch.object(builtins, "__import__", guarded_import))
        stack.enter_context(patch.object(os, "getenv", guarded_getenv))
        stack.enter_context(patch.object(environ_type, "get", guarded_env_get))
        stack.enter_context(
            patch.object(environ_type, "__getitem__", guarded_env_getitem)
        )
        yield calls


def _canonical(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _request_section(request: dict[str, object], name: str) -> object:
    user_message = request["messages"][1]["content"]  # type: ignore[index]
    begin, end, _rule_id = study3_request._SECTION_MARKERS[name]
    if user_message.count(begin) != 1 or user_message.count(end) != 1:
        raise AssertionError("request section markers are not unique")
    start = user_message.index(begin) + len(begin)
    finish = user_message.index(end)
    contents = user_message[start:finish].strip("\n")
    return json.loads(contents)


def _public_envelope(request: dict[str, object]) -> dict[str, object]:
    user_message = request["messages"][1]["content"]  # type: ignore[index]
    if user_message.count(_PUBLIC_FACTS_BEGIN) != 1 or user_message.count(
        _PUBLIC_FACTS_END
    ) != 1:
        raise AssertionError("Study 3b public inventory markers are not unique")
    start = user_message.index(_PUBLIC_FACTS_BEGIN) + len(_PUBLIC_FACTS_BEGIN)
    finish = user_message.index(_PUBLIC_FACTS_END)
    return json.loads(user_message[start:finish].strip("\n"))


def _replace_public_envelope(
    request: dict[str, object], envelope: dict[str, object]
) -> dict[str, object]:
    result = deepcopy(request)
    messages = result["messages"]
    user_message = messages[1]["content"]
    start = user_message.index(_PUBLIC_FACTS_BEGIN) + len(_PUBLIC_FACTS_BEGIN)
    finish = user_message.index(_PUBLIC_FACTS_END)
    messages[1]["content"] = (
        user_message[:start]
        + "\n"
        + _canonical(envelope)
        + "\n"
        + user_message[finish:]
    )
    return result


def _valid_delta(
    request: dict[str, object],
    fact_ids: str | tuple[str, ...],
    *,
    include_claim: bool = True,
) -> dict[str, object]:
    input_refs = _request_section(request, "input_refs")
    topology = _request_section(request, "topology_binding")
    scene_id = input_refs["scene_id"]
    roles = topology["stage_role_candidates"]
    segment_specs = (
        ("approach", "A bright glint crosses the stone."),
        ("threshold", "A narrow arch frames the room."),
        ("focal", "The central anchor is visible."),
    )
    arrivals = [
        {"id": scene_id + ":arrival:" + role, "role": role, "text": text}
        for role, text in segment_specs
    ]
    claim_groups = [
        {"segment_id": scene_id + ":arrival:" + role, "items": []}
        for role, _text in segment_specs
    ]
    if include_claim:
        if type(fact_ids) is str:
            claim_fact_ids = (fact_ids,)
        else:
            claim_fact_ids = fact_ids
        for index, fact_id in enumerate(claim_fact_ids):
            claim_groups[0]["items"].append(
                {
                    "id": scene_id + ":claim:public-source-" + str(index),
                    "fact_id": fact_id,
                    "kind": "factual",
                    "span": "bright glint",
                    "choice": None,
                    "success": None,
                }
            )
    module_id = topology["module_id"]
    return {
        "schema": "neq.llm_staging_study3_delta.v1",
        "input_refs": input_refs,
        "fixture_deltas": {
            "facts": [
                {
                    "fact_id": module_id + ":fact:study3-authored:edge-a",
                    "subject_id": roles["approach"][0],
                    "predicate": "approach_to_threshold",
                    "object_id": roles["threshold"][0],
                    "value": True,
                },
                {
                    "fact_id": module_id + ":fact:study3-authored:edge-b",
                    "subject_id": roles["threshold"][0],
                    "predicate": "threshold_to_focal",
                    "object_id": roles["focal_anchor"][0],
                    "value": True,
                },
            ]
        },
        "stage_role_bindings": {
            "approach": [roles["approach"][0]],
            "threshold": [roles["threshold"][0]],
            "focal_anchor": [roles["focal_anchor"][0]],
            "usable_space": [roles["usable_space"][0]],
        },
        "claims": claim_groups,
        "arrival_prose": arrivals,
    }


def _encoded_delta(delta: dict[str, object]) -> bytes:
    return _canonical(delta).encode("utf-8")


def _expected_authored_fact_ids(
    encoded_delta: bytes, scene_id: str, inventory: SceneFactInventory
) -> frozenset[str]:
    validated = study3b_contract.validate_delta_payload(
        encoded_delta, scene_id=scene_id, inventory=inventory
    )
    return study3b_hydration._projected_authored_fact_ids(
        validated, inventory.module_id
    )


def _synthetic_nested_inventory_and_canonical(scene_id: str):
    """Overlay a nested value in memory without writing any frozen input."""

    inventory = load_scene_inventory(scene_id)
    target = next(
        record
        for record in inventory.request_public_facts
        if record.claim_reference_eligible
    )
    nested_value = {
        "details": {
            "labels": ["SYNTHETIC_OUTER", {"items": ["SYNTHETIC_INNER", 17]}]
        },
        "flags": [True, {"enabled": False}],
    }
    replacement = replace(
        target, value=inventory_module._freeze(deepcopy(nested_value))
    )
    records = tuple(
        replacement if record.fact_id == target.fact_id else record
        for record in inventory.records
    )
    snapshot = inventory_module._to_plain(inventory._snapshot)
    snapshot["facts"] = [record.to_request_record() for record in records]
    digest = hashlib.sha256(
        inventory_module._canonical_json_bytes(snapshot)
    ).hexdigest()
    synthetic_inventory = replace(
        inventory,
        records=records,
        inventory_sha256=digest,
        _snapshot=inventory_module._freeze(snapshot),
    )
    inventory_module._validate_inventory(synthetic_inventory)

    canonical = study2_hydration._load_canonical_inputs(scene_id)
    expected_bundle = json.loads(canonical.expected_bundle_bytes.decode("utf-8"))
    source_record = next(
        row
        for row in expected_bundle["source_facts"]["facts"]
        if row["fact_id"] == target.fact_id
    )
    source_record["value"] = deepcopy(nested_value)
    synthetic_expected_bytes = _canonical(expected_bundle).encode("utf-8")
    synthetic_canonical = replace(
        canonical, expected_bundle_bytes=synthetic_expected_bytes
    )
    return synthetic_inventory, synthetic_canonical, target.fact_id, nested_value


def _rehash_inventory(
    inventory,
    *,
    records=None,
    protected_unknowns=None,
):
    updated_records = inventory.records if records is None else tuple(records)
    updated_unknowns = (
        inventory.protected_unknowns
        if protected_unknowns is None
        else tuple(
            inventory_module._freeze(deepcopy(row)) for row in protected_unknowns
        )
    )
    snapshot = inventory_module._to_plain(inventory._snapshot)
    snapshot["facts"] = [record.to_request_record() for record in updated_records]
    snapshot["protected_unknowns"] = [
        inventory_module._to_plain(row) for row in updated_unknowns
    ]
    digest = hashlib.sha256(
        inventory_module._canonical_json_bytes(snapshot)
    ).hexdigest()
    return replace(
        inventory,
        records=updated_records,
        protected_unknowns=updated_unknowns,
        inventory_sha256=digest,
        _snapshot=inventory_module._freeze(snapshot),
    )


def _prior_file_metadata():
    current = build_prior_study_baseline(REPO_ROOT)
    stored = read_baseline_metadata(BASELINE_PATH, repository_root=REPO_ROOT)
    return current["files"], stored["files"]


class Study3bParityTests(unittest.TestCase):
    def test_all_public_records_drive_request_contract_and_hydration(self) -> None:
        with _provider_free_tripwires() as calls:
            for scene_id in study3_protocol.SCENE_ORDER:
                with self.subTest(scene_id=scene_id):
                    inventory = load_scene_inventory(scene_id)
                    with self.assertRaises(FrozenInstanceError):
                        inventory.inventory_sha256 = "0" * 64
                    with self.assertRaises(TypeError):
                        inventory.source_binding["expected_bundle_sha256"] = "0" * 64
                    with self.assertRaises(FactInventoryError):
                        replace(inventory, inventory_sha256="0" * 64).to_public_envelope()
                    request = study3b_request.build_request(scene_id)
                    study3b_request.audit_request_parity(scene_id, request)
                    envelope = _public_envelope(request)
                    expected_records = [
                        record.to_request_record()
                        for record in inventory.request_public_facts
                    ]
                    self.assertEqual(
                        envelope["public_fact_records"], expected_records
                    )
                    self.assertEqual(
                        [row["fact_id"] for row in envelope["public_fact_records"]],
                        list(inventory.public_fact_ids),
                    )
                    self.assertEqual(
                        envelope["claim_reference_ids"],
                        list(inventory.claim_reference_ids),
                    )
                    self.assertEqual(
                        envelope["inventory_sha256"], inventory.inventory_sha256
                    )
                    self.assertEqual(
                        _request_section(request, "public_base_fact_ids"),
                        list(inventory.claim_reference_ids),
                    )
                    schema = _request_section(request, "output_schema")
                    self.assertEqual(
                        schema["$defs"]["claim"]["properties"]["fact_id"]["anyOf"][0]["enum"],
                        list(inventory.claim_reference_ids),
                    )
                    self.assertEqual(
                        schema["$defs"]["fact_ref_value"]["properties"]["fact_id"]["anyOf"][0]["enum"],
                        list(inventory.claim_reference_ids),
                    )

                    # Full source and expected bundles are host-owned, not request payload.
                    source_packet = _request_section(request, "source_packet")
                    expected_bundle = _request_section(request, "expected_bundle")
                    self.assertEqual(
                        source_packet["source_packet_ref"],
                        inventory.source_binding["input_refs"]["source_packet"],
                    )
                    self.assertEqual(
                        expected_bundle["expected_bundle_ref"],
                        inventory.source_binding["input_refs"]["expected_bundle"],
                    )
                    self.assertEqual(
                        expected_bundle["inventory_sha256"],
                        inventory.inventory_sha256,
                    )
                    user_message = request["messages"][1]["content"]
                    for record in inventory.records:
                        if record.audience != PUBLIC_AUDIENCE:
                            self.assertNotIn(record.fact_id, user_message)

                    materializable = [
                        record
                        for record in inventory.request_public_facts
                        if record.claim_reference_eligible
                    ]
                    non_materializable = [
                        record
                        for record in inventory.request_public_facts
                        if not record.claim_reference_eligible
                    ]
                    self.assertTrue(materializable)
                    self.assertTrue(non_materializable)
                    delta = _valid_delta(request, inventory.claim_reference_ids)
                    encoded = _encoded_delta(delta)
                    validated = study3b_contract.validate_delta_payload(
                        encoded, scene_id=scene_id
                    )
                    self.assertEqual(
                        tuple(
                            claim["fact_id"]
                            for group in validated["claims"]
                            for claim in group["items"]
                        ),
                        inventory.claim_reference_ids,
                    )

                    hydrated = study3b_hydration.hydrate_delta_output(
                        encoded, scene_id=scene_id
                    )
                    study3b_hydration.audit_hydrated_inventory_parity(
                        scene_id,
                        hydrated,
                        inventory=inventory,
                        expected_authored_fact_ids=_expected_authored_fact_ids(
                            encoded, scene_id, inventory
                        ),
                    )
                    audience_rows = hydrated["fixture"]["extension_seams"]["audience_knowledge"]
                    source_fixture_ids = {
                        row.get("id")
                        for row in hydrated["fixture"]["facts"]
                        if row.get("id") in {record.fact_id for record in inventory.records}
                    }
                    self.assertEqual(source_fixture_ids, set(inventory.claim_reference_ids))
                    self.assertEqual(
                        hydrated["fixture"]["extension_seams"]["unknown_metrics"],
                        [inventory_module._to_plain(row) for row in inventory.protected_unknowns],
                    )
                    for record in inventory.records:
                        matching_audience_rows = [
                            row for row in audience_rows if row["fact_id"] == record.fact_id
                        ]
                        self.assertEqual(len(matching_audience_rows), 1)
                        self.assertEqual(matching_audience_rows[0]["audience"], record.audience)
                        self.assertEqual(matching_audience_rows[0]["status"], record.status)
                        if not record.claim_reference_eligible:
                            self.assertNotIn(record.fact_id, source_fixture_ids)
                    for record in inventory.request_public_facts:
                        matching = [
                            row for row in audience_rows
                            if row["fact_id"] == record.fact_id
                        ]
                        self.assertEqual(
                            matching, [record.to_audience_knowledge_record()]
                        )
                        source_fixture = next(
                            (
                                row for row in hydrated["fixture"]["facts"]
                                if row.get("id") == record.fact_id
                            ),
                            None,
                        )
                        if record.claim_reference_eligible:
                            self.assertEqual(
                                source_fixture,
                                record.to_fixture_source_fact(inventory.scene_node_id),
                            )
                        else:
                            self.assertIsNone(source_fixture)

                    rejected_delta = _encoded_delta(
                        _valid_delta(request, non_materializable[0].fact_id)
                    )
                    with self.assertRaises(ContractError) as rejected:
                        study3b_hydration.hydrate_delta_output(
                            rejected_delta, scene_id=scene_id
                        )
                    self.assertEqual(
                        rejected.exception.code, "STUDY3B_FACT_NOT_MATERIALIZABLE"
                    )
            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})

    def test_protected_mutations_fail_closed_for_all_scenes(self) -> None:
        before, recorded_before = _prior_file_metadata()
        self.assertTrue(before == recorded_before, "prior-study baseline drifted before test")

        with _provider_free_tripwires() as calls:
            for scene_id in study3_protocol.SCENE_ORDER:
                with self.subTest(scene_id=scene_id):
                    inventory = load_scene_inventory(scene_id)
                    request = study3b_request.build_request(scene_id)
                    guarded = next(
                        record
                        for record in inventory.records
                        if not record.is_request_public and type(record.value) is str
                    )

                    promoted_record = replace(guarded, audience=PUBLIC_AUDIENCE)
                    promoted_records = tuple(
                        promoted_record if row.fact_id == guarded.fact_id else row
                        for row in inventory.records
                    )
                    forged_inventory = _rehash_inventory(
                        inventory, records=promoted_records
                    )
                    with self.assertRaises(FactInventoryError):
                        forged_inventory.to_public_envelope()
                    with self.assertRaises(study3b_request.RequestParityError):
                        study3b_request.audit_request_parity(
                            scene_id, request, inventory=forged_inventory
                        )
                    with self.assertRaises(ContractError):
                        study3b_contract.validate_delta_payload(
                            _encoded_delta(
                                _valid_delta(request, inventory.claim_reference_ids[0])
                            ),
                            scene_id=scene_id,
                            inventory=forged_inventory,
                        )

                    promoted_envelope = _public_envelope(request)
                    promoted_public_record = guarded.to_request_record()
                    promoted_public_record["audience"] = PUBLIC_AUDIENCE
                    promoted_envelope["public_fact_records"].append(
                        promoted_public_record
                    )
                    promoted_envelope["claim_reference_ids"].append(guarded.fact_id)
                    with self.assertRaises(study3b_request.RequestParityError):
                        study3b_request.audit_request_parity(
                            scene_id,
                            _replace_public_envelope(request, promoted_envelope),
                        )

                    altered_unknowns = [
                        inventory_module._to_plain(row)
                        for row in inventory.protected_unknowns
                    ]
                    altered_unknowns[0]["status"] = "known"
                    forged_unknown_inventory = _rehash_inventory(
                        inventory, protected_unknowns=altered_unknowns
                    )
                    with self.assertRaises(study3b_request.RequestParityError):
                        study3b_request.audit_request_parity(
                            scene_id, request, inventory=forged_unknown_inventory
                        )

                    composite = next(
                        record
                        for record in inventory.request_public_facts
                        if type(record.value) is tuple
                    )
                    changed_value = inventory_module._to_plain(composite.value)
                    changed_value.append("SYNTHETIC_INVENTORY_LIST_MUTATION")
                    changed_record = replace(
                        composite,
                        value=inventory_module._freeze(changed_value),
                    )
                    changed_records = tuple(
                        changed_record if row.fact_id == composite.fact_id else row
                        for row in inventory.records
                    )
                    forged_nested_inventory = _rehash_inventory(
                        inventory, records=changed_records
                    )
                    with self.assertRaises(study3b_request.RequestParityError):
                        study3b_request.audit_request_parity(
                            scene_id, request, inventory=forged_nested_inventory
                        )

                    nested_envelope = _public_envelope(request)
                    nested_request_record = next(
                        row
                        for row in nested_envelope["public_fact_records"]
                        if row["fact_id"] == composite.fact_id
                    )
                    nested_request_record["value"].append(
                        "SYNTHETIC_REQUEST_LIST_MUTATION"
                    )
                    with self.assertRaises(study3b_request.RequestParityError):
                        study3b_request.audit_request_parity(
                            scene_id,
                            _replace_public_envelope(request, nested_envelope),
                        )

                    valid_delta = _valid_delta(request, inventory.claim_reference_ids)
                    valid_bytes = _encoded_delta(valid_delta)
                    hydrated = study3b_hydration.hydrate_delta_output(
                        valid_bytes, scene_id=scene_id
                    )
                    for unknown_index, _unknown in enumerate(
                        inventory.protected_unknowns
                    ):
                        changed = deepcopy(hydrated)
                        changed["fixture"]["extension_seams"]["unknown_metrics"][
                            unknown_index
                        ]["status"] = "known"
                        with self.subTest(
                            scene_id=scene_id, unknown_index=unknown_index
                        ):
                            with self.assertRaises(ContractError):
                                study3b_hydration.audit_hydrated_inventory_parity(
                                    scene_id,
                                    changed,
                                    inventory=inventory,
                                    expected_authored_fact_ids=_expected_authored_fact_ids(
                                        valid_bytes, scene_id, inventory
                                    ),
                                )

                    protected_state_mutations = (
                        (
                            "scene_orientation",
                            lambda value: value["fixture"]["scene"]["orientation"].update(
                                {"status": "known"}
                            ),
                        ),
                        (
                            "arrival_orientation",
                            lambda value: value["arrival"]["orientation"].update(
                                {"frame": "synthetic-frame"}
                            ),
                        ),
                        (
                            "cue_state",
                            lambda value: value["arrival"]["cue_states"][0].update(
                                {"status": "known"}
                            ),
                        ),
                        (
                            "next_section",
                            lambda value: value["arrival"]["next_section"].update(
                                {"status": "known"}
                            ),
                        ),
                        (
                            "audience_promotion",
                            lambda value: next(
                                row
                                for row in value["fixture"]["extension_seams"][
                                    "audience_knowledge"
                                ]
                                if row["fact_id"] == guarded.fact_id
                            ).update({"audience": PUBLIC_AUDIENCE}),
                        ),
                        (
                            "source_provenance",
                            lambda value: value["arrival"]["source_provenance"].update(
                                {"sha256": "f" * 64}
                            ),
                        ),
                    )
                    for label, mutate in protected_state_mutations:
                        changed = deepcopy(hydrated)
                        mutate(changed)
                        with self.subTest(scene_id=scene_id, mutation=label):
                            with self.assertRaises(ContractError):
                                study3b_hydration.audit_hydrated_inventory_parity(
                                    scene_id,
                                    changed,
                                    inventory=inventory,
                                    expected_authored_fact_ids=_expected_authored_fact_ids(
                                        valid_bytes, scene_id, inventory
                                    ),
                                )

                    guarded_projection = {
                        "id": guarded.fact_id,
                        "subject_id": inventory.scene_node_id,
                        "predicate": "source_record",
                        "object_id": inventory.scene_node_id,
                        "status": "known",
                        "value": inventory_module._to_plain(guarded.value),
                        "provenance": {
                            "class": "source_extracted",
                            "source_refs": [guarded.provenance["source_ref"]],
                        },
                    }
                    changed = deepcopy(hydrated)
                    changed["fixture"]["facts"].append(guarded_projection)
                    with self.assertRaises(ContractError):
                        study3b_hydration.audit_hydrated_inventory_parity(
                            scene_id,
                            changed,
                            inventory=inventory,
                            expected_authored_fact_ids=_expected_authored_fact_ids(
                                valid_bytes, scene_id, inventory
                            ),
                        )

                    composite = next(
                        record
                        for record in inventory.request_public_facts
                        if type(record.value) is tuple
                    )
                    changed = deepcopy(hydrated)
                    composite_row = next(
                        row
                        for row in changed["fixture"]["extension_seams"][
                            "audience_knowledge"
                        ]
                        if row["fact_id"] == composite.fact_id
                    )
                    composite_row["value"].append("SYNTHETIC_NESTED_MUTATION")
                    with self.assertRaises(ContractError):
                        study3b_hydration.audit_hydrated_inventory_parity(
                            scene_id,
                            changed,
                            inventory=inventory,
                            expected_authored_fact_ids=_expected_authored_fact_ids(
                                valid_bytes, scene_id, inventory
                            ),
                        )

                    guarded_claim_delta = _valid_delta(request, guarded.fact_id)
                    with patch.object(
                        study2_hydration,
                        "_hydrate_validated_delta",
                        side_effect=AssertionError("rejected delta reached hydration"),
                    ):
                        with self.assertRaises(ContractError):
                            study3b_hydration.hydrate_delta_output(
                                _encoded_delta(guarded_claim_delta),
                                scene_id=scene_id,
                            )

                    overwritten_delta = _valid_delta(
                        request, inventory.claim_reference_ids[0]
                    )
                    overwritten_delta["fixture_deltas"]["facts"][0][
                        "fact_id"
                    ] = inventory.records[0].fact_id
                    with patch.object(
                        study2_hydration,
                        "_hydrate_validated_delta",
                        side_effect=AssertionError("rejected delta reached hydration"),
                    ):
                        with self.assertRaises(ContractError):
                            study3b_hydration.hydrate_delta_output(
                                _encoded_delta(overwritten_delta), scene_id=scene_id
                            )

                    topology = _request_section(request, "topology_binding")
                    inferred_unknown_delta = _valid_delta(
                        request, inventory.claim_reference_ids[0]
                    )
                    inferred_unknown_delta["fixture_deltas"]["facts"].append(
                        {
                            "fact_id": inventory.module_id
                            + ":fact:study3-authored:synthetic-unknown-inference",
                            "subject_id": topology["stage_role_candidates"]["approach"][0],
                            "predicate": "light_gradient",
                            "object_id": topology["stage_role_candidates"]["approach"][0],
                            "value": "SYNTHETIC_INFERRED_UNKNOWN",
                        }
                    )
                    with patch.object(
                        study2_hydration,
                        "_hydrate_validated_delta",
                        side_effect=AssertionError("rejected delta reached hydration"),
                    ):
                        with self.assertRaises(ContractError):
                            study3b_hydration.hydrate_delta_output(
                                _encoded_delta(inferred_unknown_delta),
                                scene_id=scene_id,
                            )

                    altered_binding_delta = _valid_delta(
                        request, inventory.claim_reference_ids[0]
                    )
                    altered_binding_delta["input_refs"]["source_packet"][
                        "sha256"
                    ] = "f" * 64
                    with patch.object(
                        study2_hydration,
                        "_hydrate_validated_delta",
                        side_effect=AssertionError("rejected delta reached hydration"),
                    ):
                        with self.assertRaises(ContractError):
                            study3b_hydration.hydrate_delta_output(
                                _encoded_delta(altered_binding_delta),
                                scene_id=scene_id,
                            )

            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})

        after, recorded_after = _prior_file_metadata()
        self.assertTrue(after == recorded_after, "prior-study files changed during test")
        self.assertTrue(recorded_before == recorded_after, "prior-study baseline changed")

    def test_hydration_audit_rejects_unbound_authored_facts(self) -> None:
        with _provider_free_tripwires() as calls:
            for scene_id in study3_protocol.SCENE_ORDER:
                with self.subTest(scene_id=scene_id):
                    inventory = load_scene_inventory(scene_id)
                    request = study3b_request.build_request(scene_id)
                    delta = _valid_delta(request, inventory.claim_reference_ids[0])
                    encoded_delta = _encoded_delta(delta)
                    hydrated = study3b_hydration.hydrate_delta_output(
                        encoded_delta, scene_id=scene_id
                    )
                    expected_authored_fact_ids = _expected_authored_fact_ids(
                        encoded_delta, scene_id, inventory
                    )

                    with self.assertRaises(TypeError):
                        study3b_hydration.audit_hydrated_inventory_parity(
                            scene_id, hydrated, inventory=inventory
                        )

                    no_authored_facts = deepcopy(hydrated)
                    source_ids = {record.fact_id for record in inventory.records}
                    no_authored_facts["fixture"]["facts"] = [
                        fact
                        for fact in no_authored_facts["fixture"]["facts"]
                        if fact["id"] in source_ids
                    ]
                    study3b_hydration.audit_hydrated_inventory_parity(
                        scene_id,
                        no_authored_facts,
                        inventory=inventory,
                        expected_authored_fact_ids=frozenset(),
                    )

                    forged_facts = (
                        {
                            "id": study2_hydration._legacy_authored_fact_id(
                                inventory.module_id,
                                inventory.module_id + ":fact:synthetic-light-gradient",
                            ),
                            "subject_id": inventory.scene_node_id,
                            "predicate": "light_gradient",
                            "object_id": inventory.scene_node_id,
                            "status": "known",
                            "value": "SYNTHETIC_INFERRED_LIGHT",
                            "provenance": {
                                "class": "builder_authored",
                                "source_refs": [],
                            },
                        },
                        {
                            "id": study2_hydration._legacy_authored_fact_id(
                                inventory.module_id,
                                inventory.module_id + ":fact:synthetic-provenance-claim",
                            ),
                            "subject_id": inventory.scene_node_id,
                            "predicate": "guarded_source_record",
                            "object_id": inventory.scene_node_id,
                            "status": "known",
                            "value": "SYNTHETIC_CLAIMED_VALUE",
                            "provenance": {
                                "class": "builder_authored",
                                "source_refs": [
                                    "claimed:canonical-source-provenance"
                                ],
                            },
                        },
                    )
                    for forged_fact in forged_facts:
                        changed = deepcopy(hydrated)
                        changed["fixture"]["facts"].append(forged_fact)
                        with self.subTest(
                            scene_id=scene_id,
                            forged_fact=forged_fact["predicate"],
                        ):
                            with self.assertRaises(ContractError):
                                study3b_hydration.audit_hydrated_inventory_parity(
                                    scene_id,
                                    changed,
                                    inventory=inventory,
                                    expected_authored_fact_ids=expected_authored_fact_ids,
                                )

            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})

    def test_synthetic_nested_fact_survives_audience_hydration_only(self) -> None:
        with _provider_free_tripwires() as calls:
            scene_id = study3_protocol.SCENE_ORDER[0]
            (
                inventory,
                canonical,
                composite_fact_id,
                nested_value,
            ) = _synthetic_nested_inventory_and_canonical(scene_id)
            composite_record = next(
                record
                for record in inventory.request_public_facts
                if record.fact_id == composite_fact_id
            )
            self.assertFalse(composite_record.fixture_materializable)
            self.assertFalse(composite_record.claim_reference_eligible)
            self.assertIsNone(
                composite_record.to_fixture_source_fact(inventory.scene_node_id)
            )
            self.assertNotIn(composite_fact_id, inventory.claim_reference_ids)

            with ExitStack() as stack:
                stack.enter_context(
                    patch.object(
                        inventory_module,
                        "load_scene_inventory",
                        return_value=inventory,
                    )
                )
                stack.enter_context(
                    patch.object(
                        study3b_request,
                        "load_scene_inventory",
                        return_value=inventory,
                    )
                )
                stack.enter_context(
                    patch.object(
                        study3b_contract,
                        "load_scene_inventory",
                        return_value=inventory,
                    )
                )
                stack.enter_context(
                    patch.object(
                        study3b_hydration,
                        "load_scene_inventory",
                        return_value=inventory,
                    )
                )
                stack.enter_context(
                    patch.object(
                        study2_hydration,
                        "_load_canonical_inputs",
                        return_value=canonical,
                    )
                )

                request = study3b_request.build_request(scene_id)
                study3b_request.audit_request_parity(
                    scene_id, request, inventory=inventory
                )
                envelope = _public_envelope(request)
                request_record = next(
                    row
                    for row in envelope["public_fact_records"]
                    if row["fact_id"] == composite_fact_id
                )
                self.assertEqual(request_record["value"], nested_value)
                self.assertNotIn(
                    composite_fact_id, envelope["claim_reference_ids"]
                )

                schema = _request_section(request, "output_schema")
                valid_fact_id = inventory.claim_reference_ids[0]
                valid_delta = _valid_delta(request, valid_fact_id)
                composite_delta = _valid_delta(request, composite_fact_id)
                validator = Draft202012Validator(schema)
                self.assertTrue(validator.is_valid(valid_delta))
                self.assertFalse(validator.is_valid(composite_delta))

                with self.assertRaises(ContractError) as rejected:
                    study3b_contract.validate_delta_payload(
                        _encoded_delta(composite_delta), scene_id=scene_id
                    )
                self.assertEqual(
                    rejected.exception.code, "STUDY3B_FACT_NOT_MATERIALIZABLE"
                )

                hydrated = study3b_hydration.hydrate_delta_output(
                    _encoded_delta(valid_delta), scene_id=scene_id
                )
                study3b_hydration.audit_hydrated_inventory_parity(
                    scene_id,
                    hydrated,
                    inventory=inventory,
                    expected_authored_fact_ids=_expected_authored_fact_ids(
                        _encoded_delta(valid_delta), scene_id, inventory
                    ),
                )
                audience_row = next(
                    row
                    for row in hydrated["fixture"]["extension_seams"]["audience_knowledge"]
                    if row["fact_id"] == composite_fact_id
                )
                self.assertEqual(audience_row["value"], nested_value)
                fixture_ids = {
                    row.get("id") for row in hydrated["fixture"]["facts"]
                }
                self.assertNotIn(composite_fact_id, fixture_ids)

            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})

    def test_request_rejects_missing_extra_and_changed_complete_records(self) -> None:
        with _provider_free_tripwires() as calls:
            for scene_id in study3_protocol.SCENE_ORDER:
                request = study3b_request.build_request(scene_id)
                original = _public_envelope(request)
                first_id = original["public_fact_records"][0]["fact_id"]
                mutations = []

                missing = deepcopy(original)
                missing["public_fact_records"].pop()
                mutations.append(("missing_public_id", missing))

                extra = deepcopy(original)
                extra_record = deepcopy(extra["public_fact_records"][0])
                extra_record["fact_id"] = "synthetic:extra-public-fact"
                extra["public_fact_records"].append(extra_record)
                mutations.append(("extra_public_id", extra))

                missing_claim_ref = deepcopy(original)
                missing_claim_ref["claim_reference_ids"].pop()
                mutations.append(("missing_claim_reference_id", missing_claim_ref))

                extra_claim_ref = deepcopy(original)
                extra_claim_ref["claim_reference_ids"].append("synthetic:extra-claim-ref")
                mutations.append(("extra_claim_reference_id", extra_claim_ref))

                for field, mutator in (
                    ("identity", lambda row: row["identity"].update({"scene_id": "synthetic:scene"})),
                    ("audience", lambda row: row.update({"audience": "gm_guarded"})),
                    ("status", lambda row: row.update({"status": "unknown"})),
                    ("value", lambda row: row.update({"value": "SYNTHETIC_VALUE_CHANGE"})),
                    ("provenance", lambda row: row["provenance"].update({"source_pointer": "/synthetic"})),
                    (
                        "source_binding",
                        lambda row: row["source_binding"].update(
                            {"source_packet_sha256": "f" * 64}
                        ),
                    ),
                ):
                    changed = deepcopy(original)
                    row = changed["public_fact_records"][0]
                    mutator(row)
                    mutations.append((field, changed))

                for label, mutated_envelope in mutations:
                    with self.subTest(scene_id=scene_id, mutation=label, fact_id=first_id):
                        mutated_request = _replace_public_envelope(
                            request, mutated_envelope
                        )
                        with self.assertRaises(study3b_request.RequestParityError):
                            study3b_request.audit_request_parity(
                                scene_id, mutated_request
                            )
            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})

    def test_hydration_rejects_missing_extra_and_changed_complete_records(self) -> None:
        with _provider_free_tripwires() as calls:
            for scene_id in study3_protocol.SCENE_ORDER:
                inventory = load_scene_inventory(scene_id)
                request = study3b_request.build_request(scene_id)
                delta = _encoded_delta(
                    _valid_delta(request, inventory.claim_reference_ids[0])
                )
                hydrated = study3b_hydration.hydrate_delta_output(
                    delta, scene_id=scene_id
                )
                public_record = inventory.request_public_facts[0]
                public_index = next(
                    index
                    for index, row in enumerate(
                        hydrated["fixture"]["extension_seams"]["audience_knowledge"]
                    )
                    if row["fact_id"] == public_record.fact_id
                )
                mutations = []

                changed = deepcopy(hydrated)
                changed["scene_id"] = "synthetic:changed-scene"
                mutations.append(("identity", changed))

                for field, value in (
                    ("fact_id", "synthetic:changed-fact-id"),
                    ("audience", "gm_guarded"),
                    ("status", "unknown"),
                    ("value", "SYNTHETIC_VALUE_CHANGE"),
                    ("source_pointer", "/synthetic"),
                    ("source_ref", "synthetic:source-ref"),
                ):
                    changed = deepcopy(hydrated)
                    changed["fixture"]["extension_seams"]["audience_knowledge"][public_index][field] = value
                    mutations.append((field, changed))

                changed = deepcopy(hydrated)
                changed["fixture"]["extension_seams"]["audience_knowledge"].pop(public_index)
                mutations.append(("missing_public_id", changed))

                changed = deepcopy(hydrated)
                extra_row = deepcopy(
                    changed["fixture"]["extension_seams"]["audience_knowledge"][public_index]
                )
                extra_row["fact_id"] = "synthetic:extra-fact-id"
                changed["fixture"]["extension_seams"]["audience_knowledge"].append(extra_row)
                mutations.append(("extra_public_id", changed))

                changed = deepcopy(hydrated)
                projected = next(
                    row for row in changed["fixture"]["facts"]
                    if row.get("id") == inventory.claim_reference_ids[0]
                )
                projected["value"] = "SYNTHETIC_FIXTURE_VALUE_CHANGE"
                mutations.append(("fixture_value", changed))

                changed = deepcopy(hydrated)
                projected = next(
                    row for row in changed["fixture"]["facts"]
                    if row.get("id") == inventory.claim_reference_ids[0]
                )
                projected["provenance"]["source_refs"] = ["synthetic:source-ref"]
                mutations.append(("fixture_provenance", changed))

                changed = deepcopy(hydrated)
                changed["arrival"]["source_provenance"]["sha256"] = "f" * 64
                mutations.append(("source_binding", changed))

                for label, mutated in mutations:
                    with self.subTest(scene_id=scene_id, mutation=label):
                        with self.assertRaises(ContractError):
                            study3b_hydration.audit_hydrated_inventory_parity(
                                scene_id,
                                mutated,
                                inventory=inventory,
                                expected_authored_fact_ids=_expected_authored_fact_ids(
                                    delta, scene_id, inventory
                                ),
                            )
            self.assertEqual(calls, {"network": 0, "credential": 0, "provider_import": 0})


if __name__ == "__main__":
    unittest.main()
