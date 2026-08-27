# Proposal: Game Install Filesystem and Web Boundary Hardening

## Why

The installed game correctly keeps remote LLM providers outside the local filesystem, but the local Python process currently has several broad file and network boundaries. In particular, a world-narrative endpoint accepts an unrestricted SQLite path, media routes construct `send_file` paths from untrusted path segments, the web server listens on all interfaces, LM Studio proxy capture is enabled by default, and relative paths depend on the process working directory.

This change closes those concrete exposure paths without adding OS-account isolation or changing the LLM/provider architecture.

## Objective

Make the normal Windows and macOS game installations safer by enforcing approved local storage roots, preventing media path traversal, limiting the web service to local access by default, disabling raw LM Studio payload capture by default, and resolving application-relative paths from the repository root rather than the caller's working directory.

## What Changes

- Restrict world-narrative database ingestion to approved repository-local database paths and reject traversal, absolute paths, symlinks, and unsupported database targets.
- Harden video, icon, portrait, and module-media serving with resolved-path containment checks before `send_file`.
- Change the default web bind address to localhost while preserving an explicit configuration escape hatch for deliberate LAN use; retain the existing configured port and Socket.IO behavior.
- Make LM Studio forwarder payload capture opt-in, preserving diagnostics without writing prompt, response, or credential payloads by default.
- Introduce a canonical repository-root path helper and use it for application-owned relative paths, including launcher-independent runtime paths and update working-directory resolution.
- Add provider-free regression coverage for path rejection, media containment, bind defaults, capture defaults, and alternate-current-working-directory behavior.

## Non-Goals

- Do not implement restricted OS-user or service-account isolation.
- Do not redesign provider routing, model selection, prompt contents, or LLM action contracts.
- Do not remove the optional explicit LAN/server deployment escape hatch.
- Do not migrate existing user data or move the Windows repair-backup or macOS application locations.
- Do not make LM Studio itself sandboxed; this change only controls the NeverEndingQuest forwarder behavior.

## Risks and Mitigations

- Local-only binding may surprise users who intentionally connect from another device. Mitigation: provide a clearly documented configuration override and test both default and override behavior.
- Path canonicalization may reject legacy custom paths. Mitigation: preserve repository-local canonical paths and return bounded actionable errors rather than silently redirecting writes.
- Root anchoring can expose latent assumptions about the current working directory. Mitigation: centralize resolution, preserve existing relative path strings at API boundaries where practical, and add alternate-CWD tests.
- Disabling LM Studio capture may reduce debugging detail. Mitigation: support an explicit opt-in environment/configuration switch and document that captured files can contain sensitive prompts and responses.
- Media containment changes could alter legacy filename behavior. Mitigation: retain allowed media types and filenames while rejecting only paths that resolve outside their intended roots.

## Fallback Strategy

All new guards fail closed for unsafe paths and fail open only for optional diagnostics. Existing repository-local defaults remain usable. If the configured bind override is invalid, the server SHALL use localhost. If LM Studio capture configuration is absent or invalid, capture SHALL remain disabled. Existing provider fallback, retry, and model behavior remain unchanged.

## Merge-Safety and Compatibility

The implementation SHOULD prefer extension helpers and minimal marked hooks in host files. Single-player and TABLETOP MODE gameplay behavior, provider selection, request shapes, and runtime data schemas remain compatible. Changes to host files SHALL be marked with `# TABLETOP MODE:` where required by repository guidance. Python user-facing output SHALL remain ASCII-only.

## Capabilities

### New Capabilities

- `web-database-path-containment`
- `web-media-path-containment`
- `local-web-server-boundary`
- `lmstudio-capture-defaults`
- `install-root-path-resolution`

### Modified Capabilities

None.

## Impact

Affected surfaces include `web/routes/world_narrative_routes.py`, media routes in `web/web_interface.py`, server configuration and launch behavior, `lmstudio_forwarder.py` and its launch documentation, application path utilities and update handling, and focused security regression tests. No new third-party dependency is required.
