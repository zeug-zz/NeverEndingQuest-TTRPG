// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  copyFileSync,
  existsSync,
  readFileSync,
  constants as fsConstants,
} from "node:fs";
import { join, relative, resolve, sep } from "node:path";

export const PROVIDER_ATTEMPT_BUDGET = 30;
export const PROVIDER_ATTEMPT_LEDGER_NAME = "provider-attempt-ledger.jsonl";

const RUN_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;
const GUARD_NAME = "httpx-client-single-request";

export function providerAttemptLedgerPath(sandboxRoot, runId) {
  if (typeof runId !== "string" || !RUN_ID_PATTERN.test(runId)) {
    throw new Error("The provider attempt run ID is invalid.");
  }
  return resolve(sandboxRoot, "tmp", "n2", `provider-attempt-ledger-${runId}.jsonl`);
}

export function buildProviderAttemptEnvironment(environment, sandboxRoot, runId) {
  const ledgerPath = providerAttemptLedgerPath(sandboxRoot, runId);
  const childEnvironment = { ...environment };
  childEnvironment.NEQ_PROVIDER_ATTEMPT_BUDGET = String(PROVIDER_ATTEMPT_BUDGET);
  childEnvironment.NEQ_PROVIDER_ATTEMPT_LEDGER = ledgerPath;
  childEnvironment.NEQ_PROVIDER_ATTEMPT_RUN_ID = runId;
  return { environment: childEnvironment, ledgerPath };
}

export function parseProviderAttemptLedger(contents, { budget = PROVIDER_ATTEMPT_BUDGET, runId }) {
  if (typeof contents !== "string" || contents.length === 0) {
    throw new Error("The provider attempt ledger is missing or empty.");
  }
  if (!contents.endsWith("\n")) {
    throw new Error("The provider attempt ledger has an incomplete record.");
  }
  const lines = contents.slice(0, -1).split(/\r?\n/);
  if (lines.some((line) => line.length === 0)) {
    throw new Error("The provider attempt ledger contains an empty record.");
  }
  let records;
  try {
    records = lines.map((line) => JSON.parse(line));
  } catch {
    throw new Error("The provider attempt ledger is malformed.");
  }
  const header = records[0];
  if (!header || typeof header !== "object" || Array.isArray(header) ||
      header.event !== "header" || header.schema_version !== 1 ||
      header.budget !== budget || header.run_id !== runId) {
    throw new Error("The provider attempt ledger header does not match this run.");
  }

  let reservationCount = 0;
  let refusalCount = 0;
  let active = false;
  const activationPids = [];
  const refusals = [];
  for (const record of records.slice(1)) {
    if (!record || typeof record !== "object" || Array.isArray(record) ||
        record.schema_version !== 1 || record.run_id !== runId || record.budget !== budget) {
      throw new Error("The provider attempt ledger contains an invalid record.");
    }
    if (record.event === "activated") {
      if (record.transport_guard !== GUARD_NAME || !Number.isInteger(record.pid)) {
        throw new Error("The provider attempt activation record is invalid.");
      }
      activationPids.push(record.pid);
      active = true;
    } else if (record.event === "reservation") {
      if (!active) {
        throw new Error("The provider attempt reservation precedes activation.");
      }
      reservationCount += 1;
      if (record.reservation_number !== reservationCount) {
        throw new Error("The provider attempt reservation sequence is invalid.");
      }
    } else if (record.event === "refusal") {
      refusalCount += 1;
      if (!active || reservationCount < budget || record.reservation_number !== budget + 1 ||
          record.reason !== "budget_exhausted") {
        throw new Error("The provider attempt refusal record is invalid.");
      }
      refusals.push(record);
    } else {
      throw new Error("The provider attempt ledger contains an unknown event.");
    }
  }
  if (reservationCount > budget) {
    throw new Error("The provider attempt ledger exceeds its configured budget.");
  }
  return {
    active,
    budget,
    activation_pids: activationPids,
    reservation_count: reservationCount,
    refusal_count: refusalCount,
    refusals,
  };
}

export function providerAttemptBudgetVerdict(report) {
  if (!report || report.active !== true) {
    return { verdict: "BLOCKED", reason: "provider_budget_not_active" };
  }
  if (report.refusal_count > 0) {
    return {
      verdict: "FAIL",
      reason: "budget_exhausted; outbound dispatch was refused before transport send",
    };
  }
  if (report.reservation_count >= report.budget) {
    return { verdict: "BLOCKED", reason: "provider_budget_consumed_before_next_gameplay_input" };
  }
  return { verdict: "PASS", reason: null };
}

export function requireProviderAttemptBudgetActive(ledgerPath, { budget = PROVIDER_ATTEMPT_BUDGET, runId }) {
  if (!existsSync(ledgerPath)) {
    throw new Error("The managed host did not report an active provider attempt budget.");
  }
  const report = parseProviderAttemptLedger(readFileSync(ledgerPath, "utf8"), { budget, runId });
  if (!report.active) {
    throw new Error("The managed host did not report an active provider attempt budget.");
  }
  return report;
}

export function requireProviderAttemptBudgetForGameplay({
  managed,
  ledgerPath,
  budget = PROVIDER_ATTEMPT_BUDGET,
  runId,
}) {
  if (managed !== true) {
    throw new Error("Live N2 gameplay requires managed provider-attempt enforcement.");
  }
  const report = requireProviderAttemptBudgetActive(ledgerPath, { budget, runId });
  const decision = providerAttemptBudgetVerdict(report);
  if (decision.verdict !== "PASS") {
    throw new Error(decision.reason);
  }
  return report;
}

export function copyProviderAttemptLedger(ledgerPath, evidenceDirectory) {
  const destination = join(evidenceDirectory, PROVIDER_ATTEMPT_LEDGER_NAME);
  if (!existsSync(ledgerPath)) {
    return { copied: false, destination: null };
  }
  copyFileSync(ledgerPath, destination, fsConstants.COPYFILE_EXCL);
  return {
    copied: true,
    destination: relative(evidenceDirectory, destination).split(sep).join("/"),
  };
}
