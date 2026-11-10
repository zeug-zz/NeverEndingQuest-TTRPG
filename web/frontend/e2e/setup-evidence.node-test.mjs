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

function snapshotDom(dom) {
  const documentRef = dom.window.document;
  const selection = dom.window.getSelection();
  return {
    html: documentRef.documentElement.outerHTML,
    activeElement: documentRef.activeElement?.id ?? null,
    controls: [...documentRef.querySelectorAll("input, textarea, select")].map((element) => ({
      tagName: element.tagName,
      value: element.value,
      selectedIndex: typeof element.selectedIndex === "number" ? element.selectedIndex : null,
      selectedValues: element.selectedOptions
        ? [...element.selectedOptions].map((option) => option.value)
        : null,
      selectionStart: typeof element.selectionStart === "number" ? element.selectionStart : null,
      selectionEnd: typeof element.selectionEnd === "number" ? element.selectionEnd : null,
    })),
    editableSubtrees: [...documentRef.querySelectorAll("[contenteditable='true']")]
      .map((element) => ({ html: element.innerHTML, text: element.textContent })),
    selection: selection
      ? {
          text: selection.toString(),
          anchorText: selection.anchorNode?.textContent ?? null,
          anchorOffset: selection.anchorOffset,
          focusText: selection.focusNode?.textContent ?? null,
          focusOffset: selection.focusOffset,
        }
      : null,
  };
}

