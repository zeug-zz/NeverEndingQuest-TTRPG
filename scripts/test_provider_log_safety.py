"""Provider-free regression tests for provider transport log safety."""

import io
import logging
import copy
import pickle
import unittest
from unittest.mock import Mock, patch

import utils.file_operations  # noqa: F401 - exercise application logging bootstrap

from utils.provider_log_safety import (
    build_provider_diagnostic,
    configure_provider_log_safety,
    log_provider_diagnostic,
    sanitize_provider_log_record,
)
import utils.ai_client_factory as ai_client_factory
from utils.toolkit_adaptation_output_safety import AdaptationOutputSafety


class ProviderLogSafetyTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("httpx.tests.provider_payload")
        self._logger_state = (
            self.logger.level,
            list(self.logger.handlers),
            list(self.logger.filters),
            self.logger.propagate,
        )
        self.logger.handlers = []
        self.logger.filters = []
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        self.logger.addHandler(handler)
        configure_provider_log_safety()

    def tearDown(self):
        self.logger.handlers = []
        self.logger.filters = []
        level, handlers, filters, propagate = self._logger_state
        self.logger.setLevel(level)
        self.logger.handlers = handlers
        self.logger.filters = filters
        self.logger.propagate = propagate

    def test_debug_payload_is_suppressed_by_transport_level(self):
        self.logger.debug("prompt SENTINEL_PROMPT", extra={"messages": "SENTINEL_SOURCE"})
        self.assertEqual(self.stream.getvalue(), "")

    def test_late_provider_child_debug_payloads_are_suppressed(self):
        """Child loggers created after setup inherit the provider warning gate."""
        root = logging.getLogger()
        root_stream = io.StringIO()
        root_handler = logging.StreamHandler(root_stream)
        root_handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        root.addHandler(root_handler)
        late_loggers = []
        try:
            # This is the first safety boundary. The child loggers below do not
            # exist yet and therefore exercise lazy provider logger creation.
            configure_provider_log_safety()
            for provider_root in ("openai", "httpx", "httpcore"):
                logger = logging.getLogger(
                    f"{provider_root}.late_payload_regression"
                )
                late_loggers.append(logger)
                logger_level = logger.level
                logger_handlers = list(logger.handlers)
                logger_filters = list(logger.filters)
                logger_propagate = logger.propagate
                logger.setLevel(logging.NOTSET)
                logger.handlers = []
                logger.filters = []
                logger.propagate = True
                logger.debug(
                    "request SENTINEL_PROMPT SENTINEL_SOURCE "
                    "json_data=SENTINEL_JSON response=RAW_RESPONSE "
                    "headers=RAW_HEADERS authorization=Bearer REAL_SECRET "
                    "credential=REAL_CREDENTIAL",
                    extra={
                        "messages": "SENTINEL_PROMPT",
                        "json_data": "SENTINEL_JSON",
                        "request_body": "SENTINEL_REQUEST",
                        "response_body": "RAW_RESPONSE",
                        "headers": "RAW_HEADERS",
                        "authorization": "Bearer REAL_SECRET",
                        "credentials": "REAL_CREDENTIAL",
                    },
                )
                self.assertGreaterEqual(
                    logger.getEffectiveLevel(),
                    logging.WARNING,
                    msg=f"late logger was not gated: {logger.name}",
                )
                # Keep the saved state on the logger for teardown below.
                logger._provider_safety_test_state = (
                    logger_level,
                    logger_handlers,
                    logger_filters,
                    logger_propagate,
                )

            output = root_stream.getvalue()
            for sentinel in (
                "SENTINEL_PROMPT",
                "SENTINEL_SOURCE",
                "SENTINEL_JSON",
                "SENTINEL_REQUEST",
                "RAW_RESPONSE",
                "RAW_HEADERS",
                "REAL_SECRET",
                "REAL_CREDENTIAL",
            ):
                self.assertNotIn(sentinel, output)
        finally:
            for logger in late_loggers:
                logger.handlers = []
                logger.filters = []
                state = getattr(logger, "_provider_safety_test_state", None)
                if state is None:
                    logger.setLevel(logging.NOTSET)
                    logger.propagate = True
                else:
                    level, handlers, filters, propagate = state
                    logger.setLevel(level)
                    logger.handlers = handlers
                    logger.filters = filters
                    logger.propagate = propagate
                    try:
                        del logger._provider_safety_test_state
                    except AttributeError:
                        pass
            root.removeHandler(root_handler)

    def test_warning_payload_is_redacted(self):
        self.logger.warning(
            "provider request",
            extra={
                "messages": "SENTINEL_PROMPT",
                "json_data": '{"source":"SENTINEL_SOURCE"}',
                "authorization": "Bearer REAL_SECRET",
                "api_key": "REAL_API_KEY",
                "response_body": "RAW_RESPONSE",
                "provider": "openai",
                "model": "safe-model",
                "stage": "adaptation",
                "status": "error",
            },
        )
        output = self.stream.getvalue()
        self.assertNotIn("SENTINEL", output)
        self.assertNotIn("REAL_", output)
        self.assertNotIn("RAW_RESPONSE", output)
        self.assertIn("PROVIDER_PAYLOAD_REDACTED", output)

    def test_request_shaped_fields_are_redacted_without_request_mutation(self):
        request = {
            "messages": ["SENTINEL_PROMPT"],
            "json_data": {"source": "SENTINEL_SOURCE"},
            "headers": {"authorization": "Bearer REAL_SECRET"},
            "body": "SENTINEL_REQUEST_BODY",
        }
        request_before = copy.deepcopy(request)
        request_bytes_before = pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL)
        self.logger.warning(
            "request SENTINEL_PROMPT SENTINEL_SOURCE",
            extra={
                "messages": "SENTINEL_PROMPT",
                "json_data": "SENTINEL_SOURCE",
                "request": request,
                "request_body": "SENTINEL_REQUEST_BODY",
                "request_content": "SENTINEL_REQUEST_CONTENT",
                "response": "SENTINEL_RESPONSE",
                "response_content": "SENTINEL_RESPONSE_BODY",
                "authorization": "Bearer REAL_SECRET",
                "bearer": "REAL_BEARER",
                "credentials": "REAL_CREDENTIALS",
                "token": "REAL_TOKEN",
                "secret": "REAL_SECRET",
                "headers": {"Authorization": "Bearer REAL_SECRET"},
            },
        )
        output = self.stream.getvalue()
        for sentinel in (
            "SENTINEL_PROMPT",
            "SENTINEL_SOURCE",
            "SENTINEL_REQUEST_BODY",
            "SENTINEL_REQUEST_CONTENT",
            "SENTINEL_RESPONSE",
            "REAL_SECRET",
            "REAL_BEARER",
            "REAL_CREDENTIALS",
            "REAL_TOKEN",
        ):
            self.assertNotIn(sentinel, output)
        self.assertIn("PROVIDER_PAYLOAD_REDACTED", output)
        self.assertEqual(request["messages"], ["SENTINEL_PROMPT"])
        self.assertEqual(request["json_data"], {"source": "SENTINEL_SOURCE"})
        self.assertEqual(request["headers"]["authorization"], "Bearer REAL_SECRET")
        self.assertEqual(request, request_before)
        self.assertEqual(
            pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL),
            request_bytes_before,
        )

    def test_safety_mutates_only_copied_log_record_fields(self):
        """Record redaction must not traverse or mutate the request payload."""
        request = {
            "messages": [{"role": "user", "content": "SENTINEL_PROMPT"}],
            "json": {"source": "SENTINEL_SOURCE", "nested": [1, {"x": 2}]},
            "headers": {"Authorization": "Bearer REAL_SECRET"},
        }
        request_before = copy.deepcopy(request)
        request_bytes_before = pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL)
        record = logging.LogRecord(
            "httpx.request", logging.WARNING, __file__, 1, "request", (), None
        )
        record.request = request
        record.messages = request["messages"]
        record.headers = request["headers"]

        sanitized = sanitize_provider_log_record(record)

        self.assertIs(sanitized, record)
        self.assertEqual(record.msg, "[PROVIDER_PAYLOAD_REDACTED]")
        self.assertEqual(record.request, "[REDACTED]")
        self.assertEqual(request, request_before)
        self.assertEqual(
            pickle.dumps(request, protocol=pickle.HIGHEST_PROTOCOL),
            request_bytes_before,
        )

    def test_child_logger_handler_and_propagation_are_safe(self):
        root = logging.getLogger()
        root_stream = io.StringIO()
        root_handler = logging.StreamHandler(root_stream)
        root_handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
        root.addHandler(root_handler)

        child = logging.getLogger("openai.transport.deep.child")
        child.handlers = []
        child.propagate = True
        child.setLevel(logging.DEBUG)
        child_stream = io.StringIO()
        child_handler = logging.StreamHandler(child_stream)
        child_handler.setFormatter(logging.Formatter("%(message)s"))
        child.addHandler(child_handler)
        try:
            configure_provider_log_safety()
            child.warning(
                "request SENTINEL_PROMPT SENTINEL_SOURCE",
                extra={
                    "messages": "SENTINEL_PROMPT",
                    "json_data": "SENTINEL_SOURCE",
                    "authorization": "Bearer REAL_SECRET",
                },
            )
            self.assertNotIn("SENTINEL", child_stream.getvalue())
            self.assertNotIn("REAL_SECRET", child_stream.getvalue())
            self.assertNotIn("SENTINEL", root_stream.getvalue())
            self.assertNotIn("REAL_SECRET", root_stream.getvalue())
            self.assertIn("PROVIDER_PAYLOAD_REDACTED", child_stream.getvalue())
            self.assertIn("PROVIDER_PAYLOAD_REDACTED", root_stream.getvalue())
        finally:
            child.removeHandler(child_handler)
            child.handlers = []
            root.removeHandler(root_handler)

    def test_debug_mode_keeps_provider_payloads_hidden_and_safe_diagnostics_visible(self):
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        root.addHandler(handler)
        application_logger = logging.getLogger("NeverEndingQuest.debug.provider_safety")
        provider_logger = logging.getLogger("httpcore.debug.provider_safety")
        previous_application_level = application_logger.level
        previous_provider_level = provider_logger.level
        try:
            application_logger.setLevel(logging.DEBUG)
            provider_logger.setLevel(logging.DEBUG)
            configure_provider_log_safety()
            provider_logger.debug(
                "debug request SENTINEL_PROMPT SENTINEL_SOURCE",
                extra={"messages": "SENTINEL_PROMPT", "json_data": "SENTINEL_SOURCE"},
            )
            application_logger.debug("SAFE_APPLICATION_DIAGNOSTIC")
            log_provider_diagnostic(
                {
                    "provider": "openai",
                    "model": "safe-model",
                    "stage": "adaptation",
                    "status": "success",
                },
                logger=application_logger,
            )
            output = stream.getvalue()
            self.assertNotIn("SENTINEL_PROMPT", output)
            self.assertNotIn("SENTINEL_SOURCE", output)
            self.assertIn("SAFE_APPLICATION_DIAGNOSTIC", output)
            self.assertIn("Provider diagnostic event", output)
        finally:
            root.removeHandler(handler)
            application_logger.setLevel(previous_application_level)
            provider_logger.setLevel(previous_provider_level)

    def test_repeated_configuration_does_not_duplicate_filters(self):
        configure_provider_log_safety()
        configure_provider_log_safety()
        logger = logging.getLogger("httpcore")
        markers = [
            item for item in logger.filters
            if getattr(item, "_neq_provider_log_safety_filter", False)
        ]
        self.assertEqual(len(markers), 1)

    def test_request_object_is_not_mutated(self):
        request = {"messages": ["SENTINEL_PROMPT"], "api_key": "REAL_API_KEY"}
        self.logger.warning("request", extra={"request": request})
        self.assertEqual(request["messages"], ["SENTINEL_PROMPT"])
        self.assertEqual(request["api_key"], "REAL_API_KEY")

    def test_safe_metadata_remains_bounded(self):
        self.logger.warning(
            "provider event",
            extra={"provider": "openai", "model": "model", "status": "ok", "elapsed_ms": 12},
        )
        output = self.stream.getvalue()
        self.assertIn("PROVIDER_PAYLOAD_REDACTED", output)
        self.assertNotIn("messages", output)

    def test_provider_diagnostic_is_allowlisted_and_bounded(self):
        diagnostic = build_provider_diagnostic(
            provider="openai",
            model="gpt-5.6-luna",
            stage="adaptation_authoring",
            status="success",
            elapsed_ms=25.8,
            retry=False,
            fallback=True,
            request_id="req_123",
        )
        self.assertEqual(diagnostic["event"], "provider_diagnostic")
        self.assertEqual(diagnostic["elapsed_ms"], 25)
        self.assertTrue(diagnostic["fallback"])
        self.assertEqual(diagnostic["request_id"], "req_123")

        unsafe = build_provider_diagnostic(
            provider="openai SENTINEL_PROMPT",
            model='model json_data="SENTINEL_SOURCE"',
            stage="adaptation",
            status="error authorization=REAL_SECRET",
            elapsed_ms=float("inf"),
            request_id="Bearer REAL_SECRET",
        )
        self.assertEqual(unsafe["provider"], "unknown")
        self.assertEqual(unsafe["model"], "unknown")
        self.assertEqual(unsafe["status"], "unknown")
        self.assertEqual(unsafe["elapsed_ms"], 0)
        self.assertNotIn("request_id", unsafe)
        self.assertNotIn("SENTINEL", repr(unsafe))

    def test_provider_diagnostic_logging_uses_static_message_only(self):
        records = []
        logger = logging.getLogger("provider_diagnostic_test")
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        try:
            safe = log_provider_diagnostic(
                {
                    "provider": "openai",
                    "model": "gpt-5.6-luna",
                    "stage": "adaptation_authoring",
                    "status": "success",
                    "elapsed_ms": 12,
                    "source_excerpt": "SENTINEL_SOURCE",
                    "prompt": "SENTINEL_PROMPT",
                    "credential": "REAL_SECRET",
                },
                logger=logger,
            )
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].getMessage(), "Provider diagnostic event")
            self.assertNotIn("SENTINEL", repr(safe))
            self.assertNotIn("REAL_SECRET", repr(records[0].__dict__))
        finally:
            logger.removeHandler(handler)
            logger.handlers = []

    def test_application_bootstrap_keeps_provider_debug_out_of_captured_root_handler(self):
        root = logging.getLogger()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))
        root.addHandler(handler)
        application_logger = logging.getLogger("NeverEndingQuest.provider_safety_test")
        provider_logger = logging.getLogger("openai._base_client.provider_safety_test")
        previous_level = application_logger.level
        try:
            application_logger.setLevel(logging.DEBUG)
            configure_provider_log_safety()
            provider_logger.debug(
                "request SENTINEL_PROMPT SENTINEL_SOURCE",
                extra={"messages": "SENTINEL_PROMPT", "json_data": "SENTINEL_SOURCE"},
            )
            application_logger.debug("SAFE_APPLICATION_DEBUG")
            application_logger.error("SAFE_APPLICATION_ERROR")
            output = stream.getvalue()
            self.assertNotIn("SENTINEL_PROMPT", output)
            self.assertNotIn("SENTINEL_SOURCE", output)
            self.assertIn("SAFE_APPLICATION_DEBUG", output)
            self.assertIn("SAFE_APPLICATION_ERROR", output)
        finally:
            root.removeHandler(handler)
            application_logger.setLevel(previous_level)

    def test_shared_factory_configures_safety_before_and_after_primary_client(self):
        events = []
        fake_client = object()
        request_payload = {
            "messages": [{"role": "user", "content": "SENTINEL_PROMPT"}],
            "json_data": {"source": "SENTINEL_SOURCE", "items": [1, 2, 3]},
            "headers": {"authorization": "Bearer REAL_SECRET"},
        }
        payload_before = copy.deepcopy(request_payload)
        payload_bytes_before = pickle.dumps(
            request_payload, protocol=pickle.HIGHEST_PROTOCOL
        )

        def configure():
            events.append("safety")
            record = logging.LogRecord(
                "openai.lazy.request", logging.WARNING, __file__, 1, "request", (), None
            )
            record.request = request_payload
            sanitize_provider_log_record(record)

        def construct(**kwargs):
            events.append(("client", kwargs))
            return fake_client

        with patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openai", False),
        ), patch.object(ai_client_factory, "configure_provider_log_safety", side_effect=configure), patch.object(
            ai_client_factory, "OpenAI", side_effect=construct
        ):
            client = ai_client_factory.create_chat_client()

        self.assertIs(client, fake_client)
        self.assertEqual(events[0], "safety")
        self.assertEqual(events[1][0], "client")
        self.assertEqual(set(events[1][1]), {"api_key"})
        self.assertEqual(events[2], "safety")
        self.assertEqual(request_payload, payload_before)
        self.assertEqual(
            pickle.dumps(request_payload, protocol=pickle.HIGHEST_PROTOCOL),
            payload_bytes_before,
        )

    def test_shared_factory_configures_safety_after_primary_openrouter_client(self):
        events = []
        fake_client = object()

        def configure():
            events.append("safety")

        def construct(**kwargs):
            events.append(("client", kwargs))
            return fake_client

        with patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openrouter", True),
        ), patch.object(ai_client_factory, "configure_provider_log_safety", side_effect=configure), patch.object(
            ai_client_factory, "OpenAI", side_effect=construct
        ):
            client = ai_client_factory.create_chat_client()

        self.assertIs(client, fake_client)
        self.assertEqual(events[0], "safety")
        self.assertEqual(events[1][0], "client")
        self.assertEqual(
            set(events[1][1]),
            {"api_key", "base_url", "default_headers"},
        )
        self.assertEqual(
            set(events[1][1]["default_headers"]),
            {"HTTP-Referer", "X-Title"},
        )
        self.assertEqual(events[2], "safety")

    def test_shared_factory_configures_safety_before_and_after_fallback_client(self):
        events = []
        fake_client = object()

        def configure():
            events.append("safety")

        def construct(**kwargs):
            events.append(("client", kwargs))
            return fake_client

        with patch.object(
            ai_client_factory,
            "_get_actual_provider",
            return_value=("openai", False),
        ), patch.object(ai_client_factory, "configure_provider_log_safety", side_effect=configure), patch.object(
            ai_client_factory, "OpenAI", side_effect=construct
        ):
            client = ai_client_factory.create_chat_client(use_fallback=True)

        self.assertIs(client, fake_client)
        self.assertEqual(events[0], "safety")
        self.assertEqual(events[1][0], "client")
        self.assertEqual(set(events[1][1]), {"api_key"})
        self.assertEqual(events[2], "safety")

    def test_adaptation_scope_contains_late_provider_and_application_handlers(self):
        """Late handlers and child loggers cannot bypass the adaptation boundary."""
        root = logging.getLogger()
        root_stream = io.StringIO()
        root_handler = logging.StreamHandler(root_stream)
        root_handler.setFormatter(logging.Formatter("%(name)s %(levelname)s %(message)s"))

        provider = logging.getLogger("httpcore.late_adaptation_boundary")
        application = logging.getLogger("NeverEndingQuest.late_adaptation_boundary")
        provider_state = (provider.level, list(provider.handlers), provider.propagate)
        application_state = (application.level, list(application.handlers), application.propagate)
        child_stream = io.StringIO()
        child_handler = logging.StreamHandler(child_stream)
        child_handler.setFormatter(logging.Formatter("%(message)s"))
        try:
            with AdaptationOutputSafety(phase="adaptation_build", status="running"):
                # These objects deliberately do not exist at factory/setup time.
                root.addHandler(root_handler)
                provider.handlers = [child_handler]
                provider.propagate = True
                provider.setLevel(logging.DEBUG)
                application.setLevel(logging.DEBUG)
                provider.debug(
                    "request SENTINEL_PROMPT source=SENTINEL_SOURCE "
                    "json_data=SENTINEL_JSON authorization=Bearer REAL_SECRET",
                    extra={
                        "messages": "SENTINEL_PROMPT",
                        "request_body": "SENTINEL_REQUEST",
                        "response_body": "RAW_RESPONSE",
                        "headers": "RAW_HEADERS",
                        "request_id": "REQ_SECRET",
                    },
                )
                application.error("SAFE_APPLICATION_ERROR")

            output = root_stream.getvalue() + child_stream.getvalue()
            for sentinel in (
                "SENTINEL_PROMPT", "SENTINEL_SOURCE", "SENTINEL_JSON",
                "SENTINEL_REQUEST", "RAW_RESPONSE", "RAW_HEADERS",
                "REAL_SECRET", "REQ_SECRET",
            ):
                self.assertNotIn(sentinel, output)
            self.assertIn("provider_payload_suppressed", output)
            self.assertIn("SAFE_APPLICATION_ERROR", output)
        finally:
            root.removeHandler(root_handler)
            provider.handlers = provider_state[1]
            provider.setLevel(provider_state[0])
            provider.propagate = provider_state[2]
            application.handlers = application_state[1]
            application.setLevel(application_state[0])
            application.propagate = application_state[2]


if __name__ == "__main__":
    unittest.main()
