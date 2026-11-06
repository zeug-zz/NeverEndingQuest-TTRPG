// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  existsSync,
  lstatSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const TMP_ROOT = resolve(REPOSITORY_ROOT, "tmp");
const MAX_SOURCE_BYTES = 64 * 1024 * 1024;
const TELEMETRY_PATH = "telemetry_log.jsonl";
const TRACE_PATH = join("debug", "combat_turn_trace.jsonl");

function isContained(parent, candidate) {
  const path = relative(parent, candidate);
  return path !== "" && path !== "." && path !== ".." &&
    !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function assertNoSymlinkComponents(parent, candidate) {
  if (!isContained(parent, candidate)) {
    throw new Error("Provider identity paths must remain below their approved root.");
  }
  let current = parent;
  if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
    throw new Error("Provider identity paths must not traverse symlinks.");
  }
  for (const component of relative(parent, candidate).split(sep)) {
    current = join(current, component);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
      throw new Error("Provider identity paths must not traverse symlinks.");
    }
  }
}

function resolveEvidenceDirectory(value) {
  const candidate = resolve(isAbsolute(value) ? value : join(REPOSITORY_ROOT, value));
  assertNoSymlinkComponents(TMP_ROOT, candidate);
  if (!existsSync(candidate) || !lstatSync(candidate).isDirectory()) {
    throw new Error("The evidence directory must already exist below repository tmp/.");
  }
  return candidate;
}

function readJsonLines(path, relativePath) {
  if (!existsSync(path)) {
    return {
      records: [],
      report: { path: relativePath, available: false, records_read: 0, malformed_records: 0, reason: "not_found" },
    };
  }
  const entry = lstatSync(path);
  if (!entry.isFile() || entry.isSymbolicLink()) {
    return {
      records: [],
      report: { path: relativePath, available: true, records_read: 0, malformed_records: 0, reason: "not_a_regular_file" },
    };
  }
  if (entry.size > MAX_SOURCE_BYTES) {
    return {
      records: [],
      report: { path: relativePath, available: true, records_read: 0, malformed_records: 0, reason: "source_exceeds_size_limit" },
    };
  }
  const records = [];
  let malformed = 0;
  for (const line of readFileSync(path, "utf8").split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      records.push(JSON.parse(line));
    } catch {
      malformed += 1;
    }
  }
  return {
    records,
    report: {
      path: relativePath,
      available: true,
      records_read: records.length,
      malformed_records: malformed,
      reason: malformed === 0 ? null : "malformed_json_lines_skipped",
    },
  };
}

function parseWindow(runRecord) {
  const start = Date.parse(runRecord?.started_at_utc ?? "");
  const end = Date.parse(runRecord?.finished_at_utc ?? "");
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return null;
  return { start, end };
}

