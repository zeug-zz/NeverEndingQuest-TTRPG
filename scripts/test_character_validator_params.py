# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root

"""Provider-free request-parameter contracts for character validation."""

import builtins
import http.client
import importlib
import logging
import logging.handlers
import os
import socket
import sys
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


_PROJECT = Path(__file__).resolve().parents[1]
_ALLOWED_WRITE_ROOT = _PROJECT / "tmp"
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))


class _FatalTripwire(BaseException):
    pass


def _deny(*args, **kwargs):
    raise _FatalTripwire("SDK and network operations are forbidden in this test")


def _install_tripwires():
    patches = []
    for target in (
        "socket.socket",
        "socket.create_connection",
        "urllib.request.urlopen",
        "http.client.HTTPConnection.request",
        "http.client.HTTPSConnection.request",
        "http.client.HTTPConnection.connect",
        "http.client.HTTPSConnection.connect",
    ):
        patcher = mock.patch(target, side_effect=_deny)
        patcher.start()
        patches.append(patcher)

    real_open = builtins.open

    def deny_external_write(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            path = Path(file).resolve()
            if not path.is_relative_to(_ALLOWED_WRITE_ROOT):
                raise _FatalTripwire("write outside project tmp is forbidden")
        return real_open(file, mode, *args, **kwargs)

    patcher = mock.patch("builtins.open", side_effect=deny_external_write)
    patcher.start()
    patches.append(patcher)
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    real_os_open = os.open

    def deny_external_os_write(path, flags, *args, **kwargs):
        if flags & write_flags and not Path(path).resolve().is_relative_to(_ALLOWED_WRITE_ROOT):
            raise _FatalTripwire("write outside project tmp is forbidden")
        return real_os_open(path, flags, *args, **kwargs)

    patcher = mock.patch("os.open", side_effect=deny_external_os_write)
    patcher.start()
    patches.append(patcher)
    for method in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace"):
        patcher = mock.patch.object(Path, method, side_effect=_FatalTripwire("filesystem write forbidden"))
        patcher.start()
        patches.append(patcher)
    patcher = mock.patch.object(
        logging.handlers,
        "RotatingFileHandler",
        side_effect=lambda *args, **kwargs: logging.NullHandler(),
    )
    patcher.start()
    patches.append(patcher)
    return patches


_GUARDS = _install_tripwires()
_openai = importlib.import_module("openai")
_SDK_GUARD = mock.patch.object(_openai, "OpenAI", side_effect=_deny)
_SDK_GUARD.start()
_validator_module = importlib.import_module("core.validation.character_validator")
_factory = importlib.import_module("utils.ai_client_factory")
_llm_router = importlib.import_module("utils.llm_router")
_llm_runtime = importlib.import_module("utils.llm_runtime")


class _FakeFacade:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def call(self, **kwargs):
        self.requests.append(
            {key: value for key, value in kwargs.items() if key != "observer"}
        )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        observer = kwargs.get("observer")
        if observer is not None:
            observer(
                SimpleNamespace(
                    kind="response",
                    attempt_id=f"attempt-{len(self.requests)}",
                    call_id=f"call-{len(self.requests)}",
                    task=kwargs.get("task"),
                ),
                SimpleNamespace(
                    usage=SimpleNamespace(
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                    )
                ),
            )
        return outcome


class CharacterValidatorParamsTests(unittest.TestCase):
    _PRODUCERS = (
        "ai_validate_armor_class",
        "ai_validate_inventory_categories",
        "ai_validate_all_batched",
        "ai_consolidate_inventory",
    )
    _MESSAGES = {
        "ai_validate_armor_class": [
            {"role": "system", "content": "ac system"},
            {"role": "user", "content": "ac prompt"},
        ],
        "ai_validate_inventory_categories": [
            {"role": "system", "content": "inventory system"},
            {"role": "user", "content": "inventory prompt"},
        ],
        "ai_validate_all_batched": [
            {"role": "system", "content": "combined system"},
            {"role": "user", "content": "combined prompt"},
        ],
        "ai_consolidate_inventory": [
            {"role": "system", "content": "consolidation system"},
            {"role": "user", "content": "consolidation prompt"},
        ],
    }

    def _capture(self, producer, *, retry=False):
        outcomes = [RuntimeError("retry once"), "{}"] if retry else ["{}"]
        facade = _FakeFacade(outcomes)
        tracker = mock.Mock()
        validator = _validator_module.AICharacterValidator.__new__(
            _validator_module.AICharacterValidator
        )
        validator.logger = mock.Mock()
        validator.validation_cache = {}
        validator.corrections_made = []
        validator.ac_prompt = ""
        validator.inventory_prompt = ""

        validator.extract_ac_relevant_data = mock.Mock(return_value={"armorClass": 10})
        validator._compute_ac_hash = mock.Mock(return_value="ac-hash")
        validator._is_ac_validation_cached = mock.Mock(return_value=False)
        validator.build_ac_validation_prompt = mock.Mock(return_value="ac prompt")
        validator.get_validator_system_prompt = mock.Mock(return_value="ac system")
        validator.parse_ai_validation_response = mock.Mock(return_value={})
        validator._update_ac_cache = mock.Mock()

        inventory = {"name": "A", "equipment": [{"item_name": "odd item", "item_type": "miscellaneous"}]}
        validator.extract_inventory_data = mock.Mock(return_value=inventory)
        validator._compute_inventory_hash = mock.Mock(return_value="inventory-hash")
        validator._is_inventory_validation_cached = mock.Mock(return_value=False)
        validator.build_inventory_validation_prompt = mock.Mock(return_value="inventory prompt")
        validator.get_inventory_validator_system_prompt = mock.Mock(return_value="inventory system")
        validator.parse_inventory_validation_response = mock.Mock(return_value={})
        validator._update_inventory_cache = mock.Mock()

        consolidation = {"name": "A", "currency": {}, "ammunition": [], "equipment": [{"item_name": "5 gold pieces"}]}
        validator.extract_currency_consolidation_data = mock.Mock(return_value=consolidation)
        validator._compute_currency_hash = mock.Mock(return_value="currency-hash")
        validator._is_currency_validation_cached = mock.Mock(return_value=False)
        validator.build_inventory_consolidation_prompt = mock.Mock(return_value="consolidation prompt")
        validator.get_inventory_consolidation_system_prompt = mock.Mock(return_value="consolidation system")
        validator.parse_currency_consolidation_response = mock.Mock(return_value={})
        validator._update_currency_cache = mock.Mock()

        validator.build_combined_validation_prompt = mock.Mock(return_value="combined prompt")
        validator.get_combined_validator_system_prompt = mock.Mock(return_value="combined system")
        validator.parse_combined_validation_response = mock.Mock(return_value={"name": "A"})

        observer_kwargs = []

        def observer_factory(**kwargs):
            observer_kwargs.append(dict(kwargs))
            return _llm_runtime.make_legacy_receipt_observer(
                tracker_getter=lambda: tracker,
                **kwargs,
            )

        fake_update_module = SimpleNamespace(
            deep_merge_dict=lambda original, changes: {**original, **changes}
        )
        with (
            mock.patch.object(_validator_module, "USAGE_TRACKING_AVAILABLE", True),
            mock.patch.object(
                _validator_module,
                "make_legacy_receipt_observer",
                side_effect=observer_factory,
            ),
            mock.patch.object(_llm_router.llm, "call", side_effect=facade.call),
            mock.patch.object(
                _factory,
                "create_chat_client",
                side_effect=AssertionError("character validator constructed a provider client"),
            ) as create_client,
            mock.patch.dict(sys.modules, {
                "updates.update_character_info": fake_update_module,
            }),
        ):
            input_data = {"name": "A", "equipment": inventory["equipment"]}
            result = getattr(validator, producer)(input_data)

        self.assertEqual(len(facade.requests), 2 if retry else 1)
        self.assertEqual(len(observer_kwargs), 2 if retry else 1)
        if retry:
            self.assertEqual(facade.requests[0]["messages"], facade.requests[1]["messages"])
        self.assertEqual(tracker.track.call_count, 1)
        usage = tracker.track.call_args.args[0]["usage"]
        self.assertEqual(usage["prompt_tokens"], 10)
        self.assertEqual(usage["completion_tokens"], 5)
        self.assertEqual(usage["total_tokens"], 15)
        self.assertEqual(
            tracker.track.call_args.args[1]["endpoint"], "character_validation"
        )
        self.assertEqual(
            tracker.track.call_args.args[1]["purpose"],
            "validate_character_effects"
            if producer in ("ai_validate_inventory_categories", "ai_consolidate_inventory")
            else "validate_character_data",
        )
        create_client.assert_not_called()

        parser = {
            "ai_validate_armor_class": validator.parse_ai_validation_response,
            "ai_validate_inventory_categories": validator.parse_inventory_validation_response,
            "ai_validate_all_batched": validator.parse_combined_validation_response,
            "ai_consolidate_inventory": validator.parse_currency_consolidation_response,
        }[producer]
        parser.assert_called_once_with("{}", input_data if producer != "ai_validate_armor_class" else {"armorClass": 10})
        if producer == "ai_validate_all_batched":
            self.assertEqual(result, {"name": "A"})
        else:
            self.assertEqual(result, input_data)
        return result, facade.requests, tracker

    def test_all_existing_producers_use_facade_contract(self):
        for producer in self._PRODUCERS:
            with self.subTest(producer=producer):
                _, requests, _ = self._capture(producer)
                self.assertEqual(len(requests), 1)
                request = requests[0]
                self.assertEqual(request["task"], "validation")
                self.assertEqual(request["messages"], self._MESSAGES[producer])
                self.assertIs(request["json_output"], False)
                self.assertFalse(
                    {"model", "temperature", "top_p", "timeout", "client", "extra_body"}.intersection(request)
                )

    def test_retrying_producers_keep_facade_messages_and_attempt_count(self):
        for producer in ("ai_validate_inventory_categories", "ai_consolidate_inventory"):
            with self.subTest(producer=producer):
                _, requests, tracker = self._capture(producer, retry=True)
                self.assertEqual(len(requests), 2)
                self.assertEqual(requests[0]["messages"], requests[1]["messages"])
                self.assertTrue(all(request["task"] == "validation" for request in requests))
                self.assertTrue(all(request["json_output"] is False for request in requests))
                self.assertTrue(
                    all(
                        not {"model", "temperature", "top_p", "timeout", "client"}.intersection(request)
                        for request in requests
                    )
                )
                self.assertEqual(tracker.track.call_count, 1)


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        _SDK_GUARD.stop()
        for _patcher in reversed(_GUARDS):
            _patcher.stop()
