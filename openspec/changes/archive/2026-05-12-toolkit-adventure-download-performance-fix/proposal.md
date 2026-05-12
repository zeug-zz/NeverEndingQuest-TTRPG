## Why

The `Download Adventure` button in the Toolkit Module Builder hangs for 20-35 seconds on modules with multiple areas (Thornwood Watch, Xhalruun's Masquerade). The endpoint calls `generate_homebrewery_adventure()` which makes serial LLM calls — 1 per area for `_llm_area_overview()`, plus intro narrative and plot hook. For Xhalruun (6 areas), that's 8 serial LLM calls before the response starts streaming. The browser shows no loading indicator during the wait.

The post-build finisher hook already writes `MODULE_SUMMARY.md` to disk during stage 12 of the module build. So for any module built through the toolkit or ingest pipeline, the file is already on disk — the endpoint is regenerating it unnecessarily.

## What Changes

1. **`web/web_interface.py`** — Rewrite `get_module_adventure_markdown()` to serve the pre-generated `MODULE_SUMMARY.md` file when it exists. Only fall back to `generate_homebrewery_adventure()` for legacy modules without a summary. Legacy generation also writes the result to disk for subsequent requests.

2. **`web/templates/module_toolkit.html`** — Add loading state to the `downloadAdventure()` button: disable the button and show "Generating..." text during the fetch. Restore on completion or error.

## Capabilities

### Modified Capabilities

- `toolkit-module-adventure-download` — Download endpoint now serves pre-generated file rather than regenerating. Modifies requirement "SHALL expose an API endpoint for adventure markdown download" to prefer cached file, falling back to generation.

## Impact

- **`web/web_interface.py`** — Rewrite `get_module_adventure_markdown()` (~30 lines changed)
- **`web/templates/module_toolkit.html`** — Add loading state to `downloadAdventure()` (~10 lines changed)
- **Zero new tests needed** — existing 52 tests cover generation logic; behavior change is at HTTP/filesystem layer
- **No config or schema changes**
- **Backward compatibility**: legacy modules without `MODULE_SUMMARY.md` get one-time generation with disk caching
