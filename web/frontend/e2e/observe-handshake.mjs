// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export const OBSERVE_HANDSHAKE_RUNTIME_IMPORTS = Object.freeze([
  ["playwright", "playwright"],
  ["playwrightTest", "playwright/test"],
  ["browserContract", "./browser-contract.mjs"],
  ["login", "./login-player.mjs"],
  ["managedHost", "./managed-host.mjs"],
  ["managedHostOutput", "./managed-host-output.mjs"],
  ["providerBudget", "./provider-attempt-budget.mjs"],
  ["requestDiagnostics", "./request-diagnostics.mjs"],
  ["setupEvidence", "./setup-evidence.mjs"],
  ["evidenceWriter", "./evidence-writer.mjs"],
  ["agentCredentials", "./agent-run-credentials.mjs"],
  ["net", "node:net"],
  ["fs", "node:fs"],
  ["path", "node:path"],
  ["os", "node:os"],
]);

const CONNECTION_STATES = new Set(["connected", "connecting", "disconnected", "unknown"]);
const BUILD_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;
const SAFE_VERSION_PATTERN = /^[A-Za-z0-9._+-]{1,64}$/;
const OBSERVATION_TIMEOUT_MS = 90_000;
const CONNECTION_TIMEOUT_MS = 15_000;
const LEDGER_MONITOR_INTERVAL_MS = 250;

export async function loadObserveHandshakeRuntime(importer = (specifier) => import(specifier)) {
  const entries = await Promise.all(OBSERVE_HANDSHAKE_RUNTIME_IMPORTS.map(async ([key, specifier]) => {
    return [key, await importer(specifier)];
  }));
  const runtime = Object.fromEntries(entries);
  if (typeof runtime.playwright?.chromium?.launch !== "function" ||
      typeof runtime.playwrightTest?.expect !== "function" ||
      typeof runtime.playwrightTest.expect.configure !== "function" ||
      typeof runtime.browserContract?.launchN2Browsers !== "function" ||
      typeof runtime.login?.loginPlayer !== "function" ||
      typeof runtime.login?.readPlayerVersion !== "function" ||
      typeof runtime.managedHost?.SandboxHostManager !== "function" ||
      typeof runtime.managedHost?.assertGatePortsFree !== "function" ||
      typeof runtime.managedHost?.isLoopbackPortFree !== "function" ||
      typeof runtime.providerBudget?.parseProviderAttemptLedger !== "function" ||
      typeof runtime.providerBudget?.providerAttemptLedgerPath !== "function" ||
      typeof runtime.providerBudget?.copyProviderAttemptLedger !== "function" ||
      typeof runtime.requestDiagnostics?.SocketRequestDiagnosticsCollector !== "function" ||
      typeof runtime.requestDiagnostics.SocketRequestDiagnosticsCollector.prototype?.attach !== "function" ||
      typeof runtime.requestDiagnostics.SocketRequestDiagnosticsCollector.prototype?.whenReady !== "function" ||
      typeof runtime.requestDiagnostics.SocketRequestDiagnosticsCollector.prototype?.detach !== "function" ||
      typeof runtime.setupEvidence?.withSetupStage !== "function" ||
      typeof runtime.setupEvidence?.setupFailureStage !== "function" ||
      typeof runtime.setupEvidence?.captureCredentialSafeScreenshot !== "function" ||
      typeof runtime.managedHostOutput?.writeManagedHostOutputEvidence !== "function" ||
      typeof runtime.evidenceWriter?.atomicJsonWrite !== "function" ||
      typeof runtime.evidenceWriter?.writeSocketRequestDiagnosticFile !== "function" ||
      typeof runtime.evidenceWriter?.writeHandshakeObservationEvidenceFile !== "function" ||
      typeof runtime.agentCredentials?.createAgentRunCredentials !== "function" ||
      typeof runtime.agentCredentials?.rejectInheritedAgentCredentials !== "function" ||
      typeof runtime.net?.createConnection !== "function") {
    throw new Error("The N2 handshake observation runtime import preflight is incomplete.");
  }
  return Object.freeze(runtime);
}

