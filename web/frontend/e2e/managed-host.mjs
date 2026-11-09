// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:net";
import {
  existsSync,
  lstatSync,
  readFileSync,
  realpathSync,
  statSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import {
  buildProviderAttemptEnvironment,
  providerAttemptLedgerPath,
} from "./provider-attempt-budget.mjs";
import {
  attachManagedHostOutputCapture,
  ManagedHostOutputCollector,
} from "./managed-host-output.mjs";

export const N2_HOST_PORT = 8360;
export const N2_PLAYER_PORT = 8370;
export const N2_GATE_PORTS = Object.freeze([N2_HOST_PORT, N2_PLAYER_PORT]);

const HOST_URL = `http://127.0.0.1:${N2_HOST_PORT}`;
const PLAYER_URL = `http://127.0.0.1:${N2_PLAYER_PORT}`;
const START_TIMEOUT_MS = 30_000;
const STOP_TIMEOUT_MS = 8_000;
const POLL_INTERVAL_MS = 200;
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const CONFIG_VALIDATOR_PYTHON = join(REPOSITORY_ROOT, ".venv", "bin", "python");
// Parse Python syntax without importing or executing sandbox config; source is stdin-only and output is one fixed token.
const WEB_PORT_CONFIG_VALIDATOR = [
  "import ast",
  "import io",
  "import sys",
  "import tokenize",
  "",
  "def has_non_port_binding(tree):",
  "    for node in ast.walk(tree):",
  "        if isinstance(node, ast.Name) and node.id == 'WEB_PORT' and isinstance(node.ctx, (ast.Store, ast.Del)):",
  "            continue",
  "        if isinstance(node, ast.Attribute) and node.attr == 'WEB_PORT' and isinstance(node.ctx, (ast.Store, ast.Del)):",
  "            return True",
  "        if isinstance(node, (ast.arg, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and getattr(node, 'arg', getattr(node, 'name', None)) == 'WEB_PORT':",
  "            return True",
  "        if isinstance(node, ast.ExceptHandler) and node.name == 'WEB_PORT':",
  "            return True",
  "        if isinstance(node, (ast.Global, ast.Nonlocal)) and 'WEB_PORT' in node.names:",
  "            return True",
  "        if isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) == 'WEB_PORT':",
  "            return True",
  "        if type(node).__name__ in ('MatchAs', 'MatchStar') and getattr(node, 'name', None) == 'WEB_PORT':",
  "            return True",
  "        if type(node).__name__ == 'MatchMapping' and getattr(node, 'rest', None) == 'WEB_PORT':",
  "            return True",
  "    return False",
  "",
  "def is_valid(source):",
  "    tree = ast.parse(source, mode='exec')",
  "    assignments = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'WEB_PORT']",
  "    if len(assignments) != 1:",
  "        return False",
  "    assignment = assignments[0]",
  "    target = assignment.targets[0]",
  "    stores = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == 'WEB_PORT' and isinstance(node.ctx, (ast.Store, ast.Del))]",
  "    if len(stores) != 1 or stores[0] is not target or has_non_port_binding(tree):",
  "        return False",
  "    value = assignment.value",
  "    if not isinstance(value, ast.Constant) or type(value.value) is not int or value.value != 8360:",
  "        return False",
  "    try:",
  "        for token in tokenize.generate_tokens(io.StringIO(source).readline):",
  "            if token.type == tokenize.OP and token.string == ';' and assignment.lineno <= token.start[0] <= assignment.end_lineno:",
  "                return False",
  "    except (tokenize.TokenError, IndentationError):",
  "        return False",
  "    return True",
  "",
  "try:",
  "    raw = sys.stdin.buffer.read()",
  "    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)",
  "    source = raw.decode(encoding)",
  "    result = is_valid(source)",
  "except Exception:",
  "    result = False",
  "sys.stdout.write('valid\\n' if result else 'invalid\\n')",
].join("\n");

function isContainedPath(parent, candidate) {
  const path = relative(parent, candidate);
  return path !== "" && path !== "." && path !== ".." &&
    !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

function lstatIfExists(path) {
  try {
    return lstatSync(path);
  } catch (error) {
    if (error?.code === "ENOENT") return null;
    throw error;
  }
}

function assertNoSymlinkPath(parent, candidate) {
  if (!isContainedPath(parent, candidate)) {
    throw new Error("Managed path is not contained by its expected root.");
  }
  let current = parent;
  if (lstatIfExists(current)?.isSymbolicLink()) {
    throw new Error("Managed paths must not traverse symlinks.");
  }
  for (const component of relative(parent, candidate).split(sep)) {
    current = join(current, component);
    if (lstatIfExists(current)?.isSymbolicLink()) {
      throw new Error("Managed paths must not traverse symlinks.");
    }
  }
}

export function validateManagedSandboxRoot(repositoryRoot, candidateRoot = join(repositoryRoot, "tmp", "combat_capture")) {
  const root = resolve(repositoryRoot);
  const expected = resolve(root, "tmp", "combat_capture");
  const candidate = resolve(candidateRoot);
  if (candidate !== expected) {
    throw new Error("Managed host may use only this repository's tmp/combat_capture sandbox.");
  }
  assertNoSymlinkPath(root, expected);
  if (!existsSync(expected) || !lstatSync(expected).isDirectory()) {
    throw new Error("The prepared tmp/combat_capture sandbox is missing or invalid.");
  }
  if (realpathSync(expected) !== expected) {
    throw new Error("The managed sandbox must resolve to its exact project-local path.");
  }

  const requiredFiles = ["run_web.py", "config.py"];
  for (const name of requiredFiles) {
    const path = join(expected, name);
    if (!existsSync(path) || !lstatSync(path).isFile()) {
      throw new Error(`The prepared sandbox is missing ${name}.`);
    }
  }
  const config = readFileSync(join(expected, "config.py"));
  const portValidation = spawnSync(
    CONFIG_VALIDATOR_PYTHON,
    ["-I", "-S", "-c", WEB_PORT_CONFIG_VALIDATOR],
    {
      cwd: REPOSITORY_ROOT,
      env: {},
      encoding: "utf8",
      input: config,
      maxBuffer: 64,
      timeout: 10_000,
      windowsHide: true,
      stdio: ["pipe", "pipe", "ignore"],
    },
  );
  if (portValidation.error || portValidation.status !== 0 || portValidation.stdout !== "valid\n") {
    throw new Error("The sandbox config must contain exactly one standalone WEB_PORT = 8360 assignment.");
  }

  const frontendRoot = join(expected, "web", "frontend");
  assertNoSymlinkPath(expected, frontendRoot);
  if (!existsSync(frontendRoot) || !statSync(frontendRoot).isDirectory()) {
    throw new Error("The sandbox player frontend directory is missing.");
  }
  return expected;
}

export function validateSandboxPython(repositoryRoot) {
  const python = resolve(repositoryRoot, ".venv", "bin", "python");
  if (!existsSync(python) || !statSync(python).isFile()) {
    throw new Error("The repository .venv/bin/python interpreter is required for managed mode.");
  }
  return python;
}

export function isLoopbackPortFree(port, onProbe = () => {}) {
  return new Promise((resolveResult) => {
    const server = createServer();
    let settled = false;
    const finish = (isFree, error = null) => {
      if (settled) return;
      settled = true;
      try {
        onProbe({
          port,
          status: isFree ? "free" : "error",
          error_code: error && typeof error.code === "string" && /^[A-Z0-9_]{1,32}$/.test(error.code)
            ? error.code
            : null,
        });
      } catch {
        // Probe reporting must not change the port-check result.
      }
      resolveResult(isFree);
    };
    server.once("error", (error) => finish(false, error));
    server.listen({ host: "127.0.0.1", port, exclusive: true }, () => {
      server.close((error) => finish(!error, error));
    });
  });
}

export async function assertGatePortsFree(checkPortFree = isLoopbackPortFree) {
  const occupied = [];
  for (const port of N2_GATE_PORTS) {
    if (!(await checkPortFree(port))) occupied.push(port);
  }
  if (occupied.length > 0) {
    throw new Error(`Managed mode requires free loopback ports ${N2_GATE_PORTS.join(" and ")}; occupied: ${occupied.join(", ")}.`);
  }
  return N2_GATE_PORTS;
}

async function sleep(milliseconds) {
  await new Promise((resolveSleep) => setTimeout(resolveSleep, milliseconds));
}

async function endpointAvailable(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
    return response.status === 200;
  } catch {
    return false;
  }
}

async function waitFor(predicate, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await sleep(POLL_INTERVAL_MS);
  }
  return Boolean(await predicate());
}

function signalOwnedProcessGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
  } catch (error) {
    if (error?.code !== "ESRCH") throw error;
  }
}

export class SandboxHostManager {
  constructor({
    repositoryRoot,
    sandboxRoot,
    pythonPath,
    runId,
    environment = process.env,
    spawnProcess = spawn,
    portCheck = assertGatePortsFree,
    portFreeProbe = isLoopbackPortFree,
    endpointProbe = endpointAvailable,
    signalProcessGroup = signalOwnedProcessGroup,
  }) {
    this.repositoryRoot = resolve(repositoryRoot);
    this.sandboxRoot = validateManagedSandboxRoot(this.repositoryRoot, sandboxRoot);
    this.pythonPath = pythonPath ?? validateSandboxPython(this.repositoryRoot);
    this.runId = runId;
    this.providerAttemptLedgerPath = providerAttemptLedgerPath(this.sandboxRoot, runId);
    this.environment = environment;
    this.spawnProcess = spawnProcess;
    this.portCheck = portCheck;
    this.portFreeProbe = portFreeProbe;
    this.endpointProbe = endpointProbe;
    this.signalProcessGroup = signalProcessGroup;
    this.outputCollector = new ManagedHostOutputCollector();
    this.outputCloseObserved = true;
    this.outputClosePromise = Promise.resolve();
    this.resolveOutputClose = null;
    this.child = null;
    this.spawnError = null;
  }

  outputSnapshot() {
    return this.outputCollector.snapshot();
  }

