# Kokoro Local TTS Pilot Plan

Status: Proposed
Priority: Medium-High
Risk: Low runtime risk, moderate installer/support risk

## Objective

Evaluate and implement Kokoro (`hexgrad/kokoro`) as an optional local Text-to-Speech engine for DM narration, improving voice quality over Chrome/Edge browser TTS without making the base Windows install more fragile for non-coders.

## Initial Assessment

Kokoro is worth piloting, but not as a default hard dependency.

The proposal is broadly correct for a proof of concept: Kokoro is small, local, Apache-licensed, and should sound noticeably better than browser voices. The main understated risk is installer complexity, not Flask/frontend integration.

## Download and Disk Footprint

- Kokoro model file: about `327 MB`.
- Each voice file: about `0.5 MB`.
- Full Hugging Face repo storage: about `1.23 GB`, but the implementation should avoid downloading all samples/voices.
- Python dependencies are the larger variable: `torch`, `transformers`, `huggingface_hub`, `misaki`, and `soundfile`.
- Realistic minimal Windows download is likely `600 MB` to just under `1 GB`, depending on cached wheels and torch wheel size.
- Installed disk use may exceed `1 GB`.

Compared with the current modules directory scale (about `4 GB`), the size is acceptable if optional.

## Windows Non-Coder Risk

Default installer should not require Kokoro.

Adding `torch` plus `espeak-ng` to the normal install path would increase install failures, download time, and support burden. Kokoro should be an optional local-high-quality voice engine with clean fallback to existing Browser/OpenAI TTS.

Recommended deployment model:

- Keep Browser TTS as default.
- Add Kokoro as optional `Local High Quality` voice engine.
- Provide a separate one-click optional installer script, such as `install_kokoro_voice_windows.bat`.
- If Kokoro is unavailable, the UI should fall back cleanly and explain setup status.

## Value

High value for tabletop play. Voice quality is one of the most player-visible upgrades, and local generation avoids API cost and network dependency. The feature is worthwhile if implemented behind a feature flag and optional dependency gate.

## Implementation Plan

### 1. Configuration

Add feature flags and defaults:

```python
ENABLE_KOKORO_TTS = False
KOKORO_TTS_VOICE = "af_bella"
KOKORO_TTS_LANG = "a"
KOKORO_TTS_MAX_CHARS = 1500
```

Keep existing Browser/OpenAI TTS behavior unchanged.

### 2. Optional Dependencies

Do not add Kokoro to base `requirements.txt` initially.

Add a separate optional dependency file:

```text
requirements-kokoro.txt
```

Expected contents:

```text
kokoro>=0.9.4
soundfile
```

Torch installation may need explicit platform guidance rather than a naive base requirement, depending on Windows wheel behavior.

### 3. Backend Service

Create a small extension module, for example:

```text
web/extensions/kokoro_tts.py
```

Responsibilities:

- Detect Kokoro availability without crashing startup.
- Lazy-load `KPipeline` on first Kokoro request, not Flask startup.
- Cache pipeline globally after first load.
- Use a lock or single-worker queue to prevent overlapping CPU-heavy generations.
- Generate WAV audio in memory with `soundfile`.
- Limit text length with `KOKORO_TTS_MAX_CHARS`.
- Return structured availability/error data for the UI.

### 4. API Integration

Extend the existing `/api/tts` route rather than creating a parallel frontend path.

Contract:

- `engine=kokoro` routes to local Kokoro generation.
- Existing OpenAI engines remain unchanged.
- Browser TTS remains frontend-only.
- Missing dependency/model/espeak failures return JSON errors and do not affect game startup.

### 5. Frontend Integration

Extend the existing DM Voice settings dropdown:

- Add engine option: `Kokoro Local` or `Local High Quality`.
- Reuse the existing TTS queue manager.
- Reuse `playAudioFromUrl(...)` for returned WAV blobs.
- Add a backend capability check so Kokoro can be shown as unavailable with a setup hint.
- Do not reintroduce sentence streaming in the first pass.

First pass should synthesize whole narration messages, matching the current OpenAI TTS path.

### 6. Windows Optional Installer

Create a separate optional script first:

```text
install_kokoro_voice_windows.bat
```

Responsibilities:

- Verify the base install and virtual environment exist.
- Install optional Python dependencies into `venv`.
- Check for `espeak-ng` availability.
- If `espeak-ng` is missing, open or print clear MSI/winget instructions.
- Run a tiny smoke test that imports Kokoro and initializes a short voice generation path.
- Print plain success/failure guidance for non-coders.

Avoid making this mandatory in `install_neverendingquest_windows.bat` until tester feedback proves it reliable.

### 7. Verification

Add tests/source-contract checks for:

- Kokoro availability detection fails open.
- `/api/tts` preserves OpenAI behavior.
- `/api/tts` returns a clean error when `engine=kokoro` but dependencies are missing.
- Frontend engine list includes Kokoro only behind capability/config gating.
- Existing Browser TTS queue behavior remains unchanged.

Manual smoke checklist:

- Browser TTS still works without Kokoro installed.
- OpenAI TTS still works unchanged.
- Kokoro TTS works after optional install.
- Missing Kokoro does not block Start Game.
- Stop/cancel playback still clears queue and button state.

## Recommendation

Proceed with an optional Kokoro pilot. Do not make it part of the default Windows install until the optional installer has been tested on non-developer Windows machines.

Best first milestone: backend capability detection plus optional `/api/tts` Kokoro path, with no default installer changes.
