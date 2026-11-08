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
import {
  DEFAULT_N2_BROWSER_SET,
  createN2BrowserInstances,
  formatN2BrowserSet,
  hasN2BrowserVersions,
  N2_PLAYWRIGHT_PROJECT,
  parseN2BrowserSet,
} from "./browser-contract.mjs";
import {
  browserBlockedChecks,
  missingScenarioChecks,
  summarizeN2Results,
} from "./browser-coverage.mjs";
import { createAgentRunCredentials, rejectInheritedAgentCredentials } from "./agent-run-credentials.mjs";
import { SandboxHostManager, validateManagedSandboxRoot, validateSandboxPython } from "./managed-host.mjs";
import { readVerifiedBundleSnapshot, runManagedLifecycleScenarios } from "./managed-lifecycle.mjs";
import { redactEvidenceText } from "./redaction.mjs";
import { readWorkspaceIdentity } from "./workspace-identity.mjs";
import {
  copyProviderAttemptLedger,
  parseProviderAttemptLedger,
  providerAttemptLedgerPath,
  PROVIDER_ATTEMPT_BUDGET,
  requireProviderAttemptBudgetForGameplay,
} from "./provider-attempt-budget.mjs";

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
  NEQ_N2_PLAYER_PASSWORD     Owner-run password; omitted for fresh --agent-run credentials
  NEQ_N2_PARTY_SIZE          1 or 4; overridden by --party-size when supplied
  NEQ_N2_EVIDENCE_DIR        Evidence directory, overridden by --evidence-dir

Options:
  --party-size 1|4           Required unless NEQ_N2_PARTY_SIZE is set
  --evidence-dir <path>      Required unless NEQ_N2_EVIDENCE_DIR is set; must be below repo tmp/
  --browsers chrome|chrome+firefox  Browser set (default: chrome+firefox)
  --agent-run                Generate throwaway credentials for managed tmp/combat_capture only;
                             requires --manage-sandbox-host --browsers chrome
  --manage-sandbox-host      Start/restart/stop only this run's verified tmp/combat_capture host
  --dry-run                  Print the plan without contacting endpoints or creating files
  --help                     Show this help

The default browser set runs Player A in system Chrome and Player B in Playwright
Firefox 1.65.0. --browsers chrome runs every Chrome-applicable check and records
each Firefox-dependent check as BLOCKED; it never launches a second Chrome player.
The facilitator UI uses a separate BrowserContext in Player A's Chrome instance.
Requested/run browser sets and actual versions are recorded in run.json. WebKit
cannot replace either required player.

The driver refuses port 8357, non-loopback URLs, and any host/player URL other than
the fixed 8360/8370 pair. By default it never starts, stops, or signals a server,
changes a bundle, prepares a campaign, or writes outside the selected project tmp/
directory. --manage-sandbox-host is the only lifecycle opt-in: it starts the host
from the exact prepared tmp/combat_capture tree, refuses occupied ports, manages
only its own detached process group, and temporarily removes/corrupts only that
sandbox's web/frontend/dist before digest-verifying restoration. It never seeds or
prepares the sandbox.
The default Playwright suite uses separate Chrome and Firefox browser instances
for the players and a third host UI context. Chrome-only mode uses one Chrome
player and the separate host context. No browser storage state, HAR, or trace
archive is written. Structured console evidence redacts cookie, authorization,
password, verifier, and CSRF values. A live run requires a clean checkout; its
commit and clean-tree state are recorded in run.json.