function recordTimestamp(record, source) {
  if (source === "trace" && Number.isSafeInteger(record?.recorded_at_ms)) {
    return record.recorded_at_ms;
  }
  const value = record?.timestamp ?? record?.recorded_at_utc ?? record?.recorded_at;
  if (typeof value !== "string") return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function knownString(value) {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return normalized && normalized.toLowerCase() !== "unknown" ? normalized : null;
}

function addField(attempt, key, value) {
  const normalized = knownString(value);
  if (normalized !== null) attempt[key].add(normalized);
}

function addAttempt(attempts, { attemptId, callId, timestamp, provider, upstreamProvider, model, outcome, source, attemptNumber }) {
  let attempt = attempts.get(attemptId);
  if (!attempt) {
    attempt = {
      attemptId,
      callIds: new Set(),
      timestamps: new Set(),
      providers: new Set(),
      upstreamProviders: new Set(),
      models: new Set(),
      outcomes: new Set(),
      sources: new Set(),
      attemptNumbers: new Set(),
    };
    attempts.set(attemptId, attempt);
  }
  addField(attempt, "callIds", callId);
  if (Number.isFinite(timestamp)) attempt.timestamps.add(timestamp);
  addField(attempt, "providers", provider);
  addField(attempt, "upstreamProviders", upstreamProvider);
  addField(attempt, "models", model);
  addField(attempt, "outcomes", outcome);
  attempt.sources.add(source);
  if (Number.isSafeInteger(attemptNumber)) attempt.attemptNumbers.add(attemptNumber);
}

function oneOrUnknown(values) {
  return values.size === 1 ? [...values][0] : "unknown";
}

function sortedUnique(values) {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

export function extractProviderIdentity(runRecord, {
  telemetryRecords = [],
  traceRecords = [],
  sourceReports = [],
} = {}) {
  const runWindow = parseWindow(runRecord);
  if (runWindow === null) {
    return {
      schema_version: 1,
      run_id: knownString(runRecord?.run_id) ?? "unknown",
      status: "unknown",
      reason: "run_window_missing_or_invalid",
      run_window: {
        started_at_utc: runRecord?.started_at_utc ?? "unknown",
        finished_at_utc: runRecord?.finished_at_utc ?? "unknown",
      },
      provider_attempt_count: "unknown",
      observed_provider_attempt_count: "unknown",
      provider_attempt_count_completeness: "unknown",
      provider_attempt_count_reason: "A valid run start and finish are required to scope runtime records.",
      response_receipt_count: "unknown",
      observed_transport_error_attempt_count: "unknown",
      providers: ["unknown"],
      resolved_models: ["unknown"],
      provider_identity_completeness: "unknown",
      provider_identity_reason: "A valid run start and finish are required to scope runtime records.",
      out_of_window_provider_records: "unknown",
      untimestamped_provider_records: "unknown",
      unbound_provider_records: "unknown",
      attempts: [],
      sources: sourceReports,
    };
  }

  const attempts = new Map();
  let outOfWindowRecords = 0;
  let untimestampedRecords = 0;
  let unboundAttemptRecords = 0;

  const addTimestamped = (record, source) => {
    if (record === null || typeof record !== "object" || Array.isArray(record)) return;
    if (source === "telemetry" && record.type === "spike_detected") return;
    if (source === "trace" && record.event_type !== "provider") return;

    const timestamp = recordTimestamp(record, source);
    if (timestamp === null) {
      untimestampedRecords += 1;
      return;
    }
    if (timestamp < runWindow.start || timestamp > runWindow.end) {
      outOfWindowRecords += 1;
      return;
    }

    if (source === "telemetry") {
      const context = record.context;
      if (context === null || typeof context !== "object" || Array.isArray(context) ||
          typeof context.attempt_id !== "string" || !context.attempt_id) {
        unboundAttemptRecords += 1;
        return;
      }
      addAttempt(attempts, {
        attemptId: context.attempt_id,
        callId: context.call_id,
        timestamp,
        provider: context.provider,
        upstreamProvider: context.observed_upstream_provider,
        model: context.resolved_model,
        outcome: "response",
        source,
        attemptNumber: context.attempt_number,
      });
      return;
    }

    if (typeof record.attempt_id !== "string" || !record.attempt_id ||
        !["response", "transport_error"].includes(record.outcome)) {
      unboundAttemptRecords += 1;
      return;
    }
    addAttempt(attempts, {
      attemptId: record.attempt_id,
      callId: record.call_id,
      timestamp,
      provider: record.provider,
      upstreamProvider: record.observed_upstream_provider,
      model: record.resolved_model ?? record.model,
      outcome: record.outcome,
      source,
      attemptNumber: record.attempt_number,
    });
  };

  for (const record of telemetryRecords) addTimestamped(record, "telemetry");
  for (const record of traceRecords) addTimestamped(record, "trace");

  const attemptRows = [...attempts.values()]
    .map((attempt) => ({
      call_id: oneOrUnknown(attempt.callIds),
      attempt_id: attempt.attemptId,
      attempt_number: oneOrUnknown(attempt.attemptNumbers),
      recorded_at_utc: attempt.timestamps.size === 0
        ? "unknown"
        : new Date(Math.min(...attempt.timestamps)).toISOString(),
      provider: oneOrUnknown(attempt.providers),
      observed_upstream_provider: oneOrUnknown(attempt.upstreamProviders),
      resolved_model: oneOrUnknown(attempt.models),
      outcome: oneOrUnknown(attempt.outcomes),
      sources: [...attempt.sources].sort(),
      identity_reason: attempt.providers.size !== 1 || attempt.models.size !== 1
        ? "provider_or_resolved_model_missing_or_conflicting_in_runtime_receipts"
        : null,
    }))
    .sort((a, b) => a.recorded_at_utc.localeCompare(b.recorded_at_utc) || a.attempt_id.localeCompare(b.attempt_id));
  const observedCount = attemptRows.length;
  const unknownIdentityCount = attemptRows.filter((row) => row.provider === "unknown" || row.resolved_model === "unknown").length;
  const providers = sortedUnique(attemptRows.map((row) => row.provider));
  const models = sortedUnique(attemptRows.map((row) => row.resolved_model));
  if (observedCount === 0) {
    providers.push("unknown");
    models.push("unknown");
  }
  const responseCount = attemptRows.filter((row) => row.sources.includes("telemetry")).length;
  const transportErrorCount = attemptRows.filter((row) => row.outcome === "transport_error").length;
  const sourceCoverageReason = "The usage tracker records response receipts; the runtime provider trace is opt-in and only covers traced call sites. This observed count is not a guaranteed total, and missing attempts remain unknown.";
  const noAttemptReason = "No timestamped router attempt IDs were found inside the run window; this is unknown, not evidence of zero provider calls.";

  return {
    schema_version: 1,
    run_id: knownString(runRecord?.run_id) ?? "unknown",
    status: observedCount === 0 ? "unknown" : unknownIdentityCount === 0 ? "observed" : "partial",
    reason: observedCount === 0
      ? noAttemptReason
      : unknownIdentityCount > 0
        ? "One or more observed attempts lack an unambiguous provider or resolved model."
        : "Provider and model values describe observed records only; source coverage is not proven.",
    run_window: {
      started_at_utc: runRecord.started_at_utc,
      finished_at_utc: runRecord.finished_at_utc,
    },
    provider_attempt_count: "unknown",
    observed_provider_attempt_count: observedCount,
    provider_attempt_count_completeness: observedCount === 0 ? "unknown" : "not_proven",
    provider_attempt_count_reason: observedCount === 0 ? noAttemptReason : sourceCoverageReason,
    response_receipt_count: responseCount,
    observed_transport_error_attempt_count: transportErrorCount,
    providers,
    resolved_models: models,
    provider_identity_completeness: observedCount === 0 ? "unknown" : "not_proven",
    provider_identity_reason: observedCount === 0 ? noAttemptReason : sourceCoverageReason,
    out_of_window_provider_records: outOfWindowRecords,
    untimestamped_provider_records: untimestampedRecords,
    unbound_provider_records: unboundAttemptRecords,
    attempts: attemptRows,
    sources: sourceReports,
  };
}

function parseArguments(argv) {
  let evidenceDirectory = null;
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--help" || token === "-h") {
      console.log("Usage: node web/frontend/e2e/provider-identity.mjs --evidence-dir tmp/router-rollout/v2-network/n2-<run-id>");
      process.exit(0);
    }
    if (token === "--evidence-dir" && argv[index + 1]) {
      evidenceDirectory = argv[index + 1];
      index += 1;
      continue;
    }
    throw new Error(`Unknown or incomplete option: ${token}`);
  }
  if (!evidenceDirectory) throw new Error("--evidence-dir is required.");
  return evidenceDirectory;
}

