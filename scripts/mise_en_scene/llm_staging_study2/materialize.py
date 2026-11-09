# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Materialize the provider-free Study 2 review packet; --check is read-only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from .sizing import approximate_tokens, cost_estimate, json_bytes, sizing_proposal

ROOT = Path(__file__).resolve().parents[3]
BASE = "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation"
P = f"{BASE}/llm-staging-study2/protocol"
S1 = f"{BASE}/llm-staging-protocol"
RAW = Path("tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging/availability-check/model-listing.json")
RAW_HASH = "d94d8370997bb6a32c8265d0c5368d98c121355ebed0c51698539d81e32bdc13"
RAW_SIZE = 829400
SCENES = [
    "into_the_deepvault:scene:ha003-i02",
    "into_the_deepvault:scene:sd005-i03",
    "xhalruuns_masquerade:scene:tsu001-ao02",
]
REF_NAMES = [
    "into_the_deepvault__scene__ha003-i02.json",
    "into_the_deepvault__scene__sd005-i03.json",
    "xhalruuns_masquerade__scene__tsu001-ao02.json",
]
ARTIFACT_ROLES = {
    "protocol": f"{P}/protocol.md", "input_bindings": f"{P}/input-bindings.json",
    "output_schema": f"{P}/output-contract.schema.json", "system_prompt": f"{P}/system-prompt.txt",
    "task_prompt": f"{P}/task-prompt.txt", "generation_config": f"{P}/generation-config.json",
    "availability_attestation": f"{S1}/availability-check.json",
}


def read(relative: str) -> bytes:
    return (ROOT / relative).read_bytes()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json_bytes(value)


