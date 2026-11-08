// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { arch, platform, release } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium, firefox, type Browser } from "playwright";
import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type TestInfo,
} from "playwright/test";
import {
  DEFAULT_N2_BROWSER_SET,
  FIREFOX_UNAVAILABLE_REASON,
  createN2BrowserInstances,
  launchN2Browsers,
  parseN2BrowserSet,
} from "./browser-contract.mjs";
import { compareHostAndPlayerParty } from "./party-coherence.mjs";
import {
  providerAttemptLedgerPath,
  PROVIDER_ATTEMPT_BUDGET,
  requireProviderAttemptBudgetForGameplay,
} from "./provider-attempt-budget.mjs";
import {
  annotation,
  catalogDescription,
  ensureEvidenceFolders,
  evidenceDirectory,
  N2_SCENARIOS,
  relativeEvidencePath,
  scenarioAnnotation,
  scenarioBlocked,
  scenarioCheck,
  scenarioCheckDefinitions,
  scenarioObservation,
  updateRunMetadata,
  writeConsoleEvidence,
  writeScenarioEvidence,
} from "./evidence";

type TranscriptMessage = Readonly<{
  id: string;
  sequence: number;
  role: "user" | "assistant";
  text: string;
  author?: string;
}>;

type PlayerSnapshot = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  revision: number;
  event_cursor: number;
  projection: Readonly<{
    party: Readonly<{
      members: readonly Readonly<{ name: string }>[];
      active_character: string | null;
      active_character_revision: number;
    }>;
    transcript?: Readonly<{
      available: boolean;
      messages: readonly TranscriptMessage[];
    }>;
    combat?: Readonly<{
      available: boolean;
      active: boolean;
      round: number | null;
      phase: string | null;
      turn_order: readonly Readonly<{ name: string; initiative: number }>[];
    }>;
    busy?: boolean;
  }>;
}>;

type PlayerVersion = Readonly<{ clientBuildId: string; protocolVersion: number }>;
type SocketPacket = Readonly<{ event: string; payload: unknown }>;
type BrowserSocketRequest = Readonly<{
  events: readonly Readonly<{ name: string; payload: unknown }>[];
  expectedEventCounts: Readonly<Record<string, number>>;
  timeoutMs: number;
  sendAtEpochMs?: number;
}>;

let PLAYER_URL = "";
let HOST_URL = "";
let PARTY_SIZE = 0;
let PLAYER_PASSWORD = "";
let RUN_ID = "n2-run-unknown";
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const MANAGED_LIFECYCLE_SCENARIOS = new Set([
  "server-instance-change",
  "missing-bundle",
  "broken-bundle",
]);
const MANAGED_SANDBOX_HOST = process.env.NEQ_N2_MANAGE_SANDBOX_HOST === "1";
const REQUESTED_BROWSERS = parseN2BrowserSet(
  process.env.NEQ_N2_BROWSERS ?? DEFAULT_N2_BROWSER_SET,
);
const FIREFOX_REQUESTED = REQUESTED_BROWSERS.includes("firefox");
const HOST_ONLY_HTTP_PATHS = ["/toolkit", "/api/toolkit/packs", "/api/settings/browser"] as const;
const HOST_ONLY_SOCKET_EVENTS = ["request_plot_data", "request_storage_data", "request_module_list"] as const;
const PRIVILEGED_SOCKET_EMISSIONS = [
  "plot_data_response",
  "storage_data_response",
  "module_list_response",
  "debug_output",
] as const;
const PLAYER_BUNDLE_MARKERS = [
  "/toolkit",
  "/api/settings",
  "game_interface.html",
  "shutdown",
  "restart_server",
  "debug_config",
  "party_tracker.json",
  "update_character_info",
  "MULTIPLAYER_MODE",
  "config.py",
  "request_plot_data",
  "request_storage_data",
  "request_module_list",
  "module_list_response",
  "plot_data_response",
  "debug_output",
  "start_build",
  "toggle_model",
] as const;

let chromeBrowser: Browser | undefined;
let firefoxBrowser: Browser | undefined;
let playerContextOne!: BrowserContext;
let playerContextTwo: BrowserContext | undefined;
let hostContext!: BrowserContext;
let playerOne: Page;
let playerTwo: Page | undefined;
let hostPage: Page;
let activeScenarioId = "setup";

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  PLAYER_URL = requiredEnv("NEQ_N2_PLAYER_URL");
  HOST_URL = requiredEnv("NEQ_N2_HOST_URL");
  PARTY_SIZE = partySizeFromEnv();
  PLAYER_PASSWORD = requiredEnv("NEQ_N2_PLAYER_PASSWORD");
  RUN_ID = process.env.NEQ_N2_RUN_ID ?? RUN_ID;
  validateFixedEndpoints();
  requireProviderAttemptBudgetForGameplay({
    managed: process.env.NEQ_N2_MANAGE_SANDBOX_HOST === "1",
    ledgerPath: providerAttemptLedgerPath(
      join(REPOSITORY_ROOT, "tmp", "combat_capture"),
      RUN_ID,
    ),
    budget: PROVIDER_ATTEMPT_BUDGET,
    runId: RUN_ID,
  });
  evidenceDirectory();
  ensureEvidenceFolders();

  try {
    const launched = await launchN2Browsers({ chromium, firefox }, REQUESTED_BROWSERS);
    const chrome = launched.chromeBrowser;
    chromeBrowser = chrome;
    const firefoxInstance = launched.firefoxBrowser ?? undefined;
    firefoxBrowser = firefoxInstance;
    updateRunMetadata({
      browsers_run: REQUESTED_BROWSERS,
      browser_instances: createN2BrowserInstances(
        chrome.version(),
        firefoxInstance?.version() ?? null,
        REQUESTED_BROWSERS,
      ),
    });
    playerContextOne = await chrome.newContext();
    if (firefoxInstance) playerContextTwo = await firefoxInstance.newContext();
    hostContext = await chrome.newContext();
    playerOne = await playerContextOne.newPage();
    if (playerContextTwo) playerTwo = await playerContextTwo.newPage();
    hostPage = await hostContext.newPage();
    attachConsoleEvidence(playerOne, "player-a-chrome");
    if (playerTwo) attachConsoleEvidence(playerTwo, "player-b-firefox");
    attachConsoleEvidence(hostPage, "host-ui-chrome-context");

    await Promise.all([
      loginPlayer(playerOne),
      ...(playerTwo ? [loginPlayer(playerTwo)] : []),
      loadHostUi(hostPage),
    ]);

    const firstVersion = await readPlayerVersion(playerOne);
    if (playerTwo && firefoxInstance) {
      const secondVersion = await readPlayerVersion(playerTwo);
      expect(secondVersion).toEqual(firstVersion);
      expect(chrome).not.toBe(firefoxInstance);
      expect(playerContextOne).not.toBe(playerContextTwo);
    }
    expect(hostContext).not.toBe(playerContextOne);

    updateRunMetadata({
      client_build_id: firstVersion.clientBuildId,
      browsers_run: REQUESTED_BROWSERS,
      browser_instances: createN2BrowserInstances(
        chrome.version(),
        firefoxInstance?.version() ?? null,
        REQUESTED_BROWSERS,
      ),
      os: { platform: platform(), release: release(), arch: arch() },
      party_size: PARTY_SIZE,
      scenario_list: N2_SCENARIOS,
      provider_identity: "not-observed-by-browser-driver; operator review required if runtime invokes provider",
    });
  } catch (error) {
    await Promise.all([
      chromeBrowser?.close().catch(() => {}),
      firefoxBrowser?.close().catch(() => {}),
    ]);
    throw error;
  }
});

