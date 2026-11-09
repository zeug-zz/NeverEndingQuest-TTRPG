// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import * as nodeFs from "node:fs";

export const SETUP_FAILURE_SCHEMA = "n2-setup-failure.v1";

export const SETUP_FAILURE_STAGES = Object.freeze([
  "browser_launch",
  "browser_context_create",
  "page_create",
  "player_shell_load",
  "player_authentication",
  "player_connection_wait",
  "host_ui_load",
  "client_metadata",
  "setup_evidence_preflight",
  "unknown",
]);

const FAILURE_CATEGORY_BY_STAGE = Object.freeze({
  browser_launch: "browser_launch_failed",
  browser_context_create: "browser_context_create_failed",
  page_create: "page_create_failed",
  player_shell_load: "player_shell_load_failed",
  player_authentication: "player_authentication_failed",
  player_connection_wait: "player_connection_wait_failed",
  host_ui_load: "host_ui_load_failed",
  client_metadata: "client_metadata_failed",
  setup_evidence_preflight: "setup_evidence_preflight_failed",
  unknown: "setup_failed",
});

const PAGE_ROLES = new Set([
  "player-a-chrome",
  "player-b-firefox",
  "host-ui-chrome-context",
  "setup",
]);
const CONNECTION_STATES = new Set([
  "connected",
  "connecting",
  "disconnected",
  "unknown",
  "not_requested",
]);
const SCREENSHOT_REASONS = new Set([
  "page-unavailable",
  "page-not-ready",
  "login-or-authentication-not-confirmed",
  "page-safety-check-unavailable",
  "screenshot-failed",
]);
const ARTIFACT_PATH_PATTERN = /^screenshots\/[A-Za-z0-9._-]{1,128}\.png$/;
const BUILD_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;

export class SetupStageError extends Error {
  constructor(stage) {
    super("N2 setup phase failed.");
    this.name = "N2SetupStageError";
    this.stage = SETUP_FAILURE_STAGES.includes(stage) ? stage : "unknown";
  }
}

export async function withSetupStage(stage, operation) {
  try {
    return await operation();
  } catch {
    throw new SetupStageError(stage);
  }
}

export async function settleSetupOperations(operations) {
  const results = await Promise.allSettled(operations);
  const failed = results.find((result) => result.status === "rejected");
  if (failed?.status === "rejected") throw failed.reason;
}

export function setupFailureStage(error, fallback = "unknown") {
  if (error?.name === "N2SetupStageError" && SETUP_FAILURE_STAGES.includes(error.stage)) {
    return error.stage;
  }
  return SETUP_FAILURE_STAGES.includes(fallback) ? fallback : "unknown";
}

export function createSetupFailureRecord({
  stage,
  observed,
  screenshots,
  requestDiagnostics,
  recordedAt = new Date().toISOString(),
}) {
  const safeStage = SETUP_FAILURE_STAGES.includes(stage) ? stage : "unknown";
  const observedRecord = observed && typeof observed === "object" ? observed : {};
  const safeBuildId = typeof observedRecord.client_build_id === "string" &&
    BUILD_ID_PATTERN.test(observedRecord.client_build_id)
    ? observedRecord.client_build_id
    : null;
  const safeProtocolVersion = isProtocolVersion(observedRecord.protocol_version)
    ? observedRecord.protocol_version
    : null;
  const safeScreenshots = normalizeScreenshots(screenshots);
  return {
    schema: SETUP_FAILURE_SCHEMA,
    status: "FAIL",
    stage: safeStage,
    failure_category: FAILURE_CATEGORY_BY_STAGE[safeStage],
    expected: {
      player_connection_state: "connected",
      player_b_connection_state: observedRecord.player_b_connection_state === "not_requested"
        ? "not_requested"
        : "connected",
      host_ui_loaded: true,
      client_build_id: "available-from-player-shell",
    },
    observed: {
      player_connection_state: safeConnectionState(observedRecord.player_connection_state),
      player_b_connection_state: safeConnectionState(observedRecord.player_b_connection_state),
      player_shell_loaded: observedRecord.player_shell_loaded === true,
      host_ui_loaded: observedRecord.host_ui_loaded === true,
      client_build_id: safeBuildId,
      protocol_version: safeProtocolVersion,
    },
    gameplay_scenarios: {
      status: "BLOCKED",
      executed: false,
      reason: "beforeAll_setup_failed",
    },
    screenshots: safeScreenshots,
    request_diagnostics: normalizeRequestDiagnosticSummary(requestDiagnostics) ?? emptyRequestDiagnosticSummary(),
    recorded_at_utc: safeTimestamp(recordedAt),
  };
}

