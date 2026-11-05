# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Isolated mapping-pilot server worker and adapter observation sink."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import math
import re
import sys
import threading
from pathlib import Path
from typing import Any, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    "combat_stage_tavern_zones",
)
_LIFECYCLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
_RECEIPT_NAME = re.compile(r"^record-[0-9]{8}\.json$")


def _safe_runtime_root(value: str | Path) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        expected = PROJECT_ROOT / "tmp" / "combat_capture"
        root = raw
        relative = Path("tmp") / "combat_capture"
        if raw != expected:
            raise ValueError("mapping-pilot runtime root must be tmp/combat_capture")
    else:
        if ".." in raw.parts or raw.as_posix() != "tmp/combat_capture":
            raise ValueError("mapping-pilot runtime root must be tmp/combat_capture")
        relative = raw
        root = PROJECT_ROOT / raw
    current = PROJECT_ROOT
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("mapping-pilot runtime root must not traverse symlinks")
    try:
        resolved = root.resolve(strict=True)
        resolved.relative_to((PROJECT_ROOT / "tmp").resolve(strict=True))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("mapping-pilot runtime root is unavailable") from exc
    if not resolved.is_dir():
        raise ValueError("mapping-pilot runtime root is unavailable")
    return resolved


def _safe_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise ValueError("mapping-pilot worker input is unavailable")
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("mapping-pilot worker input is invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("non-standard JSON value: %s" % value)


def _movement_observer(runtime_root: Path, row_run_id: str):
    mapping_root = runtime_root / "mapping_pilot"
    observation_root = mapping_root / "movement_observations" / row_run_id
    observation_root.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(runtime_root, observation_root)
    step_path = mapping_root / "current_script_step.json"
    tracker_path = runtime_root / "party_tracker.json"

    def observe(observation: Any) -> None:
        from utils.file_operations import safe_write_json

        step = _safe_json(step_path)
        tracker = _safe_json(tracker_path)
        step_id = step.get("step_id") if isinstance(step, dict) else None
        active_character = tracker.get("active_character") if isinstance(tracker, dict) else None
        if not isinstance(step_id, str) or not _SAFE_TOKEN.fullmatch(step_id):
            step_id = None
        if not isinstance(active_character, str) or not active_character.strip():
            active_character = None
        status = getattr(observation, "status", None)
        hint = getattr(observation, "hint", None)
        reason = getattr(observation, "reason", None)
        if status not in ("valid", "missing", "invalid"):
            status = "invalid"
            hint = None
            reason = "observer_payload_invalid"
        record = {
            "row_run_id": row_run_id,
            "step_id": step_id,
            "active_character": active_character,
            "status": status,
            "hint": hint,
            "reason": reason if isinstance(reason, str) else None,
        }
        sequence = 1
        while True:
            target = observation_root / ("record-%06d.json" % sequence)
            if target.exists() or target.is_symlink():
                sequence += 1
                continue
            _reject_symlink_components(runtime_root, target)
            if not safe_write_json(
                str(target),
                record,
                create_backup=False,
                acquire_lock=True,
                json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
            ):
                raise OSError("movement observation write failed")
            return

    return observe


def _router_receipt_record(
    receipt: Any,
    *,
    runtime_root: Path,
    row_run_id: str,
    lifecycle_id: str,
    sequence: int,
) -> dict[str, Any]:
    """Project one router receipt to bounded, non-content evidence."""
    step_path = runtime_root / "mapping_pilot" / "current_script_step.json"
    try:
        step = _safe_json(step_path)
    except (OSError, ValueError):
        step = None
    phase = step.get("phase") if isinstance(step, dict) else None
    step_id = step.get("step_id") if isinstance(step, dict) else None
    expected = step.get("provider_call_expected") if isinstance(step, dict) else None
    if not isinstance(step_id, str) or not _SAFE_TOKEN.fullmatch(step_id):
        step_id = None
    if type(expected) is not bool:
        expected = None
    if phase == "model_bearing_turn" and expected is True and step_id is not None:
        attribution = "model_bearing_turn"
        attribution_status = "recorded"
    elif phase == "lifecycle_control" and expected is False:
        attribution = "lifecycle_control"
        attribution_status = "recorded"
    else:
        attribution = "unknown"
        attribution_status = "missing"

    def label(name: str) -> Optional[str]:
        value = getattr(receipt, name, None)
        return value if isinstance(value, str) and _SAFE_LABEL.fullmatch(value) else None

    def count(name: str) -> Optional[int]:
        value = getattr(receipt, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return None

    def number(name: str) -> Optional[float]:
        value = getattr(receipt, name, None)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        ):
            return float(value)
        return None

    fallback = getattr(receipt, "fallback", None)
    if type(fallback) is not bool:
        fallback = None
    transport_retry = getattr(receipt, "transport_retry", None)
    if type(transport_retry) is not bool:
        transport_retry = None
    usage_complete = getattr(receipt, "usage_complete", None)
    if type(usage_complete) is not bool:
        usage_complete = None
    cost_complete = getattr(receipt, "cost_complete", None)
    if type(cost_complete) is not bool:
        cost_complete = None

    return {
        "event_type": "router_receipt",
        "row_run_id": row_run_id,
        "lifecycle_id": lifecycle_id,
        "sequence": sequence,
        "kind": label("kind"),
        "call_id": label("call_id"),
        "attempt_id": label("attempt_id"),
        "attempt_number": count("attempt_number"),
        "task": label("task"),
        "tier": label("tier"),
        "profile": label("profile"),
        "transport_retry": transport_retry,
        "retry_tier": label("retry_tier"),
        "fallback": fallback,
        "transport": label("transport_provider"),
        "provider": label("observed_upstream_provider"),
        "requested_model": label("requested_model"),
        "resolved_model": label("resolved_model"),
        "prompt_units": count("prompt_tokens"),
        "cached_units": count("cached_tokens"),
        "completion_units": count("completion_tokens"),
        "usage_complete": usage_complete,
        "provider_reported_cost_usd": number("provider_reported_cost_usd"),
        "cost_usd": number("cost_usd"),
        "cost_provenance": label("cost_provenance"),
        "cost_complete": cost_complete,
        "error_type": label("error_type"),
        "elapsed_ms": number("elapsed_ms"),
        "attribution": attribution,
        "attribution_status": attribution_status,
        "script_step_id": step_id,
        "provider_call_expected": expected,
    }


def install_router_receipt_observer(
    runtime_root: str | Path,
    row_run_id: str,
    lifecycle_id: str,
    *,
    router_module: Any = None,
) -> Any:
    """Temporarily observe router receipts without reading prompts or responses.

    The callable returns an idempotent cleanup function. ``router_module`` is a
    provider-free injection point for tests; production resolves the sandbox
    router only after the sandbox web application has been imported.
    """
    root = _safe_runtime_root(runtime_root)
    if not _SAFE_TOKEN.fullmatch(row_run_id) or not _LIFECYCLE_ID.fullmatch(lifecycle_id):
        raise ValueError("mapping-pilot receipt identity is invalid")
    if router_module is None:
        from utils import llm_router as router_module

    router = getattr(router_module, "llm", None)
    original_call = getattr(router, "call", None)
    if not callable(original_call):
        raise ValueError("sandbox LLM router call is unavailable")

    mapping_root = root / "mapping_pilot"
    receipt_root = mapping_root / "router_receipts" / row_run_id
    _reject_symlink_components(root, receipt_root)
    receipt_root.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, receipt_root)
    sequence = 0
    for entry in receipt_root.iterdir():
        if _RECEIPT_NAME.fullmatch(entry.name):
            if entry.is_symlink() or not entry.is_file():
                raise ValueError("mapping-pilot router receipt path is unsafe")
            sequence = max(sequence, int(entry.name[7:15]))
    lock = threading.RLock()

    def record(receipt: Any) -> None:
        from utils.file_operations import safe_write_json

        nonlocal sequence
        with lock:
            sequence += 1
            target = receipt_root / ("record-%08d.json" % sequence)
            _reject_symlink_components(root, target)
            payload = _router_receipt_record(
                receipt,
                runtime_root=root,
                row_run_id=row_run_id,
                lifecycle_id=lifecycle_id,
                sequence=sequence,
            )
            try:
                wrote = safe_write_json(
                    str(target),
                    payload,
                    create_backup=False,
                    acquire_lock=True,
                    json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
                )
            except Exception as exc:
                print(
                    "[FAIL] mapping_pilot_router_receipt_write_failed error_type=%s"
                    % type(exc).__name__,
                    file=sys.stderr,
                    flush=True,
                )
                raise
            if not wrote:
                print(
                    "[FAIL] mapping_pilot_router_receipt_write_failed error_type=WriteFailed",
                    file=sys.stderr,
                    flush=True,
                )
                raise OSError("router receipt write failed")

    def wrapped_call(*args: Any, **kwargs: Any) -> Any:
        original_observer = kwargs.get("observer")

        def observed(receipt: Any, _raw: Any) -> None:
            try:
                if original_observer is not None:
                    original_observer(receipt, _raw)
            finally:
                record(receipt)

        if original_observer is not None:
            for attribute in (
                "_llm_tracks_usage",
                "_llm_traces_provider",
                "_llm_api_log_before_tracker",
                "_llm_g10_source_id",
                "_llm_g10_endpoint",
            ):
                try:
                    if hasattr(original_observer, attribute):
                        setattr(observed, attribute, getattr(original_observer, attribute))
                except Exception:
                    continue
        kwargs["observer"] = observed
        return original_call(*args, **kwargs)

    router.call = wrapped_call
    cleaned = False

    def cleanup() -> None:
        nonlocal cleaned
        if cleaned:
            return
        if getattr(router, "call", None) is wrapped_call:
            router.call = original_call
        cleaned = True

    return cleanup