test.afterEach(async ({}, testInfo) => {
  const id = annotation(testInfo, "n2-scenario-id") ?? "setup";
  if (MANAGED_SANDBOX_HOST && MANAGED_LIFECYCLE_SCENARIOS.has(id)) return;
  activeScenarioId = id;
  const artifactPaths: string[] = [];
  const captureErrors: string[] = [];
  const entries = [
    ["player-a-chrome", playerOne],
    ...(playerTwo ? [["player-b-firefox", playerTwo] as const] : []),
    ["host-ui-chrome-context", hostPage],
  ];

  for (const [name, page] of entries) {
    if (page && !page.isClosed()) {
      const screenshotPath = join(evidenceDirectory(), "screenshots", `${id}-${name}.png`);
      try {
        await page.screenshot({ path: screenshotPath, fullPage: true, animations: "disabled" });
        artifactPaths.push(relativeEvidencePath(screenshotPath));
      } catch {
        captureErrors.push(`${name} screenshot was not captured`);
      }
    }
  }

  const blockedReason = annotation(testInfo, "n2-blocked");
  const expected = parseAnnotation(annotation(testInfo, "n2-expected")) ?? catalogDescription(id);
  const observed = parseAnnotation(annotation(testInfo, "n2-observed")) ?? {
    status: testInfo.status,
    note: "See the sanitized Playwright runner output for the observed assertion details.",
  };
  const recordedChecks = testInfo.annotations
    .filter((item) => item.type === "n2-check")
    .map((item) => parseAnnotation(item.description))
    .filter((item): item is { id: string; expected?: string; observed?: unknown; verdict: "PASS" | "FAIL" | "BLOCKED"; reason?: string } =>
      item !== undefined && item !== null && typeof item === "object" &&
      "id" in item && typeof item.id === "string" &&
      "verdict" in item && ["PASS", "FAIL", "BLOCKED"].includes(String(item.verdict)),
    );
  const checks = scenarioCheckDefinitions(id).map((definition) => {
    const recorded = recordedChecks.find((item) => item.id === definition.id);
    if (recorded) return { ...recorded, expected: definition.description };
    if (definition.requires_firefox && !FIREFOX_REQUESTED) {
      return {
        id: definition.id,
        expected: definition.description,
        observed: { reason: FIREFOX_UNAVAILABLE_REASON },
        verdict: "BLOCKED" as const,
        reason: FIREFOX_UNAVAILABLE_REASON,
      };
    }
    if (blockedReason) {
      return {
        id: definition.id,
        expected: definition.description,
        observed: { reason: blockedReason },
        verdict: "BLOCKED" as const,
        reason: blockedReason,
      };
    }
    return {
      id: definition.id,
      expected: definition.description,
      observed: { reason: "required-check-did-not-record-an-outcome" },
      verdict: "FAIL" as const,
      reason: "required-check-did-not-record-an-outcome",
    };
  });
  const verdict = checks.some((check) => check.verdict === "FAIL") || captureErrors.length > 0 || testInfo.status !== "passed"
    ? "FAIL"
    : blockedReason || checks.some((check) => check.verdict === "BLOCKED")
      ? "BLOCKED"
      : "PASS";

  writeScenarioEvidence({
    id,
    expected,
    observed: captureErrors.length > 0 ? { result: observed, evidence_errors: captureErrors } : observed,
    verdict,
    checks,
    artifacts: artifactPaths,
    recorded_at_utc: new Date().toISOString(),
  });
  if (captureErrors.length > 0) {
    throw new Error("N2 evidence capture failed; see this scenario's FAIL record.");
  }
});

test.afterAll(async () => {
  await Promise.all([
    playerContextOne?.close().catch(() => {}),
    playerContextTwo?.close().catch(() => {}),
    hostContext?.close().catch(() => {}),
    chromeBrowser?.close().catch(() => {}),
    firefoxBrowser?.close().catch(() => {}),
  ]);
});

test("party-coherence: 1-PC and 4-PC projections agree across isolated clients and host", async ({}, testInfo) => {
  activeScenarioId = "party-coherence";
  scenarioAnnotation(testInfo, activeScenarioId, {
    party_size: PARTY_SIZE,
    player_a_browser: "Chrome",
    player_b_browser: FIREFOX_REQUESTED ? "Firefox" : null,
    expected_distinct_browser_instances: FIREFOX_REQUESTED,
    host_ui_browser: "Chrome",
    expected_separate_host_context: true,
  });

  const first = await readPlayerSnapshot(playerOne);
  const second = playerTwo ? await readPlayerSnapshot(playerTwo) : undefined;
  const firstNames = first.projection.party.members.map((member) => member.name);
  expect(firstNames).toHaveLength(PARTY_SIZE);
  expect(first.projection.party.active_character).toBeTruthy();
  expect(new URL(hostPage.url()).origin).toBe(HOST_URL);
  await expect(hostPage.locator("#game-output")).toBeAttached();
  await expect(hostPage.locator("#user-input")).toBeAttached();
  const hostParty = await readHostPartyData();
  const hostComparison = compareHostAndPlayerParty(hostParty, first, PARTY_SIZE);
  expect(hostComparison.matches, `Host party response differs from player snapshot: ${JSON.stringify(hostComparison)}`).toBe(true);
  recordCheck(testInfo, "chrome-host-party-consistency", "PASS", {
    ...hostComparison,
    host_ui_context: "separate Chrome BrowserContext; request_party_data response verified",
  });

  if (playerTwo && second) {
    const secondNames = second.projection.party.members.map((member) => member.name);
    expect(secondNames).toEqual(firstNames);
    expect(second.projection.party.active_character).toBe(first.projection.party.active_character);
    recordCheck(testInfo, "firefox-cross-browser-party-consistency", "PASS", {
      party_names: secondNames,
      active_character: second.projection.party.active_character,
      independent_browser_instance: true,
    });
  } else {
    recordFirefoxBlocked(testInfo, "firefox-cross-browser-party-consistency");
  }

  scenarioObservation(testInfo, {
    party_names: firstNames,
    active_character: first.projection.party.active_character,
    independent_firefox_session: playerTwo !== undefined,
    host_ui_context: "loaded separately",
  });
});

