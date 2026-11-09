// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import test from "node:test";
import {
  handshakeObservationExitCode,
  loadObserveHandshakeRuntime,
  runObserveHandshake,
} from "./observe-handshake.mjs";
import { PROVIDER_ATTEMPT_BUDGET, providerAttemptLedgerPath } from "./provider-attempt-budget.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const TEST_ROOT = join(REPOSITORY_ROOT, "tmp", "n2");
const VALID_RUN_ID = "n2-20261109T071155123Z-deadbeef";
const ACTIVE_LEDGER = ledgerText(VALID_RUN_ID);
let fixtureCounter = 0;

function makeScratch() {
  mkdirSync(TEST_ROOT, { recursive: true });
  return mkdtempSync(join(TEST_ROOT, "observe-handshake-test-"));
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
  for (let number = 1; number <= reservations; number += 1) {
    records.push({
      event: "reservation",
      schema_version: 1,
      pid: 123,
      budget: PROVIDER_ATTEMPT_BUDGET,
      run_id: runId,
      reservation_number: number,
      host: "api.example.invalid",
      method: "POST",
      path: "/v1/chat/completions",
    });
  }
  for (let number = 0; number < refusals; number += 1) {
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

function makeRuntime(scratch, config = {}) {
  const loaded = globalThis.__observeRuntime ?? null;
  assert.ok(loaded, "runtime fixture must be initialized");
  const events = [];
  const endpointObservations = [];
  const pages = [];
  const contexts = [];
  const browsers = [];
  const calls = {
    launches: 0,
    contexts: 0,
    pages: 0,
    login: 0,
    probes: [],
    fetches: [],
    cdpCommands: [],
    cdpDetached: 0,
  };
  const fixtureRoot = join(scratch, `fixture-${fixtureCounter++}`);
  const sandboxRoot = join(fixtureRoot, "sandbox");
  const evidenceDirectory = join(fixtureRoot, "evidence");
  const runFile = join(evidenceDirectory, "run.json");
  const summaryFile = join(evidenceDirectory, "summary.json");
  const ledgerPath = providerAttemptLedgerPath(sandboxRoot, VALID_RUN_ID);
  const atomicWriteCounts = new Map();
  const cdpSession = new EventEmitter();
  cdpSession.send = async (method) => {
    calls.cdpCommands.push(method);
    if (method !== "Network.enable" || config.noSocketDiagnostics) return {};
    cdpSession.emit("Network.webSocketCreated", {
      requestId: "private-request-correlation-id",
      url: "ws://127.0.0.1:8370/socket.io/?EIO=4&transport=websocket&sid=private-query-value",
      initiator: { type: "script" },
    });
    cdpSession.emit("Network.webSocketWillSendHandshakeRequest", {
      requestId: "private-request-correlation-id",
      request: {
        headers: {
          Origin: "http://127.0.0.1:8370",
          Host: "127.0.0.1:8370",
          Cookie: "neq_player_session=private-cookie-value",
          Authorization: "Bearer private-authorization-value",
        },
      },
    });
    cdpSession.emit("Network.webSocketHandshakeResponseReceived", {
      requestId: "private-request-correlation-id",
      response: { status: 101, statusText: "Switching Protocols", headers: {} },
    });
    return {};
  };
  cdpSession.detach = async () => {
    calls.cdpDetached += 1;
    events.push("cdp-detach");
  };

  class FakeSandboxHostManager {
    constructor(options) {
      this.options = options;
      this.outputCollector = new loaded.managedHostOutput.ManagedHostOutputCollector();
      this.started = false;
      this.stopped = false;
    }

    async start({ playerExpected, signal }) {
      events.push("host-start");
      assert.equal(playerExpected, true);
      assert.equal(signal.aborted, false);
      if (config.hostStartFailure) throw new Error("synthetic host start failure");
      if (config.initialLedger !== null) {
        mkdirSync(dirname(ledgerPath), { recursive: true });
        writeFileSync(ledgerPath, config.initialLedger ?? ACTIVE_LEDGER, "utf8");
      }
      const hostReady = await this.options.endpointProbe("http://127.0.0.1:8360/");
      const playerReady = await this.options.endpointProbe("http://127.0.0.1:8370/");
      endpointObservations.push({ hostReady, playerReady });
      this.started = true;
      return {
        pid: 123,
        process_group_id: 123,
        cwd: "tmp/combat_capture",
        command: ".venv/bin/python -c 'import run_web; run_web.main()'",
      };
    }

    async stop() {
      events.push("host-stop");
      calls.hostStop = (calls.hostStop ?? 0) + 1;
      this.stopped = true;
      if (config.finalLedger !== undefined && existsSync(ledgerPath)) {
        writeFileSync(ledgerPath, config.finalLedger, "utf8");
      }
      if (config.hostStopFailure) throw new Error("synthetic host stop failure");
    }

    outputSnapshot() {
      return this.outputCollector.snapshot();
    }
  }

  const fakeNet = {
    createConnection(options) {
      calls.tcpOptions = options;
      const socket = new EventEmitter();
      socket.setTimeout = () => {};
      socket.destroy = () => {};
      queueMicrotask(() => socket.emit("connect"));
      return socket;
    },
  };
  const fakeExpect = (locator) => ({
    async toBeVisible() {
      const label = locator.label;
      events.push(`expect:${label}`);
      if (label === "Connected" && config.monitorLedgerText !== undefined) {
        writeFileSync(ledgerPath, config.monitorLedgerText, "utf8");
        setTimeout(() => {
          writeFileSync(ledgerPath, config.monitorLedgerRestoreText ?? ACTIVE_LEDGER, "utf8");
        }, config.monitorLedgerRestoreMs ?? 300);
      }
      if (label === "Connected" && config.connectedDelayMs) {
        await new Promise((resolveDelay) => setTimeout(resolveDelay, config.connectedDelayMs));
      }
      if (label === "Connected" && config.connectedFailure) {
        throw new Error("synthetic Connected timeout");
      }
      if (label === "Connected" && config.afterConnectedLedger !== undefined) {
        writeFileSync(ledgerPath, config.afterConnectedLedger, "utf8");
      }
    },
  });
  fakeExpect.configure = (options) => {
    calls.expectConfig = options;
    return fakeExpect;
  };

  const page = {
    closed: false,
    handlers: new Map(),
    evaluateCount: 0,
    on(eventName, handler) {
      this.handlers.set(eventName, handler);
      if (eventName === "response" && config.degradedSocketDiagnostics) {
        queueMicrotask(() => this.emit("response", {
          request: () => ({ url: () => { throw new Error("synthetic diagnostic omission"); } }),
          status: () => 200,
        }));
      }
    },
    emit(eventName, value) {
      this.handlers.get(eventName)?.(value);
    },
    async goto(url, options) {
      events.push("page-goto");
      calls.goto = { url, options };
    },
    getByRole(role, options) {
      const label = options.name;
      events.push(`locator:role:${role}:${label}`);
      return {
        label,
        async click() { events.push(`click:${label}`); },
      };
    },
    getByLabel(label) {
      events.push(`locator:label:${label}`);
      return {
        async fill(value) {
          events.push(`fill:${label}`);
          calls.password = value;
        },
      };
    },
    getByText(text, options) {
      const label = options?.exact ? text : String(text);
      events.push(`locator:text:${label}`);
      return { label };
    },
    async evaluate(script) {
      this.evaluateCount += 1;
      const source = String(script);
      if (source.includes("neq-protocol-version")) {
        calls.evaluateKind = "client-version";
        events.push("read-player-version");
        if (config.pageVersionError) throw new Error("synthetic metadata unavailable");
        return config.pageVersion ?? { clientBuildId: "build-abc", protocolVersion: 1 };
      }
      calls.evaluateKind = "player-dom-state";
      return config.pageState ?? {
        connection_state: "connected",
        shell_loaded: true,
        client_build_id: "build-abc",
      };
    },
    setDefaultTimeout(value) { calls.pageDefaultTimeout = value; },
    setDefaultNavigationTimeout(value) { calls.navigationTimeout = value; },
    isClosed() { return this.closed; },
    async close() {
      events.push("page-close");
      this.closed = true;
      if (config.pageCloseFailure) throw new Error("synthetic page close failure");
    },
    context() { return context; },
  };
  const context = {
    async newPage() {
      calls.pages += 1;
      pages.push(page);
      events.push("page-create");
      return page;
    },
    async newCDPSession(pageValue) {
      assert.equal(pageValue, page);
      calls.cdpSessions = (calls.cdpSessions ?? 0) + 1;
      return cdpSession;
    },
    async close() {
      events.push("context-close");
      if (config.contextCloseFailure) throw new Error("synthetic context close failure");
    },
  };
  const browser = {
    version: () => "Chrome-1223",
    async newContext() {
      calls.contexts += 1;
      contexts.push(context);
      events.push("context-create");
      return context;
    },
    async close() {
      events.push("browser-close");
      if (config.browserCloseFailure) throw new Error("synthetic browser close failure");
    },
  };
  const fakePlaywright = {
    chromium: {
      async launch(options) {
        calls.launches += 1;
        events.push("browser-launch");
        assert.deepEqual(options, { headless: true, channel: "chrome" });
        browsers.push(browser);
        return browser;
      },
    },
  };
  const runtime = {
    ...loaded,
    playwright: fakePlaywright,
    playwrightTest: { expect: fakeExpect },
    managedHost: {
      ...loaded.managedHost,
      SandboxHostManager: FakeSandboxHostManager,
      async isLoopbackPortFree(port, onProbe) {
        calls.probes.push(port);
        const free = config.portsFree !== false;
        onProbe?.({ port, status: free ? "free" : "error", error_code: free ? null : "EADDRINUSE" });
        return free;
      },
      async assertGatePortsFree(checkPortFree) {
        const occupied = [];
        for (const port of [8360, 8370]) {
          if (!(await checkPortFree(port))) occupied.push(port);
        }
        if (occupied.length) throw new Error("synthetic occupied port");
        return [8360, 8370];
      },
    },
    agentCredentials: {
      rejectInheritedAgentCredentials(environment) {
        if (environment.NEQ_N2_PLAYER_PASSWORD || environment.NEQ_PLAYER_PASSWORD_VERIFIER) {
          throw new Error("owner credentials refused");
        }
      },
      createAgentRunCredentials({ environment }) {
        calls.credentialsGenerated = true;
        assert.equal(environment.NEQ_N2_PLAYER_PASSWORD, undefined);
        assert.equal(environment.NEQ_PLAYER_PASSWORD_VERIFIER, undefined);
        return { password: "synthetic-player-password", verifier: "synthetic-verifier" };
      },
    },
    setupEvidence: {
      ...loaded.setupEvidence,
      async captureCredentialSafeScreenshot(pageValue) {
        events.push("screenshot");
        assert.equal(pageValue, page);
        return config.screenshotFailure
          ? { status: "failed", reason: "screenshot-failed" }
          : { status: "captured", path: "screenshots/handshake-player.png" };
      },
    },
    evidenceWriter: {
      ...loaded.evidenceWriter,
      atomicJsonWrite(path, payload) {
        const count = (atomicWriteCounts.get(path) ?? 0) + 1;
        atomicWriteCounts.set(path, count);
        if (config.failFinalRunWriteOnce && path === runFile && count === 2) {
          throw new Error("synthetic final run evidence write failure");
        }
        if (config.failSummaryWriteOnce && path === summaryFile && count === 1) {
          throw new Error("synthetic summary evidence write failure");
        }
        return loaded.evidenceWriter.atomicJsonWrite(path, payload);
      },
      writeSocketRequestDiagnosticFile(...args) {
        events.push("diagnostic-write");
        return loaded.evidenceWriter.writeSocketRequestDiagnosticFile(...args);
      },
      writeHandshakeObservationEvidenceFile(...args) {
        events.push("handshake-evidence");
        return loaded.evidenceWriter.writeHandshakeObservationEvidenceFile(...args);
      },
    },
    net: fakeNet,
  };
  const runConfig = {
    repositoryRoot: REPOSITORY_ROOT,
    sandboxRoot,
    pythonPath: join(REPOSITORY_ROOT, ".venv", "bin", "python"),
    hostUrl: "http://127.0.0.1:8360",
    playerUrl: "http://127.0.0.1:8370",
    evidenceDirectory,
    runId: VALID_RUN_ID,
    environment: {},
    workspaceIdentity: { git_sha: "abcdef123456", git_worktree_state: "clean" },
    fetchImpl: async (url) => {
      calls.fetches.push(url);
      return { status: 200 };
    },
  };
  return { runtime, runConfig, events, endpointObservations, calls, pages, contexts, browsers, ledgerPath, evidenceDirectory };
}

test.before(async () => {
  globalThis.__observeRuntime = await loadObserveHandshakeRuntime();
});

test.after(() => {
  delete globalThis.__observeRuntime;
});

test("runtime preflight resolves every observer module using the official Playwright exports", async () => {
  const seen = [];
  const runtime = await loadObserveHandshakeRuntime(async (specifier) => {
    seen.push(specifier);
    return import(specifier);
  });
  assert.deepEqual(seen, globalThis.__observeRuntime ? [
    "playwright",
    "playwright/test",
    "./browser-contract.mjs",
    "./login-player.mjs",
    "./managed-host.mjs",
    "./managed-host-output.mjs",
    "./provider-attempt-budget.mjs",
    "./request-diagnostics.mjs",
    "./setup-evidence.mjs",
    "./evidence-writer.mjs",
    "./agent-run-credentials.mjs",
    "node:net",
    "node:fs",
    "node:path",
    "node:os",
  ] : []);
  assert.equal(typeof runtime.playwrightTest.expect, "function");
  assert.equal(typeof runtime.login.loginPlayer, "function");
  await assert.rejects(
    loadObserveHandshakeRuntime(async (specifier) => {
      if (specifier === "playwright/test") throw new Error("synthetic unresolved module");
      return import(specifier);
    }),
    /synthetic unresolved module/,
  );
});

test("one-pass observer uses the shared login chain, one Chrome player, and TCP-only host readiness", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch);
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "PASS");
    assert.equal(result.n2_gate_result, "NOT_N2_GATE");
    assert.equal(fixture.calls.launches, 1);
    assert.equal(fixture.calls.contexts, 1);
    assert.equal(fixture.calls.pages, 1);
    assert.equal(fixture.calls.cdpSessions, 1);
    assert.deepEqual(fixture.calls.cdpCommands, ["Network.enable"]);
    assert.deepEqual(fixture.calls.tcpOptions, { host: "127.0.0.1", port: 8360 });
    assert.deepEqual(fixture.calls.fetches, ["http://127.0.0.1:8370/"]);
    assert.deepEqual(fixture.calls.probes, [8360, 8370]);
    assert.equal(fixture.calls.expectConfig.timeout, 15_000);
    assert.equal(fixture.calls.pageDefaultTimeout, 15_000);
    assert.equal(fixture.calls.navigationTimeout, 15_000);
    assert.deepEqual(fixture.events.filter((event) => event.startsWith("expect:")), [
      "expect:Player login",
      "expect:NeverEndingQuest player",
      "expect:Connected",
    ]);
    assert.ok(fixture.events.indexOf("page-goto") < fixture.events.indexOf("fill:Password"));
    assert.ok(fixture.events.indexOf("fill:Password") < fixture.events.indexOf("locator:role:button:Log in"));
    assert.ok(fixture.events.indexOf("handshake-evidence") < fixture.events.indexOf("page-close"));
    assert.ok(fixture.events.indexOf("diagnostic-write") < fixture.events.indexOf("page-close"));
    assert.equal(fixture.pages.length, 1);
    assert.equal(fixture.contexts.length, 1);
    assert.equal(fixture.browsers.length, 1);
    const observation = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(observation.n2_gate_result, "NOT_N2_GATE");
    assert.equal(observation.provider_attempt_ledger.before_login.state, "active_zero");
    assert.equal(observation.provider_attempt_ledger.after_observation_active.state, "active_zero");
    assert.equal(observation.provider_attempt_ledger.final_copied.state, "active_zero");
    const diagnostics = readFileSync(join(fixture.evidenceDirectory, "request-diagnostics.jsonl"), "utf8");
    assert.match(diagnostics, /"path":"\/socket.io\/"/);
    assert.match(diagnostics, /"transport":"websocket"/);
    assert.match(diagnostics, /"status":101/);
    assert.match(diagnostics, /"origin_present":true/);
    assert.match(diagnostics, /"origin_matches_expected":true/);
    assert.match(diagnostics, /"host_matches_expected":true/);
    assert.match(diagnostics, /"session_cookie_present":true/);
    assert.doesNotMatch(
      diagnostics,
      /private-query-value|private-request-correlation-id|private-cookie-value|private-authorization-value|synthetic-player-password|synthetic-verifier/,
    );
    assert.ok(fixture.events.indexOf("cdp-detach") < fixture.events.indexOf("page-close"));
    assert.equal(fixture.calls.cdpDetached, 1);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("Connected assertion failure records diagnostics and safe setup before browser close without retry", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch, {
      connectedFailure: true,
      pageState: {
        connection_state: "disconnected",
        shell_loaded: true,
        client_build_id: "build-early",
      },
      pageVersion: { clientBuildId: "build-early", protocolVersion: 1 },
    });
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "FAIL");
    assert.equal(fixture.calls.launches, 1);
    assert.equal(fixture.events.filter((event) => event === "page-goto").length, 1);
    const diagnosticWrite = fixture.events.indexOf("diagnostic-write");
    const screenshot = fixture.events.indexOf("screenshot");
    const observationWrite = fixture.events.indexOf("handshake-evidence");
    const pageClose = fixture.events.indexOf("page-close");
    assert.ok(diagnosticWrite >= 0 && diagnosticWrite < pageClose);
    assert.ok(screenshot >= 0 && screenshot < pageClose);
    assert.ok(observationWrite >= 0 && observationWrite < pageClose);
    const evidence = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(evidence.setup.status, "FAIL");
    assert.equal(evidence.setup.stage, "player_connection_wait");
    assert.equal(evidence.setup.connection_state, "disconnected");
    assert.equal(evidence.setup.shell_loaded, true);
    assert.equal(evidence.setup.client_build_id, "build-early");
    assert.equal(evidence.setup.protocol_version, 1);
    assert.ok(fixture.events.indexOf("expect:Connected") < fixture.events.indexOf("read-player-version"));
    assert.equal(evidence.n2_gate_result, "NOT_N2_GATE");
    const allEvidence = readEvidenceText(fixture.evidenceDirectory);
    assert.doesNotMatch(
      allEvidence,
      /synthetic-player-password|synthetic-verifier|private-query-value|private-request-correlation-id|private-cookie-value|private-authorization-value/,
    );
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("unknown early protocol metadata stays null without bypassing the Connected wait", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch, {
      connectedFailure: true,
      pageState: {
        connection_state: "disconnected",
        shell_loaded: true,
        client_build_id: "build-early",
      },
      pageVersionError: true,
    });
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "FAIL");
    assert.deepEqual(fixture.events.filter((event) => event.startsWith("expect:")), [
      "expect:Player login",
      "expect:NeverEndingQuest player",
      "expect:Connected",
    ]);
    assert.ok(fixture.events.indexOf("expect:Connected") < fixture.events.indexOf("read-player-version"));
    const evidence = JSON.parse(
      readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"),
    );
    assert.equal(evidence.setup.status, "FAIL");
    assert.equal(evidence.setup.stage, "player_connection_wait");
    assert.equal(evidence.setup.connection_state, "disconnected");
    assert.equal(evidence.setup.protocol_version, null);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("Connected with an active-zero ledger is BLOCKED when Socket.IO diagnostics are missing or degraded", async () => {
  const scratch = makeScratch();
  try {
    for (const config of [{ noSocketDiagnostics: true }, { degradedSocketDiagnostics: true }]) {
      const fixture = makeRuntime(scratch, config);
      const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
      assert.equal(result.observation_status, "BLOCKED");
      assert.equal(result.failure_categories.includes("diagnostic_observation_missing"), true);
      assert.equal(handshakeObservationExitCode(result.observation_status), 2);
      const evidence = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"));
      assert.equal(evidence.provider_attempt_ledger.before_login.state, "active_zero");
      assert.equal(evidence.provider_attempt_ledger.after_observation_active.state, "active_zero");
      assert.equal(evidence.provider_attempt_ledger.final_copied.state, "active_zero");
      if (config.noSocketDiagnostics) {
        assert.equal(evidence.request_diagnostics.records_written, 0);
      } else {
        assert.ok(evidence.request_diagnostics.records_written > 0);
        assert.ok(evidence.request_diagnostics.records_omitted > 0);
        assert.equal(evidence.request_diagnostics.truncated, true);
      }
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("inactive guard is BLOCKED without claiming zero, while any reservation or refusal is FAIL", async () => {
  const scratch = makeScratch();
  try {
    const missing = makeRuntime(scratch, { initialLedger: null });
    const missingResult = await runObserveHandshake(missing.runConfig, missing.runtime);
    assert.equal(missingResult.observation_status, "BLOCKED");
    assert.equal(missing.calls.launches, 0);
    const missingEvidence = JSON.parse(readFileSync(join(missing.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(missingEvidence.provider_attempt_ledger.before_login.state, "ledger_missing");
    assert.equal(missingEvidence.provider_attempt_ledger.final_copied.state, "ledger_missing");
    assert.equal(missingEvidence.provider_attempt_ledger.before_login.reservation_count, null);

    const invalid = makeRuntime(scratch, { initialLedger: "invalid ledger\n" });
    const invalidResult = await runObserveHandshake(invalid.runConfig, invalid.runtime);
    assert.equal(invalidResult.observation_status, "BLOCKED");
    assert.equal(invalid.calls.launches, 0);
    const invalidEvidence = JSON.parse(readFileSync(join(invalid.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(invalidEvidence.provider_attempt_ledger.before_login.state, "ledger_invalid");
    assert.equal(invalidEvidence.provider_attempt_ledger.final_copied.state, "ledger_invalid");

    const inactive = makeRuntime(scratch, { initialLedger: ledgerText(VALID_RUN_ID, { activated: false }) });
    const inactiveResult = await runObserveHandshake(inactive.runConfig, inactive.runtime);
    assert.equal(inactiveResult.observation_status, "BLOCKED");
    assert.equal(inactive.calls.launches, 0);
    const inactiveEvidence = JSON.parse(readFileSync(join(inactive.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(inactiveEvidence.provider_attempt_ledger.before_login.state, "guard_not_started");
    assert.equal(inactiveEvidence.provider_attempt_ledger.before_login.reservation_count, null);
    assert.equal(inactiveEvidence.provider_attempt_ledger.before_login.refusal_count, null);
    assert.equal(inactiveEvidence.setup.shell_loaded, "unknown");

    const reserved = makeRuntime(scratch, {
      initialLedger: ledgerText(VALID_RUN_ID, { reservations: 1 }),
    });
    const reservedResult = await runObserveHandshake(reserved.runConfig, reserved.runtime);
    assert.equal(reservedResult.observation_status, "FAIL");
    assert.equal(reserved.calls.launches, 0);
    const refusal = makeRuntime(scratch, {
      initialLedger: ledgerText(VALID_RUN_ID, { reservations: PROVIDER_ATTEMPT_BUDGET, refusals: 1 }),
    });
    const refusalResult = await runObserveHandshake(refusal.runConfig, refusal.runtime);
    assert.equal(refusalResult.observation_status, "FAIL");
    assert.equal(refusalResult.failure_categories.includes("provider_ledger_refusal"), true);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("a ledger violation observed while login waits fails without dispatching a second pass", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch, {
      connectedDelayMs: 325,
      afterConnectedLedger: ledgerText(VALID_RUN_ID, { reservations: 1 }),
    });
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "FAIL");
    assert.equal(result.failure_categories.includes("provider_ledger_reservation"), true);
    assert.equal(fixture.events.filter((event) => event === "page-goto").length, 1);
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("a transient invalid monitor observation blocks even when later ledger checkpoints recover", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch, {
      connectedDelayMs: 400,
      monitorLedgerText: "invalid transient ledger\n",
      monitorLedgerRestoreMs: 300,
    });
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "BLOCKED");
    assert.equal(result.failure_categories.includes("provider_ledger_invalid"), true);
    const evidence = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"));
    assert.equal(evidence.provider_attempt_ledger.monitor_state, "unavailable");
    assert.equal(evidence.provider_attempt_ledger.after_observation_active.state, "active_zero");
    assert.equal(evidence.provider_attempt_ledger.final_copied.state, "active_zero");
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("all cleanup steps run when page close, host stop, or final port probes fail", async () => {
  const scratch = makeScratch();
  try {
    const fixture = makeRuntime(scratch, {
      pageCloseFailure: true,
      contextCloseFailure: true,
      browserCloseFailure: true,
      hostStopFailure: true,
      portsFree: false,
    });
    const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
    assert.equal(result.observation_status, "FAIL");
    assert.equal(fixture.calls.hostStop, 1);
    assert.deepEqual(fixture.calls.probes, [8360, 8370]);
    assert.ok(fixture.events.includes("page-close"));
    assert.ok(fixture.events.includes("context-close"));
    assert.ok(fixture.events.includes("browser-close"));
    assert.ok(existsSync(join(fixture.evidenceDirectory, "provider-attempt-ledger.jsonl")));
    assert.ok(existsSync(join(fixture.evidenceDirectory, "managed-host-output.json")));
    assert.ok(existsSync(join(fixture.evidenceDirectory, "summary.json")));
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("final run or summary evidence write failures force FAIL and get one bounded fail-closed repair", async () => {
  const scratch = makeScratch();
  try {
    for (const config of [{ failFinalRunWriteOnce: true }, { failSummaryWriteOnce: true }]) {
      const fixture = makeRuntime(scratch, config);
      const result = await runObserveHandshake(fixture.runConfig, fixture.runtime);
      assert.equal(result.observation_status, "FAIL");
      assert.equal(result.exit_code, 1);
      assert.equal(handshakeObservationExitCode(result.observation_status), 1);
      assert.equal(result.failure_categories.includes("evidence_write_failed"), true);
      assert.equal(fixture.calls.hostStop, 1);
      assert.deepEqual(fixture.calls.probes, [8360, 8370]);

      const run = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "run.json"), "utf8"));
      const summary = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "summary.json"), "utf8"));
      const observation = JSON.parse(readFileSync(join(fixture.evidenceDirectory, "handshake-observation.json"), "utf8"));
      assert.equal(run.observation_status, "FAIL");
      assert.equal(summary.observation_status, "FAIL");
      assert.equal(run.failure_categories.includes("evidence_write_failed"), true);
      assert.equal(summary.failure_categories.includes("evidence_write_failed"), true);
      assert.equal(observation.failure_categories.includes("evidence_write_failed"), true);
      assert.equal(run.provider_attempt_budget.checkpoints.before_login.state, "active_zero");
      assert.equal(run.provider_attempt_budget.checkpoints.after_observation_active.state, "active_zero");
      assert.equal(run.provider_attempt_budget.checkpoints.final_copied.state, "active_zero");
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("actual observer CLI imports the full runtime under filesystem, process, network, browser, and credential tripwires", () => {
  const preload = fileURLToPath(new URL("./observer-tripwire-preload.mjs", import.meta.url));
  const driver = fileURLToPath(new URL("./n2-gate.mjs", import.meta.url));
  const cleanEnvironment = Object.fromEntries(Object.entries(process.env)
    .filter(([key]) => !key.startsWith("NEQ_") && key !== "NODE_OPTIONS"));
  cleanEnvironment.NEQ_OBSERVER_TRIPWIRES = "1";
  const result = spawnSync(process.execPath, ["--import", preload, driver, "--dry-run", "--observe-handshake"], {
    cwd: REPOSITORY_ROOT,
    env: cleanEnvironment,
    encoding: "utf8",
    timeout: 30_000,
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /"runtime_import_preflight": "passed"/);
  assert.match(result.stdout, /"playwright\/test"/);
  assert.match(result.stdout, /"\.\/login-player\.mjs"/);
  assert.match(result.stdout, /"credentials_generated": false/);
  assert.match(result.stdout, /"ports_bound": false/);
  assert.doesNotMatch(result.stderr, /TRIPWIRE/);
});

test("observer mode refuses conflicting P4 and browser flags before runtime effects", () => {
  const preload = fileURLToPath(new URL("./observer-tripwire-preload.mjs", import.meta.url));
  const driver = fileURLToPath(new URL("./n2-gate.mjs", import.meta.url));
  const cleanEnvironment = Object.fromEntries(Object.entries(process.env)
    .filter(([key]) => !key.startsWith("NEQ_") && key !== "NODE_OPTIONS"));
  cleanEnvironment.NEQ_OBSERVER_TRIPWIRES = "1";
  for (const args of [
    ["--dry-run", "--observe-handshake", "--party-size", "4"],
    ["--dry-run", "--observe-handshake", "--browsers", "chrome+firefox"],
  ]) {
    const result = spawnSync(process.execPath, ["--import", preload, driver, ...args], {
      cwd: REPOSITORY_ROOT,
      env: cleanEnvironment,
      encoding: "utf8",
      timeout: 15_000,
    });
    assert.equal(result.status, 2, `${result.stdout}\n${result.stderr}`);
    assert.doesNotMatch(result.stderr, /TRIPWIRE/);
  }
  const inheritedCredential = spawnSync(process.execPath, [
    "--import", preload, driver, "--dry-run", "--observe-handshake",
  ], {
    cwd: REPOSITORY_ROOT,
    env: { ...cleanEnvironment, NEQ_N2_PLAYER_PASSWORD: "1" },
    encoding: "utf8",
    timeout: 15_000,
  });
  assert.equal(inheritedCredential.status, 2, `${inheritedCredential.stdout}\n${inheritedCredential.stderr}`);
  assert.match(inheritedCredential.stderr, /refuses inherited owner player credentials/);
  assert.doesNotMatch(inheritedCredential.stdout, /NEQ_N2_PLAYER_PASSWORD|"1"/);
  assert.doesNotMatch(inheritedCredential.stderr, /TRIPWIRE/);
});

test("ordinary gate dry-run keeps its default Chrome and Firefox selection", () => {
  const driver = fileURLToPath(new URL("./n2-gate.mjs", import.meta.url));
  const result = spawnSync(process.execPath, [driver, "--dry-run"], {
    cwd: REPOSITORY_ROOT,
    env: Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("NEQ_"))),
    encoding: "utf8",
    timeout: 15_000,
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /"browsers_requested": \[\s*"chrome",\s*"firefox"\s*\]/);
  assert.doesNotMatch(result.stdout, /N2_HANDSHAKE_OBSERVATION/);
});

function readEvidenceText(directory) {
  return readdirSync(directory, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => readFileSync(join(directory, entry.name), "utf8"))
    .join("\n");
}