export async function runObserveHandshake(config, runtime) {
  const {
    repositoryRoot,
    sandboxRoot,
    pythonPath,
    hostUrl,
    playerUrl,
    evidenceDirectory,
    runId,
    environment = process.env,
    workspaceIdentity,
  } = config;
  const fs = runtime.fs;
  const path = runtime.path;
  const runFile = path.join(evidenceDirectory, "run.json");
  const summaryFile = path.join(evidenceDirectory, "summary.json");
  const ledgerPath = runtime.providerBudget.providerAttemptLedgerPath(sandboxRoot, runId);
  const failures = new Set();
  const portProbes = [];
  const ledgerCheckpoints = {
    before_login: emptyLedgerCheckpoint("ledger_missing"),
    after_observation_active: emptyLedgerCheckpoint("ledger_missing"),
    final_copied: emptyLedgerCheckpoint("ledger_missing"),
  };
  const runRecord = {
    schema_version: 1,
    mode: "N2_HANDSHAKE_OBSERVATION",
    n2_gate_result: "NOT_N2_GATE",
    run_id: runId,
    started_at_utc: new Date().toISOString(),
    finished_at_utc: null,
    git_sha: workspaceIdentity.git_sha,
    git_worktree_state: workspaceIdentity.git_worktree_state,
    party_size: 1,
    player_count: 1,
    browser: "Chrome",
    browser_version: null,
    os: {
      platform: process.platform,
      release: safeBrowserVersion(runtime.os.release()),
      arch: safeBrowserVersion(process.arch),
    },
    browsers_run: [],
    setup: {
      status: "BLOCKED",
      stage: "setup_evidence_preflight",
      connection_state: "not_started",
      shell_loaded: "unknown",
      client_build_id: null,
      protocol_version: null,
    },
    request_diagnostics: emptyDiagnosticSummary(),
    screenshot: { status: "not_attempted", path: null, reason: null },
    provider_attempt_budget: {
      maximum: runtime.providerBudget.PROVIDER_ATTEMPT_BUDGET,
      status: "not_started",
      ledger_evidence: null,
      checkpoints: ledgerCheckpoints,
      monitor_state: "not_started",
    },
    managed_sandbox_host: {
      enabled: true,
      sandbox_root: "tmp/combat_capture",
      ownership: "driver-spawned-detached-process-group",
      teardown_status: "not_started",
    },
    managed_host_output: null,
    final_port_probes: portProbes,
    cleanup: { booking_release: "external_primary_owned" },
    failure_categories: [],
    observation_status: "BLOCKED",
    verdict_scope: "single-player-handshake-observation-only",
  };

  let evidenceReady = false;
  let managedHost = null;
  let managedHostStarted = false;
  let managedHostTeardown = "not_started";
  let browser = null;
  let browserContext = null;
  let playerPage = null;
  let diagnostics = null;
  let observationEvidenceWritten = false;
  let ledgerMonitor = null;
  let monitorCheckpoint = null;
  let requestedSignal = null;
  let observationDeadline = null;
  let deadlineExpired = false;
  let loginAttempted = false;
  let rejectObservationDeadline;
  const deadlinePromise = new Promise((resolve, reject) => {
    rejectObservationDeadline = reject;
  });
  deadlinePromise.catch(() => {});
  const shutdownController = new AbortController();
  const handleSignal = (signal) => {
    requestedSignal ??= signal;
    shutdownController.abort();
  };
  const handleSigint = () => handleSignal("SIGINT");
  const handleSigterm = () => handleSignal("SIGTERM");

  const addFailure = (category) => failures.add(category);
  const updateObservationVerdict = () => {
    runRecord.failure_categories = [...failures].sort();
    runRecord.observation_status = determineObservationStatus(
      failures,
      ledgerCheckpoints,
      runRecord.provider_attempt_budget.monitor_state,
    );
    return runRecord.observation_status;
  };
  const writeRunRecord = () => runtime.evidenceWriter.atomicJsonWrite(runFile, runRecord);
  const writeSummaryRecord = () => runtime.evidenceWriter.atomicJsonWrite(summaryFile, {
    schema_version: 1,
    mode: "N2_HANDSHAKE_OBSERVATION",
    n2_gate_result: "NOT_N2_GATE",
    observation_status: runRecord.observation_status,
    run_id: runId,
    party_size: 1,
    browser: "Chrome",
    provider_attempt_budget: runRecord.provider_attempt_budget,
    failure_categories: [...failures].sort(),
    evidence_dir: path.relative(repositoryRoot, evidenceDirectory).split(path.sep).join("/"),
  });
  const closeBrowserResources = async () => {
    let diagnosticsDetached = true;
    try {
      diagnosticsDetached = await diagnostics?.detach() ?? true;
    } catch {
      diagnosticsDetached = false;
    }
    const actions = [
      () => playerPage?.close(),
      () => browserContext?.close(),
      () => browser?.close(),
    ];
    const results = await Promise.allSettled(actions.map((action) => Promise.resolve().then(action)));
    return diagnosticsDetached && results.every((result) => result.status === "fulfilled");
  };
  const writeDiagnostics = async () => {
    if (!diagnostics) return runRecord.request_diagnostics;
    const summary = await diagnostics.flush((record) =>
      runtime.evidenceWriter.writeSocketRequestDiagnosticFile(evidenceDirectory, record));
    runRecord.request_diagnostics = toDiagnosticSummary(summary);
    if (summary.record_write_failures > 0) addFailure("request_diagnostics_write_failed");
    return runRecord.request_diagnostics;
  };
  const requireDiagnosticObservation = () => {
    const summary = runRecord.request_diagnostics;
    if (loginAttempted && (summary.records_written === 0 || summary.records_omitted > 0 ||
        summary.record_write_failures > 0 || summary.truncated)) {
      addFailure("diagnostic_observation_missing");
    }
  };
  const observePageState = async () => {
    if (!playerPage || playerPage.isClosed()) {
      return {
        connection_state: "unknown",
        shell_loaded: "unknown",
        client_build_id: null,
        protocol_version: null,
      };
    }
    let state = null;
    try {
      state = await playerPage.evaluate(() => {
        const status = document.querySelector("[role='status']")?.textContent?.trim();
        const heading = document.querySelector("h1")?.textContent?.trim();
        const buildId = document.querySelector('meta[name="neq-client-build"]')?.content;
        return {
          connection_state: status === "Connected"
            ? "connected"
            : status === "Disconnected"
              ? "disconnected"
              : status === "Connecting..." || status === "Loading player snapshot..."
                ? "connecting"
                : "unknown",
          shell_loaded: heading === "NeverEndingQuest player",
          client_build_id: typeof buildId === "string" ? buildId : null,
        };
      });
    } catch {
      state = null;
    }
    let playerVersion = null;
    try {
      playerVersion = await runtime.login.readPlayerVersion(playerPage);
    } catch {
      playerVersion = null;
    }
    return {
      connection_state: CONNECTION_STATES.has(state?.connection_state)
        ? state.connection_state
        : "unknown",
      shell_loaded: typeof state?.shell_loaded === "boolean" ? state.shell_loaded : "unknown",
      client_build_id: safeBuildId(playerVersion?.clientBuildId) ?? safeBuildId(state?.client_build_id),
      protocol_version: Number.isInteger(playerVersion?.protocolVersion)
        ? playerVersion.protocolVersion
        : null,
    };
  };
  const captureScreenshot = async () => {
    if (!playerPage) {
      runRecord.screenshot = { status: "skipped", path: null, reason: "page-unavailable" };
      return;
    }
    const screenshotPath = path.join(evidenceDirectory, "screenshots", "handshake-player.png");
    try {
      const outcome = await runtime.setupEvidence.captureCredentialSafeScreenshot(
        playerPage,
        "player-a-chrome",
        screenshotPath,
        playerUrl,
      );
      runRecord.screenshot = outcome.status === "captured"
        ? { status: "captured", path: "screenshots/handshake-player.png", reason: null }
        : { status: outcome.status, path: null, reason: outcome.reason };
      if (outcome.status === "failed") addFailure("screenshot_failed");
    } catch {
      runRecord.screenshot = { status: "failed", path: null, reason: "screenshot-failed" };
      addFailure("screenshot_failed");
    }
  };
  const writeHandshakeEvidence = () => {
    updateObservationVerdict();
    runtime.evidenceWriter.writeHandshakeObservationEvidenceFile(
      evidenceDirectory,
      buildHandshakeEvidence(runRecord, ledgerCheckpoints, monitorState(runRecord.provider_attempt_budget.monitor_state), portProbes),
    );
    observationEvidenceWritten = true;
  };

  process.on("SIGINT", handleSigint);
  process.on("SIGTERM", handleSigterm);
  observationDeadline = setTimeout(() => {
    deadlineExpired = true;
    shutdownController.abort();
    rejectObservationDeadline(new Error("N2 observation time limit reached."));
  }, OBSERVATION_TIMEOUT_MS);
  try {
    fs.mkdirSync(path.join(evidenceDirectory, "screenshots"), { recursive: true });
    writeRunRecord();
    evidenceReady = true;
  } catch {
    addFailure("evidence_write_failed");
  }

  try {
    if (evidenceReady) {
      let credentials = null;
      try {
        runtime.agentCredentials.rejectInheritedAgentCredentials(environment);
        credentials = runtime.agentCredentials.createAgentRunCredentials({
          pythonPath,
          repositoryRoot,
          environment,
        });
      } catch {
        runRecord.setup = { ...runRecord.setup, status: "FAIL", stage: "agent_credentials" };
        addFailure("agent_credentials_failed");
      }

      if (credentials !== null) {
        const managedHostEnvironment = { ...environment, NEQ_PLAYER_PASSWORD_VERIFIER: credentials.verifier };
        delete managedHostEnvironment.NEQ_N2_PLAYER_PASSWORD;
        managedHost = new runtime.managedHost.SandboxHostManager({
          repositoryRoot,
          sandboxRoot,
          pythonPath,
          runId,
          environment: managedHostEnvironment,
          endpointProbe: (url) => probeManagedEndpoint(url, {
            net: runtime.net,
            fetchImpl: config.fetchImpl ?? globalThis.fetch,
          }),
        });
        try {
          runRecord.setup.stage = "managed_host_start";
          const processInfo = await managedHost.start({
            playerExpected: true,
            signal: shutdownController.signal,
          });
          managedHostStarted = true;
          managedHostTeardown = "running";
          runRecord.managed_sandbox_host = {
            ...runRecord.managed_sandbox_host,
            ...sanitizeProcessInfo(processInfo),
            teardown_status: "running",
          };
        } catch {
          runRecord.setup = { ...runRecord.setup, status: "FAIL", stage: "managed_host_start" };
          addFailure("managed_host_start_failed");
        }
      }

      if (managedHostStarted && !shutdownController.signal.aborted) {
        runRecord.setup.stage = "provider_ledger_preflight";
        ledgerCheckpoints.before_login = readProviderLedgerCheckpoint(
          runtime,
          ledgerPath,
          runId,
          "before_login",
        );
        recordLedgerCheckpoint(runRecord, ledgerCheckpoints.before_login);
        recordLedgerFailure(ledgerCheckpoints.before_login, addFailure);
        if (ledgerCheckpoints.before_login.state === "active_zero") {
          try {
            if (shutdownController.signal.aborted) throw new Error("N2 observation stopped before browser launch.");
            runRecord.setup.stage = "browser_launch";
            const launched = await runtime.browserContract.launchN2Browsers(
              { chromium: runtime.playwright.chromium },
              ["chrome"],
            );
            browser = launched.chromeBrowser;
            runRecord.browsers_run = ["chrome"];
            runRecord.browser_version = safeBrowserVersion(browser.version());
            runRecord.setup.stage = "browser_context_create";
            browserContext = await browser.newContext();
            runRecord.setup.stage = "page_create";
            playerPage = await browserContext.newPage();
            playerPage.setDefaultTimeout?.(CONNECTION_TIMEOUT_MS);
            playerPage.setDefaultNavigationTimeout?.(CONNECTION_TIMEOUT_MS);
            if (shutdownController.signal.aborted) throw new Error("N2 observation stopped before login.");
            diagnostics = new runtime.requestDiagnostics.SocketRequestDiagnosticsCollector(playerUrl);
            diagnostics.attach(playerPage, "player-a-chrome");
            await diagnostics.whenReady();

            ledgerMonitor = setInterval(() => {
              if (monitorCheckpoint !== null) return;
              const checkpoint = readProviderLedgerCheckpoint(runtime, ledgerPath, runId, "monitor");
              if (checkpoint.state !== "active_zero") monitorCheckpoint = checkpoint;
            }, LEDGER_MONITOR_INTERVAL_MS);
            try {
              loginAttempted = true;
              runRecord.setup.stage = "player_connection_wait";
              const expect = runtime.playwrightTest.expect.configure({ timeout: CONNECTION_TIMEOUT_MS });
              const version = await Promise.race([runtime.login.loginPlayer(playerPage, {
                playerUrl,
                password: credentials.password,
                expect,
                withSetupStage: runtime.setupEvidence.withSetupStage,
              }), deadlinePromise]);
              runRecord.setup = {
                status: "PASS",
                stage: "client_metadata",
                connection_state: "connected",
                shell_loaded: true,
                client_build_id: safeBuildId(version.clientBuildId),
                protocol_version: Number.isInteger(version.protocolVersion) ? version.protocolVersion : null,
              };
              if (runRecord.setup.client_build_id === null || runRecord.setup.protocol_version === null) {
                runRecord.setup.status = "FAIL";
                addFailure("player_login_failed");
              }
            } catch (error) {
              const stage = runtime.setupEvidence.setupFailureStage(error, runRecord.setup.stage);
              if (deadlineExpired) addFailure("observation_timeout");
              runRecord.setup = {
                status: "FAIL",
                stage,
                connection_state: "unknown",
                shell_loaded: "unknown",
                client_build_id: null,
                protocol_version: null,
              };
              addFailure("player_login_failed");
            } finally {
              if (ledgerMonitor !== null) clearInterval(ledgerMonitor);
              ledgerMonitor = null;
              if (observationDeadline !== null) clearTimeout(observationDeadline);
              observationDeadline = null;
            }

            if (monitorCheckpoint !== null) {
              runRecord.provider_attempt_budget.monitor_state =
                monitorCheckpoint.state === "active_nonzero" ? "violation" : "unavailable";
              recordLedgerCheckpoint(runRecord, monitorCheckpoint);
              recordLedgerFailure(monitorCheckpoint, addFailure);
            } else {
              runRecord.provider_attempt_budget.monitor_state = "active_zero";
            }
            ledgerCheckpoints.after_observation_active = readProviderLedgerCheckpoint(
              runtime,
              ledgerPath,
              runId,
              "after_observation_active",
            );
            recordLedgerCheckpoint(runRecord, ledgerCheckpoints.after_observation_active);
            recordLedgerFailure(ledgerCheckpoints.after_observation_active, addFailure);

            if (loginAttempted) {
              const state = await observePageState();
              runRecord.setup = {
                ...runRecord.setup,
                connection_state: state.connection_state,
                shell_loaded: state.shell_loaded,
                client_build_id: runRecord.setup.client_build_id ?? state.client_build_id,
                protocol_version: runRecord.setup.protocol_version ?? state.protocol_version,
              };
              await captureScreenshot();
              await writeDiagnostics();
              writeHandshakeEvidence();
            }
          } catch {
            if (runRecord.setup.status === "BLOCKED") {
              runRecord.setup = { ...runRecord.setup, status: "FAIL" };
            }
            addFailure(stageFailureCategory(runRecord.setup.stage));
          }
        } else if (ledgerCheckpoints.before_login.state === "active_nonzero") {
          addFailure("provider_ledger_reservation");
        }
      }
    }
  } catch {
    addFailure("observation_runtime_failed");
  } finally {
    if (ledgerMonitor !== null) clearInterval(ledgerMonitor);
    if (observationDeadline !== null) clearTimeout(observationDeadline);

    if (managedHostStarted && ledgerCheckpoints.after_observation_active.state === "ledger_missing") {
      ledgerCheckpoints.after_observation_active = readProviderLedgerCheckpoint(
        runtime,
        ledgerPath,
        runId,
        "after_observation_active",
      );
      recordLedgerCheckpoint(runRecord, ledgerCheckpoints.after_observation_active);
      recordLedgerFailure(ledgerCheckpoints.after_observation_active, addFailure);
    }

    try {
      await writeDiagnostics();
    } catch {
      addFailure("request_diagnostics_write_failed");
    }
    requireDiagnosticObservation();
    if (playerPage && !observationEvidenceWritten) {
      const state = await observePageState();
      if (runRecord.setup.status === "BLOCKED") {
        runRecord.setup = {
          ...runRecord.setup,
          status: loginAttempted ? "FAIL" : "BLOCKED",
          connection_state: state.connection_state,
          shell_loaded: state.shell_loaded,
          client_build_id: state.client_build_id,
          protocol_version: state.protocol_version,
        };
      }
      try {
        await captureScreenshot();
      } catch {
        addFailure("screenshot_failed");
      }
      try {
        writeHandshakeEvidence();
      } catch {
        addFailure("evidence_write_failed");
      }
    }

    const closeOk = await closeBrowserResources();
    if (!closeOk) addFailure("observation_runtime_failed");

    if (managedHost !== null) {
      try {
        await managedHost.stop();
        managedHostTeardown = "verified_stopped";
      } catch {
        managedHostTeardown = "failed";
        addFailure("managed_host_teardown_failed");
      }
      runRecord.managed_sandbox_host.teardown_status = managedHostTeardown;
      try {
        const hostOutput = runtime.managedHostOutput.writeManagedHostOutputEvidence(
          managedHost.outputSnapshot(),
          evidenceDirectory,
        );
        runRecord.managed_host_output = hostOutput;
      } catch {
        addFailure("host_output_evidence_failed");
      }
    }

    try {
      const copied = runtime.providerBudget.copyProviderAttemptLedger(ledgerPath, evidenceDirectory);
      runRecord.provider_attempt_budget.ledger_evidence = copied.copied ? copied.destination : null;
      if (copied.copied) {
        ledgerCheckpoints.final_copied = readProviderLedgerCheckpoint(
          runtime,
          path.join(evidenceDirectory, copied.destination),
          runId,
          "final_copied",
        );
      } else {
        ledgerCheckpoints.final_copied = emptyLedgerCheckpoint("ledger_missing");
      }
      recordLedgerCheckpoint(runRecord, ledgerCheckpoints.final_copied);
      recordLedgerFailure(ledgerCheckpoints.final_copied, addFailure);
    } catch {
      ledgerCheckpoints.final_copied = emptyLedgerCheckpoint("ledger_invalid");
      addFailure("provider_ledger_copy_failed");
    }

    try {
      await probeFinalPorts(runtime, portProbes, addFailure);
    } catch {
      addFailure("port_probe_failed");
    }

    if (deadlineExpired) addFailure("observation_timeout");
    if (requestedSignal !== null) addFailure("operator_interrupted");
    runRecord.provider_attempt_budget.status = providerBudgetStatus(ledgerCheckpoints);
    runRecord.finished_at_utc = new Date().toISOString();
    runRecord.managed_sandbox_host.teardown_status = managedHostTeardown;
    runRecord.final_port_probes = portProbes.map((probe) => ({ ...probe }));

    let finalEvidenceWriteFailed = false;
    updateObservationVerdict();
    try {
      writeHandshakeEvidence();
    } catch {
      addFailure("evidence_write_failed");
      finalEvidenceWriteFailed = true;
    }
    updateObservationVerdict();
    try {
      writeRunRecord();
    } catch {
      addFailure("evidence_write_failed");
      finalEvidenceWriteFailed = true;
    }
    updateObservationVerdict();
    try {
      writeSummaryRecord();
    } catch {
      addFailure("evidence_write_failed");
      finalEvidenceWriteFailed = true;
    }

    updateObservationVerdict();
    if (finalEvidenceWriteFailed) {
      // One bounded repair pass persists the fail-closed verdict wherever possible.
      try {
        writeHandshakeEvidence();
      } catch {
        addFailure("evidence_write_failed");
      }
      updateObservationVerdict();
      try {
        writeRunRecord();
      } catch {
        addFailure("evidence_write_failed");
      }
      updateObservationVerdict();
      try {
        writeSummaryRecord();
      } catch {
        addFailure("evidence_write_failed");
      }
    }
    updateObservationVerdict();
    process.off("SIGINT", handleSigint);
    process.off("SIGTERM", handleSigterm);
  }

  return {
    observation_status: runRecord.observation_status,
    exit_code: handshakeObservationExitCode(runRecord.observation_status),
    n2_gate_result: "NOT_N2_GATE",
    run_id: runId,
    failure_categories: [...failures].sort(),
    provider_attempt_budget: runRecord.provider_attempt_budget,
  };
}

