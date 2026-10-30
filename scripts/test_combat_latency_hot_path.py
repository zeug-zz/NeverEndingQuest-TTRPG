# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Provider-free contracts for combat hot-path latency work."""

import ast
import builtins
from collections import Counter
import copy
from contextlib import ExitStack
import importlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Arm the process-wide SDK/network tripwires before any production owner import.
from scripts.core_chat_test_safety import (
    arm_process_tripwires,
    install_in_memory_usage_tracker,
)

PROCESS_TRIPWIRES = arm_process_tripwires()


COMBAT_SOURCE_GLOBS = (
    "core/combat/**/*.py",
    "core/managers/*combat*.py",
    "core/managers/*initiative_tracker*.py",
    "core/ai/*combat*.py",
)

# The inventory is intentionally explicit: a newly introduced provider path
# must be reviewed and assigned a verified timeout owner, not silently ignored.
EXPECTED_PROVIDER_SITES = Counter({
    ("core/combat/validation.py", "validate_combat_response", "injected_router"): 1,
    ("core/combat/turn.py", "run_combat_provider_retry_stage", "injected_router"): 3,
    ("core/combat/bootstrap.py", "_startup_provider_call", "injected_router"): 1,
    ("core/combat/bootstrap.py", "_run_initial_scene_generation", "injected_router"): 1,
    # The approved 4c commander-plan site uses the combat-manager router binding.
    ("core/combat/enemy_batch_orchestrator.py", "try_execute_deterministic_enemy_batch", "injected_router"): 1,
    ("core/combat/combat_manager.py", "validation_llm_call", "router"): 1,
    ("core/combat/combat_manager.py", "retry_llm_call", "router"): 1,
    ("core/combat/combat_manager.py", "enemy_batch_llm_call", "router"): 1,
    # Approved 4c D6 background standing-orders prefetch uses the router binding.
    ("core/combat/combat_manager.py", "prefetch_llm_call", "router"): 2,
    # The deterministic ally batch can make its own injected-router plan request.
    ("core/combat/enemy_batch_orchestrator.py", "_run_ally_batch", "injected_router"): 1,
    ("core/combat/combat_manager.py", "startup_llm_call", "router"): 1,
    ("core/combat/combat_manager.py", "summarize_dialogue", "router"): 1,
    ("core/combat/combat_manager.py", "generate_combat_round_summary", "router"): 1,
    ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker", "router"): 1,
    # Combat compression now inherits its request timeout from the router/factory.
    ("core/ai/combat_compression_engine.py", "compress", "router"): 1,
})

LEGACY_TIMEOUT_NAMES = {
    "api_timeout_seconds",
    "combat_api_timeout_seconds",
    "COMBAT_API_TIMEOUT_SECONDS",
    "COMBAT_CONNECT_TIMEOUT_SECONDS",
}
TIMEOUT_KEYWORDS = LEGACY_TIMEOUT_NAMES | {"timeout", "connect_timeout"}

ROUTED_DEPENDENCY_BINDINGS = {
    "core/combat/validation.py": (
        "CombatValidationDependencies",
        "_build_combat_validation_dependencies",
        "validation_llm_call",
    ),
    "core/combat/turn.py": (
        "CombatRetryDependencies",
        "_build_combat_retry_dependencies",
        "retry_llm_call",
    ),
    "core/combat/bootstrap.py": (
        "CombatStartupNarrativeDependencies",
        "_build_startup_narrative_dependencies",
        "startup_llm_call",
    ),
    "core/combat/enemy_batch_orchestrator.py": (
        "EnemyBatchOrchestrationDependencies",
        "_build_enemy_batch_orchestration_dependencies",
        "enemy_batch_llm_call",
    ),
}


def _dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return prefix + "." + node.attr if prefix else node.attr
    return ""


def _scope_name(tree, line_number):
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.lineno <= line_number <= getattr(node, "end_lineno", node.lineno)
    ]
    if not matches:
        return "<module>"
    return min(
        matches,
        key=lambda node: getattr(node, "end_lineno", node.lineno) - node.lineno,
    ).name


def _provider_call_kind(call):
    function_name = _dotted_name(call.func)
    if function_name == "llm.call":
        return "router"
    if function_name == "dependencies.llm_call":
        return "injected_router"
    if function_name.endswith(".chat.completions.create"):
        return "factory_client"
    return None


def _load_combat_sources():
    paths = set()
    for pattern in COMBAT_SOURCE_GLOBS:
        paths.update(path for path in REPO_ROOT.glob(pattern) if path.is_file())
    return {
        path.relative_to(REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(paths)
    }


def _scan_provider_sites(sources):
    sites = []
    for path, source in sources.items():
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kind = _provider_call_kind(node)
            if kind is None:
                continue
            sites.append({
                "path": path,
                "function": _scope_name(tree, node.lineno),
                "kind": kind,
                "line": node.lineno,
                "timeout_keywords": sorted(
                    keyword.arg for keyword in node.keywords
                    if keyword.arg in TIMEOUT_KEYWORDS
                ),
                "call": node,
                "tree": tree,
            })
    return sorted(sites, key=lambda site: (site["path"], site["line"]))


def _has_router_import(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "utils.llm_router":
            if any(alias.name == "llm" for alias in node.names):
                return True
    return False


def _has_call(tree, dotted_function):
    return any(
        isinstance(node, ast.Call) and _dotted_name(node.func) == dotted_function
        for node in ast.walk(tree)
    )


def _functions_named(tree, function_name):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]


def _router_dependency_binding_is_valid(sources, path):
    binding = ROUTED_DEPENDENCY_BINDINGS.get(path)
    if binding is None:
        return False
    dependency_type, builder_name, wrapper_name = binding
    owner_tree = ast.parse(sources["core/combat/combat_manager.py"])
    builders = _functions_named(owner_tree, builder_name)
    wrappers = _functions_named(owner_tree, wrapper_name)
    if len(builders) != 1 or len(wrappers) != 1:
        return False
    if not _has_call(ast.Module(body=wrappers[0].body, type_ignores=[]), "llm.call"):
        return False
    for node in ast.walk(builders[0]):
        if not isinstance(node, ast.Call) or _dotted_name(node.func) != dependency_type:
            continue
        return any(
            keyword.arg == "llm_call" and _dotted_name(keyword.value) == wrapper_name
            for keyword in node.keywords
        )
    return False


def _factory_client_binding_is_valid(site):
    tree = site["tree"]
    class_nodes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "CombatCompressor"
        and node.lineno <= site["line"] <= getattr(node, "end_lineno", node.lineno)
    ]
    if len(class_nodes) != 1:
        return False
    init_methods = [
        node for node in class_nodes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    ]
    if len(init_methods) != 1:
        return False
    factory_imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "utils.ai_client_factory"
        and any(alias.name == "create_chat_client" for alias in node.names)
        for node in ast.walk(tree)
    )
    if not factory_imported:
        return False
    for node in ast.walk(init_methods[0]):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if (
            any(_dotted_name(target) == "self.client" for target in targets)
            and isinstance(node.value, ast.Call)
            and _dotted_name(node.value.func) == "create_chat_client"
        ):
            return True
    return False


def _site_has_timeout_owner(site, sources):
    if site["kind"] == "router":
        return _has_router_import(site["tree"])
    if site["kind"] == "injected_router":
        return _router_dependency_binding_is_valid(sources, site["path"])
    if site["kind"] == "factory_client":
        return _factory_client_binding_is_valid(site)
    return False


def _timeout_policy_values():
    model_tree = ast.parse((REPO_ROOT / "model_config.py").read_text(encoding="utf-8"))
    values = {}
    for node in model_tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return values


def _factory_timeout_contract_is_owned(function, constructors):
    timeout_assignments = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "client_timeout"
            for target in node.targets
        )
    ]
    if len(timeout_assignments) != 1:
        return False
    timeout_call = timeout_assignments[0].value
    if not isinstance(timeout_call, ast.Call):
        return False
    if _dotted_name(timeout_call.func) != "httpx.Timeout":
        return False
    total_is_shared = (
        len(timeout_call.args) == 1
        and isinstance(timeout_call.args[0], ast.Name)
        and timeout_call.args[0].id == "API_TIMEOUT_SECONDS"
    )
    connect = next(
        (keyword.value for keyword in timeout_call.keywords if keyword.arg == "connect"),
        None,
    )
    connect_is_shared = isinstance(connect, ast.Name) and connect.id == "API_CONNECT_TIMEOUT_SECONDS"
    if not (total_is_shared and connect_is_shared):
        return False

    deadline_calls = [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and _dotted_name(node.func) == "create_deadline_http_client"
    ]
    if len(deadline_calls) != 1:
        return False
    deadline_kwargs = {keyword.arg: keyword.value for keyword in deadline_calls[0].keywords}
    if not (
        isinstance(deadline_kwargs.get("timeout"), ast.Name)
        and deadline_kwargs["timeout"].id == "client_timeout"
        and isinstance(deadline_kwargs.get("deadline_seconds"), ast.Name)
        and deadline_kwargs["deadline_seconds"].id == "API_TIMEOUT_SECONDS"
    ):
        return False

    for constructor in constructors:
        timeout = next(
            (keyword.value for keyword in constructor.keywords if keyword.arg == "timeout"),
            None,
        )
        if not isinstance(timeout, ast.Name) or timeout.id != "client_timeout":
            return False
    return True


