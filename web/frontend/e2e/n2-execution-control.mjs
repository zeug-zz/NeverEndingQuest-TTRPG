// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { FIREFOX_UNAVAILABLE_REASON } from "./browser-contract.mjs";
import { normalizeSetupFailureRecord } from "./setup-evidence.mjs";

export const N2_MANAGED_LIFECYCLE_IDS = Object.freeze([
  "server-instance-change",
  "missing-bundle",
  "broken-bundle",
]);

const VALID_VERDICTS = new Set(["PASS", "FAIL", "BLOCKED"]);

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stopCause(kind, severity, reason, scenarioId = null, checkId = null) {
  return {
    kind,
    severity,
    reason,
    ...(scenarioId === null ? {} : { scenario_id: scenarioId }),
    ...(checkId === null ? {} : { check_id: checkId }),
  };
}

function blockedReason(cause) {
  const reason = typeof cause?.reason === "string" && cause.reason.length > 0
    ? cause.reason
    : "A prior required N2 result stopped scenario execution.";
  return reason.slice(0, 512);
}

function resultTimestamp(now) {
  const value = now();
  return value instanceof Date ? value.toISOString() : new Date(value).toISOString();
}

export function makeBlockedScenarioResult(scenario, cause, now = () => new Date()) {
  const reason = blockedReason(cause);
  const safeCause = {
    kind: typeof cause?.kind === "string" ? cause.kind : "n2-execution-stopped",
    severity: cause?.severity === "FAIL" ? "FAIL" : "BLOCKED",
    reason,
    ...(typeof cause?.scenario_id === "string" ? { scenario_id: cause.scenario_id } : {}),
    ...(typeof cause?.check_id === "string" ? { check_id: cause.check_id } : {}),
  };
  return {
    id: scenario.id,
    expected: scenario.description,
    observed: {
      status: "BLOCKED",
      executed: false,
      reason,
      stop_cause: safeCause,
    },
    verdict: "BLOCKED",
    execution_status: "BLOCKED_UNEXECUTED",
    checks: (scenario.checks ?? []).map((check) => ({
      id: check.id,
      expected: check.description,
      observed: { executed: false, reason },
      verdict: "BLOCKED",
      reason,
    })),
    artifacts: [],
    recorded_at_utc: resultTimestamp(now),
  };
}