export function handshakeObservationExitCode(status) {
  if (status === "PASS") return 0;
  if (status === "BLOCKED") return 2;
  return 1;
}

export function readProviderLedgerCheckpoint(runtime, ledgerPath, runId, checkpoint) {
  const fs = runtime.fs;
  if (!fs.existsSync(ledgerPath)) return emptyLedgerCheckpoint("ledger_missing", checkpoint);
  try {
    const report = runtime.providerBudget.parseProviderAttemptLedger(
      fs.readFileSync(ledgerPath, "utf8"),
      { budget: runtime.providerBudget.PROVIDER_ATTEMPT_BUDGET, runId },
    );
    if (!report.active) return emptyLedgerCheckpoint("guard_not_started", checkpoint);
    const reservations = report.reservation_count;
    const refusals = report.refusal_count;
    if (reservations === 0 && refusals === 0) {
      return { checkpoint, state: "active_zero", reservation_count: 0, refusal_count: 0 };
    }
    return {
      checkpoint,
      state: "active_nonzero",
      reservation_count: reservations,
      refusal_count: refusals,
    };
  } catch {
    return emptyLedgerCheckpoint("ledger_invalid", checkpoint);
  }
}

export async function probeManagedEndpoint(url, { net, fetchImpl = globalThis.fetch }) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" || parsed.hostname !== "127.0.0.1" ||
      parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/") {
    return false;
  }
  if (parsed.port === "8360") return probeTcp(net, parsed.hostname, Number(parsed.port));
  if (parsed.port !== "8370" || typeof fetchImpl !== "function") return false;
  try {
    const response = await fetchImpl(url, { signal: AbortSignal.timeout(1_000) });
    return response.status === 200;
  } catch {
    return false;
  }
}