test("repeated-request-id: identical command returns its original receipt once", async ({}, testInfo) => {
  activeScenarioId = "repeated-request-id";
  scenarioAnnotation(testInfo, activeScenarioId, {
    duplicate_receipts: "same request_id returns original accepted receipt",
    transcript_echo_count: 1,
  });

  const snapshot = await readPlayerSnapshot(playerOne);
  const marker = `N2_REPEATED_REQUEST_${RUN_ID}`;
  const requestId = `n2-${RUN_ID.replace(/[^A-Za-z0-9_-]/g, "-")}`.slice(0, 120);
  const command = {
    schema_version: 1,
    instance_id: snapshot.instance_id,
    session_epoch: snapshot.session_epoch,
    request_id: requestId,
    character_name: snapshot.projection.party.active_character,
    active_character_revision: snapshot.projection.party.active_character_revision,
    text: marker,
  };
  const version = await readPlayerVersion(playerOne);
  const messages = await exchangePlayerSocket(playerOne, version, {
    events: [
      { name: "player.input.submit", payload: command },
      { name: "player.input.submit", payload: command },
    ],
    expectedEventCounts: { "player.input.receipt": 2 },
    timeoutMs: 10_000,
  });
  const receipts = messages
    .filter((message) => message.event === "player.input.receipt")
    .map((message) => message.payload as { status?: string });
  expect(receipts).toHaveLength(2);
  expect(receipts.map((receipt) => receipt.status)).toEqual(["accepted", "accepted"]);
  await expect(playerOne.locator(".transcript-message").filter({ hasText: marker })).toHaveCount(1);
  recordCheck(testInfo, "chrome-request-id-dedup", "PASS", {
    receipt_statuses: receipts.map((receipt) => receipt.status),
    transcript_echo_count: 1,
  });
  if (playerTwo) {
    await expect(playerTwo.locator(".transcript-message").filter({ hasText: marker })).toHaveCount(1);
    recordCheck(testInfo, "firefox-transcript-receipt-convergence", "PASS", {
      transcript_echo_count: 1,
      same_request_id: true,
    });
  } else {
    recordFirefoxBlocked(testInfo, "firefox-transcript-receipt-convergence");
  }

  scenarioObservation(testInfo, {
    receipt_statuses: receipts.map((receipt) => receipt.status),
    transcript_echo_count: 1,
    pending_queue_item: true,
  });
});

test("host-transcript-ordering: host UI commit reaches both clients in sequence", async ({}, testInfo) => {
  activeScenarioId = "host-transcript-ordering";
  scenarioAnnotation(testInfo, activeScenarioId, {
    host_user_input_visible_in_chrome_player_transcript: true,
    firefox_player_transcript_requested: FIREFOX_REQUESTED,
    transcript_sequences_strictly_increasing: true,
    duplicate_message_count: 1,
    firefox_player_requested: FIREFOX_REQUESTED,
  });

  const before = await readPlayerSnapshot(playerOne);
  const beforeFirefox = playerTwo ? await readPlayerSnapshot(playerTwo) : null;
  const previousSequence = before.projection.transcript?.messages.at(-1)?.sequence ?? 0;
  const activeCharacter = before.projection.party.active_character;
  const marker = `N2_HOST_TRANSCRIPT_${RUN_ID}`;
  const hostEcho = await sendHostInput(marker, activeCharacter);
  expect(hostEcho).toBe(true);
  await expect(playerOne.locator(".transcript-message").filter({ hasText: marker })).toHaveCount(1);

  const first = await readPlayerSnapshot(playerOne);
  const second = playerTwo ? await readPlayerSnapshot(playerTwo) : undefined;
  const firstMessages = first.projection.transcript?.messages ?? [];
  expectTranscriptOrder(firstMessages);
  expect(firstMessages.filter((message) => message.text.includes(marker))).toHaveLength(1);
  const firstHostMessage = firstMessages.find((message) => message.text.includes(marker));
  expect(firstHostMessage?.sequence).toBeGreaterThan(previousSequence);
  recordCheck(testInfo, "chrome-player-transcript-order", "PASS", {
    host_message_count: 1,
    host_message_sequence: firstHostMessage?.sequence,
    previous_sequence: previousSequence,
  });

  if (playerTwo && second && beforeFirefox) {
    const secondMessages = second.projection.transcript?.messages ?? [];
    expectTranscriptOrder(secondMessages);
    expect(firstMessages.map((message) => message.id)).toEqual(secondMessages.map((message) => message.id));
    expect(secondMessages.filter((message) => message.text.includes(marker))).toHaveLength(1);
    const secondHostMessage = secondMessages.find((message) => message.text.includes(marker));
    expect(secondHostMessage?.sequence).toBe(firstHostMessage?.sequence);
    recordCheck(testInfo, "firefox-player-transcript-convergence", "PASS", {
      matching_transcript_ids: true,
      host_message_count: 1,
      host_message_sequence: secondHostMessage?.sequence,
    });
  } else {
    recordFirefoxBlocked(testInfo, "firefox-player-transcript-convergence");
  }

  scenarioObservation(testInfo, {
    host_echo_observed: true,
    player_transcript_message_count: firstMessages.length,
    sequences: firstMessages.map((message) => message.sequence),
    host_message_position: "after previous cursor; later assistant output may follow",
    firefox_player_checked: playerTwo !== undefined,
  });
});