export function normalizeSetupFailureRecord(value) {
  if (!isRecord(value) || value.schema !== SETUP_FAILURE_SCHEMA || value.status !== "FAIL" ||
      !SETUP_FAILURE_STAGES.includes(value.stage) ||
      value.failure_category !== FAILURE_CATEGORY_BY_STAGE[value.stage] ||
      !isRecord(value.expected) || !isRecord(value.observed) ||
      !isRecord(value.gameplay_scenarios) || !Array.isArray(value.screenshots) ||
      !isRecord(value.request_diagnostics) ||
      typeof value.recorded_at_utc !== "string" || !Number.isFinite(Date.parse(value.recorded_at_utc))) {
    return null;
  }

  const expectedKeys = Object.keys(value.expected).sort();
  const observedKeys = Object.keys(value.observed).sort();
  const scenarioKeys = Object.keys(value.gameplay_scenarios).sort();
  const requestKeys = Object.keys(value.request_diagnostics).sort();
  const currentObservedKeys = [
    "client_build_id",
    "host_ui_loaded",
    "player_b_connection_state",
    "player_connection_state",
    "player_shell_loaded",
    "protocol_version",
  ].sort();
  const previousObservedKeys = currentObservedKeys.filter((key) => key !== "protocol_version");
  if (!sameKeys(expectedKeys, [
    "client_build_id",
    "host_ui_loaded",
    "player_b_connection_state",
    "player_connection_state",
  ].sort()) ||
      !(sameKeys(observedKeys, currentObservedKeys) || sameKeys(observedKeys, previousObservedKeys)) ||
      !sameKeys(scenarioKeys, ["executed", "reason", "status"].sort()) ||
      !sameKeys(requestKeys, [
        "artifact",
        "record_write_failures",
        "records_omitted",
        "records_written",
        "truncated",
      ].sort()) ||
      value.expected.player_connection_state !== "connected" ||
      !(value.expected.player_b_connection_state === "connected" ||
        value.expected.player_b_connection_state === "not_requested") ||
      value.expected.host_ui_loaded !== true ||
      value.expected.client_build_id !== "available-from-player-shell" ||
      value.gameplay_scenarios.status !== "BLOCKED" ||
      value.gameplay_scenarios.executed !== false ||
      value.gameplay_scenarios.reason !== "beforeAll_setup_failed" ||
      normalizeRequestDiagnosticSummary(value.request_diagnostics) === null ||
      !isConnectionState(value.observed.player_connection_state) ||
      !isConnectionState(value.observed.player_b_connection_state) ||
      typeof value.observed.player_shell_loaded !== "boolean" ||
      typeof value.observed.host_ui_loaded !== "boolean" ||
      (value.observed.client_build_id !== null &&
        (typeof value.observed.client_build_id !== "string" || !BUILD_ID_PATTERN.test(value.observed.client_build_id))) ||
      (Object.prototype.hasOwnProperty.call(value.observed, "protocol_version") &&
        value.observed.protocol_version !== null && !isProtocolVersion(value.observed.protocol_version))) {
    return null;
  }

  const screenshots = normalizeScreenshots(value.screenshots);
  if (screenshots.length !== value.screenshots.length) return null;
  return createSetupFailureRecord({
    stage: value.stage,
    observed: value.observed,
    screenshots,
    requestDiagnostics: value.request_diagnostics,
    recordedAt: value.recorded_at_utc,
  });
}