def _write_arm_a_noop_record(
    runtime_root: Path, lifecycle_id: str
) -> None:
    from utils.file_operations import safe_write_json

    mapping_root = runtime_root / "mapping_pilot"
    evidence_directory = mapping_root / "turn_packet_evidence" / lifecycle_id
    _reject_symlink_components(runtime_root, evidence_directory)
    evidence_directory.mkdir(parents=True, exist_ok=False)
    target = evidence_directory / "record-00000001.json"
    _reject_symlink_components(runtime_root, target)
    if not safe_write_json(
        str(target),
        {
            "format_version": 1,
            "lifecycle_id": lifecycle_id,
            "sequence": 1,
            "event_type": "arm_a_noop",
            "adapter_installed": False,
            "evidence_status": "recorded",
        },
        create_backup=False,
        acquire_lock=True,
        json_kwargs={"ensure_ascii": True, "sort_keys": True, "allow_nan": False},
    ):
        raise OSError("arm A no-op evidence write failed")


def _sandbox_importer(runtime_root: Path, module_name: str) -> Any:
    if module_name != "scripts.mapping_pilot.adapter":
        return importlib.import_module(module_name)
    adapter_path = runtime_root / "scripts" / "mapping_pilot" / "adapter.py"
    _reject_symlink_components(runtime_root, adapter_path)
    if not adapter_path.is_file():
        raise ValueError("sandbox mapping-pilot adapter is unavailable")
    spec = importlib.util.spec_from_file_location(module_name, adapter_path)
    if spec is None or spec.loader is None:
        raise ValueError("sandbox mapping-pilot adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _wrap_adapter_installer(
    original_installer: Any,
    *,
    runtime_root: Path,
    row_run_id: str,
    lifecycle_id: str,
    arm: str,
) -> Any:
    def install(**kwargs: Any) -> Any:
        installation = original_installer(**kwargs)
        try:
            cleanup = install_router_receipt_observer(
                runtime_root, row_run_id, lifecycle_id
            )
            if arm == "A":
                _write_arm_a_noop_record(runtime_root, lifecycle_id)
        except Exception:
            installation.uninstall()
            raise
        original_uninstall = installation.uninstall

        def uninstall() -> None:
            try:
                original_uninstall()
            finally:
                cleanup()

        installation.uninstall = uninstall
        return installation

    return install


