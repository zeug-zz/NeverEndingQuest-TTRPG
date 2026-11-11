// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { chromium, firefox } from "playwright";
import { expect } from "playwright/test";
import test from "node:test";
import { captureCredentialSafeScreenshot } from "./setup-evidence.mjs";
import { waitForTextOnAnyPage } from "./page-locator-waits.mjs";

const PLAYER_URL = "http://127.0.0.1:8370/";
const PLAYER_ORIGIN = "http://127.0.0.1:8370";
const AUTHENTICATED_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>Offline player fixture</title></head><body>
<main>
  <h1>NeverEndingQuest player</h1>
  <button type="button">Log out</button>
  <p role="status">Connected</p>
  <p id="busy-notice"></p>
  <textarea id="gameplay-input">fixture draft</textarea>
</main>
</body></html>`;

for (const name of [
  "MOZ_DISABLE_CONTENT_SANDBOX",
  "MOZ_DISABLE_GMP_SANDBOX",
  "MOZ_DISABLE_RDD_SANDBOX",
  "MOZ_DISABLE_SOCKET_PROCESS_SANDBOX",
]) {
  process.env[name] = "1";
}

test("offline Chrome and Firefox wait for busy text on either independent page", async (t) => {
  let chromeBrowser;
  try {
    chromeBrowser = await chromium.launch({ headless: true, channel: "chrome" });
  } catch (error) {
    t.skip(`Chrome channel could not launch for the offline dual-browser fixture: ${errorMessage(error)}`);
    return;
  }

  let firefoxBrowser;
  try {
    firefoxBrowser = await firefox.launch({ headless: true });
  } catch (error) {
    await chromeBrowser.close().catch(() => {});
    t.skip(`Firefox could not launch for the offline dual-browser fixture: ${errorMessage(error)}`);
    return;
  }

  mkdirSync("tmp/n2", { recursive: true });
  const scratch = mkdtempSync(join("tmp/n2", "busy-input-dual-browser-"));
  let chromeContext;
  let firefoxContext;
  try {
    chromeContext = await chromeBrowser.newContext({ serviceWorkers: "block" });
    firefoxContext = await firefoxBrowser.newContext({ serviceWorkers: "block" });
    await Promise.all([chromeContext, firefoxContext].map((context) =>
      context.route("**/*", async (route) => {
        let url;
        try {
          url = new URL(route.request().url());
        } catch {
          await route.abort();
          return;
        }
        if (url.origin === PLAYER_ORIGIN && url.pathname === "/" && !url.search && !url.hash) {
          await route.fulfill({
            status: 200,
            contentType: "text/html; charset=utf-8",
            body: AUTHENTICATED_HTML,
          });
          return;
        }
        await route.abort();
      }),
    ));

    const chromePage = await chromeContext.newPage();
    const firefoxPage = await firefoxContext.newPage();
    await Promise.all([
      chromePage.goto(PLAYER_URL, { waitUntil: "load" }),
      firefoxPage.goto(PLAYER_URL, { waitUntil: "load" }),
    ]);
    await firefoxPage.evaluate(() => {
      window.setTimeout(() => {
        const busyNotice = document.querySelector("#busy-notice");
        if (busyNotice) busyNotice.textContent = "This input was not queued";
      }, 100);
    });

    const firefoxNotice = await waitForTextOnAnyPage(
      [chromePage, firefoxPage],
      /This input was not queued/,
      expect,
      { timeout: 5_000, intervals: [20, 50, 100] },
    );
    assert.deepEqual(firefoxNotice, [false, true]);

    await firefoxPage.locator("#busy-notice").evaluate((element) => { element.textContent = ""; });
    await chromePage.locator("#busy-notice").evaluate((element) => {
      element.textContent = "This input was not queued";
    });
    const chromeNotice = await waitForTextOnAnyPage(
      [chromePage, firefoxPage],
      /This input was not queued/,
      expect,
      { timeout: 5_000, intervals: [20, 50, 100] },
    );
    assert.deepEqual(chromeNotice, [true, false]);

    const screenshots = await Promise.all([
      captureCredentialSafeScreenshot(
        chromePage,
        "player-a-chrome",
        join(scratch, "chrome.png"),
        PLAYER_ORIGIN,
      ),
      captureCredentialSafeScreenshot(
        firefoxPage,
        "player-b-firefox",
        join(scratch, "firefox.png"),
        PLAYER_ORIGIN,
      ),
    ]);
    assert.deepEqual(screenshots.map((screenshot) => screenshot.status), ["captured", "captured"]);
    assert.ok(existsSync(join(scratch, "chrome.png")));
    assert.ok(existsSync(join(scratch, "firefox.png")));
  } finally {
    await Promise.all([
      chromeContext?.close().catch(() => {}),
      firefoxContext?.close().catch(() => {}),
      chromeBrowser.close().catch(() => {}),
      firefoxBrowser.close().catch(() => {}),
    ]);
    rmSync(scratch, { recursive: true, force: true });
  }
});

function errorMessage(error) {
  return error instanceof Error ? error.message : "unknown browser launch error";
}