export function inspectN2ScenarioResult(scenario, result, browsers) {
  const scenarioId = typeof scenario?.id === "string" ? scenario.id : null;
  if (!isRecord(scenario) || !Array.isArray(scenario.checks)) {
    return {
      canContinue: false,
      cause: stopCause("scenario-catalog-invalid", "FAIL", "The required scenario definition is invalid.", scenarioId),
    };
  }
  if (!isRecord(result) || result.id !== scenario.id) {
    return {
      canContinue: false,
      cause: stopCause("scenario-result-invalid", "FAIL", "A required scenario result is missing or malformed.", scenarioId),
    };
  }
  if (!Object.hasOwn(result, "expected") || !Object.hasOwn(result, "observed") ||
      !(typeof result.expected === "string" || isRecord(result.expected)) || !isRecord(result.observed) ||
      !Array.isArray(result.artifacts) || !result.artifacts.every((item) => typeof item === "string") ||
      typeof result.recorded_at_utc !== "string" || !Number.isFinite(Date.parse(result.recorded_at_utc)) ||
      !VALID_VERDICTS.has(result.verdict)) {
    return {
      canContinue: false,
      cause: stopCause("scenario-result-invalid", "FAIL", "A required scenario result is missing or malformed.", scenarioId),
    };
  }
  if (result.verdict === "FAIL") {
    return {
      canContinue: false,
      cause: stopCause("scenario-failed", "FAIL", "The required scenario recorded FAIL.", scenarioId),
    };
  }
  if (!Array.isArray(result.checks)) {
    return {
      canContinue: false,
      cause: stopCause("scenario-checks-invalid", "FAIL", "A required scenario has malformed check evidence.", scenarioId),
    };
  }

  const definitions = new Map(scenario.checks.map((check) => [check.id, check]));
  const recorded = new Map();
  for (const check of result.checks) {
    if (!isRecord(check) || typeof check.id !== "string" || !VALID_VERDICTS.has(check.verdict) ||
        typeof check.expected !== "string" || !isRecord(check.observed)) {
      return {
        canContinue: false,
        cause: stopCause("scenario-check-invalid", "FAIL", "A required scenario check is malformed.", scenarioId),
      };
    }
    if (!definitions.has(check.id) || recorded.has(check.id)) {
      return {
        canContinue: false,
        cause: stopCause("scenario-check-set-invalid", "FAIL", "Scenario checks do not match the required catalog.", scenarioId, check.id),
      };
    }
    recorded.set(check.id, check);
  }

  let firefoxBlocked = false;
  for (const [checkId, definition] of definitions) {
    const check = recorded.get(checkId);
    if (!check) {
      return {
        canContinue: false,
        cause: stopCause("required-check-missing", "BLOCKED", "A required scenario check has no persisted outcome.", scenarioId, checkId),
      };
    }
    if (check.verdict === "FAIL") {
      return {
        canContinue: false,
        cause: stopCause("required-check-failed", "FAIL", "A required scenario check recorded FAIL.", scenarioId, checkId),
      };
    }
    if (definition.requires_firefox && !browsers.includes("firefox")) {
      const reason = typeof check.reason === "string"
        ? check.reason
        : isRecord(check.observed) && typeof check.observed.reason === "string"
          ? check.observed.reason
          : null;
      if (check.verdict !== "BLOCKED" || reason !== FIREFOX_UNAVAILABLE_REASON) {
        return {
          canContinue: false,
          cause: stopCause("firefox-result-invalid", "BLOCKED", "The unavailable Firefox check lacks its required BLOCKED reason.", scenarioId, checkId),
        };
      }
      firefoxBlocked = true;
      continue;
    }
    if (check.verdict === "BLOCKED") {
      return {
        canContinue: false,
        cause: stopCause("required-check-blocked", "BLOCKED", "A required non-Firefox check is BLOCKED.", scenarioId, checkId),
      };
    }
  }

  const expectedVerdict = firefoxBlocked ? "BLOCKED" : "PASS";
  if (result.verdict !== expectedVerdict) {
    return {
      canContinue: false,
      cause: stopCause("scenario-verdict-inconsistent", "FAIL", "The scenario verdict does not match its check outcomes.", scenarioId),
    };
  }
  return { canContinue: true, cause: null };
}

function inspectChildResult(child, requestedSignal) {
  if (requestedSignal !== null && requestedSignal !== undefined) {
    return stopCause("playwright-interrupted", "BLOCKED", "The Playwright child was interrupted by an operator signal.");
  }
  if (!isRecord(child) || !Object.hasOwn(child, "status") || !Object.hasOwn(child, "signal") ||
      !Object.hasOwn(child, "error")) {
    return stopCause("playwright-child-result-invalid", "FAIL", "The Playwright child returned an invalid process result.");
  }
  if (child.error !== null) {
    return stopCause("playwright-child-error", "FAIL", "The Playwright child reported a spawn or runner error.");
  }
  if (child.signal !== null) {
    return stopCause("playwright-interrupted", "BLOCKED", "The Playwright child terminated from a signal.");
  }
  if (!Number.isInteger(child.status)) {
    return stopCause("playwright-child-status-invalid", "FAIL", "The Playwright child exited without a valid status.");
  }
  if (child.status !== 0) {
    return stopCause("playwright-child-failed", "FAIL", "The Playwright child exited unsuccessfully, including timeout or assertion failure.");
  }
  return null;
}

