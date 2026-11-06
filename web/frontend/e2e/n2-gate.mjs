// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  existsSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { createN2BrowserInstances, hasN2BrowserVersions, N2_PLAYWRIGHT_PROJECT } from "./browser-contract.mjs";
import { SandboxHostManager, validateManagedSandboxRoot, validateSandboxPython } from "./managed-host.mjs";
import { readVerifiedBundleSnapshot, runManagedLifecycleScenarios } from "./managed-lifecycle.mjs";
import { redactEvidenceText } from "./redaction.mjs";
import { readWorkspaceIdentity } from "./workspace-identity.mjs";

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPOSITORY_ROOT = resolve(FRONTEND_ROOT, "../..");
const TMP_ROOT = resolve(REPOSITORY_ROOT, "tmp");
const SCENARIO_CATALOG = JSON.parse(
  readFileSync(new URL("./scenarios.json", import.meta.url), "utf8"),
);
let activePlaywrightProcess = null;

const HELP = `N2 real-browser gate driver

Usage:
  npm --prefix web/frontend run test:n2-gate -- --party-size 1|4 \\
    --evidence-dir tmp/router-rollout/v2-network/n2-<run-id>

Required runtime environment (values are never printed or written to evidence):
  NEQ_N2_HOST_URL            Must be exactly http://127.0.0.1:8360
  NEQ_N2_PLAYER_URL          Must be exactly http://127.0.0.1:8370
  NEQ_N2_PLAYER_PASSWORD     Player login password, read only from the environment
  NEQ_N2_PARTY_SIZE          1 or 4; overridden by --party-size when supplied
  NEQ_N2_EVIDENCE_DIR        Evidence directory, overridden by --evidence-dir

Options:
  --party-size 1|4           Required unless NEQ_N2_PARTY_SIZE is set
  --evidence-dir <path>      Required unless NEQ_N2_EVIDENCE_DIR is set; must be below repo tmp/
  --manage-sandbox-host      Start/restart/stop only this run's verified tmp/combat_capture host
  --dry-run                  Print the plan without contacting endpoints or creating files
  --help                     Show this help

The suite always launches Player A in system Chrome (Playwright chromium with
channel: "chrome") and Player B in Playwright Firefox 1.65.0. The facilitator
UI uses a separate BrowserContext from Player A's Chrome instance.
All three browser roles and their actual versions are recorded in run.json. No
browser selection flag is supported; WebKit cannot replace either required player.

The driver refuses port 8357, non-loopback URLs, and any host/player URL other than
the fixed 8360/8370 pair. By default it never starts, stops, or signals a server,
changes a bundle, prepares a campaign, or writes outside the selected project tmp/
directory. --manage-sandbox-host is the only lifecycle opt-in: it starts the host
from the exact prepared tmp/combat_capture tree, refuses occupied ports, manages
only its own detached process group, and temporarily removes/corrupts only that
sandbox's web/frontend/dist before digest-verifying restoration. It never seeds or
prepares the sandbox.
The Playwright suite uses separate Chrome and Firefox browser instances for the
players and a third host UI context. No browser storage state, HAR, or trace archive
is written. Structured console evidence redacts cookie, authorization, password,
verifier, and CSRF values. A live run requires a clean checkout; its commit and
clean-tree state are recorded in run.json.

Without --manage-sandbox-host, the server-instance-change, missing-bundle, and
broken-bundle scenarios are explicitly recorded BLOCKED. With the flag, the driver
exercises those phases against only its own verified sandbox process. Any BLOCKED or
FAIL verdict makes the final driver exit nonzero. Socket-only evidence is never a PASS.
`;

function usageError(message) {
  console.error(`${message}\n\nRun with --help for usage.`);
  process.exit(2);
}

