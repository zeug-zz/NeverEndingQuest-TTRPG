// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  buildProviderAttemptEnvironment,
  copyProviderAttemptLedger,
  parseProviderAttemptLedger,
  providerAttemptBudgetVerdict,
  providerAttemptLedgerPath,
  requireProviderAttemptBudgetActive,
  requireProviderAttemptBudgetForGameplay,
  PROVIDER_ATTEMPT_BUDGET,
} from "./provider-attempt-budget.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const N2_TMP = join(REPOSITORY_ROOT, "tmp", "n2");

function makeScratchDirectory() {
  mkdirSync(N2_TMP, { recursive: true });
  return mkdtempSync(join(N2_TMP, "provider-attempt-budget-test-"));
}

function ledgerText(runId, { activated = true, reservations = 0, refusals = 0 } = {}) {
  const records = [{
    event: "header",
    schema_version: 1,
    budget: PROVIDER_ATTEMPT_BUDGET,
    run_id: runId,
  }];
  if (activated) {
    records.push({
      event: "activated",
      schema_version: 1,
      pid: 123,
      budget: PROVIDER_ATTEMPT_BUDGET,
      run_id: runId,
      transport_guard: "httpx-client-single-request",
    });
  }
  for (let index = 1; index <= reservations; index += 1) {
    records.push({
      event: "reservation",
      schema_version: 1,
      pid: 123,
      budget: PROVIDER_ATTEMPT_BUDGET,
      run_id: runId,
      reservation_number: index,
      host: "api.example.invalid",
      method: "POST",
      path: "/v1/chat/completions",
    });
  }
  for (let index = 0; index < refusals; index += 1) {
    records.push({
      event: "refusal",
      schema_version: 1,
      pid: 123,
      budget: PROVIDER_ATTEMPT_BUDGET,
      run_id: runId,
      reservation_number: PROVIDER_ATTEMPT_BUDGET + 1,
      reason: "budget_exhausted",
      host: "api.example.invalid",
      method: "POST",
      path: "/v1/chat/completions",
    });
  }
  return `${records.map((record) => JSON.stringify(record)).join("\n")}\n`;
}

