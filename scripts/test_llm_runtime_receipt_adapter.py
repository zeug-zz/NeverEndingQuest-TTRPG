"""Provider-free contract tests for the per-call legacy receipt adapter."""

import ast
import json
import os
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import utils.ai_client_factory as factory
import utils.llm_router as router_module
import utils.llm_usage_tracker as tracker_module
from utils.llm_runtime import make_legacy_receipt_observer


SUMMARY_SOURCE_CONTRACTS = {
    "main.py": ("main.py:generate_module_summary",),
    "core/memory/session_diary.py": (
        "core/memory/session_diary.py:_generate_rebuild_chapter_summary",
        "core/memory/session_diary.py:_generate_rebuild_chapter_summary",
        "core/memory/session_diary.py:_generate_checkpoint_summary",
        "core/memory/session_diary.py:_generate_checkpoint_summary",
    ),
    "core/memory/players_diary.py": (
        "core/memory/players_diary.py:_generate_markdown_from_prompt",
        "core/memory/players_diary.py:_generate_markdown_from_prompt",
    ),
    "core/memory/story_so_far_compiler.py": (
        "core/memory/story_so_far_compiler.py:_generate_story_text_with_llm",
        "core/memory/story_so_far_compiler.py:_generate_story_text_with_llm",
    ),
    "core/managers/campaign_manager.py": (
        "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.summary",
        "core/managers/campaign_manager.py:CampaignManager._generate_module_summary.export_data",
    ),
    "utils/homebrewery_adventure_writer.py": (
        "utils/homebrewery_adventure_writer.py:_llm_intro_narrative",
        "utils/homebrewery_adventure_writer.py:_llm_plot_hook",
        "utils/homebrewery_adventure_writer.py:_llm_area_overview",
    ),
}
SUMMARY_SOURCE_IDS = tuple(dict.fromkeys(
    source_id
    for source_ids in SUMMARY_SOURCE_CONTRACTS.values()
    for source_id in source_ids
))


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def response(content, usage=None, model="gpt-6-luna"):
    result = {
        "choices": [{"message": {"content": content}}],
        "model": model,
    }
    if usage is not None:
        result["usage"] = dict(usage)
    return result


class RecordingTracker:
    def __init__(self, fail=False):
        self.events = []
        self.fail = fail

    def track(self, value, context=None):
        if self.fail:
            raise RuntimeError("tracker failure")
        self.events.append((value, context))


