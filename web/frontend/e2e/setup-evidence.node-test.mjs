// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { JSDOM } from "jsdom";
import {
  captureCredentialSafeScreenshot,
  captureSetupFailureBeforeClose,
  createSetupFailureRecord,
  normalizeSetupFailureRecord,
  readSetupFailureEvidence,
  sanitizeSetupScreenshotPage,
  settleSetupOperations,
  setupFailureStage,
  withSetupStage,
} from "./setup-evidence.mjs";

const PROJECT_ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const TEST_ROOT = join(PROJECT_ROOT, "tmp", "n2", "setup-evidence");

function evaluateSerializedSanitizer(callback, role, documentRef) {
  return runInNewContext(`(${callback.toString()})(role)`, {
    role,
    document: documentRef,
  });
}

test("setup stage errors retain only a fixed stage and discard exception text", async () => {
  const original = new Error("password=setup-secret; Cookie: setup-cookie");
  await assert.rejects(
    withSetupStage("player_authentication", async () => { throw original; }),
    (error) => {
      assert.equal(error.message, "N2 setup phase failed.");
      assert.equal(setupFailureStage(error), "player_authentication");
      assert.equal(JSON.stringify(error).includes("setup-secret"), false);
      return true;
    },
  );
  assert.equal(setupFailureStage(original, "host_ui_load"), "host_ui_load");
  assert.equal(setupFailureStage(original, "not-a-stage"), "unknown");
});

test("setup failure waits for sibling operations to settle before evidence capture can begin", async () => {
  let siblingSettled = false;
  const rejection = new Error("password=sibling-secret");
  await assert.rejects(settleSetupOperations([
    Promise.reject(rejection),
    (async () => {
      await Promise.resolve();
      siblingSettled = true;
    })(),
  ]), (error) => error === rejection);
  assert.equal(siblingSettled, true);
});

test("setup failure capture flushes diagnostics, screenshots, persists, then closes pages", async () => {
  const order = [];
  const secret = "never-write-this-secret";
  const result = await captureSetupFailureBeforeClose({
    stage: "player_connection_wait",
    observed: {
      player_connection_state: "connected",
      player_b_connection_state: "unknown",
      player_shell_loaded: true,
      host_ui_loaded: false,
      client_build_id: "build-123",
      protocol_version: 1,
      exception: secret,
      cookie: secret,
    },
    pages: [
      { role: "player-a-chrome", page: {} },
      { role: "player-b-firefox", page: undefined },
    ],
    flushRequestDiagnostics: async () => {
      order.push("flush");
      return {
        artifact: "request-diagnostics.jsonl",
        records_written: 1,
        records_omitted: 2,
        record_write_failures: 0,
        truncated: true,
      };
    },
    captureScreenshot: async (_page, role) => {
      order.push(`screenshot:${role}`);
      if (role === "player-b-firefox") return { status: "skipped", reason: "page-unavailable" };
      return { status: "captured", path: "screenshots/setup-player-a-chrome.png" };
    },
    writeRecord: async (record) => {
      order.push("write");
      assert.equal(record.stage, "player_connection_wait");
      assert.equal(record.observed.client_build_id, "build-123");
      assert.equal(record.observed.protocol_version, 1);
      assert.equal(record.observed.player_connection_state, "connected");
      assert.equal(record.observed.cookie, undefined);
      assert.equal(record.observed.exception, undefined);
      assert.equal(JSON.stringify(record).includes(secret), false);
    },
    closePages: async () => { order.push("close"); },
    recordedAt: "2026-11-09T12:00:00.000Z",
  });

  assert.deepEqual(order, [
    "flush",
    "screenshot:player-a-chrome",
    "screenshot:player-b-firefox",
    "write",
    "close",
  ]);
  assert.equal(result.record_write_status, "written");
  assert.equal(result.page_close_status, "closed");
  assert.equal(result.record.gameplay_scenarios.status, "BLOCKED");
  assert.equal(result.record.gameplay_scenarios.executed, false);
  assert.equal(result.record.observed.protocol_version, 1);
  assert.equal(result.record.screenshots[1].reason, "page-unavailable");
  assert.deepEqual(result.record.request_diagnostics, {
    artifact: "request-diagnostics.jsonl",
    records_written: 1,
    records_omitted: 2,
    record_write_failures: 0,
    truncated: true,
  });
});

