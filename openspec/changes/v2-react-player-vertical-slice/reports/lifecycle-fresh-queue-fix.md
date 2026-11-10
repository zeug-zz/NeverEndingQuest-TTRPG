# Lifecycle fresh-queue harness fix

The `server-instance-change` lifecycle scenario now stops and restarts its managed host before creating routes or pages. `SandboxHostManager.stop()` is safe while running and idempotent when already stopped (`managed-host.mjs:379-412`); `start()` requires `child === null` (`managed-host.mjs:295-301`), which the stop fulfills. The restart creates an empty process-local runtime queue while the disk-backed transcript remains available.

## Remaining lifecycle path audit

- `server-instance-change`: accepted receipt is held at `managed-lifecycle.mjs:417-424` (fresh instance; queue must be empty). Stop/disconnect and uncertain-action notice at `433-446` depend on the running fresh instance. Restart/resynchronization and new instance ID at `453-473` depend on fresh-instance identity and persisted party state. Draft clearing and single request-ID submission at `475-482` check client-local state. Transcript marker retention at `483-489` depends on cross-process persisted transcript state. Host UI and screenshots at `490-503` depend on the restarted host.
- `missing-bundle`: the next bundle scenario runs after server-instance-change through the fail-fast sequence (`managed-lifecycle.mjs:776-816`); it stops the host, verifies/moves the bundle, then starts host-only at `569-584`. It depends on the shared sandbox bundle and recovery evidence, not the prior in-memory queue or server instance.
- `broken-bundle`: same bundle path at `569-584`, with corruption after backup (`576-579`); it depends on the recovered shared bundle and the preceding missing-bundle restoration, not on fresh-instance or cross-scenario runtime queue state.

Coverage observation (unchanged): in Chrome-only mode, `busy-input` passes with accepted filler transcript count 0 because the queue was already full.

Evidence for the cause (primary): run p1-hostui-20261110T102637Z-d29c1453 scenarios.jsonl: repeated-request-id observed pending_queue_item true; busy-input observed accepted_filler_transcript_count 0. Admission returns busy when qsize >= MAX_PENDING_RUNTIME_INPUTS (1), so the queue stayed full; queue semantics are correct and unchanged.

Primary verification (software only): Node 96/96; typecheck passed; strict OpenSpec valid; ASCII 910/0; git diff --check clean. A provider-free lifecycle-only run was not assembled: loading the managed host UI dispatches the missing-portrait image call, so zero provider dispatch cannot be guaranteed. Ruling neq-n2-lifecycle-receipt-diagnose-20261110. No live rerun/CI/merge claimed; task 6.2 open.
