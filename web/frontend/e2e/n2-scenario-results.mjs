// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { existsSync, lstatSync, readFileSync } from "node:fs";
import { Buffer } from "node:buffer";

export const MAX_N2_SCENARIO_EVIDENCE_BYTES = 262_144;

export function readN2ScenarioResults(path) {
  try {
    if (!existsSync(path)) {
      return result("missing", [], [{ line: 0, reason: "scenario-results-file-missing" }]);
    }
    const fileStat = lstatSync(path);
    if (fileStat.isSymbolicLink() || !fileStat.isFile()) {
      return result("invalid", [], [{ line: 0, reason: "scenario-results-file-invalid" }]);
    }
    const contents = readFileSync(path, "utf8");
    if (Buffer.byteLength(contents, "utf8") > MAX_N2_SCENARIO_EVIDENCE_BYTES) {
      return result("invalid", [], [{ line: 0, reason: "scenario-results-file-too-large" }]);
    }
    if (contents.length === 0 || !contents.trim()) return result("empty", [], []);

    const records = [];
    const errors = [];
    for (const [index, line] of contents.split(/\r?\n/).entries()) {
      if (!line.trim()) continue;
      try {
        records.push(JSON.parse(line));
      } catch {
        errors.push({ line: index + 1, reason: "malformed-json" });
      }
    }
    return result(errors.length > 0 ? "malformed" : "present", records, errors);
  } catch {
    return result("unreadable", [], [{ line: 0, reason: "scenario-results-file-unreadable" }]);
  }
}

export function applySetupFailureScenarioResultPolicy(scenarioEvidence, setupFailureStatus) {
  if (setupFailureStatus === "valid" &&
      ["missing", "empty"].includes(scenarioEvidence.fileStatus)) {
    return { ...scenarioEvidence, errors: [] };
  }

  if (setupFailureStatus === "valid" && scenarioEvidence.fileStatus === "present") {
    return {
      ...scenarioEvidence,
      errors: [
        ...scenarioEvidence.errors,
        { line: 0, reason: "scenario-results-present-after-setup-failure" },
      ],
    };
  }

  if (setupFailureStatus !== "valid" && scenarioEvidence.fileStatus === "empty") {
    return {
      ...scenarioEvidence,
      errors: [{ line: 0, reason: "scenario-results-file-empty" }],
    };
  }
  return scenarioEvidence;
}

function result(fileStatus, records, errors) {
  return { records, errors, fileStatus };
}
