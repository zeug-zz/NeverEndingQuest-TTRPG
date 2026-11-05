# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root.
# This software is subject to the terms of the Fair Source License.

"""Explicit, reversible wrappers for the sandbox mapping-pilot prompt seams."""

from __future__ import annotations

import ast
import builtins
import copy
import contextvars
import hashlib
import json
import logging
import re
import sys
import threading
import uuid
from collections.abc import Callable, Mapping, Set as AbstractSet
from dataclasses import dataclass, is_dataclass, replace
from pathlib import Path
from typing import Any, Optional, Union


SUPPORTED_ARMS = ("A", "B", "D")
COMBAT_FIXTURE_ID = "combat_stage_tavern_zones"
SUPPORTED_FIXTURE_IDS = (
    "interior_tavern",
    "landscape_village",
    "transition_tower_approach",
    COMBAT_FIXTURE_ID,
)
_STATE_IN_DESCRIPTION = re.compile(r"(?:^|\s)State:\s*([^.;\n]+)", re.IGNORECASE)

PacketProvider = Callable[
    [str, tuple[Any, ...], Mapping[str, Any]], Optional[Union[str, bytes]]
]
ObserverErrorCallback = Callable[[str, str], Any]


class UnsupportedMappingPilotArmError(RuntimeError):
    """Raised when an arm is invoked on a surface outside its pilot contract."""


@dataclass(frozen=True)
class MovementHintObservation:
    """A safe, bounded observation for the later shadow-ledger callback."""

    status: str
    hint: Optional[dict[str, Any]] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class _Binding:
    owner: Any
    attribute: str
    original: Any
    wrapper: Any
    original_present: bool = True


@dataclass(frozen=True)
class _InputBoundary:
    source_path: Path
    source_hash: str
    main_loop_code: Any
    player_input_lines: frozenset[int]
    nested_input_lines: frozenset[int]

    def classify(self, frame: Any) -> Optional[str]:
        if frame.f_code is not self.main_loop_code:
            return None
        try:
            current_hash = hashlib.sha256(self.source_path.read_bytes()).hexdigest()
        except OSError:
            return "source_drift"
        if current_hash != self.source_hash:
            return "source_drift"
        if frame.f_lineno in self.player_input_lines:
            return "player"
        if frame.f_lineno in self.nested_input_lines:
            return "nested"
        return "unrecognized"


@dataclass(frozen=True)
class _TurnContext:
    context_id: str
    execution_scope: tuple[Optional[int], int, Optional[int]]
    turn_number: int
    turn_kind: str
    packets: Mapping[str, Optional[bytes]]
    use_counts: Mapping[str, int]