function readSandboxSource(sandboxRoot, relativePath) {
  const path = join(sandboxRoot, relativePath);
  assertNoSymlinkComponents(sandboxRoot, path);
  return readJsonLines(path, join("tmp", "combat_capture", relativePath).split(sep).join("/"));
}

function writeProviderIdentity(evidenceDirectory, payload) {
  const output = join(evidenceDirectory, "provider-identity.json");
  const temporary = `${output}.pending`;
  if (existsSync(output) || existsSync(temporary)) {
    throw new Error("Refusing to overwrite provider-identity evidence.");
  }
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
  renameSync(temporary, output);
  return output;
}

function main(argv) {
  const evidenceDirectory = resolveEvidenceDirectory(parseArguments(argv));
  const runPath = join(evidenceDirectory, "run.json");
  if (!existsSync(runPath) || !lstatSync(runPath).isFile() || lstatSync(runPath).isSymbolicLink()) {
    throw new Error("A regular run.json is required in the evidence directory.");
  }
  const runRecord = JSON.parse(readFileSync(runPath, "utf8"));
  const sandboxRoot = join(TMP_ROOT, "combat_capture");
  const sandboxExists = existsSync(sandboxRoot) && lstatSync(sandboxRoot).isDirectory() && !lstatSync(sandboxRoot).isSymbolicLink();
  let telemetry = { records: [], report: { path: "tmp/combat_capture/telemetry_log.jsonl", available: false, records_read: 0, malformed_records: 0, reason: "sandbox_root_missing" } };
  let trace = { records: [], report: { path: "tmp/combat_capture/debug/combat_turn_trace.jsonl", available: false, records_read: 0, malformed_records: 0, reason: "sandbox_root_missing" } };
  if (sandboxExists) {
    assertNoSymlinkComponents(TMP_ROOT, sandboxRoot);
    telemetry = readSandboxSource(sandboxRoot, TELEMETRY_PATH);
    trace = readSandboxSource(sandboxRoot, TRACE_PATH);
  }
  const payload = extractProviderIdentity(runRecord, {
    telemetryRecords: telemetry.records,
    traceRecords: trace.records,
    sourceReports: [telemetry.report, trace.report],
  });
  const output = writeProviderIdentity(evidenceDirectory, payload);
  console.log(JSON.stringify({
    output: relative(REPOSITORY_ROOT, output).split(sep).join("/"),
    status: payload.status,
    provider_attempt_count: payload.provider_attempt_count,
    providers: payload.providers,
    resolved_models: payload.resolved_models,
    reason: payload.reason,
  }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(`Provider identity extraction failed: ${error instanceof Error ? error.message : "unknown error"}`);
    process.exitCode = 2;
  }
}
