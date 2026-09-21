## Context

Adaptation execution crosses several output layers: Python `print()` and logging, subprocess output from monster generation, root/application handlers, WebOutputCapture, Socket.IO progress payloads, and bounded diagnostic persistence. Current code has unconditional lock prints in `utils/file_operations.py`, verbose/full concept or response logging in generators, root DEBUG configuration and handlers, and provider child loggers that can be created after the first safety call. A report-level boolean is therefore insufficient: the boundary must protect every adaptation emission surface.

The linked finalization change sends bounded failure packets and revision context through this pipeline. The output boundary must ensure that those packets remain bounded without leaking the raw source or provider payload used to construct them.

## Goals / Non-Goals

**Goals:**

- Provide one adaptation-scoped output context that can be entered by upload/text adaptation workers and reused by revision/finalization stages.
- Permit bounded phase/status/count/failure-code events while suppressing raw source, prompt, response, credentials, paths, and request data.
- Make logger and handler safety robust to root-handler creation and lazy provider children after client construction.
- Keep diagnostic tails useful, deterministic, ASCII-only, and safe.
- Preserve legacy diagnostics outside adaptation and provider request semantics.

**Non-Goals:**

- Do not remove all logging from the repository or globally silence legacy CLI workflows.
- Do not alter provider request bodies, models, timeout/retry behavior, or fallback decisions.
- Do not persist raw stdout/stderr for debugging, even if it is bounded.
- Do not use the output boundary to hide hard failures or replace meaningful stage/failure codes.
- Do not add a new external logging dependency or a new GUI mode.

## Decisions

### 1. Adaptation scope is explicit and fail-safe

Add a project-local adaptation output guard/context with a small safe-event API. The guard tracks an active adaptation scope and routes stdout/stderr, logger records, progress callbacks, and diagnostic persistence through bounded sanitization. If setup or redaction fails, it fails closed for unsafe content while allowing a bounded internal failure code; it must not disable hard failure reporting.

Safe progress events contain only a fixed event type, stage, status, bounded code, count/percentage fields, attempt/revision identifiers, and short ASCII-safe message text. They cannot contain source excerpts, prompt blocks, provider response text, request/response bodies, credentials, absolute paths, lock paths, or arbitrary exception strings.

### 2. Capture before emit, not after GUI formatting

The adaptation boundary must sanitize before writing to original stdout/stderr, logging handlers, WebOutputCapture, Socket.IO payloads, or persisted tails. Provider-shaped records and known sensitive markers are suppressed or replaced with a stable safe diagnostic. GUI/progress consumers receive the same bounded event schema rather than raw captured lines.

### 3. Generator verbosity is scoped, not globally deleted

During adaptation, direct prints and verbose concept/response logging in ModuleBuilder, ModuleGenerator, AreaGenerator, and monster-builder subprocesses are removed or routed to the safe-event logger. Legacy non-adaptation paths retain their meaningful diagnostics where no sensitive source/provider data is involved. Raw AI responses and full prompts are never emitted in either adaptation stdout or persisted tails.

`utils/file_operations.py` lock operations must not print absolute lock paths. They may emit a categorized debug counter or a bounded event when adaptation scope is active. Root `logging.basicConfig` side effects must not install a bypass handler that can receive unsanitized provider records.

### 4. Provider safety covers late loggers and handlers

Reuse the existing provider-log safety policy before and after client construction, and extend the adaptation boundary so newly created `openai.*`, `httpx.*`, and `httpcore.*` children and root/application handlers cannot emit unsanitized DEBUG records. Handler filters/levels are applied at the emission boundary or re-applied on handler/logger changes without mutating request arguments. Late logger tests must prove that prompts, source, headers, authorization, response bodies, and request IDs remain absent.

### 5. Diagnostic persistence is a redacted projection

Failure packets and attempt reports receive safe codes, stages, counts, hashes, and bounded diagnostics only. `stdout_tail`/`stderr_tail` fields, when required for compatibility, contain a redacted bounded projection rather than raw tails. Redaction covers credential forms, authorization headers, JSON request bodies, provider response markers, source/prompt sentinel text, absolute project/lock paths, and unbounded exception text. `raw_provider_payload_exposed` remains false.

### 6. Compatibility and observability

The boundary is adaptation-only. Legacy CLI diagnostics and non-adaptation generator behavior remain available unless a line is itself an unsafe raw payload. Existing provider-lazy safety and adaptation job-reporting contracts must remain green. A meaningful failure code/stage is always emitted even when verbose output is suppressed.

## Risks / Trade-offs

- [Risk] Over-suppression could make a failed build opaque. -> Mitigation: fixed safe progress fields, concrete stage/code, counts, attempt/revision identity, and bounded redacted diagnostics.
- [Risk] Root handler changes could affect unrelated workflows. -> Mitigation: adaptation scope plus provider-specific handler filters; preserve legacy handler behavior outside scope and test it.
- [Risk] Lazy logger behavior varies by SDK version. -> Mitigation: test logger names/handler emission after factory construction and keep idempotent provider safety calls.
- [Risk] Capturing subprocess output could hide actionable errors. -> Mitigation: map process exit, timeout, JSON/schema, and provider failure into bounded codes; never depend on raw output for status.

## Migration Plan

1. Add and unit-test the adaptation output guard and redaction schema.
2. Wire adaptation worker/progress/WebOutputCapture paths to bounded events.
3. Remove/guard direct lock and generator raw output while preserving legacy diagnostics.
4. Harden root/application and late provider logger/handler safety.
5. Add sentinel tests for all required leaks and run existing provider/adaptation job suites.
6. Verify strict OpenSpec and diff scope; do not archive or commit.
