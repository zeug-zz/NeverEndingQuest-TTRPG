# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free regression checks for installed web entrypoint paths."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.repo_paths import repository_root


ROOT = repository_root()


class InstallRootEntrypointTests(unittest.TestCase):
    def test_entrypoints_use_stable_root_from_alternate_cwd(self):
        original_cwd = os.getcwd()
        try:
            os.chdir("tmp")
            import run_web
            import launch_toolkit

            self.assertEqual(run_web.INSTALL_ROOT, ROOT)
            self.assertEqual(launch_toolkit.INSTALL_ROOT, ROOT)
            self.assertTrue((run_web.INSTALL_ROOT / "web" / "web_interface.py").is_file())
            self.assertTrue((launch_toolkit.INSTALL_ROOT / "web" / "web_interface.py").is_file())
        finally:
            os.chdir(original_cwd)

    def test_run_web_child_uses_rooted_script_and_cwd(self):
        import run_web

        fake_result = type("Result", (), {"returncode": 91})()
        original_cwd = os.getcwd()
        os.chdir("tmp")
        try:
            with patch.object(run_web, "subprocess") as subprocess_mock, patch.object(
                run_web, "time"
            ), patch("builtins.input", return_value=""):
                subprocess_mock.run.return_value = fake_result
                with patch.object(run_web.os.path, "exists", return_value=True):
                    run_web.main()
        finally:
            os.chdir(original_cwd)
            kwargs = subprocess_mock.run.call_args.kwargs
            command = subprocess_mock.run.call_args.args[0]
            self.assertEqual(Path(command[1]), ROOT / "web" / "web_interface.py")
            self.assertEqual(Path(kwargs["cwd"]), ROOT)

    def test_run_web_child_preserves_pythonpath_and_imports_utils(self):
        import run_web

        fake_result = type("Result", (), {"returncode": 91})()
        original_cwd = os.getcwd()
        os.chdir("tmp")
        try:
            with patch.dict(run_web.os.environ, {"PYTHONPATH": "existing-entry"}), patch.object(
                run_web, "subprocess"
            ) as subprocess_mock, patch.object(run_web, "time"):
                subprocess_mock.run.return_value = fake_result
                run_web.main()
                child_env = subprocess_mock.run.call_args.kwargs["env"]
                self.assertEqual(
                    child_env["PYTHONPATH"],
                    str(ROOT) + os.pathsep + "existing-entry",
                )
                child_command = subprocess_mock.run.call_args.args[0]
                child_cwd = subprocess_mock.run.call_args.kwargs["cwd"]
        finally:
            os.chdir(original_cwd)

        smoke = subprocess.run(
            [sys.executable, "-c", "import utils.media_paths"],
            cwd="tmp",
            env=child_env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(smoke.returncode, 0, smoke.stderr)
        self.assertEqual(Path(child_command[1]), ROOT / "web" / "web_interface.py")
        self.assertEqual(Path(child_cwd), ROOT)

    def test_toolkit_child_uses_rooted_script_and_cwd(self):
        import launch_toolkit

        process = type("Process", (), {"stdout": [], "wait": lambda self: None})()
        original_cwd = os.getcwd()
        os.chdir("tmp")
        try:
            with patch.object(launch_toolkit, "check_port", return_value=True), patch.object(
                launch_toolkit.subprocess, "Popen", return_value=process
            ) as popen, patch.object(launch_toolkit.webbrowser, "open"), patch.object(
                launch_toolkit.time, "sleep"
            ):
                self.assertEqual(launch_toolkit.main(), 0)
        finally:
            os.chdir(original_cwd)
        kwargs = popen.call_args.kwargs
        command = popen.call_args.args[0]
        self.assertEqual(Path(command[1]), ROOT / "web" / "web_interface.py")
        self.assertEqual(Path(kwargs["cwd"]), ROOT)


class WebRuntimeRootTests(unittest.TestCase):
    def test_declared_web_runtime_roots_are_not_cwd_relative(self):
        from web.extensions import live_chat_monitor
        from web.routes import toolkit_homebrew_routes, world_narrative_routes

        self.assertTrue(Path(live_chat_monitor.LIVE_CHAT_LOG_FILE).is_absolute())
        self.assertTrue(world_narrative_routes.USER_UPLOADS_ROOT.is_absolute())
        self.assertTrue(toolkit_homebrew_routes.TOOLKIT_HOMEBREW_UPLOAD_ROOT.is_absolute())

    def test_update_source_uses_install_root(self):
        source = Path("web/web_interface.py").read_text(encoding="utf-8")
        self.assertIn("repo_path = str(INSTALL_ROOT)", source)
        self.assertIn('cwd=repo_path', source)
        self.assertIn('resolve_update_target(repo_path=repo_path)', source)
        self.assertIn('str(INSTALL_ROOT / "web" / "web_interface.py")', source)


if __name__ == "__main__":
    unittest.main()