function parseArguments(argv) {
  const options = {
    partySize: null,
    evidenceDir: process.env.NEQ_N2_EVIDENCE_DIR ?? null,
    manageSandboxHost: false,
    dryRun: false,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--help" || token === "-h") {
      console.log(HELP);
      process.exit(0);
    }
    if (token === "--dry-run") {
      options.dryRun = true;
      continue;
    }
    if (token === "--manage-sandbox-host") {
      options.manageSandboxHost = true;
      continue;
    }
    if (["--party-size", "--evidence-dir"].includes(token)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) usageError(`${token} requires a value`);
      index += 1;
      if (token === "--party-size") options.partySize = value;
      if (token === "--evidence-dir") options.evidenceDir = value;
      continue;
    }
    usageError(`Unknown option: ${token}`);
  }

  options.partySize ??= process.env.NEQ_N2_PARTY_SIZE ?? null;
  if (options.partySize !== null && !["1", "4"].includes(options.partySize)) {
    usageError("--party-size and NEQ_N2_PARTY_SIZE must be 1 or 4");
  }
  if (options.evidenceDir !== null) {
    options.evidenceDir = resolveEvidenceDirectory(options.evidenceDir);
  }
  return options;
}

function resolveEvidenceDirectory(value) {
  const candidate = resolve(isAbsolute(value) ? value : join(REPOSITORY_ROOT, value));
  const relativeToTmp = relative(TMP_ROOT, candidate);
  if (!relativeToTmp || relativeToTmp === "." || relativeToTmp.startsWith(`..${sep}`) || relativeToTmp === ".." || isAbsolute(relativeToTmp)) {
    usageError("Evidence directory must be a child of this repository's tmp/ directory");
  }

  let current = REPOSITORY_ROOT;
  for (const component of ["tmp", ...relativeToTmp.split(sep)]) {
    current = join(current, component);
    if (existsSync(current) && lstatSync(current).isSymbolicLink()) {
      usageError("Evidence directory must not traverse symlinks");
    }
  }
  return candidate;
}

function validateEndpoint(name, value, expectedPort) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    usageError(`${name} must be a valid URL`);
  }
  if (parsed.port === "8357") usageError(`${name} must never use port 8357`);
  if (
    parsed.protocol !== "http:" ||
    parsed.hostname !== "127.0.0.1" ||
    parsed.port !== String(expectedPort) ||
    parsed.pathname !== "/" ||
    parsed.search !== "" ||
    parsed.hash !== "" ||
    parsed.username !== "" ||
    parsed.password !== ""
  ) {
    usageError(`${name} must be exactly http://127.0.0.1:${expectedPort}`);
  }
  return parsed.origin;
}

function utcNow() {
  return new Date().toISOString();
}

function makeRunId() {
  const timestamp = new Date().toISOString().replace(/[-:.]/g, "");
  const suffix = randomBytes(4).toString("hex");
  return `n2-${timestamp}-${suffix}`;
}

function atomicJsonWrite(path, payload) {
  const temporary = `${path}.pending`;
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  renameSync(temporary, path);
}

function appendScenario(path, result) {
  writeFileSync(path, `${JSON.stringify(result)}\n`, { encoding: "utf8", flag: "a" });
}