test("setup capture still closes pages if screenshot or evidence writing fails", async () => {
  const order = [];
  const result = await captureSetupFailureBeforeClose({
    stage: "unknown",
    observed: {},
    pages: [{ role: "setup", page: {} }],
    captureScreenshot: async () => { throw new Error("screenshot secret"); },
    writeRecord: async () => { throw new Error("disk secret"); },
    closePages: async () => { order.push("closed"); },
  });
  assert.equal(result.record_write_status, "failed");
  assert.equal(result.record.screenshots[0].reason, "screenshot-failed");
  assert.deepEqual(order, ["closed"]);
});

test("screenshot sanitization masks form content and refuses login or unknown pages", () => {
  const authenticated = new JSDOM(`<!doctype html><main>
    <h1>NeverEndingQuest player</h1>
    <button type="button">Log out</button>
    <p role="status">Connected</p>
    <input type="hidden" name="csrf_token" value="csrf-secret">
    <input name="player-note" value="draft-secret">
    <textarea>typed-secret</textarea>
    <select name="active-character"><option selected>private-character</option></select>
    <div contenteditable="true">editable-secret</div>
    <button aria-label="Show session token">session-token-secret</button>
    <span data-testid="csrf-token-value">csrf-ui-secret</span>
  </main>`);
  const safe = sanitizeSetupScreenshotPage("player-a-chrome", authenticated.window.document);
  assert.deepEqual(safe, { safe: true, reason: null });
  for (const field of authenticated.window.document.querySelectorAll("input, textarea")) {
    assert.equal(field.value, "");
    assert.equal(field.getAttribute("value"), "");
    assert.equal(field.style.getPropertyValue("-webkit-text-fill-color"), "transparent");
  }
  assert.equal(authenticated.window.document.querySelector("[contenteditable]")?.textContent, "");
  assert.equal(authenticated.window.document.querySelector("select")?.selectedIndex, -1);
  assert.equal(authenticated.window.document.querySelector("button[aria-label]")?.textContent, "[REDACTED]");
  assert.equal(authenticated.window.document.querySelector("[data-testid='csrf-token-value']")?.textContent, "[REDACTED]");

  const login = new JSDOM(`<!doctype html><main><h1>Player login</h1><input type="password" value="password-secret"></main>`);
  const unsafe = sanitizeSetupScreenshotPage("player-a-chrome", login.window.document);
  assert.equal(unsafe.safe, false);
  assert.equal(unsafe.reason, "login-or-authentication-not-confirmed");
  assert.equal(sanitizeSetupScreenshotPage("unapproved-role", login.window.document).safe, false);

  const disconnected = new JSDOM(`<!doctype html><h1>NeverEndingQuest player</h1><p role="status">Disconnected</p>`);
  assert.deepEqual(sanitizeSetupScreenshotPage("player-a-chrome", disconnected.window.document), {
    safe: false,
    reason: "login-or-authentication-not-confirmed",
  });
  const unknownStatus = new JSDOM(`<!doctype html><main>
    <h1>NeverEndingQuest player</h1>
    <button type="button">Log out</button>
    <p role="status">Not connected</p>
  </main>`);
  assert.deepEqual(sanitizeSetupScreenshotPage("player-a-chrome", unknownStatus.window.document), {
    safe: false,
    reason: "login-or-authentication-not-confirmed",
  });

  for (const status of ["Connected", "Disconnected", "Connecting...", "Loading player snapshot..."]) {
    const loggedIn = new JSDOM(`<!doctype html><main>
      <h1>NeverEndingQuest player</h1>
      <button type="button">Log out</button>
      <p role="status">${status}</p>
      <p role="alert">Connection state is being reported.</p>
    </main>`);
    assert.deepEqual(
      sanitizeSetupScreenshotPage("player-a-chrome", loggedIn.window.document),
      { safe: true, reason: null },
      `authenticated player screenshot should accept ${status}`,
    );
  }

  const hostUi = new JSDOM(`<!doctype html><main><div id="game-output"></div><textarea id="user-input">draft</textarea></main>`);
  assert.deepEqual(sanitizeSetupScreenshotPage("host-ui-chrome-context", hostUi.window.document), {
    safe: true,
    reason: null,
  });
  const incompleteHost = new JSDOM(`<!doctype html><main><div id="game-output"></div></main>`);
  assert.equal(sanitizeSetupScreenshotPage("host-ui-chrome-context", incompleteHost.window.document).safe, false);
});