test("active-pc-sync-switch-race: synchronized selection and revision race", async ({}, testInfo) => {
  activeScenarioId = "active-pc-sync-switch-race";
  scenarioAnnotation(testInfo, activeScenarioId, {
    party_size: PARTY_SIZE,
    expected_final_revision_delta_for_competing_four_pc_selections: PARTY_SIZE === 4 ? 1 : "not applicable",
    firefox_player_requested: FIREFOX_REQUESTED,
  });

  const initial = await readPlayerSnapshot(playerOne);
  const names = initial.projection.party.members.map((member) => member.name);
  await expect(playerOne.locator("#active-pc option")).toHaveCount(PARTY_SIZE);
  if (playerTwo) await expect(playerTwo.locator("#active-pc option")).toHaveCount(PARTY_SIZE);
  if (PARTY_SIZE === 1) {
    expect(names).toHaveLength(1);
    await expect(playerOne.locator("#active-pc")).toHaveValue(names[0]);
    if (playerTwo) {
      await expect(playerTwo.locator("#active-pc")).toHaveValue(names[0]);
      recordCheck(testInfo, "firefox-cross-browser-active-pc-and-race", "PASS", {
        single_pc_party: true,
        firefox_active_character: names[0],
      });
    } else {
      recordFirefoxBlocked(testInfo, "firefox-cross-browser-active-pc-and-race");
    }
    recordCheck(testInfo, "chrome-active-pc-selection", "PASS", {
      single_pc_party: true,
      selectable_options: names.length,
      active_character: names[0],
    });
    scenarioObservation(testInfo, {
      one_pc_switch_race: "not applicable; only the canonical single PC is selectable",
      active_character: names[0],
    });
    return;
  }

  const current = initial.projection.party.active_character;
  const sequentialTarget = names.find((name) => name !== current);
  expect(sequentialTarget).toBeTruthy();
  await playerOne.locator("#active-pc").selectOption(sequentialTarget as string);
  await expect(playerOne.locator("#active-pc")).toHaveValue(sequentialTarget as string);
  const synchronized = await readPlayerSnapshot(playerOne);
  expect(synchronized.projection.party.active_character).toBe(sequentialTarget);
  recordCheck(testInfo, "chrome-active-pc-selection", "PASS", {
    selected_character: sequentialTarget,
    active_character_revision: synchronized.projection.party.active_character_revision,
  });

  if (!playerTwo) {
    recordFirefoxBlocked(testInfo, "firefox-cross-browser-active-pc-and-race");
    scenarioObservation(testInfo, {
      sequential_sync: "Chrome Player A authoritative selection verified",
      cross_client_revision_race: "BLOCKED: firefox-unavailable-in-sandbox",
      active_character: synchronized.projection.party.active_character,
    });
    return;
  }
  await expect(playerTwo.locator("#active-pc")).toHaveValue(sequentialTarget as string);

  const raceTargets = synchronized.projection.party.members
    .map((member) => member.name)
    .filter((name) => name !== synchronized.projection.party.active_character)
    .slice(0, 2);
  expect(raceTargets).toHaveLength(2);
  const [one, two] = await Promise.all([
    readPlayerSnapshot(playerOne),
    readPlayerSnapshot(playerTwo),
  ]);
  expect(two.projection.party.active_character_revision).toBe(one.projection.party.active_character_revision);
  const sendAtEpochMs = Date.now() + 3000;
  const version = await readPlayerVersion(playerOne);
  const [raceOne, raceTwo] = await Promise.all([
    exchangePlayerSocket(playerOne, version, {
      events: [{
        name: "player.active_pc.select",
        payload: activePcEnvelope(one, raceTargets[0]),
      }],
      expectedEventCounts: { "player.snapshot": 1 },
      timeoutMs: 12_000,
      sendAtEpochMs,
    }),
    exchangePlayerSocket(playerTwo, version, {
      events: [{
        name: "player.active_pc.select",
        payload: activePcEnvelope(two, raceTargets[1]),
      }],
      expectedEventCounts: { "player.snapshot": 1 },
      timeoutMs: 12_000,
      sendAtEpochMs,
    }),
  ]);
  expect(raceOne.some((message) => message.event === "player.snapshot")).toBe(true);
  expect(raceTwo.some((message) => message.event === "player.snapshot")).toBe(true);

  const finalOne = await readPlayerSnapshot(playerOne);
  const finalTwo = await readPlayerSnapshot(playerTwo);
  await expect(playerOne.locator("#active-pc")).toHaveValue(finalOne.projection.party.active_character ?? "");
  await expect(playerTwo.locator("#active-pc")).toHaveValue(finalOne.projection.party.active_character ?? "");
  expect(finalTwo.projection.party.active_character).toBe(finalOne.projection.party.active_character);
  expect(finalOne.projection.party.active_character_revision).toBe(
    one.projection.party.active_character_revision + 1,
  );
  expect(raceTargets).toContain(finalOne.projection.party.active_character);

  scenarioObservation(testInfo, {
    sequential_sync: true,
    same_revision_race_targets: 2,
    final_active_pc: finalOne.projection.party.active_character,
    revision_delta: finalOne.projection.party.active_character_revision - one.projection.party.active_character_revision,
  });
  recordCheck(testInfo, "firefox-cross-browser-active-pc-and-race", "PASS", {
    firefox_selection_synchronized: true,
    final_active_pc: finalOne.projection.party.active_character,
    revision_delta: finalOne.projection.party.active_character_revision - one.projection.party.active_character_revision,
  });
});

test("sheets-initiative-combat-busy-state: safe projection matches the visible UI", async ({}, testInfo) => {
  activeScenarioId = "sheets-initiative-combat-busy-state";
  scenarioAnnotation(testInfo, activeScenarioId, {
    sheet: "active PC read-only sheet is visible",
    combat: "seeded initiative and combat projection is visible",
    busy_state: "visible UI label equals projected busy boolean",
  });

  const pages: Page[] = [playerOne, ...(playerTwo ? [playerTwo] : [])];
  for (const page of pages) {
    const snapshot = await readPlayerSnapshot(page);
    const activeName = snapshot.projection.party.active_character;
    expect(activeName).toBeTruthy();
    const sheet = page.locator('article[aria-label$=" read-only sheet"]');
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole("heading", { name: activeName as string })).toBeVisible();
    await expect(sheet.locator("dt", { hasText: "Hit points" })).toHaveCount(1);
    expect(snapshot.projection.combat?.available).toBe(true);
    expect(snapshot.projection.combat?.active).toBe(true);
    expect(snapshot.projection.combat?.turn_order.length).toBeGreaterThanOrEqual(PARTY_SIZE);
    await expect(page.getByRole("heading", { name: "Initiative and combat" })).toBeVisible();
    await expect(page.getByRole("list", { name: "Initiative order" })).toBeVisible();

    expect(typeof snapshot.projection.busy).toBe("boolean");
    if (snapshot.projection.busy) {
      await expect(page.getByText("The game is busy. Please wait before submitting input.", { exact: true })).toBeVisible();
    } else {
      await expect(page.getByText("The game is ready for input.", { exact: true })).toBeVisible();
    }
  }

  const snapshot = await readPlayerSnapshot(playerOne);
  recordCheck(testInfo, "chrome-sheet-combat-busy-projection", "PASS", {
    active_pc: snapshot.projection.party.active_character,
    party_size: snapshot.projection.party.members.length,
    combatants: snapshot.projection.combat?.turn_order.map((combatant) => combatant.name),
    busy: snapshot.projection.busy,
  });
  if (playerTwo) {
    const firefoxSnapshot = await readPlayerSnapshot(playerTwo);
    recordCheck(testInfo, "firefox-sheet-combat-busy-projection", "PASS", {
      active_pc: firefoxSnapshot.projection.party.active_character,
      party_size: firefoxSnapshot.projection.party.members.length,
      combatants: firefoxSnapshot.projection.combat?.turn_order.map((combatant) => combatant.name),
      busy: firefoxSnapshot.projection.busy,
    });
  } else {
    recordFirefoxBlocked(testInfo, "firefox-sheet-combat-busy-projection");
  }
  scenarioObservation(testInfo, {
    active_pc: snapshot.projection.party.active_character,
    party_size: snapshot.projection.party.members.length,
    combatants: snapshot.projection.combat?.turn_order.map((combatant) => combatant.name),
    busy: snapshot.projection.busy,
  });
});

