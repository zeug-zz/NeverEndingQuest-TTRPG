# Executor Prompts

## Builder Prompt

Implement `toolkit-mmg-final-media-authority` by adding a versioned `module_media_generator_report.json` final media audit for Module Media Generator completion, wiring MMG completion to write it, and updating Module Builder sidebar metadata so this report is the final authority for `media_generator_needed` only. Preserve `toolkit_build_report.json` authority for semantic/build failures, do not count static fallback media as module-complete, and add focused regression coverage for stale media debt suppression, MMG fail handoff, malformed report fallback, and non-media failure preservation.

## Verification Prompt

Verify that MMG final pass reports suppress stale `Needs Module Media Generator` sidebar state, MMG fail reports surface missing-media handoff, malformed/non-authoritative MMG reports fall back safely, semantic/build failures remain visible, modified Python files compile, targeted regressions pass, and `openspec validate toolkit-mmg-final-media-authority` is valid.
