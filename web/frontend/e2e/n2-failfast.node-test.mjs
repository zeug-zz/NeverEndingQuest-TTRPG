// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { FIREFOX_UNAVAILABLE_REASON } from "./browser-contract.mjs";
import { createSetupFailureRecord } from "./setup-evidence.mjs";
import {
  N2_MANAGED_LIFECYCLE_IDS,
  runFailFastScenarioSequence,
  runLifecycleAfterPlaywright,
} from "./n2-execution-control.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const N2_TMP = join(REPOSITORY_ROOT, "tmp", "n2");
const SCENARIO_CATALOG = JSON.parse(
  readFileSync(new URL("./scenarios.json", import.meta.url), "utf8"),
);
const PLAYWRIGHT_SCENARIOS = SCENARIO_CATALOG.filter(
  (scenario) => !N2_MANAGED_LIFECYCLE_IDS.includes(scenario.id),
);
const LIFECYCLE_SCENARIOS = SCENARIO_CATALOG.filter(
  (scenario) => N2_MANAGED_LIFECYCLE_IDS.includes(scenario.id),
);

function scenarioResult(scenario, browsers = ["chrome", "firefox"], overrides = {}) {
  const checks = scenario.checks.map((definition) => {
    if (definition.requires_firefox && !browsers.includes("firefox")) {
      return {
        id: definition.id,
        expected: definition.description,
        observed: { reason: FIREFOX_UNAVAILABLE_REASON },
        verdict: "BLOCKED",
        reason: FIREFOX_UNAVAILABLE_REASON,
      };
    }
    return {
      id: definition.id,
      expected: definition.description,
      observed: { verified: true },
      verdict: "PASS",
    };
  });
  const hasBlocked = checks.some((check) => check.verdict === "BLOCKED");
  return {
    id: scenario.id,
    expected: scenario.description,
    observed: { verified: true },
    verdict: hasBlocked ? "BLOCKED" : "PASS",
    checks,
    artifacts: [],
    recorded_at_utc: "2026-11-09T12:00:00.000Z",
    ...overrides,
  };
}

function playResults(browsers = ["chrome", "firefox"]) {
  return PLAYWRIGHT_SCENARIOS.map((scenario) => scenarioResult(scenario, browsers));
}

function successfulLifecycleOutput(browsers = ["chrome", "firefox"]) {
  return {
    results: LIFECYCLE_SCENARIOS.map((scenario) => scenarioResult(scenario, browsers)),
    stop_cause: null,
  };
}

function successChild() {
  return { status: 0, signal: null, error: null, stdout: "", stderr: "" };
}

const providerBudgetPass = { verdict: "PASS", reason: null };

test("a failed Playwright child blocks all managed lifecycle scenarios", async () => {
  let lifecycleCalls = 0;
  const result = await runLifecycleAfterPlaywright({
    child: { ...successChild(), status: 1 },
    records: playResults(),
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => {
      lifecycleCalls += 1;
      return successfulLifecycleOutput();
    },
  });

  assert.equal(lifecycleCalls, 0);
  assert.equal(result.lifecycleStarted, false);
  assert.equal(result.stopCause.kind, "playwright-child-failed");
  assert.equal(result.lifecycleResults.length, 3);
  assert.ok(result.lifecycleResults.every((record) => record.verdict === "BLOCKED"));
  assert.ok(result.lifecycleResults.every((record) => record.execution_status === "BLOCKED_UNEXECUTED"));
  assert.ok(result.lifecycleResults.every((record) =>
    record.checks.every((check) => check.verdict === "BLOCKED" && check.reason === result.stopCause.reason),
  ));
});