test("busy-input: concurrent player inputs surface a busy receipt without appending it", async ({}, testInfo) => {
  activeScenarioId = "busy-input";
  scenarioAnnotation(testInfo, activeScenarioId, {
    expected_receipts: "one accepted and one busy response from available concurrent player requests",
    expected_busy_transcript_append_count: 0,
    queue_capacity: 1,
    independent_firefox_player_requested: FIREFOX_REQUESTED,
  });

  const markers = [
    `N2_BUSY_INPUT_ONE_${RUN_ID}`,
    `N2_BUSY_INPUT_TWO_${RUN_ID}`,
  ] as const;
  const busyNotice = /This input was not queued/;
  let busyCount = 0;
  let rejectedMarker = markers[1];
  if (playerTwo) {
    const pages = [playerOne, playerTwo] as const;
    for (const page of pages) {
      await expect(page.getByText("The game is ready for input.", { exact: true })).toBeVisible();
    }
    await Promise.all(pages.map((page, index) => page.locator("#gameplay-input").fill(markers[index])));
    await Promise.all(pages.map((page) => page.getByRole("button", { name: "Submit input" }).click()));

    await expect(playerOne.getByText(busyNotice).or(playerTwo.getByText(busyNotice))).toBeVisible();
    const busyPages = await Promise.all(pages.map((page) => page.getByText(busyNotice).isVisible()));
    busyCount = busyPages.filter(Boolean).length;
    rejectedMarker = markers[busyPages[0] ? 0 : 1];
    const snapshots = await Promise.all(pages.map((page) => readPlayerSnapshot(page)));
    expect(snapshots.every((snapshot) =>
      !snapshot.projection.transcript?.messages.some((message) => message.text.includes(rejectedMarker)),
    )).toBe(true);
    recordCheck(testInfo, "firefox-independent-player-concurrency", "PASS", {
      chrome_and_firefox_sessions_submitted: true,
      busy_receipt_visible: true,
      rejected_transcript_append_count: 0,
    });
  } else {
    let injectedAdmissionRequest = false;
    const fillerMarker = `N2_BUSY_INPUT_ACCEPTED_${RUN_ID}`;
    await playerContextOne.routeWebSocket("**/socket.io/**", (route) => {
      const server = route.connectToServer();
      route.onMessage((message) => {
        if (injectedAdmissionRequest || typeof message !== "string" || !message.startsWith("42/player,")) {
          server.send(message);
          return;
        }
        let packet: unknown;
        try {
          packet = JSON.parse(message.slice("42/player,".length));
        } catch {
          server.send(message);
          return;
        }
        if (!Array.isArray(packet) || packet[0] !== "player.input.submit" ||
            packet[1] === null || typeof packet[1] !== "object") {
          server.send(message);
          return;
        }
        const original = packet[1] as Record<string, unknown>;
        if (typeof original.request_id !== "string" || typeof original.text !== "string") {
          server.send(message);
          return;
        }
        injectedAdmissionRequest = true;
        const filler = {
          ...original,
          request_id: `n2-${RUN_ID}-busy-filler`.slice(0, 120),
          text: fillerMarker,
        };
        server.send(`42/player,${JSON.stringify(["player.input.submit", filler])}`);
        server.send(message);
      });
      server.onMessage((message) => route.send(message));
    });
    await playerOne.reload({ waitUntil: "domcontentloaded" });
    await expect(playerOne.getByRole("heading", { name: "NeverEndingQuest player" })).toBeVisible();
    await expect(playerOne.getByText("Connected", { exact: true })).toBeVisible();
    await playerOne.locator("#gameplay-input").fill(markers[0]);
    await playerOne.getByRole("button", { name: "Submit input" }).click();
    await expect(playerOne.getByText(busyNotice)).toBeVisible({ timeout: 10_000 });
    expect(injectedAdmissionRequest).toBe(true);
    await expect(playerOne.locator(".transcript-message").filter({ hasText: markers[0] })).toHaveCount(0);
    busyCount = 1;
    rejectedMarker = markers[0];
    const acceptedInTranscript = await playerOne.locator(".transcript-message").filter({ hasText: fillerMarker }).count();
    recordFirefoxBlocked(testInfo, "firefox-independent-player-concurrency");
    scenarioObservation(testInfo, {
      visible_busy_receipt: true,
      accepted_filler_transcript_count: acceptedInTranscript,
      rejected_transcript_append_count: 0,
      submissions_from_independent_clients: 1,
      concurrent_requests_from_chrome_session: true,
      rejected_marker: rejectedMarker,
    });
    recordCheck(testInfo, "chrome-player-admission-and-busy-receipt", "PASS", {
      busy_receipt_visible_in_chrome_ui: true,
      rejected_transcript_append_count: 0,
      single_chrome_player_session: true,
    });
    return;
  }

  scenarioObservation(testInfo, {
    visible_busy_receipts: busyCount,
    rejected_input_transcript_append_count: 0,
    submissions_from_independent_clients: playerTwo ? 2 : 1,
    concurrent_requests_from_chrome_session: !playerTwo,
    rejected_marker: rejectedMarker,
  });
  recordCheck(testInfo, "chrome-player-admission-and-busy-receipt", "PASS", {
    busy_receipts: busyCount,
    rejected_transcript_append_count: 0,
    single_chrome_player_session: !playerTwo,
  });
});