function readScenarioResults(path) {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function summarize(results) {
  const counts = { PASS: 0, FAIL: 0, BLOCKED: 0 };
  for (const result of results) {
    if (Object.hasOwn(counts, result.verdict)) counts[result.verdict] += 1;
  }
  const verdict = counts.FAIL > 0 ? "FAIL" : counts.BLOCKED > 0 ? "BLOCKED" : "PASS";
  return { verdict, counts, scenarios: results };
}

function sanitizeOutput(text, password) {
  return redactEvidenceText(
    text,
    [password, process.env.NEQ_PLAYER_PASSWORD_VERIFIER],
    120_000,
  ).slice(-120_000);
}

function runPlaywright(playwrightPath, args, environment) {
  return new Promise((resolveRun) => {
    const runner = spawn(playwrightPath, args, {
      cwd: FRONTEND_ROOT,
      env: environment,
      stdio: ["ignore", "pipe", "pipe"],
    });
    activePlaywrightProcess = runner;
    let stdout = "";
    let stderr = "";
    let spawnError = null;
    const maxBuffer = 2 * 1024 * 1024;
    const collect = (current, chunk) => `${current}${chunk}`.slice(-maxBuffer);
    runner.stdout.setEncoding("utf8");
    runner.stderr.setEncoding("utf8");
    runner.stdout.on("data", (chunk) => { stdout = collect(stdout, chunk); });
    runner.stderr.on("data", (chunk) => { stderr = collect(stderr, chunk); });
    runner.once("error", (error) => { spawnError = error; });
    runner.once("close", (status, signal) => {
      if (activePlaywrightProcess === runner) activePlaywrightProcess = null;
      resolveRun({ status, signal, error: spawnError, stdout, stderr });
    });
  });
}

const options = parseArguments(process.argv.slice(2));
if (options.dryRun) {
  console.log(JSON.stringify({
    mode: "dry-run",
    party_size: options.partySize,
    browser_instances: createN2BrowserInstances(),
    playwright_project: N2_PLAYWRIGHT_PROJECT,
    evidence_dir: options.evidenceDir,
    manage_sandbox_host: options.manageSandboxHost,
    endpoint_contract: {
      host: "http://127.0.0.1:8360",
      player: "http://127.0.0.1:8370",
      forbidden_port: 8357,
    },
    scenarios: SCENARIO_CATALOG,
    no_server_or_campaign_side_effects: true,
  }, null, 2));
  process.exit(0);
}

if (options.partySize === null) usageError("Set --party-size 1|4 or NEQ_N2_PARTY_SIZE");
if (!options.evidenceDir) usageError("Set --evidence-dir or NEQ_N2_EVIDENCE_DIR");
const hostUrl = validateEndpoint("NEQ_N2_HOST_URL", process.env.NEQ_N2_HOST_URL ?? "", 8360);
const playerUrl = validateEndpoint("NEQ_N2_PLAYER_URL", process.env.NEQ_N2_PLAYER_URL ?? "", 8370);
if (!process.env.NEQ_N2_PLAYER_PASSWORD) usageError("NEQ_N2_PLAYER_PASSWORD must be set in the environment");
const workspaceIdentity = readWorkspaceIdentity(REPOSITORY_ROOT);
if (workspaceIdentity.git_sha === "unknown") usageError("A readable git commit SHA is required for an N2 live run");
if (workspaceIdentity.git_worktree_state !== "clean") {
  usageError("N2 live runs require a clean git checkout; no evidence directory or server was started");
}
if (!existsSync(join(REPOSITORY_ROOT, "tmp"))) usageError("Repository tmp/ directory is required for evidence");
if (existsSync(options.evidenceDir)) usageError("Evidence directory already exists; select a unique run directory");

const runId = makeRunId();
const relativeEvidenceDir = relative(REPOSITORY_ROOT, options.evidenceDir).split(sep).join("/");
const scenarioFile = join(options.evidenceDir, "scenarios.jsonl");
const runFile = join(options.evidenceDir, "run.json");
const summaryFile = join(options.evidenceDir, "summary.json");
mkdirSync(join(options.evidenceDir, "screenshots"), { recursive: true });

const runRecord = {
  schema_version: 1,
  run_id: runId,
  started_at_utc: utcNow(),
  finished_at_utc: null,
  ...workspaceIdentity,
  client_build_id: null,
  browser_instances: createN2BrowserInstances(),
  os: { platform: process.platform, release: (await import("node:os")).release(), arch: process.arch },
  party_size: Number(options.partySize),
  scenario_list: SCENARIO_CATALOG,
  provider_identity: "not-observed-by-browser-driver; operator review required if runtime invokes provider",
  endpoints: { host: hostUrl, player: playerUrl },
  evidence_dir: relativeEvidenceDir,
  managed_sandbox_host: options.manageSandboxHost ? { enabled: true, sandbox_root: "tmp/combat_capture" } : { enabled: false },
  verdict: "PENDING",
};
writeFileSync(runFile, `${JSON.stringify(runRecord, null, 2)}\n`, { encoding: "utf8", flag: "wx" });

const playwright = join(FRONTEND_ROOT, "node_modules", ".bin", "playwright");
let child = null;
let managedHost = null;
let startupError = null;
let lifecycleResults = [];
let managedTeardownStatus = options.manageSandboxHost ? "not-started" : "not-applicable";
let requestedSignal = null;
let signalStopError = null;
let signalStopPromise = null;
const shutdownController = new AbortController();
const handleSignal = (signal) => {
  requestedSignal ??= signal;
  if (!shutdownController.signal.aborted) shutdownController.abort();
  if (activePlaywrightProcess && activePlaywrightProcess.exitCode === null) {
    try {
      activePlaywrightProcess.kill(signal);
    } catch {
      // The runner may already be exiting as the signal is delivered.
    }
  }
  if (managedHost !== null && signalStopPromise === null) {
    signalStopPromise = managedHost.stop().catch((error) => {
      signalStopError = error;
    });
  }
};
const handleSigint = () => handleSignal("SIGINT");
const handleSigterm = () => handleSignal("SIGTERM");
process.on("SIGINT", handleSigint);
process.on("SIGTERM", handleSigterm);
if (options.manageSandboxHost) {
  try {
    const sandboxRoot = validateManagedSandboxRoot(REPOSITORY_ROOT);
    const pythonPath = validateSandboxPython(REPOSITORY_ROOT);
    readVerifiedBundleSnapshot(REPOSITORY_ROOT, sandboxRoot);
    managedHost = new SandboxHostManager({ repositoryRoot: REPOSITORY_ROOT, sandboxRoot, pythonPath });
    const processInfo = await managedHost.start({
      playerExpected: true,
      signal: shutdownController.signal,
    });
    managedTeardownStatus = "running";
    runRecord.managed_sandbox_host = {
      enabled: true,
      sandbox_root: "tmp/combat_capture",
      ownership: "driver-spawned-detached-process-group",
      ...processInfo,
    };
    atomicJsonWrite(runFile, runRecord);
  } catch (error) {
    startupError = error;
  }
}

if (startupError === null && !shutdownController.signal.aborted) {
  try {
    const playwrightEnvironment = { ...process.env };
    delete playwrightEnvironment.NEQ_PLAYER_PASSWORD_VERIFIER;
    child = await runPlaywright(playwright, [
      "test",
      "--config=playwright.config.ts",
      `--project=${N2_PLAYWRIGHT_PROJECT}`,
      "--workers=1",
    ], {
      ...playwrightEnvironment,
      NEQ_N2_HOST_URL: hostUrl,
      NEQ_N2_PLAYER_URL: playerUrl,
      NEQ_N2_PARTY_SIZE: options.partySize,
      NEQ_N2_RUN_ID: runId,
      NEQ_N2_EVIDENCE_DIR: options.evidenceDir,
      ...(options.manageSandboxHost ? { NEQ_N2_MANAGE_SANDBOX_HOST: "1" } : {}),
    });
  } catch (error) {
    child = { status: 1, error, stdout: "", stderr: "" };
  }
} else if (startupError === null) {
  child = { status: 130, error: null, stdout: "", stderr: "runner interrupted before launch" };
}

if (options.manageSandboxHost) {
  if (startupError !== null || managedHost === null || shutdownController.signal.aborted) {
    const lifecycleError = startupError ?? new Error("The managed lifecycle was interrupted by an operator signal.");
    lifecycleResults = SCENARIO_CATALOG
      .filter((scenario) => ["server-instance-change", "missing-bundle", "broken-bundle"].includes(scenario.id))
      .map((scenario) => ({
        id: scenario.id,
        expected: scenario.description,
        observed: { error: sanitizeOutput(String(lifecycleError), process.env.NEQ_N2_PLAYER_PASSWORD) },
        verdict: "FAIL",
        artifacts: [],
        recorded_at_utc: utcNow(),
      }));
  } else {
    try {
      lifecycleResults = await runManagedLifecycleScenarios({
        repositoryRoot: REPOSITORY_ROOT,
        sandboxRoot: join(REPOSITORY_ROOT, "tmp", "combat_capture"),
        evidenceDirectory: options.evidenceDir,
        manager: managedHost,
        partySize: Number(options.partySize),
        runId,
        password: process.env.NEQ_N2_PLAYER_PASSWORD,
        scenarioCatalog: SCENARIO_CATALOG,
        signal: shutdownController.signal,
      });
    } catch (error) {
      lifecycleResults = SCENARIO_CATALOG
        .filter((scenario) => ["server-instance-change", "missing-bundle", "broken-bundle"].includes(scenario.id))
        .map((scenario) => ({
          id: scenario.id,
          expected: scenario.description,
          observed: { error: sanitizeOutput(String(error), process.env.NEQ_N2_PLAYER_PASSWORD) },
          verdict: "FAIL",
          artifacts: [],
          recorded_at_utc: utcNow(),
        }));
    }
  }
}

if (managedHost !== null) {
  try {
    if (signalStopPromise !== null) await signalStopPromise;
    await managedHost.stop();
    if (managedTeardownStatus === "running") managedTeardownStatus = "verified-stopped";
  } catch (error) {
    managedTeardownStatus = "failed";
    const record = lifecycleResults.find((result) => result.id === "broken-bundle") ?? lifecycleResults.at(-1);
    if (record) {
      record.verdict = "FAIL";
      record.observed = {
        ...(record.observed && typeof record.observed === "object" ? record.observed : {}),
        managed_host_teardown_error: sanitizeOutput(String(error), process.env.NEQ_N2_PLAYER_PASSWORD),
      };
    } else {
      startupError ??= error;
    }
  }
}
if (signalStopError !== null) {
  startupError ??= signalStopError;
}

for (const result of lifecycleResults) appendScenario(scenarioFile, result);

let results = readScenarioResults(scenarioFile);
const presentIds = new Set(results.map((result) => result.id));
for (const scenario of SCENARIO_CATALOG) {
  if (!presentIds.has(scenario.id)) {
    appendScenario(scenarioFile, {
      id: scenario.id,
      expected: scenario.description,
      observed: "Playwright did not produce a scenario result; see the sanitized runner output.",
      verdict: "FAIL",
      artifacts: [],
      recorded_at_utc: utcNow(),
    });
  }
}
results = readScenarioResults(scenarioFile);

let finalRunRecord = JSON.parse(readFileSync(runFile, "utf8"));
finalRunRecord.finished_at_utc = utcNow();
if (options.manageSandboxHost && finalRunRecord.managed_sandbox_host &&
    typeof finalRunRecord.managed_sandbox_host === "object") {
  finalRunRecord.managed_sandbox_host.teardown_status = managedTeardownStatus;
}
if (!finalRunRecord.client_build_id) {
  finalRunRecord.metadata_error = "Player shell did not provide client_build_id from the manifest.";
}
if (!hasN2BrowserVersions(finalRunRecord.browser_instances)) {
  finalRunRecord.metadata_error = "Chrome, Firefox, and host-context browser versions were not recorded.";
}
const result = summarize(results);
if (startupError || child?.error || child?.status !== 0 || finalRunRecord.metadata_error) {
  result.verdict = "FAIL";
  result.runner_error = "Playwright runner or required run metadata failed; see sanitized output.";
}
finalRunRecord.verdict = result.verdict;
result.run_id = runId;
result.started_at_utc = runRecord.started_at_utc;
result.finished_at_utc = finalRunRecord.finished_at_utc;
result.git_sha = finalRunRecord.git_sha;
result.client_build_id = finalRunRecord.client_build_id;
result.browser_instances = finalRunRecord.browser_instances;
result.party_size = finalRunRecord.party_size;
result.provider_identity = finalRunRecord.provider_identity;
result.evidence_dir = relativeEvidenceDir;
atomicJsonWrite(runFile, finalRunRecord);
atomicJsonWrite(summaryFile, result);

const output = `${startupError ? `${String(startupError)}\n` : ""}${child?.stdout ?? ""}${child?.stderr ?? ""}`;
if (output) process.stdout.write(sanitizeOutput(output, process.env.NEQ_N2_PLAYER_PASSWORD));
console.log(`N2 gate ${result.verdict}: PASS=${result.counts.PASS} FAIL=${result.counts.FAIL} BLOCKED=${result.counts.BLOCKED}`);
console.log(`Evidence: ${relativeEvidenceDir}`);
process.off("SIGINT", handleSigint);
process.off("SIGTERM", handleSigterm);
process.exitCode = requestedSignal === "SIGINT"
  ? 130
  : requestedSignal === "SIGTERM"
    ? 143
    : result.verdict === "PASS"
      ? 0
      : result.verdict === "BLOCKED"
        ? 2
        : 1;