test("a recorded beforeAll setup failure preserves zero gameplay records and blocks every lifecycle scenario", async () => {
  const setupRecord = createSetupFailureRecord({
    stage: "player_connection_wait",
    observed: {
      player_connection_state: "disconnected",
      player_b_connection_state: "not_requested",
      player_shell_loaded: true,
      host_ui_loaded: true,
      client_build_id: "n2-build-123",
    },
    screenshots: [
      { role: "player-a-chrome", status: "skipped", reason: "login-or-authentication-not-confirmed" },
      { role: "host-ui-chrome-context", status: "captured", path: "screenshots/setup-host.png" },
    ],
  });
  let lifecycleCalls = 0;
  const result = await runLifecycleAfterPlaywright({
    child: { ...successChild(), status: 1 },
    records: [],
    setupFailureEvidence: { status: "valid", record: setupRecord },
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => {
      lifecycleCalls += 1;
      return successfulLifecycleOutput(["chrome"]);
    },
  });

  assert.equal(setupRecord.gameplay_scenarios.executed, false);
  assert.equal(setupRecord.gameplay_scenarios.status, "BLOCKED");
  assert.equal(lifecycleCalls, 0);
  assert.equal(result.stopCause.kind, "playwright-setup-failed");
  assert.equal(result.stopCause.severity, "FAIL");
  assert.deepEqual(result.lifecycleResults.map((record) => record.id), N2_MANAGED_LIFECYCLE_IDS);
  assert.ok(result.lifecycleResults.every((record) =>
    record.verdict === "BLOCKED" && record.execution_status === "BLOCKED_UNEXECUTED",
  ));
});

test("null, malformed, signaled, or nonzero child results fail closed before lifecycle", async () => {
  const cases = [
    { child: null, kind: "playwright-child-result-invalid" },
    { child: { status: null, signal: null, error: null }, kind: "playwright-child-status-invalid" },
    { child: { status: 0, signal: "SIGTERM", error: null }, kind: "playwright-interrupted" },
    { child: { status: 1, signal: null, error: null }, kind: "playwright-child-failed" },
    { child: { status: 0, signal: null, error: new Error("spawn failed") }, kind: "playwright-child-error" },
  ];

  for (const item of cases) {
    let lifecycleCalls = 0;
    const result = await runLifecycleAfterPlaywright({
      child: item.child,
      records: playResults(),
      scenarioCatalog: SCENARIO_CATALOG,
      browsers: ["chrome", "firefox"],
      providerBudgetDecision: providerBudgetPass,
      runLifecycle: async () => {
        lifecycleCalls += 1;
        return successfulLifecycleOutput();
      },
    });
    assert.equal(lifecycleCalls, 0, item.kind);
    assert.equal(result.stopCause.kind, item.kind);
  }
});

test("a persisted FAIL record prevents lifecycle even when the child exits zero", async () => {
  const records = playResults();
  records[0] = { ...records[0], verdict: "FAIL" };
  let lifecycleCalls = 0;
  const result = await runLifecycleAfterPlaywright({
    child: successChild(),
    records,
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => {
      lifecycleCalls += 1;
      return successfulLifecycleOutput();
    },
  });

  assert.equal(lifecycleCalls, 0);
  assert.equal(result.stopCause.kind, "scenario-failed");
  assert.equal(result.stopCause.scenario_id, PLAYWRIGHT_SCENARIOS[0].id);
});

test("missing, malformed, or incomplete required evidence blocks lifecycle", async () => {
  const incomplete = playResults().slice(1);
  const missing = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: incomplete,
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => assert.fail("missing scenario must not launch lifecycle"),
  });
  assert.equal(missing.stopCause.kind, "playwright-scenario-missing");

  const malformedResult = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: playResults(),
    evidenceErrors: [{ line: 4, reason: "malformed-json" }],
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => assert.fail("malformed evidence must not launch lifecycle"),
  });
  assert.equal(malformedResult.stopCause.kind, "playwright-evidence-malformed");

  const incompleteCheckRecords = playResults();
  incompleteCheckRecords[0] = {
    ...incompleteCheckRecords[0],
    checks: incompleteCheckRecords[0].checks.filter((check) => check.id !== "chrome-host-party-consistency"),
  };
  const incompleteCheck = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: incompleteCheckRecords,
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => assert.fail("missing Chrome check must not launch lifecycle"),
  });
  assert.equal(incompleteCheck.stopCause.kind, "required-check-missing");
  assert.equal(incompleteCheck.stopCause.severity, "BLOCKED");

  const malformedRecord = playResults();
  malformedRecord[0] = { ...malformedRecord[0], checks: "not-a-check-list" };
  const malformedRecordResult = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: malformedRecord,
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => assert.fail("malformed scenario evidence must not launch lifecycle"),
  });
  assert.equal(malformedRecordResult.stopCause.kind, "scenario-checks-invalid");

  const budgetRefusal = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: playResults(),
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: {
      verdict: "FAIL",
      reason: "budget_exhausted; outbound dispatch was refused before transport send",
    },
    runLifecycle: async () => assert.fail("budget refusal must not launch lifecycle"),
  });
  assert.equal(budgetRefusal.stopCause.kind, "provider-budget-refusal");
  assert.equal(budgetRefusal.stopCause.severity, "FAIL");
});