export async function captureSetupFailureBeforeClose({
  stage,
  observed,
  pages,
  captureScreenshot,
  flushRequestDiagnostics,
  writeRecord,
  closePages,
  recordedAt = new Date().toISOString(),
}) {
  let requestDiagnostics = emptyRequestDiagnosticSummary();
  if (typeof flushRequestDiagnostics === "function") {
    try {
      requestDiagnostics = normalizeRequestDiagnosticSummary(await flushRequestDiagnostics()) ?? {
        ...emptyRequestDiagnosticSummary(),
        record_write_failures: 1,
      };
    } catch {
      requestDiagnostics = {
        ...emptyRequestDiagnosticSummary(),
        record_write_failures: 1,
      };
    }
  }

  const screenshots = [];
  const candidates = Array.isArray(pages) ? pages.slice(0, 3) : [];
  if (candidates.length === 0) {
    screenshots.push({ role: "setup", status: "skipped", reason: "page-unavailable" });
  }

  for (const candidate of candidates) {
    const role = PAGE_ROLES.has(candidate?.role) ? candidate.role : "setup";
    try {
      const result = await captureScreenshot(candidate?.page, role);
      screenshots.push(normalizeScreenshotResult(role, result));
    } catch {
      screenshots.push({ role, status: "failed", reason: "screenshot-failed" });
    }
  }

  const record = createSetupFailureRecord({
    stage,
    observed,
    screenshots,
    requestDiagnostics,
    recordedAt,
  });
  let recordWriteStatus = "written";
  try {
    await writeRecord(record);
  } catch {
    recordWriteStatus = "failed";
  }

  let pageCloseStatus = "closed";
  try {
    await closePages();
  } catch {
    pageCloseStatus = "failed";
  }
  return { record, record_write_status: recordWriteStatus, page_close_status: pageCloseStatus };
}

export function sanitizeSetupScreenshotPage(role, documentRef = globalThis.document) {
  const authenticatedPlayerStatuses = new Set([
    "Connected",
    "Disconnected",
    "Connecting...",
    "Loading player snapshot...",
  ]);
  if (![
    "player-a-chrome",
    "player-b-firefox",
    "host-ui-chrome-context",
    "setup",
  ].includes(role) || !documentRef?.documentElement) {
    return { safe: false, reason: "page-not-ready" };
  }

  const sensitiveName = /(password|passphrase|verifier|token|csrf|secret|authorization|cookie|session)/i;
  const maskElement = (element) => {
    element.setAttribute("data-n2-evidence-masked", "true");
    element.style?.setProperty("color", "transparent", "important");
    element.style?.setProperty("-webkit-text-fill-color", "transparent", "important");
    element.style?.setProperty("text-shadow", "none", "important");
    element.style?.setProperty("background-image", "none", "important");
  };
  for (const element of documentRef.querySelectorAll("input, textarea, select")) {
    if (element.matches("select")) {
      element.selectedIndex = -1;
    } else {
      element.value = "";
      element.setAttribute("value", "");
    }
    element.setAttribute("placeholder", "");
    maskElement(element);
  }

  for (const element of documentRef.querySelectorAll("[contenteditable='true']")) {
    element.textContent = "";
    maskElement(element);
  }

  for (const element of documentRef.querySelectorAll(
    "[data-sensitive], [data-secret], [aria-label], [data-testid], [autocomplete], [id], [name], button, [role='button'], [role='status']",
  )) {
    const identifyingText = [
      element.id,
      element.getAttribute("name"),
      element.getAttribute("autocomplete"),
      element.getAttribute("aria-label"),
      element.getAttribute("data-testid"),
      element.textContent,
    ].filter(Boolean).join(" ");
    if (!sensitiveName.test(identifyingText) && !element.hasAttribute("data-sensitive") &&
        !element.hasAttribute("data-secret")) continue;
    if (element.matches("input, textarea")) continue;
    element.textContent = "[REDACTED]";
    maskElement(element);
  }

  const passwordField = documentRef.querySelector("input[type='password']");
  if (role.startsWith("player-")) {
    const heading = documentRef.querySelector("h1")?.textContent?.trim();
    const connectionStatus = documentRef.querySelector("[role='status']")?.textContent?.trim();
    const logoutButton = [...documentRef.querySelectorAll("button")]
      .some((button) => button.textContent?.trim() === "Log out");
    if (heading !== "NeverEndingQuest player" || !logoutButton ||
        !authenticatedPlayerStatuses.has(connectionStatus) || passwordField) {
      return { safe: false, reason: "login-or-authentication-not-confirmed" };
    }
  } else if (role === "host-ui-chrome-context") {
    if (!documentRef.querySelector("#game-output") || !documentRef.querySelector("#user-input") || passwordField) {
      return { safe: false, reason: "login-or-authentication-not-confirmed" };
    }
  }
  return { safe: true, reason: null };
}

