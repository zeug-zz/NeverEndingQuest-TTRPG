# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free tests for the opt-in N3 sandbox model route."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import seed_combat_capture
from utils import ai_client_factory, llm_router


class SeedN3LunaRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_root = seed_combat_capture.PROJECT_ROOT / "tmp"
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        self.scratch = Path(
            tempfile.mkdtemp(prefix="seed-n3-luna-route-", dir=self.tmp_root)
        )
        self.production_model_config = (
            seed_combat_capture.PROJECT_ROOT / "model_config.py"
        )
        self.production_bytes = self.production_model_config.read_bytes()
        self.production_sha256 = hashlib.sha256(self.production_bytes).hexdigest()

    def tearDown(self) -> None:
        shutil.rmtree(self.scratch, ignore_errors=True)

    def _sandbox_model_config(self) -> Path:
        path = self.scratch / "combat_capture" / "model_config.py"
        path.parent.mkdir(parents=True)
        shutil.copyfile(self.production_model_config, path)
        return path

    @staticmethod
    def _load_model_config(path: Path):
        spec = importlib.util.spec_from_file_location("model_config", path)
        if spec is None or spec.loader is None:
            raise AssertionError("sandbox model_config.py could not be loaded")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_default_model_config_patch_keeps_default_profile_and_provider(self) -> None:
        path = self._sandbox_model_config()
        before = path.read_text(encoding="utf-8")
        with patch.object(seed_combat_capture, "SANDBOX_ROOT", path.parent):
            seed_combat_capture._patch_sandbox_model_config(
                "g4", "narrator-dialogue-travel"
            )
        updated = path.read_text(encoding="utf-8")
        self.assertIn('ACTIVE_PROFILE = "production-auto"', updated)
        self.assertNotIn('MODEL_PROFILES["n3-luna"]', updated)
        self.assertIn('LLM_PROVIDER = "openrouter"', updated)
        self.assertEqual(
            hashlib.sha256(self.production_model_config.read_bytes()).hexdigest(),
            self.production_sha256,
        )
        self.assertNotEqual(updated, before)

    def test_n3_luna_patch_is_sandbox_only_and_resolves_priced_dm_main(self) -> None:
        path = self._sandbox_model_config()
        with patch.object(seed_combat_capture, "SANDBOX_ROOT", path.parent):
            seed_combat_capture._patch_sandbox_model_config(
                "g4", "narrator-dialogue-travel", "n3-luna"
            )

        sandbox_config = self._load_model_config(path)
        self.assertEqual(sandbox_config.LLM_PROVIDER, "openrouter")
        self.assertEqual(sandbox_config.ACTIVE_PROFILE, "n3-luna")
        self.assertEqual(
            sandbox_config.ENABLE_PROVIDER_FALLBACK,
            self._load_model_config(self.production_model_config).ENABLE_PROVIDER_FALLBACK,
        )
        self.assertEqual(
            hashlib.sha256(self.production_model_config.read_bytes()).hexdigest(),
            self.production_sha256,
        )

        with (
            patch.dict(sys.modules, {"model_config": sandbox_config}),
            patch.object(
                ai_client_factory,
                "_get_actual_provider",
                return_value=("openrouter", True),
            ),
        ):
            profile = llm_router.llm.resolve_profile(
                "dm_main", model_tier="complex"
            )
            request = llm_router.llm._request_kwargs(
                profile,
                [{"role": "user", "content": "narrator startup"}],
                auto_router_cost_tier=None,
                json_output=False,
                json_contract=False,
                temperature=None,
                max_tokens=None,
                retry_tier=None,
                extra_kwargs={},
            )

        self.assertEqual(profile["profile"], "n3-luna")
        self.assertEqual(profile["model"], "openai/gpt-6-luna")
        self.assertEqual(
            profile["price_per_1k"],
            {"prompt": 0.0001, "completion": 0.0005},
        )
        self.assertEqual(request["max_tokens"], 2048)
        self.assertEqual(
            request["extra_body"]["provider"], {"allow_fallbacks": False}
        )
        self.assertEqual(
            hashlib.sha256(self.production_model_config.read_bytes()).hexdigest(),
            self.production_sha256,
        )

    def test_model_route_is_prepare_only_and_bound_to_narrator_scenario(self) -> None:
        with patch.object(seed_combat_capture, "prepare", return_value=0) as prepare:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                seed_combat_capture.main(
                    ["--restore", "--model-route", "n3-luna"]
                )
            prepare.assert_not_called()

            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                seed_combat_capture.main(
                    [
                        "--prepare",
                        "--party",
                        "1",
                        "--scenario",
                        "combat-smoke",
                        "--model-route",
                        "n3-luna",
                    ]
                )
            prepare.assert_not_called()

            result = seed_combat_capture.main(
                [
                    "--prepare",
                    "--party",
                    "1",
                    "--gate",
                    "g4",
                    "--scenario",
                    "narrator-dialogue-travel",
                    "--model-route",
                    "n3-luna",
                ]
            )

        self.assertEqual(result, 0)
        self.assertEqual(prepare.call_args.kwargs["model_route"], "n3-luna")


if __name__ == "__main__":
    unittest.main()