async function probeFinalPorts(runtime, portProbes, addFailure) {
  const seen = new Set();
  const checkPort = async (port) => {
    try {
      const free = await runtime.managedHost.isLoopbackPortFree(port, (probe) => {
        if (seen.has(port)) return;
        seen.add(port);
        portProbes.push(probe);
      });
      if (!seen.has(port)) {
        seen.add(port);
        portProbes.push({ port, status: free ? "free" : "error", error_code: null });
      }
      if (!free) addFailure("port_probe_failed");
      return free;
    } catch {
      if (!seen.has(port)) {
        seen.add(port);
        portProbes.push({ port, status: "error", error_code: null });
      }
      addFailure("port_probe_failed");
      return false;
    }
  };
  await runtime.managedHost.assertGatePortsFree(checkPort);
  if (portProbes.length !== 2 || portProbes.some((probe) => probe.status !== "free")) {
    addFailure("port_probe_failed");
  }
}

function probeTcp(net, hostname, port) {
  return new Promise((resolve) => {
    let settled = false;
    let socket;
    const finish = (available) => {
      if (settled) return;
      settled = true;
      socket?.destroy();
      resolve(available);
    };
    try {
      socket = net.createConnection({ host: hostname, port });
      socket.setTimeout(1_000);
      socket.once("connect", () => finish(true));
      socket.once("timeout", () => finish(false));
      socket.once("error", () => finish(false));
    } catch {
      finish(false);
    }
  });
}

