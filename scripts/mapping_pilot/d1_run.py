# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Selection-gated D1 runner and owner audit exporter.

Run from the repository root with::

    .venv/bin/python -m scripts.mapping_pilot.d1_run --run-id <id>

``--max-invocations N`` sets a cumulative attempt ceiling for this run ID and
must be between 1 and 60; the durable cartographer ledger is always guarded by
the hard 60-invocation cap. ``--retry MODULE:LOCATION`` explicitly retries a
prior location and reserves another slot. ``--dry-run`` validates the frozen
selection, sources, and ledger without constructing a client or writing files.

The machine-readable cartographer audit remains JSON. A separate deterministic
CSV has one proposed claim per row for the owner sitting; CSV is used because
its rows can be filtered and rated directly in a spreadsheet. Its first line
states the precision >= 85% and zero-invented-exits threshold. Owner columns
are left blank by this tool.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, MutableSequence, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.mapping_pilot import cartographer
from scripts.mapping_pilot.d1_selection import MODULE_QUOTAS
from scripts.mapping_pilot.evidence import _reject_symlink_components, _validate_token


D1_ROOT = Path("tmp/router-rollout/mapping-pilot/d1")
OWNER_AUDIT_FILENAME = "d1_owner_audit.csv"
RUN_EVENTS_FILENAME = "d1_run_events.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")
_VISIBILITY_KEY = re.compile(r"(?:visibility|perceiv|sightline)", re.IGNORECASE)
_RECEIPT_FIELDS = frozenset(
    {
        "invocation_index",
        "prompt_sha256",
        "kind",
        "call_id",
        "attempt_id",
        "attempt_index",
        "task",
        "tier",
        "profile",
        "transport_retry",
        "retry_tier",
        "fallback",
        "transport_provider",
        "observed_upstream_provider",
        "requested_model",
        "resolved_model",
        "prompt_tokens",
        "cached_tokens",
        "completion_tokens",
        "usage_complete",
        "provider_reported_cost_usd",
        "cost_usd",
        "cost_provenance",
        "cost_complete",
        "error_type",
        "terminal_kind",
        "elapsed_ms",
    }
)
_CSV_FIELDS = (
    "claim_id",
    "attempt_number",
    "location_key",
    "module_slug",
    "location_id",
    "claim_category",
    "entity_id",
    "claim_field",
    "proposed_claim",
    "authored_source_reference",
    "authored_source_sha256",
    "owner_correct",
    "owner_incorrect",
    "owner_invented",
    "owner_notes",
)
_CSV_THRESHOLD = "# Threshold: precision >= 85% with zero invented exits"


class D1SelectionError(ValueError):
    """Raised before client construction when selection provenance is invalid."""


class D1CallCapError(RuntimeError):
    """Raised after the cap refusal has been durably recorded."""


