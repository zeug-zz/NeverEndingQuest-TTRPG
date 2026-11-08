// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { createHash } from "node:crypto";
import {
  cpSync,
  existsSync,
  lstatSync,
  readFileSync,
  readdirSync,
  renameSync,
  rmSync,
  appendFileSync,
} from "node:fs";
import { basename, isAbsolute, join, relative, resolve, sep } from "node:path";
import {
  isLoopbackPortFree,
  N2_PLAYER_PORT,
  validateManagedSandboxRoot,
} from "./managed-host.mjs";
import { FIREFOX_UNAVAILABLE_REASON, launchN2Browsers } from "./browser-contract.mjs";
import { redactEvidenceText } from "./redaction.mjs";

const LIFECYCLE_IDS = ["server-instance-change", "missing-bundle", "broken-bundle"];
const HOST_URL = "http://127.0.0.1:8360";
const PLAYER_URL = "http://127.0.0.1:8370";

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
    throw new Error("Lifecycle path is not contained by its expected root.");
  }
  let current = parent;
  if (lstatIfExists(current)?.isSymbolicLink()) {
    throw new Error("Lifecycle paths must not traverse symlinks.");
  }
  for (const component of relative(parent, candidate).split(sep)) {
    current = join(current, component);
    if (lstatIfExists(current)?.isSymbolicLink()) {
      throw new Error("Lifecycle paths must not traverse symlinks.");
    }
  }
}

function assertTreeHasNoSymlinks(path) {
  const entry = lstatSync(path);
  if (entry.isSymbolicLink()) throw new Error("The player bundle must not contain symlinks.");
  if (entry.isDirectory()) {
    for (const child of readdirSync(path)) assertTreeHasNoSymlinks(join(path, child));
  } else if (!entry.isFile()) {
    throw new Error("The player bundle may contain only regular files and directories.");
  }
}

function repositoryTmpRoot(repositoryRoot) {
  return resolve(repositoryRoot, "tmp");
}

function validateEvidenceDirectory(repositoryRoot, evidenceDirectory) {
  const tmpRoot = repositoryTmpRoot(repositoryRoot);
  const evidenceRoot = resolve(evidenceDirectory);
  assertNoSymlinkPath(tmpRoot, evidenceRoot);
  if (!existsSync(evidenceRoot) || !lstatSync(evidenceRoot).isDirectory()) {
    throw new Error("Lifecycle evidence must use an existing project-local tmp/ directory.");
  }
  return evidenceRoot;
}

function safeAssetEntry(entry, filename) {
  return entry !== null && typeof entry === "object" &&
    typeof entry.file === "string" && entry.file === filename &&
    filename === basename(filename) && filename !== "." && filename !== ".." &&
    !/[\\/]/.test(filename) && typeof entry.sha256 === "string" &&
    /^[a-f0-9]{64}$/.test(entry.sha256) &&
    Number.isSafeInteger(entry.bytes) && entry.bytes >= 0;
}

function sha256(contents) {
  return createHash("sha256").update(contents).digest("hex");
}