test("valid Chrome checks with only Firefox-unavailable blocks may run managed lifecycle", async () => {
  let lifecycleCalls = 0;
  const result = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: playResults(["chrome"]),
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => {
      lifecycleCalls += 1;
      return successfulLifecycleOutput(["chrome"]);
    },
  });

  assert.equal(lifecycleCalls, 1);
  assert.equal(result.lifecycleStarted, true);
  assert.equal(result.stopCause, null);
  assert.equal(result.lifecycleStopCause, null);
  assert.ok(result.lifecycleResults.every((record) => record.verdict === "BLOCKED"));
  assert.ok(result.lifecycleResults.every((record) => record.checks.every((check) =>
    check.verdict === "PASS" || check.reason === FIREFOX_UNAVAILABLE_REASON,
  )));
});

test("a timeout or provider budget refusal prevents subsequent scenario dispatch", async () => {
  const timeoutCalls = [];
  const timeout = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome", "firefox"],
    runScenario: async (scenario) => {
      timeoutCalls.push(scenario.id);
      return scenarioResult(scenario, ["chrome", "firefox"], {
        verdict: "FAIL",
        observed: { error: "scenario timed out" },
      });
    },
  });
  assert.deepEqual(timeoutCalls, [LIFECYCLE_SCENARIOS[0].id]);
  assert.equal(timeout.stop_cause.kind, "scenario-failed");
  assert.equal(timeout.results[1].execution_status, "BLOCKED_UNEXECUTED");

  const budgetCalls = [];
  const budget = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome", "firefox"],
    beforeScenario: async () => budgetCalls.length === 0
      ? { verdict: "PASS" }
      : { verdict: "FAIL", reason: "budget_exhausted; outbound dispatch was refused before transport send" },
    runScenario: async (scenario) => {
      budgetCalls.push(scenario.id);
      return scenarioResult(scenario);
    },
  });
  assert.deepEqual(budgetCalls, [LIFECYCLE_SCENARIOS[0].id]);
  assert.equal(budget.stop_cause.kind, "provider-budget-refusal");
  assert.equal(budget.stop_cause.severity, "FAIL");
  assert.ok(budget.results.slice(1).every((record) => record.execution_status === "BLOCKED_UNEXECUTED"));
});

test("an operator interruption after a lifecycle scenario blocks later dispatch", async () => {
  const calls = [];
  const result = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome", "firefox"],
    runScenario: async (scenario) => {
      calls.push(scenario.id);
      return scenarioResult(scenario);
    },
    getInterruption: () => calls.length > 0 ? "SIGINT" : null,
  });

  assert.deepEqual(calls, [LIFECYCLE_SCENARIOS[0].id]);
  assert.equal(result.stop_cause.kind, "managed-lifecycle-interrupted");
  assert.equal(result.stop_cause.severity, "BLOCKED");
  assert.ok(result.results.slice(1).every((record) => record.execution_status === "BLOCKED_UNEXECUTED"));
});

test("a lifecycle evidence write failure prevents later dispatch but still finalizes", async () => {
  const calls = [];
  let finalized = false;
  const result = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome", "firefox"],
    runScenario: async (scenario) => {
      calls.push(scenario.id);
      return scenarioResult(scenario);
    },
    onResult: async (record) => {
      if (record.id === LIFECYCLE_SCENARIOS[0].id) throw new Error("synthetic evidence write failure");
    },
    finalize: async () => { finalized = true; },
  });

  assert.deepEqual(calls, [LIFECYCLE_SCENARIOS[0].id]);
  assert.equal(finalized, true);
  assert.equal(result.stop_cause.kind, "scenario-evidence-write-failed");
  assert.ok(result.evidence_errors.includes("scenario-evidence-write-failed"));
  assert.ok(result.results.slice(1).every((record) => record.execution_status === "BLOCKED_UNEXECUTED"));
});