test("refresh-reconnect: refresh and network reconnect never replay a draft", async ({}, testInfo) => {
  activeScenarioId = "refresh-reconnect";
  scenarioAnnotation(testInfo, activeScenarioId, {
    refreshed_snapshot_is_authoritative: true,
    offline_online_reconnect_resynchronizes: true,
    unsent_draft_replay_count: 0,
  });

  const marker = `N2_UNSENT_DRAFT_${RUN_ID}`;
  await playerOne.locator("#gameplay-input").fill(marker);
  await playerOne.reload({ waitUntil: "domcontentloaded" });
  await expect(playerOne.getByRole("heading", { name: "NeverEndingQuest player" })).toBeVisible();
  await expect(playerOne.getByText("Connected", { exact: true })).toBeVisible();
  await expect(playerOne.locator("#gameplay-input")).toHaveValue("");
  expect((await readPlayerSnapshot(playerOne)).projection.transcript?.messages.some(
    (message) => message.text.includes(marker),
  )).toBe(false);

  await playerContextOne.setOffline(true);
  await expect(playerOne.getByText("Disconnected", { exact: true })).toBeVisible({ timeout: 15_000 });
  await playerContextOne.setOffline(false);
  await expect(playerOne.getByText("Connected", { exact: true })).toBeVisible({ timeout: 20_000 });
  const refreshed = await readPlayerSnapshot(playerOne);
  expect(refreshed.projection.party.members).toHaveLength(PARTY_SIZE);
  expect(refreshed.projection.party.active_character).toBeTruthy();
  recordCheck(testInfo, "chrome-refresh-reconnect-no-replay", "PASS", {
    refresh_party_size: refreshed.projection.party.members.length,
    reconnect_status: "Connected",
    unsent_draft_replayed: false,
  });

  if (playerTwo) {
    const firefoxMarker = `${marker}_FIREFOX`;
    await playerTwo.locator("#gameplay-input").fill(firefoxMarker);
    await playerTwo.reload({ waitUntil: "domcontentloaded" });
    await expect(playerTwo.getByRole("heading", { name: "NeverEndingQuest player" })).toBeVisible();
    await expect(playerTwo.getByText("Connected", { exact: true })).toBeVisible();
    await expect(playerTwo.locator("#gameplay-input")).toHaveValue("");
    expect((await readPlayerSnapshot(playerTwo)).projection.transcript?.messages.some(
      (message) => message.text.includes(firefoxMarker),
    )).toBe(false);
    await playerContextTwo?.setOffline(true);
    await expect(playerTwo.getByText("Disconnected", { exact: true })).toBeVisible({ timeout: 15_000 });
    await playerContextTwo?.setOffline(false);
    await expect(playerTwo.getByText("Connected", { exact: true })).toBeVisible({ timeout: 20_000 });
    const firefoxRefreshed = await readPlayerSnapshot(playerTwo);
    expect(firefoxRefreshed.projection.party.members).toHaveLength(PARTY_SIZE);
    recordCheck(testInfo, "firefox-refresh-reconnect-no-replay", "PASS", {
      refresh_party_size: firefoxRefreshed.projection.party.members.length,
      reconnect_status: "Connected",
      unsent_draft_replayed: false,
    });
  } else {
    recordFirefoxBlocked(testInfo, "firefox-refresh-reconnect-no-replay");
  }

  scenarioObservation(testInfo, {
    refresh_snapshot_party_size: refreshed.projection.party.members.length,
    reconnect_status: "Connected",
    unsent_draft_replayed: false,
    firefox_player_checked: playerTwo !== undefined,
  });
});

test("server-instance-change: owned sandbox restart leaves pending input uncertain and resynchronizes", async ({}, testInfo) => {
  activeScenarioId = "server-instance-change";
  scenarioAnnotation(testInfo, activeScenarioId, catalogDescription(activeScenarioId));
  if (!MANAGED_SANDBOX_HOST) {
    scenarioBlocked(
      testInfo,
      "BLOCKED: the host process is externally owned. Re-run with --manage-sandbox-host to exercise the verified sandbox restart.",
    );
  }
});

test("missing-bundle: owned sandbox host UI stays usable while player startup fails closed", async ({}, testInfo) => {
  activeScenarioId = "missing-bundle";
  scenarioAnnotation(testInfo, activeScenarioId, catalogDescription(activeScenarioId));
  if (!MANAGED_SANDBOX_HOST) {
    scenarioBlocked(
      testInfo,
      "BLOCKED: removing the bundle is permitted only for the driver-owned sandbox; re-run with --manage-sandbox-host.",
    );
  }
});

test("broken-bundle: digest mismatch keeps host UI usable and player startup closed", async ({}, testInfo) => {
  activeScenarioId = "broken-bundle";
  scenarioAnnotation(testInfo, activeScenarioId, catalogDescription(activeScenarioId));
  if (!MANAGED_SANDBOX_HOST) {
    scenarioBlocked(
      testInfo,
      "BLOCKED: corrupting an asset is permitted only for the driver-owned sandbox; re-run with --manage-sandbox-host.",
    );
  }
});

test("host-only-route-event-and-bundle-probes: player origin refuses host surfaces", async ({}, testInfo) => {
  activeScenarioId = "host-only-route-event-and-bundle-probes";
  scenarioAnnotation(testInfo, activeScenarioId, {
    routes: HOST_ONLY_HTTP_PATHS.map((path) => ({ path, status: 404 })),
    socket_events: HOST_ONLY_SOCKET_EVENTS,
    privileged_payloads: 0,
    loaded_player_js_host_markers: 0,
    firefox_player_requested: FIREFOX_REQUESTED,
  });

  const chromeProbe = await runHostOnlyProbes(playerOne);
  recordCheck(testInfo, "chrome-player-origin-host-surface-isolation", "PASS", chromeProbe);
  let firefoxProbe = null;
  if (playerTwo) {
    firefoxProbe = await runHostOnlyProbes(playerTwo);
    recordCheck(testInfo, "firefox-player-origin-host-surface-isolation", "PASS", firefoxProbe);
  } else {
    recordFirefoxBlocked(testInfo, "firefox-player-origin-host-surface-isolation");
  }

  scenarioObservation(testInfo, {
    chrome_route_statuses: chromeProbe.route_statuses,
    refused_host_socket_events: HOST_ONLY_SOCKET_EVENTS,
    chrome_privileged_socket_payloads: chromeProbe.privileged_socket_payloads,
    chrome_loaded_js_count: chromeProbe.loaded_js_count,
    chrome_host_marker_hits: chromeProbe.host_marker_hits,
    firefox_checked: firefoxProbe !== null,
  });
});

async function loginPlayer(page: Page): Promise<void> {
  await page.goto(PLAYER_URL, { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Player login" })).toBeVisible();
  await page.getByLabel("Password").fill(PLAYER_PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "NeverEndingQuest player" })).toBeVisible();
  await expect(page.getByText("Connected", { exact: true })).toBeVisible();
}

async function loadHostUi(page: Page): Promise<void> {
  await page.goto(HOST_URL, { waitUntil: "domcontentloaded" });
  await expect(page.locator("#game-output")).toBeAttached();
  await expect(page.locator("#user-input")).toBeAttached();
}