export function readVerifiedBundleSnapshot(repositoryRoot, sandboxRoot) {
  const sandbox = validateManagedSandboxRoot(repositoryRoot, sandboxRoot);
  const distRoot = join(sandbox, "web", "frontend", "dist");
  assertNoSymlinkPath(sandbox, distRoot);
  if (!existsSync(distRoot) || !lstatSync(distRoot).isDirectory()) {
    throw new Error("The sandbox player dist/ bundle is missing or invalid.");
  }
  assertTreeHasNoSymlinks(distRoot);

  const manifestPath = join(distRoot, "player-manifest.json");
  if (!existsSync(manifestPath) || !lstatSync(manifestPath).isFile()) {
    throw new Error("The sandbox player manifest is missing or invalid.");
  }
  const manifestContents = readFileSync(manifestPath);
  if (manifestContents.byteLength > 64 * 1024) {
    throw new Error("The sandbox player manifest exceeds its size bound.");
  }
  let manifest;
  try {
    manifest = JSON.parse(manifestContents.toString("utf8"));
  } catch {
    throw new Error("The sandbox player manifest is not valid JSON.");
  }
  if (manifest === null || typeof manifest !== "object" ||
      manifest.manifest_version !== 1 || !manifest.shell ||
      manifest.assets === null || typeof manifest.assets !== "object" ||
      Array.isArray(manifest.assets)) {
    throw new Error("The sandbox player manifest has an unsupported shape.");
  }

  const descriptors = [manifest.shell, ...Object.values(manifest.assets)];
  const seenFiles = new Set();
  const files = {};
  for (const descriptor of descriptors) {
    if (!descriptor || typeof descriptor.file !== "string" || seenFiles.has(descriptor.file) ||
        !safeAssetEntry(descriptor, descriptor.file)) {
      throw new Error("The sandbox player manifest contains an unsafe asset entry.");
    }
    seenFiles.add(descriptor.file);
    const assetPath = join(distRoot, descriptor.file);
    if (!existsSync(assetPath) || !lstatSync(assetPath).isFile()) {
      throw new Error("The sandbox player bundle is incomplete.");
    }
    const contents = readFileSync(assetPath);
    const digest = sha256(contents);
    if (contents.byteLength !== descriptor.bytes || digest !== descriptor.sha256) {
      throw new Error("A sandbox player asset does not match its manifest digest.");
    }
    files[descriptor.file] = { sha256: digest, bytes: contents.byteLength };
  }

  return {
    manifest_sha256: sha256(manifestContents),
    files,
    asset_files: Object.keys(manifest.assets),
  };
}

export function moveSandboxDistToBackup(repositoryRoot, sandboxRoot, evidenceDirectory, scenarioId) {
  const sandbox = validateManagedSandboxRoot(repositoryRoot, sandboxRoot);
  const evidenceRoot = validateEvidenceDirectory(repositoryRoot, evidenceDirectory);
  if (!/^(missing|broken)-bundle$/.test(scenarioId)) {
    throw new Error("Unknown managed bundle scenario.");
  }
  const distRoot = join(sandbox, "web", "frontend", "dist");
  const backupPath = join(evidenceRoot, `managed-${scenarioId}-original-dist`);
  assertNoSymlinkPath(sandbox, distRoot);
  assertNoSymlinkPath(evidenceRoot, backupPath);
  if (existsSync(backupPath)) throw new Error("The managed bundle recovery path already exists.");
  const snapshot = readVerifiedBundleSnapshot(repositoryRoot, sandbox);
  renameSync(distRoot, backupPath);
  return { distRoot, backupPath, snapshot };
}

export function copySandboxDistFromBackup(repositoryRoot, sandboxRoot, backupPath) {
  const sandbox = validateManagedSandboxRoot(repositoryRoot, sandboxRoot);
  const distRoot = join(sandbox, "web", "frontend", "dist");
  const tmpRoot = repositoryTmpRoot(repositoryRoot);
  assertNoSymlinkPath(tmpRoot, resolve(backupPath));
  if (isContainedPath(sandbox, resolve(backupPath))) {
    throw new Error("The bundle recovery copy must remain outside the sandbox tree.");
  }
  if (!existsSync(backupPath) || !lstatSync(backupPath).isDirectory()) {
    throw new Error("The original sandbox bundle recovery copy is missing.");
  }
  assertTreeHasNoSymlinks(backupPath);
  if (existsSync(distRoot)) throw new Error("Refusing to overwrite a sandbox dist/ directory.");
  cpSync(backupPath, distRoot, { recursive: true, errorOnExist: true, force: false });
}

export function corruptSandboxBundle(repositoryRoot, sandboxRoot, snapshot) {
  const sandbox = validateManagedSandboxRoot(repositoryRoot, sandboxRoot);
  const distRoot = join(sandbox, "web", "frontend", "dist");
  const assetName = snapshot.asset_files[0];
  if (typeof assetName !== "string" || !snapshot.files[assetName]) {
    throw new Error("The verified sandbox bundle has no corruptible listed asset.");
  }
  const assetPath = join(distRoot, assetName);
  assertNoSymlinkPath(distRoot, assetPath);
  appendFileSync(assetPath, Buffer.from([0]));
  return assetName;
}