export async function captureCredentialSafeScreenshot(page, role, path, expectedOrigin) {
  if (!page || typeof page.isClosed !== "function" || page.isClosed()) {
    return { status: "skipped", reason: "page-unavailable" };
  }
  const fixedOrigin = role.startsWith("player-")
    ? "http://127.0.0.1:8370"
    : role === "host-ui-chrome-context"
      ? "http://127.0.0.1:8360"
      : null;
  try {
    if (fixedOrigin === null || expectedOrigin !== fixedOrigin ||
        new URL(page.url()).origin !== fixedOrigin) {
      return { status: "skipped", reason: "page-not-ready" };
    }
  } catch {
    return { status: "skipped", reason: "page-unavailable" };
  }
  let safety;
  try {
    safety = await page.evaluate(sanitizeSetupScreenshotPage, role);
  } catch {
    return { status: "skipped", reason: "page-safety-check-unavailable" };
  }
  if (!safety?.safe) {
    return {
      status: "skipped",
      reason: SCREENSHOT_REASONS.has(safety?.reason)
        ? safety.reason
        : "page-safety-check-unavailable",
    };
  }
  try {
    await page.screenshot({ path, fullPage: true, animations: "disabled" });
    return { status: "captured", path };
  } catch {
    return { status: "failed", reason: "screenshot-failed" };
  }
}

export function readSetupFailureEvidence(path) {
  try {
    if (!nodeFs.existsSync(path)) return { status: "missing", record: null };
    if (nodeFs.lstatSync(path).isSymbolicLink() || !nodeFs.lstatSync(path).isFile()) {
      return { status: "invalid", record: null };
    }
    const contents = nodeFs.readFileSync(path, "utf8");
    if (Buffer.byteLength(contents, "utf8") > 16_384) return { status: "invalid", record: null };
    let parsed;
    try {
      parsed = JSON.parse(contents);
    } catch {
      return { status: "invalid", record: null };
    }
    const record = normalizeSetupFailureRecord(parsed);
    return record === null
      ? { status: "invalid", record: null }
      : { status: "valid", record };
  } catch {
    return { status: "invalid", record: null };
  }
}

export function normalizeRequestDiagnosticSummary(value) {
  if (!isRecord(value) ||
      !(value.artifact === null || value.artifact === "request-diagnostics.jsonl") ||
      !Number.isInteger(value.records_written) || value.records_written < 0 ||
      !Number.isInteger(value.records_omitted) || value.records_omitted < 0 ||
      !Number.isInteger(value.record_write_failures) || value.record_write_failures < 0 ||
      typeof value.truncated !== "boolean" ||
      value.truncated !== (value.records_omitted > 0)) {
    return null;
  }
  return {
    artifact: value.artifact,
    records_written: Math.min(128, value.records_written),
    records_omitted: Math.min(1_000_000, value.records_omitted),
    record_write_failures: Math.min(1_000_000, value.record_write_failures),
    truncated: value.truncated,
  };
}

function normalizeScreenshots(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 3).map((item) => {
    const role = PAGE_ROLES.has(item?.role) ? item.role : "setup";
    if (item?.status === "captured" && typeof item.path === "string" && ARTIFACT_PATH_PATTERN.test(item.path)) {
      return { role, status: "captured", path: item.path };
    }
    if (item?.status === "failed") {
      return { role, status: "failed", reason: "screenshot-failed" };
    }
    const reason = SCREENSHOT_REASONS.has(item?.reason) ? item.reason : "page-safety-check-unavailable";
    return { role, status: "skipped", reason };
  });
}

function emptyRequestDiagnosticSummary() {
  return {
    artifact: null,
    records_written: 0,
    records_omitted: 0,
    record_write_failures: 0,
    truncated: false,
  };
}

function normalizeScreenshotResult(role, result) {
  if (result?.status === "captured" && typeof result.path === "string" && ARTIFACT_PATH_PATTERN.test(result.path)) {
    return { role, status: "captured", path: result.path };
  }
  if (result?.status === "failed") return { role, status: "failed", reason: "screenshot-failed" };
  return {
    role,
    status: "skipped",
    reason: SCREENSHOT_REASONS.has(result?.reason) ? result.reason : "page-safety-check-unavailable",
  };
}

function safeConnectionState(value) {
  return isConnectionState(value) ? value : "unknown";
}

function isConnectionState(value) {
  return typeof value === "string" && CONNECTION_STATES.has(value);
}

function isProtocolVersion(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function safeTimestamp(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    ? value.slice(0, 40)
    : new Date(0).toISOString();
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sameKeys(actual, expected) {
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}
