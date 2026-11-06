# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Provider-free validation and serving tests for the player client bundle."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from web.extensions.player import (
    PLAYER_HOST,
    PLAYER_PORT,
    PlayerClientAssetsError,
    PlayerListener,
    PlayerSnapshot,
    create_app,
)
from web.extensions.player.auth import PlayerSecurity


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = Path("tmp/n2")
MANIFEST_NAME = "player-manifest.json"
SHELL_NAME = "index.html"
CSRF_PLACEHOLDER = "__NEQ_PRELOGIN_CSRF_NONCE__"
JS_ASSET_ID = "player-AbCdEfGh.js"
CSS_ASSET_ID = "player-Style1234.css"
JS_BODY = b"window.playerBundle = true;\n"
CSS_BODY = b"body{font-family:system-ui,sans-serif}\n"


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _make_bundle(root: Path) -> dict[str, Any]:
    """Write one deterministic, complete manifest fixture below tmp/n2."""
    root.mkdir(parents=True, exist_ok=True)
    asset_bodies = {JS_ASSET_ID: JS_BODY, CSS_ASSET_ID: CSS_BODY}
    asset_records: dict[str, dict[str, object]] = {}
    for asset_id, body in asset_bodies.items():
        asset_type = (
            "text/javascript; charset=utf-8"
            if asset_id.endswith(".js")
            else "text/css; charset=utf-8"
        )
        (root / asset_id).write_bytes(body)
        asset_records[asset_id] = {
            "file": asset_id,
            "sha256": _sha256(body),
            "bytes": len(body),
            "content_type": asset_type,
        }
    build_rows = "".join(
        f"{asset_id}\t{asset_records[asset_id]['sha256']}\n"
        for asset_id in sorted(asset_records)
    )
    build_id = hashlib.sha256(build_rows.encode("ascii")).hexdigest()[:32]
    shell = (
        "<!doctype html>\n"
        "<html lang=\"en\"><head>"
        f"<meta name=\"neq-client-build\" content=\"{build_id}\">"
        "<meta name=\"neq-protocol-version\" content=\"1\">"
        f"<link rel=\"stylesheet\" href=\"/static/player/{CSS_ASSET_ID}\">"
        f"<script type=\"module\" src=\"/static/player/{JS_ASSET_ID}\"></script>"
        "</head><body><main><h1>Player login</h1>"
        "<form method=\"post\" action=\"/api/player/login\">"
        f"<input type=\"hidden\" name=\"csrf_token\" value=\"{CSRF_PLACEHOLDER}\">"
        "<label>Password <input type=\"password\" name=\"password\" "
        "autocomplete=\"current-password\" maxlength=\"1024\" required></label>"
        "<button type=\"submit\">Log in</button></form></main>"
        "<div id=\"root\"></div></body></html>"
    ).encode("ascii")
    (root / SHELL_NAME).write_bytes(shell)
    manifest: dict[str, Any] = {
        "manifest_version": 1,
        "protocol_version": 1,
        "client_build_id": build_id,
        "shell": {
            "file": SHELL_NAME,
            "sha256": _sha256(shell),
            "bytes": len(shell),
            "content_type": "text/html; charset=utf-8",
        },
        "assets": asset_records,
    }
    _write_manifest(root, manifest)
    return manifest


def _write_manifest(root: Path, manifest: dict[str, Any]) -> None:
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def _dispatch_http(
    app: Any,
    path: str,
    *,
    raw_path: bytes | None = None,
    host: str | None = None,
    cookie: str | None = None,
    origin: str | None = None,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    messages: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [(b"host", (host or f"{PLAYER_HOST}:{PLAYER_PORT}").encode("ascii"))],
    }
    if cookie is not None:
        scope["headers"].append((b"cookie", f"neq_player_session={cookie}".encode("ascii")))
    if origin is not None:
        scope["headers"].append((b"origin", origin.encode("ascii")))
    scope["headers"].extend(extra_headers or [])
    if raw_path is not None:
        scope["raw_path"] = raw_path
    asyncio.run(app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), start["headers"], body