export function restoreSandboxDist(repositoryRoot, sandboxRoot, backupPath, snapshot) {
  const sandbox = validateManagedSandboxRoot(repositoryRoot, sandboxRoot);
  const tmpRoot = repositoryTmpRoot(repositoryRoot);
  assertNoSymlinkPath(tmpRoot, resolve(backupPath));
  if (isContainedPath(sandbox, resolve(backupPath))) {
    throw new Error("The bundle recovery copy must remain outside the sandbox tree.");
  }
  const distRoot = join(sandbox, "web", "frontend", "dist");
  if (!existsSync(backupPath) || !lstatSync(backupPath).isDirectory()) {
    throw new Error("The original sandbox bundle recovery copy is unavailable; restore failed.");
  }
  assertTreeHasNoSymlinks(backupPath);
  if (existsSync(distRoot)) {
    assertNoSymlinkPath(sandbox, distRoot);
    if (!lstatSync(distRoot).isDirectory()) {
      throw new Error("The sandbox dist/ path is not a directory; refusing unsafe restoration.");
    }
    rmSync(distRoot, { recursive: true, force: false });
  }
  renameSync(backupPath, distRoot);
  const restored = readVerifiedBundleSnapshot(repositoryRoot, sandbox);
  if (JSON.stringify(restored) !== JSON.stringify(snapshot)) {
    throw new Error("The original sandbox manifest or asset digests changed during restoration.");
  }
  return restored;
}

function safeErrorMessage(error, password, verifier = process.env.NEQ_PLAYER_PASSWORD_VERIFIER) {
  const message = error instanceof Error ? error.message : String(error);
  return redactEvidenceText(
    message,
    [password, verifier],
    4096,
  );
}

function parseSocketEvent(message) {
  if (typeof message !== "string" || !message.startsWith("42/player,")) return null;
  try {
    const packet = JSON.parse(message.slice("42/player,".length));
    if (!Array.isArray(packet) || typeof packet[0] !== "string") return null;
    return { name: packet[0], payload: packet[1] };
  } catch {
    return null;
  }
}

async function waitFor(predicate, timeoutMs, message) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await new Promise((resolveSleep) => setTimeout(resolveSleep, 50));
  }
  if (!(await predicate())) throw new Error(message);
}

async function loginPlayer(page, password) {
  await page.getByRole("heading", { name: "Player login" }).waitFor({ state: "visible", timeout: 15_000 });
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.getByRole("heading", { name: "NeverEndingQuest player" }).waitFor({ state: "visible", timeout: 15_000 });
  await page.getByText("Connected", { exact: true }).waitFor({ state: "visible", timeout: 15_000 });
}

async function readSnapshot(page) {
  return page.evaluate(async () => {
    const build = document.querySelector('meta[name="neq-client-build"]')?.content;
    const protocol = document.querySelector('meta[name="neq-protocol-version"]')?.content;
    if (!build || !protocol) throw new Error("Player build metadata is missing.");
    const response = await fetch("/api/player/snapshot", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "X-NEQ-Client-Build": build,
        "X-NEQ-Protocol-Version": protocol,
      },
    });
    if (!response.ok) throw new Error(`Player snapshot returned HTTP ${response.status}.`);
    return response.json();
  });
}

async function assertHostUi(page) {
  await page.goto(HOST_URL, { waitUntil: "domcontentloaded", timeout: 15_000 });
  await page.locator("#game-output").waitFor({ state: "attached", timeout: 15_000 });
  const input = page.locator("#user-input");
  await input.waitFor({ state: "attached", timeout: 15_000 });
  if (!(await input.isEnabled())) throw new Error("The host gameplay input is disabled.");
  const probe = "N2_HOST_UI_LOCAL_USABILITY_PROBE";
  await input.fill(probe);
  if ((await input.inputValue()) !== probe) throw new Error("The host input did not accept local text entry.");
  await input.fill("");
  return {
    host_http_status: 200,
    game_output_attached: true,
    user_input_enabled_and_editable: true,
    probe_submitted: false,
  };
}

