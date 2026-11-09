// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  appendFileSync,
  existsSync,
  lstatSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import {
  MAX_REQUEST_DIAGNOSTIC_BYTES,
  MAX_REQUEST_DIAGNOSTIC_RECORDS,
  normalizeSocketRequestDiagnostic,
} from "./request-diagnostics.mjs";
import { normalizeSetupFailureRecord } from "./setup-evidence.mjs";

const OBSERVATION_SETUP_STAGES = new Set([
  "agent_credentials",
  "managed_host_start",
  "browser_launch",
  "browser_context_create",
  "page_create",
  "player_shell_load",
  "player_authentication",
  "player_connection_wait",
  "client_metadata",
  "setup_evidence_preflight",
  "provider_ledger_preflight",
  "unknown",
]);
const OBSERVATION_FAILURE_CATEGORIES = new Set([
  "agent_credentials_failed",
  "managed_host_start_failed",
  "browser_launch_failed",
  "browser_context_create_failed",
  "page_create_failed",
  "player_login_failed",
  "provider_ledger_reservation",
  "provider_ledger_refusal",
  "provider_ledger_inactive",
  "provider_ledger_missing",
  "provider_ledger_invalid",
  "provider_ledger_copy_failed",
  "managed_host_teardown_failed",
  "port_probe_failed",
  "request_diagnostics_write_failed",
  "diagnostic_observation_missing",
  "screenshot_failed",
  "evidence_write_failed",
  "operator_interrupted",
  "observation_timeout",
  "observation_runtime_failed",
  "host_output_evidence_failed",
]);

export function atomicJsonWrite(path, payload) {
  const temporary = `${path}.pending`;
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
  renameSync(temporary, path);
}

export function writeSetupFailureEvidenceFile(evidenceDirectory, value) {
  const safe = normalizeSetupFailureRecord(value);
  if (safe === null) throw new Error("N2 setup failure evidence is invalid.");
  atomicJsonWrite(join(evidenceDirectory, "setup-failure.json"), safe);
}

export function writeSocketRequestDiagnosticFile(evidenceDirectory, value) {
  const safe = normalizeSocketRequestDiagnostic(value);
  if (safe === null) throw new Error("N2 socket request diagnostic is invalid.");
  const path = join(evidenceDirectory, "request-diagnostics.jsonl");
  const line = `${JSON.stringify(safe)}\n`;
  const nextBytes = Buffer.byteLength(line, "utf8");
  let currentBytes = 0;
  let currentRecords = 0;
  if (existsSync(path)) {
    const stat = lstatSync(path);
    if (stat.isSymbolicLink() || !stat.isFile() || stat.size > MAX_REQUEST_DIAGNOSTIC_BYTES) {
      throw new Error("N2 socket request diagnostic evidence path or size is invalid.");
    }
    const current = readFileSync(path, "utf8");
    if (current !== "" && !current.endsWith("\n")) {
      throw new Error("N2 socket request diagnostic evidence is incomplete.");
    }
    currentBytes = Buffer.byteLength(current, "utf8");
    currentRecords = current === "" ? 0 : current.split("\n").length - 1;
  }
  if (currentRecords >= MAX_REQUEST_DIAGNOSTIC_RECORDS ||
      currentBytes + nextBytes > MAX_REQUEST_DIAGNOSTIC_BYTES) {
    throw new Error("N2 socket request diagnostic evidence exceeds its run limit.");
  }
  appendFileSync(path, line, { encoding: "utf8", flag: "a" });
}

export function writeHandshakeObservationEvidenceFile(evidenceDirectory, value) {
  const safe = normalizeHandshakeObservation(value);
  if (safe === null) throw new Error("N2 handshake observation evidence is invalid.");
  atomicJsonWrite(join(evidenceDirectory, "handshake-observation.json"), safe);
}