test("credential-safe screenshot capture skips unsafe pages and masks before capture", async () => {
  const login = new JSDOM(`<!doctype html><h1>Player login</h1><input type="password" value="secret">`);
  let screenshotCalled = false;
  const skipped = await captureCredentialSafeScreenshot({
    isClosed: () => false,
    url: () => "http://127.0.0.1:8370/",
    evaluate: (callback, role) => evaluateSerializedSanitizer(callback, role, login.window.document),
    screenshot: async () => { screenshotCalled = true; },
  }, "player-a-chrome", "screenshots/login.png", "http://127.0.0.1:8370");
  assert.equal(skipped.status, "skipped");
  assert.equal(screenshotCalled, false);

  const authenticated = new JSDOM(`<!doctype html>
    <h1>NeverEndingQuest player</h1>
    <button type="button">Log out</button>
    <p role="status">Disconnected</p>
    <input type="hidden" name="csrf_token" value="csrf-secret">
    <textarea>typed-secret</textarea>
    <select><option selected>private-character</option></select>
    <div contenteditable="true">editable-secret</div>
    <button aria-label="Show session token">session-token-secret</button>`);
  let inputValueAtCapture = "not-captured";
  let maskedAtCapture = false;
  const captured = await captureCredentialSafeScreenshot({
    isClosed: () => false,
    url: () => "http://127.0.0.1:8370/",
    evaluate: (callback, role) => evaluateSerializedSanitizer(callback, role, authenticated.window.document),
    screenshot: async () => {
      screenshotCalled = true;
      inputValueAtCapture = authenticated.window.document.querySelector("input")?.value ?? "missing";
      maskedAtCapture =
        authenticated.window.document.querySelector("input")?.getAttribute("value") === "" &&
        authenticated.window.document.querySelector("textarea")?.value === "" &&
        authenticated.window.document.querySelector("select")?.selectedIndex === -1 &&
        authenticated.window.document.querySelector("[contenteditable]")?.textContent === "" &&
        authenticated.window.document.querySelector("button[aria-label]")?.textContent === "[REDACTED]";
    },
  }, "player-a-chrome", "screenshots/player.png", "http://127.0.0.1:8370");
  assert.equal(captured.status, "captured");
  assert.equal(screenshotCalled, true);
  assert.equal(inputValueAtCapture, "");
  assert.equal(maskedAtCapture, true);

  screenshotCalled = false;
  const wrongOrigin = await captureCredentialSafeScreenshot({
    isClosed: () => false,
    url: () => "http://127.0.0.1:8360/",
    evaluate: (callback, role) => evaluateSerializedSanitizer(callback, role, authenticated.window.document),
    screenshot: async () => { screenshotCalled = true; },
  }, "player-a-chrome", "screenshots/foreign.png", "http://127.0.0.1:8370");
  assert.deepEqual(wrongOrigin, { status: "skipped", reason: "page-not-ready" });
  assert.equal(screenshotCalled, false);
});

