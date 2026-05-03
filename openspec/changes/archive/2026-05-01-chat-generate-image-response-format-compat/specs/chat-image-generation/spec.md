# Chat Image Generation

## ADDED Requirements

### Requirement: Chat image generation supports base64 image responses

The chat `[Generate Image]` Socket.IO handler SHALL render successfully when the image API returns base64 image data instead of a URL.

Specifically, `web/web_interface.py` `handle_generate_image(...)` MUST inspect both `response.data[0].url` and `response.data[0].b64_json`. When `b64_json` is present and `url` is absent, the handler MUST decode the base64 image data and MUST NOT attempt to download the image via `requests.get(None)`.

#### Scenario: gpt-image-1 returns base64 image data

**Given** the chat `[Generate Image]` handler calls an image model that returns `b64_json` and no `url`  
**When** the generation response is processed  
**Then** the handler SHALL decode the base64 image data  
**And** the handler SHALL save the generated image locally when possible  
**And** the handler SHALL emit `image_generated` with a browser-usable image source  
**And** the handler SHALL NOT call `requests.get(...)` with `None`

### Requirement: Chat image generation preserves URL response compatibility

The chat `[Generate Image]` Socket.IO handler SHALL continue to support image API responses that provide a temporary or permanent image URL.

#### Scenario: URL-backed image response

**Given** the chat `[Generate Image]` handler receives an image response with `url` and no `b64_json`  
**When** the generation response is processed  
**Then** the handler SHALL download the image from that URL  
**And** the handler SHALL save the generated image locally when possible  
**And** the handler SHALL emit `image_generated` with a browser-usable image source

### Requirement: Chat image generation fails explicitly when no image data exists

The chat `[Generate Image]` Socket.IO handler SHALL fail explicitly when the image response contains neither URL image data nor base64 image data.

#### Scenario: Image response lacks usable image data

**Given** the image API returns a success-shaped response without `url` or `b64_json`  
**When** the chat image handler processes the response  
**Then** the handler SHALL emit `image_generation_error`  
**And** the handler SHALL NOT emit `image_generated` with a null image source

### Requirement: Generated chat images use a browser-usable source

The `image_generated` payload emitted by the chat image generation handler SHALL include an image source that the browser can render immediately.

The implementation SHOULD prefer a browser-accessible local saved image path when available. If no browser-accessible local path is available for a base64-backed response, the implementation MAY emit a `data:image/png;base64,...` source as a fallback.

#### Scenario: Browser receives generated image payload

**Given** image generation succeeds  
**When** the frontend receives `image_generated`  
**Then** assigning the emitted image source to `img.src` SHALL display the generated image  
**And** the emitted image source SHALL NOT be `null`, `None`, or an empty string

### Requirement: Image generation failure restores frontend retry state

The frontend `image_generation_error` handler SHALL re-enable the same button state that `generateImageForMessage(...)` marks as loading.

#### Scenario: Chat image generation fails after button enters loading state

**Given** `generateImageForMessage(...)` disables a button and adds the `loading-image` class  
**When** the frontend receives `image_generation_error`  
**Then** the handler SHALL find the `loading-image` button  
**And** the handler SHALL re-enable it  
**And** the handler SHALL remove `loading-image`  
**And** the handler SHALL restore the label to `Generate Image`
