// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import {
  mkdtempSync,
  mkdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  applySetupFailureScenarioResultPolicy,
  readN2ScenarioResults,
} from "./n2-scenario-results.mjs";

const PROJECT_ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const TEST_ROOT = join(PROJECT_ROOT, "tmp", "n2", "setup-evidence");

test("missing and empty results remain distinct only for a valid beforeAll setup failure", () => {
  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "scenario-results-"));
  const path = join(directory, "scenarios.jsonl");
  try {
    const missing = readN2ScenarioResults(path);
    assert.equal(missing.fileStatus, "missing");
    assert.deepEqual(missing.errors, [{ line: 0, reason: "scenario-results-file-missing" }]);
    const setupMissing = applySetupFailureScenarioResultPolicy(missing, "valid");
    assert.equal(setupMissing.fileStatus, "missing");
    assert.deepEqual(setupMissing.records, []);
    assert.deepEqual(setupMissing.errors, []);

    writeFileSync(path, "\n  \n", { encoding: "utf8" });
    const empty = readN2ScenarioResults(path);
    assert.equal(empty.fileStatus, "empty");
    assert.deepEqual(applySetupFailureScenarioResultPolicy(empty, "valid").errors, []);
    assert.deepEqual(applySetupFailureScenarioResultPolicy(empty, "missing").errors, [
      { line: 0, reason: "scenario-results-file-empty" },
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("malformed or contradictory scenario results are not excused by setup failure evidence", () => {
  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "scenario-malformed-"));
  const path = join(directory, "scenarios.jsonl");
  try {
    writeFileSync(path, "{bad json\n", { encoding: "utf8" });
    const malformed = readN2ScenarioResults(path);
    assert.equal(malformed.fileStatus, "malformed");
    assert.equal(applySetupFailureScenarioResultPolicy(malformed, "valid").errors[0].reason, "malformed-json");

    writeFileSync(path, `${JSON.stringify({ id: "unexpected" })}\n`, { encoding: "utf8" });
    const contradictory = applySetupFailureScenarioResultPolicy(readN2ScenarioResults(path), "valid");
    assert.equal(contradictory.fileStatus, "present");
    assert.equal(contradictory.errors[0].reason, "scenario-results-present-after-setup-failure");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("scenario evidence reader rejects symlinks and oversized artifacts", () => {
  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "scenario-safety-"));
  const target = join(directory, "target.jsonl");
  const link = join(directory, "scenarios.jsonl");
  try {
    writeFileSync(target, "{}\n", { encoding: "utf8" });
    symlinkSync(target, link);
    assert.equal(readN2ScenarioResults(link).fileStatus, "invalid");
    rmSync(link);
    writeFileSync(link, "x".repeat(262_145), { encoding: "utf8" });
    assert.equal(readN2ScenarioResults(link).fileStatus, "invalid");
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
