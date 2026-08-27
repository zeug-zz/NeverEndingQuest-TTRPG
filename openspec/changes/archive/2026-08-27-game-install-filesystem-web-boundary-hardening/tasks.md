## 1. Shared Boundary Foundation

- [x] 1.1 Add the canonical repository-root and resolved-path containment helpers, including traversal and symlink-component checks, and verify them with provider-free unit tests covering normal, alternate-CWD, absolute, traversal, missing-target, and symlink cases.
- [x] 1.2 Add a repository-local database-target resolver for world-narrative ingestion and wire the endpoint to reject unsafe `db_path` values before SQLite connection; verify default/local acceptance, outside-path rejection, symlink rejection, bounded errors, and no-ingest-on-rejection behavior.
- [x] 1.3 Harden video, icon, portrait, and module-media serving with resolved containment checks while preserving safe lookup order and allowlists; verify safe-file serving, static fallback, traversal rejection, absolute-path rejection, symlink rejection, and no `send_file` call for unsafe paths.

## 2. Installed Web and Runtime Boundaries

- [x] 2.1 Add safe `WEB_HOST` and Socket.IO origin configuration with loopback defaults and explicit validated overrides; verify missing, invalid, local, and deliberate LAN configurations without changing the configured port.
- [x] 2.2 Anchor `run_web.py`, `launch_toolkit.py`, relevant web upload/runtime roots, and the in-app update working directory to the installation repository root; verify startup and update path behavior from an alternate current directory while preserving normal launcher behavior.
- [x] 2.3 Make LM Studio payload capture explicitly opt-in, default invalid values to disabled, and root enabled capture relative to the forwarder location; verify disabled forwarding creates no payload logs and enabled alternate-CWD capture remains project-local.

## 3. Documentation and Regression Gate

- [x] 3.1 Update configuration/setup documentation for localhost defaults, explicit LAN host/origin overrides, and opt-in LM Studio capture; verify templates and docs do not instruct wildcard CORS or enabled-by-default payload logging.
- [x] 3.2 Add or extend provider-free regression coverage for all five boundaries and run focused security, provider-log, adaptation-safety, syntax, and existing web/runtime tests; verify no provider request/model/retry behavior changes.
- [x] 3.3 Review the complete worktree diff against the proposal, design, and all five delta specs, then run `openspec validate game-install-filesystem-web-boundary-hardening --strict` and record the final verification results.