test("managed host environment pins the run-wide budget and sandbox ledger", () => {
  const scratch = makeScratchDirectory();
  try {
    const sandboxRoot = join(scratch, "tmp", "combat_capture");
    const runId = "n2-test-run";
    const configured = buildProviderAttemptEnvironment({
      NEQ_PROVIDER_ATTEMPT_BUDGET: "900",
      NEQ_PROVIDER_ATTEMPT_LEDGER: "outside",
      KEEP_ME: "yes",
    }, sandboxRoot, runId);

    assert.equal(configured.environment.NEQ_PROVIDER_ATTEMPT_BUDGET, "30");
    assert.equal(configured.environment.NEQ_PROVIDER_ATTEMPT_LEDGER, configured.ledgerPath);
    assert.equal(configured.environment.NEQ_PROVIDER_ATTEMPT_RUN_ID, runId);
    assert.equal(configured.environment.KEEP_ME, "yes");
    assert.equal(configured.ledgerPath, providerAttemptLedgerPath(sandboxRoot, runId));
    assert.equal(configured.ledgerPath.startsWith(`${sandboxRoot}/tmp/n2/`), true);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("driver requires an active ledger before launching gameplay input", () => {
  const scratch = makeScratchDirectory();
  try {
    const runId = "n2-active-check";
    const ledgerPath = join(scratch, "provider-attempt-ledger.jsonl");
    writeFileSync(ledgerPath, ledgerText(runId, { activated: false }), { encoding: "ascii" });
    assert.throws(
      () => requireProviderAttemptBudgetActive(ledgerPath, { budget: 30, runId }),
      /did not report an active provider attempt budget/,
    );

    writeFileSync(ledgerPath, ledgerText(runId), { encoding: "ascii" });
    const report = requireProviderAttemptBudgetActive(ledgerPath, { budget: 30, runId });
    assert.equal(providerAttemptBudgetVerdict(report).verdict, "PASS");
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("Playwright gameplay preflight rejects non-managed or inactive budget runs", () => {
  const scratch = makeScratchDirectory();
  try {
    const runId = "n2-gameplay-preflight";
    const ledgerPath = join(scratch, "provider-attempt-ledger.jsonl");
    writeFileSync(ledgerPath, ledgerText(runId), { encoding: "ascii" });
    assert.throws(
      () => requireProviderAttemptBudgetForGameplay({
        managed: false,
        ledgerPath,
        budget: PROVIDER_ATTEMPT_BUDGET,
        runId,
      }),
      /requires managed provider-attempt enforcement/,
    );
    const report = requireProviderAttemptBudgetForGameplay({
      managed: true,
      ledgerPath,
      budget: PROVIDER_ATTEMPT_BUDGET,
      runId,
    });
    assert.equal(report.active, true);
    writeFileSync(ledgerPath, ledgerText(runId, { activated: false }), { encoding: "ascii" });
    assert.throws(
      () => requireProviderAttemptBudgetForGameplay({
        managed: true,
        ledgerPath,
        budget: PROVIDER_ATTEMPT_BUDGET,
        runId,
      }),
      /did not report an active provider attempt budget/,
    );
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("non-managed live runs are refused before evidence creation or endpoint access", () => {
  const evidenceDirectory = join(N2_TMP, `provider-budget-unmanaged-${process.pid}`);
  assert.equal(existsSync(evidenceDirectory), false);
  const gateScript = fileURLToPath(new URL("./n2-gate.mjs", import.meta.url));
  const result = spawnSync(
    process.execPath,
    [gateScript, "--party-size", "1", "--evidence-dir", evidenceDirectory],
    {
      cwd: REPOSITORY_ROOT,
      encoding: "utf8",
      env: {
        ...process.env,
        NEQ_N2_HOST_URL: "",
        NEQ_N2_PLAYER_URL: "",
        NEQ_N2_PLAYER_PASSWORD: "",
      },
    },
  );
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Live N2 runs require --manage-sandbox-host/);
  assert.equal(existsSync(evidenceDirectory), false);
});

test("cap refusal produces a non-PASS driver verdict with a refusal reason", () => {
  const runId = "n2-refused";
  const report = parseProviderAttemptLedger(
    ledgerText(runId, { reservations: PROVIDER_ATTEMPT_BUDGET, refusals: 1 }),
    { budget: PROVIDER_ATTEMPT_BUDGET, runId },
  );
  const verdict = providerAttemptBudgetVerdict(report);
  assert.equal(report.refusal_count, 1);
  assert.equal(verdict.verdict, "FAIL");
  assert.match(verdict.reason, /budget_exhausted/);
});

test("a consumed budget blocks the next gameplay input even before a refusal", () => {
  const runId = "n2-consumed";
  const report = parseProviderAttemptLedger(
    ledgerText(runId, { reservations: PROVIDER_ATTEMPT_BUDGET }),
    { budget: PROVIDER_ATTEMPT_BUDGET, runId },
  );
  assert.equal(providerAttemptBudgetVerdict(report).verdict, "BLOCKED");
});

test("managed teardown copies the separate transport ledger into evidence", () => {
  const scratch = makeScratchDirectory();
  try {
    const runId = "n2-copy-ledger";
    const ledgerPath = join(scratch, "source.jsonl");
    const evidenceDirectory = join(scratch, "evidence");
    mkdirSync(evidenceDirectory);
    const contents = ledgerText(runId, { reservations: 1 });
    writeFileSync(ledgerPath, contents, { encoding: "ascii" });

    const copied = copyProviderAttemptLedger(ledgerPath, evidenceDirectory);
    assert.equal(copied.copied, true);
    assert.equal(copied.destination, "provider-attempt-ledger.jsonl");
    assert.equal(readFileSync(join(evidenceDirectory, copied.destination), "ascii"), contents);
    assert.equal(Object.hasOwn(parseProviderAttemptLedger(contents, { budget: 30, runId }), "provider_identity"), false);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