def run_d1(
    run_id: str,
    *,
    max_invocations: int = cartographer.MAX_D1_CALLS,
    retry_locations: Sequence[str] = (),
    dry_run: bool = False,
    modules_dir: str | Path = "modules",
    client_factory: Callable[
        [MutableSequence[dict[str, Any]]], Callable[[str], Any]
    ]
    | None = None,
) -> dict[str, Any]:
    """Run or resume one selection-bound D1 experiment.

    ``modules_dir`` is an injectable read-only source root for provider-free
    tests; all generated artifacts always stay in the canonical D1 run folder.
    ``client_factory`` is a test seam. Production construction is lazy and goes
    only through ``live_client.create_live_client`` after preflight succeeds.
    """
    _validate_token(run_id, "run_id")
    if type(max_invocations) is not int or not 1 <= max_invocations <= cartographer.MAX_D1_CALLS:
        raise ValueError("max_invocations must be between 1 and 60")
    if not isinstance(retry_locations, Sequence) or isinstance(retry_locations, (str, bytes)):
        raise ValueError("retry_locations must be a sequence of location keys")
    retries = list(retry_locations)
    if len(set(retries)) != len(retries) or any(not isinstance(item, str) for item in retries):
        raise ValueError("retry locations must be unique text keys")

    run_relative = D1_ROOT / run_id
    run_directory = cartographer.PROJECT_ROOT / run_relative
    _reject_symlink_components(run_directory)
    if not run_directory.is_dir():
        raise D1SelectionError("D1 run directory with its selection record is required")
    selection_path = run_directory / "selection.json"
    _reject_symlink_components(selection_path)
    selection = _read_selection(selection_path, run_id)
    modules_root = _resolve_modules_root(modules_dir)
    selected_locations = _selected_locations(selection)
    _verify_selection_sources(selection, modules_root)

    sources = cartographer.extract_sources(
        modules_root,
        list(MODULE_QUOTAS),
        selected_locations,
    )
    _verify_extracted_sources(selection, sources)
    _verify_selection_sources(selection, modules_root)
    selection_digest = hashlib.sha256(selection_path.read_bytes()).hexdigest()
    ledger_relative, audit_relative = cartographer._validated_output_paths(run_relative)
    ledger_path = cartographer.PROJECT_ROOT / ledger_relative
    audit_path = cartographer.PROJECT_ROOT / audit_relative
    state, existing_audit = cartographer._load_run_state(
        ledger_path, audit_path, sources
    )
    attempts = state["attempts"]
    attempt_count = len(attempts)
    attempted_keys = {attempt["location_key"] for attempt in attempts}
    source_by_key = {
        "%s:%s" % (source["module_slug"], source["location_id"]): source
        for source in sources
    }

    for key in retries:
        if key not in source_by_key:
            raise ValueError("retry location is not selected: %s" % key)
        if key not in attempted_keys:
            raise ValueError("retry location has no prior attempt: %s" % key)

    if dry_run:
        return {
            "status": "dry_run",
            "run_id": run_id,
            "selection_sha256": selection_digest,
            "selection_fingerprint": state["selection_fingerprint"],
            "selected_location_count": len(sources),
            "invocation_count": attempt_count,
            "call_cap": cartographer.MAX_D1_CALLS,
        }

    ordered_work = [source_by_key[key] for key in retries]
    ordered_work.extend(
        source
        for source in sources
        if "%s:%s" % (source["module_slug"], source["location_id"])
        not in attempted_keys
    )
    effective_cap = min(max_invocations, cartographer.MAX_D1_CALLS)
    if attempt_count >= effective_cap and (ordered_work or attempt_count >= cartographer.MAX_D1_CALLS):
        reason = "global_cap_reached" if attempt_count >= cartographer.MAX_D1_CALLS else "requested_cap_reached"
        _record_cap_refusal(
            run_directory,
            run_id,
            attempt_count,
            effective_cap,
            reason,
            state["selection_fingerprint"],
        )
        raise D1CallCapError(
            "D1 invocation cap reached (%d/%d); no client was constructed"
            % (attempt_count, effective_cap)
        )

    if not ordered_work:
        audit = existing_audit or cartographer._build_audit_sheet(state)
        if not audit_path.exists():
            _write_json(audit_relative, audit)
        _write_owner_audit(run_directory, state)
        return audit

    if not _selection_unchanged(selection_path, selection_digest):
        raise D1SelectionError("selection record changed after preflight")
    _verify_selection_sources(selection, modules_root)
    receipt_sink: list[dict[str, Any]] = []
    factory = client_factory if client_factory is not None else _default_client_factory()
    client = factory(receipt_sink)
    if not callable(client):
        raise TypeError("client factory must return a callable")

    for index, source in enumerate(ordered_work):
        current_state, _ = cartographer._load_run_state(
            ledger_path, audit_path, sources
        )
        count_before = len(current_state["attempts"])
        if count_before >= effective_cap:
            reason = "global_cap_reached" if count_before >= cartographer.MAX_D1_CALLS else "requested_cap_reached"
            _record_cap_refusal(
                run_directory,
                run_id,
                count_before,
                effective_cap,
                reason,
                current_state["selection_fingerprint"],
            )
            _write_owner_audit(run_directory, current_state)
            raise D1CallCapError(
                "D1 invocation cap reached (%d/%d); remaining work stopped"
                % (count_before, effective_cap)
            )

        if hashlib.sha256(selection_path.read_bytes()).hexdigest() != selection_digest:
            raise D1SelectionError("selection record changed after preflight")
        stale_source = False

        def checked_client(prompt: str) -> Any:
            nonlocal stale_source
            try:
                _verify_selection_sources(selection, modules_root)
            except D1SelectionError:
                stale_source = True
                raise
            if not _selection_unchanged(selection_path, selection_digest):
                stale_source = True
                raise D1SelectionError("selection record changed before client invocation")
            return client(prompt)

        receipt_start = len(receipt_sink)
        result = cartographer.invoke_location(
            source,
            checked_client,
            run_relative,
            selection=sources,
        )
        attempt_number = result.get("attempt_number")
        if result.get("attempted") is True and isinstance(attempt_number, int):
            invocation_receipts = receipt_sink[receipt_start:]
            _attach_receipts(
                ledger_path,
                attempt_number,
                invocation_receipts,
            )
        if stale_source:
            latest_state, _ = cartographer._load_run_state(
                ledger_path, audit_path, sources
            )
            _write_owner_audit(run_directory, latest_state)
            raise D1SelectionError(
                "a selected source changed after preflight; the reserved slot was retained"
            )
        if result.get("status") == "call_cap_reached":
            latest_state, _ = cartographer._load_run_state(
                ledger_path, audit_path, sources
            )
            _record_cap_refusal(
                run_directory,
                run_id,
                len(latest_state["attempts"]),
                cartographer.MAX_D1_CALLS,
                "global_cap_reached",
                latest_state["selection_fingerprint"],
            )
            _write_owner_audit(run_directory, latest_state)
            raise D1CallCapError("D1 invocation cap of 60 has been reached")
        if index + 1 < len(ordered_work):
            continue

    final_state, final_audit = cartographer._load_run_state(
        ledger_path, audit_path, sources
    )
    _write_owner_audit(run_directory, final_state)
    return final_audit or cartographer._build_audit_sheet(final_state)