test("the lifecycle stops at its first failed record but runs every successful record", async () => {
  const failedCalls = [];
  const failed = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome", "firefox"],
    runScenario: async (scenario) => {
      failedCalls.push(scenario.id);
      return scenarioResult(scenario, ["chrome", "firefox"], {
        verdict: "FAIL",
        observed: { error: "first lifecycle assertion failed" },
      });
    },
  });
  assert.deepEqual(failedCalls, [LIFECYCLE_SCENARIOS[0].id]);
  assert.equal(failed.results[0].verdict, "FAIL");
  assert.ok(failed.results.slice(1).every((record) => record.verdict === "BLOCKED"));

  const successCalls = [];
  const successful = await runFailFastScenarioSequence({
    scenarios: LIFECYCLE_SCENARIOS,
    browsers: ["chrome"],
    runScenario: async (scenario) => {
      successCalls.push(scenario.id);
      return scenarioResult(scenario, ["chrome"]);
    },
  });
  assert.deepEqual(successCalls, N2_MANAGED_LIFECYCLE_IDS);
  assert.equal(successful.stop_cause, null);
  assert.equal(successful.results.length, 3);
  assert.ok(successful.results.every((record) => record.verdict === "BLOCKED"));
});

test("a missing or unexpected lifecycle result fails closed", async () => {
  const partial = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: playResults(),
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => ({
      results: LIFECYCLE_SCENARIOS.slice(0, 2).map((scenario) => scenarioResult(scenario)),
      stop_cause: null,
    }),
  });
  assert.equal(partial.lifecycleStopCause.kind, "managed-lifecycle-result-missing");
  assert.ok(partial.lifecycleResults.some((record) =>
    record.id === LIFECYCLE_SCENARIOS[2].id && record.execution_status === "BLOCKED_UNEXECUTED",
  ));

  const unexpected = await runLifecycleAfterPlaywright({
    child: successChild(),
    records: playResults(),
    scenarioCatalog: SCENARIO_CATALOG,
    browsers: ["chrome", "firefox"],
    providerBudgetDecision: providerBudgetPass,
    runLifecycle: async () => ({
      results: [
        ...successfulLifecycleOutput().results,
        scenarioResult({ id: "unexpected-lifecycle", description: "unexpected", checks: [] }),
      ],
      stop_cause: null,
    }),
  });
  assert.equal(unexpected.lifecycleStopCause.kind, "managed-lifecycle-result-unexpected");
});

test("failure still restores scenario data, tears down, and records fail plus unexecuted evidence", async () => {
  mkdirSync(N2_TMP, { recursive: true });
  const scratch = mkdtempSync(join(N2_TMP, "n2-failfast-test-"));
  const bundle = join(scratch, "bundle.js");
  const evidence = join(scratch, "scenarios.jsonl");
  const original = "verified original bundle\n";
  writeFileSync(bundle, original, { encoding: "ascii", flag: "wx" });
  let restored = false;
  let tornDown = false;

  try {
    const output = await runFailFastScenarioSequence({
      scenarios: LIFECYCLE_SCENARIOS,
      browsers: ["chrome", "firefox"],
      runScenario: async (scenario) => {
        try {
          writeFileSync(bundle, "synthetic corruption\n", { encoding: "ascii" });
          return scenarioResult(scenario, ["chrome", "firefox"], {
            verdict: "FAIL",
            observed: { error: "synthetic managed check failure" },
          });
        } finally {
          writeFileSync(bundle, original, { encoding: "ascii" });
          restored = readFileSync(bundle, "ascii") === original;
        }
      },
      finalize: async () => { tornDown = true; },
      onResult: async (record) => {
        writeFileSync(evidence, `${JSON.stringify(record)}\n`, { encoding: "utf8", flag: "a" });
      },
    });

    assert.equal(restored, true);
    assert.equal(tornDown, true);
    assert.equal(existsSync(evidence), true);
    const evidenceRecords = readFileSync(evidence, "utf8").trim().split("\n").map((line) => JSON.parse(line));
    assert.equal(evidenceRecords[0].verdict, "FAIL");
    assert.ok(evidenceRecords.slice(1).every((record) =>
      record.verdict === "BLOCKED" && record.execution_status === "BLOCKED_UNEXECUTED",
    ));
    assert.equal(output.results.length, 3);
    assert.equal(output.stop_cause.severity, "FAIL");
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
