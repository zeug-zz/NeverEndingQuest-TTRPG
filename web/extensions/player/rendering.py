# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Constrain player display text to non-executable Markdown and safe links."""

from __future__ import annotations

import html
import re
from urllib.parse import unquote, urlsplit

from .limits import MAX_PLAYER_TEXT_BYTES

_MARKDOWN_LINK_RE = re.compile(
    r"(?P<image>!)?\[(?P<label>[^\]\r\n]{0,512})\]"
    r"\(\s*(?P<destination><[^>\r\n]{1,2048}>|"
    r"(?:\\.|[^()\s\r\n]){1,2048}"
    r"(?:\([^()\r\n]{0,512}\)(?:\\.|[^()\s\r\n]){0,2048})*)"
    r"(?:\s+['\"][^'\"\r\n]{0,256}['\"])?\s*\)"
)
_URL_CANDIDATE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])([A-Za-z0-9%&#;.+-]{1,64}):"
    r"[^\s<>\])}]*"
)
_DISALLOWED_SCHEMES = frozenset(
    {"javascript", "data", "vbscript", "file", "blob", "filesystem"}
)
_ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto"})


def render_safe_markdown(value: object) -> str | None:
    """Return a bounded Markdown subset with HTML and unsafe links neutralized.

    Raw HTML is escaped so Markdown consumers display it as text. Images are
    reduced to their alt text; media must use the player media-ID endpoint.
    Only explicit HTTP(S) and mailto links survive Markdown link parsing.
    """
    if not isinstance(value, str):
        return None
    try:
        if len(value.encode("utf-8")) > MAX_PLAYER_TEXT_BYTES:
            return None
    except UnicodeEncodeError:
        return None

    text = html.unescape(value)

    def replace_markdown_link(match: re.Match[str]) -> str:
        label = match.group("label")
        if match.group("image"):
            return label
        destination = match.group("destination").strip()
        if destination.startswith("<") and destination.endswith(">"):
            destination = destination[1:-1]
        if not _safe_link_destination(destination):
            return label
        return f"[{label}]({destination})"

    text = _MARKDOWN_LINK_RE.sub(replace_markdown_link, text)

    def remove_unsafe_url(match: re.Match[str]) -> str:
        candidate = match.group(1)
        normalized = html.unescape(candidate)
        for _index in range(3):
            normalized = unquote(normalized)
        normalized = "".join(
            character
            for character in normalized
            if not character.isspace() and ord(character) >= 32
        ).casefold()
        if normalized in _DISALLOWED_SCHEMES:
            return "[unsafe URL removed]"
        return match.group(0)

    text = _URL_CANDIDATE_RE.sub(remove_unsafe_url, text)
    return html.escape(text, quote=False)


def _safe_link_destination(destination: str) -> bool:
    if not destination or any(
        ord(character) < 32 or character in "\\\"'<>"
        for character in destination
    ):
        return False
    normalized = html.unescape(destination)
    for _index in range(3):
        normalized = unquote(normalized)
    compact = "".join(
        character
        for character in normalized
        if not character.isspace() and ord(character) >= 32
    )
    try:
        parsed = urlsplit(compact)
    except ValueError:
        return False
    scheme = parsed.scheme.casefold()
    if scheme not in _ALLOWED_LINK_SCHEMES:
        return False
    if scheme in {"http", "https"}:
        return bool(parsed.netloc)
    return bool(parsed.path)
