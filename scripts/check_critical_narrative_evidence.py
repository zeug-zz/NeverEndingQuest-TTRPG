# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0

"""
CLI entrypoint for the critical narrative omission evidence pass.

Usage:
    .venv/bin/python scripts/check_critical_narrative_evidence.py \\
        --module The_Hidden_City_of_Numillian [--json]

    .venv/bin/python scripts/check_critical_narrative_evidence.py \\
        --module The_Hidden_City_of_Numillian --write-run [--json] \\
        [--output-dir <path>] [--task-id <id>]

Outputs structured evidence of critical narrative omissions found by
comparing benchmark source expectations against live module JSON and
the original source markdown.

With --write-run, also writes an agent-run evidence package to disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
# Ensure repo root is on sys.path so `utils` imports resolve
# when the script is executed by path from the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from utils.critical_narrative_evidence import (
    _generate_task_id,
    build_critical_narrative_agent_run,
    format_evidence_summary,
    run_critical_omission_evidence_pass,
    write_critical_narrative_agent_run,
)

_DEFAULT_RUN_BASE = Path("data/agent_runs/critical_narrative_repair")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run critical narrative omission evidence pass for a module.",
    )
    parser.add_argument(
        "--module",
        required=True,
        help="Module slug (e.g. The_Hidden_City_of_Numillian)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of human-readable summary",
    )
    parser.add_argument(
        "--write-run",
        action="store_true",
        help="Write agent-run evidence package to disk",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for agent run (default: data/agent_runs/critical_narrative_repair/<task_id>/)",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Task ID for agent run (default: auto-generated timestamped id)",
    )
    return parser


def main(argv: list = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    evidence = run_critical_omission_evidence_pass(args.module)

    # Build JSON output payload
    output: dict = dict(evidence)

    # Write agent run if requested
    if args.write_run:
        task_id = args.task_id or _generate_task_id(args.module)
        output_dir = Path(args.output_dir) if args.output_dir else _DEFAULT_RUN_BASE / task_id

        package = build_critical_narrative_agent_run(
            evidence, args.module, task_id,
        )
        files = write_critical_narrative_agent_run(output_dir, package)

        output["run_dir"] = str(output_dir)
        output["run_files"] = {
            "run": files.get("run", ""),
            "critical_evidence": files.get("critical_evidence", ""),
            "source_excerpts": files.get("source_excerpts", ""),
            "builder_repair_brief": files.get("builder_repair_brief", ""),
        }

    if args.json:
        json.dump(output, sys.stdout, indent=2, sort_keys=True)
        print()
    else:
        print(format_evidence_summary(evidence))

    # Exit with non-zero if critical omissions found
    if evidence.get("error"):
        return 2
    if evidence.get("fail_count", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