Live runs require --manage-sandbox-host because only the owned sandbox receives
the fail-closed 30-attempt provider budget; external hosts cannot be safely
budgeted. Without the flag, the driver refuses before creating evidence or
contacting endpoints. A cap refusal is recorded in the provider ledger and
forces FAIL. Any BLOCKED or FAIL verdict makes the final driver exit nonzero.
Socket-only evidence is never a PASS.
`;

function usageError(message) {
  console.error(`${message}\n\nRun with --help for usage.`);
  process.exit(2);
}

function parseArguments(argv) {
  const options = {
    partySize: null,
    evidenceDir: process.env.NEQ_N2_EVIDENCE_DIR ?? null,
    browserSet: DEFAULT_N2_BROWSER_SET,
    browsers: parseN2BrowserSet(DEFAULT_N2_BROWSER_SET),
    manageSandboxHost: false,
    agentRun: false,
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
    if (token === "--agent-run") {
      options.agentRun = true;
      continue;
    }
    if (["--party-size", "--evidence-dir", "--browsers"].includes(token)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) usageError(`${token} requires a value`);
      index += 1;
      if (token === "--party-size") options.partySize = value;
      if (token === "--evidence-dir") options.evidenceDir = value;
      if (token === "--browsers") options.browserSet = value;
      continue;
    }
    usageError(`Unknown option: ${token}`);
  }

  try {
    options.browsers = parseN2BrowserSet(options.browserSet);
  } catch (error) {
    usageError(error.message);
  }
  if (options.agentRun && !options.manageSandboxHost) {
    usageError("--agent-run requires --manage-sandbox-host");
  }
  if (options.agentRun && options.browserSet !== "chrome") {
    usageError("--agent-run requires --browsers chrome");
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

function sanitizeOutput(text, password, verifier = process.env.NEQ_PLAYER_PASSWORD_VERIFIER) {
  return redactEvidenceText(
    text,
    [password, verifier],
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
if (options.agentRun) {
  try {
    rejectInheritedAgentCredentials(process.env);
  } catch (error) {
    usageError(error.message);
  }
}
if (options.dryRun) {
  const plannedBlockedChecks = browserBlockedChecks(SCENARIO_CATALOG, options.browsers);
  console.log(JSON.stringify({
    mode: "dry-run",
    party_size: options.partySize,
    browsers_requested: options.browsers,
    browsers_run: [],
    browser_set: formatN2BrowserSet(options.browsers),
    browser_instances: createN2BrowserInstances(null, null, options.browsers),
    blocked: plannedBlockedChecks,
    agent_run: options.agentRun,
    playwright_project: N2_PLAYWRIGHT_PROJECT,
    evidence_dir: options.evidenceDir,
    manage_sandbox_host: options.manageSandboxHost,
    endpoint_contract: {
      host: "http://127.0.0.1:8360",
      player: "http://127.0.0.1:8370",
      forbidden_port: 8357,
    },
    provider_attempt_budget: {
      maximum: PROVIDER_ATTEMPT_BUDGET,
      enforced_only_in_managed_sandbox: true,
      active_ledger_required_before_gameplay: true,
    },
    scenarios: SCENARIO_CATALOG,
    no_server_or_campaign_side_effects: true,
  }, null, 2));
  process.exit(0);
}

if (!options.manageSandboxHost) {
  usageError(
    "Live N2 runs require --manage-sandbox-host because the provider-attempt budget cannot be enforced on an external host",
  );
}
if (options.partySize === null) usageError("Set --party-size 1|4 or NEQ_N2_PARTY_SIZE");
if (!options.evidenceDir) usageError("Set --evidence-dir or NEQ_N2_EVIDENCE_DIR");
if (!options.agentRun && !process.env.NEQ_N2_PLAYER_PASSWORD) {
  usageError("NEQ_N2_PLAYER_PASSWORD must be set in the environment");
}
const hostUrl = validateEndpoint("NEQ_N2_HOST_URL", process.env.NEQ_N2_HOST_URL ?? "", 8360);
const playerUrl = validateEndpoint("NEQ_N2_PLAYER_URL", process.env.NEQ_N2_PLAYER_URL ?? "", 8370);
const workspaceIdentity = readWorkspaceIdentity(REPOSITORY_ROOT);
if (workspaceIdentity.git_sha === "unknown") usageError("A readable git commit SHA is required for an N2 live run");
if (workspaceIdentity.git_worktree_state !== "clean") {
  usageError("N2 live runs require a clean git checkout; no evidence directory or server was started");
}
if (!existsSync(join(REPOSITORY_ROOT, "tmp"))) usageError("Repository tmp/ directory is required for evidence");
if (existsSync(options.evidenceDir)) usageError("Evidence directory already exists; select a unique run directory");

const sandboxRoot = resolve(REPOSITORY_ROOT, "tmp", "combat_capture");
let pythonPath;
try {
  validateManagedSandboxRoot(REPOSITORY_ROOT, sandboxRoot);
  pythonPath = validateSandboxPython(REPOSITORY_ROOT);
  readVerifiedBundleSnapshot(REPOSITORY_ROOT, sandboxRoot);
} catch (error) {
  usageError(`Managed sandbox preflight failed: ${error.message}`);
}

let agentCredentials = null;
if (options.agentRun) {
  try {
    agentCredentials = createAgentRunCredentials({
      pythonPath,
      repositoryRoot: REPOSITORY_ROOT,
      environment: process.env,
    });
  } catch (error) {
    usageError(error.message);
  }
}
const playerPassword = agentCredentials?.password ?? process.env.NEQ_N2_PLAYER_PASSWORD;
const playerVerifier = agentCredentials?.verifier ?? process.env.NEQ_PLAYER_PASSWORD_VERIFIER;
const managedHostEnvironment = agentCredentials
  ? { ...process.env, NEQ_PLAYER_PASSWORD_VERIFIER: agentCredentials.verifier }
  : process.env;
if (agentCredentials) delete managedHostEnvironment.NEQ_N2_PLAYER_PASSWORD;

const runId = makeRunId();
const expectedProviderAttemptLedger = providerAttemptLedgerPath(sandboxRoot, runId);
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
  browser_set: formatN2BrowserSet(options.browsers),
  browsers_requested: options.browsers,
  browsers_run: [],
  browser_instances: createN2BrowserInstances(null, null, options.browsers),
  blocked: browserBlockedChecks(SCENARIO_CATALOG, options.browsers),
  os: { platform: process.platform, release: (await import("node:os")).release(), arch: process.arch },
  party_size: Number(options.partySize),
  scenario_list: SCENARIO_CATALOG,
  provider_identity: "not-observed-by-browser-driver; operator review required if runtime invokes provider",
  provider_attempt_budget: {
    maximum: PROVIDER_ATTEMPT_BUDGET,
    status: "pending",
    scope: "managed-tmp-combat_capture-only",
    ledger_path: `tmp/n2/provider-attempt-ledger-${runId}.jsonl`,
  },
  endpoints: { host: hostUrl, player: playerUrl },
  agent_run: options.agentRun,
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
let providerBudgetReport = null;
let providerBudgetBlocker = null;
let providerBudgetPreflightPassed = false;
let providerBudgetStatus = "pending";
let providerBudgetCopyError = null;
let providerBudgetLedgerCopy = { copied: false, destination: null };
let providerBudgetRefusals = [];
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
    managedHost = new SandboxHostManager({
      repositoryRoot: REPOSITORY_ROOT,
      sandboxRoot,
      pythonPath,
      runId,
      environment: managedHostEnvironment,
    });
    const processInfo = await managedHost.start({
      playerExpected: true,
      signal: shutdownController.signal,
    });
    managedTeardownStatus = "running";
    try {
      providerBudgetReport = requireProviderAttemptBudgetForGameplay({
        managed: options.manageSandboxHost,
        ledgerPath: expectedProviderAttemptLedger,
        budget: PROVIDER_ATTEMPT_BUDGET,
        runId,
      });
      providerBudgetRefusals = providerBudgetReport.refusals;
      providerBudgetStatus = "active";
      runRecord.provider_attempt_budget.status = providerBudgetStatus;
      providerBudgetPreflightPassed = true;
    } catch (error) {
      if (providerBudgetRefusals.length === 0) providerBudgetBlocker = error;
      startupError = error;
      providerBudgetStatus = providerBudgetRefusals.length > 0
        ? "refused_before_gameplay"
        : "blocked_inactive_or_exhausted";
      runRecord.provider_attempt_budget.status = providerBudgetStatus;
    }
    runRecord.managed_sandbox_host = {
      enabled: true,
      sandbox_root: "tmp/combat_capture",
      ownership: "driver-spawned-detached-process-group",
      ...processInfo,
    };
    atomicJsonWrite(runFile, runRecord);
  } catch (error) {
    startupError = error;
    providerBudgetStatus = "startup_failed";
  }
}

if (startupError === null && !shutdownController.signal.aborted) {
  try {
    const playwrightEnvironment = { ...process.env };
    delete playwrightEnvironment.NEQ_PLAYER_PASSWORD_VERIFIER;
    playwrightEnvironment.NEQ_N2_PLAYER_PASSWORD = playerPassword;
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
      NEQ_N2_BROWSERS: options.browserSet,
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
        observed: providerBudgetBlocker !== null
          ? { blocked: sanitizeOutput(String(providerBudgetBlocker), playerPassword, playerVerifier) }
          : { error: sanitizeOutput(String(lifecycleError), playerPassword, playerVerifier) },
        verdict: providerBudgetBlocker !== null ? "BLOCKED" : "FAIL",
        checks: missingScenarioChecks(
          scenario,
          options.browsers,
          providerBudgetBlocker !== null ? "BLOCKED" : "FAIL",
          providerBudgetBlocker !== null ? "provider-attempt-budget-inactive" : "managed-lifecycle-did-not-run",
        ),
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
        password: playerPassword,
        verifier: playerVerifier,
        browsers: options.browsers,
        scenarioCatalog: SCENARIO_CATALOG,
        signal: shutdownController.signal,
      });
    } catch (error) {
      lifecycleResults = SCENARIO_CATALOG
        .filter((scenario) => ["server-instance-change", "missing-bundle", "broken-bundle"].includes(scenario.id))
        .map((scenario) => ({
          id: scenario.id,
          expected: scenario.description,
          observed: { error: sanitizeOutput(String(error), playerPassword, playerVerifier) },
          verdict: "FAIL",
          checks: missingScenarioChecks(scenario, options.browsers, "FAIL", "managed-lifecycle-did-not-run"),
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
        managed_host_teardown_error: sanitizeOutput(String(error), playerPassword, playerVerifier),
      };
    } else {
      startupError ??= error;
    }
  }
}
if (signalStopError !== null) {
  startupError ??= signalStopError;
}

try {
  providerBudgetLedgerCopy = copyProviderAttemptLedger(
    expectedProviderAttemptLedger,
    options.evidenceDir,
  );
  if (providerBudgetLedgerCopy.copied) {
    providerBudgetReport = parseProviderAttemptLedger(
      readFileSync(join(options.evidenceDir, providerBudgetLedgerCopy.destination), "utf8"),
      { budget: PROVIDER_ATTEMPT_BUDGET, runId },
    );
    providerBudgetRefusals = providerBudgetReport.refusals;
    providerBudgetStatus = providerBudgetRefusals.length > 0
      ? "refused"
      : providerBudgetReport.active
        ? "complete"
        : "blocked_inactive";
    runRecord.provider_attempt_budget.status = providerBudgetStatus;
    runRecord.provider_attempt_budget.ledger_evidence = providerBudgetLedgerCopy.destination;
  } else if (providerBudgetBlocker === null && startupError === null) {
    providerBudgetCopyError = new Error("The managed run produced no provider attempt ledger.");
    providerBudgetStatus = "ledger_missing";
  }
} catch (error) {
  providerBudgetCopyError = error;
  providerBudgetStatus = "ledger_evidence_invalid_or_unavailable";
}

for (const result of lifecycleResults) appendScenario(scenarioFile, result);

let results = readScenarioResults(scenarioFile);
const presentIds = new Set(results.map((result) => result.id));
for (const scenario of SCENARIO_CATALOG) {
  if (!presentIds.has(scenario.id)) {
    appendScenario(scenarioFile, {
      id: scenario.id,
      expected: scenario.description,
      observed: providerBudgetBlocker !== null
        ? { blocked: "Provider attempt budget was not active before gameplay; no browser inputs were dispatched." }
        : "Playwright did not produce a scenario result; see the sanitized runner output.",
      verdict: providerBudgetBlocker !== null ? "BLOCKED" : "FAIL",
      checks: missingScenarioChecks(
        scenario,
        options.browsers,
        providerBudgetBlocker !== null ? "BLOCKED" : "FAIL",
        providerBudgetBlocker !== null ? "provider-attempt-budget-inactive" : "scenario-result-missing",
      ),
      artifacts: [],
      recorded_at_utc: utcNow(),
    });
  }
}
results = readScenarioResults(scenarioFile);

let finalRunRecord = JSON.parse(readFileSync(runFile, "utf8"));
const result = summarizeN2Results(results, options.browsers);
finalRunRecord.finished_at_utc = utcNow();
if (options.manageSandboxHost && finalRunRecord.managed_sandbox_host &&
    typeof finalRunRecord.managed_sandbox_host === "object") {
  finalRunRecord.managed_sandbox_host.teardown_status = managedTeardownStatus;
}
finalRunRecord.provider_attempt_budget = {
  ...finalRunRecord.provider_attempt_budget,
  status: providerBudgetStatus,
  active_before_gameplay: providerBudgetPreflightPassed,
  ledger_copied_to_evidence: providerBudgetLedgerCopy.copied,
  ledger_evidence: providerBudgetLedgerCopy.destination,
  reservation_count: providerBudgetReport?.reservation_count ?? null,
  refusal_count: providerBudgetReport?.refusal_count ?? null,
  refusal_reason: providerBudgetRefusals.length > 0 ? "budget_exhausted" : null,
  copy_error: providerBudgetCopyError === null
    ? null
     : sanitizeOutput(String(providerBudgetCopyError), playerPassword, playerVerifier),
};
finalRunRecord.browsers_requested = options.browsers;
finalRunRecord.browsers_run = Array.isArray(finalRunRecord.browsers_run)
  ? finalRunRecord.browsers_run
  : [];
finalRunRecord.blocked = result.blocked;
finalRunRecord.browser_coverage_status = result.browser_coverage_status;
finalRunRecord.verdict_scope = "driver-assertions-only; Overseer owns the live N2 verdict";
if (!finalRunRecord.client_build_id) {
  finalRunRecord.metadata_error = "Player shell did not provide client_build_id from the manifest.";
}
if (!hasN2BrowserVersions(finalRunRecord.browser_instances, options.browsers)) {
  finalRunRecord.metadata_error = options.browsers.includes("firefox")
    ? "Chrome, Firefox, and host-context browser versions were not recorded."
    : "Chrome and host-context browser versions were not recorded.";
}
result.provider_attempt_budget = finalRunRecord.provider_attempt_budget;
if (providerBudgetBlocker !== null) {
  if (result.verdict !== "FAIL") result.verdict = "BLOCKED";
  result.runner_error = "The managed host did not prove active provider-attempt enforcement before gameplay.";
} else if (startupError || child?.error || child?.status !== 0 || finalRunRecord.metadata_error || providerBudgetCopyError) {
  result.verdict = "FAIL";
  result.runner_error = "Playwright runner or required run metadata failed; see sanitized output.";
}
if (providerBudgetRefusals.length > 0) {
  result.verdict = "FAIL";
  result.provider_attempt_budget.refusal_reason = "budget_exhausted; outbound dispatch was refused before transport send";
}
result.browser_set = options.browserSet;
result.browsers_requested = options.browsers;
result.browsers_run = finalRunRecord.browsers_run;
result.blocked = finalRunRecord.blocked;
result.browser_coverage_status = finalRunRecord.browser_coverage_status;
result.verdict_scope = finalRunRecord.verdict_scope;
result.browser_instances = finalRunRecord.browser_instances;
result.agent_run = options.agentRun;
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
if (output) process.stdout.write(sanitizeOutput(output, playerPassword, playerVerifier));
console.log(`N2 gate ${result.verdict}: PASS=${result.counts.PASS} FAIL=${result.counts.FAIL} BLOCKED=${result.counts.BLOCKED}`);
console.log(`Browsers: requested=${options.browserSet} run=${finalRunRecord.browsers_run.join("+") || "none"}`);
console.log(`Blocked checks: ${finalRunRecord.blocked.length}`);
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