def _reject_symlink_components(root: Path, path: Path) -> None:
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("mapping-pilot worker path escaped the sandbox") from exc
    current = root
    if root.is_symlink():
        raise ValueError("mapping-pilot worker root is unsafe")
    relative = path.relative_to(root)
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("mapping-pilot worker path is unsafe")


def launch_worker(
    *,
    arm: str,
    fixture_id: str,
    party_size: int,
    row_run_id: str,
    lifecycle_id: Optional[str] = None,
    runtime_root: str | Path = "tmp/combat_capture",
    launcher: Any = None,
) -> Any:
    """Invoke the existing sandbox launcher with a file-backed shadow observer."""
    if arm not in ("A", "B", "D"):
        raise ValueError("mapping-pilot arm must be A, B, or D")
    if fixture_id not in _FIXTURE_IDS:
        raise ValueError("unsupported mapping-pilot fixture")
    if isinstance(party_size, bool) or party_size not in (1, 4):
        raise ValueError("mapping-pilot party size must be 1 or 4")
    if not isinstance(row_run_id, str) or not _SAFE_TOKEN.fullmatch(row_run_id):
        raise ValueError("mapping-pilot row run ID is invalid")
    if lifecycle_id is not None and not _LIFECYCLE_ID.fullmatch(lifecycle_id):
        raise ValueError("mapping-pilot lifecycle ID is invalid")
    root = _safe_runtime_root(runtime_root)
    if launcher is None:
        from scripts.mapping_pilot import launcher as launcher_module

        launcher = launcher_module
    observer = _movement_observer(root, row_run_id) if arm == "D" else None
    imported_adapter: list[Any] = []

    def importer(name: str) -> Any:
        if name == "scripts.mapping_pilot.adapter":
            if not imported_adapter:
                imported_adapter.append(_sandbox_importer(root, name))
            return imported_adapter[0]
        return importlib.import_module(name)

    def adapter_installer(**kwargs: Any) -> Any:
        if not imported_adapter:
            importer("scripts.mapping_pilot.adapter")
        return _wrap_adapter_installer(
            imported_adapter[0].install_adapter,
            runtime_root=root,
            row_run_id=row_run_id,
            lifecycle_id=lifecycle_id or row_run_id,
            arm=arm,
        )(**kwargs)
    return launcher.launch(
        arm=arm,
        fixture_id=fixture_id,
        party_size=party_size,
        runtime_root=root,
        movement_hint_observer=observer,
        lifecycle_id=lifecycle_id,
        module_importer=importer,
        adapter_installer=adapter_installer,
    )


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one isolated mapping-pilot server.")
    parser.add_argument("--arm", choices=("A", "B", "D"), required=True)
    parser.add_argument("--fixture-id", choices=_FIXTURE_IDS, required=True)
    parser.add_argument("--party-size", type=int, choices=(1, 4), required=True)
    parser.add_argument("--row-run-id", required=True)
    parser.add_argument("--lifecycle-id", default=None)
    parser.add_argument("--runtime-root", default="tmp/combat_capture")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        launch_worker(
            arm=args.arm,
            fixture_id=args.fixture_id,
            party_size=args.party_size,
            row_run_id=args.row_run_id,
            lifecycle_id=args.lifecycle_id,
            runtime_root=args.runtime_root,
        )
    except Exception as exc:
        print("[FAIL] mapping-pilot server worker: %s" % type(exc).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