function normalizeHandshakeObservation(value) {
  if (!isRecord(value) || !sameKeys(Object.keys(value).sort(), [
    "schema",
    "mode",
    "n2_gate_result",
    "run_id",
    "party_size",
    "player_count",
    "browser",
    "browser_version",
    "setup",
    "request_diagnostics",
    "screenshot",
    "provider_attempt_ledger",
    "cleanup",
    "failure_categories",
    "recorded_at_utc",
  ].sort()) || value.schema !== "n2-handshake-observation.v1" ||
      value.mode !== "N2_HANDSHAKE_OBSERVATION" || value.n2_gate_result !== "NOT_N2_GATE" ||
      typeof value.run_id !== "string" || !/^n2-[A-Za-z0-9_-]{1,80}$/.test(value.run_id) ||
      value.party_size !== 1 || value.player_count !== 1 || value.browser !== "Chrome" ||
      !(value.browser_version === null || isBoundedToken(value.browser_version, 64)) ||
      !isRecord(value.setup) || !sameKeys(Object.keys(value.setup).sort(), [
        "status", "stage", "connection_state", "shell_loaded", "client_build_id", "protocol_version",
      ].sort()) || !["PASS", "FAIL", "BLOCKED"].includes(value.setup.status) ||
      !(value.setup.stage === null || OBSERVATION_SETUP_STAGES.has(value.setup.stage)) ||
      !["connected", "connecting", "disconnected", "unknown", "not_started"].includes(value.setup.connection_state) ||
      !(typeof value.setup.shell_loaded === "boolean" || value.setup.shell_loaded === "unknown") ||
      !(value.setup.client_build_id === null || isBoundedToken(value.setup.client_build_id, 128)) ||
      !(value.setup.protocol_version === null || Number.isInteger(value.setup.protocol_version)) ||
      !isRecord(value.request_diagnostics) || !sameKeys(Object.keys(value.request_diagnostics).sort(), [
        "records_written", "records_omitted", "record_write_failures", "truncated", "raw_headers_retained", "raw_urls_retained",
      ].sort()) || !boundedCounter(value.request_diagnostics.records_written, MAX_REQUEST_DIAGNOSTIC_RECORDS) ||
      !boundedCounter(value.request_diagnostics.records_omitted, 1_000_000) ||
      !boundedCounter(value.request_diagnostics.record_write_failures, 1_000_000) ||
      typeof value.request_diagnostics.truncated !== "boolean" ||
      value.request_diagnostics.raw_headers_retained !== false || value.request_diagnostics.raw_urls_retained !== false ||
      !isRecord(value.screenshot) || !sameKeys(Object.keys(value.screenshot).sort(), ["status", "path", "reason"].sort()) ||
      !["captured", "skipped", "failed", "not_attempted"].includes(value.screenshot.status) ||
      !(value.screenshot.path === null || /^screenshots\/[A-Za-z0-9._-]{1,128}\.png$/.test(value.screenshot.path)) ||
      !(value.screenshot.reason === null || ["page-unavailable", "page-not-ready", "login-or-authentication-not-confirmed", "page-safety-check-unavailable", "screenshot-failed"].includes(value.screenshot.reason)) ||
      !isRecord(value.provider_attempt_ledger) || !sameKeys(Object.keys(value.provider_attempt_ledger).sort(), [
        "before_login", "after_observation_active", "final_copied", "monitor_state",
      ].sort()) || !normalizeLedgerCheckpoint(value.provider_attempt_ledger.before_login) ||
      !normalizeLedgerCheckpoint(value.provider_attempt_ledger.after_observation_active) ||
      !normalizeLedgerCheckpoint(value.provider_attempt_ledger.final_copied) ||
      !["not_started", "active_zero", "violation", "unavailable"].includes(value.provider_attempt_ledger.monitor_state) ||
      !isRecord(value.cleanup) || !sameKeys(Object.keys(value.cleanup).sort(), [
        "owned_host_teardown", "port_probes", "booking_release",
      ].sort()) ||
      !["not_started", "running", "verified_stopped", "failed"].includes(value.cleanup.owned_host_teardown) ||
      value.cleanup.booking_release !== "external_primary_owned" ||
      !normalizePortProbes(value.cleanup.port_probes) ||
      !Array.isArray(value.failure_categories) || value.failure_categories.length > OBSERVATION_FAILURE_CATEGORIES.size ||
      value.failure_categories.some((category) => !OBSERVATION_FAILURE_CATEGORIES.has(category)) ||
      typeof value.recorded_at_utc !== "string" || !Number.isFinite(Date.parse(value.recorded_at_utc))) {
    return null;
  }
  return {
    schema: "n2-handshake-observation.v1",
    mode: "N2_HANDSHAKE_OBSERVATION",
    n2_gate_result: "NOT_N2_GATE",
    run_id: value.run_id,
    party_size: 1,
    player_count: 1,
    browser: "Chrome",
    browser_version: value.browser_version,
    setup: { ...value.setup },
    request_diagnostics: { ...value.request_diagnostics },
    screenshot: { ...value.screenshot },
    provider_attempt_ledger: {
      before_login: { ...value.provider_attempt_ledger.before_login },
      after_observation_active: { ...value.provider_attempt_ledger.after_observation_active },
      final_copied: { ...value.provider_attempt_ledger.final_copied },
      monitor_state: value.provider_attempt_ledger.monitor_state,
    },
    cleanup: {
      owned_host_teardown: value.cleanup.owned_host_teardown,
      port_probes: value.cleanup.port_probes.map((probe) => ({ ...probe })),
      booking_release: "external_primary_owned",
    },
    failure_categories: [...new Set(value.failure_categories)],
    recorded_at_utc: value.recorded_at_utc.slice(0, 40),
  };
}

function normalizeLedgerCheckpoint(value) {
  if (!isRecord(value) || !sameKeys(Object.keys(value).sort(), [
    "state", "reservation_count", "refusal_count",
  ].sort()) || !["active_zero", "active_nonzero", "guard_not_started", "ledger_missing", "ledger_invalid"].includes(value.state)) {
    return false;
  }
  if (value.state === "active_zero") {
    return value.reservation_count === 0 && value.refusal_count === 0;
  }
  if (value.state === "active_nonzero") {
    return Number.isInteger(value.reservation_count) && value.reservation_count > 0 &&
      Number.isInteger(value.refusal_count) && value.refusal_count >= 0;
  }
  return value.reservation_count === null && value.refusal_count === null;
}

function normalizePortProbes(value) {
  if (!Array.isArray(value) || value.length > 2) return false;
  const ports = new Set();
  for (const probe of value) {
    if (!isRecord(probe) || !sameKeys(Object.keys(probe).sort(), ["port", "status", "error_code"].sort()) ||
        ![8360, 8370].includes(probe.port) || ports.has(probe.port) ||
        !["free", "error"].includes(probe.status) ||
        !(probe.error_code === null || isBoundedToken(probe.error_code, 32))) return false;
    ports.add(probe.port);
  }
  return true;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sameKeys(actual, expected) {
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function isBoundedToken(value, maximum) {
  return typeof value === "string" && value.length > 0 && value.length <= maximum && /^[A-Za-z0-9._+-]+$/.test(value);
}

function boundedCounter(value, maximum) {
  return Number.isInteger(value) && value >= 0 && value <= maximum;
}