function attachConsoleEvidence(page: Page, contextName: string): void {
  page.on("console", (message) => {
    writeConsoleEvidence(activeScenarioId, contextName, message.type(), message.text());
  });
  page.on("pageerror", (error) => {
    writeConsoleEvidence(activeScenarioId, contextName, "pageerror", error.message);
  });
}

async function readPlayerVersion(page: Page): Promise<PlayerVersion> {
  return page.evaluate(() => {
    const buildMeta = document.querySelector<HTMLMetaElement>('meta[name="neq-client-build"]');
    const protocolMeta = document.querySelector<HTMLMetaElement>('meta[name="neq-protocol-version"]');
    if (!buildMeta?.content || !protocolMeta?.content) {
      throw new Error("Player shell is missing manifest build/protocol metadata.");
    }
    const protocolVersion = Number(protocolMeta.content);
    if (!Number.isInteger(protocolVersion)) throw new Error("Player protocol metadata is invalid.");
    return { clientBuildId: buildMeta.content, protocolVersion };
  });
}

async function readPlayerSnapshot(page: Page): Promise<PlayerSnapshot> {
  return page.evaluate(async () => {
    const version = await (async () => {
      const buildMeta = document.querySelector<HTMLMetaElement>('meta[name="neq-client-build"]');
      const protocolMeta = document.querySelector<HTMLMetaElement>('meta[name="neq-protocol-version"]');
      if (!buildMeta?.content || !protocolMeta?.content) throw new Error("Player version metadata is missing.");
      return { build: buildMeta.content, protocol: protocolMeta.content };
    })();
    const response = await fetch("/api/player/snapshot", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "X-NEQ-Client-Build": version.build,
        "X-NEQ-Protocol-Version": version.protocol,
      },
    });
    if (!response.ok) throw new Error(`Player snapshot request failed with HTTP ${response.status}.`);
    return await response.json() as PlayerSnapshot;
  });
}

function expectTranscriptOrder(messages: readonly TranscriptMessage[]): void {
  for (let index = 1; index < messages.length; index += 1) {
    expect(messages[index].sequence).toBeGreaterThan(messages[index - 1].sequence);
  }
}

async function sendHostInput(text: string, character: string | null): Promise<boolean> {
  return hostPage.evaluate(async ({ inputText, activeCharacter }) => {
    type HostSocket = {
      connected: boolean;
      on: (event: string, callback: (payload?: unknown) => void) => void;
      off: (event: string, callback: (payload?: unknown) => void) => void;
      emit: (event: string, payload: unknown) => void;
    };
    const socket = (window as Window & { socket?: HostSocket }).socket;
    if (!socket) throw new Error("Host UI Socket.IO client is unavailable.");
    if (!socket.connected) {
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => reject(new Error("Host UI socket did not connect.")), 10_000);
        const onConnect = (): void => {
          window.clearTimeout(timer);
          socket.off("connect", onConnect);
          resolve();
        };
        socket.on("connect", onConnect);
      });
    }
    return await new Promise<boolean>((resolve, reject) => {
      const timer = window.setTimeout(() => {
        socket.off("game_output", onOutput);
        reject(new Error("Host UI did not echo its transcript probe."));
      }, 10_000);
      const onOutput = (payload?: unknown): void => {
        if (
          payload !== null &&
          typeof payload === "object" &&
          "content" in payload &&
          payload.content === inputText
        ) {
          window.clearTimeout(timer);
          socket.off("game_output", onOutput);
          resolve(true);
        }
      };
      socket.on("game_output", onOutput);
      socket.emit("user_input", { input: inputText, character: activeCharacter });
    });
  }, { inputText: text, activeCharacter: character });
}

async function readHostPartyData(): Promise<{
  party_members: readonly string[];
  active_character: string;
}> {
  return hostPage.evaluate(async () => {
    type HostPartyData = { party_members?: unknown; active_character?: unknown };
    type HostSocket = {
      connected: boolean;
      on: (event: string, callback: (payload?: unknown) => void) => void;
      off: (event: string, callback: (payload?: unknown) => void) => void;
      emit: (event: string) => void;
    };
    const socket = (window as Window & { socket?: HostSocket }).socket;
    if (!socket) throw new Error("Host UI Socket.IO client is unavailable.");
    if (!socket.connected) {
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(() => {
          socket.off("connect", onConnect);
          reject(new Error("Host UI socket did not connect before party-data probe."));
        }, 10_000);
        const onConnect = (): void => {
          window.clearTimeout(timer);
          socket.off("connect", onConnect);
          resolve();
        };
        socket.on("connect", onConnect);
      });
    }

    return await new Promise<{ party_members: string[]; active_character: string }>((resolve, reject) => {
      const finish = (callback: () => void): void => {
        window.clearTimeout(timer);
        socket.off("party_data_response", onResponse);
        callback();
      };
      const onResponse = (payload?: unknown): void => {
        if (payload === null || typeof payload !== "object") {
          finish(() => reject(new Error("Host party-data response is not an object.")));
          return;
        }
        const response = payload as HostPartyData;
        if (!Array.isArray(response.party_members) ||
            !response.party_members.every((name) => typeof name === "string") ||
            typeof response.active_character !== "string" || response.active_character.length === 0) {
          finish(() => reject(new Error("Host party-data response is missing party members or active PC.")));
          return;
        }
        finish(() => resolve({
          party_members: response.party_members as string[],
          active_character: response.active_character as string,
        }));
      };
      const timer = window.setTimeout(() => {
        finish(() => reject(new Error("Host UI did not return party_data_response within 10 seconds.")));
      }, 10_000);
      socket.on("party_data_response", onResponse);
      socket.emit("request_party_data");
    });
  });
}

function activePcEnvelope(snapshot: PlayerSnapshot, characterName: string) {
  return {
    schema_version: 1,
    instance_id: snapshot.instance_id,
    session_epoch: snapshot.session_epoch,
    character_name: characterName,
    expected_revision: snapshot.projection.party.active_character_revision,
  };
}

