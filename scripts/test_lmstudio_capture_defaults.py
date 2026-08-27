"""Provider-free tests for LM Studio forwarder capture boundaries."""

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class LMStudioCaptureDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEQ_LMSTUDIO_CAPTURE_PAYLOADS", None)
            cls.forwarder_module = importlib.import_module("lmstudio_forwarder")

    def _new_forwarder(self, value=None, root=None):
        environment = {}
        if value is not None:
            environment["NEQ_LMSTUDIO_CAPTURE_PAYLOADS"] = value
        root_patch = patch.object(self.forwarder_module, "FORWARDER_DIRECTORY", root)
        with patch.dict(os.environ, environment, clear=False), root_patch:
            if value is None:
                os.environ.pop("NEQ_LMSTUDIO_CAPTURE_PAYLOADS", None)
            return self.forwarder_module.LMStudioForwarder()

    def test_capture_requires_recognized_true_value(self):
        for value in (None, "", " ", "false", "0", "no", "off", "maybe"):
            with self.subTest(value=value):
                forwarder = self._new_forwarder(value)
                self.assertFalse(forwarder.capture_logs)

        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory(dir="tmp") as temp_dir:
                    forwarder = self._new_forwarder(value, Path(temp_dir))
                    self.assertTrue(forwarder.capture_logs)

    def test_disabled_startup_and_forwarding_create_no_payload_files(self):
        with tempfile.TemporaryDirectory(dir="tmp") as temp_dir:
            temp_root = Path(temp_dir)
            with patch.object(self.forwarder_module, "FORWARDER_DIRECTORY", temp_root):
                forwarder = self._new_forwarder("false")
                request = SimpleNamespace(
                    url="http://localhost:8080/v1/chat/completions",
                    path="/v1/chat/completions",
                    method="POST",
                    host="localhost",
                    port=8080,
                    scheme="http",
                    content=b'{"model":"local"}',
                    headers={"authorization": "Bearer test"},
                )
                response = SimpleNamespace(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    content=b'{"choices":[]}',
                )
                flow = SimpleNamespace(request=request, response=response)

                forwarder.request(flow)
                forwarder.response(flow)

            self.assertFalse((temp_root / "lmstudio_logs").exists())
            self.assertEqual(list(temp_root.rglob("*.jsonl")), [])
            self.assertEqual(list(temp_root.rglob("*.log")), [])
            self.assertEqual(request.url, "http://localhost:1234/v1/chat/completions")

    def test_disabled_startup_alone_creates_no_capture_directory(self):
        with tempfile.TemporaryDirectory(dir="tmp") as temp_dir:
            temp_root = Path(temp_dir)
            with patch.object(self.forwarder_module, "FORWARDER_DIRECTORY", temp_root):
                forwarder = self._new_forwarder("false")

            self.assertFalse(forwarder.capture_logs)
            self.assertFalse((temp_root / "lmstudio_logs").exists())

    def test_enabled_capture_is_forwarder_rooted_from_alternate_cwd(self):
        with tempfile.TemporaryDirectory(dir="tmp") as temp_dir:
            temp_root = Path(temp_dir) / "forwarder_project"
            caller_root = Path(temp_dir) / "caller_cwd"
            temp_root.mkdir()
            caller_root.mkdir()
            original_cwd = Path.cwd()
            try:
                os.chdir(caller_root)
                with patch.object(self.forwarder_module, "FORWARDER_DIRECTORY", temp_root), \
                        patch.object(self.forwarder_module, "LOG_DIRECTORY", "lmstudio_logs"), \
                        patch.dict(os.environ, {"NEQ_LMSTUDIO_CAPTURE_PAYLOADS": "true"}):
                    forwarder = self.forwarder_module.LMStudioForwarder()
                    request = SimpleNamespace(
                        url="http://localhost:8080/v1/chat/completions",
                        path="/v1/chat/completions",
                        method="POST",
                        host="localhost",
                        port=8080,
                        scheme="http",
                        content=b'{"model":"local"}',
                        headers={},
                    )
                    response = SimpleNamespace(
                        status_code=200,
                        headers={},
                        content=b'{"usage":{"total_tokens":2}}',
                    )
                    flow = SimpleNamespace(request=request, response=response)
                    forwarder.request(flow)
                    forwarder.response(flow)

                    capture_file = forwarder.capture_file
                    log_file = forwarder.log_file
                    self.assertTrue(capture_file.is_relative_to(temp_root))
                    self.assertTrue(log_file.is_relative_to(temp_root))
                    self.assertFalse(capture_file.is_relative_to(caller_root))
                    self.assertTrue(capture_file.exists())
                    self.assertEqual(
                        json.loads(capture_file.read_text().splitlines()[0])["request"]["body"]["model"],
                        "local",
                    )
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
