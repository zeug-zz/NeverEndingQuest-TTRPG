## 1. Backend response-format compatibility

- [X] 1.1 Update `web/web_interface.py` `handle_generate_image(...)` to extract `image_url`, `b64_json`, and optional `revised_prompt` with `getattr(...)` instead of assuming `.url` exists.
- [X] 1.2 Preserve the existing URL download path when `image_url` is present.
- [X] 1.3 Add base64 decode handling when `b64_json` is present, writing decoded bytes to the generated image file without calling `requests.get(...)`.
- [X] 1.4 Return an explicit error and emit `image_generation_error` when neither `image_url` nor `b64_json` is present.
- [X] 1.5 Ensure metadata distinguishes URL-backed images from base64-backed images and does not persist `original_url: null` as a valid URL.

## 2. Browser render source

- [X] 2.1 Emit a browser-usable image source in `image_generated` after successful generation.
- [X] 2.2 Prefer a local saved image path/route when that path is browser-accessible.
- [X] 2.3 Use a `data:image/png;base64,...` fallback only when no browser-accessible local path is available.
- [X] 2.4 Preserve the existing frontend `img.src = data.image_url` flow or update it with a clearly named compatible field while keeping old payloads working.

## 3. Frontend failure recovery

- [X] 3.1 Fix the `image_generation_error` handler in `web/templates/game_interface.html` to look for the same loading class set by `generateImageForMessage(...)` (`loading-image`).
- [X] 3.2 Verify failed generation re-enables the button and restores the `Generate Image` label.

## 4. Regression coverage

- [X] 4.1 Add a focused backend test or source-contract test proving `handle_generate_image(...)` supports base64-only image responses.
- [X] 4.2 Add a focused backend test or source-contract test proving URL responses still use the existing download path.
- [X] 4.3 Add a focused frontend source-contract test proving the error handler clears `loading-image`, not an unrelated class.
- [X] 4.4 Add a regression assertion that `requests.get(None)` cannot occur in the chat image handler.

## 5. Verification

- [X] 5.1 Compile-check modified Python files with `.venv/bin/python -m py_compile web/web_interface.py`.
- [X] 5.2 Run the new targeted regression tests.
- [X] 5.3 Run or manually smoke the chat `[Generate Image]` button with the default `gpt-image-1` path and confirm the generated image renders in chat.
- [X] 5.4 Optionally smoke a URL-shaped mock/fixture path to confirm URL-backed response compatibility.