async function exchangePlayerSocket(
  page: Page,
  version: PlayerVersion,
  request: BrowserSocketRequest,
): Promise<readonly SocketPacket[]> {
  return page.evaluate(async (input) => {
    const url = new URL("/socket.io/?EIO=4&transport=websocket", window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(url.toString());
    const received: SocketPacket[] = [];
    const counts: Record<string, number> = {};

    return await new Promise<readonly SocketPacket[]>((resolve, reject) => {
      let settled = false;
      let namespaceRequested = false;
      let eventsSent = false;
      const finish = (error?: Error): void => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timeout);
        try {
          socket.close();
        } catch {
          // The connection may already have closed after the assertion window.
        }
        if (error) reject(error);
        else resolve(received);
      };
      const timeout = window.setTimeout(() => finish(), input.timeoutMs);
      const sendEvents = (): void => {
        if (eventsSent) return;
        eventsSent = true;
        for (const event of input.events) {
          socket.send(`42/player,${JSON.stringify([event.name, event.payload])}`);
        }
      };

      socket.onerror = () => finish(new Error("Browser Socket.IO probe failed to connect."));
      socket.onclose = () => {
        if (!settled) finish(new Error("Browser Socket.IO probe closed before its assertion window."));
      };
      socket.onmessage = (message): void => {
        const packet = String(message.data);
        if (packet === "2") {
          socket.send("3");
          return;
        }
        if (packet.startsWith("0")) {
          if (!namespaceRequested) {
            namespaceRequested = true;
            socket.send(`40/player,${JSON.stringify({
              client_build_id: input.clientBuildId,
              protocol_version: input.protocolVersion,
            })}`);
          }
          return;
        }
        if (packet.startsWith("44/player,")) {
          finish(new Error("Player namespace refused the authenticated browser probe."));
          return;
        }
        if (packet.startsWith("40/player,")) {
          if (input.sendAtEpochMs === undefined) sendEvents();
          else window.setTimeout(sendEvents, Math.max(0, input.sendAtEpochMs - Date.now()));
          return;
        }
        if (!packet.startsWith("42/player,")) return;
        try {
          const decoded = JSON.parse(packet.slice("42/player,".length)) as unknown[];
          if (typeof decoded[0] !== "string") return;
          const event = decoded[0];
          received.push({ event, payload: decoded[1] });
          counts[event] = (counts[event] ?? 0) + 1;
          const complete = Object.entries(input.expectedEventCounts).every(
            ([name, count]) => (counts[name] ?? 0) >= count,
          );
          if (Object.keys(input.expectedEventCounts).length > 0 && complete) finish();
        } catch {
          finish(new Error("Player Socket.IO probe received a malformed event packet."));
        }
      };
    });
  }, {
    ...request,
    clientBuildId: version.clientBuildId,
    protocolVersion: version.protocolVersion,
  });
}

async function scanLoadedPlayerJavaScript(page: Page): Promise<{ scriptCount: number; hits: readonly string[] }> {
  return page.evaluate(async (markers) => {
    const scriptUrls = [...document.scripts]
      .map((script) => script.src)
      .filter((source) => source.length > 0)
      .filter((source) => new URL(source, location.href).origin === location.origin)
      .filter((source) => new URL(source, location.href).pathname.endsWith(".js"));
    const loaded = await Promise.all(scriptUrls.map(async (source) => {
      const response = await fetch(source, { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`Player JavaScript asset returned HTTP ${response.status}.`);
      return { source, text: await response.text() };
    }));
    const hits = loaded.flatMap(({ source, text }) =>
      markers.filter((marker) => text.includes(marker)).map((marker) => `${new URL(source).pathname}:${marker}`),
    );
    return { scriptCount: loaded.length, hits };
  }, [...PLAYER_BUNDLE_MARKERS]);
}

async function runHostOnlyProbes(page: Page): Promise<{
  route_statuses: number[];
  privileged_socket_payloads: number;
  loaded_js_count: number;
  host_marker_hits: readonly string[];
}> {
  const routeResults = await page.evaluate(async (paths) => {
    const privilegedMarkers = ["plot_data_response", "storage_data_response", "module_list_response", "debug_output"];
    return Promise.all(paths.map(async (path) => {
      const response = await fetch(path, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "manual",
      });
      const body = await response.text();
      return {
        path,
        status: response.status,
        privileged_payload: privilegedMarkers.some((marker) => body.includes(marker)),
      };
    }));
  }, [...HOST_ONLY_HTTP_PATHS]);
  for (const route of routeResults) {
    expect(route.status).toBe(404);
    expect(route.privileged_payload).toBe(false);
  }

  const snapshot = await readPlayerSnapshot(page);
  const version = await readPlayerVersion(page);
  const socketMessages = await exchangePlayerSocket(page, version, {
    events: HOST_ONLY_SOCKET_EVENTS.map((name) => ({
      name,
      payload: { probe: "N2_HOST_ONLY_PROBE", include_debug: true },
    })),
    expectedEventCounts: {},
    timeoutMs: 1200,
  });
  const privilegedMessages = socketMessages.filter((message) =>
    PRIVILEGED_SOCKET_EMISSIONS.includes(message.event as (typeof PRIVILEGED_SOCKET_EMISSIONS)[number]),
  );
  expect(privilegedMessages).toHaveLength(0);

  const bundleScan = await scanLoadedPlayerJavaScript(page);
  expect(bundleScan.scriptCount).toBeGreaterThan(0);
  expect(bundleScan.hits).toEqual([]);
  expect(snapshot.projection.party.members).toHaveLength(PARTY_SIZE);
  return {
    route_statuses: routeResults.map((route) => route.status),
    privileged_socket_payloads: privilegedMessages.length,
    loaded_js_count: bundleScan.scriptCount,
    host_marker_hits: bundleScan.hits,
  };
}

function recordCheck(
  testInfo: TestInfo,
  id: string,
  verdict: "PASS" | "FAIL" | "BLOCKED",
  observed: unknown,
  reason?: string,
): void {
  const expected = scenarioCheckDefinitions(activeScenarioId).find((check) => check.id === id)?.description ?? id;
  scenarioCheck(testInfo, {
    id,
    expected,
    observed,
    verdict,
    ...(reason === undefined ? {} : { reason }),
  });
}

function recordFirefoxBlocked(testInfo: TestInfo, id: string): void {
  recordCheck(
    testInfo,
    id,
    "BLOCKED",
    { reason: FIREFOX_UNAVAILABLE_REASON },
    FIREFOX_UNAVAILABLE_REASON,
  );
}

function partySizeFromEnv(): number {
  const value = requiredEnv("NEQ_N2_PARTY_SIZE");
  if (value !== "1" && value !== "4") throw new Error("NEQ_N2_PARTY_SIZE must be 1 or 4.");
  return Number(value);
}

function requiredEnv(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must be set in the environment.`);
  return value;
}

function validateFixedEndpoints(): void {
  if (HOST_URL !== "http://127.0.0.1:8360" || PLAYER_URL !== "http://127.0.0.1:8370") {
    throw new Error("N2 browser suite accepts only host 127.0.0.1:8360 and player 127.0.0.1:8370.");
  }
  if (HOST_URL.includes(":8357") || PLAYER_URL.includes(":8357")) {
    throw new Error("The installed campaign port 8357 is forbidden.");
  }
}

function parseAnnotation(value: string | undefined): unknown {
  if (value === undefined) return undefined;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}
