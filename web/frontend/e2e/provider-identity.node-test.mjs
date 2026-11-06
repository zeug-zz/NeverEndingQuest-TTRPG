// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { extractProviderIdentity } from "./provider-identity.mjs";
import { readWorkspaceIdentity } from "./workspace-identity.mjs";

const RUN = {
  run_id: "n2-synthetic-run",
  started_at_utc: "2026-11-06T10:00:00.000Z",
  finished_at_utc: "2026-11-06T10:30:00.000Z",
};

test("provider identity joins sandbox response and trace receipts without double-counting", () => {
  const result = extractProviderIdentity(RUN, {
    telemetryRecords: [{
      timestamp: "2026-11-06T10:05:00.000Z",
      context: {
        call_id: "call-1",
        attempt_id: "attempt-1",
        attempt_number: 1,
        provider: "openrouter",
        resolved_model: "provider/model-1",
      },
    }],
    traceRecords: [{
      event_type: "provider",
      recorded_at_ms: Date.parse("2026-11-06T10:05:00.000Z"),
      call_id: "call-1",
      attempt_id: "attempt-1",
      attempt_number: 1,
      provider: "openrouter",
      resolved_model: "provider/model-1",
      outcome: "response",
    }],
  });

  assert.equal(result.status, "observed");
  assert.equal(result.provider_attempt_count, "unknown");
  assert.equal(result.observed_provider_attempt_count, 1);
  assert.equal(result.response_receipt_count, 1);
  assert.deepEqual(result.providers, ["openrouter"]);
  assert.deepEqual(result.resolved_models, ["provider/model-1"]);
  assert.deepEqual(result.attempts[0].sources, ["telemetry", "trace"]);
  assert.equal(result.attempts[0].attempt_number, 1);
  assert.equal(result.provider_attempt_count_completeness, "not_proven");
  assert.equal(result.provider_attempt_count_reason.includes("not a guaranteed total"), true);
});

test("provider identity preserves unknown provider/model with an explicit reason", () => {
  const result = extractProviderIdentity(RUN, {
    telemetryRecords: [{
      timestamp: "2026-11-06T10:06:00.000Z",
      context: { attempt_id: "attempt-unknown", provider: "unknown", resolved_model: null },
    }],
  });

  assert.equal(result.status, "partial");
  assert.equal(result.provider_attempt_count, "unknown");
  assert.equal(result.observed_provider_attempt_count, 1);
  assert.deepEqual(result.providers, ["unknown"]);
  assert.deepEqual(result.resolved_models, ["unknown"]);
  assert.match(result.attempts[0].identity_reason, /missing_or_conflicting/);
  assert.match(result.provider_attempt_count_reason, /not a guaranteed total/);
});

test("provider identity retains trace-only transport errors without claiming complete count", () => {
  const result = extractProviderIdentity(RUN, {
    traceRecords: [{
      event_type: "provider",
      recorded_at_ms: Date.parse("2026-11-06T10:07:00.000Z"),
      call_id: "call-error",
      attempt_id: "attempt-error",
      attempt_number: 2,
      provider: "openrouter",
      resolved_model: "provider/model-2",
      outcome: "transport_error",
    }],
  });

  assert.equal(result.provider_attempt_count, "unknown");
  assert.equal(result.observed_provider_attempt_count, 1);
  assert.equal(result.response_receipt_count, 0);
  assert.equal(result.observed_transport_error_attempt_count, 1);
  assert.equal(result.attempts[0].attempt_number, 2);
  assert.equal(result.attempts[0].outcome, "transport_error");
});

test("provider records outside run.json window do not contribute or imply zero calls", () => {
  const result = extractProviderIdentity(RUN, {
    telemetryRecords: [
      {
        timestamp: "2026-11-06T09:59:59.999Z",
        context: { attempt_id: "before", provider: "openrouter", resolved_model: "provider/model-1" },
      },
      {
        timestamp: "2026-11-06T10:30:00.001Z",
        context: { attempt_id: "after", provider: "openrouter", resolved_model: "provider/model-1" },
      },
    ],
    traceRecords: [{
      event_type: "provider",
      recorded_at_ms: Date.parse("2026-11-06T10:30:00.001Z"),
      attempt_id: "after-trace",
      provider: "openrouter",
      resolved_model: "provider/model-1",
      outcome: "response",
    }],
  });

  assert.equal(result.status, "unknown");
  assert.equal(result.provider_attempt_count, "unknown");
  assert.equal(result.observed_provider_attempt_count, 0);
  assert.equal(result.out_of_window_provider_records, 3);
  assert.match(result.reason, /unknown, not evidence of zero/);
});

test("provider identity does not report zero observations when the run window is invalid", () => {
  const result = extractProviderIdentity({ run_id: "invalid-window" }, {
    telemetryRecords: [{
      timestamp: "2026-11-06T10:05:00.000Z",
      context: { attempt_id: "attempt-unscoped", provider: "openrouter", resolved_model: "provider/model-1" },
    }],
  });

  assert.equal(result.status, "unknown");
  assert.equal(result.provider_attempt_count, "unknown");
  assert.equal(result.observed_provider_attempt_count, "unknown");
  assert.equal(result.response_receipt_count, "unknown");
  assert.equal(result.observed_transport_error_attempt_count, "unknown");
  assert.equal(result.provider_attempt_count_completeness, "unknown");
  assert.match(result.provider_attempt_count_reason, /valid run start and finish/);
});

test("workspace identity records a clean/dirty flag and fails closed when git status is unavailable", () => {
  const sha = "a".repeat(40);
  const clean = readWorkspaceIdentity("/repo", (_command, args) =>
    args[0] === "rev-parse" ? `${sha}\n` : "",
  );
  const dirty = readWorkspaceIdentity("/repo", (_command, args) =>
    args[0] === "rev-parse" ? `${sha}\n` : " M web/frontend/e2e/n2-gate.mjs\n",
  );
  const unknown = readWorkspaceIdentity("/repo", () => {
    throw new Error("git unavailable");
  });

  assert.deepEqual(clean, {
    git_sha: sha,
    git_worktree_state: "clean",
    git_worktree_clean: true,
  });
  assert.equal(dirty.git_worktree_state, "dirty");
  assert.equal(dirty.git_worktree_clean, false);
  assert.equal(unknown.git_worktree_state, "unknown");
  assert.equal(unknown.git_worktree_clean, false);
});
