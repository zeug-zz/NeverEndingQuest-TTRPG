## Context

The completed `toolkit-llm-adaptation-builder` change supplies the adaptation dossier contract, provider runner, bounded source context, staging, revision, gate composition, publication transaction, Markdown quality, provenance, and job-reporting primitives. Those primitives are currently exercised by provider-free harnesses and direct utility seams.

The live Toolkit has two separate entry points:

- Uploaded Markdown/PDF files enter `toolkit_homebrew_routes.py`, are normalized into an artifact workspace, and then call the packet builder without adaptation arguments.
- The existing text-description Socket.IO builder calls `ModuleBuilder.build_module(narrative)` directly and writes to a module directory, bypassing the adaptation dossier, staging, and adaptation publication transaction.

This design connects both entry points to one background adaptation runtime. The existing GUI remains the operator surface; the feature flag determines the route.

## Goals / Non-Goals

**Goals:**

- MUST make enabled adaptation the background route for eligible uploads and text descriptions.
- MUST preserve legacy behavior when adaptation is disabled or when a job is explicitly legacy.
- MUST use one Python-owned authoring, staging, ModuleBuilder, readiness, finishing, Markdown, registry, campaign, and rollback transaction for both input types.
- MUST carry Python-owned rights, source identity, world-context provenance, and attempt metadata into authoring before the LLM is called.
- MUST distinguish author-policy refusal, provider/API refusal, provider infrastructure failure, invalid dossier, and downstream build failure.
- MUST prevent a selected adaptation failure from silently falling through to legacy generation.
- MUST keep the LLM limited to bounded narrative dossier content and proposed world hooks.
- SHOULD keep host-file hooks thin and isolate shared orchestration in an extension module.

**Non-Goals:**

- No new GUI tab, mode selector, approval dialog, or alternate operator workflow.
- No change to the completed adaptation scaffold's publication gates or registry/campaign contracts except to invoke them.
- No direct LLM writes to module files, registry state, campaign state, or mechanical state.
- No automatic legal rights determination or relabeling of restricted sources.
- No change to the default shipped feature flag; rollout remains operator-controlled.
- No provider fallback from a selected adaptation request to legacy generation.

## Decisions

### Use one background adaptation runtime adapter

Create a focused adapter in the extension layer that owns the runtime sequence:

1. Resolve whether the input is eligible and whether adaptation is enabled.
2. Build bounded source context and Python-owned attempt metadata.
3. Resolve rights metadata and read-only world-context provenance.
4. Run adaptation authoring and persist the dossier artifact.
5. Reserve an isolated staging target.
6. Invoke the existing adaptation-aware packet builder/ModuleBuilder handoff.
7. Run the existing readiness, finisher, Markdown, registry, campaign, and rollback transaction.
8. Return the existing job/result shape plus bounded adaptation fields.

The adapter MUST not duplicate the completed scaffold's gate or publication logic. It only assembles inputs and connects existing stages.

Alternative rejected: add separate upload and text-specific adaptation implementations. That would recreate the current divergence and allow one path to bypass publication guarantees.

### Treat the feature flag as a background route selector

When the flag is exactly `True`, eligible inputs automatically request `llm_adaptation` internally. No GUI field is needed. When the flag is false, route selection remains legacy and no adaptation authoring is attempted.

The route decision MUST be recorded in the job and attempt artifacts. A selected adaptation route is authoritative for that attempt; it cannot silently downgrade after authoring or build failure.

Alternative rejected: use the flag only as permission while requiring an undocumented internal route field. That is the current incomplete behavior and prevents normal GUI jobs from exercising the builder.

### Normalize both inputs into an adaptation runtime envelope

The adapter will use a common bounded envelope with:

- `input_kind`: `upload_markdown`, `upload_pdf`, or `text_description`;
- source title/name and lowercase SHA-256 source hash;
- bounded source digest/context and inferred or selected source profile evidence;
- Python-owned rights class, review requirement, and review status;
- attempt/job/revision identity;
- bounded world-context provenance and fallback status;
- model/provider task metadata without credentials.

Upload inputs use the existing normalized packet and upload rights classification. Text descriptions use the submitted narrative as user-authored source material, compute a deterministic source hash, and create a minimal attempt workspace so the same packet builder and finisher path can be reused.

Raw source is bounded before provider serialization. Runtime paths, credentials, full prompts, and arbitrary provider response data are excluded.

### Make Python authoritative for rights metadata

The adapter will set rights metadata before building the author request. User-entered text is `user_authored`. An upload uses the validated upload classification; restricted or review-pending inputs remain review-gated.

The LLM may repeat the metadata in its dossier but cannot change it. Missing or contradictory rights fields produce an explicit refusal/blocked outcome rather than a forced ready dossier.

Alternative rejected: let the author infer ownership from source prose or decide that a restricted source is safe. That would make a creative model the rights authority.

### Use strict GPT-family structured output with parser defense

The author request will use the repository's task/profile parameter resolver and a strict structured-output contract where the configured provider/model supports it. The existing Python dossier parser remains mandatory after the provider response.

The runtime will distinguish two refusal channels:

- API-level refusal or content-filter response with no dossier content;
- valid dossier JSON with `status: refused`, including rights or source-policy warnings.