class TestTimeoutCoverage(unittest.TestCase):
    """Prove each active combat provider route inherits an effective bound."""

    def setUp(self):
        self.sources = _load_combat_sources()
        self.sites = _scan_provider_sites(self.sources)

    def test_active_combat_provider_inventory_is_explicit_and_complete(self):
        observed = Counter(
            (site["path"], site["function"], site["kind"])
            for site in self.sites
        )
        self.assertEqual(observed, EXPECTED_PROVIDER_SITES)

    def test_each_provider_site_has_router_or_factory_timeout_owner(self):
        unbounded = [
            "%s:%s:%s" % (site["path"], site["line"], site["kind"])
            for site in self.sites
            if not _site_has_timeout_owner(site, self.sources)
        ]
        self.assertEqual(unbounded, [])

    def test_provider_sites_have_no_legacy_or_per_call_timeout_keyword(self):
        offenders = [
            "%s:%s:%s" % (site["path"], site["line"], ",".join(site["timeout_keywords"]))
            for site in self.sites if site["timeout_keywords"]
        ]
        self.assertEqual(offenders, [])
        for path, source in self.sources.items():
            if not path.startswith("core/combat/"):
                continue
            tree = ast.parse(source, filename=path)
            stale_names = sorted({
                node.id for node in ast.walk(tree)
                if isinstance(node, ast.Name) and node.id in LEGACY_TIMEOUT_NAMES
            })
            stale_attributes = sorted({
                node.attr for node in ast.walk(tree)
                if isinstance(node, ast.Attribute) and node.attr in LEGACY_TIMEOUT_NAMES
            })
            self.assertEqual(stale_names + stale_attributes, [], path)

    def test_shared_factory_bounds_both_provider_constructors(self):
        factory_source = (REPO_ROOT / "utils/ai_client_factory.py").read_text(encoding="utf-8")
        factory_tree = ast.parse(factory_source)
        factory_functions = _functions_named(factory_tree, "create_chat_client")
        self.assertEqual(len(factory_functions), 1)
        constructors = [
            node for node in ast.walk(factory_functions[0])
            if isinstance(node, ast.Call) and _dotted_name(node.func) == "OpenAI"
        ]
        self.assertEqual(len(constructors), 2)
        self.assertTrue(_factory_timeout_contract_is_owned(factory_functions[0], constructors))

        values = _timeout_policy_values()
        self.assertLessEqual(values["API_TIMEOUT_SECONDS"], values["COMBAT_API_TIMEOUT_SECONDS"])
        self.assertLessEqual(
            values["API_CONNECT_TIMEOUT_SECONDS"], values["COMBAT_CONNECT_TIMEOUT_SECONDS"]
        )

    def test_router_builds_its_request_client_from_the_shared_factory(self):
        router_source = (REPO_ROOT / "utils/llm_router.py").read_text(encoding="utf-8")
        router_tree = ast.parse(router_source)
        call_functions = _functions_named(router_tree, "call")
        router_methods = [
            node for node in call_functions
            if any(isinstance(parent, ast.ClassDef) and parent.name == "LLMRouter"
                   and parent.lineno <= node.lineno <= getattr(parent, "end_lineno", parent.lineno)
                   for parent in ast.walk(router_tree))
        ]
        self.assertEqual(len(router_methods), 1)
        method_tree = ast.Module(body=router_methods[0].body, type_ignores=[])
        self.assertTrue(_has_call(method_tree, "ai_client_factory.create_chat_client"))
        completion_calls = [
            node for node in ast.walk(method_tree)
            if isinstance(node, ast.Call)
            and _dotted_name(node.func).endswith(".chat.completions.create")
        ]
        self.assertTrue(completion_calls)
        self.assertTrue(all(
            not any(keyword.arg in TIMEOUT_KEYWORDS for keyword in call.keywords)
            for call in completion_calls
        ))

    def test_unbounded_hypothetical_provider_sites_are_detected(self):
        hypothetical_sources = {
            "core/combat/hypothetical.py": (
                "def request(client):\n"
                "    return client.chat.completions.create(model='fixture', messages=[])\n"
            ),
            "core/combat/unrouted.py": (
                "def request(llm):\n"
                "    return llm.call('combat_main', [])\n"
            ),
        }
        hypothetical_sites = _scan_provider_sites(hypothetical_sources)
        self.assertEqual(len(hypothetical_sites), 2)
        self.assertTrue(all(
            not _site_has_timeout_owner(site, hypothetical_sources)
            for site in hypothetical_sites
        ))

    def test_startup_provider_helper_has_no_ignored_timeout_parameter(self):
        tree = ast.parse(self.sources["core/combat/bootstrap.py"])
        helpers = _functions_named(tree, "_startup_provider_call")
        self.assertEqual(len(helpers), 1)
        parameter_names = {argument.arg for argument in helpers[0].args.args}
        self.assertNotIn("timeout", parameter_names)


