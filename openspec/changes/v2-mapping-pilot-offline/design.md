# Design

## Context

See `proposal.md` for motivation and `specs/mapping-pilot-offline/spec.md` for the contract.

The SP1 `scripts/mapping_pilot/cartographer.py` already accepts a `Callable[[str], Any]`, extracts selected source locations, validates proposals, and writes a durable attempt ledger and owner audit sheet below project `tmp/`; its 60-call guard counts cartographer client invocations. It currently requires explicit module/location selections. `m1.py` already validates, filters, and renders a layout for a supplied viewpoint. `evidence.py` validates SP3 row bundles, so D1/M1 run artifacts should not be forced into that row schema.

The existing router exposes `LLMRouter.call` with a per-call receipt observer; its `decide` method is currently unavailable. `model_config.py` currently selects `production-auto`, provides a `location_generator` task policy, and has no task override for it. The frozen prereg defines P1/P4 combat placement variants in the combat fixture; it does not define additional P1/P4 variants for the other three fixtures.

## Goals / Non-Goals

**Goals:**

- Add a small SP2 extension in `scripts/mapping_pilot/` that connects the existing cartographer, router receipts, deterministic source selection, and M1 renderer without changing SP1 files.
- Make each D1/M1 run self-identifying and reproducible under its specified `tmp/router-rollout/mapping-pilot/` subtree.
- Keep provider-free verification distinct from the orchestrator-owned live run and the SP4 owner review.

**Non-Goals:**

- No production gameplay, model configuration, core, web/client, published module, or module data changes.
- No new routing/fallback policy, downstream model pin, general evidence framework, spatial authority decision, or module backfill.
- No Stage 1 packet re-rating, SP3 transcript rating, D1 owner audit, or M1 owner rating. Stage 1 remains waived; SP4 owner judgments are not implementation tasks.

## Decisions

### Contract Layer (MUST)

1. **Keep the follow-up in focused mapping-pilot scripts.** Add separate selection, router-client, D1-run, and M1-packet entry points plus provider-free tests, and reuse the existing cartographer and M1 APIs. Do not edit `v2-mapping-pilot-tooling/`. This is smaller than moving or rewriting the existing tooling or creating a general experiment framework.

2. **Use the router's generative call path and receipt observer.** The adapter SHALL call the existing `llm.call` path with the existing `location_generator` task policy, JSON output, and no model-tier or model override. It SHALL check the resolved profile before sending a provider request and refuse if the active selection is not `production-auto` / `openrouter/auto`. It SHALL NOT call `llm.decide`, which is currently gated unavailable, and SHALL NOT call a provider SDK or transport directly. A fake router implementing the call/observer boundary supplies provider-free tests.

3. **Keep the injected cartographer interface stable.** The adapter accepts one prompt string, calls the router, and serializes the returned JSON object as ASCII JSON text for the existing cartographer client contract. The receipt observer records an explicit allowlist of `RouterReceipt` metadata (call/attempt identity, route/provider, fallback, usage/completeness, cost provenance, error type, and elapsed time); it does not record the prompt or raw response in the receipt artifact. A prompt hash maps each receipt group to its selected location. Unknown fields remain unknown rather than being defaulted.

4. **Count D1 budget at the existing cartographer boundary.** One reserved injected-client invocation consumes one of the existing 60 D1 slots, including a failed invocation or explicit retry. Router-internal transport attempts and fallbacks remain separate receipt events attached to that invocation; the adapter adds no retry or fallback policy. This preserves SP1's durable ledger semantics while making every observed router attempt auditable.

