#!/usr/bin/env python3
"""
Smoke check for unified-assets MMG authority.

This script is intentionally thin: it calls the shared MMG authority helper
and the Flask endpoint, then prints a concise parity summary so it cannot drift
from the production extraction path.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.module_mmg_authority import build_module_mmg_assets


MODULE_NAME = "Night_of_the_Restless_Dead"


def get_endpoint_assets(module_name):
    from web.web_interface import app

    with app.test_client() as client:
        response = client.get(f"/api/toolkit/modules/{module_name}/unified-assets")
        if response.status_code != 200:
            raise SystemExit(f"endpoint failed with status {response.status_code}")
        payload = response.get_json() or {}
        if not payload.get("success"):
            raise SystemExit(payload.get("error") or "endpoint returned failure")
        return payload.get("assets", [])


def asset_signature(asset):
    return (asset.get("id"), asset.get("type"), asset.get("authority_role"))


def main():
    helper = build_module_mmg_assets(MODULE_NAME)
    endpoint_assets = get_endpoint_assets(MODULE_NAME)

    helper_assets = list(helper.get("npcs", {}).values()) + list(
        helper.get("monsters", {}).values()
    )

    print("UNIFIED-ASSETS MMG SMOKE")
    print(f"module: {MODULE_NAME}")
    print(f"helper_assets: {len(helper_assets)}")
    print(f"endpoint_assets: {len(endpoint_assets)}")
    print(f"suppressed_npc_slugs: {helper.get('suppressed_npc_slugs', [])}")

    helper_signatures = sorted(asset_signature(asset) for asset in helper_assets)
    endpoint_signatures = sorted(asset_signature(asset) for asset in endpoint_assets)

    print(f"helper_signatures: {helper_signatures}")
    print(f"endpoint_signatures: {endpoint_signatures}")

    if helper_signatures != endpoint_signatures:
        raise SystemExit("MMG helper and endpoint diverged")


if __name__ == "__main__":
    main()