class ReceiptAdapterTests(unittest.TestCase):
    def setUp(self):
        self.config_patch = mock.patch.object(factory, "_get_actual_provider", return_value=("openai", False))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.default_tracker = RecordingTracker()
        self.default_tracker_patch = mock.patch.object(
            tracker_module, "get_global_tracker", return_value=self.default_tracker
        )
        self.default_tracker_patch.start()
        self.addCleanup(self.default_tracker_patch.stop)

    def _call(self, client, observer=None, task="dm_main", **kwargs):
        with mock.patch.object(factory, "create_chat_client", return_value=client):
            return router_module.LLMRouter().call(task, [{"role": "user", "content": "hello"}], observer=observer, **kwargs)

    def test_summary_producers_pass_their_static_g10_source_id(self):
        repo_root = Path(__file__).resolve().parents[1]
        for relative_path, expected_source_ids in SUMMARY_SOURCE_CONTRACTS.items():
            with self.subTest(source=relative_path):
                tree = ast.parse((repo_root / relative_path).read_text(encoding="utf-8"))
                summary_calls = sorted(
                    (
                        node for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "call"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "llm"
                        and any(
                            keyword.arg == "task"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value == "summaries"
                            for keyword in node.keywords
                        )
                    ),
                    key=lambda node: node.lineno,
                )
                self.assertEqual(len(summary_calls), len(expected_source_ids))
                if relative_path == "main.py":
                    source_ids = [
                        keyword.value.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "make_legacy_receipt_observer"
                        for keyword in node.keywords
                        if keyword.arg == "g10_source_id"
                        and isinstance(keyword.value, ast.Constant)
                    ]
                    self.assertTrue(any(
                        keyword.arg == "observer"
                        for keyword in summary_calls[0].keywords
                    ))
                else:
                    source_ids = [
                        next(
                            keyword.value.value
                            for keyword in node.keywords
                            if keyword.arg == "g10_source_id"
                            and isinstance(keyword.value, ast.Constant)
                        )
                        for node in summary_calls
                    ]
                self.assertEqual(source_ids, list(expected_source_ids))

        legacy_source_contracts = {
            "core/ai/adv_summary.py": "core/ai/adv_summary.py:adv_summary",
            "core/ai/cumulative_summary.py": "core/ai/cumulative_summary.py:cumulative_summary",
        }
        for relative_path, expected_source_id in legacy_source_contracts.items():
            with self.subTest(source=relative_path):
                tree = ast.parse((repo_root / relative_path).read_text(encoding="utf-8"))
                source_ids = [
                    keyword.value.value
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "make_legacy_receipt_observer"
                    for keyword in node.keywords
                    if keyword.arg == "g10_source_id"
                    and isinstance(keyword.value, ast.Constant)
                ]
                self.assertEqual(source_ids, [expected_source_id, expected_source_id])

    def test_unobserved_json_retries_reach_tracker_once_and_keep_sdk_total(self):
        client = SequenceClient([
            response("not-json", {
                "prompt_tokens": 2, "completion_tokens": 1,
                "total_tokens": 91, "cost": 0.0,
            }),
            response('{"ok":true}', None),
        ])

        self.assertEqual(self._call(client, json_output=True), {"ok": True})

        self.assertEqual(len(self.default_tracker.events), 2)
        first_usage, first_context = self.default_tracker.events[0]
        second_usage, second_context = self.default_tracker.events[1]
        self.assertEqual(first_usage["usage"]["total_tokens"], 91)
        self.assertEqual(first_usage["usage"]["prompt_tokens"], 2)
        self.assertEqual(first_usage["usage"]["completion_tokens"], 1)
        self.assertEqual(second_usage, {"usage": None})
        self.assertEqual(first_context["call_id"], second_context["call_id"])
        self.assertNotEqual(first_context["attempt_id"], second_context["attempt_id"])
        self.assertEqual(
            [first_context["attempt_number"], second_context["attempt_number"]],
            [1, 2],
        )
        self.assertFalse(second_context["usage_complete"])

    def test_explicit_plain_observer_is_preserved_and_tracker_receives_once(self):
        observed = []
        client = SequenceClient([
            response("ok", {
                "prompt_tokens": 3, "completion_tokens": 2,
                "total_tokens": 8, "cost": 0.0,
            })
        ])

        self.assertEqual(
            self._call(client, lambda receipt, raw: observed.append((receipt, raw))),
            "ok",
        )

        self.assertEqual(len(observed), 1)
        self.assertEqual(len(self.default_tracker.events), 1)
        self.assertEqual(
            observed[0][0].attempt_id,
            self.default_tracker.events[0][1]["attempt_id"],
        )
        self.assertEqual(
            self.default_tracker.events[0][0]["usage"]["total_tokens"], 8
        )

    def test_g10_capture_trace_is_opt_in_and_contains_receipt_metadata_only(self):
        import model_config
        from utils import combat_latency_trace

        with tempfile.TemporaryDirectory(prefix="llm-g10-trace-", dir="tmp") as directory:
            trace_path = Path(directory) / "trace.jsonl"
            raw = response(
                "private response marker",
                {
                    "prompt_tokens": 3, "completion_tokens": 2,
                    "total_tokens": 17, "cost": 0.0004,
                },
            )
            with mock.patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                with mock.patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "NEQ_G10_RECEIPT_TRACE": "1",
                            "NEQ_G5_CAPTURE_RUN_ID": "g10-provider-free",
                        },
                    ):
                        self._call(SequenceClient([raw]))

                    records = trace_path.read_text(encoding="ascii").splitlines()
                    self.assertEqual(len(records), 1)
                    record = json.loads(records[0])
                    self.assertEqual(record["event_type"], "provider")
                    self.assertEqual(record["site"], "llm_router")
                    self.assertEqual(record["run_id"], "g10-provider-free")
                    self.assertNotIn("source_id", record)
                    self.assertTrue(record["call_id"])
                    self.assertTrue(record["attempt_id"])
                    self.assertEqual(record["sdk_total_tokens"], 17)
                    self.assertEqual(record["cost_usd"], 0.0004)
                    self.assertEqual(record["provider_reported_cost_usd"], 0.0004)
                    self.assertNotIn("hello", records[0])
                    self.assertNotIn("private response marker", records[0])

                    trace_path.unlink()
                    with mock.patch.dict(
                        os.environ,
                        {
                            "NEQ_G10_RECEIPT_TRACE": "",
                            "NEQ_G5_CAPTURE_RUN_ID": "g5-existing",
                        },
                    ):
                        self._call(SequenceClient([response("ordinary", {
                            "prompt_tokens": 1, "completion_tokens": 1,
                            "total_tokens": 2,
                        })]))
                    self.assertFalse(trace_path.exists())

    def test_g10_summary_receipts_use_allowlisted_source_ids_only_in_trace(self):
        import model_config
        from utils import combat_latency_trace

        direct_observer_source = "main.py:generate_module_summary"
        with tempfile.TemporaryDirectory(prefix="llm-g10-summary-", dir="tmp") as directory:
            trace_path = Path(directory) / "trace.jsonl"
            clients = []
            with mock.patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                with mock.patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "NEQ_G10_RECEIPT_TRACE": "1",
                            "NEQ_G5_CAPTURE_RUN_ID": "g10-summary-provider-free",
                        },
                    ):
                        for index, source_id in enumerate(SUMMARY_SOURCE_IDS):
                            client = SequenceClient([response("private summary %d" % index, {
                                "prompt_tokens": 2,
                                "completion_tokens": 3,
                                "total_tokens": 5,
                            })])
                            clients.append(client)
                            if source_id == direct_observer_source:
                                observer = make_legacy_receipt_observer(
                                    g10_source_id=source_id,
                                    legacy_context={"function": "summary", "purpose": "test"},
                                )
                                self._call(client, observer, task="summaries")
                            else:
                                self._call(
                                    client,
                                    task="summaries",
                                    g10_source_id=source_id,
                                )

                    records = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
                    self.assertEqual([record["source_id"] for record in records], list(SUMMARY_SOURCE_IDS))
                    self.assertTrue(all(record["site"] == "llm_router" for record in records))
                    self.assertTrue(all(record["task"] == "summaries" for record in records))
                    serialized = trace_path.read_text(encoding="ascii")
                    self.assertNotIn("hello", serialized)
                    self.assertNotIn("private summary", serialized)
                    self.assertTrue(all(
                        "g10_source_id" not in call
                        for client in clients
                        for call in client.calls
                    ))
                    self.assertEqual(len(self.default_tracker.events), len(SUMMARY_SOURCE_IDS))
                    self.assertTrue(all("source_id" not in context for _, context in self.default_tracker.events))

                    invalid_observer = make_legacy_receipt_observer(
                        g10_source_id="https://provider.invalid/private?query=user-data",
                    )
                    self.assertFalse(hasattr(invalid_observer, "_llm_g10_source_id"))

                    trace_path.unlink()
                    with mock.patch.dict(
                        os.environ,
                        {
                            "NEQ_G10_RECEIPT_TRACE": "1",
                            "NEQ_G5_CAPTURE_RUN_ID": "g10-summary-provider-free",
                        },
                    ):
                        self._call(
                            SequenceClient([response("private unknown summary", {
                                "prompt_tokens": 2,
                                "completion_tokens": 3,
                                "total_tokens": 5,
                            })]),
                            task="summaries",
                            g10_source_id="https://provider.invalid/private?query=user-data",
                        )
                    unknown_record = json.loads(trace_path.read_text(encoding="ascii"))
                    self.assertNotIn("source_id", unknown_record)
                    self.assertNotIn("provider.invalid", trace_path.read_text(encoding="ascii"))

    def test_g10_source_id_is_not_emitted_without_g10_capture_gate(self):
        trace_calls = []
        observer = make_legacy_receipt_observer(
            trace_site="unit", g10_source_id="core/ai/adv_summary.py:adv_summary",
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: trace_calls.append(fields),
        )
        with mock.patch.dict(
            os.environ,
            {"NEQ_G10_RECEIPT_TRACE": "", "NEQ_G5_CAPTURE_RUN_ID": "ordinary-run"},
        ):
            self._call(SequenceClient([response("ordinary", {
                "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
            })]), observer)
        self.assertEqual(len(trace_calls), 1)
        self.assertNotIn("source_id", trace_calls[0])

    def test_g10_uses_only_explicit_allowlisted_observer_endpoint(self):
        import model_config
        from utils import combat_latency_trace

        with tempfile.TemporaryDirectory(prefix="llm-g10-endpoint-", dir="tmp") as directory:
            trace_path = Path(directory) / "trace.jsonl"
            with mock.patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                with mock.patch.object(combat_latency_trace, "DEFAULT_TRACE_PATH", trace_path):
                    with mock.patch.dict(
                        os.environ,
                        {
                            "NEQ_G10_RECEIPT_TRACE": "1",
                            "NEQ_G5_CAPTURE_RUN_ID": "g10-endpoint-provider-free",
                        },
                    ):
                        observer_specs = (
                            ("module_summary", None),
                            ("module_summary", "core/ai/adv_summary.py:adv_summary"),
                            ("https://provider.invalid/private?query=user-data", None),
                        )
                        for endpoint, source_id in observer_specs:
                            observer = make_legacy_receipt_observer(
                                endpoint_name=endpoint,
                                g10_source_id=source_id,
                            )
                            self._call(SequenceClient([response("private endpoint response", {
                                "prompt_tokens": 1,
                                "completion_tokens": 1,
                                "total_tokens": 2,
                            })]), observer)

                    records = [json.loads(line) for line in trace_path.read_text(encoding="ascii").splitlines()]
                    self.assertEqual(len(records), 3)
                    self.assertEqual(records[0]["endpoint"], "module_summary")
                    self.assertNotIn("source_id", records[0])
                    self.assertEqual(records[1]["source_id"], "core/ai/adv_summary.py:adv_summary")
                    self.assertNotIn("endpoint", records[1])
                    self.assertNotIn("source_id", records[2])
                    self.assertNotIn("endpoint", records[2])
                    serialized = trace_path.read_text(encoding="ascii")
                    self.assertNotIn("private?query=user-data", serialized)
                    self.assertNotIn("private endpoint response", serialized)

    def test_each_response_attempt_once_including_empty_and_malformed_json(self):
        tracker = RecordingTracker()
        logged = []
        traced = []
        messages = [{"role": "user", "content": "hello"}]
        observer = make_legacy_receipt_observer(
            endpoint_name="main_dm", messages=messages, trace_site="main_dm",
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logged.append((args, kwargs)),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: traced.append((event, fields)),
        )
        client = SequenceClient([
            response("", {"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2}),
            response("not-json", {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}),
            response('{"ok":true}', {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4}),
        ])
        self.assertEqual(self._call(client, observer, json_output=True), {"ok": True})

        # JSON retry responses are all receipts; the router returns only after the valid third one.
        self.assertEqual(len(tracker.events), 3)
        self.assertEqual(len(logged), 3)
        self.assertEqual(len(traced), 3)
        self.assertEqual([call[0][0] for call in logged], ["main_dm"] * 3)
        self.assertEqual([event for event, _ in traced], ["provider"] * 3)
        self.assertEqual([fields["attempt_number"] for _, fields in traced], [1, 2, 3])
        self.assertEqual(tracker.events[0][0]["usage"]["total_tokens"], 2)
        self.assertEqual(tracker.events[1][0]["usage"]["total_tokens"], 3)
        self.assertEqual(self.default_tracker.events, [])
        self.assertEqual(messages, [{"role": "user", "content": "hello"}])

    def test_unobserved_transport_error_does_not_track_successful_usage(self):
        with self.assertRaisesRegex(RuntimeError, "transport"):
            self._call(SequenceClient([RuntimeError("transport")]))
        self.assertEqual(self.default_tracker.events, [])

    def test_empty_text_recovery_emits_once_per_attempt_and_preserves_actual_zero(self):
        tracker = RecordingTracker()
        logged = []
        observer = make_legacy_receipt_observer(
            endpoint_name="main_dm", messages=[], tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logged.append((args, kwargs)),
        )
        client = SequenceClient([
            response("", {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1, "cost": 0.0}),
            response("ok", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}),
        ])
        self.assertEqual(self._call(client, observer, empty_retry_limit=1), "ok")
        self.assertEqual(len(tracker.events), 2)
        self.assertEqual(len(logged), 2)
        self.assertEqual(tracker.events[0][0]["usage"]["cost"], 0.0)
        self.assertEqual(logged[0][1]["metadata"]["cost_provenance"], "actual")

    def test_three_none_responses_then_fallback_success_reaches_each_consumer_once(self):
        tracker = RecordingTracker()
        logger_calls = []
        trace_calls = []
        observer = make_legacy_receipt_observer(
            endpoint_name="empty-recovery", messages=[], trace_site="combat",
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logger_calls.append(args),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: trace_calls.append((event, fields)),
        )
        primary = SequenceClient([None, None, None])
        fallback_usage = {"prompt_tokens": 6, "completion_tokens": 3, "total_tokens": 9, "cost": 0.0}
        fallback = SequenceClient([response("fallback", fallback_usage)])
        with mock.patch.object(factory, "_get_actual_provider", side_effect=[("openrouter", True), ("openai", False)]):
            with mock.patch.object(factory, "create_chat_client", side_effect=[primary, fallback]):
                self.assertEqual(
                    router_module.LLMRouter().call(
                        "dm_main", [], observer=observer, empty_retry_limit=2
                    ),
                    "fallback",
                )
        self.assertEqual((len(tracker.events), len(logger_calls), len(trace_calls)), (4, 4, 4))
        self.assertEqual([event[0] for event in tracker.events[:3]], [{"usage": None}] * 3)
        self.assertEqual(tracker.events[3][0]["usage"], fallback_usage)
        self.assertEqual([row[1]["attempt_number"] for row in trace_calls], [1, 2, 3, 4])
        self.assertTrue(trace_calls[3][1]["fallback"])

    def test_concurrent_calls_are_independent_and_callbacks_are_outside_router_lock(self):
        clients = [SequenceClient([response(str(index), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]) for index in range(12)]
        clients_iter = iter(clients)
        client_lock = threading.Lock()
        tracker = RecordingTracker()
        logger_events = []
        logger_lock = threading.Lock()
        observer = make_legacy_receipt_observer(
            endpoint_name="parallel", messages=[], tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: (logger_lock.acquire(), logger_events.append(args), logger_lock.release()),
        )
        lock_checks = []

        def wrapped(receipt, raw):
            acquired = router_module._USAGE_LOCK.acquire(blocking=False)
            lock_checks.append(acquired)
            if acquired:
                router_module._USAGE_LOCK.release()
            observer(receipt, raw)

        def run(_):
            return router_module.LLMRouter().call(
                "dm_main", [{"role": "user", "content": "hello"}], observer=wrapped
            )

        def next_client():
            with client_lock:
                return next(clients_iter)

        with mock.patch.object(factory, "create_chat_client", side_effect=next_client):
            with ThreadPoolExecutor(max_workers=12) as pool:
                list(pool.map(run, range(12)))
        self.assertEqual(len(tracker.events), 12)
        self.assertEqual(len(logger_events), 12)
        self.assertTrue(all(lock_checks))
        self.assertEqual(len({context["call_id"] for _, context in tracker.events}), 12)
        self.assertEqual(len({context["attempt_id"] for _, context in tracker.events}), 12)

    def test_error_and_constructor_events_never_track_or_log_successful_usage(self):
        tracker = RecordingTracker()
        logged = []
        traced = []
        observer = make_legacy_receipt_observer(
            endpoint_name="main_dm", messages=[], trace_site="combat",
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logged.append(args),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: traced.append(fields),
        )
        with self.assertRaisesRegex(RuntimeError, "transport"):
            self._call(SequenceClient([RuntimeError("transport")]), observer)
        self.assertEqual(tracker.events, [])
        self.assertEqual(logged, [])
        self.assertEqual(len(traced), 1)
        self.assertEqual(traced[0]["outcome"], "transport_error")
        self.assertIsNone(traced[0]["cost_usd"])

        with mock.patch.object(factory, "create_chat_client", side_effect=RuntimeError("construction")):
            with self.assertRaisesRegex(RuntimeError, "construction"):
                router_module.LLMRouter().call("dm_main", [], observer=observer)
        self.assertEqual(len(traced), 2)
        self.assertEqual(traced[1]["observation"], "llm_client_construction_error")
        self.assertEqual(tracker.events, [])
        self.assertEqual(logged, [])

    def test_response_kind_with_none_raw_is_adapted_but_errors_are_not(self):
        tracker = RecordingTracker()
        logged = []
        traced = []
        observer = make_legacy_receipt_observer(
            endpoint_name="empty", messages=[], trace_site="combat",
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logged.append((args, kwargs)),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: traced.append((event, fields)),
        )
        with self.assertRaises(Exception):
            self._call(SequenceClient([None]), observer)
        self.assertEqual(len(tracker.events), 1)
        self.assertEqual(tracker.events[0][0], {"usage": None})
        self.assertEqual(len(logged), 1)
        self.assertIsNone(logged[0][0][2])
        self.assertNotIn("prompt_tokens", logged[0][1]["metadata"])
        self.assertFalse(logged[0][1]["metadata"]["usage_available"])
        self.assertEqual(logged[0][1]["metadata"]["cost_provenance"], "unpriced")
        self.assertEqual(traced[0][0], "provider")
        self.assertEqual(traced[0][1]["outcome"], "response")
        self.assertIsNone(traced[0][1]["cost_usd"])

    def test_top_level_actual_cost_enters_detached_tracker_view(self):
        for actual_cost in (0.0, 0.0025):
            with self.subTest(actual_cost=actual_cost):
                tracker = RecordingTracker()
                logger_rows = []
                observer = make_legacy_receipt_observer(
                    endpoint_name="cost", messages=[], tracker_getter=lambda: tracker,
                    api_logger=lambda *args, **kwargs: logger_rows.append(kwargs["metadata"]),
                )
                raw = response("charged", {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})
                raw["cost"] = actual_cost
                raw_bytes = json.dumps(raw, sort_keys=True).encode("utf-8")
                self._call(SequenceClient([raw]), observer)
                self.assertEqual(tracker.events[0][0]["usage"]["cost"], actual_cost)
                self.assertEqual(logger_rows[0]["provider_reported_cost_usd"], actual_cost)
                self.assertEqual(logger_rows[0]["cost_provenance"], "actual")
                self.assertEqual(json.dumps(raw, sort_keys=True).encode("utf-8"), raw_bytes)

    def test_verified_estimate_and_partial_tokens_reach_tracker_once(self):
        tracker = RecordingTracker()
        observer = make_legacy_receipt_observer(tracker_getter=lambda: tracker)
        receipt = SimpleNamespace(
            kind="response", call_id="call-estimated", attempt_id="attempt-estimated",
            attempt_number=1, task="dm_main", tier="complex", profile="verified",
            transport_provider="openrouter", observed_upstream_provider="upstream",
            requested_model="vendor/model", resolved_model="vendor/model",
            transport_retry=False, retry_tier=None, fallback=False,
            prompt_tokens=10, cached_tokens=0, completion_tokens=5,
            cost_usd=0.04, provider_reported_cost_usd=None,
            cost_provenance="estimated", cost_complete=True, usage_complete=True,
            error_type=None, elapsed_ms=1.0,
        )
        raw = response(
            "priced",
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 0},
            },
            model="vendor/model",
        )

        observer(receipt, raw)
        observer(receipt, raw)

        self.assertEqual(len(tracker.events), 1)
        self.assertEqual(
            tracker.events[0][0]["usage"],
            {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        self.assertEqual(tracker.events[0][1]["cost_provenance"], "estimated")
        self.assertEqual(tracker.events[0][1]["cost_usd"], 0.04)

    def test_unknown_and_invalid_usage_counts_are_not_zero_filled(self):
        tracker = RecordingTracker()
        observer = make_legacy_receipt_observer(tracker_getter=lambda: tracker)
        usage_cases = [
            (None, None),
            ({"prompt_tokens": 1, "completion_tokens": 2}, {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}),
            ({"prompt_tokens": True, "completion_tokens": 2, "total_tokens": 3}, {"completion_tokens": 2, "total_tokens": 3}),
            ({"prompt_tokens": -1, "completion_tokens": 2, "total_tokens": 1}, {"completion_tokens": 2, "total_tokens": 1}),
            ({"prompt_tokens": 1.5, "completion_tokens": 2, "total_tokens": 3.5}, {"completion_tokens": 2, "total_tokens": 2}),
            ({"prompt_tokens": float("nan"), "completion_tokens": 2, "total_tokens": 3}, {"completion_tokens": 2, "total_tokens": 3}),
        ]
        for index, (usage, expected) in enumerate(usage_cases):
            raw = response("partial", usage)
            receipt = SimpleNamespace(
                kind="response", call_id="c%d" % index, attempt_id="a%d" % index,
                attempt_number=1, task="dm_main", tier="simple", profile="default",
                transport_provider="openai", observed_upstream_provider="unknown",
                requested_model="requested", resolved_model="gpt-6-luna",
                transport_retry=False, retry_tier=None, fallback=False,
                prompt_tokens=None, cached_tokens=None, completion_tokens=None,
                cost_usd=None, provider_reported_cost_usd=None, cost_provenance="unpriced",
                cost_complete=False, usage_complete=False, error_type=None, elapsed_ms=None,
            )
            observer(receipt, raw)
        self.assertEqual(len(tracker.events), len(usage_cases))
        self.assertEqual(tracker.events[0][0], {"usage": None})
        for event, (_usage, expected) in zip(tracker.events[1:], usage_cases[1:]):
            self.assertEqual(event[0]["usage"], expected)

    def test_context_labels_are_copied_and_receipt_facts_win_collisions(self):
        tracker = RecordingTracker()
        source_context = {
            "endpoint": "combat", "function": "turn", "purpose": "retry",
            "task": "spoof-task", "provider": "spoof-provider",
            "resolved_model": "spoof-model", "cost_usd": 999, "model": "legacy-request-label",
        }
        metadata_rows = []
        observer = make_legacy_receipt_observer(
            endpoint_name="legacy-api", messages=[], legacy_context=source_context,
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: metadata_rows.append(kwargs["metadata"]),
        )
        source_context["purpose"] = "mutated-after-factory"
        self._call(SequenceClient([response("ok", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]), observer)
        metadata = metadata_rows[0]
        self.assertEqual((metadata["endpoint"], metadata["function"], metadata["purpose"]), ("combat", "turn", "retry"))
        self.assertEqual(metadata["task"], "dm_main")
        self.assertEqual(metadata["provider"], "openai")
        self.assertEqual(metadata["resolved_model"], "gpt-6-luna")
        self.assertEqual(metadata["legacy_context_model"], "legacy-request-label")
        self.assertNotEqual(metadata["cost_usd"], 999)
        self.assertNotIn("stats_snapshot", metadata)

    def test_trace_tracker_logger_order_and_reentrant_stats_query(self):
        order = []

        class OrderedTracker:
            def track(self, response, context=None):
                order.append("tracker")

        observer = make_legacy_receipt_observer(
            endpoint_name="ordered", messages=[],
            tracker_getter=lambda: OrderedTracker(),
            api_logger=lambda *args, **kwargs: (
                router_module.llm.get_usage_stats(), order.append("logger")
            ),
            trace_site="combat", trace_gate=lambda: True,
            trace_writer=lambda event, **fields: order.append("trace"),
        )
        self._call(SequenceClient([response("order", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]), observer)
        self.assertEqual(order, ["trace", "tracker", "logger"])

    def test_optional_usage_gate_and_legacy_api_logger_before_tracker_order(self):
        order = []
        observer = make_legacy_receipt_observer(
            endpoint_name="narration_generator", messages=[], track_usage=False,
            api_log_before_tracker=True,
            tracker_getter=lambda: (_ for _ in ()).throw(AssertionError("disabled usage getter")),
            api_logger=lambda *args, **kwargs: order.append("logger"),
        )
        self._call(
            SequenceClient([response("logged", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]),
            observer,
        )
        self.assertEqual(order, ["logger"])

        tracker = RecordingTracker()
        order = []
        observer = make_legacy_receipt_observer(
            endpoint_name="narration_generator", messages=[], track_usage=True,
            api_log_before_tracker=True,
            tracker_getter=lambda: (order.append("tracker-getter") or tracker),
            api_logger=lambda *args, **kwargs: order.append("logger"),
        )
        self._call(
            SequenceClient([response("tracked", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]),
            observer,
        )
        self.assertEqual(order, ["logger", "tracker-getter"])
        self.assertEqual(len(tracker.events), 1)

    def test_constructor_receipt_deduplicates_without_sdk_provider_row(self):
        records = []
        observer = make_legacy_receipt_observer(
            trace_site="combat", trace_gate=lambda: True,
            trace_writer=lambda event, **fields: records.append((event, fields)),
        )
        receipt = SimpleNamespace(
            kind="constructor_error", call_id="call-ctor", attempt_id=None,
            attempt_number=None, task="combat_main", transport_provider="openai",
            requested_model="requested", fallback=False, error_type="RuntimeError",
        )
        observer(receipt, None)
        observer(receipt, None)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0][0], "combat_observation")
        self.assertNotEqual(records[0][0], "provider")

    def test_consumer_failures_are_isolated_and_duplicate_receipt_is_ignored(self):
        invoked = []
        observer = make_legacy_receipt_observer(
            endpoint_name="endpoint", messages=[],
            tracker_getter=lambda: (_ for _ in ()).throw(RuntimeError("tracker")),
            api_logger=lambda *args, **kwargs: invoked.append("logger"),
            trace_site="combat", trace_gate=lambda: True,
            trace_writer=lambda event, **fields: invoked.append("trace"),
        )
        receipt = SimpleNamespace(
            kind="response", attempt_id="attempt", call_id="call", attempt_number=1,
            task="combat_main", tier="complex", profile="default", transport_retry=False,
            retry_tier=None, fallback=False, transport_provider="openai",
            observed_upstream_provider="unknown", requested_model="requested", resolved_model="actual",
            prompt_tokens=1, cached_tokens=0, completion_tokens=2, cost_usd=None,
            cost_provenance="unpriced", cost_complete=False, usage_complete=False,
            error_type=None, elapsed_ms=1.0,
        )
        raw = response("ok")
        observer(receipt, raw)
        observer(receipt, raw)
        self.assertEqual(invoked, ["trace", "logger"])

    def test_trace_writer_failure_does_not_skip_tracker_or_api_logger(self):
        tracker = RecordingTracker()
        logged = []
        observer = make_legacy_receipt_observer(
            endpoint_name="failure-order", messages=[], trace_site="combat",
            tracker_getter=lambda: tracker,
            api_logger=lambda *args, **kwargs: logged.append(args),
            trace_gate=lambda: True,
            trace_writer=lambda event, **fields: (_ for _ in ()).throw(RuntimeError("trace failure")),
        )
        self._call(
            SequenceClient([response("survives", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})]),
            observer,
        )
        self.assertEqual(len(tracker.events), 1)
        self.assertEqual(len(logged), 1)

    def test_trace_off_does_not_call_writer_and_real_writer_keeps_cost_unknown(self):
        writer = mock.Mock()
        tracker = RecordingTracker()
        logged = []
        observer = make_legacy_receipt_observer(
            trace_site="combat", trace_gate=lambda: False, trace_writer=writer,
            tracker_getter=lambda: tracker,
            endpoint_name="off", messages=[], api_logger=lambda *args, **kwargs: logged.append(args),
        )
        self._call(SequenceClient([response("off")]), observer)
        writer.assert_not_called()
        self.assertEqual(len(tracker.events), 1)
        self.assertEqual(len(logged), 1)

        import model_config
        from utils.combat_latency_trace import emit_trace_event

        with tempfile.TemporaryDirectory(prefix="llm-runtime-receipt-", dir="tmp") as directory:
            trace_path = Path(directory) / "combat.jsonl"
            real_writer = lambda event, **fields: emit_trace_event(event, path=trace_path, **fields)
            real_observer = make_legacy_receipt_observer(
                trace_site="combat", trace_gate=lambda: True, trace_writer=real_writer,
                tracker_getter=lambda: RecordingTracker(),
            )
            original = response("unpriced", {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})
            original_bytes = json.dumps(original, sort_keys=True).encode("utf-8")
            with mock.patch.object(model_config, "ENABLE_COMBAT_TURN_TRACE", True):
                self._call(SequenceClient([original]), real_observer)
            self.assertEqual(json.dumps(original, sort_keys=True).encode("utf-8"), original_bytes)
            serialized_events = trace_path.read_text(encoding="ascii").splitlines()
            self.assertEqual(len(serialized_events), 1)
            self.assertTrue(all(len(line.encode("ascii")) <= 8192 for line in serialized_events))
            record = json.loads(serialized_events[0])
            self.assertEqual(record["event_type"], "provider")
            self.assertEqual(record["site"], "combat")
            self.assertEqual(record["model"], "gpt-6-luna")
            self.assertEqual(record["requested_model"], "gpt-6-luna")
            self.assertEqual(record["resolved_model"], "gpt-6-luna")
            self.assertIsNone(record["cost_usd"])
            self.assertEqual(record["cost_provenance"], "unpriced")
            self.assertEqual(record["task"], "dm_main")


if __name__ == "__main__":
    unittest.main()