class TestRoundCompression(unittest.TestCase):
    """Provider-free contracts for compression boundaries and deterministic fallbacks."""

    @staticmethod
    def _combat_owner():
        inert_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: None))
        )
        with patch("utils.ai_client_factory.create_chat_client", return_value=inert_client), \
             patch("os.makedirs", return_value=None):
            return importlib.import_module("core.combat.combat_manager")

    @staticmethod
    def _round_history():
        history = [{"role": "system", "content": "combat header"}]
        for round_num in range(1, 6):
            history.extend([
                {"role": "user", "content": f"COMBAT ROUND {round_num}"},
                {"role": "user", "content": (
                    f"[ALREADY_APPLIED] [System: Round {round_num} mechanical event.] "
                    + ("x" * 260 if round_num == 1 else "")
                )},
                {"role": "assistant", "content": f"Round {round_num} narration."},
            ])
        return history

    @staticmethod
    def _summary_body(message):
        return json.loads(message["content"].split("\n", 1)[1])

    def test_retry_attempts_send_uncompressed_history_without_compression_calls(self):
        from core.combat.turn import (
            CombatRetryDependencies,
            CombatRetryInputs,
            run_combat_provider_retry_stage,
        )

        history = [
            {"role": "system", "content": "authoritative head"},
            {"role": "user", "content": "long original " + ("x" * 1500)},
        ]
        tasks = []
        requests = []
        replies = iter(["not json", '{"narration":"ok","actions":[]}'])

        def router_call(task, messages, **kwargs):
            tasks.append(task)
            requests.append(copy.deepcopy(messages))
            return next(replies)

        def is_json(value):
            try:
                return isinstance(json.loads(value), dict)
            except (TypeError, ValueError):
                return False

        dependencies = CombatRetryDependencies(
            client=None,
            use_gpt5_models=False,
            gpt5_mini_model="fixture-mini",
            gpt5_high_reasoning_on_retry=False,
            combat_main_model="fixture-main",
            get_completion_params=lambda role, model, **kwargs: {"model": model, **kwargs},
            get_temperature=lambda encounter, validation_attempt: 0.2,
            perf_counter=lambda: 1.0,
            trace_stage=lambda *args: None,
            trace_provider_call=lambda *args: None,
            export_open=lambda *args, **kwargs: io.StringIO(),
            makedirs=lambda *args, **kwargs: None,
            emit=lambda message: None,
            debug=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            usage_tracking_available=False,
            track_usage=lambda result: None,
            is_valid_json=is_json,
            check_multiple_update_encounter=lambda actions: False,
            make_multiple_update_feedback=lambda parsed: "multiple update correction",
            validate_combatant_integrity=lambda *args, **kwargs: True,
            validate_combat_response=lambda *args, **kwargs: True,
            update_status=lambda *args, **kwargs: None,
            llm_call=router_call,
            receipt_observer_factory=lambda **kwargs: (lambda *args: None),
        )
        result = run_combat_provider_retry_stage(
            CombatRetryInputs(
                conversation_history=history,
                initial_conversation_length=len(history),
                encounter_data={"creatures": []},
                party_tracker_data={},
                multi_pc_manager=None,
                user_input_text="attack",
                max_retries=3,
            ),
            dependencies,
        )
        self.assertTrue(result.valid_response)
        self.assertEqual(tasks, ["combat_main", "combat_main"])
        self.assertEqual(requests[0], history)
        self.assertEqual(requests[1][:-1], history)
        self.assertIn("Please provide a valid JSON response.", requests[1][-1]["content"])
        self.assertEqual(sum(task == "compression" for task in tasks), 0)

    def test_one_boundary_llm_summary_and_repeatable_older_round_summaries(self):
        owner = self._combat_owner()
        history = self._round_history()
        calls = []

        def summarize(round_num, messages):
            calls.append(round_num)
            return {"round": round_num, "actions": ["fixture"]}

        with patch.object(owner, "generate_combat_round_summary", side_effect=summarize):
            first = owner.compress_old_combat_rounds(copy.deepcopy(history), 6, keep_recent_rounds=1)
            self.assertEqual(calls, [4])
            calls.clear()
            second = owner.compress_old_combat_rounds(copy.deepcopy(history), 6, keep_recent_rounds=1)
        self.assertEqual(calls, [4])
        self.assertEqual(
            json.dumps(first, ensure_ascii=True, separators=(",", ":")),
            json.dumps(second, ensure_ascii=True, separators=(",", ":")),
        )
        summaries = {
            round_num: message
            for message in first
            if message.get("role") == "assistant"
            for round_num in range(1, 5)
            if f"COMBAT ROUND {round_num} SUMMARY:" in message.get("content", "")
        }
        self.assertEqual(set(summaries), {1, 2, 3, 4})
        for round_num in (1, 2, 3):
            body = self._summary_body(summaries[round_num])
            self.assertEqual(body["round"], round_num)
            self.assertIs(body["deterministic"], True)
        self.assertEqual(self._summary_body(summaries[4]), {"round": 4, "actions": ["fixture"]})
        first_event = self._summary_body(summaries[1])["applied_events"][0]
        self.assertLessEqual(len(first_event), 240)
        self.assertIn("Round 4 ends and Round 5 begins", [message["content"] for message in first])

    def test_failed_boundary_summary_falls_back_for_code_derived_round_transition(self):
        from core.combat.turn import RoundTransitionDependencies, stage_combat_turn_snapshot

        owner = self._combat_owner()
        calls = []
        saved = []
        bound = []
        history = self._round_history()
        dependencies = RoundTransitionDependencies(
            apply_opening_batch_marker=lambda *args: False,
            sync_available=False,
            save_json=lambda path, value: saved.append((path, value)),
            compress_old_rounds=owner.compress_old_combat_rounds,
            log_debug=lambda *args, **kwargs: None,
            log_info=lambda *args, **kwargs: None,
            log_warning=lambda *args, **kwargs: None,
            bind_history=lambda value: bound.append(value),
        )

        def fail_summary(round_num, messages):
            calls.append(round_num)
            raise RuntimeError("fixture provider failure")

        with patch.object(owner, "generate_combat_round_summary", side_effect=fail_summary):
            result = stage_combat_turn_snapshot(
                {"combat_round": 2, "openingEnemyBatchPending": False},
                history,
                phase_before="ENEMY_PHASE",
                phase_after="ENEMY_PHASE",
                enemy_batch_completed=True,
                opening_batch_pending_before=False,
                dependencies=dependencies,
            )
        self.assertTrue(result.phase_transitioned)
        self.assertTrue(result.round_advanced)
        self.assertEqual(result.encounter_data["combat_round"], 3)
        self.assertEqual(result.encounter_data["combat_phase"], "PC_PHASE")
        self.assertEqual(calls, [1])
        deterministic = next(
            message for message in result.conversation_history
            if message.get("role") == "assistant" and "COMBAT ROUND 1 SUMMARY:" in message.get("content", "")
        )
        self.assertIs(self._summary_body(deterministic)["deterministic"], True)
        self.assertEqual(bound, [result.conversation_history])
        self.assertEqual(saved, [])

    def test_summary_idempotence_and_removed_per_message_cache_write(self):
        owner = self._combat_owner()
        history = self._round_history()
        calls = []
        opened = []

        def record_open(path, *args, **kwargs):
            opened.append(str(path))
            return io.StringIO()

        with patch.object(owner, "generate_combat_round_summary", side_effect=lambda n, m: calls.append(n) or {"round": n}):
            with patch.object(builtins, "open", side_effect=record_open):
                first = owner.compress_old_combat_rounds(history, 6, keep_recent_rounds=1)
                repeated = owner.compress_old_combat_rounds(first, 6, keep_recent_rounds=1)
        self.assertEqual(calls, [4])
        self.assertEqual(first, repeated)
        self.assertFalse(any("combat_user_message_cache.json" in path for path in opened))
        self.assertFalse(hasattr(owner, "combat_message_compressor"))
        source = (REPO_ROOT / "core/combat/combat_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("combat_user_message_cache.json", source)

    def test_validation_bootstrap_and_retry_sources_have_no_compressor_calls(self):
        sources = {
            path: (REPO_ROOT / path).read_text(encoding="utf-8")
            for path in (
                "core/combat/turn.py",
                "core/combat/bootstrap.py",
                "core/combat/validation.py",
            )
        }
        for path, source in sources.items():
            self.assertNotIn("process_combat_conversation", source, path)
            self.assertNotIn("compress_message(", source, path)
        self.assertIn('content[:1200] + " [truncated]"', sources["core/combat/validation.py"])
        self.assertIn("VALIDATION_COMPRESSION_MIN_CHARS", (REPO_ROOT / "core/combat/combat_manager.py").read_text(encoding="utf-8"))


class TestValidationRouting(unittest.TestCase):
    """Provider-free validation skip, trace, and deterministic retry contracts."""

    @staticmethod
    def _validation_fixture():
        from scripts.test_combat_validation_stage import _dependencies

        dependencies, calls = _dependencies()
        return dependencies, calls

    @staticmethod
    def _validate(dependencies, response, *, user_input="hold position", manager=None,
                  encounter=None):
        from core.combat.validation import validate_combat_response

        return validate_combat_response(
            response,
            encounter or {"encounterId": "G5_FIXTURE", "combat_round": 1, "creatures": []},
            user_input,
            conversation_history=[],
            multi_pc_manager=manager,
            dependencies=dependencies,
        )

    def test_empty_and_allowlisted_actions_skip_provider_validation(self):
        for response in (
            '{"narration":"The goblin waits.","actions":[]}',
            '{"narration":"Time passes.","actions":[{"action":"updateTime","parameters":{"minutes":5}}]}',
        ):
            with self.subTest(response=response):
                dependencies, calls = self._validation_fixture()
                self.assertIs(self._validate(dependencies, response), True)
                self.assertEqual(calls["provider"], [])
                self.assertTrue(calls["debug"])

    def test_no_skip_cases_keep_provider_validation_active(self):
        class EnemyBatchManager:
            combat_phase = "ENEMY_PHASE"
            pc_phase_complete = True

            def get_available_pcs(self):
                return []

            def get_forbidden_actors(self):
                return []

            def get_remaining_enemies_for_round(self):
                return ["Goblin"]

        cases = [
            ("unsafe action", '{"narration":"A goblin falls.","actions":[{"action":"updateEncounter","parameters":{}}]}', "hold position", None, None),
            ("possession", '{"narration":"The party waits.","actions":[]}', "Do I still have my sword?", None, None),
            ("bookkeeping correction", '{"narration":"Correction: your gold is now stored in the coin purse.","actions":[]}', "Fix the gold record.", None, None),
            ("enemy batch", '{"narration":"The goblin attacks.","actions":[]}', "Enemies turn.", EnemyBatchManager(), None),
            ("round advance", '{"narration":"The round ends.","combat_round":2,"actions":[]}', "hold position", None, {"encounterId": "G5_FIXTURE", "combat_round": 1, "creatures": []}),
            ("unknown action", '{"narration":"A portal opens.","actions":[{"action":"teleport","parameters":{}}]}', "hold position", None, None),
            ("parse failure", "not-json", "hold position", None, None),
        ]
        for name, response, user_input, manager, encounter in cases:
            with self.subTest(name=name):
                dependencies, calls = self._validation_fixture()
                self._validate(
                    dependencies,
                    response,
                    user_input=user_input,
                    manager=manager,
                    encounter=encounter,
                )
                self.assertEqual(len(calls["provider"]), 1)

    def test_decision_rejects_failed_prechecks_and_unknown_shapes(self):
        from core.combat.validation import decide_validation_routing

        valid = {"narration": "The party waits.", "actions": []}
        decisions = [
            decide_validation_routing(valid, "hold", deterministic_prechecks_passed=False),
            decide_validation_routing(None, "hold"),
            decide_validation_routing({"narration": "Missing actions."}, "hold"),
            decide_validation_routing(
                valid, "hold", full_enemy_batch_intent=True,
            ),
            decide_validation_routing(
                {"narration": "The round ends.", "combat_round": 2, "actions": []},
                "hold", encounter_data={"combat_round": 1},
            ),
            decide_validation_routing(
                {"narration": "A portal opens.", "actions": [{"action": "teleport"}]},
                "hold",
            ),
            decide_validation_routing(
                {"narration": "Malformed action.", "actions": ["updateTime"]},
                "hold",
            ),
        ]
        for skip, reason in decisions:
            self.assertFalse(skip, reason)

    def test_reserved_jev_reasons_are_never_returned(self):
        from core.combat.validation import decide_validation_routing
        from utils.validation_routing import JEV_RESERVED_REASON_NAMES

        candidates = [
            ({"narration": "The party waits.", "actions": []}, "hold"),
            ({"narration": "A portal opens.", "actions": [{"action": "teleport"}]}, "hold"),
            (None, "hold"),
        ]
        for payload, utterance in candidates:
            skip, reason = decide_validation_routing(payload, utterance)
            self.assertNotIn(reason, JEV_RESERVED_REASON_NAMES)
            if payload is None or payload.get("actions") != []:
                self.assertFalse(skip)

    def test_validation_decision_trace_matches_g5_report_contract(self):
        from core.combat.validation import validate_combat_response
        from scripts.combat_latency_report import _g5_extract_rates

        dependencies, calls = self._validation_fixture()
        events = []

        def capture(point, source, started_at, provider_call_avoided, **fields):
            events.append({
                "event_type": "decision",
                "decision_point": point,
                "decision_source": source,
                "decision_latency_ms": 0.0,
                "provider_call_avoided": provider_call_avoided,
                **fields,
            })
            return True

        with patch("utils.combat_latency_trace.trace_enabled", return_value=True), \
             patch("utils.combat_latency_trace.trace_decision", side_effect=capture):
            self.assertIs(
                validate_combat_response(
                    '{"narration":"The party waits.","actions":[]}',
                    {"encounterId": "G5_FIXTURE", "combat_round": 1, "creatures": []},
                    "hold position",
                    conversation_history=[],
                    dependencies=dependencies,
                ),
                True,
            )

        self.assertEqual(calls["provider"], [])
        self.assertEqual(len(events), 1)
        event = events[0]
        for field in (
            "decision_point", "decision_source", "decision_latency_ms",
            "provider_call_avoided", "outcome", "skip_llm_validation", "reason",
        ):
            self.assertIn(field, event)
        self.assertEqual(event["decision_point"], "validation_routing")
        self.assertEqual(event["decision_source"], "deterministic")
        self.assertEqual(event["outcome"], "skip")
        self.assertIs(event["provider_call_avoided"], True)
        report = _g5_extract_rates(events)
        self.assertEqual(report["validation_skip"]["skipped"]["count"], 1)
        self.assertEqual(
            report["validation_skip"]["skip_reasons"],
            {"low_risk_actions_only": 1},
        )

    @staticmethod
    def _retry_fixture(replies, *, validation_result=True, integrity=True, multiple=False):
        from core.combat.turn import CombatRetryDependencies

        calls = {"provider": [], "validation": [], "warnings": [], "errors": []}

        def is_valid_json(value):
            try:
                payload = json.loads(value)
            except (TypeError, ValueError):
                return False
            return (
                isinstance(payload, dict)
                and isinstance(payload.get("narration"), str)
                and isinstance(payload.get("actions"), list)
            )

        def router_call(task, messages, **kwargs):
            calls["provider"].append({"task": task, "messages": messages, **kwargs})
            item = replies.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item

        def validate(*args, **kwargs):
            calls["validation"].append((args, kwargs))
            if isinstance(validation_result, list):
                return validation_result.pop(0)
            return validation_result

        dependencies = CombatRetryDependencies(
            client=None,
            use_gpt5_models=False,
            gpt5_mini_model="fixture-mini",
            gpt5_high_reasoning_on_retry=False,
            combat_main_model="fixture-main",
            get_completion_params=lambda role, model, **kwargs: {"model": model, **kwargs},
            get_temperature=lambda encounter, validation_attempt: 0.2,
            perf_counter=lambda: 10.0,
            trace_stage=lambda *args: None,
            trace_provider_call=lambda *args: None,
            export_open=lambda *args, **kwargs: io.StringIO(),
            makedirs=lambda *args, **kwargs: None,
            emit=lambda message: None,
            debug=lambda *args, **kwargs: None,
            warning=lambda message, **kwargs: calls["warnings"].append(message),
            error=lambda *args, **kwargs: calls["errors"].append(args),
            usage_tracking_available=False,
            track_usage=lambda result: None,
            is_valid_json=is_valid_json,
            check_multiple_update_encounter=lambda actions: multiple,
            make_multiple_update_feedback=lambda parsed: "multiple update correction",
            validate_combatant_integrity=lambda *args, **kwargs: integrity,
            validate_combat_response=validate,
            update_status=lambda *args, **kwargs: None,
            debug_dumps_enabled=lambda: False,
            llm_call=router_call,
            receipt_observer_factory=lambda **kwargs: (lambda *args: None),
        )
        return dependencies, calls

    def _run_retry_fixture(self, dependencies, *, max_retries=5):
        from core.combat.turn import CombatRetryInputs, run_combat_provider_retry_stage

        return run_combat_provider_retry_stage(
            CombatRetryInputs(
                conversation_history=[{"role": "system", "content": "fixture"}],
                initial_conversation_length=1,
                encounter_data={"encounterId": "FIXTURE", "creatures": []},
                party_tracker_data={},
                multi_pc_manager=None,
                user_input_text="attack",
                max_retries=max_retries,
            ),
            dependencies,
        )

    def test_deterministic_precheck_failures_stop_at_two_and_keep_last_response(self):
        replies = [
            '{"narration":"first","actions":[]}',
            '{"narration":"second","actions":[]}',
            '{"narration":"third","actions":[]}',
        ]
        dependencies, calls = self._retry_fixture(
            replies, validation_result="VALIDATION FAILURE: deterministic fixture rejection"
        )
        result = self._run_retry_fixture(dependencies)
        self.assertFalse(result.valid_response)
        self.assertEqual(len(calls["provider"]), 2)
        self.assertEqual(len(calls["validation"]), 2)
        self.assertIn('"narration":"second"', result.ai_response)
        self.assertIn(
            "VALIDATION: Max retries exceeded for combat validation. Using last response.",
            calls["warnings"],
        )

    def test_two_invalid_json_attempts_do_not_stop_ladder_before_third_attempt(self):
        valid = '{"narration":"recovered","actions":[]}'
        dependencies, calls = self._retry_fixture(
            ["not-json", "still-not-json", valid],
            validation_result=True,
        )
        result = self._run_retry_fixture(dependencies, max_retries=5)

        self.assertTrue(result.valid_response)
        self.assertEqual(len(calls["provider"]), 3)
        self.assertEqual(len(calls["validation"]), 1)
        self.assertEqual(
            [attempt["error_type"] for attempt in result.validation_attempts],
            ["json_format", "json_format"],
        )

    def test_one_invalid_json_plus_one_guard_rejection_does_not_hit_cap(self):
        valid = '{"narration":"recovered","actions":[]}'
        dependencies, calls = self._retry_fixture(
            ["not-json", valid, valid],
            validation_result=["VALIDATION FAILURE: deterministic fixture rejection", True],
        )
        result = self._run_retry_fixture(dependencies, max_retries=5)

        self.assertTrue(result.valid_response)
        self.assertEqual(len(calls["provider"]), 3)
        self.assertEqual(len(calls["validation"]), 2)
        self.assertEqual(
            [attempt["error_type"] for attempt in result.validation_attempts],
            ["json_format", "deterministic_precheck"],
        )

    def test_integrity_and_multiple_action_rejections_share_two_attempt_cap(self):
        valid = '{"narration":"rejected","actions":[]}'
        cases = (
            ("integrity", [valid, valid, valid], False, False, 0),
            ("multiple", [valid, valid, valid], True, True, 0),
        )
        for name, replies, integrity, multiple, expected_validation in cases:
            with self.subTest(name=name):
                dependencies, calls = self._retry_fixture(
                    replies,
                    validation_result=True,
                    integrity=integrity,
                    multiple=multiple,
                )
                result = self._run_retry_fixture(dependencies)
                self.assertFalse(result.valid_response)
                self.assertEqual(len(calls["provider"]), 2)
                self.assertEqual(len(calls["validation"]), expected_validation)

    def test_llm_judgment_failures_and_router_terminal_errors_are_not_capped(self):
        valid = '{"narration":"candidate","actions":[]}'
        dependencies, calls = self._retry_fixture(
            [valid, valid, valid],
            validation_result=["LLM says revise", "LLM says revise", True],
        )
        result = self._run_retry_fixture(dependencies, max_retries=3)
        self.assertTrue(result.valid_response)
        self.assertEqual(len(calls["provider"]), 3)
        self.assertEqual(len(calls["validation"]), 3)

        from utils.llm_router import GameLLMTerminalError

        dependencies, calls = self._retry_fixture([GameLLMTerminalError("quota")])
        with self.assertRaises(GameLLMTerminalError):
            self._run_retry_fixture(dependencies)
        self.assertEqual(len(calls["provider"]), 1)
        self.assertEqual(calls["validation"], [])

    def test_rollback_switch_disables_skips_and_restores_prior_retry_bound(self):
        import core.combat.validation as validation

        original = validation.VALIDATION_ROUTING_ENABLED
        try:
            validation.VALIDATION_ROUTING_ENABLED = False
            self.assertEqual(
                validation.decide_validation_routing(
                    {"narration": "The party waits.", "actions": []}, "hold"
                    ),
                (False, "validation_routing_disabled"),
            )
            valid = '{"narration":"candidate","actions":[]}'
            dependencies, calls = self._retry_fixture(
                [valid, valid, valid],
                validation_result="VALIDATION FAILURE: deterministic fixture rejection",
            )
            result = self._run_retry_fixture(dependencies, max_retries=3)
            self.assertFalse(result.valid_response)
            self.assertEqual(len(calls["provider"]), 3)
        finally:
            validation.VALIDATION_ROUTING_ENABLED = original
        source = (REPO_ROOT / "core/combat/turn.py").read_text(encoding="utf-8")
        self.assertIn(
            "if combat_validation.VALIDATION_ROUTING_ENABLED else max_retries",
            source,
        )


class TestContextMemoization(unittest.TestCase):
    @staticmethod
    def _build_manager():
        from core.combat.multi_pc.manager import MultiPCCombatManager
        from core.combat.multi_pc.state import PCCombatState, PCStatus
        from core.combat.multi_pc.turn_queue import Combatant, CombatantType

        manager = MultiPCCombatManager()
        manager._state.current_round = 3
        manager._state.current_pc_name = "Acheron"
        manager._state.party_initiative = 17
        manager._state.enemy_initiative = 12
        manager._state.party_goes_first = True
        manager._state.pc_states = {
            "Acheron": PCCombatState(
                character_name="Acheron",
                status=PCStatus.READY,
                current_hp=21,
                max_hp=25,
                ac=16,
                metadata={"position": "front"},
            ),
            "Merisiel": PCCombatState(
                character_name="Merisiel",
                status=PCStatus.ACTED,
                current_hp=18,
                max_hp=22,
                ac=15,
            ),
        }
        manager._turns.turn_queue = [
            Combatant("Acheron", CombatantType.PC, 17, 21, 25, 16),
            Combatant("Merisiel", CombatantType.PC, 14, 18, 22, 15),
            Combatant("Goblin Raider", CombatantType.ENEMY, 12, 7, 7, 13),
        ]
        encounter = {
            "encounterId": "context-cache-fixture",
            "creatures": [{
                "name": "Goblin Raider",
                "type": "enemy",
                "currentHitPoints": 7,
                "maxHitPoints": 7,
            }],
        }
        manager.bind_context_encounter(encounter)
        manager.record_pc_phase_event(
            "manual_note",
            "Acheron",
            facts={"note": "The party holds position."},
            narration="The party holds position.",
            source_key="context-cache-initial-ledger-event",
        )
        return manager, encounter

    def test_five_renderers_are_byte_identical_and_render_once_per_key(self):
        manager, encounter = self._build_manager()
        cases = (
            (
                "_render_multi_pc_head_context",
                lambda owner: owner.format_multi_pc_head_context(),
                lambda owner: owner._render_multi_pc_head_context(),
            ),
            (
                "_render_initiative_tracker",
                lambda owner: owner.format_initiative_tracker(encounter),
                lambda owner: owner._render_initiative_tracker(encounter),
            ),
            (
                "_render_party_turn_summary",
                lambda owner: owner.format_party_turn_summary(),
                lambda owner: owner._render_party_turn_summary(),
            ),
            (
                "_render_pc_context_for_prompt",
                lambda owner: owner.format_pc_context_for_prompt("Acheron"),
                lambda owner: owner._render_pc_context_for_prompt("Acheron"),
            ),
            (
                "_render_pc_phase_event_ledger_for_prompt",
                lambda owner: owner.format_pc_phase_event_ledger_for_prompt(),
                lambda owner: owner._render_pc_phase_event_ledger_for_prompt(),
            ),
        )

        for render_name, cached_call, fresh_call in cases:
            with self.subTest(renderer=render_name):
                expected = fresh_call(manager)
                with patch.object(
                    manager,
                    render_name,
                    wraps=getattr(manager, render_name),
                ) as renderer:
                    first = cached_call(manager)
                    second = cached_call(manager)
                self.assertEqual(first, expected)
                self.assertEqual(second, expected)
                self.assertEqual(renderer.call_count, 1)

    def test_state_and_folded_inputs_invalidate_cached_context(self):
        manager, encounter = self._build_manager()
        with patch.object(
            manager,
            "_render_multi_pc_head_context",
            wraps=manager._render_multi_pc_head_context,
        ) as renderer:
            original = manager.format_multi_pc_head_context()
            self.assertEqual(manager.format_multi_pc_head_context(), original)
            self.assertEqual(renderer.call_count, 1)

            manager._state.current_round += 1
            changed_round = manager.format_multi_pc_head_context()
            self.assertNotEqual(changed_round, original)
            self.assertEqual(renderer.call_count, 2)

            manager._turns.pc_phase_complete = True
            changed_phase = manager.format_multi_pc_head_context()
            self.assertNotEqual(changed_phase, changed_round)
            self.assertEqual(renderer.call_count, 3)

            manager._state.current_pc_name = "Merisiel"
            changed_active_pc = manager.format_multi_pc_head_context()
            self.assertNotEqual(changed_active_pc, changed_phase)
            self.assertEqual(renderer.call_count, 4)

            encounter["creatures"][0]["currentHitPoints"] = 4
            manager.bind_context_encounter(encounter)
            encounter_changed = manager.format_multi_pc_head_context()
            # Head output does not include enemy HP, but its renderer must run
            # again because the authoritative encounter revision changed.
            self.assertEqual(encounter_changed, changed_active_pc)
            self.assertEqual(renderer.call_count, 5)

        with patch.object(
            manager,
            "_render_pc_phase_event_ledger_for_prompt",
            wraps=manager._render_pc_phase_event_ledger_for_prompt,
        ) as ledger_renderer:
            before = manager.format_pc_phase_event_ledger_for_prompt()
            self.assertEqual(manager.format_pc_phase_event_ledger_for_prompt(), before)
            self.assertEqual(ledger_renderer.call_count, 1)
            manager.record_pc_phase_event(
                "manual_note",
                "Merisiel",
                facts={"note": "A new event was recorded."},
                narration="A new event was recorded.",
                source_key="context-cache-second-ledger-event",
            )
            after = manager.format_pc_phase_event_ledger_for_prompt()
            self.assertNotEqual(after, before)
            self.assertEqual(ledger_renderer.call_count, 2)

    def test_bypass_renders_fresh_and_cache_is_bounded_to_current_state(self):
        from core.combat.context_cache import CombatContextCache

        manager, _encounter = self._build_manager()
        with patch(
            "core.combat.context_cache.CONTEXT_MEMOIZATION_ENABLED",
            False,
        ):
            with patch.object(
                manager,
                "_render_party_turn_summary",
                wraps=manager._render_party_turn_summary,
            ) as renderer:
                first = manager.format_party_turn_summary()
                second = manager.format_party_turn_summary()
            self.assertEqual(first, second)
            self.assertEqual(renderer.call_count, 2)

        cache = CombatContextCache(max_entries=2)
        first_state = (1, "PC_PHASE", "Acheron", "revision-1")
        cache.get_or_render(first_state, "renderer-1", lambda: "one")
        cache.get_or_render(first_state, "renderer-2", lambda: "two")
        cache.get_or_render(first_state, "renderer-3", lambda: "three")
        self.assertEqual(cache.size, 2)

        second_state = (2, "PC_PHASE", "Acheron", "revision-2")
        cache.get_or_render(second_state, "renderer-1", lambda: "new state")
        self.assertEqual(cache.size, 1)
        self.assertEqual(cache._current_state_key, second_state)

        other_manager, _ = self._build_manager()
        self.assertIsNot(manager._context_cache, other_manager._context_cache)

    def test_undigestible_snapshot_bypasses_memoization_and_renders_fresh(self):
        from core.combat.multi_pc.manager import MultiPCCombatManager
        from core.combat.multi_pc.state import PCStatus

        manager = MultiPCCombatManager()
        manager._state.pc_states = {
            "Acheron": SimpleNamespace(
                status=PCStatus.READY,
                current_hp=10,
                max_hp=10,
            ),
        }
        with patch.object(
            manager,
            "_render_party_turn_summary",
            wraps=manager._render_party_turn_summary,
        ) as renderer:
            first = manager.format_party_turn_summary()
            second = manager.format_party_turn_summary()

        self.assertEqual(first, second)
        self.assertEqual(renderer.call_count, 2)

    def test_combat_session_binds_initial_and_reloaded_encounter(self):
        from core.combat.session import CombatSession

        manager, initial_encounter = self._build_manager()
        session = CombatSession(
            encounter=initial_encounter,
            multi_pc_manager=manager,
        )
        self.assertIs(manager._context_encounter, initial_encounter)

        reloaded_encounter = copy.deepcopy(initial_encounter)
        reloaded_encounter["creatures"][0]["currentHitPoints"] = 2
        self.assertIs(session.bind_encounter(reloaded_encounter), reloaded_encounter)
        self.assertIs(manager._context_encounter, reloaded_encounter)


class TestDebugDumpGating(unittest.TestCase):
    def test_turn_no_longer_writes_messages_dump_and_response_dump_is_gated(self):
        source = (REPO_ROOT / "core/combat/turn.py").read_text(encoding="utf-8")
        self.assertNotIn("combat_messages_to_api.json", source)
        self.assertIn("if dependencies.debug_dumps_enabled():", source)

    def test_validation_and_bootstrap_per_attempt_dumps_are_gated(self):
        validation = (REPO_ROOT / "core/combat/validation.py").read_text(encoding="utf-8")
        bootstrap = (REPO_ROOT / "core/combat/bootstrap.py").read_text(encoding="utf-8")
        initiative = (REPO_ROOT / "core/combat/initiative_tracker_ai.py").read_text(encoding="utf-8")
        self.assertIn('filename = f"validation_{timestamp}_{encounter_id}_attempt{attempt + 1}.json"', validation)
        self.assertIn("if dependencies.debug_dumps_enabled():", validation)
        self.assertGreaterEqual(bootstrap.count("if dependencies.debug_dumps_enabled():"), 2)
        self.assertGreaterEqual(initiative.count("if combat_debug_dumps_enabled():"), 2)

    def test_latency_trace_remains_independent(self):
        source = (REPO_ROOT / "core/combat/turn.py").read_text(encoding="utf-8")
        self.assertIn("trace_enabled", source)
        self.assertNotIn("debug_dumps_enabled() and trace_enabled", source)


class TestEncounterSyncCadence(unittest.TestCase):
    ENCOUNTER_PATH = "modules/encounters/encounter_sync-test.json"
    CHARACTER_PATH = "characters/acheron.json"

    def setUp(self):
        # The legacy owner module constructs a client and creates combat_logs
        # at import time; replace both side effects while loading its sync seam.
        with patch("utils.ai_client_factory.create_chat_client", return_value=SimpleNamespace()), patch("os.makedirs"):
            self.combat_manager = importlib.import_module("core.combat.combat_manager")
        from core.combat.session import CombatSession

        self.CombatSession = CombatSession
        self.party_tracker = {
            "module": "Sync Test",
            "active_character": "Acheron",
            "partyMembers": ["Acheron"],
            "worldConditions": {"activeCombatEncounter": "sync-test"},
        }
        self.store = {
            "encounter": {
                "encounterId": "sync-test",
                "creatures": [{
                    "type": "player",
                    "name": "Acheron",
                    "currentHitPoints": 8,
                    "maxHitPoints": 12,
                    "status": "alive",
                    "conditions": [],
                }],
            },
            "character": {
                "name": "Acheron",
                "hitPoints": 8,
                "maxHitPoints": 12,
                "status": "alive",
                "condition_affected": [],
            },
        }
        self.reads = []
        self.writes = []
        self.trace_events = []
        self.path_manager = SimpleNamespace(
            get_character_path=lambda name: self.CHARACTER_PATH
        )

        def load_json(path):
            self.reads.append(path)
            if path == self.ENCOUNTER_PATH:
                return copy.deepcopy(self.store["encounter"])
            if path == self.CHARACTER_PATH:
                return copy.deepcopy(self.store["character"])
            if path == "party_tracker.json":
                return copy.deepcopy(self.party_tracker)
            return None

        def write_json(path, data):
            self.writes.append((path, copy.deepcopy(data)))
            if path == self.ENCOUNTER_PATH:
                self.store["encounter"] = copy.deepcopy(data)
            elif path == self.CHARACTER_PATH:
                self.store["character"] = copy.deepcopy(data)
            return True

        self.load_json = load_json
        self._patches = ExitStack()
        self.addCleanup(self._patches.close)
        self._patches.enter_context(
            patch.object(self.combat_manager, "safe_json_load", side_effect=load_json)
        )
        self.atomic_write = self._patches.enter_context(
            patch.object(self.combat_manager, "safe_write_json", side_effect=write_json)
        )
        self.module_path_manager_factory = self._patches.enter_context(
            patch("utils.module_path_manager.ModulePathManager", return_value=self.path_manager)
        )
        self._patches.enter_context(
            patch.object(self.combat_manager, "normalize_life_state_fields", side_effect=lambda value: value)
        )
        self._patches.enter_context(
            patch.object(self.combat_manager, "load_npc_with_fuzzy_match", return_value=(None, None))
        )
        self._patches.enter_context(
            patch.object(self.combat_manager, "trace_file_operation", side_effect=lambda *args: self.trace_events.append(args))
        )
        for logger_name in ("debug", "warning", "error"):
            self._patches.enter_context(patch.object(self.combat_manager, logger_name))

    def _new_session(self):
        return self.CombatSession(encounter=copy.deepcopy(self.store["encounter"]))

    def _sync(self, session, turn_identity, *, force=False):
        return self.combat_manager.sync_active_encounter(
            self.party_tracker,
            session,
            turn_identity,
            force=force,
        )

    def test_repeated_sync_is_guarded_and_unchanged_state_has_no_write_or_trace(self):
        # Deliberately use a different dictionary insertion order from the JSON
        # file's eventual canonical order; key ordering alone is not a change.
        self.store["encounter"] = {
            "creatures": [copy.deepcopy(self.store["encounter"]["creatures"][0])],
            "encounterId": "sync-test",
        }
        session = self._new_session()
        turn_identity = session.begin_turn_iteration()

        self.assertFalse(self._sync(session, turn_identity))
        self.assertFalse(self._sync(session, turn_identity))

        self.atomic_write.assert_not_called()
        self.assertEqual(self.trace_events, [])
        self.assertEqual(self.reads.count(self.ENCOUNTER_PATH), 1)
        self.assertEqual(self.reads.count(self.CHARACTER_PATH), 1)
        self.assertNotIn("party_tracker.json", self.reads)

    def test_changed_state_writes_atomically_once_per_turn_and_next_turn_is_not_suppressed(self):
        self.store["character"]["hitPoints"] = 6
        session = self._new_session()
        first_turn = session.begin_turn_iteration()

        self.assertIsNone(self._sync(session, first_turn))
        self.assertFalse(self._sync(session, first_turn))
        self.assertEqual(self.atomic_write.call_count, 1)
        self.atomic_write.assert_called_once_with(self.ENCOUNTER_PATH, self.store["encounter"])
        self.assertEqual(self.trace_events, [("write", "active_encounter_sync")])
        self.assertEqual(self.store["encounter"]["creatures"][0]["currentHitPoints"], 6)

        self.store["character"]["hitPoints"] = 5
        next_turn = session.begin_turn_iteration()
        self.assertEqual(next_turn, first_turn + 1)
        self.assertIsNone(self._sync(session, next_turn))
        self.assertEqual(self.atomic_write.call_count, 2)
        self.assertEqual(self.store["encounter"]["creatures"][0]["currentHitPoints"], 5)
        self.assertEqual(
            self.trace_events,
            [("write", "active_encounter_sync"), ("write", "active_encounter_sync")],
        )

    def test_hp_command_forces_same_turn_sync_and_persists_through_atomic_helper(self):
        from core.combat.commands import run_deterministic_command_stage

        session = self._new_session()
        turn_identity = session.begin_turn_iteration()
        self.assertFalse(self._sync(session, turn_identity))
        force_values = []
        sync_results = []

        normal_dependencies = self.combat_manager._build_normal_turn_dependencies(
            lambda: self.path_manager,
            self.load_json,
        )
        io = normal_dependencies.deterministic_command_io_factory(
            self.path_manager,
            self.CHARACTER_PATH,
            session,
            self.party_tracker,
        )
        original_sync = io.sync_active_encounter

        def capture_force(*, force=False):
            force_values.append(force)
            sync_result = original_sync(force=force)
            sync_results.append(sync_result)
            return sync_result

        io.sync_active_encounter = capture_force
        result = run_deterministic_command_stage(
            cmd="/hp -3",
            current_round=1,
            encounter_id="sync-test",
            encounter_data=self.store["encounter"],
            party_tracker_data=self.party_tracker,
            conversation_history=[],
            location_info={},
            player_file=self.CHARACTER_PATH,
            io=io,
        )

        self.assertEqual(result.control_action, "continue")
        self.assertEqual(force_values, [True])
        self.assertEqual(sync_results, [None])
        self.assertEqual(self.store["character"]["hitPoints"], 5)
        self.assertEqual(self.store["encounter"]["creatures"][0]["currentHitPoints"], 5)
        self.assertEqual(self.atomic_write.call_count, 2)
        self.assertEqual(
            self.atomic_write.call_args_list[-1].args,
            (self.ENCOUNTER_PATH, self.store["encounter"]),
        )
        self.assertEqual(
            [path for path, _data in self.writes],
            [self.CHARACTER_PATH, self.ENCOUNTER_PATH],
        )
        self.assertEqual(self.trace_events, [("write", "active_encounter_sync")])

    def test_fresh_resumed_session_claims_its_first_turn_sync(self):
        prior_process_session = self._new_session()
        prior_process_session.turn_iteration_id = 9
        prior_process_session.last_active_encounter_sync_turn_id = 9

        resumed_session = self._new_session()
        first_turn = resumed_session.begin_turn_iteration()
        self.assertEqual(first_turn, 1)
        self.assertIsNone(resumed_session.last_active_encounter_sync_turn_id)

        self.assertFalse(self._sync(resumed_session, first_turn))
        self.assertEqual(self.reads.count(self.ENCOUNTER_PATH), 1)
        self.assertEqual(resumed_session.last_active_encounter_sync_turn_id, first_turn)
        self.assertFalse(self._sync(resumed_session, first_turn))
        self.assertEqual(self.reads.count(self.ENCOUNTER_PATH), 1)

    def test_missing_module_uses_explicit_default_without_party_tracker_reread(self):
        party_snapshot = copy.deepcopy(self.party_tracker)
        party_snapshot.pop("module")
        session = self._new_session()
        turn_identity = session.begin_turn_iteration()

        self.assertFalse(
            self.combat_manager.sync_active_encounter(
                party_snapshot,
                session,
                turn_identity,
            )
        )

        self.module_path_manager_factory.assert_called_once_with("Keep_of_Doom")
        self.assertNotIn("party_tracker.json", self.reads)


class TestRetryTierOnly(unittest.TestCase):
    """Prove validation retry escalation reaches the factory only as a tier."""

    VALID_RESPONSE = '{"narration":"The party regroups.","actions":[]}'

    @staticmethod
    def _request_parameters(request):
        return {key: value for key, value in request.items() if key != "messages"}

    def _run_retry_stage(self, *, use_gpt5_models, high_reasoning_on_retry):
        from dataclasses import replace

        import model_config
        from core.combat.turn import CombatRetryInputs, run_combat_provider_retry_stage
        from utils.llm_router import LLMRouter

        usage_tracker = install_in_memory_usage_tracker(self)

        dependencies, calls = TestValidationRouting._retry_fixture(
            [],
            validation_result=[
                "VALIDATION FAILURE: deterministic fixture rejection",
                True,
            ],
        )
        router_calls = []
        provider_requests = []
        temperatures = []
        self_response = self.VALID_RESPONSE

        class FakeCompletions:
            def create(self, **request):
                provider_requests.append(copy.deepcopy(request))
                return {"choices": [{"message": {"content": self_response}}]}

        class FakeClient:
            def __init__(self):
                self.chat = SimpleNamespace(completions=FakeCompletions())

            def with_options(self, **_options):
                return self

        fake_client = FakeClient()
        router = LLMRouter()
        router.reset_usage_stats()
        self.addCleanup(router.reset_usage_stats)

        def get_temperature(_encounter, validation_attempt):
            value = round(max(0.1, 0.8 - (0.1 * validation_attempt)), 2)
            temperatures.append(value)
            return value

        def router_call(task, messages, **kwargs):
            router_calls.append({"task": task, "messages": messages, "kwargs": dict(kwargs)})
            return router.call(task, messages, **kwargs)

        with patch.object(model_config, "USE_GPT5_MODELS", use_gpt5_models), \
             patch.object(
                 model_config,
                 "GPT5_USE_HIGH_REASONING_ON_RETRY",
                 high_reasoning_on_retry,
             ), \
             patch("utils.ai_client_factory._get_actual_provider", return_value=("openai", False)), \
             patch("utils.ai_client_factory.create_chat_client", return_value=fake_client):
            dependencies = replace(
                dependencies,
                use_gpt5_models=model_config.USE_GPT5_MODELS,
                gpt5_high_reasoning_on_retry=model_config.GPT5_USE_HIGH_REASONING_ON_RETRY,
                get_temperature=get_temperature,
                llm_call=router_call,
            )
            result = run_combat_provider_retry_stage(
                CombatRetryInputs(
                    conversation_history=[{"role": "system", "content": "fixture"}],
                    initial_conversation_length=1,
                    encounter_data={"encounterId": "FIXTURE", "creatures": []},
                    party_tracker_data={},
                    multi_pc_manager=None,
                    user_input_text="attack",
                    max_retries=2,
                ),
                dependencies,
            )

        self.assertEqual(len(usage_tracker.records), 2)
        return result, calls, router_calls, provider_requests, temperatures

    def test_direct_openai_gpt6_retry_keeps_identical_finalized_parameters(self):
        import model_config

        self.assertEqual(model_config.LLM_PROVIDER, "openrouter")
        self.assertEqual(model_config.ACTIVE_PROFILE, "production-auto")
        self.assertEqual(model_config.OPENAI_FALLBACK_MODEL, "gpt-6-luna")
        result, calls, router_calls, requests, temperatures = self._run_retry_stage(
            use_gpt5_models=False,
            high_reasoning_on_retry=False,
        )

        self.assertTrue(result.valid_response)
        self.assertEqual(len(calls["validation"]), 2)
        self.assertEqual(temperatures, [0.8, 0.7])
        self.assertEqual(len(router_calls), 2)
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            [self._request_parameters(request) for request in requests],
            [
                {
                    "model": "gpt-6-luna",
                    "reasoning_effort": "medium",
                    "verbosity": "medium",
                },
                {
                    "model": "gpt-6-luna",
                    "reasoning_effort": "medium",
                    "verbosity": "medium",
                },
            ],
        )
        self.assertNotEqual(requests[0]["messages"], requests[1]["messages"])
        for call in router_calls:
            self.assertNotIn("retry_tier", call["kwargs"])
            for key in ("reasoning_effort", "reasoning", "verbosity", "model", "profile", "model_tier"):
                self.assertNotIn(key, call["kwargs"])

    def test_gpt5_flag_retry_escalates_only_with_router_retry_tier(self):
        result, calls, router_calls, requests, temperatures = self._run_retry_stage(
            use_gpt5_models=True,
            high_reasoning_on_retry=True,
        )

        self.assertTrue(result.valid_response)
        self.assertEqual(len(calls["validation"]), 2)
        self.assertEqual(temperatures, [])
        self.assertEqual(len(router_calls), 2)
        self.assertEqual(len(requests), 2)
        self.assertNotIn("retry_tier", router_calls[0]["kwargs"])
        self.assertEqual(router_calls[1]["kwargs"].get("retry_tier"), "high")
        for call in router_calls:
            for key in ("reasoning_effort", "reasoning", "verbosity", "model", "profile", "model_tier"):
                self.assertNotIn(key, call["kwargs"])
        self.assertEqual(
            [self._request_parameters(request) for request in requests],
            [
                {
                    "model": "gpt-6-luna",
                    "reasoning_effort": "medium",
                    "verbosity": "medium",
                },
                {
                    "model": "gpt-6-luna",
                    "reasoning_effort": "high",
                    "verbosity": "medium",
                },
            ],
        )

    def test_combat_router_calls_have_no_caller_owned_profile_or_reasoning_override(self):
        source_paths = sorted((REPO_ROOT / "core/combat").glob("*.py"))
        source_paths.append(REPO_ROOT / "core/ai/combat_compression_engine.py")
        forbidden_keywords = {
            "reasoning_effort",
            "reasoning",
            "verbosity",
            "model",
            "model_name",
            "model_override",
            "model_tier",
            "profile",
            "profile_name",
            "profile_override",
            "model_profile",
        }
        router_sites = []
        retry_tier_sites = []
        violations = []

        for source_path in source_paths:
            relative_path = source_path.relative_to(REPO_ROOT).as_posix()
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=relative_path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function_name = _dotted_name(node.func)
                if function_name != "llm.call" and not function_name.endswith(".llm_call"):
                    continue
                site = (relative_path, _scope_name(tree, node.lineno), node.lineno)
                router_sites.append(site)
                keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg is not None}
                forbidden = sorted(keyword_names & forbidden_keywords)
                if forbidden:
                    violations.append((site, forbidden))
                if "retry_tier" in keyword_names:
                    retry_tier_sites.append(site)

        self.assertTrue(router_sites)
        self.assertEqual(violations, [])
        self.assertEqual(
            [(path, function) for path, function, _line in retry_tier_sites],
            [("core/combat/turn.py", "run_combat_provider_retry_stage")],
        )

    def test_nonreasoning_task_policy_overrides_legacy_temperature_ladder(self):
        from utils.ai_client_factory import finalize_chat_params

        # Non-reasoning requests use the factory-owned task policy even when
        # legacy callers supply a per-attempt temperature.
        for temperature in (0.8, 0.7):
            for retry_tier in (None, "high"):
                with self.subTest(temperature=temperature, retry_tier=retry_tier):
                    finalized = finalize_chat_params(
                        "gpt-4.1-2025-04-14",
                        params={},
                        temperature=temperature,
                        is_openrouter=False,
                        retry_tier=retry_tier,
                        task_id="combat_main",
                    )
                    self.assertEqual(
                        finalized,
                        {
                            "model": "gpt-4.1-2025-04-14",
                            "temperature": 0.7,
                        },
                    )