5. **Select against authored area types and bind exact source bytes.** For each fixed module, the selector enumerates `modules/<slug>/areas/*_BU.json` in sorted filename order, reads each file's literal `areaType`, and groups that file's `locations[].locationId` entries under that type. Duplicate location IDs across area files within a module cause refusal. It sorts area-type keys and location IDs lexically, then cycles through the type groups, taking the next location from each non-exhausted group until that module's fixed quota is met; when a module has only one area type, that type supplies the entire quota. It does not map values into an invented interior/outdoor taxonomy. Each selected location is bound to its exact `_BU.json` source path and that file's SHA-256. Missing types or insufficient quota fail closed. The selection record captures the current repository commit and per-location source paths/hashes, is created atomically at `d1/<run-id>/selection.json`, and is never overwritten. The D1 CLI rechecks source hashes before constructing the live client; an unrelated HEAD change alone does not invalidate unchanged source bytes.

6. **Preflight D1 before constructing the live client.** `run_d1` requires the run-local selection record, checks run-id/path containment, selection identity, current source hashes, and remaining durable call budget first. Only after those checks does it construct the router adapter and call `run_cartographer` with output root `tmp/router-rollout/mapping-pilot/d1/<run-id>/`. The cartographer ledger/audit remain the canonical attempt results; the adapter's receipt ledger is keyed by location and invocation. No artifact writer targets `modules/`.

7. **Expose D1 sightline claims without expanding the layout schema.** The D1 review packet SHALL include existing feature position and exit-side claims, plus explicit feature visibility/perceivability or sightline claims when present in proposal data. It SHALL leave absent claims absent and owner fields blank. The simpler alternative of adding a new required sightline response schema is rejected because the approved scope requires auditing claims, not changing the model-output contract.

8. **Build M1 packets only from frozen fixtures and validated D1 layouts.** The generator verifies the preregistration manifest, uses the existing fixture/projection and `render_m1_sketch` paths, and renders the four fixtures in preregistered order. It renders both party placement variants for the combat fixture and no invented P1/P4 viewpoint variants for the other fixtures. It adds only D1 proposals with validated status. It writes deterministic sketch data, a run manifest with input/artifact hashes, and a Markdown rating sheet with one blank pair of legibility/usefulness cells per sketch. The sheet states the 3.5 thresholds and partial blinding; it contains no model/provider metadata or fixture answer key.

9. **Keep final execution orchestrator-owned.** First run the provider-free offline tests, ASCII compliance, strict OpenSpec validation, and a boundary diff. Only the primary/orchestrator then runs the live D1 pass through the selection-gated CLI and generates the M1 run packet from its validated layouts. Builders and tests make no provider calls. The single SP4 owner sitting batches D1 audits and M1 ratings with the SP3 live-transcript ratings; these owner judgments do not gate completion of this tooling change.

### Guidance Layer (SHOULD)

- The selector SHOULD use only the raw `areaType` strings present in source records and report the selected counts by type in `selection.json` for human audit.
- The router adapter SHOULD persist receipt records with the D1 run artifacts immediately after each injected invocation and preserve router errors without copying credentials or raw prompt/response text into receipt metadata.
- The M1 packet SHOULD use stable sketch IDs derived from fixture/location and viewpoint, and should not overwrite an existing run directory or preregistration/historical evidence.
- The M1 renderer SHOULD reuse the existing party/viewpoint knowledge filter and projection so hidden or unperceived facts are not added to sketches.
- D1 and M1 evidence SHOULD retain run identity and source provenance, and remain separate from prompt-only and SP3 live-matrix evidence.

## Risks / Trade-offs

- **Module source bytes change between selection and D1 execution** -> the CLI rehashes every selected source before any provider call and refuses a stale selection; the next selection records a new commit and hashes.
- **Provider outage or quota failure during a D1 invocation** -> rely only on existing router behavior, preserve its receipt/error and consume the reserved cartographer slot; an explicit retry can use only the same selection and remaining D1 budget.
- **A D1 proposal does not validate** -> retain its audit evidence, but omit it from M1 sketches; the tool does not repair or infer a layout to fill the set.

No production migration or rollback is needed. Run artifacts are retained as evidence under their unique run IDs; no task archives or deletes them. There are no open questions that change the approved scope or acceptance criteria.