class _TurnPacketRecorder:
    """Freeze one packet per surface and logical turn, with per-use evidence."""

    def __init__(
        self,
        *,
        runtime_root: Optional[Union[str, Path]],
        lifecycle_id: Optional[str],
        error_callback: Optional[ObserverErrorCallback],
        record_writer: Optional[Callable[[Path, Mapping[str, Any]], Any]],
    ) -> None:
        self.lifecycle_id = lifecycle_id or uuid.uuid4().hex
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.lifecycle_id):
            raise ValueError("mapping-pilot lifecycle ID is invalid")
        self._error_callback = error_callback
        self._record_writer = record_writer or _write_turn_evidence_record
        self._context: contextvars.ContextVar[Optional[_TurnContext]] = (
            contextvars.ContextVar(
                "mapping_pilot_turn_context_%s" % self.lifecycle_id,
                default=None,
            )
        )
        self._lock = threading.RLock()
        self._sequence = 0
        self._turn_number = 0
        self._degraded = False
        self._sandbox_root: Optional[Path] = None
        self._evidence_directory: Optional[Path] = None
        if runtime_root is not None:
            self._evidence_directory = self._create_lifecycle_directory(runtime_root)

    @property
    def evidence_status(self) -> str:
        if self._degraded:
            return "degraded"
        if self._evidence_directory is None:
            return "disabled"
        return "recording"

    def mark_degraded(self, event: str, error_type: str) -> None:
        with self._lock:
            self._degraded = True
        if not error_type.isascii() or not error_type.isidentifier() or len(error_type) > 80:
            error_type = "Exception"
        if not event.isascii() or not re.fullmatch(r"[a-z_]{1,80}", event):
            event = "turn_evidence_failed"
        callback_error_type: Optional[str] = None
        if self._error_callback is not None:
            try:
                self._error_callback(event, error_type)
                return
            except Exception as exc:
                callback_error_type = _safe_exception_type(exc)
        message = (
            "category=mapping_pilot_turn_evidence status=degraded "
            "event=%s error_type=%s" % (event, error_type)
        )
        if callback_error_type is not None:
            message += " reporter_error_type=%s" % callback_error_type
        try:
            from utils.enhanced_logger import game_logger

            game_logger.error(message, category="mapping_pilot_turn_evidence")
        except Exception:
            try:
                logging.getLogger("mapping_pilot.turn_evidence").error(message)
            except Exception:
                pass

    def advance_turn(self) -> None:
        current = self._current_context()
        with self._lock:
            self._turn_number += 1
            turn_number = self._turn_number
        updated = _TurnContext(
            context_id=current.context_id,
            execution_scope=current.execution_scope,
            turn_number=turn_number,
            turn_kind="player_input",
            packets={},
            use_counts={},
        )
        self._context.set(updated)
        self._record_event(
            updated,
            {
                "event_type": "turn_boundary",
                "boundary": "accepted_player_input",
                "input_text_recorded": False,
            },
        )

    def packet_for_use(
        self,
        surface: str,
        provider: Optional[PacketProvider],
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> Optional[bytes]:
        current = self._current_context()
        if surface in current.packets:
            packet = current.packets[surface]
        else:
            packet = _get_packet_bytes(provider, surface, args, kwargs)
            packets = dict(current.packets)
            packets[surface] = packet
            current = replace(current, packets=packets)

        use_counts = dict(current.use_counts)
        use_index = use_counts.get(surface, 0) + 1
        use_counts[surface] = use_index
        current = replace(current, use_counts=use_counts)
        self._context.set(current)

        packet_hash = hashlib.sha256(packet).hexdigest() if packet is not None else None
        self._record_event(
            current,
            {
                "event_type": "packet_use",
                "surface": surface,
                "use_index": use_index,
                "packet_status": "present" if packet is not None else "absent",
                "packet_ascii": packet.decode("ascii") if packet is not None else None,
                "packet_sha256": packet_hash,
            },
        )
        return packet

    def _current_context(self) -> _TurnContext:
        scope = _execution_scope()
        current = self._context.get()
        if current is not None and current.execution_scope == scope:
            return current
        current = _TurnContext(
            context_id=uuid.uuid4().hex,
            execution_scope=scope,
            turn_number=0,
            turn_kind="startup",
            packets={},
            use_counts={},
        )
        self._context.set(current)
        self._record_event(
            current,
            {"event_type": "turn_boundary", "boundary": "startup", "input_text_recorded": False},
        )
        return current

    def _create_lifecycle_directory(self, runtime_root: Union[str, Path]) -> Optional[Path]:
        requested_root = Path(runtime_root)
        if requested_root.is_symlink():
            raise ValueError("mapping-pilot evidence root is unsafe")
        try:
            root = requested_root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("mapping-pilot evidence root is unavailable") from exc
        if not root.is_dir():
            raise ValueError("mapping-pilot evidence root is unavailable")
        self._sandbox_root = root
        mapping_root = root / "mapping_pilot"
        if mapping_root.is_symlink() or not mapping_root.is_dir():
            raise ValueError("mapping-pilot evidence directory is unsafe")
        evidence_root = mapping_root / "turn_packet_evidence"
        if evidence_root.is_symlink():
            raise ValueError("mapping-pilot evidence directory is unsafe")
        try:
            evidence_root.mkdir(exist_ok=True)
            evidence_root.resolve(strict=True).relative_to(root)
            lifecycle_root = evidence_root / self.lifecycle_id
            if lifecycle_root.is_symlink():
                raise ValueError("mapping-pilot lifecycle evidence path is unsafe")
            lifecycle_root.mkdir(exist_ok=False)
            lifecycle_root.resolve(strict=True).relative_to(root)
            return lifecycle_root
        except FileExistsError as exc:
            self.mark_degraded("lifecycle_id_collision", "FileExistsError")
            return None
        except (OSError, RuntimeError, ValueError) as exc:
            if isinstance(exc, ValueError) and "unsafe" in str(exc):
                raise
            self.mark_degraded("evidence_directory_unavailable", _safe_exception_type(exc))
            return None

    def _record_event(self, context: _TurnContext, fields: Mapping[str, Any]) -> None:
        if self._evidence_directory is None:
            return
        with self._lock:
            self._sequence += 1
            sequence = self._sequence
            turn_id = "%s:%s:%d" % (
                self.lifecycle_id,
                context.context_id,
                context.turn_number,
            )
            payload: dict[str, Any] = {
                "format_version": 1,
                "lifecycle_id": self.lifecycle_id,
                "sequence": sequence,
                "context_id": context.context_id,
                "turn_id": turn_id,
                "turn_number": context.turn_number,
                "turn_kind": context.turn_kind,
            }
            payload.update(fields)
            payload["evidence_status"] = "degraded" if self._degraded else "recorded"
            target = self._evidence_directory / ("record-%08d.json" % sequence)
            try:
                evidence_directory = self._evidence_directory
                if (
                    self._sandbox_root is None
                    or evidence_directory.is_symlink()
                    or evidence_directory.resolve(strict=True) != evidence_directory
                ):
                    raise ValueError("turn evidence directory changed")
                evidence_directory.resolve(strict=True).relative_to(
                    self._sandbox_root
                )
                if target.exists() or target.is_symlink():
                    raise FileExistsError("turn evidence record path already exists")
                result = self._record_writer(target, payload)
                if result is False:
                    self.mark_degraded(
                        "packet_hash_log_write_failed", "AtomicWriteFailed"
                    )
            except Exception as exc:
                self.mark_degraded("packet_hash_log_write_failed", _safe_exception_type(exc))


def _execution_scope() -> tuple[Optional[int], int, Optional[int]]:
    task_id: Optional[int] = None
    try:
        import asyncio

        task = asyncio.current_task()
        task_id = id(task) if task is not None else None
    except (ImportError, RuntimeError):
        pass
    greenlet_id: Optional[int] = None
    greenlet_module = sys.modules.get("greenlet")
    get_current = getattr(greenlet_module, "getcurrent", None)
    if callable(get_current):
        try:
            greenlet_id = id(get_current())
        except Exception:
            greenlet_id = None
    return task_id, threading.get_ident(), greenlet_id


def _write_turn_evidence_record(path: Path, payload: Mapping[str, Any]) -> bool:
    from utils.file_operations import safe_write_json

    return safe_write_json(
        str(path),
        dict(payload),
        create_backup=False,
        acquire_lock=True,
        json_kwargs={"ensure_ascii": True, "sort_keys": True},
    )


def _make_input_boundary(
    main_module: Any, runtime_root: Union[str, Path]
) -> _InputBoundary:
    requested_root = Path(runtime_root)
    if requested_root.is_symlink():
        raise ValueError("sandbox main input root is unsafe")
    root = requested_root.resolve(strict=True)
    source_value = getattr(main_module, "__file__", None)
    main_loop = getattr(main_module, "main_game_loop", None)
    code = getattr(main_loop, "__code__", None)
    if (
        not isinstance(source_value, (str, Path))
        or code is None
        or getattr(main_loop, "__globals__", None) is not vars(main_module)
    ):
        raise ValueError("sandbox main module has no verifiable input boundary")
    source_path = Path(source_value).resolve(strict=True)
    if source_path != root / "main.py":
        raise ValueError("sandbox main input source is outside the validated runtime")
    try:
        code_path = Path(code.co_filename).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("sandbox main input code source is unavailable") from exc
    if code_path != source_path:
        raise ValueError("sandbox main input code does not match its source file")
    try:
        source_bytes = source_path.read_bytes()
        source = source_bytes.decode("utf-8")
        tree = ast.parse(source, filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ValueError("sandbox main input source cannot be verified") from exc

    function_nodes = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "main_game_loop"
    ]
    if len(function_nodes) != 1:
        raise ValueError("sandbox main input loop source is ambiguous")
    function_node = function_nodes[0]
    if code.co_firstlineno != function_node.lineno:
        raise ValueError("sandbox main input code does not match its AST definition")
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    calls = list(ast.walk(function_node))
    input_calls = [
        node
        for node in calls
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "input"
    ]
    player_lines: set[int] = set()
    nested_lines: set[int] = set()
    player_loops: list[ast.While] = []
    for call in input_calls:
        parent = parents.get(call)
        target_names: set[str] = set()
        if isinstance(parent, ast.Assign):
            for target in parent.targets:
                target_names.update(_ast_store_names(target))
        elif isinstance(parent, ast.AnnAssign):
            target_names.update(_ast_store_names(parent.target))
        if target_names == {"user_input_text"}:
            player_lines.add(call.lineno)
            ancestor = parent
            while ancestor is not None and not isinstance(ancestor, ast.While):
                ancestor = parents.get(ancestor)
            if isinstance(ancestor, ast.While):
                player_loops.append(ancestor)
        elif target_names == {"level_up_input"}:
            nested_lines.add(call.lineno)
        else:
            raise ValueError("sandbox main input callsite is not allowlisted")
    if (
        len(input_calls) != 4
        or len(player_lines) != 2
        or len(nested_lines) != 2
        or len(player_loops) != 2
        or player_loops[0] is not player_loops[1]
    ):
        raise ValueError("sandbox main input callsites changed; boundary is unverified")
    return _InputBoundary(
        source_path=source_path,
        source_hash=hashlib.sha256(source_bytes).hexdigest(),
        main_loop_code=code,
        player_input_lines=frozenset(player_lines),
        nested_input_lines=frozenset(nested_lines),
    )


def _ast_store_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
    }


