# SPDX-FileCopyrightText: 2024 MoonlightByte
# SPDX-License-Identifier: Fair-Source-1.0
# License: See LICENSE file in the repository root
# This software is subject to the terms of the Fair Source License.

"""Small pure validators for encounter-scoped tactical data."""

from typing import Any, List


def validate_tactical_features(features: Any) -> List[str]:
    """Return bounded cross-item error codes for one location's features.

    JSON Schema validates the list and each feature's fields. This helper owns
    the cross-item uniqueness rule for feature IDs and never mutates its input.
    At most one fixed error code is returned for deterministic diagnostics.
    """
    if not isinstance(features, list):
        return ["tactical_features_not_list"]

    seen_feature_ids = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        feature_id = feature.get("featureId")
        if not isinstance(feature_id, str) or not feature_id:
            continue
        if feature_id in seen_feature_ids:
            return ["duplicate_feature_id"]
        seen_feature_ids.add(feature_id)

    return []