class TestNLPcActionCanary(unittest.TestCase):
    """Provider-free coverage for canary eligibility, outcomes, and rollback."""

    @staticmethod
    def _run_decision(*, trace_decision, parsed=None, applied=True, loader_error=None,
                      party_size=1, eligible=True):
        from core.combat.decisions import run_pc_action_decision

        manager = SimpleNamespace(combat_phase="PC_PHASE", current_pc_name="Acheron")
        party_members = ["Acheron"] + ["Party Member %d" % index
                                        for index in range(2, party_size + 1)]

        def parser_loader():
            if loader_error is not None:
                raise loader_error

            def parse_action(*_args, **_kwargs):
                return parsed or {"handled": False}

            def apply_result(*_args, **_kwargs):
                return applied

            return parse_action, apply_result

        return run_pc_action_decision(
            eligible=eligible,
            clean_input="I attack the Goblin",
            encounter_data={"creatures": []},
            party_tracker_data={"partyMembers": party_members},
            actor_name="Acheron",
            multi_pc_manager=manager,
            encounter_id="G5_FIXTURE",
            decision_started_at=1.0,
            trace_decision=trace_decision,
            parser_loader=parser_loader,
        )

    def test_enabled_canary_uses_same_eligibility_for_one_pc_and_multi_pc(self):
        import inspect
        import model_config
        from core.combat.decisions import pc_action_decision_eligible

        self.assertIs(model_config.COMBAT_PC_PHASE_NL_FAST_PATH, True)
        source = inspect.getsource(pc_action_decision_eligible)
        self.assertNotIn("partyMembers", source)
        self.assertNotIn("len(", source)
        for party_size in (1, 4):
            with self.subTest(party_size=party_size):
                manager = SimpleNamespace(combat_phase="PC_PHASE")
                eligible = pc_action_decision_eligible(
                    enabled=model_config.COMBAT_PC_PHASE_NL_FAST_PATH,
                    multi_pc_manager=manager,
                    clean_input="I attack the Goblin",
                    cmd="i attack the goblin",
                )
                from core.combat.decisions import PCActionDecisionStatus

                result = self._run_decision(
                    trace_decision=lambda *_args, **_kwargs: None,
                    parsed={"handled": True},
                    party_size=party_size,
                    eligible=eligible,
                )
                self.assertEqual(result.status, PCActionDecisionStatus.HANDLED)

    def test_hit_miss_false_positive_and_unavailable_emit_distinct_events(self):
        import utils.combat_latency_trace as latency_trace
        from core.combat.decisions import PCActionDecisionStatus

        events = []

        def capture_event(event_type, path=None, **fields):
            events.append({"event_type": event_type, **fields})
            return True

        with patch.object(latency_trace, "trace_enabled", return_value=True), \
             patch.object(latency_trace, "emit_trace_event", side_effect=capture_event):
            hit = self._run_decision(
                trace_decision=latency_trace.trace_decision,
                parsed={"handled": True},
            )
            miss = self._run_decision(
                trace_decision=latency_trace.trace_decision,
                parsed={"handled": False},
            )
            false_positive = self._run_decision(
                trace_decision=latency_trace.trace_decision,
                parsed={"handled": True},
                applied=False,
            )
            unavailable = self._run_decision(
                trace_decision=latency_trace.trace_decision,
                loader_error=ImportError("fixture parser unavailable"),
            )

        self.assertEqual(hit.status, PCActionDecisionStatus.HANDLED)
        self.assertEqual(miss.status, PCActionDecisionStatus.DECLINED)
        self.assertEqual(false_positive.status, PCActionDecisionStatus.DECLINED)
        self.assertEqual(unavailable.status, PCActionDecisionStatus.UNAVAILABLE)
        self.assertEqual(
            [(event["decision_source"], event["outcome"],
              event["llm_fallback"], event["provider_call_avoided"])
             for event in events],
            [
                ("deterministic", "hit", False, True),
                ("llm_fallback", "miss", True, False),
                ("llm_fallback", "false_positive", True, False),
                ("llm_fallback", "unavailable", True, False),
            ],
        )
        self.assertTrue(all(event["decision_point"] == "pc_phase_parser" for event in events))

    def test_ineligible_slash_disabled_and_wrong_phase_inputs_emit_no_event(self):
        import utils.combat_latency_trace as latency_trace
        from core.combat.decisions import (
            PCActionDecisionStatus,
            pc_action_decision_eligible,
            run_pc_action_decision,
        )
        from unittest.mock import Mock

        cases = (
            (False, "PC_PHASE", "move north", "move north"),
            (True, "ENEMY_PHASE", "move north", "move north"),
            (True, "PC_PHASE", "/att Goblin 18", "/att goblin 18"),
        )
        events = []
        loader = Mock()
        manager = SimpleNamespace(combat_phase="PC_PHASE", current_pc_name="Acheron")

        def capture_event(event_type, path=None, **fields):
            events.append({"event_type": event_type, **fields})
            return True

        with patch.object(latency_trace, "trace_enabled", return_value=True), \
             patch.object(latency_trace, "emit_trace_event", side_effect=capture_event):
            for enabled, phase, clean_input, cmd in cases:
                manager.combat_phase = phase
                eligible = pc_action_decision_eligible(
                    enabled=enabled,
                    multi_pc_manager=manager,
                    clean_input=clean_input,
                    cmd=cmd,
                )
                self.assertFalse(eligible)
                result = run_pc_action_decision(
                    eligible=eligible,
                    clean_input=clean_input,
                    encounter_data={},
                    party_tracker_data={"active_character": "Acheron"},
                    actor_name="Acheron",
                    multi_pc_manager=manager,
                    encounter_id="G5_FIXTURE",
                    decision_started_at=1.0,
                    trace_decision=latency_trace.trace_decision,
                    parser_loader=loader,
                )
                self.assertEqual(result.status, PCActionDecisionStatus.UNAVAILABLE)

        loader.assert_not_called()
        self.assertEqual(events, [])

    def test_g5_report_counts_only_parser_events_and_does_not_infer_fallback_kind(self):
        from scripts.combat_latency_report import _g5_extract_rates

        events = [
            {"event_type": "decision", "decision_point": "pc_phase_parser",
             "decision_source": "deterministic", "outcome": "hit", "llm_fallback": False},
            {"event_type": "decision", "decision_point": "pc_phase_parser",
             "decision_source": "llm_fallback", "outcome": "miss", "llm_fallback": True},
            {"event_type": "decision", "decision_point": "pc_phase_parser",
             "decision_source": "llm_fallback", "outcome": "false_positive", "llm_fallback": True},
            {"event_type": "decision", "decision_point": "pc_phase_parser",
             "decision_source": "llm_fallback", "outcome": "unavailable", "llm_fallback": True},
            {"event_type": "decision", "decision_point": "combat_command_fast_path",
             "decision_source": "deterministic", "provider_call_avoided": True},
            {"event_type": "decision", "decision_point": "combat_command_fast_path",
             "decision_source": "llm_fallback", "provider_call_avoided": False},
        ]
        report = _g5_extract_rates(events)["nl_fast_path"]
        self.assertEqual(report["total_events"], 4)
        for name in ("hit", "miss", "false_positive", "unavailable"):
            self.assertEqual(report["outcomes"][name]["count"], 1)
            self.assertEqual(report["outcomes"][name]["rate"], 0.25)
        self.assertEqual(report["outcomes"]["llm_fallback"]["count"], 3)
        self.assertEqual(report["outcomes"]["llm_fallback"]["rate"], 0.75)

        fallback_only = _g5_extract_rates([{
            "event_type": "decision", "decision_point": "pc_phase_parser",
            "decision_source": "llm_fallback",
        }])["nl_fast_path"]["outcomes"]
        self.assertEqual(fallback_only["llm_fallback"]["count"], 1)
        for name in ("miss", "false_positive", "unavailable"):
            self.assertIsNone(fallback_only[name]["count"])

    def test_rollback_flag_disables_parser_and_continues_to_context_assembly(self):
        from dataclasses import replace
        from unittest.mock import Mock

        from core.combat.turn import (
            CombatNormalTurnInputs,
            CombatTurnIterationResult,
            InputPhaseGateResult,
            prepare_combat_normal_turn,
        )

        with patch(
            "utils.ai_client_factory.create_chat_client",
            return_value=SimpleNamespace(),
        ), patch("os.makedirs"):
            import core.combat.combat_manager as combat_manager

        with patch.object(combat_manager, "COMBAT_PC_PHASE_NL_FAST_PATH", False):
            dependencies = combat_manager._build_normal_turn_dependencies(
                lambda _module: SimpleNamespace(), lambda _path: {}
            )
        self.assertIs(dependencies.pc_action_enabled, False)

        trace_decision = Mock()
        assembled = []

        def assemble_context(context_inputs):
            assembled.append(context_inputs)
            return SimpleNamespace(
                return_early=False,
                return_value=None,
                encounter_data=context_inputs.encounter_data,
                user_prompt="LLM context for the existing provider path",
                user_input_text=context_inputs.user_input_text,
            )

        dependencies = replace(
            dependencies,
            input_phase_gate=lambda text, **_kwargs: InputPhaseGateResult(
                raw_input=text, clean_input=text
            ),
            phase_gate_io_factory=lambda _manager: None,
            fast_command_stage=lambda **kwargs: SimpleNamespace(
                control_action="proceed", user_input_text=kwargs["user_input_text"]
            ),
            fast_command_io_factory=lambda: None,
            deterministic_command_stage=lambda **_kwargs: SimpleNamespace(
                control_action="proceed", status=None, return_value=None
            ),
            deterministic_command_io_factory=lambda *_args: None,
            character_stat_command=lambda *_args: False,
            character_stat_io_factory=lambda _manager: None,
            trace_decision=trace_decision,
            enhance_inventory_context=lambda context_inputs: SimpleNamespace(
                user_input_text=context_inputs.user_input_text,
                fresh_player_data=context_inputs.preexisting_player_data,
            ),
            assemble_context=assemble_context,
            clean_old_dm_notes=lambda history: history,
            clean_combat_state_blocks=lambda history: history,
            save_json=Mock(),
            debug=Mock(),
            emit=Mock(),
            flush=Mock(),
        )
        manager = SimpleNamespace(
            combat_phase="PC_PHASE", current_pc_name="Acheron"
        )
        session = SimpleNamespace(
            active_pc=None,
            set_phase=lambda _phase: None,
            bind_history=lambda _history: None,
        )
        encounter = {"encounterId": "G5_FIXTURE", "combat_round": 1, "creatures": []}
        party_tracker = {"active_character": "Acheron", "partyMembers": ["Acheron"]}
        history = []
        iteration = CombatTurnIterationResult(
            session=session,
            encounter_data=encounter,
            multi_pc_manager=manager,
            party_tracker_data=party_tracker,
            conversation_history=history,
            npc_templates={},
            player_file="characters/acheron.json",
            fresh_player_data={},
            current_hp=10,
            max_hp=10,
            player_name_display="Acheron",
            current_round_trace_start=1.0,
            user_input_text="I move cautiously toward the door",
            path_manager=SimpleNamespace(),
            player_info={},
        )
        result = prepare_combat_normal_turn(
            CombatNormalTurnInputs(
                iteration=iteration,
                encounter_id="G5_FIXTURE",
                json_file_path="modules/encounters/encounter_G5_FIXTURE.json",
                conversation_history_file="conversation_history.json",
                location_info={},
            ),
            dependencies,
        )

        self.assertEqual(result.control_action, "proceed")
        self.assertEqual(len(assembled), 1)
        trace_decision.assert_not_called()


def tearDownModule():
    PROCESS_TRIPWIRES.assert_untouched(unittest.TestCase())


if __name__ == "__main__":
    unittest.main()
