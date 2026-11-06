// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  appendFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import type { TestInfo } from "playwright/test";
import { isSensitiveEvidenceField, redactEvidenceText } from "./redaction.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const TMP_ROOT = resolve(REPOSITORY_ROOT, "tmp");
const SCENARIO_CATALOG = JSON.parse(
  readFileSync(new URL("./scenarios.json", import.meta.url), "utf8"),
) as readonly ScenarioDefinition[];
export type Verdict = "PASS" | "FAIL" | "BLOCKED";

export type ScenarioDefinition = Readonly<{
  id: string;
  description: string;
}>;

export type ScenarioResult = Readonly<{
  id: string;
  expected: unknown;
  observed: unknown;
  verdict: Verdict;
  artifacts: readonly string[];
  recorded_at_utc: string;
}>;

export const N2_SCENARIOS = SCENARIO_CATALOG;

export function evidenceDirectory(): string {
  const configured = process.env.NEQ_N2_EVIDENCE_DIR;
  if (!configured) throw new Error("NEQ_N2_EVIDENCE_DIR is required for a live N2 run.");
  const candidate = resolve(isAbsolute(configured) ? configured : join(REPOSITORY_ROOT, configured));
  const relativeToTmp = relative(TMP_ROOT, candidate);
  if (
    !relativeToTmp ||
    relativeToTmp === "." ||
    relativeToTmp === ".." ||
    relativeToTmp.startsWith(`..${sep}`) ||
    isAbsolute(relativeToTmp)
  ) {
    throw new Error("N2 evidence must be written below this repository's tmp/ directory.");
  }

  let current = REPOSITORY_ROOT;
  for (const component of ["tmp", ...relativeToTmp.split(sep)]) {
    current = join(current, component);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
      throw new Error("N2 evidence paths must not traverse symlinks.");
    }
  }
  return candidate;
}

export function scenarioAnnotation(
  testInfo: TestInfo,
  id: string,
  expected: unknown,
): void {
  if (!N2_SCENARIOS.some((scenario) => scenario.id === id)) {
    throw new Error(`Unknown N2 scenario id: ${id}`);
  }
  testInfo.annotations.push(
    { type: "n2-scenario-id", description: id },
    { type: "n2-expected", description: JSON.stringify(expected) },
  );
}

export function scenarioObservation(testInfo: TestInfo, observed: unknown): void {
  testInfo.annotations.push({ type: "n2-observed", description: JSON.stringify(observed) });
}

export function scenarioBlocked(testInfo: TestInfo, reason: string): void {
  testInfo.annotations.push({ type: "n2-blocked", description: reason });
  scenarioObservation(testInfo, { status: "BLOCKED", reason });
}

export function updateRunMetadata(patch: Record<string, unknown>): void {
  const path = join(evidenceDirectory(), "run.json");
  if (!existsSync(path) || lstatSync(path).isSymbolicLink()) {
    throw new Error("N2 run.json is missing or is not a regular evidence file.");
  }
  const current = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
  const next = { ...current, ...redactValue(patch) as Record<string, unknown> };
  atomicJsonWrite(path, next);
}

export function writeConsoleEvidence(
  scenarioId: string,
  contextName: string,
  messageType: string,
  messageText: string,
): void {
  const path = join(evidenceDirectory(), "console.jsonl");
  const record = redactValue({
    scenario_id: scenarioId,
    context: contextName,
    type: messageType,
    text: sanitizeText(messageText),
    recorded_at_utc: new Date().toISOString(),
  });
  appendFileSync(path, `${JSON.stringify(record)}\n`, { encoding: "utf8", flag: "a" });
}

export function writeScenarioEvidence(result: ScenarioResult): void {
  const path = join(evidenceDirectory(), "scenarios.jsonl");
  const safe = redactValue(result);
  appendFileSync(path, `${JSON.stringify(safe)}\n`, { encoding: "utf8", flag: "a" });
}

export function ensureEvidenceFolders(): void {
  const directory = evidenceDirectory();
  mkdirSync(join(directory, "screenshots"), { recursive: true });
}

export function redactValue<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => redactValue(item)) as T;
  }
  if (value !== null && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value)) {
      result[key] = isSensitiveField(key) ? "[REDACTED]" : redactValue(item);
    }
    return result as T;
  }
  if (typeof value === "string") return sanitizeText(value) as T;
  return value;
}

export function sanitizeText(value: string): string {
  return redactEvidenceText(
    value,
    [process.env.NEQ_N2_PLAYER_PASSWORD, process.env.NEQ_PLAYER_PASSWORD_VERIFIER],
    4096,
  );
}

export function annotation(testInfo: TestInfo, type: string): string | undefined {
  return testInfo.annotations.find((item) => item.type === type)?.description;
}

export function catalogDescription(id: string): string {
  return N2_SCENARIOS.find((scenario) => scenario.id === id)?.description ?? "No scenario description found.";
}

export function relativeEvidencePath(path: string): string {
  return relative(evidenceDirectory(), path).split(sep).join("/");
}

export function atomicJsonWrite(path: string, payload: unknown): void {
  const temporary = `${path}.pending`;
  writeFileSync(temporary, `${JSON.stringify(redactValue(payload), null, 2)}\n`, {
    encoding: "utf8",
    flag: "wx",
  });
  renameSync(temporary, path);
}

function isSensitiveField(key: string): boolean {
  return isSensitiveEvidenceField(key);
}
