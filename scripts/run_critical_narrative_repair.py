# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
CLI entrypoint for critical narrative repair.

Usage:
    .venv/bin/python scripts/run_critical_narrative_repair.py \\
        --run-dir <agent-run-dir> \\
        --module The_Hidden_City_of_Numillian \\
        [--dry-run] [--apply] [--fake-response <path>]

Dry-run (default): validates the repair plan but does not write module files.
Apply: writes validated repairs to module artifacts.
Fake response: injects a canned Builder response for provider-free testing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.critical_narrative_repair import (
    apply_repair_plan,
    build_builder_repair_prompt,
    load_repair_run,
    parse_builder_repair_response,
    validate_repair_plan,
    write_builder_repair_result,
)


def _try_provider_call(prompt: str) -> str:
    """Attempt a real provider call using the factory. Returns raw text.

    Fails closed: returns an error marker on any failure.
    """
    provider_stage = "accurate_ingest.critical_narrative_repair"
    try:
        from utils.ai_client_factory import (
            create_chat_client,
            get_chat_completion_params,
            get_chat_model_name,
            handle_provider_error,
        )
        client = create_chat_client()
        response = client.chat.completions.create(
            **get_chat_completion_params(
                "builders",
                get_chat_model_name(),
                temperature_override=0.2,
            ),
            messages=[
                {"role": "system", "content": "Return structured JSON only. No markdown, no prose outside the JSON object."},
                {"role": "user", "content": prompt},
            ],
            timeout=120,
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        error_result = {"should_fallback": False}
        try:
            error_result = handle_provider_error(exc, provider_stage)
        except Exception:
            pass
        return json.dumps({
            "provider_error": True,
            "provider_stage": provider_stage,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:500],
            "retryable": bool(error_result.get("should_fallback", False)),
        })


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run critical narrative repair from an agent-run directory.",
    )
    p.add_argument("--run-dir", required=True, help="Agent-run directory path")
    p.add_argument("--module", required=True, help="Module slug")
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Validate without writing (default)")
    p.add_argument("--apply", action="store_true",
                   help="Apply validated repair to module files")
    p.add_argument("--fake-response", default=None,
                   help="Path to a JSON file with a fake Builder response")
    return p


def main(argv: list = None) -> int:
    args = build_parser().parse_args(argv)

    run_dir = Path(args.run_dir)
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"ERROR: run-dir does not exist: {run_dir}", file=sys.stderr)
        return 2

    # Load agent run
    run_data = load_repair_run(run_dir)
    if run_data is None:
        print("ERROR: Failed to load agent-run files.", file=sys.stderr)
        return 2

    module_dir = Path("modules") / args.module

    # Get Builder response: fake > provider > error
    if args.fake_response:
        try:
            raw = Path(args.fake_response).read_text(encoding="utf-8")
        except Exception as exc:
            print(f"ERROR: Cannot read fake-response: {exc}", file=sys.stderr)
            return 2
    else:
        prompt = build_builder_repair_prompt(run_data)
        if not prompt:
            print("ERROR: Could not build repair prompt.", file=sys.stderr)
            return 2
        print("[REPAIR] Calling Builder provider...")
        raw = _try_provider_call(prompt)
        if "provider_error" in raw:
            try:
                err = json.loads(raw)
                print(f"ERROR: Provider call failed: {err.get('error_message', '?')}", file=sys.stderr)
            except Exception:
                pass
            write_builder_repair_result(run_dir, {
                "status": "failed",
                "module_slug": args.module,
                "omissions_addressed": [],
                "files_proposed": [],
                "files_written": [],
                "validation_errors": [],
                "provider_error": raw[:500],
                "next_verification_commands": [],
            })
            return 2

    # Parse response
    plan = parse_builder_repair_response(raw)
    if plan is None:
        print("ERROR: Failed to parse Builder response as JSON.", file=sys.stderr)
        write_builder_repair_result(run_dir, {
            "status": "failed",
            "module_slug": args.module,
            "omissions_addressed": [],
            "files_proposed": [],
            "files_written": [],
            "validation_errors": ["Builder response is not valid JSON"],
            "next_verification_commands": [],
        })
        return 2

    # Validate
    validation = validate_repair_plan(plan, module_dir)
    if not validation["valid"]:
        print("VALIDATION FAILED:")
        for e in validation["errors"]:
            print(f"  - {e}")
        write_builder_repair_result(run_dir, {
            "status": "failed",
            "module_slug": plan.get("module_slug", args.module),
            "omissions_addressed": plan.get("omissions_addressed", []),
            "files_proposed": [],
            "files_written": [],
            "validation_errors": validation["errors"],
            "next_verification_commands": [],
        })
        return 2

    # Apply
    apply_flag = args.apply
    if not apply_flag:
        print("[DRY-RUN] Repair plan is valid. Use --apply to write.")
    else:
        print("[APPLY] Writing repair artifacts...")

    result = apply_repair_plan(plan, module_dir, apply=apply_flag)
    write_builder_repair_result(run_dir, result)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "failed":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
