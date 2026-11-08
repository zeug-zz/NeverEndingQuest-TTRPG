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
  return results.flatMap((scenario) => (scenario.checks ?? [])
    .filter((check) => check.verdict === "BLOCKED")
    .map((check) => ({
      scenario_id: scenario.id,
      check_id: check.id,
      reason: check.reason ?? check.observed?.reason ?? "blocked-check-without-reason",
    })));
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
  for (const result of results) {
    if (Object.hasOwn(counts, result.verdict)) counts[result.verdict] += 1;
  }
  const blocked = blockedChecksFromResults(results);
  const checkVerdicts = results.flatMap((result) => (result.checks ?? []).map((check) => check.verdict));
  let verdict = counts.FAIL > 0 || checkVerdicts.includes("FAIL")
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
    scenarios: results,
    blocked,
    browser_coverage_status: blocked.length > 0 ? "incomplete" : "complete",
  };
}