def _default_client_factory() -> Callable[
    [MutableSequence[dict[str, Any]]], Callable[[str], Any]
]:
    from scripts.mapping_pilot.live_client import create_live_client

    return create_live_client


def _selection_unchanged(path: Path, expected_digest: str) -> bool:
    try:
        _reject_symlink_components(path)
        if path.is_symlink() or not path.is_file():
            return False
        observed = hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return False
    return observed == expected_digest


def _read_selection(path: Path, run_id: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise D1SelectionError("run-local selection.json is required")
    try:
        selection = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise D1SelectionError("run-local selection.json is invalid") from exc
    if not isinstance(selection, dict):
        raise D1SelectionError("selection record must be an object")
    if selection.get("schema_version") != 1 or selection.get("run_id") != run_id:
        raise D1SelectionError("selection identity does not match the requested run")
    if not isinstance(selection.get("commit"), str) or not _GIT_SHA.fullmatch(selection["commit"]):
        raise D1SelectionError("selection record has no valid repository commit")
    if selection.get("module_quotas") != MODULE_QUOTAS:
        raise D1SelectionError("selection record does not match the fixed D1 module quotas")
    locations = selection.get("locations")
    if not isinstance(locations, list) or len(locations) != sum(MODULE_QUOTAS.values()):
        raise D1SelectionError("selection record must contain the fixed 20 D1 locations")
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for row in locations:
        if not isinstance(row, Mapping):
            raise D1SelectionError("selection location must be an object")
        slug = row.get("module_slug")
        location_id = row.get("location_id")
        area_type = row.get("area_type")
        if slug not in MODULE_QUOTAS or not isinstance(location_id, str) or not location_id:
            raise D1SelectionError("selection location identity is invalid")
        if "/" in location_id or "\\" in location_id:
            raise D1SelectionError("selection location ID is unsafe")
        if not isinstance(area_type, str) or not area_type:
            raise D1SelectionError("selection area type is missing")
        key = "%s:%s" % (slug, location_id)
        if key in seen:
            raise D1SelectionError("selection contains a duplicate location")
        seen.add(key)
        counts[slug] += 1
        paths = row.get("source_paths")
        hashes = row.get("source_sha256")
        if not isinstance(paths, list) or len(paths) != 1 or not isinstance(hashes, Mapping):
            raise D1SelectionError("selection source path and hash are required")
        source_path = paths[0]
        if not isinstance(source_path, str) or set(hashes) != {source_path}:
            raise D1SelectionError("selection source path/hash entries do not match")
        parsed = PurePosixPath(source_path)
        if (
            parsed.is_absolute()
            or parsed.as_posix() != source_path
            or ".." in parsed.parts
            or "\\" in source_path
            or len(parsed.parts) != 4
            or parsed.parts[0] != "modules"
            or parsed.parts[1] != slug
            or parsed.parts[2] != "areas"
            or not parsed.parts[3].endswith("_BU.json")
        ):
            raise D1SelectionError("selection source path is outside its authored module")
        digest = hashes[source_path]
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise D1SelectionError("selection source hash is invalid")
    if dict(counts) != MODULE_QUOTAS:
        raise D1SelectionError("selection record does not contain the fixed 7/6/7 quotas")
    return selection


def _selected_locations(selection: Mapping[str, Any]) -> dict[str, list[str]]:
    result = {slug: [] for slug in MODULE_QUOTAS}
    for row in selection["locations"]:
        result[row["module_slug"]].append(row["location_id"])
    return result


def _resolve_modules_root(modules_dir: str | Path) -> Path:
    raw = Path(modules_dir)
    if ".." in raw.parts or "\\" in str(modules_dir):
        raise D1SelectionError("modules source root must be a safe project path")
    root = raw if raw.is_absolute() else cartographer.PROJECT_ROOT / raw
    _reject_symlink_components(root)
    try:
        resolved = root.resolve(strict=True)
        resolved.relative_to(cartographer.PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise D1SelectionError("modules source root must remain inside the project") from exc
    if not resolved.is_dir():
        raise D1SelectionError("modules source root is not a directory")
    return resolved


def _verify_selection_sources(selection: Mapping[str, Any], modules_root: Path) -> None:
    for row in selection["locations"]:
        source_path = row["source_paths"][0]
        source_file = modules_root.parent.joinpath(*PurePosixPath(source_path).parts)
        _reject_symlink_components(source_file)
        try:
            resolved = source_file.resolve(strict=True)
            resolved.relative_to(modules_root)
            raw = resolved.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise D1SelectionError("selected source file is unavailable or unsafe") from exc
        expected = row["source_sha256"][source_path]
        observed = hashlib.sha256(raw).hexdigest()
        if observed != expected:
            raise D1SelectionError("selected source hash is stale: %s" % source_path)
        try:
            area = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise D1SelectionError("selected authored source is invalid JSON") from exc
        if not isinstance(area, Mapping) or area.get("areaType") != row["area_type"]:
            raise D1SelectionError("selected source area type no longer matches the record")
        locations = area.get("locations")
        if not isinstance(locations, list) or not any(
            isinstance(item, Mapping) and item.get("locationId") == row["location_id"]
            for item in locations
        ):
            raise D1SelectionError("selected location is absent from its bound source file")


def _verify_extracted_sources(
    selection: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]
) -> None:
    selected_by_key = {
        "%s:%s" % (row["module_slug"], row["location_id"]): row
        for row in selection["locations"]
    }
    if len(sources) != len(selected_by_key):
        raise D1SelectionError("cartographer source extraction did not match the selection")
    for source in sources:
        key = "%s:%s" % (source.get("module_slug"), source.get("location_id"))
        selected = selected_by_key.get(key)
        if selected is None:
            raise D1SelectionError("cartographer extracted an unselected location")
        selection_path = selected["source_paths"][0]
        area_reference = selection_path[len("modules/") :]
        source_hashes = source.get("source_sha256")
        source_references = source.get("source_references")
        if (
            not isinstance(source_hashes, Mapping)
            or not isinstance(source_references, list)
            or area_reference not in source_references
            or source_hashes.get(area_reference) != selected["source_sha256"][selection_path]
        ):
            raise D1SelectionError("cartographer source provenance does not match selection")


def _attach_receipts(
    ledger_path: Path,
    attempt_number: int,
    receipts: Sequence[Mapping[str, Any]],
) -> None:
    state = _read_json_file(ledger_path, "D1 attempt ledger")
    attempts = state.get("attempts")
    if not isinstance(attempts, list) or attempt_number < 1 or attempt_number > len(attempts):
        raise ValueError("reserved D1 attempt could not be found for its receipts")
    attempt = attempts[attempt_number - 1]
    if not isinstance(attempt, dict) or attempt.get("attempt_number") != attempt_number:
        raise ValueError("D1 attempt sequence changed before receipt attachment")
    allowlisted = []
    for receipt in receipts:
        if isinstance(receipt, Mapping):
            allowlisted.append({key: receipt[key] for key in _RECEIPT_FIELDS if key in receipt})
    prior = attempt.get("router_receipts", [])
    if not isinstance(prior, list):
        raise ValueError("existing invocation receipts are invalid")
    attempt["router_receipts"] = prior + allowlisted
    _write_json(ledger_path.relative_to(cartographer.PROJECT_ROOT), state)


def _write_owner_audit(run_directory: Path, state: Mapping[str, Any]) -> None:
    path = run_directory / OWNER_AUDIT_FILENAME
    _reject_symlink_components(path)
    old_values = _read_existing_owner_values(path)
    rows = _audit_claim_rows(state)
    output = io.StringIO(newline="")
    output.write(_CSV_THRESHOLD + "\n")
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for claim in rows:
        existing = old_values.get(claim["claim_id"], {})
        writer.writerow({
            **claim,
            "owner_correct": existing.get("owner_correct", ""),
            "owner_incorrect": existing.get("owner_incorrect", ""),
            "owner_invented": existing.get("owner_invented", ""),
            "owner_notes": existing.get("owner_notes", ""),
        })
    payload = output.getvalue().encode("ascii", errors="backslashreplace")
    _atomic_write_bytes(path, payload)


def _read_existing_owner_values(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError("existing D1 owner audit sheet is unsafe")
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise ValueError("existing D1 owner audit sheet is invalid") from exc
    lines = text.splitlines()
    if not lines or lines[0] != _CSV_THRESHOLD:
        raise ValueError("existing D1 owner audit threshold header was changed")
    reader = csv.DictReader(io.StringIO("\n".join(lines[1:])))
    if tuple(reader.fieldnames or ()) != _CSV_FIELDS:
        raise ValueError("existing D1 owner audit columns were changed")
    values: dict[str, dict[str, str]] = {}
    for row in reader:
        claim_id = row.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id or claim_id in values:
            raise ValueError("existing D1 owner audit claim IDs are invalid")
        values[claim_id] = {
            name: row.get(name, "") or ""
            for name in ("owner_correct", "owner_incorrect", "owner_invented", "owner_notes")
        }
    return values


def _audit_claim_rows(state: Mapping[str, Any]) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    attempts = state.get("attempts", [])
    if not isinstance(attempts, list):
        return results
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            continue
        proposal = attempt.get("proposal")
        if not isinstance(proposal, Mapping):
            continue
        attempt_number = attempt.get("attempt_number")
        location_key = attempt.get("location_key")
        module_slug = attempt.get("module_slug")
        location_id = attempt.get("location_id")
        source_evidence = {
            "source_references": attempt.get("source_references", []),
            "source_sha256": attempt.get("source_sha256", {}),
        }
        source_reference = _json_cell(source_evidence["source_references"])
        source_hashes = _json_cell(source_evidence["source_sha256"])
        seen_paths: set[str] = set()

        def add_claim(
            path: str,
            category: str,
            entity_id: Any,
            field: str,
            value: Any,
        ) -> None:
            if path in seen_paths:
                return
            seen_paths.add(path)
            claim_id = "attempt-%s:%s" % (attempt_number, path)
            results.append({
                "claim_id": claim_id,
                "attempt_number": str(attempt_number),
                "location_key": _ascii_cell(location_key),
                "module_slug": _ascii_cell(module_slug),
                "location_id": _ascii_cell(location_id),
                "claim_category": category,
                "entity_id": _ascii_cell(entity_id),
                "claim_field": path,
                "proposed_claim": _json_cell(value),
                "authored_source_reference": source_reference,
                "authored_source_sha256": source_hashes,
            })

        locations = proposal.get("locations", [])
        if isinstance(locations, list):
            for location_index, location in enumerate(locations):
                if not isinstance(location, Mapping):
                    continue
                location_prefix = "/locations/%d" % location_index
                if "name" in location:
                    add_claim(
                        location_prefix + "/name",
                        "location",
                        location.get("location_id", location_id),
                        "name",
                        location["name"],
                    )
                if "orientation" in location:
                    add_claim(
                        location_prefix + "/orientation",
                        "location",
                        location.get("location_id", location_id),
                        "orientation",
                        location["orientation"],
                    )
                features = location.get("features", [])
                if isinstance(features, list):
                    for feature_index, feature in enumerate(features):
                        if not isinstance(feature, Mapping):
                            continue
                        entity = feature.get("feature_id", "feature-%d" % feature_index)
                        for field, value in sorted(feature.items()):
                            if field == "feature_id":
                                continue
                            category = (
                                "visibility_perceivability_sightline"
                                if _VISIBILITY_KEY.search(str(field))
                                else "feature"
                            )
                            add_claim(
                                "%s/features/%d/%s" % (location_prefix, feature_index, field),
                                category,
                                entity,
                                str(field),
                                value,
                            )
                exits = location.get("exits", [])
                if isinstance(exits, list):
                    for exit_index, exit_row in enumerate(exits):
                        if not isinstance(exit_row, Mapping):
                            continue
                        entity = exit_row.get("exit_id", "exit-%d" % exit_index)
                        add_claim(
                            "%s/exits/%d/exists" % (location_prefix, exit_index),
                            "exit",
                            entity,
                            "exists",
                            True,
                        )
                        for field, value in sorted(exit_row.items()):
                            if field == "exit_id":
                                continue
                            if field == "side":
                                category = "exit_side"
                            elif _VISIBILITY_KEY.search(str(field)):
                                category = "visibility_perceivability_sightline"
                            else:
                                category = "exit"
                            add_claim(
                                "%s/exits/%d/%s" % (location_prefix, exit_index, field),
                                category,
                                entity,
                                str(field),
                                value,
                            )
                for facts_field in ("perceivable_facts", "hidden_facts"):
                    facts = location.get(facts_field, [])
                    if isinstance(facts, list):
                        for fact_index, fact in enumerate(facts):
                            add_claim(
                                "%s/%s/%d" % (location_prefix, facts_field, fact_index),
                                "visibility_perceivability_sightline",
                                location.get("location_id", location_id),
                                facts_field,
                                fact,
                            )
                _collect_explicit_visibility_claims(
                    location,
                    location_prefix,
                    location.get("location_id", location_id),
                    add_claim,
                )
    results.sort(key=lambda row: (int(row["attempt_number"]), row["claim_field"], row["claim_category"]))
    return results


def _collect_explicit_visibility_claims(
    value: Any,
    path: str,
    entity_id: Any,
    add_claim: Callable[[str, str, Any, str, Any], None],
) -> None:
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            child_path = "%s/%s" % (path, str(key).replace("~", "~0").replace("/", "~1"))
            child = value[key]
            if _VISIBILITY_KEY.search(str(key)):
                if isinstance(child, list):
                    for index, item in enumerate(child):
                        add_claim(
                            "%s/%d" % (child_path, index),
                            "visibility_perceivability_sightline",
                            entity_id,
                            str(key),
                            item,
                        )
                    continue
                add_claim(
                    child_path,
                    "visibility_perceivability_sightline",
                    entity_id,
                    str(key),
                    child,
                )
                continue
            if isinstance(child, (Mapping, list)):
                _collect_explicit_visibility_claims(child, child_path, entity_id, add_claim)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _collect_explicit_visibility_claims(child, "%s/%d" % (path, index), entity_id, add_claim)


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _ascii_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).encode("ascii", errors="backslashreplace").decode("ascii")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    _reject_symlink_components(path)
    if path.exists() and not path.is_file():
        raise ValueError("D1 audit output path is not a regular file")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".d1-owner-audit-", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        os.close(file_descriptor)
        with temporary_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise


def _record_cap_refusal(
    run_directory: Path,
    run_id: str,
    invocation_count: int,
    cap: int,
    reason: str,
    selection_fingerprint: str,
) -> None:
    path = run_directory / RUN_EVENTS_FILENAME
    _reject_symlink_components(path)
    events: list[dict[str, Any]] = []
    if path.exists():
        loaded = _read_json_file(path, "D1 run events")
        if loaded.get("schema_version") != 1 or loaded.get("run_id") != run_id:
            raise ValueError("existing D1 run events do not match the run")
        existing = loaded.get("events")
        if not isinstance(existing, list):
            raise ValueError("existing D1 run event list is invalid")
        events = existing
    events.append({
        "sequence": len(events) + 1,
        "event": "call_cap_refusal",
        "run_id": run_id,
        "invocation_count": invocation_count,
        "cap": cap,
        "reason": reason,
        "selection_fingerprint": selection_fingerprint,
    })
    _write_json(
        (D1_ROOT / run_id / RUN_EVENTS_FILENAME),
        {"schema_version": 1, "run_id": run_id, "events": events},
    )


def _read_json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("%s is invalid" % label) from exc
    if not isinstance(value, dict):
        raise ValueError("%s must be an object" % label)
    return value


def _write_json(relative_path: Path, payload: Any) -> None:
    if relative_path.is_absolute() or ".." in relative_path.parts or relative_path.parts[:4] != D1_ROOT.parts:
        raise ValueError("D1 output must remain below the run-local evidence directory")
    absolute_path = cartographer.PROJECT_ROOT / relative_path
    _reject_symlink_components(absolute_path)
    from utils.file_operations import safe_write_json

    if not safe_write_json(
        str(relative_path),
        payload,
        create_backup=False,
        acquire_lock=False,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    ):
        raise OSError("atomic D1 JSON write failed: %s" % relative_path.name)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a source-bound D1 mapping pilot.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-invocations", type=int, default=cartographer.MAX_D1_CALLS)
    parser.add_argument("--retry", action="append", dest="retry_locations", default=[])
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = run_d1(
            args.run_id,
            max_invocations=args.max_invocations,
            retry_locations=args.retry_locations,
            dry_run=args.dry_run,
        )
    except (D1SelectionError, D1CallCapError, ValueError, OSError) as exc:
        print("[FAIL] %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
