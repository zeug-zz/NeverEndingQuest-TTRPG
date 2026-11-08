# Advisory Assessor Configuration Stub

**UNCONFIGURED / NOT APPROVED / NO CALLS AUTHORIZED.** This file is a non-operational placeholder. It identifies no provider, model, endpoint, credentials, prompt, or executable assessment configuration. The current work is provider-free; do not invoke an assessor.

| Field | Draft state |
| --- | --- |
| Provider and model identifier | `PENDING_OWNER_APPROVAL` |
| Model/version and serving route | `PENDING_OWNER_APPROVAL` |
| System and task prompt hashes | `PENDING_OWNER_APPROVAL` |
| Output schema and parsing policy | `PENDING_OWNER_APPROVAL` |
| Temperature and other generation settings | `PENDING_OWNER_APPROVAL` |
| Assessment identity and data-retention policy | `PENDING_OWNER_APPROVAL` |
| Item-to-artifact binding | Exact scene, condition, artifact SHA-256, and axis required if separately approved |
| Rating range | Integer 1-5 on legibility and usefulness, as proposed in `rubric.md` |
| Attempt ceiling | `PENDING_OWNER_APPROVAL`; no attempt is authorized here |
| Retry policy and request/time limits | `PENDING_OWNER_APPROVAL` |
| Calibration labels and exact artifact versions | `PENDING_OWNER_APPROVAL`; no labels or scores are supplied here |
| Owner-score visibility isolation | Must be specified and frozen before any separately approved assessment |
| Current status | No provider calls, assessment, or scoring performed |

The design proposes a distinct ceiling of at most 30 advisory attempts total (24 held-out artifacts plus six calibration items), at most one attempt per item. That proposal is not approved, is not a current budget, and cannot be enabled by filling in this stub. Any future assessor configuration, model identity, budget, limits, and data handling require separate owner authorization and a frozen manifest before use. Advisory output cannot replace owner ratings.
