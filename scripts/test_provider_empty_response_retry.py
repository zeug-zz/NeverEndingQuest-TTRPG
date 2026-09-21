# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
Provider empty-response recovery contract coverage.

Provider-free regression suite for utils/provider_response_recovery.py and the
guarded main.py narrator call sites. Fakes are local attribute-style objects
that replay scripted response sequences; no provider package is imported for
the fakes, no network calls are made, and no live API is exercised.

Covered contracts:
- classification: ok / empty_transient / refusal / content_filter, including
  unusual response shapes that must not raise
- bounded empty-completion retry (empty then valid, empty through the bound,
  custom retry limits)
- EmptyProviderResponseError attempt accounting and retryable fallback policy
- refusal and content-filter responses returned unchanged without retry
- verbatim forwarding of messages, timeout, and request parameters
- ASCII-only, payload-free exception diagnostics
- no empty response object returned as success (terminal empty fails
  deterministically; the narrator call sites route through the helper)
"""

import ast
import os
import sys
import unittest
from types import SimpleNamespace

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from utils.ai_client_factory import handle_provider_error, reset_fallback_status
from utils.provider_response_recovery import (
    CLASS_CONTENT_FILTER,
    CLASS_EMPTY_TRANSIENT,
    CLASS_OK,
    CLASS_REFUSAL,
    EMPTY_RESPONSE_RETRY_LIMIT,
    EmptyProviderResponseError,
    classify_chat_completion,
    request_chat_completion_with_recovery,
)

# Sentinel strings that must never appear inside exception diagnostics.
PROMPT_SENTINEL = "PROMPT_SENTINEL_DO_NOT_LEAK"
PAYLOAD_SENTINEL = "RAW_PROVIDER_PAYLOAD_SENTINEL_DO_NOT_LEAK"

# Identity sentinel proving the exact timeout object is forwarded on retries.
TIMEOUT_SENTINEL = object()

# Simulated resolved parameter shapes (no model config import needed).
GPT5_REQUEST_PARAMS = {
    "model": "gpt-5.6-luna",
    "reasoning_effort": "medium",
    "verbosity": "medium",
}
OPENROUTER_REQUEST_PARAMS = {
    "model": "moonshotai/kimi-k2.5",
    "temperature": 1.0,
    "thinking": {"type": "enabled"},
}
LEGACY_SAMPLING_KEYS = ("temperature", "top_p")


class FakeMessage:
    """Attribute-style chat message stand-in."""

    def __init__(self, content=None, refusal=None):
        self.content = content
        self.refusal = refusal


class FakeChoice:
    """Attribute-style chat choice stand-in."""

    def __init__(self, content=None, refusal=None, finish_reason="stop"):
        self.message = FakeMessage(content=content, refusal=refusal)
        self.finish_reason = finish_reason


class FakeResponse:
    """Attribute-style chat completion response stand-in."""

    def __init__(self, choices=None):
        self.choices = choices


class FakeCompletions:
    """Records every create() call and replays a scripted response sequence.

    Once the script is exhausted the final scripted entry repeats, so a single
    empty response models a provider that persists in returning empties.
    Exception entries are raised instead of returned.
    """

    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        if not self._script:
            return None
        index = len(self.calls) - 1
        item = self._script[index] if index < len(self._script) else self._script[-1]
        if isinstance(item, Exception):
            raise item
        return item


class FakeClient:
    """Provider client stand-in exposing the chat.completions.create surface."""

    def __init__(self, script):
        self.completions = FakeCompletions(script)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self):
        return self.completions.calls


def make_usable_response(text="The torchlight flickers along the corridor."):
    return FakeResponse([FakeChoice(content=text)])


def make_empty_response():
    return FakeResponse([FakeChoice(content=None)])


def make_blank_response():
    return FakeResponse([FakeChoice(content="   ")])


def make_no_choices_response():
    return FakeResponse([])


def make_refusal_response(refusal="I cannot help with that request."):
    return FakeResponse([FakeChoice(content=None, refusal=refusal)])


def make_content_filter_response():
    return FakeResponse([FakeChoice(content=None, finish_reason="content_filter")])


def make_call_kwargs():
    return {
        "messages": [{"role": "user", "content": "Continue the story."}],
        "timeout": TIMEOUT_SENTINEL,
        "request_params": dict(GPT5_REQUEST_PARAMS),
        "context": "DM response generation (GPT-5)",
    }


def _load_get_ai_response_source() -> str:
    """Return the exact main.py source segment of get_ai_response()."""
    main_path = os.path.join(REPO_ROOT, "main.py")
    with open(main_path, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "get_ai_response":
            lines = source.splitlines(keepends=True)
            return "".join(lines[node.lineno - 1:node.end_lineno])
    raise AssertionError("get_ai_response not found in main.py")


class TestClassifyChatCompletion(unittest.TestCase):
    """Classification of provider completions into explicit failure classes."""

    def test_class_constants_keep_contract_values(self) -> None:
        self.assertEqual(CLASS_OK, "ok")
        self.assertEqual(CLASS_EMPTY_TRANSIENT, "empty_transient")
        self.assertEqual(CLASS_REFUSAL, "refusal")
        self.assertEqual(CLASS_CONTENT_FILTER, "content_filter")

    def test_usable_text_is_ok(self) -> None:
        self.assertEqual(classify_chat_completion(make_usable_response()), CLASS_OK)

    def test_usable_collection_content_is_ok(self) -> None:
        response = FakeResponse([FakeChoice(content=["A usable content block."])])
        self.assertEqual(classify_chat_completion(response), CLASS_OK)

    def test_usable_mapping_style_response_is_ok(self) -> None:
        response = {
            "choices": [
                {
                    "message": {"content": "A usable mapping-style completion."},
                    "finish_reason": "stop",
                }
            ]
        }
        self.assertEqual(classify_chat_completion(response), CLASS_OK)

    def test_missing_choices_is_empty_transient(self) -> None:
        self.assertEqual(classify_chat_completion(None), CLASS_EMPTY_TRANSIENT)
        self.assertEqual(
            classify_chat_completion(SimpleNamespace(choices=None)),
            CLASS_EMPTY_TRANSIENT,
        )
        self.assertEqual(classify_chat_completion(make_no_choices_response()), CLASS_EMPTY_TRANSIENT)

    def test_missing_message_is_empty_transient(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace(message=None, finish_reason="stop")])
        self.assertEqual(classify_chat_completion(response), CLASS_EMPTY_TRANSIENT)

    def test_none_content_is_empty_transient(self) -> None:
        self.assertEqual(classify_chat_completion(make_empty_response()), CLASS_EMPTY_TRANSIENT)

    def test_blank_string_content_is_empty_transient(self) -> None:
        self.assertEqual(classify_chat_completion(make_blank_response()), CLASS_EMPTY_TRANSIENT)
        self.assertEqual(
            classify_chat_completion(FakeResponse([FakeChoice(content="")])),
            CLASS_EMPTY_TRANSIENT,
        )

    def test_empty_collection_content_is_empty_transient(self) -> None:
        self.assertEqual(
            classify_chat_completion(FakeResponse([FakeChoice(content=[])])),
            CLASS_EMPTY_TRANSIENT,
        )

    def test_refusal_marker_is_refusal(self) -> None:
        self.assertEqual(classify_chat_completion(make_refusal_response()), CLASS_REFUSAL)

    def test_blank_refusal_marker_does_not_hide_empty_content(self) -> None:
        response = FakeResponse([FakeChoice(content="", refusal="   ")])
        self.assertEqual(classify_chat_completion(response), CLASS_EMPTY_TRANSIENT)

    def test_content_filter_finish_reason_wins_over_missing_content(self) -> None:
        self.assertEqual(
            classify_chat_completion(make_content_filter_response()),
            CLASS_CONTENT_FILTER,
        )

    def test_content_filter_finish_reason_is_case_insensitive(self) -> None:
        response = FakeResponse([FakeChoice(content=None, finish_reason="CONTENT_FILTER")])
        self.assertEqual(classify_chat_completion(response), CLASS_CONTENT_FILTER)

    def test_content_filter_precedes_usable_content(self) -> None:
        response = FakeResponse(
            [FakeChoice(content="partial text", finish_reason="content_filter")]
        )
        self.assertEqual(classify_chat_completion(response), CLASS_CONTENT_FILTER)

    def test_unusual_shapes_never_raise(self) -> None:
        allowed = {CLASS_OK, CLASS_EMPTY_TRANSIENT, CLASS_REFUSAL, CLASS_CONTENT_FILTER}
        unusual_shapes = [
            None,
            123,
            "not-a-response",
            [],
            {},
            SimpleNamespace(),
            SimpleNamespace(choices=None),
            SimpleNamespace(choices="not-a-sequence"),
            SimpleNamespace(choices=42),
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[None]),
            SimpleNamespace(choices=[SimpleNamespace(message=None)]),
            SimpleNamespace(choices=[SimpleNamespace(message={}, finish_reason=None)]),
            FakeResponse(choices=None),
            FakeResponse(choices=()),
        ]
        for shape in unusual_shapes:
            with self.subTest(shape=repr(shape)):
                self.assertIn(classify_chat_completion(shape), allowed)


class TestBoundedEmptyRetry(unittest.TestCase):
    """Bounded retry behavior for empty transient completions."""

    def test_empty_then_valid_returns_valid_after_two_attempts(self) -> None:
        valid_response = make_usable_response()
        client = FakeClient([make_empty_response(), valid_response])
        call_kwargs = make_call_kwargs()

        response = request_chat_completion_with_recovery(
            client,
            messages=call_kwargs["messages"],
            timeout=call_kwargs["timeout"],
            request_params=call_kwargs["request_params"],
            context=call_kwargs["context"],
        )

        self.assertIs(response, valid_response)
        self.assertEqual(classify_chat_completion(response), CLASS_OK)
        self.assertEqual(len(client.calls), 2)

        expected = {
            "messages": call_kwargs["messages"],
            "timeout": TIMEOUT_SENTINEL,
            **GPT5_REQUEST_PARAMS,
        }
        self.assertEqual(client.calls[0], expected)
        self.assertEqual(client.calls[1], expected)
        self.assertIs(client.calls[0]["messages"], call_kwargs["messages"])
        self.assertIs(client.calls[1]["messages"], call_kwargs["messages"])
        self.assertIs(client.calls[0]["timeout"], TIMEOUT_SENTINEL)
        self.assertIs(client.calls[1]["timeout"], TIMEOUT_SENTINEL)

    def test_empty_through_retry_bound_raises_with_attempt_accounting(self) -> None:
        client = FakeClient([make_empty_response()])
        call_kwargs = make_call_kwargs()

        with self.assertRaises(EmptyProviderResponseError) as raised:
            request_chat_completion_with_recovery(
                client,
                messages=call_kwargs["messages"],
                timeout=call_kwargs["timeout"],
                request_params=call_kwargs["request_params"],
                context=call_kwargs["context"],
            )

        error = raised.exception
        self.assertEqual(error.attempts, EMPTY_RESPONSE_RETRY_LIMIT + 1)
        self.assertEqual(len(client.calls), EMPTY_RESPONSE_RETRY_LIMIT + 1)
        self.assertGreaterEqual(EMPTY_RESPONSE_RETRY_LIMIT, 1)

    def test_zero_retry_limit_raises_after_single_attempt(self) -> None:
        client = FakeClient([make_empty_response()])
        call_kwargs = make_call_kwargs()

        with self.assertRaises(EmptyProviderResponseError) as raised:
            request_chat_completion_with_recovery(
                client,
                messages=call_kwargs["messages"],
                timeout=call_kwargs["timeout"],
                request_params=call_kwargs["request_params"],
                context=call_kwargs["context"],
                retry_limit=0,
            )

        self.assertEqual(raised.exception.attempts, 1)
        self.assertEqual(len(client.calls), 1)


class TestFallbackAfterPrimaryExhaustion(unittest.TestCase):
    """EmptyProviderResponseError stays retryable and fallback stays bounded."""

    def setUp(self) -> None:
        reset_fallback_status()

    def tearDown(self) -> None:
        reset_fallback_status()

    def _exhaust_primary(self, context: str) -> EmptyProviderResponseError:
        client = FakeClient([make_empty_response()])
        messages = [{"role": "user", "content": PROMPT_SENTINEL}]
        with self.assertRaises(EmptyProviderResponseError) as raised:
            request_chat_completion_with_recovery(
                client,
                messages=messages,
                timeout=TIMEOUT_SENTINEL,
                request_params=dict(GPT5_REQUEST_PARAMS),
                context=context,
            )
        return raised.exception

    def test_exhaustion_error_classifies_as_retryable_fallback(self) -> None:
        error = self._exhaust_primary("DM response generation (GPT-5)")

        error_result = handle_provider_error(
            error, context="DM response generation (GPT-5)"
        )

        self.assertIs(error_result["should_fallback"], True)
        self.assertEqual(error_result["error_type"], "EmptyProviderResponseError")
        self.assertEqual(error_result["context"], "DM response generation (GPT-5)")

    def test_fallback_request_uses_bounded_recovery(self) -> None:
        context = "DM response generation (GPT-5)"
        error = self._exhaust_primary(context)
        error_result = handle_provider_error(error, context=context)
        self.assertTrue(error_result["should_fallback"])

        valid_response = make_usable_response()
        fallback_client = FakeClient([make_empty_response(), valid_response])

        fallback_response = request_chat_completion_with_recovery(
            fallback_client,
            messages=[{"role": "user", "content": "Continue the story."}],
            timeout=TIMEOUT_SENTINEL,
            request_params=dict(GPT5_REQUEST_PARAMS),
            context="DM response generation fallback (GPT-5)",
        )

        self.assertIs(fallback_response, valid_response)
        self.assertEqual(len(fallback_client.calls), 2)

    def test_terminal_empty_after_fallback_raises_again(self) -> None:
        fallback_client = FakeClient([make_empty_response()])

        with self.assertRaises(EmptyProviderResponseError) as raised:
            request_chat_completion_with_recovery(
                fallback_client,
                messages=[{"role": "user", "content": "Continue the story."}],
                timeout=TIMEOUT_SENTINEL,
                request_params=dict(GPT5_REQUEST_PARAMS),
                context="DM response generation fallback (GPT-5)",
            )

        self.assertEqual(raised.exception.attempts, EMPTY_RESPONSE_RETRY_LIMIT + 1)
        self.assertEqual(len(fallback_client.calls), EMPTY_RESPONSE_RETRY_LIMIT + 1)


class TestNoRetryForNonEmptyClasses(unittest.TestCase):
    """Refusal and content-filter responses are returned unchanged without retry."""

    def test_refusal_returned_unchanged_after_one_attempt(self) -> None:
        refusal_response = make_refusal_response()
        client = FakeClient([refusal_response, make_usable_response()])

        response = request_chat_completion_with_recovery(
            client,
            messages=[{"role": "user", "content": "Continue the story."}],
            timeout=TIMEOUT_SENTINEL,
            request_params=dict(GPT5_REQUEST_PARAMS),
            context="refusal case",
        )

        self.assertIs(response, refusal_response)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(classify_chat_completion(response), CLASS_REFUSAL)

    def test_content_filter_returned_unchanged_after_one_attempt(self) -> None:
        filtered_response = make_content_filter_response()
        client = FakeClient([filtered_response, make_usable_response()])

        response = request_chat_completion_with_recovery(
            client,
            messages=[{"role": "user", "content": "Continue the story."}],
            timeout=TIMEOUT_SENTINEL,
            request_params=dict(OPENROUTER_REQUEST_PARAMS),
            context="content filter case",
        )

        self.assertIs(response, filtered_response)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(classify_chat_completion(response), CLASS_CONTENT_FILTER)

    def test_non_empty_classes_never_exhaust_the_retry_bound(self) -> None:
        for response in (make_refusal_response(), make_content_filter_response()):
            with self.subTest(classification=classify_chat_completion(response)):
                client = FakeClient([response])
                returned = request_chat_completion_with_recovery(
                    client,
                    messages=[{"role": "user", "content": "Continue the story."}],
                    timeout=TIMEOUT_SENTINEL,
                    request_params=dict(GPT5_REQUEST_PARAMS),
                    context="single-attempt case",
                )
                self.assertIs(returned, response)
                self.assertEqual(len(client.calls), 1)


class TestRequestParamsForwardedVerbatim(unittest.TestCase):
    """Resolved request parameters are forwarded exactly, with no mutation."""

    def test_gpt5_params_forwarded_without_added_or_removed_keys(self) -> None:
        client = FakeClient([make_empty_response(), make_usable_response()])
        params = dict(GPT5_REQUEST_PARAMS)
        messages = [{"role": "user", "content": "Continue the story."}]

        request_chat_completion_with_recovery(
            client,
            messages=messages,
            timeout=TIMEOUT_SENTINEL,
            request_params=params,
            context="DM response generation (GPT-5)",
        )

        expected_keys = {"messages", "timeout", "model", "reasoning_effort", "verbosity"}
        for call in client.calls:
            self.assertEqual(set(call.keys()), expected_keys)
        self.assertEqual(client.calls[0]["model"], GPT5_REQUEST_PARAMS["model"])
        self.assertEqual(
            client.calls[0]["reasoning_effort"],
            GPT5_REQUEST_PARAMS["reasoning_effort"],
        )
        self.assertEqual(client.calls[0]["verbosity"], GPT5_REQUEST_PARAMS["verbosity"])
        for legacy_key in LEGACY_SAMPLING_KEYS:
            self.assertNotIn(legacy_key, client.calls[0])
            self.assertNotIn(legacy_key, client.calls[1])

    def test_openrouter_params_forwarded_unchanged(self) -> None:
        client = FakeClient([make_empty_response(), make_usable_response()])
        params = {
            "model": OPENROUTER_REQUEST_PARAMS["model"],
            "temperature": OPENROUTER_REQUEST_PARAMS["temperature"],
            "thinking": dict(OPENROUTER_REQUEST_PARAMS["thinking"]),
        }
        messages = [{"role": "user", "content": "Continue the story."}]

        request_chat_completion_with_recovery(
            client,
            messages=messages,
            timeout=TIMEOUT_SENTINEL,
            request_params=params,
            context="DM response generation (GPT-4.1/OpenRouter)",
        )

        expected = {"messages": messages, "timeout": TIMEOUT_SENTINEL, **params}
        self.assertEqual(client.calls[0], expected)
        self.assertEqual(client.calls[1], expected)
        self.assertEqual(client.calls[0]["temperature"], 1.0)
        self.assertEqual(client.calls[0]["thinking"], {"type": "enabled"})

    def test_legacy_sampling_absent_from_gpt5_param_fixture(self) -> None:
        for legacy_key in LEGACY_SAMPLING_KEYS:
            self.assertNotIn(legacy_key, GPT5_REQUEST_PARAMS)

    def test_request_params_mapping_is_not_mutated(self) -> None:
        client = FakeClient([make_empty_response(), make_usable_response()])
        params = dict(GPT5_REQUEST_PARAMS)
        original = dict(params)

        request_chat_completion_with_recovery(
            client,
            messages=[{"role": "user", "content": "Continue the story."}],
            timeout=TIMEOUT_SENTINEL,
            request_params=params,
            context="immutability case",
        )

        self.assertEqual(params, original)


class TestExceptionDiagnostics(unittest.TestCase):
    """Exception messages are ASCII-only, bounded, and payload-free."""

    def test_helper_exception_message_is_ascii_and_payload_free(self) -> None:
        client = FakeClient([make_empty_response()])
        messages = [{"role": "user", "content": PROMPT_SENTINEL}]
        params = {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "medium",
            "verbosity": "medium",
            "metadata": {"raw_payload": PAYLOAD_SENTINEL},
        }

        with self.assertRaises(EmptyProviderResponseError) as raised:
            request_chat_completion_with_recovery(
                client,
                messages=messages,
                timeout=TIMEOUT_SENTINEL,
                request_params=params,
                context="DM response generation (GPT-5)",
            )

        message = str(raised.exception)
        self.assertEqual(message.encode("ascii", "strict").decode("ascii"), message)
        self.assertNotIn(PROMPT_SENTINEL, message)
        self.assertNotIn(PAYLOAD_SENTINEL, message)

    def test_constructed_exception_message_is_ascii_and_payload_free(self) -> None:
        error = EmptyProviderResponseError(attempts=3, context="narrator stage")

        message = str(error)
        self.assertEqual(message.encode("ascii", "strict").decode("ascii"), message)
        self.assertNotIn(PROMPT_SENTINEL, message)
        self.assertNotIn(PAYLOAD_SENTINEL, message)
        self.assertIn("3", message)

    def test_non_ascii_context_is_replaced(self) -> None:
        error = EmptyProviderResponseError(attempts=2, context="narrator \u2014 stage")

        message = str(error)
        self.assertEqual(message.encode("ascii", "strict").decode("ascii"), message)
        self.assertNotIn("\u2014", message)

    def test_context_is_bounded(self) -> None:
        long_context = "stage-marker-" * 60
        error = EmptyProviderResponseError(attempts=2, context=long_context)

        self.assertLess(len(error.context), len(long_context))
        self.assertLess(len(str(error)), len(long_context) + 100)

    def test_context_free_message_has_no_suffix(self) -> None:
        error = EmptyProviderResponseError(attempts=2)

        self.assertNotIn("context=", str(error))


class TestNoEmptySuccessArtifacts(unittest.TestCase):
    """A terminal empty completion never surfaces as a successful response."""

    def test_terminal_empty_raises_instead_of_returning_response(self) -> None:
        empty_response = make_empty_response()
        client = FakeClient([empty_response])

        with self.assertRaises(EmptyProviderResponseError):
            request_chat_completion_with_recovery(
                client,
                messages=[{"role": "user", "content": "Continue the story."}],
                timeout=TIMEOUT_SENTINEL,
                request_params=dict(GPT5_REQUEST_PARAMS),
                context="terminal empty case",
            )

        self.assertEqual(len(client.calls), EMPTY_RESPONSE_RETRY_LIMIT + 1)

    def test_helper_never_returns_empty_transient_response(self) -> None:
        scenarios = [
            (FakeClient([make_empty_response(), make_usable_response()]), CLASS_OK),
            (FakeClient([make_refusal_response()]), CLASS_REFUSAL),
            (FakeClient([make_content_filter_response()]), CLASS_CONTENT_FILTER),
        ]
        for client, expected_class in scenarios:
            with self.subTest(expected_class=expected_class):
                response = request_chat_completion_with_recovery(
                    client,
                    messages=[{"role": "user", "content": "Continue the story."}],
                    timeout=TIMEOUT_SENTINEL,
                    request_params=dict(GPT5_REQUEST_PARAMS),
                    context="no empty success case",
                )
                self.assertEqual(classify_chat_completion(response), expected_class)
                self.assertNotEqual(
                    classify_chat_completion(response), CLASS_EMPTY_TRANSIENT
                )


class TestMainNarratorSourceContract(unittest.TestCase):
    """The wired narrator sites use the guarded helper, not raw create calls."""

    def test_get_ai_response_routes_all_narrator_sites_through_helper(self) -> None:
        segment = _load_get_ai_response_source()

        helper_call = "request_chat_completion_with_recovery("
        self.assertEqual(segment.count(helper_call), 4)
        self.assertIn(
            "from utils.provider_response_recovery import "
            "request_chat_completion_with_recovery",
            segment,
        )
        self.assertNotIn("client.chat.completions.create(", segment)

        content_assignment = "content = response.choices[0].message.content.strip()"
        self.assertIn(content_assignment, segment)
        self.assertGreater(segment.find(content_assignment), segment.rfind(helper_call))

    def test_terminal_empty_still_surfaces_provider_error_in_main(self) -> None:
        segment = _load_get_ai_response_source()

        self.assertIn("handle_provider_error(", segment)
        self.assertIn('context="DM response generation', segment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
