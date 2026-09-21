# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Utility - Toolkit Adaptation Markdown Quality
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Provider-free deterministic quality contract for the readable adaptation
MODULE_SUMMARY.md artifact. The checker verifies UTF-8 validity, a meaningful
title, required heading structure, a bounded playable/content signal, minimum
size, the exact "Adapted for NEQ-TTRPG" notice, and rejection of raw JSON
dumps or error/traceback text.

This utility only inspects text. It does not call a provider, write files,
run ModuleBuilder, or claim publication. Publication authority remains in the
Python finisher transaction.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file in the repository root.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from utils.toolkit_adaptation_dossier import ADAPTATION_NOTICE

# Versioned contract identity used in reports and diagnostics.
ADAPTATION_MARKDOWN_QUALITY_CONTRACT = "toolkit_adaptation_markdown_quality.v1"

# Default minimum persisted artifact size in UTF-8 bytes.
MIN_SUMMARY_BYTES = 100

# Markdown heading line: one or more leading '#' markers plus text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")

# Placeholder titles that are not meaningful adapted module titles.
_TITLE_PLACEHOLDER_RE = re.compile(
    r"^(title|untitled|module title|adventure title|placeholder|no title|tbd|new module)$",
    re.IGNORECASE,
)

# Fenced code blocks are stripped before raw-JSON and error-text scans.
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

# Quoted-key JSON signature used to detect raw JSON dumps.
_JSON_KEY_RE = re.compile(r'"([^"\n]{1,120})"\s*:')

# Playable location/area signal inside markdown headings or bold fields.
_LOCATION_SIGNAL_RE = re.compile(
    r"(?:^#{1,3}\s+[^\n]*(?:locations?|areas?|rooms?|quests?|encounters?|dungeons?))"
    r"|(?:^\*\*(?:location|area|room)\*\*\s*:)"
    r"|(?:^#{1,3}\s+[^\n]*\b(?:adventure)\b)",
    re.IGNORECASE | re.MULTILINE,
)

# Premise/plot content signal inside markdown headings or prose.
_PREMISE_SIGNAL_RE = re.compile(
    r"(?:^#{1,3}\s+[^\n]*(?:introduction|plot overview|premise|story so far|objective))"
    r"|(?:^\S[^\n]*\b(?:premise|main objective|objective|plot)\b)",
    re.IGNORECASE | re.MULTILINE,
)

# Bounded error/traceback/provider-failure signatures that must not appear in
# a readable adaptation summary.
_ERROR_TEXT_PATTERNS = (
    r"traceback \(most recent call last\)",
    r'file "[^"]*",\s*line\s+\d+',
    r"\bprovidererror\b",
    r"\bapierror\b",
    r"\bopenaierror\b",
    r"\brate ?limit(?:ed| exceeded)?\b",
    r"\bhttp ?error\b",
    r"\binternal server error\b",
    r"\[error\]",
    r"\bexception\s*:",
    r"\bvalueerror\s*:",
    r"\bkeyerror\s*:",
    r"\btypeerror\s*:",
    r"\battributeerror\s*:",
    r"\bzerodivisionerror\s*:",
    r"\bindexerror\s*:",
    r"\bnoneType object",
    r"\bstatus[ :]+(?:40[0134]|429|50[0234])\b",
)
_ERROR_TEXT_RES = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in _ERROR_TEXT_PATTERNS
)


def _strip_code_fences(text: str) -> str:
    """Remove fenced code blocks before JSON/error-text scanning."""
    return _CODE_FENCE_RE.sub("", text)


def _check_utf8(markdown: Any) -> Dict[str, Any]:
    """Verify the value is text that can be strictly encoded as UTF-8."""
    if not isinstance(markdown, str):
        return {"status": "fail", "reason": "summary_not_text"}
    if "\x00" in markdown:
        return {"status": "fail", "reason": "invalid_utf8"}
    try:
        encoded = markdown.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return {"status": "fail", "reason": "invalid_utf8"}
    try:
        roundtrip = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"status": "fail", "reason": "invalid_utf8"}
    if roundtrip != markdown:
        return {"status": "fail", "reason": "invalid_utf8"}
    return {"status": "pass", "reason": "valid_utf8", "bytes": len(encoded)}


def _extract_title(markdown: str) -> Optional[str]:
    """Return the first meaningful H1 title text or None."""
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group(1))
        if level != 1:
            continue
        title = match.group(2).strip()
        title = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", title)
        title = re.sub(r"[`*_~]", "", title).strip()
        if not title:
            continue
        return title
    return None


def _check_title(markdown: str) -> Dict[str, Any]:
    """Verify a non-empty meaningful module title exists as an H1 heading."""
    title = _extract_title(markdown)
    if title is None:
        return {"status": "fail", "reason": "summary_missing_title"}
    if len(title) < 4:
        return {"status": "fail", "reason": "summary_title_not_meaningful"}
    if _TITLE_PLACEHOLDER_RE.fullmatch(title):
        return {"status": "fail", "reason": "summary_title_not_meaningful"}
    return {"status": "pass", "reason": "summary_title_ok", "title": title}


def _check_headings(markdown: str) -> Dict[str, Any]:
    """Verify a readable heading structure: one title plus sub-sections."""
    headings: List[Dict[str, Any]] = []
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            headings.append(
                {
                    "level": len(match.group(1)),
                    "text": match.group(2).strip(),
                }
            )
    sub_headings = [h for h in headings if h["level"] >= 2]
    if len(headings) < 4:
        return {
            "status": "fail",
            "reason": "summary_insufficient_headings",
            "heading_count": len(headings),
        }
    if len(sub_headings) < 3:
        return {
            "status": "fail",
            "reason": "summary_insufficient_headings",
            "heading_count": len(headings),
            "sub_heading_count": len(sub_headings),
        }
    return {
        "status": "pass",
        "reason": "summary_headings_ok",
        "heading_count": len(headings),
        "sub_heading_count": len(sub_headings),
    }


