# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

#!/usr/bin/env python3
"""One-shot unauthenticated OpenRouter model-listing check.

This script is not run during sequence step (a). The replacement GET requires
explicit Overseer authority because the earlier permitted GET did not preserve
the raw listing or confirm the exact model ID.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Callable
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_ROOT = REPO_ROOT / "tmp/router-rollout/mapping-pilot/mise-en-scene-offline/llm-staging"
AVAILABILITY_DIR = STAGING_ROOT / "availability-check"
GET_APPROVAL_PATH = STAGING_ROOT / "availability-get-approval.json"
MODEL_LIST_URL = "https://openrouter.ai/api/v1/models"
MODEL_ID = "openai/gpt-6-luna"
_MAX_LISTING_BYTES = 8 * 1024 * 1024


class AvailabilityCheckError(RuntimeError):
    """Raised when the one-shot check cannot safely preserve its evidence."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def _fetch_once(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "NEQ-llm-staging-availability/1.0"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        response = opener.open(request, timeout=15)
    except urllib.error.HTTPError as exc:
        return int(exc.code), exc.read(_MAX_LISTING_BYTES + 1)
    with response:
        status = int(response.getcode())
        body = response.read(_MAX_LISTING_BYTES + 1)
    return status, body


def _contained_output_dir(value: str | Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = STAGING_ROOT / candidate
    root = STAGING_ROOT.resolve(strict=True)
    lexical = Path(os.path.abspath(candidate))
    try:
        lexical_relative = lexical.relative_to(root)
    except ValueError as exc:
        raise AvailabilityCheckError("output directory must remain inside the staging scratch root") from exc
    current = root
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise AvailabilityCheckError("output directory must not traverse a symlink")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AvailabilityCheckError("output directory resolves outside the staging scratch root") from exc
    return resolved


def _write_new_private_file(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is not None:
        flags |= nofollow
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise AvailabilityCheckError("availability evidence already exists; refusing a second GET") from exc
    try:
        offset = 0
        while offset < len(contents):
            offset += os.write(descriptor, contents[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def check_model_availability(
    authority_attestation_path: str | Path = GET_APPROVAL_PATH,
    *,
    fetch_once: Callable[[str], tuple[int, bytes]] = _fetch_once,
    performed_utc: str | None = None,
) -> dict[str, object]:
    """Perform exactly one unauthenticated GET and preserve its raw body/hash."""

    approval_path = _contained_output_dir(authority_attestation_path)
    try:
        if not approval_path.is_file() or approval_path.is_symlink():
            raise OSError("approval must be a regular file")
        authority = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise AvailabilityCheckError("explicit Overseer authority for the replacement GET is required") from None
    if type(authority) is not dict or any(authority.get(key) != value for key, value in {
        "schema": "neq.openrouter_availability_get_approval.v1",
        "status": "APPROVED_REPLACEMENT_GET",
        "requested_model_id": MODEL_ID,
        "authorized_gets": 1,
        "approved_by": "overseer",
    }.items()):
        raise AvailabilityCheckError("explicit Overseer authority for the replacement GET is required")

    destination = _contained_output_dir(AVAILABILITY_DIR)
    reservation_path = destination / "get-reservation.json"
    raw_path = destination / "model-listing.json"
    attestation_path = destination / "attestation.json"
    if reservation_path.exists() or raw_path.exists() or attestation_path.exists():
        raise AvailabilityCheckError("availability evidence already exists; refusing a second GET")

    reservation = {
        "schema": "neq.openrouter_availability_get_reservation.v1",
        "requested_model_id": MODEL_ID,
        "authorized_gets": 1,
        "reservation_status": "CONSUMED_BEFORE_DISPATCH",
    }
    _write_new_private_file(
        reservation_path,
        (json.dumps(reservation, sort_keys=True, indent=2) + "\n").encode("ascii"),
    )

    try:
        status, raw_listing = fetch_once(MODEL_LIST_URL)
    except Exception:
        raise AvailabilityCheckError("availability GET failed; no retry is permitted") from None
    if type(status) is not int or type(raw_listing) is not bytes:
        raise AvailabilityCheckError("availability transport returned an invalid result; no retry is permitted")
    if len(raw_listing) > _MAX_LISTING_BYTES:
        raise AvailabilityCheckError("availability listing exceeded the evidence size limit; no retry is permitted")

    digest = hashlib.sha256(raw_listing).hexdigest()
    performed = performed_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    _write_new_private_file(raw_path, raw_listing)

    model_present = False
    parse_status = "valid_json"
    try:
        decoded = json.loads(raw_listing.decode("utf-8"))
        rows = decoded.get("data") if type(decoded) is dict else None
        model_present = type(rows) is list and any(
            type(row) is dict and row.get("id") == MODEL_ID for row in rows
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        parse_status = "invalid_json"

    confirmed = status == 200 and model_present
    attestation: dict[str, object] = {
        "schema": "neq.openrouter_model_availability.v1",
        "method": "GET",
        "url": MODEL_LIST_URL,
        "performed_utc": performed,
        "http_status": status,
        "requested_model_id": MODEL_ID,
        "exact_model_id_present": model_present,
        "parse_status": parse_status,
        "raw_listing_path": str(raw_path.relative_to(STAGING_ROOT)),
        "raw_listing_sha256": digest,
        "request_count": 1,
        "authenticated": False,
        "redirects_followed": False,
        "verdict": "CONFIRMED" if confirmed else "UNCONFIRMED",
        "generation_calls": 0,
    }
    _write_new_private_file(attestation_path, (json.dumps(attestation, sort_keys=True, indent=2) + "\n").encode("ascii"))
    return attestation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    try:
        attestation = check_model_availability()
    except AvailabilityCheckError:
        print("availability check blocked; inspect no credential or raw payload output")
        return 2
    print(json.dumps({
        "verdict": attestation["verdict"],
        "requested_model_id": MODEL_ID,
        "raw_listing_sha256": attestation["raw_listing_sha256"],
        "generation_calls": 0,
    }, sort_keys=True))
    return 0 if attestation["verdict"] == "CONFIRMED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