async function assertPlayerListenerClosed(playerContexts) {
  let response = null;
  try {
    response = await fetch(PLAYER_URL, { signal: AbortSignal.timeout(2_000) });
  } catch {
    // A refused loopback connection is the expected fail-closed state.
  }
  if (response !== null) throw new Error("The player listener returned a response with an invalid bundle.");
  if (!(await isLoopbackPortFree(N2_PLAYER_PORT))) {
    throw new Error("The player listener port remained occupied after asset preflight failed.");
  }

  for (const player of playerContexts) {
    const probePage = await player.context.newPage();
    try {
      const browserResponse = await probePage.goto(PLAYER_URL, {
        waitUntil: "domcontentloaded",
        timeout: 5_000,
      }).catch(() => null);
      if (browserResponse !== null) {
        throw new Error(`Player browser ${player.browser} received a page while the bundle was invalid.`);
      }
    } finally {
      await probePage.close();
    }
  }
  return {
    player_http_unreachable: true,
    player_port_free: true,
    player_contexts_probed: playerContexts.map((player) => player.browser),
  };
}

async function captureScreenshot(page, evidenceDirectory, name) {
  const path = join(evidenceDirectory, "screenshots", `${name}.png`);
  await page.screenshot({ path, fullPage: true, animations: "disabled" });
  return relative(evidenceDirectory, path).split(sep).join("/");
}

async function recordScenario(id, expected, password, verifier, run, signal) {
  const result = {
    id,
    expected,
    observed: null,
    verdict: "PASS",
    artifacts: [],
    recorded_at_utc: new Date().toISOString(),
  };
  try {
    if (signal?.aborted) throw new Error("The managed lifecycle phase was cancelled by an operator signal.");
    const outcome = await run();
    result.observed = outcome.observed;
    result.checks = outcome.checks ?? [];
    result.artifacts = outcome.artifacts ?? [];
  } catch (error) {
    result.verdict = "FAIL";
    result.observed = { error: safeErrorMessage(error, password, verifier) };
  }
  return result;
}