function emptyLedgerCheckpoint(state, checkpoint = null) {
  return { checkpoint, state, reservation_count: null, refusal_count: null };
}

function recordLedgerCheckpoint(runRecord, checkpoint) {
  runRecord.provider_attempt_budget.checkpoints[checkpoint.checkpoint] = {
    state: checkpoint.state,
    reservation_count: checkpoint.reservation_count,
    refusal_count: checkpoint.refusal_count,
  };
}

function recordLedgerFailure(checkpoint, addFailure) {
  if (checkpoint.state === "active_nonzero") {
    if (checkpoint.reservation_count > 0) addFailure("provider_ledger_reservation");
    if (checkpoint.refusal_count > 0) addFailure("provider_ledger_refusal");
  } else if (checkpoint.state === "guard_not_started") {
    addFailure("provider_ledger_inactive");
  } else if (checkpoint.state === "ledger_missing") {
    addFailure("provider_ledger_missing");
  } else if (checkpoint.state === "ledger_invalid") {
    addFailure("provider_ledger_invalid");
  }
}

function providerBudgetStatus(checkpoints) {
  const states = [checkpoints.before_login, checkpoints.after_observation_active, checkpoints.final_copied]
    .map((checkpoint) => checkpoint.state);
  if (states.includes("active_nonzero")) return "fail_nonzero_dispatch";
  if (states.includes("ledger_invalid")) return "blocked_invalid";
  if (states.includes("ledger_missing")) return "blocked_missing";
  if (states.includes("guard_not_started")) return "blocked_inactive";
  if (states.every((state) => state === "active_zero")) return "active_zero_all_checkpoints";
  return "blocked_incomplete";
}

