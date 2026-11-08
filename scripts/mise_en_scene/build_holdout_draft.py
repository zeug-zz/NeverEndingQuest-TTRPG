# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Build or verify the deterministic, unseeded six-scene holdout draft."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from mise_en_scene import evaluation, holdout_draft_specs
else:
    from . import evaluation, holdout_draft_specs


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_RELATIVE = Path(
    "openspec/changes/v2-mise-en-scene-authoring-projection-evaluation/holdout-draft"
)
_TEST_RELATIVE = Path("scripts/test_mise_en_scene_holdout_draft.py")
_RUBRIC_RELATIVE = _OUTPUT_RELATIVE / "rubric.md"
_ASSESSOR_RELATIVE = _OUTPUT_RELATIVE / "assessor-config.draft.md"


class DraftBuildError(RuntimeError):
    """Raised when the fixed draft inputs or outputs are incomplete."""


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DraftBuildError("required draft input is unreadable: " + str(path)) from exc


def _render_files() -> tuple[dict[str, bytes], dict[str, Any]]:
    """Return the manifest and exact public artifact bytes without writing."""

    manifest = evaluation.build_draft_holdout_manifest(
        holdout_draft_specs.build_scene_inputs(),
        test_sha256=_sha256_file(_REPO_ROOT / _TEST_RELATIVE),
        rubric_sha256=_sha256_file(_REPO_ROOT / _RUBRIC_RELATIVE),
        assessor_sha256=_sha256_file(_REPO_ROOT / _ASSESSOR_RELATIVE),
        include_owner_leakage_adjudications=True,
    )
    manifest_text = json.dumps(
        manifest,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    files: dict[str, bytes] = {
        "manifest.draft.json": manifest_text.encode("ascii"),
    }
    for record in holdout_draft_specs.SCENE_SPECS:
        scene_slug = record["scene_id"].split(":scene:", 1)[1]
        source_manifest = {
            "scene_id": record["scene_id"],
            "source_identity": record["source_identity"],
            "source_files": record["source_files"],
            "source_text_sha256": record["source_text_sha256"],
            "source_spans": record["source_spans"],
            "source_field_refs": record["source_field_refs"],
            "source_ref": record["source_ref"],
            "lineage_status": record["lineage_status"],
            "adaptation_lineage": record["adaptation_lineage"],
        }
        spec_payload = {
            "status": "DRAFT_UNFROZEN_NOT_OWNER_APPROVED",
            "source": source_manifest,
            "spec": record["spec"],
        }
        spec_text = json.dumps(
            spec_payload,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
        files[(Path("scene-specs") / (scene_slug + ".json")).as_posix()] = spec_text.encode("ascii")
    for scene in manifest["scenes"]:
        scene_slug = scene["scene_id"].split(":scene:", 1)[1]
        for artifact in scene["artifacts"]:
            content = artifact["content"]
            if type(content) is not str or not content.isascii():
                raise DraftBuildError(
                    "rendered artifact is not ASCII: "
                    + scene["scene_id"]
                    + "/"
                    + artifact["condition"]
                )
            relative = Path("artifacts") / scene_slug / (artifact["condition"] + ".txt")
            files[relative.as_posix()] = content.encode("ascii")
    files["leakage-review.draft.md"] = _render_leakage_review(manifest).encode("ascii")
    return files, manifest


def _render_leakage_review(manifest: dict[str, Any]) -> str:
    summary = manifest["leakage_summary"]
    adjudications = {
        (item["scene_id"], item["known_record_id"]): item
        for item in manifest["leakage_adjudications"]
    }
    lines = [
        "# Bounded Leakage Screen - Draft Review Record",
        "",
        "**Status: DRAFT / UNFROZEN / NOT OWNER-APPROVED.** This is a provider-free lexical screen, not semantic proof or a leakage certification.",
        "",
        "- Evaluator result: `" + manifest["leakage_status"] + "`",
        "- Manual review: owner-adjudicated on `2026-11-08` for `"
        + str(len(adjudications))
        + "` flagged pairs; the draft remains not owner-approved for freeze or scoring.",
        "- Rejected pairs: `" + str(summary["rejected_pairs"]) + "`",
        "- Review-required pairs: `" + str(summary["review_required_pairs"]) + "`",
        "- No-match pairs within bounded checks: `" + str(summary["no_match_pairs"]) + "`",
        "- Total source/derivative pair checks: `" + str(summary["pair_checks"]) + "`",
        "",
        "The evaluator checks exact identity/reference/hash/lineage and bounded text, artifact-text, layout, and feature token overlap against all 16 original M1 artifacts and nine expanded owner examples. It does not claim semantic detection. Thresholds remain unchanged from the reviewed selection and evaluation contract.",
        "",
        "## Manual owner adjudication (2026-11-08)",
        "",
        "The repository owner, under ruling `2026-11-08T21:14:44Z`, adjudicated both flagged pairs as `ACCEPTED-NOT-DERIVED`. The overlap is generic approach-to-threshold-to-focal staging vocabulary; there is no text or lineage overlap, and the module differs. This is a narrow manual decision, not semantic/NLP proof.",
        "",
        "## Flagged pairs",
        "",
    ]
    flagged_checks = [
        check
        for check in manifest["leakage_checks"]
        if check["verdict"] != "NO_MATCH_WITHIN_BOUNDED_CHECKS"
    ]
    if flagged_checks:
        for check in flagged_checks:
            scene_slug = check["scene_id"].split(":scene:", 1)[1]
            flags = ",".join(check["review_flags"] or check["flags"])
            pair = scene_slug + " / " + check["known_record_id"] + " / " + flags
            decision = adjudications.get(
                (check["scene_id"], check["known_record_id"])
            )
            if decision is None:
                lines.append(
                    "- `" + pair + "` - unresolved; inspect before any future freeze."
                )
            else:
                lines.append(
                    "- `"
                    + pair
                    + "` - automated `"
                    + check["verdict"]
                    + "`; owner-adjudicated `"
                    + decision["adjudication"]
                    + "` by `"
                    + decision["owner"]
                    + "` on `"
                    + decision["adjudicated_on"]
                    + "`."
                )
    else:
        lines.append("- None from the bounded checks; this is not a semantic independence finding.")
    lines.extend(
        [
            "",
            "No threshold was changed, no source was substituted, and no assignment seed/order was selected. The two manual decisions are stored separately from the automated `REVIEW_REQUIRED` results and do not alter the generic status contract. This draft remains `DRAFT_UNFROZEN` / `NOT_OWNER_APPROVED` and does not authorize scoring, provider assessment, or live evaluation.",
            "",
        ]
    )
    return "\n".join(lines)


def _output_directory() -> Path:
    return _REPO_ROOT / _OUTPUT_RELATIVE


def _write_files(files: dict[str, bytes]) -> None:
    output_root = _output_directory().resolve()
    for relative_text, content in sorted(files.items()):
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise DraftBuildError("unsafe generated path: " + relative_text)
        path = output_root / relative
        resolved = path.resolve()
        try:
            resolved.relative_to(output_root)
        except ValueError as exc:
            raise DraftBuildError("generated path escapes holdout-draft") from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(content)


def _check_files(files: dict[str, bytes]) -> list[str]:
    output_root = _output_directory()
    mismatches: list[str] = []
    for relative_text, expected in sorted(files.items()):
        path = output_root / relative_text
        try:
            observed = path.read_bytes()
        except OSError:
            mismatches.append(relative_text + " (missing or unreadable)")
            continue
        if observed != expected:
            mismatches.append(relative_text + " (content differs)")

    generated_roots = ("artifacts", "scene-specs")
    expected_generated = {
        name
        for name in files
        if any(name.startswith(root + "/") for root in generated_roots)
    }
    actual_generated: set[str] = set()
    for root_name in generated_roots:
        root = output_root / root_name
        if root.exists():
            actual_generated.update(
                path.relative_to(output_root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            )
    mismatches.extend(
        name + " (unexpected generated file)"
        for name in sorted(actual_generated - expected_generated)
    )
    return mismatches


def _flagged_pairs(manifest: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for check in manifest["leakage_checks"]:
        if check["verdict"] == "NO_MATCH_WITHIN_BOUNDED_CHECKS":
            continue
        result.append(
            check["scene_id"].split(":scene:", 1)[1]
            + " / "
            + check["known_record_id"]
            + " / "
            + ",".join(check["review_flags"] or check["flags"])
        )
    return result


def _report(manifest: dict[str, Any]) -> None:
    print(
        "candidate_sha256="
        + manifest["candidate_sha256"]
        + " leakage_status="
        + manifest["leakage_status"]
    )
    flagged = _flagged_pairs(manifest)
    print("flagged_pairs=" + ("; ".join(flagged) if flagged else "none"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare with the draft manifest and artifacts",
    )
    arguments = parser.parse_args(argv)
    try:
        files, manifest = _render_files()
        if arguments.check:
            mismatches = _check_files(files)
            if mismatches:
                for mismatch in mismatches:
                    print("MISMATCH: " + mismatch, file=sys.stderr)
                return 1
            print("OK: committed draft outputs reproduce")
        else:
            _write_files(files)
            print("Wrote " + str(len(files)) + " files under " + _OUTPUT_RELATIVE.as_posix())
        _report(manifest)
    except (DraftBuildError, evaluation.EvaluationManifestError, ValueError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
