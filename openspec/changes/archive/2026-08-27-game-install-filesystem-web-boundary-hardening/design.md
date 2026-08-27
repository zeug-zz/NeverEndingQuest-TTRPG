## Context

See `proposal.md` for the motivation and requested scope. The current application has several host-file and route surfaces that use relative paths, untrusted path segments, or broad network defaults. Existing launchers normally set the repository as the working directory, but direct/manual starts and web callbacks can bypass that assumption.

The implementation must preserve single-player and TABLETOP MODE behavior, existing media lookup order, configured port behavior, provider fallback, and optional LAN deployment. It must not introduce an OS-account sandbox.

## Goals / Non-Goals

**Goals:**

- Establish one canonical repository root for application-owned runtime paths.
- Provide shared resolved-path containment and symlink rejection for file-serving and database targets.
- Make local-only web serving the safe default while retaining explicit operator configuration for LAN use.
- Make raw LM Studio request/response capture opt-in and root-relative.
- Keep error responses bounded and avoid exposing host filesystem paths unnecessarily.

**Non-Goals:**

- OS-level privilege reduction, service accounts, containers, or filesystem ACL changes.
- Provider routing, model selection, prompt, retry, or response-shape redesign.
- General repository-wide conversion of every historical script path that is not reachable from the installed game entrypoints.

## Decisions

### 1. Canonical root and path policy

Add a small provider-free path utility deriving the repository root from a file location, not from `os.getcwd()`. It will offer normalized repository-relative resolution and containment checks with explicit options for rejecting absolute input, traversal, and symlink components. Runtime entrypoints will resolve their required directories from this root; the web update handler will always use this root as its Git working directory.

A global process `chdir` is not the primary boundary because it can surprise embedders and tests. The launcher paths and high-risk web/runtime surfaces will use explicit rooted paths, while launch scripts will continue to `cd` to the installation directory for legacy compatibility.

### 2. Database target containment

The world-narrative ingest route will resolve omitted or valid relative database targets beneath the repository `data/` directory and require a `.db` suffix. It will reject absolute paths, traversal components, symlinked components, and targets outside that directory before opening SQLite. The ingest service remains responsible for SQL/schema behavior; the route owns path authorization.

This preserves the existing default `data/memory.db` target and prevents the request body from selecting an arbitrary OS-user database path.

### 3. Media containment

All static and module media routes will use resolved-path containment against their intended roots before calling `send_file`. The existing media type allowlist, module-first lookup order, fallback behavior, and supported extensions remain unchanged. A path that is unsafe, missing, or symlinked will return the existing not-found style response without revealing the resolved host path.

A shared helper is preferred over framework-specific behavior so the same policy covers video, icon, portrait, and module media routes.

### 4. Web boundary defaults

Add a configuration-backed `WEB_HOST` with `127.0.0.1` as the default and fail-closed fallback for blank or invalid values. Keep `WEB_PORT` unchanged. Replace wildcard Socket.IO CORS as the default with loopback origins; non-loopback use requires an explicit allowed-origin configuration. This prevents a normal install from listening on the LAN or accepting arbitrary browser origins while preserving deliberate deployment configuration.

The change does not add authentication because the selected user requirement is local binding by default, not a new account/session system.

### 5. LM Studio capture

`lmstudio_forwarder.py` will read a clearly named opt-in environment variable for payload capture. Missing, blank, or invalid values disable capture. When disabled, no request or response body/header capture files are created; normal forwarding and concise console status remain available. When enabled, capture remains compatible with the existing JSONL workflow and is rooted relative to the forwarder file rather than the caller's current directory.

### 6. Compatibility and error handling

Path rejection returns bounded client-facing errors and logs only safe relative identifiers. Existing provider and application errors continue through their existing paths. Configuration parsing is fail-safe: unsafe or malformed host/CORS/capture settings use safe defaults rather than preventing startup.

## Risks / Trade-offs

- [Risk] Existing users relying on LAN access without configuration will lose access after upgrade. -> [Mitigation] Document `WEB_HOST` and explicit CORS configuration in the template and setup documentation.
- [Risk] Strict symlink rejection can reject a deliberately linked media or database file. -> [Mitigation] Preserve direct regular-file behavior and require operators to place approved files inside the installation roots.
- [Risk] Absolute paths in old world-narrative API clients will be rejected. -> [Mitigation] The upload route returns repository-relative paths and the supported default remains unchanged.
- [Risk] Rooted paths may reveal latent current-directory assumptions. -> [Mitigation] Apply the helper to entrypoints and high-risk web surfaces first, with alternate-CWD regression tests.
- [Risk] Opt-in LM Studio capture reduces default diagnostics. -> [Mitigation] Preserve explicit opt-in and document the sensitivity of captured payloads.

## Migration Plan

1. Add the root and containment helpers plus provider-free tests.
2. Harden world-narrative database targets and media routes.
3. Add safe web host/CORS configuration and update entrypoint path resolution.
4. Change LM Studio capture to opt-in and root-relative output.
5. Run focused security tests, existing provider/logging regressions, syntax checks, and strict OpenSpec validation.
6. Rollback is a code/config rollback: restore the prior route/server/forwarder behavior. No data migration is required. Existing repository-local databases, media, uploads, and saves remain in place.

## Open Questions

None. LAN host/origin configuration and LM Studio capture are explicit operator opt-ins defined by this change.
