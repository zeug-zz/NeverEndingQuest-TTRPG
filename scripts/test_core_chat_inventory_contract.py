# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.

"""Fresh AST inventory for the 15 scoped core chat operations."""

import ast
import builtins
from pathlib import Path
import socket
import unittest
import os
import shutil
import tempfile

from scripts.core_chat_test_safety import arm_process_tripwires

_TRIPWIRES = arm_process_tripwires()
ROOT = Path(__file__).resolve().parents[1]


def _functions(relative_path):
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls(node):
    return [item for item in ast.walk(node) if isinstance(item, ast.Call)]


def _call_name(call):
    node = call.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = [node.attr]
        current = node.value
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def _literal_task_calls(function):
    recognized = ("get_chat_completion_params", "get_completion_params", "completion_params")
    observed = []
    for call in _calls(function):
        if _call_name(call) in {"dependencies.llm_call", "llm.call"} and call.args:
            try:
                observed.append(ast.literal_eval(call.args[0]))
            except (ValueError, TypeError):
                pass
        if _call_name(call).endswith(recognized) and call.args:
            try:
                observed.append(ast.literal_eval(call.args[0]))
            except (ValueError, TypeError):
                continue
    return observed


def _request_task_ids(function, helper_functions=None):
    helper_functions = helper_functions or {}
    result = []
    boundaries = {
        "request_chat_completion_with_recovery",
        "_startup_provider_call",
    }
    for call in _calls(function):
        name = _call_name(call)
        if not (name.endswith("chat.completions.create") or name in boundaries or name == "llm.call"
                or name == "dependencies.llm_call"):
            continue
        if name in {"llm.call", "dependencies.llm_call"}:
            task = next((keyword.value for keyword in call.keywords if keyword.arg == "task"), None)
            task = task or (call.args[0] if call.args else None)
            if task is not None:
                try:
                    result.append(ast.literal_eval(task))
                except (ValueError, TypeError):
                    pass
        result.extend(_literal_task_calls(call))
        if name in helper_functions:
            result.extend(_literal_task_calls(helper_functions[name]))
    return result