async function runServerInstanceScenario({ manager, playerContextOne, playerContextTwo, hostContext, evidenceDirectory, partySize, runId, password, signal }) {
  const tracking = { websocketRoutes: 0, requestIds: [], acceptedReceiptsDropped: 0 };
  await playerContextOne.routeWebSocket("**/socket.io/**", (route) => {
    tracking.websocketRoutes += 1;
    const server = route.connectToServer();
    route.onMessage((message) => {
      const packet = parseSocketEvent(message);
      if (packet?.name === "player.input.submit" && typeof packet.payload?.request_id === "string") {
        tracking.requestIds.push(packet.payload.request_id);
      }
      server.send(message);
    });
    server.onMessage((message) => {
      const packet = parseSocketEvent(message);
      if (packet?.name === "player.input.receipt" &&
          packet.payload?.request_id === tracking.requestIds[0] &&
          packet.payload?.status === "accepted") {
        tracking.acceptedReceiptsDropped += 1;
        return;
      }
      route.send(message);
    });
  });

  const playerPageOne = await playerContextOne.newPage();
  const playerPageTwo = playerContextTwo ? await playerContextTwo.newPage() : null;
  const hostPage = await hostContext.newPage();
  await Promise.all([
    playerPageOne.goto(PLAYER_URL, { waitUntil: "domcontentloaded" }),
    ...(playerPageTwo ? [playerPageTwo.goto(PLAYER_URL, { waitUntil: "domcontentloaded" })] : []),
    assertHostUi(hostPage),
  ]);
  await Promise.all([
    loginPlayer(playerPageOne, password),
    ...(playerPageTwo ? [loginPlayer(playerPageTwo, password)] : []),
  ]);
  const initialOne = await readSnapshot(playerPageOne);
  const initialTwo = playerPageTwo ? await readSnapshot(playerPageTwo) : null;
  if (initialTwo && initialOne.instance_id !== initialTwo.instance_id) {
    throw new Error("Chrome and Firefox clients did not hydrate the same server instance.");
  }
  const marker = `N2_INSTANCE_CHANGE_${runId}`;
  await playerPageOne.locator("#gameplay-input").fill(marker);
  await playerPageOne.getByRole("button", { name: "Submit input" }).click();
  await waitFor(
    () => tracking.websocketRoutes > 0 && tracking.requestIds.length === 1 && tracking.acceptedReceiptsDropped === 1,
    20_000,
    "The accepted player receipt could not be held while the browser page remained open.",
  );
  const requestId = tracking.requestIds[0];
  if (!requestId) throw new Error("The player request ID was not observed on the player socket.");
  await waitFor(async () =>
    (await playerPageOne.locator(".transcript-message").filter({ hasText: marker }).count()) === 1,
  20_000,
  "The accepted instance-change probe did not appear exactly once in the player transcript.");
  await playerPageOne.getByText(/Sending input for .* at revision \d+\.\.\./).waitFor({ state: "visible" });

  await manager.stop();
  await Promise.all([
    playerPageOne.getByText("Disconnected", { exact: true }).waitFor({ state: "visible", timeout: 15_000 }),
    ...(playerPageTwo
      ? [playerPageTwo.getByText("Disconnected", { exact: true }).waitFor({ state: "visible", timeout: 15_000 })]
      : []),
  ]);
  const uncertainNotice = playerPageOne.getByRole("alert").filter({ hasText: "The action may or may not have applied" });
  await uncertainNotice.waitFor({ state: "visible", timeout: 10_000 });
  if (playerPageTwo) {
    await playerPageTwo.getByRole("alert")
      .filter({ hasText: "The action may or may not have applied" })
      .waitFor({ state: "visible", timeout: 10_000 });
  }
  const uncertainScreenshot = await captureScreenshot(
    playerPageOne,
    evidenceDirectory,
    "server-instance-change-uncertain-player",
  );

  await manager.start({ playerExpected: true, signal });
  await Promise.all([
    playerPageOne.reload({ waitUntil: "domcontentloaded" }),
    ...(playerPageTwo ? [playerPageTwo.reload({ waitUntil: "domcontentloaded" })] : []),
  ]);
  await Promise.all([
    loginPlayer(playerPageOne, password),
    ...(playerPageTwo ? [loginPlayer(playerPageTwo, password)] : []),
  ]);
  const resynchronizedOne = await readSnapshot(playerPageOne);
  const resynchronizedTwo = playerPageTwo ? await readSnapshot(playerPageTwo) : null;
  if (resynchronizedOne.instance_id === initialOne.instance_id ||
      (resynchronizedTwo && resynchronizedTwo.instance_id === initialTwo?.instance_id)) {
    throw new Error("The restarted player listener did not issue a new server instance ID.");
  }
  if (resynchronizedTwo && resynchronizedOne.instance_id !== resynchronizedTwo.instance_id) {
    throw new Error("Chrome and Firefox clients did not resynchronize to the same server instance.");
  }
  if (resynchronizedOne.projection.party.members.length !== partySize ||
      (resynchronizedTwo && resynchronizedTwo.projection.party.members.length !== partySize)) {
    throw new Error("The post-restart snapshot did not resynchronize the expected party shape.");
  }
  if ((await playerPageOne.locator("#gameplay-input").inputValue()) !== "" ||
      (playerPageTwo && (await playerPageTwo.locator("#gameplay-input").inputValue()) !== "")) {
    throw new Error("A pre-restart input draft was replayed after resynchronization.");
  }
  const matchingSubmissions = tracking.requestIds.filter((id) => id === requestId).length;
  if (matchingSubmissions !== 1) {
    throw new Error("The pre-restart request ID was replayed or duplicated after reconnect.");
  }
  const markerCountOne = await playerPageOne.locator(".transcript-message").filter({ hasText: marker }).count();
  const markerCountTwo = playerPageTwo
    ? await playerPageTwo.locator(".transcript-message").filter({ hasText: marker }).count()
    : null;
  if (markerCountOne !== 1 || (markerCountTwo !== null && markerCountTwo !== 1)) {
    throw new Error("The transcript did not retain exactly one copy of the pre-restart input.");
  }
  const hostUi = await assertHostUi(hostPage);
  const resynchronizedScreenshot = await captureScreenshot(
    playerPageOne,
    evidenceDirectory,
    "server-instance-change-resynchronized-player",
  );
  const firefoxResynchronizedScreenshot = playerPageTwo
    ? await captureScreenshot(playerPageTwo, evidenceDirectory, "server-instance-change-resynchronized-firefox-player")
    : null;
  const hostScreenshot = await captureScreenshot(
    hostPage,
    evidenceDirectory,
    "server-instance-change-host-ui",
  );
  const checks = [{
    id: "chrome-server-instance-resync",
    verdict: "PASS",
    observed: {
      uncertain_before_restart: true,
      new_instance_id: resynchronizedOne.instance_id,
      request_id_submissions: matchingSubmissions,
      transcript_marker_count: markerCountOne,
      authoritative_snapshot_resynchronized: true,
    },
  }];
  if (playerPageTwo && resynchronizedTwo && markerCountTwo !== null) {
    checks.push({
      id: "firefox-server-instance-resync",
      verdict: "PASS",
      observed: {
        uncertain_before_restart: true,
        new_instance_id: resynchronizedTwo.instance_id,
        transcript_marker_count: markerCountTwo,
        authoritative_snapshot_resynchronized: true,
      },
    });
  }
  return {
    observed: {
      player_a_browser: "Chrome",
      player_b_browser: playerPageTwo ? "Firefox" : null,
      old_instance_id: initialOne.instance_id,
      new_instance_id: resynchronizedOne.instance_id,
      uncertainty_visible_before_reload: true,
      request_id_submissions: matchingSubmissions,
      transcript_marker_count_after_resync: {
        player_a_chrome: markerCountOne,
        player_b_firefox: markerCountTwo,
      },
      authoritative_snapshot_resynchronized: true,
      party_size: resynchronizedOne.projection.party.members.length,
      host_ui_after_restart: hostUi,
    },
    checks,
    artifacts: [uncertainScreenshot, resynchronizedScreenshot, firefoxResynchronizedScreenshot, hostScreenshot]
      .filter(Boolean),
  };
}