function createSerializedScreenshotPage(dom, {
  url = "http://127.0.0.1:8370/",
  screenshotError = null,
  screenshotEffect = null,
} = {}) {
  const screenshotOptions = [];
  const page = {
    isClosed: () => false,
    url: () => url,
    evaluate: async (callback, role) => evaluateSerializedSanitizer(callback, role, dom.window.document),
    locator: (selector) => {
      const elements = [...dom.window.document.querySelectorAll(selector)];
      return {
        selector,
        element: elements[0],
        count: async () => elements.length,
      };
    },
    screenshot: async (options) => {
      assert.equal(options.caret, "initial");
      screenshotOptions.push(options);
      if (screenshotError) throw screenshotError;
      await screenshotEffect?.(options);
    },
  };
  return { page, screenshotOptions };
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

test("serialized screenshot masking is non-interfering and keeps authentication safety checks", async () => {
  const authenticated = new JSDOM(`<!doctype html><main>
    <h1>NeverEndingQuest player</h1>
    <button id="logout-button" type="button">Log out</button>
    <p role="status">Disconnected</p>
    <input type="hidden" name="csrf_token" value="csrf-secret" style="color: rgb(1, 2, 3)">
    <input name="player-note" value="draft-secret" placeholder="keep-placeholder" style="outline: 1px solid red">
    <textarea id="text-control">typed-secret</textarea>
    <select id="active-pc" name="active-character"><option value="Merisiel">Merisiel</option><option value="Acheron" selected>Acheron</option></select>
    <div id="editable-control" contenteditable="true"><strong>editable-sentinel</strong></div>
    <button id="token-button" aria-label="Show session token">session-token-sentinel</button>
    <span data-testid="csrf-token-value">csrf-ui-sentinel</span>
    <span data-sensitive>identified-sensitive-sentinel</span>
    <span data-secret>identified-secret-sentinel</span>
    <span id="text-identified">Authorization header sentinel</span>
    <span name="refresh_token">name-identified sentinel</span>
    <span autocomplete="current-password">autocomplete-identified sentinel</span>
    <div role="button" aria-label="Session verifier">role-button sentinel</div>
  </main>`, { pretendToBeVisual: true });
  const documentRef = authenticated.window.document;
  const draft = documentRef.querySelector("input[name='player-note']");
  draft.focus();
  draft.setSelectionRange(2, 7);
  documentRef.querySelector("select").selectedIndex = 1;
  const editableText = documentRef.querySelector("#editable-control strong").firstChild;
  const range = documentRef.createRange();
  range.setStart(editableText, 2);
  range.setEnd(editableText, 9);
  authenticated.window.getSelection().removeAllRanges();
  authenticated.window.getSelection().addRange(range);
  const events = [];
  for (const eventName of ["beforeinput", "input", "change", "focus", "blur", "selectionchange"]) {
    documentRef.addEventListener(eventName, () => events.push(eventName));
  }
  const before = snapshotDom(authenticated);
  const serializedSafety = evaluateSerializedSanitizer(
    sanitizeSetupScreenshotPage,
    "player-a-chrome",
    documentRef,
  );
  assert.equal(serializedSafety.safe, true);
  assert.equal(serializedSafety.reason, null);
  assert.ok(Array.isArray(serializedSafety.mask_selectors));

  const mock = createSerializedScreenshotPage(authenticated);
  const captured = await captureCredentialSafeScreenshot(
    mock.page,
    "player-a-chrome",
    "screenshots/player.png",
    "http://127.0.0.1:8370",
  );
  assert.equal(captured.status, "captured");
  assert.deepEqual(snapshotDom(authenticated), before);
  assert.deepEqual(events, []);

  const expectedMaskedElements = [
    ...documentRef.querySelectorAll("input, textarea, select, [contenteditable='true']"),
    documentRef.querySelector("#token-button"),
    documentRef.querySelector("[data-testid='csrf-token-value']"),
    documentRef.querySelector("[data-sensitive]"),
    documentRef.querySelector("[data-secret]"),
    documentRef.querySelector("#text-identified"),
    documentRef.querySelector("[name='refresh_token']"),
    documentRef.querySelector("[autocomplete='current-password']"),
    documentRef.querySelector("[role='button']"),
  ];
  const screenshotMask = mock.screenshotOptions[0]?.mask;
  assert.ok(Array.isArray(screenshotMask));
  const actualMaskedElements = new Set(screenshotMask.map((locator) => locator.element));
  assert.equal(actualMaskedElements.size, expectedMaskedElements.length);
  for (const element of expectedMaskedElements) assert.ok(actualMaskedElements.has(element));
  assert.equal(actualMaskedElements.has(documentRef.querySelector("#logout-button")), false);
  assert.equal(documentRef.querySelector("#active-pc").value, "Acheron");

  const repeated = await captureCredentialSafeScreenshot(
    mock.page,
    "player-a-chrome",
    "screenshots/player-repeat.png",
    "http://127.0.0.1:8370",
  );
  assert.equal(repeated.status, "captured");
  assert.deepEqual(snapshotDom(authenticated), before);
  assert.deepEqual(events, []);

  const failingMock = createSerializedScreenshotPage(authenticated, {
    screenshotError: new Error("synthetic screenshot failure"),
  });
  const failed = await captureCredentialSafeScreenshot(
    failingMock.page,
    "player-a-chrome",
    "screenshots/player-failed.png",
    "http://127.0.0.1:8370",
  );
  assert.deepEqual(failed, { status: "failed", reason: "screenshot-failed" });
  assert.deepEqual(snapshotDom(authenticated), before);
  assert.deepEqual(events, []);

  const login = new JSDOM(`<!doctype html><main><h1>Player login</h1><input type="password" value="password-secret"></main>`);
  const loginBefore = snapshotDom(login);
  const loginMock = createSerializedScreenshotPage(login);
  const unsafe = await captureCredentialSafeScreenshot(
    loginMock.page,
    "player-a-chrome",
    "screenshots/login.png",
    "http://127.0.0.1:8370",
  );
  assert.deepEqual(unsafe, { status: "skipped", reason: "login-or-authentication-not-confirmed" });
  assert.equal(loginMock.screenshotOptions.length, 0);
  assert.deepEqual(snapshotDom(login), loginBefore);
  assert.equal(sanitizeSetupScreenshotPage("unapproved-role", login.window.document).safe, false);

  const disconnectedWithoutLogout = new JSDOM(`<!doctype html><h1>NeverEndingQuest player</h1><p role="status">Disconnected</p>`);
  assert.deepEqual(sanitizeSetupScreenshotPage("player-a-chrome", disconnectedWithoutLogout.window.document), {
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
    const safety = evaluateSerializedSanitizer(sanitizeSetupScreenshotPage, "player-a-chrome", loggedIn.window.document);
    assert.equal(safety.safe, true, `authenticated player screenshot should accept ${status}`);
  }

  const hostUi = new JSDOM(`<!doctype html><main><div id="game-output"></div><textarea id="user-input">draft</textarea></main>`);
  const hostSafety = evaluateSerializedSanitizer(
    sanitizeSetupScreenshotPage,
    "host-ui-chrome-context",
    hostUi.window.document,
  );
  assert.equal(hostSafety.safe, true);
  assert.ok(hostSafety.mask_selectors.length > 0);
  const incompleteHost = new JSDOM(`<!doctype html><main><div id="game-output"></div></main>`);
  assert.deepEqual(sanitizeSetupScreenshotPage("host-ui-chrome-context", incompleteHost.window.document), {
    safe: false,
    reason: "login-or-authentication-not-confirmed",
  });
});

test("screenshot capture preserves legitimate active-PC and DOM updates during masking", async () => {
  const dom = new JSDOM(`<!doctype html><main>
    <h1>NeverEndingQuest player</h1>
    <button type="button">Log out</button>
    <p role="status">Disconnected</p>
    <select id="active-pc"><option value="Acheron" selected>Acheron</option><option value="Merisiel">Merisiel</option></select>
    <div id="editable-control" contenteditable="true"><strong>Initial fixture value</strong></div>
  </main>`);
  const mock = createSerializedScreenshotPage(dom, {
    screenshotEffect: async () => {
      dom.window.document.querySelector("#active-pc").value = "Merisiel";
      dom.window.document.querySelector("#editable-control").innerHTML = "<strong>Updated server value</strong>";
    },
  });

  const result = await captureCredentialSafeScreenshot(
    mock.page,
    "player-a-chrome",
    "screenshots/player-concurrent-update.png",
    "http://127.0.0.1:8370",
  );

  assert.deepEqual(result, {
    status: "captured",
    path: "screenshots/player-concurrent-update.png",
  });
  assert.equal(dom.window.document.querySelector("#active-pc").value, "Merisiel");
  assert.equal(dom.window.document.querySelector("#active-pc").selectedIndex, 1);
  assert.equal(
    dom.window.document.querySelector("#editable-control").innerHTML,
    "<strong>Updated server value</strong>",
  );
  assert.equal(mock.screenshotOptions.length, 1);
});

test("credential-safe screenshot capture refuses origin and mask errors", async () => {
  const login = new JSDOM(`<!doctype html><h1>Player login</h1><input type="password" value="secret">`);
  const loginMock = createSerializedScreenshotPage(login);
  const skipped = await captureCredentialSafeScreenshot(
    loginMock.page,
    "player-a-chrome",
    "screenshots/login.png",
    "http://127.0.0.1:8370",
  );
  assert.deepEqual(skipped, { status: "skipped", reason: "login-or-authentication-not-confirmed" });
  assert.equal(loginMock.screenshotOptions.length, 0);

  const authenticated = new JSDOM(`<!doctype html>
    <h1>NeverEndingQuest player</h1>
    <button type="button">Log out</button>
    <p role="status">Disconnected</p>
    <input name="player-note" value="draft-secret">
    <textarea>typed-secret</textarea>`);
  const wrongOriginMock = createSerializedScreenshotPage(authenticated, {
    url: "http://127.0.0.1:8360/",
  });
  const wrongOrigin = await captureCredentialSafeScreenshot(
    wrongOriginMock.page,
    "player-a-chrome",
    "screenshots/foreign.png",
    "http://127.0.0.1:8370",
  );
  assert.deepEqual(wrongOrigin, { status: "skipped", reason: "page-not-ready" });
  assert.equal(wrongOriginMock.screenshotOptions.length, 0);

  const maskErrorMock = createSerializedScreenshotPage(authenticated);
  maskErrorMock.page.locator = () => ({ count: async () => 0 });
  const maskError = await captureCredentialSafeScreenshot(
    maskErrorMock.page,
    "player-a-chrome",
    "screenshots/mask-error.png",
    "http://127.0.0.1:8370",
  );
  assert.deepEqual(maskError, { status: "failed", reason: "screenshot-failed" });
  assert.equal(maskErrorMock.screenshotOptions.length, 0);
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
  const mock = createSerializedScreenshotPage(historicPage);
  mock.page.screenshot = async (options) => {
    mock.screenshotOptions.push(options);
    order.push("screenshot");
  };
  const page = mock.page;
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
