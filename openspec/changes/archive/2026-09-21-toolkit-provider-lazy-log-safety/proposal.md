# Proposal: Provider Lazy-Logger Safety

## Problem

The provider-log redaction slice configures `openai`, `httpx`, and `httpcore` before shared client construction. Some SDK transport child loggers are created lazily after that call, and a fresh runtime with root DEBUG logging can emit request options, prompt-bearing JSON, response headers, and transport details to stdout.

This is a security and observability defect independent of adaptation gate outcomes. It must be corrected without changing provider requests, models, timeouts, retries, fallback routing, or application failure classification.

## Scope

- Reapply the existing provider-log safety policy after shared OpenAI/OpenRouter client construction.
- Preserve the pre-construction policy call for root-handler and already-existing logger protection.
- Add provider-free regressions for late-created provider child loggers and real factory ordering.
- Keep raw provider payload exposure false in adaptation reports.

## Non-Goals

- No provider SDK replacement.
- No request/response transformation.
- No broad logging-system rewrite.
- No live provider calls or credential requirements.
- No changes to adaptation readiness or publication behavior.