async function runBundleScenario({
  id,
  repositoryRoot,
  sandboxRoot,
  manager,
  hostContext,
  playerContexts,
  evidenceDirectory,
  originalSnapshot,
  corrupt,
  password,
  verifier,
  signal,
}) {
  let backup = null;
  let observed = null;
  let failure = null;
  let restorationFailure = null;
  const hostPage = await hostContext.newPage();
  try {
    await manager.stop();
    const before = readVerifiedBundleSnapshot(repositoryRoot, sandboxRoot);
    if (JSON.stringify(before) !== JSON.stringify(originalSnapshot)) {
      throw new Error("Sandbox player bundle changed before its managed failure phase.");
    }
    backup = moveSandboxDistToBackup(repositoryRoot, sandboxRoot, evidenceDirectory, id);
    let corruptedAsset = null;
    if (corrupt) {
      copySandboxDistFromBackup(repositoryRoot, sandboxRoot, backup.backupPath);
      corruptedAsset = corruptSandboxBundle(repositoryRoot, sandboxRoot, backup.snapshot);
    }

    await manager.start({ playerExpected: false, signal });
    const hostUi = await assertHostUi(hostPage);
    const playerClosed = await assertPlayerListenerClosed(playerContexts);
    const hostScreenshot = await captureScreenshot(hostPage, evidenceDirectory, `${id}-host-ui`);
    observed = {
      bundle_state: corrupt ? "listed asset digest mismatch" : "dist directory absent",
      corrupted_asset: corruptedAsset,
      host_ui_usable: hostUi,
      player_listener_fail_closed: playerClosed,
    };
    backup.artifacts = [hostScreenshot];
  } catch (error) {
    failure = error;
  } finally {
    try {
      await manager.stop();
      if (backup !== null) {
        restoreSandboxDist(repositoryRoot, sandboxRoot, backup.backupPath, backup.snapshot);
        const restored = readVerifiedBundleSnapshot(repositoryRoot, sandboxRoot);
        if (JSON.stringify(restored) !== JSON.stringify(originalSnapshot)) {
          throw new Error("Restored manifest digests differ from the original run bundle.");
        }
      }
    } catch (error) {
      restorationFailure = error;
    }
  }
  await hostPage.close();
  if (restorationFailure !== null) {
    const restoreMessage = safeErrorMessage(restorationFailure, password, verifier);
    const primaryMessage = failure === null ? null : safeErrorMessage(failure, password, verifier);
    throw new Error(`Bundle restoration failed: ${restoreMessage}${primaryMessage ? `; phase error: ${primaryMessage}` : ""}`);
  }
  if (failure !== null) throw failure;
  const chromeCheckId = id === "missing-bundle"
    ? "chrome-missing-bundle-host-and-player"
    : "chrome-broken-bundle-host-and-player";
  const firefoxCheckId = id === "missing-bundle"
    ? "firefox-missing-bundle-player"
    : "firefox-broken-bundle-player";
  const checks = [{
    id: chromeCheckId,
    verdict: "PASS",
    observed: {
      host_ui_usable: observed.host_ui_usable,
      chrome_player_listener_fail_closed: observed.player_listener_fail_closed,
      original_bundle_restored: true,
    },
  }];
  if (observed.player_listener_fail_closed.player_contexts_probed.includes("Firefox")) {
    checks.push({
      id: firefoxCheckId,
      verdict: "PASS",
      observed: { firefox_player_listener_fail_closed: true },
    });
  }
  return {
    observed: { ...observed, original_manifest_and_asset_digests_restored: true },
    checks,
    artifacts: backup?.artifacts ?? [],
  };
}