function inspectBudgetDecision(decision) {
  if (!isRecord(decision) || !VALID_VERDICTS.has(decision.verdict)) {
    return stopCause("provider-budget-result-invalid", "BLOCKED", "The provider-attempt ledger did not produce a valid continuation decision.");
  }
  if (decision.verdict === "PASS") return null;
  if (decision.verdict === "FAIL") {
    return stopCause("provider-budget-refusal", "FAIL", "The provider-attempt budget refused a dispatch.");
  }
  return stopCause("provider-budget-unavailable", "BLOCKED", "The provider-attempt budget cannot safely permit another scenario.");
}

export function assessPlaywrightCompletion({
  child,
  records,
  evidenceErrors = [],
  setupFailureEvidence = null,
  scenarioCatalog,
  browsers,
  lifecycleScenarioIds = N2_MANAGED_LIFECYCLE_IDS,
  providerBudgetDecision,
  requestedSignal = null,
}) {
  const lifecycleIds = new Set(lifecycleScenarioIds);
  const catalogById = new Map(scenarioCatalog.map((scenario) => [scenario.id, scenario]));
  const requiredScenarios = scenarioCatalog.filter((scenario) => !lifecycleIds.has(scenario.id));
  const seenIds = new Set();
  let cause = null;

  if (!Array.isArray(records)) {
    cause = stopCause("playwright-evidence-invalid", "FAIL", "Persisted Playwright scenario evidence is not a list.");
  } else {
    for (const record of records) {
      if (!isRecord(record) || typeof record.id !== "string") {
        cause = stopCause("playwright-result-invalid", "FAIL", "Persisted Playwright scenario evidence contains a malformed result.");
        break;
      }
      if (lifecycleIds.has(record.id)) {
        cause = stopCause("unexpected-lifecycle-placeholder", "FAIL", "A managed lifecycle placeholder appeared in Playwright evidence.", record.id);
        break;
      }
      const scenario = catalogById.get(record.id);
      if (!scenario || seenIds.has(record.id)) {
        cause = stopCause("playwright-result-set-invalid", "FAIL", "Persisted Playwright scenario IDs are unknown or duplicated.", record.id);
        break;
      }
      seenIds.add(record.id);
      const inspection = inspectN2ScenarioResult(scenario, record, browsers);
      if (!inspection.canContinue) {
        cause = inspection.cause;
        break;
      }
    }
  }

  if (cause === null && evidenceErrors.length > 0) {
    cause = stopCause("playwright-evidence-malformed", "FAIL", "The persisted Playwright scenario file contains malformed evidence.");
  }
  if (cause === null && setupFailureEvidence?.status === "invalid") {
    cause = stopCause("playwright-setup-evidence-invalid", "FAIL", "Playwright setup failure evidence is invalid.");
  }
  if (cause === null && setupFailureEvidence?.status === "valid") {
    const setupRecord = normalizeSetupFailureRecord(setupFailureEvidence.record);
    cause = setupRecord === null
      ? stopCause("playwright-setup-evidence-invalid", "FAIL", "Playwright setup failure evidence is invalid.")
      : stopCause("playwright-setup-failed", "FAIL", "Playwright beforeAll setup failed before gameplay scenarios.");
  }
  if (cause === null) cause = inspectBudgetDecision(providerBudgetDecision);
  if (cause === null) cause = inspectChildResult(child, requestedSignal);
  if (cause === null) {
    const missing = requiredScenarios.find((scenario) => !seenIds.has(scenario.id));
    if (missing) {
      cause = stopCause("playwright-scenario-missing", "BLOCKED", "A required Playwright scenario has no persisted result.", missing.id);
    }
  }

  return {
    mayRunLifecycle: cause === null,
    stopCause: cause,
    missingScenarioIds: requiredScenarios
      .filter((scenario) => !seenIds.has(scenario.id))
      .map((scenario) => scenario.id),
  };
}

function scenarioListForIds(scenarioCatalog, scenarioIds) {
  const byId = new Map(scenarioCatalog.map((scenario) => [scenario.id, scenario]));
  return scenarioIds.map((id) => byId.get(id)).filter(Boolean);
}

