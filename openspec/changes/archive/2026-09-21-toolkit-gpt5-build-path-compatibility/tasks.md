## 1. Inventory And Contract Baseline

- [x] 1.1 Inventory every priority Homebrew, ModuleBuilder, generator, spatial, classification, and Markdown Chat Completions call site; record task ID, model source, timeout, and current sampling fields; verify the inventory against a repository search.
- [x] 1.2 Add provider-free contract fixtures for direct GPT-5, compatible non-GPT-5, and OpenRouter request branches; verify the fixtures capture final provider kwargs.

## 2. Normalizer And Generator Migration

- [x] 2.1 Migrate `utils/toolkit_homebrew_normalizer.py` to the shared parameter helper; verify all normalizer create calls omit unsupported GPT-5 fields and preserve task profiles.
- [x] 2.2 Migrate ModuleBuilder, ModuleGenerator, AreaGenerator, LocationGenerator, PlotGenerator, NPCBuilder, and MonsterBuilder calls; verify each in-scope call has one compatible parameter-resolution path.
- [x] 2.3 Migrate spatial, classification, and related toolkit calls that can run during build-time normalization or publication; verify provider errors retain stage identity.

## 3. Markdown And Auxiliary Callers

- [x] 3.1 Migrate `homebrewery_adventure_writer.py` and other publication-adjacent enrichment calls; verify deterministic Markdown fallback remains available when optional LLM enrichment fails.
- [x] 3.2 Remove unsupported direct `top_p` use from the in-scope GPT-5 build path; verify no priority create block emits forbidden legacy parameters.

## 4. Regression And Provider Verification

- [x] 4.1 Extend GPT-5 contract tests for builder, normalizer, generator, toolkit, and Markdown call sites; verify direct GPT-5 kwargs include reasoning/verbosity and omit unsupported sampling fields.
- [x] 4.2 Add OpenRouter regression assertions for model IDs, thinking/request fields, and compatible temperature behavior; verify no OpenRouter request-shape regression.
- [x] 4.3 Run the focused normalizer, accurate-ingest, and toolkit publication suites with `.venv/bin/python`; verify all provider-free tests pass.
- [x] 4.4 Run one bounded GPT-5.6 Luna build-call smoke using a small fixture; verify the provider accepts the request and no API credential or raw source is persisted in diagnostics.

## 5. Rollout Gate

- [x] 5.1 Record the compatibility result and enable the adaptation-builder prerequisite only after the focused suites and bounded smoke pass; verify legacy accurate-ingest remains selectable.
