// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { FIREFOX_UNAVAILABLE_REASON } from "./browser-contract.mjs";

export function browserBlockedChecks(scenarios, browsers) {
  if (browsers.includes("firefox")) return [];
  return scenarios.flatMap((scenario) => (scenario.checks ?? [])
    .filter((check) => check.requires_firefox)
    .map((check) => ({
      scenario_id: scenario.id,
      check_id: check.id,
      reason: FIREFOX_UNAVAILABLE_REASON,
    })));
}

export function blockedChecksFromResults(results) {
  if (!Array.isArray(results)) return [];
  return results.flatMap((scenario) => {
    if (scenario === null || typeof scenario !== "object" || Array.isArray(scenario) ||
        !Array.isArray(scenario.checks)) return [];
    return scenario.checks
      .filter((check) => check !== null && typeof check === "object" && check.verdict === "BLOCKED")
      .map((check) => ({
      scenario_id: scenario.id,
      check_id: check.id,
      reason: check.reason ?? (
        check.observed !== null && typeof check.observed === "object"
          ? check.observed.reason
          : null
      ) ?? "blocked-check-without-reason",
      }));
  });
}

export function missingScenarioChecks(scenario, browsers, scenarioVerdict, reason) {
  return (scenario.checks ?? []).map((check) => {
    if (check.requires_firefox && !browsers.includes("firefox")) {
      return {
        id: check.id,
        expected: check.description,
        observed: { reason: FIREFOX_UNAVAILABLE_REASON },
        verdict: "BLOCKED",
        reason: FIREFOX_UNAVAILABLE_REASON,
      };
    }
    const verdict = scenarioVerdict === "BLOCKED" ? "BLOCKED" : "FAIL";
    const checkReason = scenarioVerdict === "BLOCKED"
      ? reason
      : "required-check-did-not-record-an-outcome";
    return {
      id: check.id,
      expected: check.description,
      observed: { reason: checkReason },
      verdict,
      reason: checkReason,
    };
  });
}

export function summarizeN2Results(results, browsers) {
  const counts = { PASS: 0, FAIL: 0, BLOCKED: 0 };
  const safeResults = Array.isArray(results) ? results : [];
  let invalidEvidence = !Array.isArray(results);
  for (const result of safeResults) {
    if (result === null || typeof result !== "object" || Array.isArray(result) ||
        !Object.hasOwn(counts, result.verdict) || !Array.isArray(result.checks) ||
        result.checks.some((check) => check === null || typeof check !== "object" ||
          Array.isArray(check) || !Object.hasOwn(counts, check.verdict))) {
      invalidEvidence = true;
      counts.FAIL += 1;
      continue;
    }
    counts[result.verdict] += 1;
  }
  const blocked = blockedChecksFromResults(safeResults);
  const checkVerdicts = safeResults.flatMap((result) =>
    result !== null && typeof result === "object" && Array.isArray(result.checks)
      ? result.checks.filter((check) => check !== null && typeof check === "object").map((check) => check.verdict)
      : [],
  );
  let verdict = invalidEvidence || counts.FAIL > 0 || checkVerdicts.includes("FAIL")
    ? "FAIL"
    : counts.BLOCKED > 0 || blocked.length > 0
      ? "BLOCKED"
      : "PASS";
  if (!browsers.includes("firefox") && verdict === "PASS") {
    verdict = "BLOCKED";
    if (blocked.length === 0) {
      blocked.push({
        scenario_id: "browser-coverage",
        check_id: "firefox-n2-coverage",
        reason: FIREFOX_UNAVAILABLE_REASON,
      });
    }
  }
  return {
    verdict,
    counts,
    scenarios: safeResults,
    blocked,
    browser_coverage_status: blocked.length > 0 ? "incomplete" : "complete",
  };
}
