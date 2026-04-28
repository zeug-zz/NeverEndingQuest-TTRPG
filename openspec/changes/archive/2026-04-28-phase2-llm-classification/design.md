# Design: Phase 2 LLM-Assisted Narrative Classification

## Architecture Boundaries

### Flow Diagram

```
Module Build Complete (post-finisher)
         │
         ▼
┌─────────────────────────────────────┐
│  Deterministic Ambiguity Detection   │  ← Python only
│  - Scans for ambiguous entities      │
│  - Scans for ambiguous phrases       │
│  - Scans for ambiguous NPC mentions  │
│  - Builds classification batches     │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  LLM Classification (DP1-3)         │  ← Advisory only
│  - Single call per batch            │
│  - Structured JSON output           │
│  - Fail-open to safe defaults       │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Python Validation & Apply          │  ← Gatekeeper
│  - Validates enum values            │
│  - Rejects hallucinated labels      │
│  - Applies only allowed transforms  │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Publishability Re-audit            │
│  - Regenerates semantic authority   │
│  - Re-runs semantic probes          │
│  - Produces residual blocker report │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  LLM Remediation Proposals (DP4)    │  ← Advisory only
│  - Consumes residual blockers       │
│  - Proposes concrete fixes          │
│  - Fail-open to empty proposals     │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  GUI Review (human)                 │  ← Final authority
│  - Shows classification results     │
│  - Shows proposed remediations      │
│  - Accept/reject per proposal       │
└─────────────────────────────────────┘
```

### File Placement

All new code lives in a dedicated extension module. No modifications to existing builder/finisher/validator files in Phase 2 MVP:

```
web/extensions/toolkit_llm_classification.py   # NEW — classification engine
web/templates/module_toolkit.html               # MODIFIED — review UI
```

The classification engine is invoked from `toolkit_module_finisher.py` after deterministic enrichment but before publishability audit, guarded by a feature flag.

## Key Decisions

### Decision 1: Batch Classification, Not Per-Entity

**Chosen:** Send one batch per classification domain (entities, destinations, NPCs) rather than one call per ambiguous item.

**Rationale:** The LLM needs surrounding context to classify correctly (e.g., "spectral servants" may be combatants in one room and illusion in another). A single batch call with contextualized items is token-efficient and produces consistent classifications.

### Decision 2: Content-Hash Caching

**Chosen:** Cache LLM classification results keyed by `hashlib.sha256(authored_text + module_slug).hexdigest()`.

**Rationale:** Prevents costly LLM re-calls when:
- The same module is re-ingested with unchanged authored text
- The readiness gate re-runs during toolkit repeat builds
- The publishability audit is re-run without source changes

Cache lives at `modules/<slug>/llm_classification_cache.json`. Invalidated when authored text changes.

### Decision 3: Strict Enum Validation

**Chosen:** Python MUST validate every LLM classification label against allowed enum values. Unknown labels SHALL fall back to the safest default.

**Rationale:** Prevents hallucinated labels from corrupting module JSON. The LLM may invent new categories; Python enforces the contract.

Allowed enums:
- Entity: `combatant`, `scene_illusion`, `narrator_flavor`
- Destination: `canonical_alias`, `quest_objective`, `evocative_prose`
- NPC visibility: `visible`, `hidden_reveal`, `lore_only`

### Decision 4: Feature Flag Gate

**Chosen:** Classification only activates when `ENABLE_LLM_CLASSIFICATION = True` in `model_config.py`. Default: `True` for toolkit builds, `False` for CLI ingest.

**Rationale:** Phase 2 is additive and advisory. The feature flag allows:
- Gradual rollout (enable for specific modules first)
- Easy disable if LLM behavior is problematic
- No impact on existing deterministic flows when disabled

### Decision 5: GUI Review Before Apply

**Chosen:** Classification results and remediation proposals are surfaced in the toolkit GUI for human review before any transforms are applied to module JSON.

**Rationale:** Respects the Prime Directive ("Python enforces reality; you interpret it"). The human author must approve LLM-proposed classification changes. Auto-apply is deferred to a future phase.

## Trade-offs

| Trade-off | Decision |
|---|---|
| **LLM cost vs accuracy** | Batch calls are token-efficient; caching prevents re-calls. Accept slight per-item classification errors (fail-safe defaults catch them). |
| **Human review vs automation** | Review-first in MVP. Auto-apply can be added later with confidence thresholds. |
| **Scope vs complexity** | Only 4 classification domains. Resist adding entity extraction, plot generation, or narrative enrichment (these belong in v2 narrative track). |
| **Code location** | Single extension module keeps merge boundaries clean. Avoid fragmenting across many files. |

## Migration and Rollback

### Activation
1. Set `ENABLE_LLM_CLASSIFICATION = True` in `model_config.py`
2. Classification engine activates after finisher enrichment
3. GUI shows classification review panel when ambiguity is detected

### Rollback
1. Set `ENABLE_LLM_CLASSIFICATION = False`
2. Classification cache is ignored
3. Deterministic extraction proceeds as before
4. No module data is affected (all classification transforms require human approval)

### Cache Invalidation
- Delete `modules/<slug>/llm_classification_cache.json` to force re-classification on next build
- Or set `ENABLE_LLM_CLASSIFICATION = False` to bypass entirely
