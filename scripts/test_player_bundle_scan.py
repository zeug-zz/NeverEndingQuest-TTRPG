# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Reject host-only capabilities from the built player bundle."""

from __future__ import annotations

import json
import re
import shutil
import unittest
import uuid
from pathlib import Path

from scripts.test_player_route_inventory import discover_host_surfaces
from web.extensions.player.capabilities import (
    HOST_ONLY,
    HOST_SURFACE_CLASSIFICATION,
    PLAYER_HTTP_ALLOWLIST,
    PLAYER_SOCKET_EMISSION_ALLOWLIST,
    PLAYER_SOCKET_EVENT_ALLOWLIST,
    PLAYER_SOCKET_LIFECYCLE_EVENTS,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = REPOSITORY_ROOT / "web" / "frontend" / "dist"
FIXED_MARKERS = (
    "/toolkit",
    "/api/settings",
    "game_interface.html",
    "shutdown",
    "restart_server",
    "debug_config",
    "party_tracker.json",
    "update_character_info",
    "MULTIPLAYER_MODE",
    "config.py",
)
ROUTE_PARAMETER = re.compile(r"<")
OPEN_QUOTES = "\"'`"
BARE_EVENT = re.compile(r"^[a-z]+$")
SOCKET_CALL_PREFIX = re.compile(r"\.(?:emit|on|once|off)\(\s*$")


def _host_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Derive distinctive forbidden paths and event names from host inventory."""
    inventory = discover_host_surfaces()
    if inventory.discovery_errors:
        raise AssertionError("host inventory errors: " + "; ".join(inventory.discovery_errors))
    player_routes = {route for _method, route in PLAYER_HTTP_ALLOWLIST}
    host_only_routes = {
        key.removeprefix("http:")
        for key, classification in HOST_SURFACE_CLASSIFICATION.items()
        if key.startswith("http:") and classification == HOST_ONLY
    }
    routes = {
        route
        for route in inventory.http_routes
        if route in host_only_routes and route not in player_routes and route != "/"
    }
    routes = {route for route in routes if len(route.split("<", 1)[0]) >= 5}
    host_events = (
        (inventory.inbound_events - PLAYER_SOCKET_EVENT_ALLOWLIST - PLAYER_SOCKET_LIFECYCLE_EVENTS)
        | (inventory.emissions - PLAYER_SOCKET_EMISSION_ALLOWLIST)
    ) - PLAYER_SOCKET_LIFECYCLE_EVENTS
    host_only_classified = {
        key.split(":", 1)[1]
        for key, classification in HOST_SURFACE_CLASSIFICATION.items()
        if classification == HOST_ONLY and key.startswith(("inbound:", "emission:"))
    }
    events = host_events & host_only_classified
    return tuple(sorted(routes)), tuple(sorted(events))


def _bundle_files(root: Path) -> set[Path]:
    """Return manifest shell/assets plus every regular file in the flat output."""
    manifest = json.loads((root / "player-manifest.json").read_text(encoding="utf-8"))
    listed = {manifest["shell"]["file"]}
    listed.update(record["file"] for record in manifest["assets"].values())
    listed.update(path.name for path in root.iterdir() if path.is_file())
    return {root / name for name in listed if (root / name).is_file()}


def scan_bundle(root: Path) -> list[tuple[str, str]]:
    """Return (relative file, forbidden marker) hits across the built output."""
    routes, events = _host_markers()
    patterns: list[tuple[str, re.Pattern[str]]] = []
    player_static_prefixes = tuple(
        route.split("<", 1)[0]
        for _method, route in PLAYER_HTTP_ALLOWLIST
        if route.startswith("/static/")
    )
    for route in routes:
        if "<" in route:
            marker = route.split("<", 1)[0]
            if marker in ("/", "/static/player/") or len(marker) < 5:
                continue
            pattern = re.compile(rf"(?P<quote>[\"'`])(?P<match>{re.escape(marker)})")
        else:
            marker = route
            pattern = re.compile(rf"(?P<match>(?P<quote>[\"'`]){re.escape(marker)}(?P=quote))")
        patterns.append((marker, pattern))
    for event in events:
        literal = rf"(?P<quote>[\"'`]){re.escape(event)}(?P=quote)"
        if BARE_EVENT.fullmatch(event):
            # Bare words like action/error also occur in React DOM internals;
            # only treat them as host events when passed to a Socket.IO method.
            event_pattern = re.compile(rf"\.(?:emit|on|once|off)\(\s*(?P<match>{literal})")
        else:
            event_pattern = re.compile(rf"(?P<match>{literal})")
        patterns.append((event, event_pattern))
    patterns.extend((marker, re.compile(re.escape(marker))) for marker in FIXED_MARKERS)
    hits: list[tuple[str, str]] = []
    for path in sorted(_bundle_files(root)):
        content = path.read_bytes().decode("utf-8", errors="ignore")
        for marker, pattern in patterns:
            for match in pattern.finditer(content):
                parameterized_marker = any(
                    route.startswith(marker) and "<" in route
                    for route in routes
                )
                if parameterized_marker:
                    quote_start = match.start("quote") if "quote" in match.groupdict() else match.start()
                    position = quote_start + 1
                    if any(content.startswith(prefix, position) for prefix in player_static_prefixes):
                        continue
                hits.append((path.relative_to(root).as_posix(), f"{marker} [{match.groupdict().get('match', match.group(0))}]"))
    return hits


class PlayerBundleScanTests(unittest.TestCase):
    def test_derived_host_route_and_event_markers_are_non_empty(self) -> None:
        routes, events = _host_markers()
        self.assertTrue(routes, "host-only route extraction returned no markers")
        self.assertTrue(events, "host-only event extraction returned no markers")

    def test_built_bundle_has_no_host_capability_markers(self) -> None:
        manifest_path = DIST_ROOT / "player-manifest.json"
        self.assertTrue(
            manifest_path.is_file(),
            "Built player manifest is missing; run `npm --prefix web/frontend run build` first.",
        )
        self.assertEqual(scan_bundle(DIST_ROOT), [])

    def test_synthetic_positive_control_detects_route_event_and_fixed_marker(self) -> None:
        routes, events = _host_markers()
        parameterized = [route for route in routes if "<" in route]
        plain = [route for route in routes if "<" not in route]
        self.assertTrue(parameterized, "host-only parameterized route extraction returned no routes")
        self.assertTrue(plain, "host-only plain route extraction returned no routes")
        scratch = Path("tmp/n2") / f"bundle-scan-{uuid.uuid4()}"
        scratch.mkdir(parents=True)
        try:
            if (DIST_ROOT / "player-manifest.json").is_file():
                shutil.copytree(DIST_ROOT, scratch / "bundle")
                bundle = scratch / "bundle"
            else:
                bundle = scratch / "bundle"
                bundle.mkdir()
                (bundle / "player-manifest.json").write_text(
                    json.dumps({"shell": {"file": "index.html"}, "assets": {"test.js": {"file": "test.js"}}}),
                    encoding="utf-8",
                )
                (bundle / "index.html").write_text("<html></html>", encoding="ascii")
                (bundle / "test.js").write_text("", encoding="ascii")
            asset = next(path for path in bundle.iterdir() if path.suffix == ".js")
            plain_marker = plain[0]
            parameterized_route = next(route for route in parameterized if route.startswith("/static/"))
            route_prefix = parameterized_route.split("<", 1)[0]
            bare_events = [event for event in events if BARE_EVENT.fullmatch(event)]
            self.assertTrue(bare_events, "host inventory has no bare-word event for call-context control")
            event = bare_events[0]
            injected = (
                f'"{plain_marker}"',
                f"'{event}'",
                f"`{route_prefix}foo.css`",
                FIXED_MARKERS[0],
                f".emit(`{event}`)",
                "'/static/foo.css'",
            )
            asset.write_text("\n".join(injected), encoding="ascii")
            negative = bundle / "negative.js"
            negative.write_text(f"`{event}` '/static/player/x.js'", encoding="ascii")
            hits = scan_bundle(bundle)
            detected = {marker.split(" [", 1)[0] for _file, marker in hits}
            self.assertTrue({plain_marker, event, route_prefix, FIXED_MARKERS[0], "/static/"} <= detected)
            negative_hits = [marker for file_name, marker in hits if file_name == "negative.js"]
            self.assertEqual(negative_hits, [])
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