def _headers(headers: list[tuple[bytes, bytes]]) -> dict[bytes, bytes]:
    return {name.lower(): value for name, value in headers}


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener_socket:
        listener_socket.bind((PLAYER_HOST, 0))
        return int(listener_socket.getsockname()[1])


class PlayerClientAssetsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="player-client-assets-",
            dir=SCRATCH_ROOT,
        )
        self.scratch = Path(self._temporary.name)
        self.bundle_root = self.scratch / "bundle"
        self.manifest = _make_bundle(self.bundle_root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def _new_bundle(self, name: str) -> tuple[Path, dict[str, Any]]:
        root = self.scratch / name
        return root, _make_bundle(root)

    def test_shell_and_only_manifest_assets_are_served_with_security_headers(self) -> None:
        app = create_app(build_root=self.bundle_root)
        status, shell_headers, shell = _dispatch_http(app, "/")
        shell_header_map = _headers(shell_headers)
        self.assertEqual(status, 200)
        self.assertIn(b"Player login", shell)
        self.assertNotIn(CSRF_PLACEHOLDER.encode("ascii"), shell)
        self.assertEqual(shell_header_map[b"content-type"], b"text/html; charset=utf-8")
        self.assertEqual(shell_header_map[b"cache-control"], b"no-store")
        self.assertEqual(shell_header_map[b"x-content-type-options"], b"nosniff")
        self.assertIn(b"script-src 'self'", shell_header_map[b"content-security-policy"])
        self.assertIn(b"style-src 'self'", shell_header_map[b"content-security-policy"])
        self.assertIn(b"connect-src 'self'", shell_header_map[b"content-security-policy"])
        self.assertEqual(shell_header_map[b"cross-origin-resource-policy"], b"same-origin")

        for asset_id, body, content_type in (
            (JS_ASSET_ID, JS_BODY, b"text/javascript; charset=utf-8"),
            (CSS_ASSET_ID, CSS_BODY, b"text/css; charset=utf-8"),
        ):
            with self.subTest(asset_id=asset_id):
                asset_status, asset_headers, asset_body = _dispatch_http(
                    app,
                    f"/static/player/{asset_id}",
                )
                asset_header_map = _headers(asset_headers)
                self.assertEqual(asset_status, 200)
                self.assertEqual(asset_body, body)
                self.assertEqual(asset_header_map[b"content-type"], content_type)
                self.assertEqual(
                    asset_header_map[b"cache-control"],
                    b"public, max-age=31536000, immutable",
                )
                self.assertEqual(asset_header_map[b"x-content-type-options"], b"nosniff")
                self.assertIn(b"default-src 'none'", asset_header_map[b"content-security-policy"])
                self.assertEqual(
                    asset_header_map[b"cross-origin-resource-policy"],
                    b"same-origin",
                )

        legacy_css_status, _headers_value, _body = _dispatch_http(
            app,
            "/static/player/shell.css",
        )
        self.assertEqual(legacy_css_status, 404)

    def test_manifest_and_all_assets_are_verified_before_listener_can_bind(self) -> None:
        missing_manifest_root = self.scratch / "missing-manifest"
        missing_manifest_root.mkdir()
        invalid_roots = [
            ("missing manifest", missing_manifest_root),
        ]
        corrupt_root, _manifest = self._new_bundle("corrupt-json")
        (corrupt_root / MANIFEST_NAME).write_text("{", encoding="ascii")
        invalid_roots.append(("corrupt JSON", corrupt_root))

        digest_root, _manifest = self._new_bundle("digest-mismatch")
        (digest_root / JS_ASSET_ID).write_bytes(b"tampered after manifest")
        invalid_roots.append(("digest mismatch", digest_root))

        missing_asset_root, _manifest = self._new_bundle("missing-asset")
        (missing_asset_root / CSS_ASSET_ID).unlink()
        invalid_roots.append(("missing asset", missing_asset_root))

        for label, root in invalid_roots:
            with self.subTest(bundle=label):
                with self.assertRaises(PlayerClientAssetsError):
                    create_app(build_root=root).preflight_client_assets()

        port = _free_loopback_port()
        listener = PlayerListener(test_only_port=port, build_root=missing_manifest_root)
        with self.assertRaises(PlayerClientAssetsError):
            listener.start()
        self.assertFalse(listener.is_running)
        unavailable_status, _headers_value, unavailable_body = _dispatch_http(
            listener.app,
            "/",
            host=f"{PLAYER_HOST}:{port}",
        )
        self.assertEqual(unavailable_status, 503)
        self.assertEqual(unavailable_body, b'{"error":"client_assets_unavailable"}')
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((PLAYER_HOST, port))

    def test_manifest_rejects_extra_fields_unsupported_versions_and_bad_ids(self) -> None:
        mutations = (
            ("extra field", lambda manifest: manifest.update({"unexpected": True})),
            ("manifest version", lambda manifest: manifest.update({"manifest_version": 2})),
            ("protocol version", lambda manifest: manifest.update({"protocol_version": 2})),
            (
                "bad asset ID",
                lambda manifest: manifest["assets"].update(
                    {"../escape.js": manifest["assets"].pop(JS_ASSET_ID)}
                ),
            ),
        )
        for label, mutate in mutations:
            with self.subTest(manifest=label):
                root, manifest = self._new_bundle(f"invalid-{label.replace(' ', '-')}")
                mutate(manifest)
                _write_manifest(root, manifest)
                with self.assertRaises(PlayerClientAssetsError):
                    create_app(build_root=root).preflight_client_assets()

    def test_manifest_rejects_unsupported_content_types(self) -> None:
        root, manifest = self._new_bundle("unsupported-content-type")
        manifest["assets"][JS_ASSET_ID]["content_type"] = "application/octet-stream"
        _write_manifest(root, manifest)
        with self.assertRaises(PlayerClientAssetsError):
            create_app(build_root=root).preflight_client_assets()

    def test_symlink_escape_and_incomplete_shell_reference_are_rejected(self) -> None:
        symlink_root, _manifest = self._new_bundle("symlink-escape")
        external_file = self.scratch / "outside.js"
        external_file.write_bytes(b"must not be served")
        (symlink_root / JS_ASSET_ID).unlink()
        os.symlink(external_file, symlink_root / JS_ASSET_ID)
        with self.assertRaises(PlayerClientAssetsError):
            create_app(build_root=symlink_root).preflight_client_assets()

        incomplete_root, incomplete_manifest = self._new_bundle("unlisted-reference")
        shell_path = incomplete_root / SHELL_NAME
        shell = shell_path.read_bytes().replace(
            f"/static/player/{JS_ASSET_ID}".encode("ascii"),
            b"/static/player/unlisted-AbCdEfGh.js",
        )
        shell_path.write_bytes(shell)
        incomplete_manifest["shell"]["sha256"] = _sha256(shell)
        incomplete_manifest["shell"]["bytes"] = len(shell)
        _write_manifest(incomplete_root, incomplete_manifest)
        with self.assertRaises(PlayerClientAssetsError):
            create_app(build_root=incomplete_root).preflight_client_assets()

    def test_asset_requests_reject_traversal_encoded_unknown_and_overlong_ids(self) -> None:
        app = create_app(build_root=self.bundle_root)
        requests = (
            ("traversal", "/static/player/../outside.js", None),
            (
                "encoded traversal",
                "/static/player/../outside.js",
                b"/static/player/%2e%2e%2foutside.js",
            ),
            (
                "encoded otherwise-valid ID",
                f"/static/player/{JS_ASSET_ID}",
                f"/static/player/%70{JS_ASSET_ID[1:]}".encode("ascii"),
            ),
            ("unknown ID", "/static/player/unknown-AbCdEfGh.js", None),
            ("overlong ID", "/static/player/" + ("a" * 129), None),
        )
        for label, path, raw_path in requests:
            with self.subTest(request=label):
                status, _headers_value, body = _dispatch_http(app, path, raw_path=raw_path)
                self.assertEqual(status, 404)
                self.assertEqual(body, b'{"error":"not_found"}')
                self.assertNotIn(b"outside.js", body)

    def test_post_preflight_tampering_cannot_change_served_asset_bytes(self) -> None:
        app = create_app(build_root=self.bundle_root)
        app.preflight_client_assets()
        (self.bundle_root / JS_ASSET_ID).write_bytes(b"tampered after readiness")
        status, _headers_value, body = _dispatch_http(
            app,
            f"/static/player/{JS_ASSET_ID}",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, JS_BODY)

    def test_snapshot_client_version_mismatch_is_bounded_and_precedes_projection(self) -> None:
        security = PlayerSecurity(lambda: None)
        grant = security.create_session()
        self.assertIsNotNone(grant)
        assert grant is not None
        gateway = mock.Mock()
        gateway.read_snapshot.return_value = PlayerSnapshot(
            1,
            {
                "party": {
                    "members": [],
                    "active_character": None,
                    "active_character_revision": 0,
                    "world": {},
                },
                "busy": False,
            },
        )
        app = create_app(
            gateway=gateway,
            security=security,
            build_root=self.bundle_root,
        )
        build_id = str(self.manifest["client_build_id"])
        current_version = [
            (b"x-neq-client-build", build_id.encode("ascii")),
            (b"x-neq-protocol-version", b"1"),
        ]
        mismatch_cases = (
            ("stale build", [(b"x-neq-client-build", b"0" * 32), current_version[1]]),
            ("unsupported protocol", [current_version[0], (b"x-neq-protocol-version", b"2")]),
            ("missing build", [current_version[1]]),
            ("missing protocol", [current_version[0]]),
            ("malformed build", [(b"x-neq-client-build", b"not-a-build"), current_version[1]]),
            ("malformed protocol", [current_version[0], (b"x-neq-protocol-version", b"1.0")]),
            ("duplicate header", current_version + [current_version[0]]),
        )
        for label, version_headers in mismatch_cases:
            with self.subTest(version=label):
                status, _headers_value, body = _dispatch_http(
                    app,
                    "/api/player/snapshot",
                    cookie=grant.cookie_value,
                    origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
                    extra_headers=version_headers,
                )
                self.assertEqual(status, 409)
                self.assertEqual(body, b'{"error":"client_version_mismatch"}')
                self.assertNotIn(build_id.encode("ascii"), body)
                gateway.read_snapshot.assert_not_called()

        unauthenticated_status, _headers_value, unauthenticated_body = _dispatch_http(
            app,
            "/api/player/snapshot",
            extra_headers=[
                (b"x-neq-client-build", b"0" * 32),
                (b"x-neq-protocol-version", b"1"),
            ],
        )
        self.assertEqual(unauthenticated_status, 404)
        self.assertEqual(unauthenticated_body, b'{"error":"not_found"}')
        gateway.read_snapshot.assert_not_called()

        bad_origin_status, _headers_value, bad_origin_body = _dispatch_http(
            app,
            "/api/player/snapshot",
            cookie=grant.cookie_value,
            origin="http://attacker.invalid",
            extra_headers=[
                (b"x-neq-client-build", b"0" * 32),
                (b"x-neq-protocol-version", b"1"),
            ],
        )
        self.assertEqual(bad_origin_status, 403)
        self.assertEqual(bad_origin_body, b'{"error":"request_rejected"}')
        gateway.read_snapshot.assert_not_called()

        valid_status, _headers_value, valid_body = _dispatch_http(
            app,
            "/api/player/snapshot",
            cookie=grant.cookie_value,
            origin=f"http://{PLAYER_HOST}:{PLAYER_PORT}",
            extra_headers=current_version,
        )
        self.assertEqual(valid_status, 200)
        self.assertEqual(
            set(json.loads(valid_body)),
            {
                "schema_version",
                "instance_id",
                "session_epoch",
                "revision",
                "event_cursor",
                "projection",
            },
        )
        gateway.read_snapshot.assert_called_once_with()

    def test_host_launcher_imports_without_a_dist_directory(self) -> None:
        no_dist_cwd = self.scratch / "host-without-dist"
        no_dist_cwd.mkdir()
        self.assertFalse((no_dist_cwd / "web" / "frontend" / "dist").exists())
        environment = os.environ.copy()
        existing_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            entry
            for entry in (str(REPOSITORY_ROOT), existing_pythonpath)
            if entry
        )
        probe_script = (
            "import run_web\n"
            "import sys\n"
            "assert 'web.extensions.player.assets' not in sys.modules\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe_script],
            cwd=no_dist_cwd,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout={completed.stdout}\nstderr={completed.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