test("serialized screenshot safety skips login, unknown status, missing logout, and password pages", async () => {
  const pages = [
    {
      path: "login",
      html: `<!doctype html><h1>Player login</h1><input type="password" value="secret">`,
    },
    {
      path: "unknown-status",
      html: `<!doctype html><h1>NeverEndingQuest player</h1><button>Log out</button><p role="status">Not connected</p>`,
    },
    {
      path: "missing-logout",
      html: `<!doctype html><h1>NeverEndingQuest player</h1><button>Log out now</button><p role="status">Disconnected</p>`,
    },
    {
      path: "password-field",
      html: `<!doctype html><h1>NeverEndingQuest player</h1><button>Log out</button><p role="status">Disconnected</p><input type="password">`,
    },
  ];
  for (const entry of pages) {
    const dom = new JSDOM(entry.html);
    let screenshotCalled = false;
    const result = await captureCredentialSafeScreenshot({
      isClosed: () => false,
      url: () => "http://127.0.0.1:8370/",
      evaluate: (callback, role) => evaluateSerializedSanitizer(callback, role, dom.window.document),
      screenshot: async () => { screenshotCalled = true; },
    }, "player-a-chrome", `screenshots/${entry.path}.png`, "http://127.0.0.1:8370");
    assert.equal(result.status, "skipped", entry.path);
    assert.equal(screenshotCalled, false, entry.path);
  }
});

test("historic authenticated Disconnected DOM is captured before setup pages close", async () => {
  const order = [];
  const historicPage = new JSDOM(`<!doctype html><main>
    <header>
      <h1>NeverEndingQuest player</h1>
      <button type="button">Log out</button>
    </header>
    <p role="status">Disconnected</p>
    <p role="alert">The player connection ended before setup completed.</p>
  </main>`);
  const page = {
    isClosed: () => false,
    url: () => "http://127.0.0.1:8370/",
    evaluate: (callback, role) => evaluateSerializedSanitizer(callback, role, historicPage.window.document),
    screenshot: async () => { order.push("screenshot"); },
  };
  const result = await captureSetupFailureBeforeClose({
    stage: "player_connection_wait",
    observed: { player_connection_state: "disconnected", player_shell_loaded: true },
    pages: [{ role: "player-a-chrome", page }],
    flushRequestDiagnostics: async () => {
      order.push("flush");
      return {
        artifact: null,
        records_written: 0,
        records_omitted: 0,
        record_write_failures: 0,
        truncated: false,
      };
    },
    captureScreenshot: (candidate, role) => captureCredentialSafeScreenshot(
      candidate,
      role,
      "screenshots/player-a-chrome.png",
      "http://127.0.0.1:8370",
    ),
    writeRecord: async () => { order.push("record"); },
    closePages: async () => { order.push("close"); },
  });

  assert.equal(result.record.screenshots[0].status, "captured");
  assert.deepEqual(order, ["flush", "screenshot", "record", "close"]);
});

test("setup failure evidence reader distinguishes missing, valid, invalid, and oversized records", () => {
  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "reader-"));
  const path = join(directory, "setup-failure.json");
  try {
    assert.deepEqual(readSetupFailureEvidence(path), { status: "missing", record: null });
    const record = createSetupFailureRecord({
      stage: "browser_launch",
      observed: {},
      screenshots: [{ role: "setup", status: "skipped", reason: "page-unavailable" }],
      recordedAt: "2026-11-09T12:00:00.000Z",
    });
    assert.equal(record.observed.protocol_version, null);
    writeFileSync(path, `${JSON.stringify(record)}\n`, { encoding: "utf8" });
    assert.equal(readSetupFailureEvidence(path).status, "valid");
    const legacyRecord = { ...record, observed: { ...record.observed } };
    delete legacyRecord.observed.protocol_version;
    const normalizedLegacyRecord = normalizeSetupFailureRecord(legacyRecord);
    assert.equal(normalizedLegacyRecord?.observed.protocol_version, null);
    writeFileSync(path, "{bad json", { encoding: "utf8" });
    assert.deepEqual(readSetupFailureEvidence(path), { status: "invalid", record: null });
    writeFileSync(path, "x".repeat(16_385), { encoding: "utf8" });
    assert.deepEqual(readSetupFailureEvidence(path), { status: "invalid", record: null });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