function determineObservationStatus(failures, checkpoints, monitorStatus = "not_started") {
  if ([...failures].some((category) => [
    "provider_ledger_reservation",
    "provider_ledger_refusal",
  ].includes(category))) return "FAIL";
  if ([...failures].some((category) => category !== "diagnostic_observation_missing" &&
      !category.startsWith("provider_ledger_"))) return "FAIL";
  if ([...failures].some((category) => category.startsWith("provider_ledger_")) ||
      monitorStatus === "unavailable" || failures.has("diagnostic_observation_missing")) return "BLOCKED";
  if (providerBudgetStatus(checkpoints) !== "active_zero_all_checkpoints") return "BLOCKED";
  return "PASS";
}

function stageFailureCategory(stage) {
  if (stage === "agent_credentials") return "agent_credentials_failed";
  if (stage === "managed_host_start") return "managed_host_start_failed";
  if (stage === "browser_launch") return "browser_launch_failed";
  if (stage === "browser_context_create") return "browser_context_create_failed";
  if (stage === "page_create") return "page_create_failed";
  if (stage === "player_shell_load" || stage === "player_authentication" ||
      stage === "player_connection_wait" || stage === "client_metadata") return "player_login_failed";
  return "observation_runtime_failed";
}

function buildHandshakeEvidence(runRecord, checkpoints, monitor, portProbes) {
  const finalSetup = runRecord.setup;
  return {
    schema: "n2-handshake-observation.v1",
    mode: "N2_HANDSHAKE_OBSERVATION",
    n2_gate_result: "NOT_N2_GATE",
    run_id: runRecord.run_id,
    party_size: 1,
    player_count: 1,
    browser: "Chrome",
    browser_version: runRecord.browser_version,
    setup: {
      status: finalSetup.status,
      stage: finalSetup.stage,
      connection_state: finalSetup.connection_state,
      shell_loaded: finalSetup.shell_loaded,
      client_build_id: safeBuildId(finalSetup.client_build_id),
      protocol_version: Number.isInteger(finalSetup.protocol_version) ? finalSetup.protocol_version : null,
    },
    request_diagnostics: runRecord.request_diagnostics,
    screenshot: runRecord.screenshot,
    provider_attempt_ledger: {
      before_login: toEvidenceCheckpoint(checkpoints.before_login),
      after_observation_active: toEvidenceCheckpoint(checkpoints.after_observation_active),
      final_copied: toEvidenceCheckpoint(checkpoints.final_copied),
      monitor_state: monitor,
    },
    cleanup: {
      owned_host_teardown: runRecord.managed_sandbox_host.teardown_status,
      port_probes: portProbes.map(({ port, status, error_code }) => ({ port, status, error_code })),
      booking_release: "external_primary_owned",
    },
    failure_categories: runRecord.failure_categories,
    recorded_at_utc: new Date().toISOString(),
  };
}