function failedLifecycleRecord(id, expected, error, password, verifier) {
  return {
    id,
    expected,
    observed: { error: safeErrorMessage(error, password, verifier) },
    verdict: "FAIL",
    artifacts: [],
    recorded_at_utc: new Date().toISOString(),
  };
}

function completeLifecycleRecords(records, scenarioCatalog, browsers) {
  const recordById = new Map(records.map((record) => [record.id, record]));
  const scenarioById = new Map(scenarioCatalog.map((scenario) => [scenario.id, scenario]));
  return LIFECYCLE_IDS.map((id) => {
    const scenario = scenarioById.get(id);
    const record = recordById.get(id) ?? {
      id,
      expected: scenario?.description,
      observed: { reason: "managed-lifecycle-result-missing" },
      verdict: "FAIL",
      checks: [],
      artifacts: [],
      recorded_at_utc: new Date().toISOString(),
    };
    const existingChecks = new Map((record.checks ?? []).map((check) => [check.id, check]));
    const checks = (scenario?.checks ?? []).map((definition) => {
      const existing = existingChecks.get(definition.id);
      if (existing) return { ...existing, expected: definition.description };
      if (definition.requires_firefox && !browsers.includes("firefox")) {
        return {
          id: definition.id,
          expected: definition.description,
          observed: { reason: FIREFOX_UNAVAILABLE_REASON },
          verdict: "BLOCKED",
          reason: FIREFOX_UNAVAILABLE_REASON,
        };
      }
      const reason = record.verdict === "BLOCKED"
        ? record.observed?.reason ?? "managed-lifecycle-blocked"
        : "required-check-did-not-record-an-outcome";
      return {
        id: definition.id,
        expected: definition.description,
        observed: { reason },
        verdict: record.verdict === "BLOCKED" ? "BLOCKED" : "FAIL",
        reason,
      };
    });
    const verdict = record.verdict === "FAIL" || checks.some((check) => check.verdict === "FAIL")
      ? "FAIL"
      : record.verdict === "BLOCKED" || checks.some((check) => check.verdict === "BLOCKED")
        ? "BLOCKED"
        : "PASS";
    return { ...record, checks, verdict };
  });
}