def _make_input_turn_wrapper(
    original: Callable[..., Any],
    *,
    boundary: _InputBoundary,
    recorder: _TurnPacketRecorder,
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            caller_frame = sys._getframe(1)
        except ValueError:
            caller_frame = None
        result = original(*args, **kwargs)
        if caller_frame is None:
            return result
        try:
            classification = boundary.classify(caller_frame)
            if classification == "player":
                if isinstance(result, str) and result.strip():
                    recorder.advance_turn()
            elif classification == "source_drift":
                recorder.mark_degraded("turn_boundary_source_drift", "SourceDrift")
            elif classification == "unrecognized":
                recorder.mark_degraded("turn_boundary_unrecognized", "SourceDrift")
        except Exception as exc:
            try:
                recorder.mark_degraded(
                    "turn_boundary_observation_failed", _safe_exception_type(exc)
                )
            except Exception:
                pass
        return result

    return wrapped


class AdapterInstallation:
    """Own temporary module-global replacements and restore them explicitly."""

    def __init__(
        self,
        arm: str,
        bindings: tuple[_Binding, ...] = (),
        turn_recorder: Optional[_TurnPacketRecorder] = None,
    ) -> None:
        self.arm = arm
        self._bindings = bindings
        self._turn_recorder = turn_recorder
        self._installed = True

    @property
    def installed_attributes(self) -> tuple[str, ...]:
        return tuple(binding.attribute for binding in self._bindings)

    @property
    def lifecycle_id(self) -> Optional[str]:
        return self._turn_recorder.lifecycle_id if self._turn_recorder else None

    @property
    def evidence_status(self) -> str:
        if self._turn_recorder is None:
            return "disabled"
        return self._turn_recorder.evidence_status

    def uninstall(self) -> None:
        if not self._installed:
            return
        for binding in reversed(self._bindings):
            if getattr(binding.owner, binding.attribute, None) is binding.wrapper:
                if binding.original_present:
                    setattr(binding.owner, binding.attribute, binding.original)
                else:
                    delattr(binding.owner, binding.attribute)
        self._installed = False

    def __enter__(self) -> "AdapterInstallation":
        return self

    def __exit__(self, _exc_type: Any, _exc: Any, _traceback: Any) -> None:
        self.uninstall()


def install_adapter(
    *,
    arm: str,
    main_module: Any,
    combat_prompts_module: Any,
    packet_provider: Optional[PacketProvider] = None,
    combat_manager_module: Any = None,
    movement_hint_observer: Optional[Callable[[MovementHintObservation], Any]] = None,
    observer_error_callback: Optional[ObserverErrorCallback] = None,
    fixture_id: Optional[str] = None,
    runtime_root: Optional[Union[str, Path]] = None,
    lifecycle_id: Optional[str] = None,
    turn_record_writer: Optional[Callable[[Path, Mapping[str, Any]], Any]] = None,
    turn_evidence_error_callback: Optional[ObserverErrorCallback] = None,
) -> AdapterInstallation:
    """Patch only the already-imported sandbox bindings and return cleanup.

    B/D installations freeze packet bytes per logical turn and surface. When a
    validated runtime root is supplied, the main module's user-input binding is
    wrapped locally to advance turn identity without changing builtins.input.
    """
    if arm not in SUPPORTED_ARMS:
        raise ValueError("mapping-pilot arm must be A, B, or D")
    if fixture_id is not None and fixture_id not in SUPPORTED_FIXTURE_IDS:
        raise ValueError("unsupported mapping-pilot fixture")
    if arm == "B" and fixture_id == COMBAT_FIXTURE_ID:
        raise UnsupportedMappingPilotArmError(
            "mapping-pilot arm B is not registered for combat"
        )

    # Arm A is deliberately a no-op: do not even replace a binding with a
    # delegating wrapper, so function identity and byte output stay untouched.
    if arm == "A":
        return AdapterInstallation(arm)

    bindings: list[_Binding] = []
    turn_recorder = _TurnPacketRecorder(
        runtime_root=runtime_root,
        lifecycle_id=lifecycle_id,
        error_callback=turn_evidence_error_callback,
        record_writer=turn_record_writer,
    )
    input_boundary = (
        _make_input_boundary(main_module, runtime_root)
        if runtime_root is not None
        else None
    )

    def patch(
        owner: Any,
        attribute: str,
        wrapper_factory: Callable[[Any], Any],
        *,
        fallback_original: Any = None,
    ) -> None:
        original_present = hasattr(owner, attribute)
        original = (
            getattr(owner, attribute) if original_present else fallback_original
        )
        if original is None:
            raise ValueError("mapping-pilot adapter binding is unavailable")
        wrapper = wrapper_factory(original)
        setattr(owner, attribute, wrapper)
        bindings.append(
            _Binding(owner, attribute, original, wrapper, original_present)
        )

    try:
        patch(
            main_module,
            "build_enhanced_dm_note",
            lambda original: _make_dm_note_wrapper(
                original,
                arm=arm,
                packet_provider=packet_provider,
                turn_recorder=turn_recorder,
            ),
        )

        if input_boundary is not None:
            patch(
                main_module,
                "input",
                lambda original: _make_input_turn_wrapper(
                    original,
                    boundary=input_boundary,
                    recorder=turn_recorder,
                ),
                fallback_original=builtins.input,
            )

        if arm == "D":
            result_type = getattr(combat_prompts_module, "CombatPromptResult", None)
            if result_type is None:
                raise ValueError("combat prompt module has no CombatPromptResult type")
            patch(
                combat_prompts_module,
                "assemble_combat_prompt",
                lambda original: _make_combat_prompt_wrapper(
                    original,
                    result_type=result_type,
                    packet_provider=packet_provider,
                    turn_recorder=turn_recorder,
                ),
            )
            if combat_manager_module is not None and movement_hint_observer is not None:
                patch(
                    combat_manager_module,
                    "validate_combat_response",
                    lambda original: _make_validation_observer(
                        original,
                        movement_hint_observer,
                        observer_error_callback,
                    ),
                )
        else:
            # B is an exploration-only arm. Guard any accidental combat use
            # rather than silently treating it as an A or D combat prompt.
            patch(
                combat_prompts_module,
                "assemble_combat_prompt",
                lambda original: _make_unsupported_combat_wrapper(original),
            )
    except Exception:
        for binding in reversed(bindings):
            if getattr(binding.owner, binding.attribute, None) is binding.wrapper:
                if binding.original_present:
                    setattr(binding.owner, binding.attribute, binding.original)
                else:
                    delattr(binding.owner, binding.attribute)
        raise

    return AdapterInstallation(arm, tuple(bindings), turn_recorder)


def _make_dm_note_wrapper(
    original: Callable[..., Any],
    *,
    arm: str,
    packet_provider: Optional[PacketProvider],
    turn_recorder: _TurnPacketRecorder,
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if not isinstance(result, str):
            return result
        packet_bytes = turn_recorder.packet_for_use(
            "exploration", packet_provider, args, kwargs
        )
        packet = packet_bytes.decode("ascii") if packet_bytes is not None else None
        if packet is None:
            return result
        return _replace_spatial_slot(result, packet, arm)

    return wrapped


def _make_combat_prompt_wrapper(
    original: Callable[..., Any],
    *,
    result_type: type,
    packet_provider: Optional[PacketProvider],
    turn_recorder: _TurnPacketRecorder,
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = original(*args, **kwargs)
        if not isinstance(result, result_type) or not is_dataclass(result):
            return result
        prompt = getattr(result, "user_prompt", None)
        if not isinstance(prompt, str):
            return result
        packet_bytes = turn_recorder.packet_for_use(
            "combat", packet_provider, args, kwargs
        )
        packet = packet_bytes.decode("ascii") if packet_bytes is not None else None
        if packet is None:
            return result
        updated_prompt = (
            prompt
            + "\n\n--- MAPPING PILOT COMBAT ZONE (D) ---\n"
            + packet
            + "\n\n"
            + _MOVEMENT_HINT_INSTRUCTION
        )
        return replace(result, user_prompt=updated_prompt)

    return wrapped


_MOVEMENT_HINT_INSTRUCTION = (
    "Optional D-arm combat observation only: when the acting creature moves, "
    "include a top-level movement_hint object with from, to, disengage, and "
    "cover_sought fields. This is observational metadata, not an action; do not "
    "add, remove, or change any entry in actions."
)


def _make_unsupported_combat_wrapper(original: Callable[..., Any]) -> Callable[..., Any]:
    def wrapped(*_args: Any, **_kwargs: Any) -> Any:
        raise UnsupportedMappingPilotArmError(
            "mapping-pilot arm B does not support combat prompts"
        )

    return wrapped


def _make_validation_observer(
    original: Callable[..., Any],
    observer: Callable[[MovementHintObservation], Any],
    error_callback: Optional[ObserverErrorCallback] = None,
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        response = args[0] if args else kwargs.get("response")
        try:
            observation = observe_movement_hint(response)
            observer(observation)
        except Exception as exc:
            # Keep validation authoritative, but surface loss of the advisory
            # observation without logging response content or exception text.
            _report_observer_failure(exc, error_callback)
        return original(*args, **kwargs)

    return wrapped


def _report_observer_failure(
    error: Exception,
    error_callback: Optional[ObserverErrorCallback],
) -> None:
    event = "movement_hint_observer_failed"
    error_type = _safe_exception_type(error)
    reporter_error_type: Optional[str] = None
    if error_callback is not None:
        try:
            error_callback(event, error_type)
            return
        except Exception as exc:
            reporter_error_type = _safe_exception_type(exc)

    message = (
        "category=mapping_pilot_observer status=degraded event=%s error_type=%s"
        % (event, error_type)
    )
    if reporter_error_type is not None:
        message += " reporter_error_type=%s" % reporter_error_type
    try:
        from utils.enhanced_logger import game_logger

        game_logger.error(message, category="mapping_pilot_observer")
    except Exception:
        logging.getLogger("mapping_pilot.observer").error(message)


def _safe_exception_type(error: Exception) -> str:
    name = type(error).__name__
    if not name.isascii() or not name.isidentifier() or len(name) > 80:
        return "Exception"
    return name


def observe_movement_hint(response: Any) -> MovementHintObservation:
    """Inspect only top-level movement_hint; never alter the original response."""
    parsed: Any = response
    if isinstance(parsed, bytes):
        try:
            parsed = parsed.decode("utf-8")
        except UnicodeDecodeError:
            return MovementHintObservation("invalid", reason="response_not_json")
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (json.JSONDecodeError, ValueError):
            return MovementHintObservation("invalid", reason="response_not_json")
    if not isinstance(parsed, Mapping):
        return MovementHintObservation("invalid", reason="response_not_object")
    if "movement_hint" not in parsed:
        return MovementHintObservation("missing")

    hint = parsed.get("movement_hint")
    if not isinstance(hint, Mapping):
        return MovementHintObservation("invalid", reason="hint_not_object")
    from_zone = hint.get("from")
    to_zone = hint.get("to")
    disengage = hint.get("disengage")
    cover_sought = hint.get("cover_sought")
    if (
        not isinstance(from_zone, str)
        or not from_zone.strip()
        or from_zone != from_zone.strip()
        or not isinstance(to_zone, str)
        or not to_zone.strip()
        or to_zone != to_zone.strip()
        or not isinstance(disengage, bool)
        or (
            cover_sought is not None
            and (
                not isinstance(cover_sought, str)
                or not cover_sought.strip()
                or cover_sought != cover_sought.strip()
            )
        )
    ):
        return MovementHintObservation("invalid", reason="hint_fields_invalid")

    return MovementHintObservation(
        "valid",
        hint={
            "from": from_zone,
            "to": to_zone,
            "disengage": disengage,
            "cover_sought": cover_sought,
        },
    )


def _get_packet_bytes(
    provider: Optional[PacketProvider],
    surface: str,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Optional[bytes]:
    if provider is None:
        return None
    packet = provider(surface, args, kwargs)
    if packet is None:
        return None
    if isinstance(packet, bytes):
        try:
            packet.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError("mapping-pilot packet must be ASCII") from exc
        return packet or None
    if isinstance(packet, str):
        try:
            encoded = packet.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError("mapping-pilot packet must be ASCII") from exc
        return encoded or None
    raise TypeError("mapping-pilot packet provider must return text or bytes")


_SPATIAL_MARKERS = (
    "Adjacent locations:",
    "Adjacent locations in this area:",
)


def _replace_spatial_slot(text: str, packet: str, arm: str) -> str:
    matches: list[tuple[int, str]] = []
    for marker in _SPATIAL_MARKERS:
        start = 0
        while True:
            marker_index = text.find(marker, start)
            if marker_index < 0:
                break
            matches.append((marker_index, marker))
            start = marker_index + len(marker)
    matches.sort(key=lambda item: item[0])
    if len(matches) > 1:
        raise ValueError("DM note contains ambiguous spatial context slots")
    heading = "--- EXITS / COMPACT ORIENTATION (MAPPING PILOT %s) ---" % arm
    if not matches:
        prefix = text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        return prefix + heading + "\n" + packet
    marker_index, _marker = matches[0]
    line_end = text.find("\n", marker_index)
    if line_end < 0:
        line_end = len(text)
    prefix = text[:marker_index]
    if prefix and not prefix.endswith("\n"):
        prefix = prefix.rstrip() + "\n"
    return prefix + heading + "\n" + packet + text[line_end:]


class SandboxPacketProvider:
    """Build a fresh packet from canonical sandbox state and frozen fixture data.

    ``fixture_payloads`` maps fixture IDs to the ``source_truth`` object from
    each seeder-created expected-properties file. ``runtime_to_source`` is the
    inverse of the seeder-written ``location_id_map.json``. The resolver is an
    explicit injection point for party-known/perceived facts; when omitted, the
    provider uses only fixture-marked perceptible facts and known destinations.
    """

    def __init__(
        self,
        *,
        runtime_root: Union[str, Path],
        metadata: Mapping[str, Any],
        fixture_payloads: Mapping[str, Mapping[str, Any]],
        runtime_to_source: Mapping[str, str],
        explicit_known_ids: Optional[AbstractSet[str]] = None,
        explicit_perceived_ids: Optional[AbstractSet[str]] = None,
        knowledge_resolver: Optional[Callable[..., Mapping[str, Any]]] = None,
    ) -> None:
        self.runtime_root = Path(runtime_root).resolve(strict=True)
        self.metadata = copy.deepcopy(dict(metadata))
        self.fixture_payloads = {
            key: copy.deepcopy(dict(value)) for key, value in fixture_payloads.items()
        }
        self.runtime_to_source = dict(runtime_to_source)
        self.explicit_known_ids = _normalize_optional_ids(explicit_known_ids)
        self.explicit_perceived_ids = _normalize_optional_ids(explicit_perceived_ids)
        if (self.explicit_known_ids is None) != (self.explicit_perceived_ids is None):
            raise ValueError("known and perceived ID overrides must be supplied together")
        self.knowledge_resolver = knowledge_resolver

    def __call__(
        self,
        surface: str,
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
    ) -> Optional[str]:
        if surface not in ("exploration", "combat"):
            raise ValueError("unsupported mapping-pilot prompt surface")
        tracker = self._tracker_for_use(surface, args, kwargs)
        world = tracker.get("worldConditions")
        if not isinstance(world, Mapping):
            raise ValueError("mapping-pilot party location is unavailable")
        runtime_location_id = world.get("currentLocationId")
        source_location_id = self.runtime_to_source.get(runtime_location_id)
        if source_location_id is None:
            raise ValueError("mapping-pilot current location is outside fixture coverage")
        active_actor_id = tracker.get("active_character")
        party_members = tracker.get("partyMembers")
        if (
            not isinstance(active_actor_id, str)
            or not active_actor_id
            or not isinstance(party_members, list)
            or active_actor_id not in party_members
        ):
            raise ValueError("mapping-pilot active actor is unavailable")

        fixture_id, layout = self._layout_for_location(surface, source_location_id)
        if layout is None:
            return None
        layout = self._overlay_canonical_feature_states(
            layout, str(runtime_location_id)
        )
        knowledge = self._resolve_knowledge(
            fixture_id,
            layout,
            tracker,
            source_location_id,
            active_actor_id,
        )

        from scripts.mapping_pilot.knowledge import filter_layout_for_viewpoint
        from scripts.mapping_pilot.projections import render_packet

        projection = filter_layout_for_viewpoint(
            layout,
            current_location_id=source_location_id,
            active_actor_id=active_actor_id,
            party_known_ids=knowledge["party_known_ids"],
            perceived_ids=knowledge["perceived_ids"],
            recent_movement=knowledge.get("recent_movement"),
        )
        location_names = self._known_location_names(
            knowledge["party_known_ids"]
        )
        projection["known_location_names"] = location_names
        recent_movement = projection.get("recent_movement")
        if isinstance(recent_movement, dict):
            from_id = recent_movement.get("from_location_id")
            from_name = location_names.get(from_id)
            if isinstance(from_name, str):
                recent_movement["from_name"] = from_name

        arm = str(self.metadata.get("arm", ""))
        if surface == "combat":
            if arm != "D":
                raise UnsupportedMappingPilotArmError(
                    "mapping-pilot arm B does not support combat prompts"
                )
            if not isinstance(layout.get("zones"), list):
                return None
            return render_packet(projection, "D")
        if arm not in ("B", "D"):
            return None
        return render_packet(projection, arm)

    def _tracker_for_use(
        self, surface: str, args: tuple[Any, ...], kwargs: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if surface == "exploration":
            tracker = kwargs.get("party_tracker_data")
            if tracker is None and len(args) > 3:
                tracker = args[3]
            if isinstance(tracker, Mapping):
                return tracker
        tracker_path = _safe_sandbox_path(self.runtime_root, "party_tracker.json")
        try:
            payload = json.loads(tracker_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("mapping-pilot party tracker is unavailable") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("mapping-pilot party tracker is invalid")
        return payload

    def _layout_for_location(
        self, surface: str, source_location_id: str
    ) -> tuple[str, Optional[dict[str, Any]]]:
        candidates: list[tuple[str, Mapping[str, Any]]] = []
        for fixture_id, fixture in self.fixture_payloads.items():
            if fixture.get("fixture_id") != fixture_id:
                continue
            location_ids = fixture.get("location_ids")
            if not isinstance(location_ids, list) or source_location_id not in location_ids:
                continue
            is_combat = isinstance(fixture.get("zones"), list)
            if surface == "combat" and is_combat:
                candidates.append((fixture_id, fixture))
            elif surface == "exploration" and not is_combat:
                locations = fixture.get("locations")
                if isinstance(locations, list) and any(
                    isinstance(row, Mapping)
                    and row.get("location_id") == source_location_id
                    for row in locations
                ):
                    candidates.append((fixture_id, fixture))
        if not candidates:
            return "", None
        if len(candidates) != 1:
            raise ValueError("mapping-pilot location has ambiguous frozen fixture coverage")
        from scripts.mapping_pilot.layout import normalize_fixture_layout

        return candidates[0][0], normalize_fixture_layout(
            copy.deepcopy(dict(candidates[0][1]))
        )

    def _resolve_knowledge(
        self,
        fixture_id: str,
        layout: Mapping[str, Any],
        tracker: Mapping[str, Any],
        current_location_id: str,
        active_actor_id: str,
    ) -> dict[str, Any]:
        if self.knowledge_resolver is not None:
            supplied = self.knowledge_resolver(
                fixture_id=fixture_id,
                layout=layout,
                tracker=tracker,
                current_location_id=current_location_id,
                active_actor_id=active_actor_id,
            )
            if not isinstance(supplied, Mapping):
                raise ValueError("mapping-pilot knowledge resolver must return an object")
            known = _normalize_required_ids(supplied.get("party_known_ids"))
            perceived = _normalize_required_ids(supplied.get("perceived_ids"))
            recent = supplied.get("recent_movement")
            if recent is not None and not isinstance(recent, Mapping):
                raise ValueError("mapping-pilot recent movement must be an object")
        elif self.explicit_known_ids is not None:
            known = frozenset(set(self.explicit_known_ids) | {current_location_id})
            perceived = self.explicit_perceived_ids or frozenset()
            recent = None
        else:
            known, perceived = _fixture_knowledge(layout, current_location_id)
            recent = None
        return {
            "party_known_ids": known,
            "perceived_ids": perceived,
            "recent_movement": recent,
        }

    def _known_location_names(self, known_ids: AbstractSet[str]) -> dict[str, str]:
        names: dict[str, str] = {}
        for fixture in self.fixture_payloads.values():
            locations = fixture.get("locations")
            if not isinstance(locations, list):
                continue
            for location in locations:
                if not isinstance(location, Mapping):
                    continue
                location_id = location.get("location_id")
                name = location.get("name")
                if (
                    isinstance(location_id, str)
                    and location_id in known_ids
                    and isinstance(name, str)
                    and name.isascii()
                ):
                    names[location_id] = name
        return names

    def _overlay_canonical_feature_states(
        self, layout: dict[str, Any], runtime_location_id: str
    ) -> dict[str, Any]:
        canonical_features = _read_canonical_features(
            self.runtime_root, self.metadata, runtime_location_id
        )
        if not canonical_features:
            return layout
        feature_collections = (
            ("features", "locations")
            if layout.get("layout_type") != "combat_zones"
            else ("feature_anchors", "top")
        )
        rows_key, scope = feature_collections
        if scope == "locations":
            locations = layout.get("locations")
            if not isinstance(locations, list):
                return layout
            rows = next(
                (
                    location.get(rows_key)
                    for location in locations
                    if isinstance(location, Mapping)
                    and self.runtime_to_source.get(runtime_location_id)
                    == location.get("location_id")
                ),
                None,
            )
        else:
            rows = layout.get(rows_key)
        if not isinstance(rows, list):
            return layout
        by_id, by_name = canonical_features
        for feature in rows:
            if not isinstance(feature, dict):
                continue
            state = by_id.get(feature.get("feature_id"))
            if state is None:
                name = feature.get("name")
                state = by_name.get(_normalized_name(name))
            if isinstance(state, str):
                feature["state"] = state
        return layout


def _fixture_knowledge(
    layout: Mapping[str, Any], current_location_id: str
) -> tuple[frozenset[str], frozenset[str]]:
    perceived: set[str] = set()
    known: set[str] = {current_location_id}
    if layout.get("layout_type") == "combat_zones":
        feature_rows = layout.get("feature_anchors", [])
        npc_rows = layout.get("npc_anchors", [])
        for collection in (feature_rows, npc_rows):
            if isinstance(collection, list):
                for row in collection:
                    if isinstance(row, Mapping):
                        identifier = row.get("feature_id", row.get("npc_id"))
                        if isinstance(identifier, str) and row.get("perceivable", True) is not False:
                            perceived.add(identifier)
        zone_ids = {
            row.get("zone_id")
            for row in layout.get("zones", [])
            if isinstance(row, Mapping) and isinstance(row.get("zone_id"), str)
        }
        for row in layout.get("occupant_roles", []):
            if (
                isinstance(row, Mapping)
                and row.get("initial_zone_id") in zone_ids
                and isinstance(row.get("actor_id"), str)
            ):
                perceived.add(row["actor_id"])
        exit_rows = layout.get("exits", [])
    else:
        locations = layout.get("locations", [])
        current = next(
            (
                row
                for row in locations
                if isinstance(row, Mapping)
                and row.get("location_id") == current_location_id
            ),
            {},
        )
        for feature in current.get("features", []):
            if (
                isinstance(feature, Mapping)
                and feature.get("perceivable", True) is not False
                and isinstance(feature.get("feature_id"), str)
            ):
                perceived.add(feature["feature_id"])
        for npc in current.get("npc_anchors", []):
            if (
                isinstance(npc, Mapping)
                and npc.get("perceivable", True) is not False
                and isinstance(npc.get("npc_id"), str)
            ):
                perceived.add(npc["npc_id"])
        exit_rows = current.get("exits", [])
    known.update(perceived)
    if isinstance(exit_rows, list):
        for exit_row in exit_rows:
            if (
                isinstance(exit_row, Mapping)
                and exit_row.get("destination_knowledge") == "known"
                and isinstance(exit_row.get("known_destination_location_id"), str)
            ):
                known.add(exit_row["known_destination_location_id"])
    return frozenset(known), frozenset(perceived)


def _read_canonical_features(
    runtime_root: Path,
    metadata: Mapping[str, Any],
    runtime_location_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    mapping = metadata.get("mapping")
    module_name = mapping.get("module") if isinstance(mapping, Mapping) else None
    if not isinstance(module_name, str) or not module_name or "/" in module_name or "\\" in module_name:
        return {}, {}
    module_root = _safe_sandbox_path(runtime_root, "modules/" + module_name)
    areas_root = module_root / "areas"
    if not areas_root.is_dir() or areas_root.is_symlink():
        return {}, {}
    for area_path in sorted(areas_root.glob("*.json")):
        if area_path.name.endswith("_BU.json"):
            continue
        try:
            resolved = area_path.resolve(strict=True)
            resolved.relative_to(runtime_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("mapping-pilot canonical area path is unsafe") from exc
        if area_path.is_symlink():
            raise ValueError("mapping-pilot canonical area path is unsafe")
        try:
            area = json.loads(area_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("mapping-pilot canonical area data is invalid") from exc
        if not isinstance(area, Mapping):
            continue
        for location in area.get("locations", []):
            if not isinstance(location, Mapping) or location.get("locationId") != runtime_location_id:
                continue
            by_id: dict[str, str] = {}
            by_name: dict[str, str] = {}
            for feature in location.get("features", []):
                if not isinstance(feature, Mapping):
                    continue
                state = feature.get("state")
                description = feature.get("description")
                if not isinstance(state, str) and isinstance(description, str):
                    match = _STATE_IN_DESCRIPTION.search(description)
                    state = match.group(1).strip() if match else None
                if not isinstance(state, str) or not state.strip() or not state.isascii():
                    continue
                feature_id = feature.get("feature_id") or feature.get("featureId")
                name = feature.get("name")
                if isinstance(feature_id, str):
                    by_id[feature_id] = state.strip()
                if isinstance(name, str):
                    by_name[_normalized_name(name)] = state.strip()
            return by_id, by_name
    return {}, {}


def _normalized_name(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.casefold().split())


def _normalize_optional_ids(values: Optional[AbstractSet[str]]) -> Optional[frozenset[str]]:
    if values is None:
        return None
    return _normalize_required_ids(values)


def _normalize_required_ids(values: Any) -> frozenset[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, AbstractSet):
        raise ValueError("mapping-pilot knowledge IDs must be an explicit set")
    normalized: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("mapping-pilot knowledge IDs must be non-empty strings")
        normalized.add(value)
    return frozenset(normalized)


def _safe_sandbox_path(runtime_root: Path, relative_path: str) -> Path:
    raw = Path(relative_path)
    if raw.is_absolute() or ".." in raw.parts or "\\" in relative_path:
        raise ValueError("mapping-pilot sandbox path is unsafe")
    candidate = runtime_root.joinpath(*raw.parts)
    current = runtime_root
    for part in raw.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("mapping-pilot sandbox path is unsafe")
    try:
        candidate.resolve(strict=True).relative_to(runtime_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("mapping-pilot sandbox path is unsafe") from exc
    return candidate