def generate(check: bool = False) -> dict[str, bytes]:
    listing_path = ROOT / RAW
    listing_exists = listing_path.exists()
    listing = listing_path.read_bytes() if listing_exists else b""
    if listing_exists:
        if len(listing) != RAW_SIZE or digest(listing) != RAW_HASH:
            raise ValueError("UNPRICED/BLOCKED: historical raw listing size/hash mismatch")
        listing_data = json.loads(listing)
        match = next(row for row in listing_data["data"] if row.get("id") == "openai/gpt-6-luna")
        rates = match["pricing"]
        prompt_rate, completion_rate = rates["prompt"], rates["completion"]
        listing_size = len(listing)
    elif check:
        prior = json.loads(read(f"{P}/sizing-report.json"))
        provenance = prior["cost"]
        if provenance.get("listing_sha256") != RAW_HASH or provenance.get("listing_bytes") != RAW_SIZE:
            raise ValueError("UNPRICED/BLOCKED: no verified stored listing provenance")
        prompt_rate = provenance["prompt_usd_per_token"]
        completion_rate = provenance["completion_usd_per_token"]
        match = {"id": "openai/gpt-6-luna"}
        listing_size = RAW_SIZE
    else:
        raise ValueError("UNPRICED/BLOCKED: verified historical raw listing unavailable")

    system_prompt = """You are the NeverEndingQuest initial-scene Builder. Return only one JSON object conforming to the supplied Study 2 delta schema. This is a new authored delta, not a full fixture: do not echo the source packet, expected bundle, or topology. The canonical inputs and gate own all base facts, topology, identities, and unknowns. Use only the three supplied frozen inputs for this scene; reject/avoid any unknown key or unsupported identity. Add only permitted authored fixture deltas, stage-role bindings, claims, arrival prose, and exact input references. Do not invent or infer compass direction, door, access, visibility, traversal, distance, scale, sensory metrics or gradients, mechanics, cues, next-section, or any other unspecified fact. Preserve every unprovided/unknown state as unknown. Exclude private, guarded, schematic-only, and source-reference-only content from public claims and prose. Do not describe prior PCs, relocate fixed facts, assert player choices or outcomes, or write a prose-only factual claim: bind checkable spans to their supporting fact IDs. Provide exactly three natural, vivid arrival segments in approach, threshold, focal order. Do not mention staging, schemas, prompts, or these hand-assembled tooling references. No repair, continuation, retries, or extra output is allowed."""
    task = """Prepare a delta for exactly {{SCENE_ID}} using the frozen binding references below. These are provided context, not response payload to repeat.\n\nINPUT REFERENCES (authoritative; copy exact values only):\n{{INPUT_REFS_JSON}}\n\nSOURCE PACKET (read-only context):\n{{SOURCE_PACKET_JSON}}\n\nEXPECTED BUNDLE (read-only gate context; preserve all unknowns):\n{{EXPECTED_BUNDLE_JSON}}\n\nOUTPUT SCHEMA (return one object matching it exactly):\n{{OUTPUT_SCHEMA_JSON}}\n\nReturn only the permitted delta. Do not copy canonical inputs into the response.\n"""
    protocol_bytes = read(f"{P}/protocol.md")
    bindings_bytes = read(f"{P}/input-bindings.json")
    bindings = json.loads(read(f"{P}/input-bindings.json"))
    schema = read(f"{P}/output-contract.schema.json")
    attestation = read(f"{S1}/availability-check.json")
    ref_bytes = [read(f"{P}/references/{name}") for name in REF_NAMES]
    refs = [json.loads(data) for data in ref_bytes]
    config_template = {
        "schema": "neq.llm_staging_study2_generation_config.v1",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "model_id": "openai/gpt-6-luna", "temperature": 1.0, "top_p": 1.0,
        "frequency_penalty": 0.0, "presence_penalty": 0.0,
        "max_tokens": 0, "timeout_seconds": 0, "stream": False,
        "response_format": {"type": "json_object"}, "tools": [], "tool_choice": "none",
        "provider": {"allow_fallbacks": False},
    }
    estimates: dict[str, int] = {}
    input_counts: dict[str, int] = {}
    reference_byte_counts: dict[str, int] = {}
    reference_hashes: dict[str, str] = {}
    for scene_id, raw_reference, ref in zip(SCENES, ref_bytes, refs):
        row = next(item for item in bindings["scenes"] if item["scene_id"] == scene_id)
        source = read(row["source_packet"]["id"]).decode("utf-8")
        expected = read(row["expected_bundle"]["id"]).decode("utf-8")
        refs_json = canonical(ref["input_refs"]).decode("utf-8")
        rendered = task
        for key, value in {
            "{{SCENE_ID}}": scene_id, "{{INPUT_REFS_JSON}}": refs_json,
            "{{SOURCE_PACKET_JSON}}": source, "{{EXPECTED_BUNDLE_JSON}}": expected,
            "{{OUTPUT_SCHEMA_JSON}}": schema.decode("utf-8"),
        }.items():
            if rendered.count(key) != 1:
                raise ValueError("task prompt template placeholder mismatch")
            rendered = rendered.replace(key, value)
        estimates[scene_id] = (len(raw_reference) + 2) // 3
        reference_byte_counts[scene_id] = len(raw_reference)
        reference_hashes[scene_id] = digest(raw_reference)
        input_counts[scene_id] = approximate_tokens(system_prompt) + approximate_tokens(rendered)
    proposal = sizing_proposal(estimates)
    config_template["max_tokens"] = proposal["max_tokens"]
    config_template["timeout_seconds"] = proposal["timeout_seconds"]
    config = canonical(config_template) + b"\n"
    # Cost uses the configured completion cap as a conservative per-scene output envelope.
    costs = {
        scene: cost_estimate(input_counts[scene], proposal["max_tokens"], prompt_rate, completion_rate)
        for scene in SCENES
    }
    total = sum(costs.values())
    attestation_hash = digest(attestation)
    artifacts = {role: {"path": path, "sha256": digest(config if role == "generation_config" else (
        protocol_bytes if role == "protocol" else
        bindings_bytes if role == "input_bindings" else
        schema if role == "output_schema" else
        system_prompt.encode("utf-8") if role == "system_prompt" else
        task.encode("utf-8") if role == "task_prompt" else attestation))} for role, path in ARTIFACT_ROLES.items()}
    manifest = {
        "schema": "neq.llm_staging_study2_manifest.v1", "study_id": "mise-en-scene-study2-20261109",
        "protocol_version": "neq.llm_staging_study2_delta.v1", "status": "FROZEN_FOR_REVIEW",
        "scene_order": SCENES, "attempt_cap": 3,
        "endpoint": config_template["endpoint"], "model_id": config_template["model_id"],
        "availability": {"raw_listing_path": RAW.as_posix(), "raw_listing_sha256": RAW_HASH,
                         "attestation_path": f"{S1}/availability-check.json", "attestation_sha256": attestation_hash},
        "artifacts": artifacts,
        "scenes": [{"scene_id": sid,
                    "source_packet": {"path": row["source_packet"]["id"], "sha256": row["source_packet"]["sha256"]},
                    "expected_bundle": {"path": row["expected_bundle"]["id"], "sha256": row["expected_bundle"]["sha256"]}}
                   for sid, row in zip(SCENES, bindings["scenes"])],
    }
    report = {
        "schema": "neq.llm_staging_study2_sizing_report.v1", "status": "ESTIMATE",
        "token_method": "APPROXIMATE: ceil(exact hand-reference UTF-8 file bytes / 3) for L; ceil(UTF-8 bytes / 3) per actual system/user message content for input. Heuristic, not a GPT tokenizer; JSON message framing overhead is not tokenized separately.",
        "scenes": {sid: {"reference_file": f"{P}/references/{REF_NAMES[index]}",
                         "reference_utf8_bytes": reference_byte_counts[sid], "reference_sha256": reference_hashes[sid],
                         "reference_estimated_tokens": estimates[sid], "request_input_estimated_tokens": input_counts[sid],
                         "output_tokens_upper_envelope": proposal["max_tokens"], "cost_usd": str(costs[sid])}
                   for index, sid in enumerate(SCENES)},
        **proposal,
        "cost": {"status": "ESTIMATE", "total_usd": str(total), "prompt_usd_per_token": prompt_rate,
                  "completion_usd_per_token": completion_rate,
                  "rate_source": "historical listing pricing fields bound by the confirmed attestation; check-mode stored provenance is not fresh availability confirmation",
                  "fresh_availability_confirmation": False,
                 "listing_path": RAW.as_posix(), "listing_bytes": listing_size, "listing_sha256": RAW_HASH,
                 "availability_attestation_path": f"{S1}/availability-check.json",
                 "availability_attestation_sha256": attestation_hash, "performed_utc": "2026-11-09T03:48:13Z",
                 "model_id": match["id"], "pricing_fields": ["pricing.prompt", "pricing.completion"]},
        "network_calls": 0, "provider_calls": 0,
    }
    outputs = {
        f"{P}/system-prompt.txt": system_prompt.encode("utf-8"),
        f"{P}/task-prompt.txt": task.encode("utf-8"),
        f"{P}/generation-config.json": config,
        f"{P}/staging-manifest.json": canonical(manifest) + b"\n",
        f"{P}/sizing-report.json": canonical(report) + b"\n",
        f"{P}/sizing-report.md": ("# Study 2 Offline Sizing and Step-(a) Packet\n\n" +
            f"Status: ESTIMATE. Largest reference estimate L={proposal['largest_estimate']}; " +
            f"proposed max_tokens={proposal['max_tokens']}, timeout_seconds={proposal['timeout_seconds']}.\n\n" +
            "Counts use the documented UTF-8-bytes/3 approximation, not a model tokenizer. " +
            "Cost is a three-scene estimate from the hash-verified historical listing; no calls were made.\n\n" +
            "Per-scene estimates (reference bytes; reference L; request input tokens; cost USD):\n" + "\n".join(
                f"- {sid}: {reference_byte_counts[sid]}; {estimates[sid]}; {input_counts[sid]}; {costs[sid]}" for sid in SCENES) +
            f"\n\nTotal ESTIMATE: ${total}. Rates: prompt {prompt_rate} USD/token; completion {completion_rate} USD/token.\n").encode("utf-8"),
    }
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        outputs = generate(check=args.check)
    except (OSError, ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    changed = []
    for relative, data in outputs.items():
        path = ROOT / relative
        if not path.exists() or path.read_bytes() != data:
            changed.append(relative)
            if not args.check:
                path.write_bytes(data)
    if args.check and changed:
        print("[FAIL] materialized files differ: " + ", ".join(changed))
        return 1
    print("[PASS] " + ("materialized files match" if args.check else "materialized review packet"))
    print("[PASS] files: " + ", ".join(outputs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