def _check_playable_content(markdown: str) -> Dict[str, Any]:
    """Verify the summary contains playable locations and a plot premise."""
    scan_text = _strip_code_fences(markdown)
    location_hits = _LOCATION_SIGNAL_RE.findall(scan_text)
    premise_hits = _PREMISE_SIGNAL_RE.findall(scan_text)
    details: Dict[str, Any] = {
        "playable_locations": len(location_hits),
        "plot_premise": len(premise_hits),
    }
    if not location_hits or not premise_hits:
        return {
            "status": "fail",
            "reason": "summary_missing_playable_content",
            "details": details,
        }
    return {"status": "pass", "reason": "summary_playable_content_ok", "details": details}


def _check_notice(markdown: str, notice: str) -> Dict[str, Any]:
    """Verify the exact adaptation notice is present in the summary."""
    if not notice or notice not in markdown:
        return {"status": "fail", "reason": "summary_missing_adaptation_notice"}
    return {"status": "pass", "reason": "summary_adaptation_notice_ok"}


def _check_raw_json(markdown: str) -> Dict[str, Any]:
    """Reject raw JSON dumps while ignoring fenced JSON examples."""
    scan_text = _strip_code_fences(markdown).strip()
    if scan_text.startswith("{") and scan_text.endswith("}"):
        try:
            json.loads(scan_text)
            return {"status": "fail", "reason": "summary_contains_raw_json"}
        except (ValueError, TypeError):
            pass
    if scan_text.startswith("[") and scan_text.endswith("]"):
        try:
            json.loads(scan_text)
            return {"status": "fail", "reason": "summary_contains_raw_json"}
        except (ValueError, TypeError):
            pass
    quoted_key_count = len(_JSON_KEY_RE.findall(scan_text))
    if quoted_key_count >= 4:
        return {
            "status": "fail",
            "reason": "summary_contains_raw_json",
            "quoted_key_count": quoted_key_count,
        }
    return {"status": "pass", "reason": "summary_no_raw_json"}


def _check_error_text(markdown: str) -> Dict[str, Any]:
    """Reject traceback, provider-error, and failure-signature text."""
    scan_text = _strip_code_fences(markdown)
    for compiled in _ERROR_TEXT_RES:
        match = compiled.search(scan_text)
        if match:
            return {
                "status": "fail",
                "reason": "summary_contains_error_text",
                "matched": match.group(0)[:80],
            }
    return {"status": "pass", "reason": "summary_no_error_text"}


def check_adaptation_markdown_quality(
    markdown: Any,
    *,
    module_slug: str = "",
    min_bytes: int = MIN_SUMMARY_BYTES,
    notice: str = ADAPTATION_NOTICE,
) -> Dict[str, Any]:
    """Run the full deterministic Markdown quality contract.

    Returns a bounded structured result with one check per contract rule, a
    first-failure reason, and the aggregate failure list. No provider call and
    no file mutation is performed.
    """
    utf8_check = _check_utf8(markdown)
    if utf8_check["status"] == "fail":
        checks = {"utf8": utf8_check}
        return {
            "contract": ADAPTATION_MARKDOWN_QUALITY_CONTRACT,
            "valid": False,
            "reason": utf8_check["reason"],
            "failures": ["utf8"],
            "bytes": 0,
            "checks": checks,
        }

    encoded = markdown.encode("utf-8")
    byte_size = len(encoded)

    min_size_check = {
        "status": "pass" if byte_size >= int(min_bytes) else "fail",
        "reason": "generated_content_too_short"
        if byte_size < int(min_bytes)
        else "minimum_size_ok",
        "bytes": byte_size,
        "min_bytes": int(min_bytes),
    }

    title_check = _check_title(markdown)
    headings_check = _check_headings(markdown)
    playable_check = _check_playable_content(markdown)
    notice_check = _check_notice(markdown, notice)
    raw_json_check = _check_raw_json(markdown)
    error_text_check = _check_error_text(markdown)

    checks: Dict[str, Any] = {
        "utf8": utf8_check,
        "min_size": min_size_check,
        "title": title_check,
        "headings": headings_check,
        "playable_content": playable_check,
        "notice": notice_check,
        "no_raw_json": raw_json_check,
        "no_error_text": error_text_check,
    }

    failures: List[str] = []
    for name in (
        "utf8",
        "min_size",
        "title",
        "headings",
        "playable_content",
        "notice",
        "no_raw_json",
        "no_error_text",
    ):
        if checks[name]["status"] != "pass":
            failures.append(name)

    result: Dict[str, Any] = {
        "contract": ADAPTATION_MARKDOWN_QUALITY_CONTRACT,
        "valid": not failures,
        "failures": failures,
        "bytes": byte_size,
        "checks": checks,
    }
    if module_slug:
        result["module_slug"] = str(module_slug).strip()
    if failures:
        result["reason"] = checks[failures[0]]["reason"]
    else:
        result["reason"] = "adaptation_markdown_quality_pass"
    return result


def summarize_adaptation_markdown_quality(quality: Mapping[str, Any]) -> str:
    """Return a compact single-line diagnostic for build reports."""
    if not isinstance(quality, Mapping):
        return "adaptation_markdown_quality_unavailable"
    if quality.get("valid") is True:
        return "adaptation_markdown_quality_pass"
    failures = quality.get("failures") or []
    reason = quality.get("reason") or "adaptation_markdown_quality_failed"
    if failures:
        return "{}:{}".format(reason, ",".join(str(item) for item in failures))
    return str(reason)
