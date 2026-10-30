"""Focused launcher tests for the Capture_Arena headless-start contract."""

import contextlib
import io
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import run_web


class _FakePath:
    def __init__(self, value, *, exists=False):
        self.value = value
        self._exists = exists

    def exists(self):
        return self._exists

    def mkdir(self, **_kwargs):
        return None

    def __str__(self):
        return self.value


class RunWebCaptureHeadlessTests(unittest.TestCase):
    def _run_launcher(self, parent_browser_flag, return_codes):
        resolved = {}

        def resolve(path, root=None):
            del root
            if path not in resolved:
                resolved[path] = _FakePath(
                    f"sandbox/{path}", exists=(path == "config.py")
                )
            return resolved[path]

        subprocess_run = mock.Mock(
            side_effect=[SimpleNamespace(returncode=code) for code in return_codes]
        )
        env_patch = (
            mock.patch.dict(os.environ, {"NEQ_OPEN_BROWSER": parent_browser_flag})
            if parent_browser_flag is not None
            else mock.patch.dict(os.environ, {}, clear=True)
        )
        with (
            env_patch,
            mock.patch.object(run_web, "INSTALL_ROOT", "sandbox"),
            mock.patch.object(run_web, "resolve_repository_path", side_effect=resolve),
            mock.patch.object(run_web.subprocess, "run", subprocess_run),
            mock.patch.object(run_web.time, "sleep"),
            mock.patch.object(run_web.sys, "path", list(sys.path)),
            mock.patch.dict(sys.modules, {"config": SimpleNamespace(WEB_PORT=8360)}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run_web.main()

        return [call.kwargs["env"]["NEQ_OPEN_BROWSER"] for call in subprocess_run.call_args_list]

    def test_explicit_zero_stays_headless_on_first_spawn_and_restarts(self):
        self.assertEqual(
            self._run_launcher("0", [0, 0, 91]),
            ["0", "0", "0"],
        )

    def test_unset_defaults_to_browser_once_then_restarts_headless(self):
        self.assertEqual(
            self._run_launcher(None, [0, 91]),
            ["1", "0"],
        )


if __name__ == "__main__":
    unittest.main()