Only bounded reason categories and safe warning text are retained in reports. Raw refusal text is not sent to GUI consumers or persisted unbounded.

OpenAI GPT-5-family requests MUST continue to omit unsupported legacy sampling parameters. Provider-specific structured-output differences belong in the existing provider/profile boundary rather than in the route adapter.

### Route text descriptions through a minimal packet workspace

The text-description path will stop writing directly to `./modules/<name>` when adaptation is enabled. It will create an attempt-scoped, project-relative workspace containing the bounded concept input and the minimum packet metadata required by the existing adaptation packet builder.

The packet builder will receive the validated dossier and reserved adaptation staging target. The existing finisher then owns readiness, report agreement, Markdown, registry, campaign, and rollback semantics.

The legacy text path remains unchanged when adaptation is disabled.

Alternative rejected: add adaptation context only to `ModuleBuilder.build_module(narrative)` while leaving direct output writes in place. That would bypass staging and make publication rollback unsafe.

### Preserve the completed publication transaction

The adapter will treat module files as provisional until the completed adaptation publication transaction reports success. The existing order remains:

1. staged ModuleBuilder output;
2. schema/readiness/mechanical/semantic/report checks;
3. Markdown generation and quality validation;
4. registry integration and post-write verification;
5. active campaign synchronization and verification;
6. rollback on post-registration failure;
7. completed status.

No route-level success response may be emitted from raw ModuleBuilder completion alone.

### Keep job state thread-safe and observable

Existing job locks and progress callbacks remain the source of truth for GUI polling. The adapter will publish bounded adaptation phases such as authoring, staging, revision, validation, Markdown, registry, campaign sync, rollback, and terminal outcome. Attempt artifacts remain the durable diagnostic source.

Provider clients are request-scoped or passed through existing injectable seams; no mutable global adaptation state is introduced.

## Risks / Trade-offs

- [Risk] The model returns `status: refused` because rights metadata is missing or restrictive. -> Python supplies rights metadata before authoring, preserves legitimate review refusal, and records bounded refusal diagnostics instead of forcing a build.
- [Risk] GPT-5-family structured-output support differs by provider. -> Keep provider parameter resolution centralized, use capability-aware structured output, and retain the Python parser as a hard fallback validator.
- [Risk] Text-description workspaces diverge from upload packets. -> Use one minimal runtime envelope and the same packet builder/finisher transaction, with provider-free parity tests.
- [Risk] A selected adaptation attempt silently falls back to legacy after failure. -> Persist route selection and fail closed; legacy is selected only when the feature flag was false before the attempt.
- [Risk] Existing direct text builds write files before readiness. -> Gate the direct path behind the flag and move enabled adaptation output to reserved staging before ModuleBuilder runs.
- [Risk] Provider refusal or quota errors appear as generic GUI failures. -> Map failure classes through the existing adaptation job-reporting contract and retain safe attempt diagnostics.
- [Risk] Runtime registry or campaign state is partially changed. -> Reuse the completed atomic registry/campaign transaction and targeted rollback snapshots; test with sentinel files.
- [Risk] Enabling adaptation changes existing tester workflows unexpectedly. -> Keep the flag operator-controlled, test both true and false routing, and do not alter the shipped default in this slice.

## Migration Plan

1. Add provider-free runtime envelope and route-decision seams without changing the feature flag.
2. Wire the upload worker to authoring, dossier persistence, staging, and the existing adaptation packet/finisher path.
3. Wire the text-description Socket.IO worker to the same adapter and remove its enabled-path direct output bypass.
4. Add rights-aware author request tests, including valid user-authored and restricted/refused cases.
5. Add provider refusal/structured-output diagnostics tests and a no-network tripwire.
6. Run the Jeremys Magic Shop source through the actual upload job path using an injected author provider, then run a bounded real-provider smoke with complete rights metadata.
7. Verify schema/readiness/semantic/report/Markdown/registry/campaign/rollback outcomes and protected real-artifact hashes.
8. Leave `ENABLE_LLM_ADAPTATION` operator-controlled. Rollback is setting it to `False`, which returns both input paths to their existing legacy routes without deleting diagnostics.

## Open Questions

None. The user requirement resolves the routing decision: adaptation is a background builder default when enabled, with no GUI mode selection.

## Follow-up Slice: Semantic Revision Status Projection Repair

The shared adaptation classifier and revision runner already define the semantic-revision budget. The runtime-unification boundary must preserve that decision when a gate result becomes a job result; it MUST NOT derive a terminal `adaptation_blocked` status merely because the initial gate failed.

For a first semantic or mechanical content failure, the runtime MUST carry one coherent decision through the packet result, persisted `build_result`, job state, and retry diagnostics:

- `adaptation_revision_required` is the terminal job status;
- `outcome=semantic_revision` and retry status is available;
- `next_revision_eligible=true` and the remaining budget are retained;
- no registry, campaign, or live-module publication occurs.

After the allowed revision is consumed, the same surfaces MUST agree on an exhausted/blocked terminal result and MUST clear retry eligibility. Infrastructure, rights/refusal, publication, and monster-guardrail failures remain non-revision classes even when a nominal revision budget exists. Legacy routes and legacy payload shapes remain unchanged.