  get processInfo() {
    if (!this.child?.pid) return null;
    return {
      pid: this.child.pid,
      process_group_id: this.child.pid,
      cwd: "tmp/combat_capture",
      command: ".venv/bin/python -c 'import run_web; run_web.main()'",
    };
  }

  async start({ playerExpected = true, signal } = {}) {
    if (process.platform === "win32") {
      throw new Error("Managed sandbox process-group lifecycle is supported on macOS and Linux only.");
    }
    if (this.child !== null) {
      throw new Error("The managed sandbox host is already owned by this gate run.");
    }
    if (!this.environment.NEQ_PLAYER_PASSWORD_VERIFIER) {
      throw new Error("NEQ_PLAYER_PASSWORD_VERIFIER must be injected for managed host startup.");
    }

    validateManagedSandboxRoot(this.repositoryRoot, this.sandboxRoot);
    if (signal?.aborted) throw new Error("Managed sandbox startup was cancelled.");
    await this.portCheck(this.portFreeProbe);
    if (signal?.aborted) throw new Error("Managed sandbox startup was cancelled.");
    let childEnvironment = { ...this.environment };
    delete childEnvironment.NEQ_N2_PLAYER_PASSWORD;
    delete childEnvironment.NEQ_N2_EVIDENCE_DIR;
    delete childEnvironment.NEQ_N2_HOST_URL;
    delete childEnvironment.NEQ_N2_PLAYER_URL;
    childEnvironment.NEQ_OPEN_BROWSER = "0";
    childEnvironment.NEQ_PLAYER_DEV_LISTENER = "1";
    childEnvironment.PYTHONPATH = this.sandboxRoot;
    const providerBudgetEnvironment = buildProviderAttemptEnvironment(
      childEnvironment,
      this.sandboxRoot,
      this.runId,
    );
    childEnvironment = providerBudgetEnvironment.environment;
    this.providerAttemptLedgerPath = providerBudgetEnvironment.ledgerPath;

    this.spawnError = null;
    const child = this.spawnProcess(this.pythonPath, ["-c", "import run_web; run_web.main()"], {
      cwd: this.sandboxRoot,
      detached: true,
      env: childEnvironment,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.child = child;
    attachManagedHostOutputCapture(child, this.outputCollector);
    this.outputCloseObserved = false;
    this.outputClosePromise = new Promise((resolveClose) => {
      this.resolveOutputClose = resolveClose;
    });
    child.once("close", (status, signal) => {
      this.outputCloseObserved = true;
      this.resolveOutputClose?.();
      this.resolveOutputClose = null;
    });
    child.once("error", (error) => {
      this.spawnError = error;
    });
    if (!child.pid) {
      this.child = null;
      throw new Error("The managed sandbox host process could not be created.");
    }

    let ready;
    try {
      ready = await waitFor(async () => {
        if (signal?.aborted) throw new Error("Managed sandbox startup was cancelled.");
        if (this.spawnError) throw new Error("The managed sandbox host process failed to spawn.");
        if (child.exitCode !== null || child.signalCode !== null) {
          throw new Error("The managed sandbox host process exited before readiness.");
        }
        const hostReady = await this.endpointProbe(HOST_URL);
        if (!hostReady) return false;
        if (playerExpected) return this.endpointProbe(PLAYER_URL);
        return this.portFreeProbe(N2_PLAYER_PORT);
      }, START_TIMEOUT_MS);
    } catch (error) {
      await this.stop().catch(() => {});
      throw error;
    }
    if (!ready) {
      const spawnFailed = this.spawnError !== null;
      await this.stop().catch(() => {});
      throw new Error(spawnFailed
        ? "The managed sandbox host process failed to start."
        : "The managed sandbox host did not reach the expected host/player readiness state.");
    }
    return this.processInfo;
  }

  async stop() {
    const child = this.child;
    if (child === null) return;
    const pid = child.pid;
    if (!pid) {
      this.child = null;
      return;
    }

    this.signalProcessGroup(pid, "SIGTERM");
    let stopped = await waitFor(async () => {
      const processExited = child.exitCode !== null || child.signalCode !== null;
      if (!processExited) return false;
      return (await this.portFreeProbe(N2_HOST_PORT)) && (await this.portFreeProbe(N2_PLAYER_PORT));
    }, STOP_TIMEOUT_MS);
    if (!stopped) {
      this.signalProcessGroup(pid, "SIGKILL");
      stopped = await waitFor(async () => {
        const processExited = child.exitCode !== null || child.signalCode !== null;
        if (!processExited) return false;
        return (await this.portFreeProbe(N2_HOST_PORT)) && (await this.portFreeProbe(N2_PLAYER_PORT));
      }, STOP_TIMEOUT_MS);
    }
    if (!stopped) {
      throw new Error("The owned sandbox process group did not stop with both gate ports released.");
    }
    const outputDrained = await waitFor(async () => this.outputCloseObserved, STOP_TIMEOUT_MS);
    if (!outputDrained) {
      throw new Error("The owned sandbox output streams did not close after process teardown.");
    }
    await this.outputClosePromise;
    this.child = null;
    this.spawnError = null;
  }
}
