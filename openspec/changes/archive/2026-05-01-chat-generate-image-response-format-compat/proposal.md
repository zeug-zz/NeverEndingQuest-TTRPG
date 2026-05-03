# Why

The chat `[Generate Image]` button has regressed after the image model default moved to `gpt-image-1`. The Socket.IO handler in `web/web_interface.py` still assumes image generation responses expose `response.data[0].url`, which matched older URL-backed image response paths. `gpt-image-1` can return base64 image data (`b64_json`) instead, leaving `image_url` as `None`.

The observed startup/chat failure is not an API generation failure: OpenAI returns `200 OK`. The local app then attempts `requests.get(None)` while saving the image, logs `Warning: Failed to save image locally: Invalid URL 'None'`, and emits `image_generated` with `image_url: None`, so the browser cannot render the generated image.

Other image paths already handle both URL and base64 response shapes, notably `core/toolkit/portrait_service.py`, `core/toolkit/npc_generator.py`, and `core/toolkit/monster_generator.py`. The chat image generation handler was missed.

# What Changes

- Update the chat `generate_image` Socket.IO handler to extract both `url` and `b64_json` from image API responses.
- Decode and save base64 image data directly when no URL is present.
- Preserve the existing URL download path for any provider/model that returns URL image data.
- Emit a browser-usable image source after successful generation, either a local saved image path or a data URL fallback.
- Ensure metadata does not store `original_url: None` as if it were a valid source URL.
- Fix the frontend error handler class mismatch so failed chat image generation re-enables the loading button reliably.
- Add regression coverage for base64-only responses and URL responses so the handler cannot regress to URL-only assumptions.

# Capability Scope

- Chat narration `[Generate Image]` button behavior in `web/templates/game_interface.html`.
- Socket.IO image generation handler in `web/web_interface.py`.
- Focused regression tests for response-format compatibility and frontend loading-state recovery.

# Non-Goals

- Changing portrait, NPC, monster, or Module Media Generator image generation flows.
- Replacing the image provider or changing the default image model.
- Changing image prompt wording or style.
- Reworking image archive/storage layout beyond what is needed to return a renderable source.
- Changing image-cost accounting except to preserve existing successful-generation tracking.
- Broad logging reconfiguration. OpenAI/httpcore debug noise may be reduced only if it can be done as a narrow, low-risk cleanup.

# Impact

- Chat `[Generate Image]` works with `gpt-image-1` base64 responses and URL-backed responses.
- Local module image saving continues when possible.
- Browser rendering no longer depends on temporary provider URLs.
- Failed generation paths leave the button usable for retry.

# Risks

- Returning a data URL can increase Socket.IO payload size if local route emission is not used. Prefer emitting a local saved route/path when available.
- If local save fails after a successful base64 response, a data URL fallback should render immediately but not provide durable image history.
- Existing module image storage may not be web-served directly; implementation should verify the emitted local path is actually browser-accessible before relying on it.