export async function runLifecycleAfterPlaywright({
  child,
  records,
  evidenceErrors = [],
  setupFailureEvidence = null,
  scenarioCatalog,
  browsers,
  lifecycleScenarioIds = N2_MANAGED_LIFECYCLE_IDS,
  providerBudgetDecision,
  requestedSignal = null,
  runLifecycle,
  now = () => new Date(),
}) {
  const decision = assessPlaywrightCompletion({
    child,
    records,
    evidenceErrors,
    setupFailureEvidence,
    scenarioCatalog,
    browsers,
    lifecycleScenarioIds,
    providerBudgetDecision,
    requestedSignal,
  });
  if (!decision.mayRunLifecycle) {
    return {
      lifecycleStarted: false,
      stopCause: decision.stopCause,
      lifecycleStopCause: null,
      lifecycleResults: scenarioListForIds(scenarioCatalog, lifecycleScenarioIds)
        .map((scenario) => makeBlockedScenarioResult(scenario, decision.stopCause, now)),
    };
  }

  let lifecycle;
  try {
    lifecycle = await runLifecycle();
  } catch {
    const cause = stopCause("managed-lifecycle-runner-failed", "FAIL", "The managed lifecycle runner failed before returning complete evidence.");
    return {
      lifecycleStarted: true,
      stopCause: null,
      lifecycleStopCause: cause,
      lifecycleResults: scenarioListForIds(scenarioCatalog, lifecycleScenarioIds)
        .map((scenario) => makeBlockedScenarioResult(scenario, cause, now)),
    };
  }

  if (!isRecord(lifecycle) || !Array.isArray(lifecycle.results)) {
    const cause = stopCause("managed-lifecycle-result-invalid", "FAIL", "The managed lifecycle returned malformed scenario evidence.");
    return {
      lifecycleStarted: true,
      stopCause: null,
      lifecycleStopCause: cause,
      lifecycleResults: scenarioListForIds(scenarioCatalog, lifecycleScenarioIds)
        .map((scenario) => makeBlockedScenarioResult(scenario, cause, now)),
    };
  }

  const lifecycleResults = [...lifecycle.results];
  const lifecycleById = new Map();
  let lifecycleStopCause = lifecycle.stop_cause ?? null;
  if (lifecycleStopCause !== null &&
      (!isRecord(lifecycleStopCause) || !["FAIL", "BLOCKED"].includes(lifecycleStopCause.severity) ||
        typeof lifecycleStopCause.kind !== "string" || typeof lifecycleStopCause.reason !== "string")) {
    lifecycleStopCause = stopCause("managed-lifecycle-stop-cause-invalid", "FAIL", "The managed lifecycle returned an invalid stop cause.");
  }
  for (const record of lifecycleResults) {
    if (!isRecord(record) || typeof record.id !== "string" || lifecycleById.has(record.id)) {
      lifecycleStopCause ??= stopCause("managed-lifecycle-result-invalid", "FAIL", "The managed lifecycle returned malformed or duplicate scenario evidence.");
      continue;
    }
    if (!lifecycleScenarioIds.includes(record.id)) {
      lifecycleStopCause ??= stopCause("managed-lifecycle-result-unexpected", "FAIL", "The managed lifecycle returned an unknown scenario result.", record.id);
      continue;
    }
    lifecycleById.set(record.id, record);
  }
  for (const scenario of scenarioListForIds(scenarioCatalog, lifecycleScenarioIds)) {
    const record = lifecycleById.get(scenario.id);
    if (!record) {
      lifecycleStopCause ??= stopCause("managed-lifecycle-result-missing", "BLOCKED", "A required managed lifecycle scenario has no persisted result.", scenario.id);
      lifecycleResults.push(makeBlockedScenarioResult(scenario, lifecycleStopCause, now));
      continue;
    }
    const inspection = inspectN2ScenarioResult(scenario, record, browsers);
    if (!inspection.canContinue) lifecycleStopCause ??= inspection.cause;
  }
  return {
    lifecycleStarted: true,
    stopCause: null,
    lifecycleStopCause,
    lifecycleResults,
  };
}

