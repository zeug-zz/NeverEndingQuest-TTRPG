# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Reject host-only capabilities from the built player bundle."""

from __future__ import annotations

import hashlib
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
from web.extensions.player.assets import PRELOGIN_CSRF_PLACEHOLDER, load_player_client_assets


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
    "/api/player-sharing",
    "player-sharing",
    "PlayerSharingService",
    "PlayerSharingController",
    "SharingService",
    "SharingController",
    "copy-invitation",
    "opentunnel",
)
PLAYER_SHARING_BUNDLE_MARKERS = (
    "/api/player-sharing",
    "player-sharing",
    "PlayerSharingService",
    "PlayerSharingController",
    "SharingService",
    "SharingController",
    "copy-invitation",
    "opentunnel",
)
ROUTE_PARAMETER = re.compile(r"<")
OPEN_QUOTES = "\"'`"
BARE_EVENT = re.compile(r"^[a-z]+$")
# Socket.IO/Engine.IO reserves these names; their client transport uses them internally.
SOCKETIO_RESERVED_EVENT_NAMES = frozenset({
    "connect", "connect_error", "disconnect", "disconnecting", "error", "message",
    "open", "close", "ping", "pong", "packet", "upgrade", "upgradeError", "drain",
    "flush", "reconnect", "reconnect_attempt", "reconnect_error", "reconnect_failed",
    "newListener", "removeListener",
})


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


def _served_bundle_contents(root: Path) -> list[tuple[str, bytes]]:
    """Read precisely the verified shell and assets the player app serves."""
    assets = load_player_client_assets(root)
    return [("index.html", assets.shell_document)] + [
        (asset_id, asset.body) for asset_id, asset in sorted(assets.assets.items())
    ]


def _write_fixture_bundle(root: Path, javascript: str) -> None:
    """Write a minimal manifest-valid player bundle for source-free controls."""
    root.mkdir(parents=True, exist_ok=True)
    asset_id = "player-12345678.js"
    asset_body = javascript.encode("ascii")
    asset_digest = hashlib.sha256(asset_body).hexdigest()
    build_id = hashlib.sha256(
        (asset_id + "\t" + asset_digest + "\n").encode("ascii")
    ).hexdigest()[:32]
    shell = (
        '<!doctype html><html><head>'
        '<meta name="neq-client-build" content="%s">'
        '<meta name="neq-protocol-version" content="1">'
        '</head><body><script src="/static/player/%s"></script>%s'
        '</body></html>'
        % (build_id, asset_id, PRELOGIN_CSRF_PLACEHOLDER.decode("ascii"))
    ).encode("ascii")
    manifest = {
        "manifest_version": 1,
        "protocol_version": 1,
        "client_build_id": build_id,
        "shell": {
            "file": "index.html",
            "sha256": hashlib.sha256(shell).hexdigest(),
            "bytes": len(shell),
            "content_type": "text/html; charset=utf-8",
        },
        "assets": {
            asset_id: {
                "file": asset_id,
                "sha256": asset_digest,
                "bytes": len(asset_body),
                "content_type": "text/javascript; charset=utf-8",
            }
        },
    }
    (root / "index.html").write_bytes(shell)
    (root / asset_id).write_bytes(asset_body)
    (root / "player-manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":")), encoding="ascii"
    )


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
        if event in SOCKETIO_RESERVED_EVENT_NAMES:
            continue
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
    for relative_path, payload in _served_bundle_contents(root):
        content = payload.decode("utf-8", errors="ignore")
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
                hits.append((relative_path, f"{marker} [{match.groupdict().get('match', match.group(0))}]"))
    return hits


class PlayerBundleScanTests(unittest.TestCase):
    def _fixture_bundle(self, javascript: str = "export const player = true;") -> Path:
        root = Path("tmp/n2") / f"bundle-scan-{uuid.uuid4()}"
        _write_fixture_bundle(root, javascript)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def test_derived_host_route_and_event_markers_are_non_empty(self) -> None:
        routes, events = _host_markers()
        self.assertTrue(routes, "host-only route extraction returned no markers")
        self.assertTrue(events, "host-only event extraction returned no markers")
        self.assertTrue(set(events) - SOCKETIO_RESERVED_EVENT_NAMES, "no non-reserved host event markers remain")

    def test_served_bundle_has_no_host_capability_markers(self) -> None:
        manifest_path = DIST_ROOT / "player-manifest.json"
        if manifest_path.is_file():
            bundle_root = DIST_ROOT
        else:
            # This checkout has no built or committed dist; use the existing
            # isolated fixture approach, validated by the production asset loader.
            bundle_root = self._fixture_bundle()
        self.assertEqual(scan_bundle(bundle_root), [])

    def test_synthetic_positive_control_detects_route_event_and_fixed_marker(self) -> None:
        routes, events = _host_markers()
        parameterized = [route for route in routes if "<" in route]
        plain = [route for route in routes if "<" not in route]
        self.assertTrue(parameterized, "host-only parameterized route extraction returned no routes")
        self.assertTrue(plain, "host-only plain route extraction returned no routes")
        bundle = self._fixture_bundle()
        asset = bundle / "player-12345678.js"
        plain_marker = plain[0]
        parameterized_route = next(route for route in parameterized if route.startswith("/static/"))
        route_prefix = parameterized_route.split("<", 1)[0]
        non_reserved = sorted(set(events) - SOCKETIO_RESERVED_EVENT_NAMES)
        self.assertTrue(non_reserved, "host inventory has no non-reserved event marker")
        event = non_reserved[0]
        bare_events = [name for name in non_reserved if BARE_EVENT.fullmatch(name)]
        self.assertTrue(bare_events, "host inventory has no bare-word event for call-context control")
        bare_event = bare_events[0]
        injected = (
            f'"{plain_marker}"',
            f"'{event}'",
            f"`{route_prefix}foo.css`",
            FIXED_MARKERS[0],
            f".emit(`{bare_event}`)",
            "'/static/foo.css'",
            *PLAYER_SHARING_BUNDLE_MARKERS,
        )
        _write_fixture_bundle(bundle, "\n".join(injected))
        negative = bundle / "negative.js"
        negative.write_text(".on(`error`, `action`) '/static/player/x.js'", encoding="ascii")
        hits = scan_bundle(bundle)
        detected = {marker.split(" [", 1)[0] for _file, marker in hits}
        self.assertTrue({plain_marker, event, route_prefix, FIXED_MARKERS[0], "/static/"} <= detected)
        self.assertTrue(set(PLAYER_SHARING_BUNDLE_MARKERS) <= detected)
        negative_hits = [marker for file_name, marker in hits if file_name == "negative.js"]
        self.assertEqual(negative_hits, [])
        self.assertIn(bare_event, detected)


if __name__ == "__main__":
    unittest.main()