export async function runManagedLifecycleScenarios({
  repositoryRoot,
  sandboxRoot,
  evidenceDirectory,
  manager,
  partySize,
  runId,
  password,
  verifier,
  browsers,
  scenarioCatalog,
  signal,
}) {
  const expected = new Map(scenarioCatalog.map((scenario) => [scenario.id, scenario.description]));
  let originalSnapshot;
  try {
    originalSnapshot = readVerifiedBundleSnapshot(repositoryRoot, sandboxRoot);
  } catch (error) {
    return completeLifecycleRecords(
      LIFECYCLE_IDS.map((id) => failedLifecycleRecord(id, expected.get(id), error, password, verifier)),
      scenarioCatalog,
      browsers,
    );
  }
  if (signal?.aborted) {
    const error = new Error("The managed lifecycle was cancelled by an operator signal.");
    return completeLifecycleRecords(
      LIFECYCLE_IDS.map((id) => failedLifecycleRecord(id, expected.get(id), error, password, verifier)),
      scenarioCatalog,
      browsers,
    );
  }

  let chromeBrowser;
  let firefoxBrowser;
  let playerContextOne;
  let playerContextTwo;
  let hostContext;
  let closeBrowserOnAbort;
  try {
    const playwright = await import("playwright");
    const launched = await launchN2Browsers(playwright, browsers);
    chromeBrowser = launched.chromeBrowser;
    firefoxBrowser = launched.firefoxBrowser ?? undefined;
    closeBrowserOnAbort = () => {
      void Promise.all([
        chromeBrowser?.close().catch(() => {}),
        firefoxBrowser?.close().catch(() => {}),
      ]);
    };
    signal?.addEventListener("abort", closeBrowserOnAbort, { once: true });
    if (signal?.aborted) closeBrowserOnAbort();
    playerContextOne = await chromeBrowser.newContext();
    if (firefoxBrowser) playerContextTwo = await firefoxBrowser.newContext();
    hostContext = await chromeBrowser.newContext();
  } catch (error) {
    await Promise.all([
      chromeBrowser?.close().catch(() => {}),
      firefoxBrowser?.close().catch(() => {}),
    ]);
    if (closeBrowserOnAbort) signal?.removeEventListener("abort", closeBrowserOnAbort);
    return completeLifecycleRecords(
      LIFECYCLE_IDS.map((id) => failedLifecycleRecord(id, expected.get(id), error, password, verifier)),
      scenarioCatalog,
      browsers,
    );
  }

  const playerContexts = [
    { browser: "Chrome", context: playerContextOne },
    ...(playerContextTwo ? [{ browser: "Firefox", context: playerContextTwo }] : []),
  ];
  const records = [];
  try {
    records.push(await recordScenario(
      "server-instance-change",
      expected.get("server-instance-change"),
      password,
      verifier,
      () => runServerInstanceScenario({
        manager,
        playerContextOne,
        playerContextTwo,
        hostContext,
        evidenceDirectory,
        partySize,
        runId,
        password,
        verifier,
        signal,
      }),
      signal,
    ));
    records.push(await recordScenario(
      "missing-bundle",
      expected.get("missing-bundle"),
      password,
      verifier,
      () => runBundleScenario({
        id: "missing-bundle",
        repositoryRoot,
        sandboxRoot,
        manager,
        hostContext,
        playerContexts,
        evidenceDirectory,
        originalSnapshot,
        corrupt: false,
        password,
        verifier,
        signal,
      }),
      signal,
    ));
    records.push(await recordScenario(
      "broken-bundle",
      expected.get("broken-bundle"),
      password,
      verifier,
      () => runBundleScenario({
        id: "broken-bundle",
        repositoryRoot,
        sandboxRoot,
        manager,
        hostContext,
        playerContexts,
        evidenceDirectory,
        originalSnapshot,
        corrupt: true,
        password,
        verifier,
        signal,
      }),
      signal,
    ));
  } finally {
    try {
      await manager.stop();
    } catch (error) {
      const record = records.find((item) => item.id === "broken-bundle") ?? records.at(-1);
      if (record) {
        record.verdict = "FAIL";
        record.observed = {
          ...(record.observed && typeof record.observed === "object" ? record.observed : {}),
          managed_host_teardown_error: safeErrorMessage(error, password, verifier),
        };
      }
    }
    await Promise.all([
      playerContextOne?.close().catch(() => {}),
      playerContextTwo?.close().catch(() => {}),
      hostContext?.close().catch(() => {}),
      chromeBrowser?.close().catch(() => {}),
      firefoxBrowser?.close().catch(() => {}),
    ]);
    if (closeBrowserOnAbort) signal?.removeEventListener("abort", closeBrowserOnAbort);
  }

  return completeLifecycleRecords(records, scenarioCatalog, browsers);
}
