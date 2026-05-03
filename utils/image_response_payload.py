# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""
NeverEndingQuest Image Response Payload Utils
Copyright (c) 2024 MoonlightByte
Licensed under Fair Source License 1.0

Pure helpers for converting image API responses into runtime-safe payloads.

This software is free for non-commercial and educational use.
Commercial competing use is prohibited for 2 years from release.
See LICENSE file for full terms.
"""

import base64
from typing import Any, Dict, Optional, Tuple


def extract_image_data(response: Any) -> Tuple[Optional[str], Optional[str]]:
    """Extract image URL and base64 data from an image generation response.

    Returns:
        Tuple of (image_url, b64_json). Either or both may be None.
    """
    data = getattr(response, "data", None)
    if not data:
        return None, None

    first = data[0]
    image_url = getattr(first, "url", None)
    b64_json = getattr(first, "b64_json", None)
    return image_url, b64_json


def convert_image_response_payload(response: Any) -> Dict[str, Any]:
    """Convert image API response into browser/render/save payload.

    Returns a dictionary with keys:
    - browser_source: string suitable for browser img.src
    - image_bytes: decoded bytes for base64 responses, else None
    - source: "base64" or "url"

    Raises:
        ValueError: response has no usable image data or invalid base64 data.
    """
    image_url, b64_json = extract_image_data(response)

    if b64_json:
        try:
            image_bytes = base64.b64decode(b64_json)
        except Exception as decode_error:
            raise ValueError(f"Invalid base64 image data: {decode_error}") from decode_error

        return {
            "browser_source": f"data:image/png;base64,{b64_json}",
            "image_bytes": image_bytes,
            "source": "base64",
        }

    if image_url:
        return {
            "browser_source": image_url,
            "image_bytes": None,
            "source": "url",
        }

    raise ValueError("Image generated but no image data returned from API")