function toEvidenceCheckpoint(checkpoint) {
  return {
    state: checkpoint.state,
    reservation_count: checkpoint.reservation_count,
    refusal_count: checkpoint.refusal_count,
  };
}

function monitorState(value) {
  return ["not_started", "active_zero", "violation", "unavailable"].includes(value)
    ? value
    : "unavailable";
}

function toDiagnosticSummary(summary) {
  return {
    records_written: boundedInteger(summary.records_written, 0, 128),
    records_omitted: boundedInteger(summary.records_omitted, 0, 1_000_000),
    record_write_failures: boundedInteger(summary.record_write_failures, 0, 1_000_000),
    truncated: summary.truncated === true,
    raw_headers_retained: false,
    raw_urls_retained: false,
  };
}

function emptyDiagnosticSummary() {
  return {
    records_written: 0,
    records_omitted: 0,
    record_write_failures: 0,
    truncated: false,
    raw_headers_retained: false,
    raw_urls_retained: false,
  };
}

function safeBuildId(value) {
  return typeof value === "string" && BUILD_ID_PATTERN.test(value) ? value : null;
}

function safeBrowserVersion(value) {
  return typeof value === "string" && SAFE_VERSION_PATTERN.test(value) ? value : null;
}

function sanitizeProcessInfo(value) {
  if (!value || typeof value !== "object") return {};
  return {
    pid: Number.isInteger(value.pid) && value.pid > 0 ? value.pid : null,
    process_group_id: Number.isInteger(value.process_group_id) && value.process_group_id > 0
      ? value.process_group_id
      : null,
    cwd: value.cwd === "tmp/combat_capture" ? value.cwd : null,
    command: value.command === ".venv/bin/python -c 'import run_web; run_web.main()'" ? value.command : null,
  };
}

function boundedInteger(value, minimum, maximum) {
  return Number.isInteger(value) ? Math.min(maximum, Math.max(minimum, value)) : minimum;
}