function failedScenarioResult(scenario, reason, now) {
  return {
    id: scenario.id,
    expected: scenario.description,
    observed: { error: reason },
    verdict: "FAIL",
    checks: [],
    artifacts: [],
    recorded_at_utc: resultTimestamp(now),
  };
}

export async function runFailFastScenarioSequence({
  scenarios,
  browsers,
  runScenario,
  normalizeResult = (result) => result,
  beforeScenario = async () => null,
  finalize = async () => {},
  onResult = async () => {},
  getInterruption = () => null,
  now = () => new Date(),
}) {
  const results = [];
  const evidenceErrors = [];
  let stopCause = null;
  let nextIndex = 0;

  const emit = async (result) => {
    results.push(result);
    try {
      await onResult(result);
      return true;
    } catch {
      evidenceErrors.push("scenario-evidence-write-failed");
      stopCause ??= stopCauseValue("scenario-evidence-write-failed", "FAIL", "A scenario result could not be preserved as evidence.");
      return false;
    }
  };

  try {
    for (let index = 0; index < scenarios.length; index += 1) {
      const scenario = scenarios[index];
      nextIndex = index;
      let budgetDecision;
      try {
        budgetDecision = await beforeScenario(scenario);
      } catch {
        stopCause = stopCauseValue("before-scenario-guard-failed", "FAIL", "A required pre-scenario safety check failed.", scenario.id);
        break;
      }
      if (budgetDecision !== null && budgetDecision !== undefined &&
          (!isRecord(budgetDecision) || budgetDecision.verdict !== "PASS")) {
        const severity = budgetDecision?.verdict === "FAIL" ? "FAIL" : "BLOCKED";
        const kind = typeof budgetDecision?.kind === "string"
          ? budgetDecision.kind
          : severity === "FAIL"
            ? "provider-budget-refusal"
            : "before-scenario-blocked";
        stopCause = stopCauseValue(
          kind,
          severity,
          typeof budgetDecision?.reason === "string" ? budgetDecision.reason : "A required pre-scenario check blocked further execution.",
          scenario.id,
        );
        break;
      }

      let result;
      try {
        result = normalizeResult(await runScenario(scenario), scenario);
      } catch {
        result = failedScenarioResult(scenario, "The lifecycle scenario runner failed or timed out.", now);
      }
      if (!isRecord(result) || result.id !== scenario.id) {
        result = failedScenarioResult(scenario, "The lifecycle scenario returned an invalid result.", now);
      }
      await emit(result);
      nextIndex = index + 1;
      if (stopCause !== null) break;
      const interruption = getInterruption();
      if (interruption !== null && interruption !== undefined) {
        stopCause = stopCauseValue(
          "managed-lifecycle-interrupted",
          "BLOCKED",
          "The managed lifecycle was interrupted by an operator signal.",
          scenario.id,
        );
        break;
      }
      const inspection = inspectN2ScenarioResult(scenario, result, browsers);
      if (!inspection.canContinue) {
        stopCause = inspection.cause;
        break;
      }
    }
  } finally {
    try {
      await finalize({ results, stopCause });
    } catch {
      evidenceErrors.push("managed-lifecycle-finalization-failed");
      const cleanupCause = stopCauseValue("managed-lifecycle-finalization-failed", "FAIL", "Managed lifecycle teardown failed.");
      if (stopCause === null) stopCause = cleanupCause;
      else {
        stopCause = {
          ...stopCause,
          severity: "FAIL",
          secondary_causes: [...(stopCause.secondary_causes ?? []), cleanupCause],
        };
      }
    }
  }

  if (stopCause !== null) {
    for (let index = nextIndex; index < scenarios.length; index += 1) {
      await emit(makeBlockedScenarioResult(scenarios[index], stopCause, now));
    }
  }
  return { results, stop_cause: stopCause, evidence_errors: evidenceErrors };
}

function stopCauseValue(kind, severity, reason, scenarioId = null) {
  return stopCause(kind, severity, reason, scenarioId);
}