class CoreChatInventoryContract(unittest.TestCase):
    def test_main_game_loop_terminal_callers_ready_and_wait_for_next_input(self):
        main_loop = _functions("main.py")["main_game_loop"]
        terminal_tries = [
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.Try)
            and any(_call_name(call) in {"get_ai_response", "validate_ai_response"} for call in _calls(node))
            and any(handler.type is not None and ast.unparse(handler.type) == "GameLLMTerminalError" for handler in node.handlers)
        ]
        self.assertEqual(len(terminal_tries), 2)
        for terminal_try in terminal_tries:
            handler = next(handler for handler in terminal_try.handlers if ast.unparse(handler.type) == "GameLLMTerminalError")
            handler_source = ast.unparse(handler)
            self.assertIn("status_ready()", handler_source)
            self.assertIn("break", handler_source)

        turn_loop = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.While) and any(_call_name(call) == "get_ai_response" for call in _calls(node))
        )
        terminal_guard = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.If) and ast.unparse(node.test) == "terminal_llm_failure"
        )
        self.assertEqual(ast.unparse(terminal_guard.body[0]), "continue")
        exhaustion_guard = next(
            node for node in ast.walk(main_loop)
            if isinstance(node, ast.If) and "not valid_response_received" in ast.unparse(node.test)
        )
        self.assertLess(
            terminal_guard.lineno,
            exhaustion_guard.lineno,
        )

    def test_exact_15_semantic_owners_and_task_mappings_are_observed_in_current_source(self):
        owners = {
            "main.py": {
                "generate_arrival_narration": "dm_main",
                "generate_seamless_transition_narration": "dm_main",
                "validate_ai_response": "dm_validation",
                "generate_module_summary": "summaries",
                "get_ai_response": "dm_main",
            },
            "core/combat/bootstrap.py": {
                "_run_resume_narrative": "combat_main",
                "_run_initial_scene_generation": "combat_main",
            },
            "core/combat/turn.py": {"run_combat_provider_retry_stage": "combat_main"},
            "core/combat/validation.py": {"validate_combat_response": "combat_validation"},
            "core/combat/combat_manager.py": {
                "summarize_dialogue": "combat_summary",
                "generate_combat_round_summary": "compression",
            },
            "core/combat/initiative_tracker_ai.py": {
                "generate_live_initiative_tracker": "combat_main"
            },
            "core/ai/action_handler.py": {
                "_ai_analyze_starting_location": "dm_validation",
                "process_action": "dm_main",
                "get_ai_npc_movement_decision": "updates",
            },
        }
        found = {}
        for path, expected in owners.items():
            functions = _functions(path)
            for function_name, task in expected.items():
                self.assertIn(function_name, functions, path)
                owner = functions[function_name]
                helpers = {"_startup_provider_call": functions.get("_startup_provider_call")}
                tasks = _request_task_ids(owner, helpers)
                self.assertTrue(tasks, f"no current task-bearing helper call: {path}::{function_name}")
                self.assertTrue(all(task_id == task for task_id in tasks), (path, function_name, tasks))
                found[(path, function_name)] = tasks[0]
        self.assertEqual(len(found), 15)
        self.assertEqual(set(found.values()), {
            "dm_main", "dm_validation", "summaries", "combat_main",
            "combat_validation", "combat_summary", "compression", "updates",
        })

    def test_current_primary_fallback_and_helper_variants_are_fresh(self):
        expected = {
            ("main.py", "generate_arrival_narration"): ("llm.call", 1),
            ("main.py", "generate_seamless_transition_narration"): ("llm.call", 1),
            ("main.py", "validate_ai_response"): ("llm.call", 1),
            ("main.py", "generate_module_summary"): ("llm.call", 1),
            ("main.py", "get_ai_response"): ("llm.call", 1),
            ("core/combat/turn.py", "run_combat_provider_retry_stage"): ("dependencies.llm_call", 3),
            ("core/combat/validation.py", "validate_combat_response"): ("dependencies.llm_call", 1),
            ("core/combat/combat_manager.py", "summarize_dialogue"): ("llm.call", 1),
            ("core/combat/combat_manager.py", "generate_combat_round_summary"): ("llm.call", 1),
            ("core/combat/initiative_tracker_ai.py", "generate_live_initiative_tracker"): ("llm.call", 1),
            ("core/ai/action_handler.py", "_ai_analyze_starting_location"): ("llm.call", 1),
            ("core/ai/action_handler.py", "process_action"): ("llm.call", 1),
            ("core/ai/action_handler.py", "get_ai_npc_movement_decision"): ("llm.call", 1),
        }
        for (path, name), (terminal, count) in expected.items():
            function = _functions(path)[name]
            calls = _calls(function)
            if terminal == "create":
                actual = sum(_call_name(call).endswith("chat.completions.create") for call in calls)
            elif terminal == "llm.call":
                actual = sum(_call_name(call) == "llm.call" for call in calls)
            elif terminal == "dependencies.llm_call":
                actual = sum(_call_name(call) == "dependencies.llm_call" for call in calls)
            else:
                actual = sum(_call_name(call) == terminal for call in calls)
            with self.subTest(owner=path + "::" + name):
                self.assertEqual(actual, count)

        bootstrap = _functions("core/combat/bootstrap.py")
        self.assertEqual(sum(_call_name(call).endswith("chat.completions.create")
                             for call in _calls(bootstrap["_startup_provider_call"])), 0)
        self.assertEqual(sum(_call_name(call) == "dependencies.llm_call"
                             for call in _calls(bootstrap["_startup_provider_call"])), 1)
        self.assertEqual(
            sum(_call_name(call) == "_startup_provider_call" for call in _calls(bootstrap["_run_resume_narrative"])),
            2,
        )
        initiative_calls = _calls(_functions("core/combat/initiative_tracker_ai.py")["generate_live_initiative_tracker"])
        self.assertEqual(sum(_call_name(call) == "OpenAI" for call in initiative_calls), 0)

        recovery = _functions("utils/provider_response_recovery.py")
        helper_calls = _calls(recovery["request_chat_completion_with_recovery"])
        self.assertTrue(any(_call_name(call).endswith("chat.completions.create") for call in helper_calls))

    def test_all_15_operations_use_facade_and_have_no_caller_owned_transport(self):
        owners = {
            "main.py": {
                "generate_arrival_narration": ("dm_main", 1),
                "generate_seamless_transition_narration": ("dm_main", 1),
                "validate_ai_response": ("dm_validation", 1),
                "generate_module_summary": ("summaries", 1),
                "get_ai_response": ("dm_main", 1),
            },
            "core/combat/bootstrap.py": {
                "_run_initial_scene_generation": ("combat_main", 1),
            },
            "core/combat/turn.py": {"run_combat_provider_retry_stage": ("combat_main", 3)},
            "core/combat/validation.py": {"validate_combat_response": ("combat_validation", 1)},
            "core/combat/combat_manager.py": {
                "summarize_dialogue": ("combat_summary", 1),
                "generate_combat_round_summary": ("compression", 1),
            },
            "core/combat/initiative_tracker_ai.py": {
                "generate_live_initiative_tracker": ("combat_main", 1),
            },
            "core/ai/action_handler.py": {
                "_ai_analyze_starting_location": ("dm_validation", 1),
                "process_action": ("dm_main", 1),
                "get_ai_npc_movement_decision": ("updates", 1),
            },
        }
        observed = set()
        for path, expected_owners in owners.items():
            functions = _functions(path)
            for function_name, (expected_task, expected_calls) in expected_owners.items():
                function = functions[function_name]
                calls = _calls(function)
                routed = [
                    call for call in calls
                    if _call_name(call) in {"llm.call", "dependencies.llm_call"}
                ]
                self.assertEqual(len(routed), expected_calls, path + "::" + function_name)
                for call in routed:
                    task_value = next(
                        (keyword.value for keyword in call.keywords if keyword.arg == "task"),
                        call.args[0] if call.args else None,
                    )
                    self.assertEqual(ast.literal_eval(task_value), expected_task)
                    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
                    self.assertIs(ast.literal_eval(keywords["json_output"]), False)
                    self.assertNotIn("timeout", keywords)
                    self.assertNotIn("model", keywords)
                forbidden = [
                    call for call in calls
                    if _call_name(call).endswith("chat.completions.create")
                    or _call_name(call) in {"OpenAI", "create_chat_client"}
                ]
                self.assertEqual(forbidden, [], path + "::" + function_name)
                observed.add((path, function_name))

        bootstrap = _functions("core/combat/bootstrap.py")
        resume = bootstrap["_run_resume_narrative"]
        self.assertEqual(
            sum(_call_name(call) == "_startup_provider_call" for call in _calls(resume)), 2
        )
        helper = bootstrap["_startup_provider_call"]
        helper_calls = _calls(helper)
        self.assertEqual(sum(_call_name(call) == "dependencies.llm_call" for call in helper_calls), 1)
        self.assertFalse(any(_call_name(call).endswith("chat.completions.create") for call in helper_calls))
        self.assertEqual(len(observed) + 1, 15)  # resume is the one operation routed by its shared helper.

        dormant = _functions("main.py")
        self.assertIn("generate_arrival_narration", dormant)
        self.assertIn("generate_seamless_transition_narration", dormant)

    def test_direct_sdk_leftovers_are_only_named_infrastructure_or_exclusions(self):
        # Action prediction now crosses the facade (G6); the only retained raw
        # transport owners are the router and the recovery helper.
        router = _functions("utils/llm_router.py")
        self.assertTrue(any(
            _call_name(call).endswith("chat.completions.create")
            for call in _calls(router["call"])
        ))
        recovery = _functions("utils/provider_response_recovery.py")
        self.assertTrue(any(
            _call_name(call).endswith("chat.completions.create")
            for call in _calls(recovery["request_chat_completion_with_recovery"])
        ))
        prediction = _functions("utils/action_predictor.py")
        self.assertFalse(any(
            _call_name(call).endswith("chat.completions.create")
            for function in prediction.values() for call in _calls(function)
        ))
        self.assertTrue(any(
            _call_name(call).endswith("llm.call")
            for call in _calls(prediction["predict_actions_required"])
        ))

    def test_combat_retry_family_variants_and_action_fallback_clients_are_distinct(self):
        turn = _functions("core/combat/turn.py")["run_combat_provider_retry_stage"]
        router_calls = [call for call in _calls(turn) if _call_name(call) == "dependencies.llm_call"]
        self.assertEqual(len(router_calls), 3)
        rendered = [(call.lineno, ast.unparse(call)) for call in router_calls]
        self.assertTrue(any("retry_tier=" in text and "high" in text for _, text in rendered))
        self.assertTrue(all("json_output=False" in text for _, text in rendered))
        self.assertFalse(any("timeout=" in text for _, text in rendered))
        self.assertFalse(any(_call_name(call).endswith("chat.completions.create") for call in _calls(turn)))

        movement = _functions("core/ai/action_handler.py")["get_ai_npc_movement_decision"]
        movement_calls = _calls(movement)
        routed = [call for call in movement_calls if _call_name(call) == "llm.call"]
        self.assertEqual(len(routed), 1)
        self.assertFalse(any(_call_name(call).endswith("chat.completions.create") for call in movement_calls))
        self.assertFalse(any(_call_name(call) == "create_chat_client" for call in movement_calls))
        keywords = {keyword.arg: keyword.value for keyword in routed[0].keywords}
        self.assertEqual(ast.literal_eval(keywords["task"]), "updates")
        self.assertIs(ast.literal_eval(keywords["json_output"]), False)
        self.assertEqual(ast.literal_eval(keywords["temperature"]), 0.7)
        self.assertNotIn("timeout", keywords)

        caller = _functions("core/ai/action_handler.py")["move_background_npc"]
        guarded = [node for node in ast.walk(caller) if isinstance(node, ast.Try) and any(
            isinstance(handler.type, ast.Name) and handler.type.id == "GameLLMTerminalError"
            for handler in node.handlers
        )]
        self.assertTrue(guarded, "NPC movement caller must propagate terminal router errors")
        handler_types = [ast.unparse(handler.type) if handler.type else None for handler in guarded[0].handlers]
        self.assertLess(handler_types.index("GameLLMTerminalError"), handler_types.index("Exception"))

    def test_main_router_family_branch_task_and_per_provider_bound_are_source_grounded(self):
        main = _functions("main.py")
        narrator = main["get_ai_response"]
        calls = _calls(narrator)
        router_calls = [call for call in calls if _call_name(call) == "llm.call"]
        self.assertEqual(len(router_calls), 1)
        self.assertEqual(sum(isinstance(node, ast.If) and ast.unparse(node.test) == "USE_GPT5_MODELS"
                             for node in ast.walk(narrator)), 2)
        keywords = {keyword.arg: keyword.value for keyword in router_calls[0].keywords}
        self.assertEqual(ast.literal_eval(keywords["task"]), "dm_main")
        self.assertIs(ast.literal_eval(keywords["json_output"]), False)
        self.assertEqual(ast.literal_eval(keywords["empty_retry_limit"]), 2)
        self.assertFalse(any(_call_name(call) == "request_chat_completion_with_recovery" for call in calls))
        self.assertFalse(any(_call_name(call) == "create_chat_client" for call in calls))

        recovery_tree = ast.parse((ROOT / "utils/provider_response_recovery.py").read_text(encoding="utf-8"))
        retry_limit = next(
            node.value
            for node in recovery_tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "EMPTY_RESPONSE_RETRY_LIMIT" for target in node.targets)
        )
        self.assertEqual(ast.literal_eval(retry_limit), 2)
        self.assertTrue(any(isinstance(node, ast.If) and "empty_retry_limit" in ast.unparse(node.test)
                            for node in ast.walk(_functions("utils/llm_router.py")["call"])))

    def test_a_process_tripwires_are_armed_before_owner_inspection(self):
        _TRIPWIRES.assert_untouched(self)

    def test_fatal_sdk_network_and_write_guards_fail_before_side_effect(self):
        import openai
        from scripts.core_chat_test_safety import TripwireFailure

        with self.assertRaisesRegex(TripwireFailure, "openai.OpenAI"):
            openai.OpenAI(api_key="fixture-only")
        with self.assertRaisesRegex(TripwireFailure, "socket.create_connection"):
            socket.create_connection(("127.0.0.1", 1))
        with self.assertRaisesRegex(TripwireFailure, "outside write"):
            with builtins.open(ROOT / "forbidden-core-chat-test-write", "w", encoding="utf-8"):
                pass

    def test_mutation_guards_cover_outside_paths_symlink_escape_and_dual_renames(self):
        from scripts.core_chat_test_safety import TripwireFailure

        outside = ROOT / "core-chat-tripwire-never-create"
        source_inside = ROOT / "tmp" / "core-chat-tripwire-rename-source"
        link = ROOT / "tmp" / "core-chat-tripwire-symlink"
        if link.is_symlink():
            os.unlink(link)
        for action in (
            lambda: os.mkdir(outside),
            lambda: os.makedirs(outside),
            lambda: os.remove(outside),
            lambda: os.unlink(outside),
            lambda: os.rmdir(outside),
            lambda: os.rename(source_inside, outside),
            lambda: os.rename(outside, source_inside),
            lambda: os.replace(source_inside, outside),
            lambda: os.replace(outside, source_inside),
            lambda: shutil.rmtree(outside),
            lambda: os.chmod(outside, 0o600),
            lambda: os.utime(outside, None),
            lambda: os.truncate(outside, 0),
            lambda: shutil.copyfile(outside, outside),
            lambda: shutil.move(source_inside, outside),
            lambda: os.link(outside, source_inside),
            lambda: os.link(source_inside, outside),
        ):
            with self.assertRaises(TripwireFailure):
                action()
        self.assertFalse(outside.exists())
        self.assertFalse(source_inside.exists())

        os.symlink(outside, link)
        try:
            self.assertTrue(link.is_symlink())
            with self.assertRaisesRegex(TripwireFailure, "outside mutation: os.mkdir"):
                os.mkdir(link / "escaped-child")
            self.assertFalse(outside.exists())
            self.assertFalse((outside / "escaped-child").exists())
        finally:
            os.unlink(link)

    def test_fd_relative_mutations_are_rejected_before_outside_side_effects(self):
        from scripts.core_chat_test_safety import TripwireFailure

        outside_dir = ROOT.parent
        outside_target = "core-chat-fd-tripwire-never-create"
        outside_second = "core-chat-fd-tripwire-never-create-2"
        descriptor = os.open(outside_dir, os.O_RDONLY)
        try:
            actions = (
                lambda: os.open(outside_target, os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=descriptor),
                lambda: os.mkdir(outside_target, dir_fd=descriptor),
                lambda: os.unlink(outside_target, dir_fd=descriptor),
                lambda: os.rename(outside_target, outside_second, src_dir_fd=descriptor, dst_dir_fd=descriptor),
                lambda: os.replace(outside_target, outside_second, src_dir_fd=descriptor, dst_dir_fd=descriptor),
                lambda: os.link(outside_target, outside_second, src_dir_fd=descriptor, dst_dir_fd=descriptor),
                lambda: os.symlink(outside_target, outside_second, dir_fd=descriptor),
            )
            for action in actions:
                with self.subTest(action=action), self.assertRaises(TripwireFailure):
                    action()
        finally:
            os.close(descriptor)
        self.assertFalse((outside_dir / outside_target).exists())
        self.assertFalse((outside_dir / outside_second).exists())

    def test_tracked_tmp_directory_fd_allows_scoped_mutations_and_cleanup(self):
        from scripts.core_chat_test_safety import TripwireFailure

        outside_dir = ROOT.parent
        outside_target = "core-chat-fd-tripwire-mixed-destination"
        outside_fd = os.open(outside_dir, os.O_RDONLY)
        try:
            with tempfile.TemporaryDirectory(prefix="core-chat-fd-owned-", dir=ROOT / "tmp") as directory:
                root = Path(directory)
                owned_fd = os.open(root, os.O_RDONLY)
                try:
                    descriptor = os.open(
                        "first.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600, dir_fd=owned_fd,
                    )
                    os.write(descriptor, b"inside tmp")
                    os.close(descriptor)
                    os.rename("first.txt", "second.txt", src_dir_fd=owned_fd,
                              dst_dir_fd=owned_fd)
                    self.assertEqual((root / "second.txt").read_bytes(), b"inside tmp")

                    with self.assertRaises(TripwireFailure):
                        os.rename("second.txt", outside_target, src_dir_fd=owned_fd,
                                  dst_dir_fd=outside_fd)
                    with self.assertRaises(TripwireFailure):
                        os.unlink("tmp/inside-looking-but-relative.txt", dir_fd=987654321)
                    with self.assertRaises(TripwireFailure):
                        os.open("tmp/inside-looking-but-relative.txt",
                                os.O_WRONLY | os.O_CREAT, 0o600, dir_fd=987654321)

                    os.unlink("second.txt", dir_fd=owned_fd)
                    nested = root / "nested"
                    nested.mkdir()
                    (nested / "payload.txt").write_bytes(b"cleanup")
                    os.symlink(outside_dir / "nonexistent-cleanup-target", nested / "escape")
                    self.assertTrue((nested / "escape").is_symlink())
                finally:
                    os.close(owned_fd)
            self.assertFalse((outside_dir / outside_target).exists())
            self.assertFalse(root.exists())
        finally:
            os.close(outside_fd)

    def test_tracked_fd_mutations_still_reject_outside_paths_and_link_escapes(self):
        from scripts.core_chat_test_safety import TripwireFailure

        outside_dir = ROOT.parent
        outside_target = "core-chat-fd-tripwire-outside-open"
        source_link = ROOT / "tmp" / "core-chat-fd-hardlink-source-link"
        destination = ROOT / "tmp" / "core-chat-fd-hardlink-destination"
        outside_fd = os.open(outside_dir, os.O_RDONLY)
        owned_fd = os.open(ROOT / "tmp", os.O_RDONLY)
        try:
            for action in (
                lambda: os.open(outside_target, os.O_WRONLY | os.O_CREAT, 0o600,
                                dir_fd=outside_fd),
                lambda: os.unlink(outside_target, dir_fd=outside_fd),
                lambda: os.unlink("tmp/inside-looking-relative-path.txt", dir_fd=outside_fd),
            ):
                with self.assertRaises(TripwireFailure):
                    action()

            if source_link.is_symlink():
                os.unlink(source_link)
            os.symlink(outside_dir / "nonexistent-hardlink-target", source_link)
            with self.assertRaisesRegex(TripwireFailure, "outside mutation: os.link"):
                os.link("core-chat-fd-hardlink-source-link", "core-chat-fd-hardlink-destination",
                        src_dir_fd=owned_fd, dst_dir_fd=owned_fd)
            self.assertFalse((outside_dir / outside_target).exists())
            self.assertFalse(destination.exists())
        finally:
            if source_link.is_symlink():
                os.unlink(source_link)
            os.close(owned_fd)
            os.close(outside_fd)

    def test_hardlink_source_symlink_cannot_escape_tmp(self):
        from scripts.core_chat_test_safety import TripwireFailure

        outside = ROOT.parent / "core-chat-hardlink-tripwire-never-create"
        source = ROOT / "tmp" / "core-chat-hardlink-source-link"
        destination = ROOT / "tmp" / "core-chat-hardlink-destination"
        if source.is_symlink():
            os.unlink(source)
        os.symlink(outside, source)
        try:
            with self.assertRaisesRegex(TripwireFailure, "outside mutation: os.link"):
                os.link(source, destination)
            self.assertFalse(outside.exists())
            self.assertFalse(destination.exists())
        finally:
            os.unlink(source)


if __name__ == "__main__":
    unittest.main()
