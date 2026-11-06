// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { defineConfig } from "playwright/test";
import { existsSync, lstatSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { N2_PLAYWRIGHT_PROJECT } from "./e2e/browser-contract.mjs";

const FRONTEND_ROOT = dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = resolve(FRONTEND_ROOT, "../..");
const TMP_ROOT = resolve(REPOSITORY_ROOT, "tmp");
const configuredEvidenceDir = process.env.NEQ_N2_EVIDENCE_DIR;
const evidenceDir = configuredEvidenceDir
  ? resolve(isAbsolute(configuredEvidenceDir) ? configuredEvidenceDir : join(REPOSITORY_ROOT, configuredEvidenceDir))
  : resolve(TMP_ROOT, "n2-playwright-test-results");
const relativeEvidenceDir = relative(TMP_ROOT, evidenceDir);
if (
  !relativeEvidenceDir ||
  relativeEvidenceDir === "." ||
  relativeEvidenceDir === ".." ||
  relativeEvidenceDir.startsWith(`..${sep}`) ||
  isAbsolute(relativeEvidenceDir)
) {
  throw new Error("Playwright output must remain below repository tmp/.");
}
let checkedPath = REPOSITORY_ROOT;
for (const component of ["tmp", ...relativeEvidenceDir.split(sep)]) {
  checkedPath = join(checkedPath, component);
  if (existsSync(checkedPath) && lstatSync(checkedPath).isSymbolicLink()) {
    throw new Error("Playwright output path must not traverse symlinks.");
  }
}

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  outputDir: join(evidenceDir, "playwright-test-results"),
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: { trace: "off", screenshot: "off", video: "off" },
  projects: [{ name: N2_PLAYWRIGHT_PROJECT }],
});
