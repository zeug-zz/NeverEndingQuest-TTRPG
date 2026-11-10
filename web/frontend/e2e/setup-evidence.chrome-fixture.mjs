// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { existsSync, mkdirSync, unlinkSync } from "node:fs";
import { inflateSync } from "node:zlib";
import { chromium } from "playwright";
import test from "node:test";
import { launchN2Browsers } from "./browser-contract.mjs";
import { captureCredentialSafeScreenshot } from "./setup-evidence.mjs";

const SCREENSHOT_ROOT = "tmp/n2/masking-fix";
const PLAYER_ORIGIN = "http://127.0.0.1:8370";
const AUTHENTICATED_HTML = `<!doctype html>
<html><head><meta charset="utf-8"><title>Offline player fixture</title>
<style>
  html, body { margin: 0; padding: 0; background: #fff; color: #111; font: 18px Arial, sans-serif; }
  main { width: 760px; padding: 24px; }
  main > * { display: block; box-sizing: border-box; width: 700px; min-height: 30px; margin: 4px 0; }
  input, textarea, select, button, [contenteditable="true"], .credential-text { padding: 8px; border: 1px solid #111; background: #fff; color: #111; }
  textarea { height: 42px; }
  [contenteditable="true"] { height: 42px; }
</style></head><body><main>
  <h1>NeverEndingQuest player</h1>
  <button id="logout-button" type="button">Log out</button>
  <p role="status">Disconnected</p>
  <input id="csrf-hidden" type="hidden" name="csrf_token" value="hidden-control-sentinel">
  <input id="draft-input" name="player-note" value="visible-input-sentinel" placeholder="input-placeholder-sentinel">
  <textarea id="notes-control">visible-textarea-sentinel</textarea>
  <select id="active-pc" name="active-character"><option value="Merisiel">Merisiel</option><option value="Acheron" selected>Acheron</option></select>
  <div id="editor-control" contenteditable="true"><strong>visible-editable-sentinel</strong></div>
  <button id="token-button" aria-label="Show session token">credential-button-sentinel</button>
  <span id="credential-text" data-testid="csrf-token-value" class="credential-text">credential-text-sentinel</span>
  <span id="data-sensitive" data-sensitive>data-sensitive-sentinel</span>
  <span id="data-secret" data-secret>data-secret-sentinel</span>
  <span id="text-identified">Authorization header sentinel</span>
  <span id="name-identified" name="refresh_token">name-identified sentinel</span>
  <span id="autocomplete-identified" autocomplete="current-password">autocomplete-identified sentinel</span>
  <div id="role-button-identified" role="button" aria-label="Session verifier">role-button sentinel</div>
</main></body></html>`;
const LOGIN_HTML = `<!doctype html><html><body><h1>Player login</h1><input type="password" value="synthetic-password-sentinel"></body></html>`;

test("offline Chrome screenshot masking preserves the live player page and active-PC selection", async () => {
  mkdirSync(SCREENSHOT_ROOT, { recursive: true });
  const { chromeBrowser: browser } = await launchN2Browsers({ chromium }, ["chrome"]);
  let blockedNetworkRequests = 0;
  let fulfilledFixtureRequests = 0;
  let context;
  try {
    context = await browser.newContext({
      viewport: { width: 1024, height: 900 },
      serviceWorkers: "block",
    });
    await context.route("**/*", async (route) => {
      let url;
      try {
        url = new URL(route.request().url());
      } catch {
        blockedNetworkRequests += 1;
        await route.abort();
        return;
      }
      if (url.origin === PLAYER_ORIGIN && url.pathname === "/" && !url.search && !url.hash) {
        fulfilledFixtureRequests += 1;
        await route.fulfill({
          status: 200,
          contentType: "text/html; charset=utf-8",
          body: AUTHENTICATED_HTML,
        });
        return;
      }
      if (url.origin === PLAYER_ORIGIN && url.pathname === "/unsafe" && !url.search && !url.hash) {
        fulfilledFixtureRequests += 1;
        await route.fulfill({
          status: 200,
          contentType: "text/html; charset=utf-8",
          body: LOGIN_HTML,
        });
        return;
      }
      if (url.origin === PLAYER_ORIGIN && url.pathname === "/favicon.ico") {
        fulfilledFixtureRequests += 1;
        await route.fulfill({ status: 204, body: "" });
        return;
      }
      blockedNetworkRequests += 1;
      await route.abort();
    });

    const page = await context.newPage();
    await page.goto(`${PLAYER_ORIGIN}/`, { waitUntil: "load" });
    await page.evaluate(prepareFixtureSelections);
    const before = await page.evaluate(snapshotFixtureState);
    assert.equal(before.controls.find((control) => control.id === "active-pc")?.value, "Acheron");
    assert.equal(before.controls.find((control) => control.id === "active-pc")?.selectedIndex, 1);

    const firstPath = `${SCREENSHOT_ROOT}/setup-evidence-chrome-mask.png`;
    const firstCapture = createPlaywrightScreenshotPage(page);
    const first = await captureCredentialSafeScreenshot(
      firstCapture.page,
      "player-a-chrome",
      firstPath,
      PLAYER_ORIGIN,
    );
    assert.deepEqual(first, { status: "captured", path: firstPath }, firstCapture.screenshotError ?? "");
    assert.ok(existsSync(firstPath));
    assert.deepEqual(await page.evaluate(snapshotFixtureState), before, "the screenshot call itself must not mutate the live DOM");
    await assertScreenshotMaskTargets(page, firstCapture.maskSelectors);
    await assertScreenshotPixels(page, firstCapture.screenshotBuffer, [
      "draft-input",
      "notes-control",
      "active-pc",
      "editor-control",
      "token-button",
      "credential-text",
      "data-sensitive",
      "data-secret",
      "text-identified",
      "name-identified",
      "autocomplete-identified",
      "role-button-identified",
    ]);
    assert.deepEqual(await page.evaluate(snapshotFixtureState), before);

    const secondPath = `${SCREENSHOT_ROOT}/setup-evidence-chrome-mask-repeat.png`;
    const secondCapture = createPlaywrightScreenshotPage(page);
    const second = await captureCredentialSafeScreenshot(
      secondCapture.page,
      "player-a-chrome",
      secondPath,
      PLAYER_ORIGIN,
    );
    assert.deepEqual(second, { status: "captured", path: secondPath });
    assert.ok(existsSync(secondPath));
    await assertScreenshotMaskTargets(page, secondCapture.maskSelectors);
    assert.deepEqual(await page.evaluate(snapshotFixtureState), before);

    const failedCapturePage = createPlaywrightScreenshotPage(page, { failScreenshot: true });
    const failedPath = `${SCREENSHOT_ROOT}/setup-evidence-chrome-mask-failed.png`;
    const failed = await captureCredentialSafeScreenshot(
      failedCapturePage.page,
      "player-a-chrome",
      failedPath,
      PLAYER_ORIGIN,
    );
    assert.deepEqual(failed, { status: "failed", reason: "screenshot-failed" });
    assert.equal(existsSync(failedPath), false);
    await assertScreenshotMaskTargets(page, failedCapturePage.maskSelectors);
    assert.deepEqual(await page.evaluate(snapshotFixtureState), before);

    const unsafePage = await context.newPage();
    await unsafePage.goto(`${PLAYER_ORIGIN}/unsafe`, { waitUntil: "load" });
    const unsafeBefore = await unsafePage.evaluate(snapshotFixtureState);
    const unsafeCapturePage = createPlaywrightScreenshotPage(unsafePage);
    const unsafe = await captureCredentialSafeScreenshot(
      unsafeCapturePage.page,
      "player-a-chrome",
      `${SCREENSHOT_ROOT}/setup-evidence-chrome-mask-unsafe.png`,
      PLAYER_ORIGIN,
    );
    assert.deepEqual(unsafe, { status: "skipped", reason: "login-or-authentication-not-confirmed" });
    assert.equal(unsafeCapturePage.screenshotBuffer, null);
    assert.deepEqual(await unsafePage.evaluate(snapshotFixtureState), unsafeBefore);

    assert.ok(fulfilledFixtureRequests >= 2, "the fixture pages must be fulfilled by browser routing");
    assert.equal(blockedNetworkRequests, 0, "all non-fixture browser requests must be aborted");
    const after = await page.evaluate(snapshotFixtureState);
    assert.deepEqual(after.events, []);
    assert.equal(after.controls.find((control) => control.id === "active-pc")?.value, "Acheron");
    assert.equal(after.controls.find((control) => control.id === "active-pc")?.selectedIndex, 1);
    console.log(`OFFLINE_CHROME_MASK_SCREENSHOT=${firstPath}`);
    console.log(`OFFLINE_CHROME_MASK_REPEAT=${secondPath}`);
  } finally {
    await context?.close();
    await browser.close();
  }
});

function createPlaywrightScreenshotPage(page, { failScreenshot = false } = {}) {
  const selectorsByLocator = new WeakMap();
  const observed = { maskSelectors: [], screenshotBuffer: null, screenshotError: null };
  const pageScreenshot = page.screenshot.bind(page);
  const wrappedPage = {
    isClosed: () => page.isClosed(),
    url: () => page.url(),
    evaluate: (...args) => page.evaluate(...args),
    locator: (selector) => {
      const locator = page.locator(selector);
      selectorsByLocator.set(locator, selector);
      return locator;
    },
    screenshot: async (options) => {
      observed.maskSelectors = options.mask.map((locator) => selectorsByLocator.get(locator) ?? null);
      if (failScreenshot) {
        try {
          observed.screenshotBuffer = await pageScreenshot(options);
        } finally {
          if (existsSync(options.path)) unlinkSync(options.path);
        }
        throw new Error("synthetic screenshot failure after masked capture");
      }
      try {
        observed.screenshotBuffer = await pageScreenshot(options);
      } catch (error) {
        observed.screenshotError = error instanceof Error ? error.message : "unknown screenshot failure";
        throw error;
      }
      return observed.screenshotBuffer;
    },
  };
  return {
    page: wrappedPage,
    get maskSelectors() {
      return observed.maskSelectors;
    },
    get screenshotBuffer() {
      return observed.screenshotBuffer;
    },
    get screenshotError() {
      return observed.screenshotError;
    },
  };
}

function assertScreenshotMaskTargets(page, selectors) {
  const expectedIds = new Set([
    "csrf-hidden",
    "draft-input",
    "notes-control",
    "active-pc",
    "editor-control",
    "token-button",
    "credential-text",
    "data-sensitive",
    "data-secret",
    "text-identified",
    "name-identified",
    "autocomplete-identified",
    "role-button-identified",
  ]);
  assert.equal(selectors.length, expectedIds.size);
  const actualIds = [];
  for (const selector of selectors) {
    assert.equal(typeof selector, "string");
    actualIds.push(page.locator(selector).evaluate((element) => element.id));
  }
  return Promise.all(actualIds).then((ids) => {
    assert.deepEqual(new Set(ids), expectedIds);
  });
}

async function assertScreenshotPixels(page, buffer, elementIds) {
  assert.ok(Buffer.isBuffer(buffer));
  const image = decodePng(buffer);
  for (const id of elementIds) {
    const box = await page.locator(`#${id}`).boundingBox();
    assert.ok(box && box.width > 0 && box.height > 0, `fixture element #${id} must be visible`);
    const x = Math.floor(box.x + box.width / 2);
    const y = Math.floor(box.y + box.height / 2);
    assert.deepEqual(
      pixelAt(image, x, y),
      [255, 0, 255],
      `#${id} must be overlaid by the screenshot mask at (${x}, ${y}) in ${image.width}x${image.height}`,
    );
  }
}

function decodePng(buffer) {
  assert.deepEqual(buffer.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  let offset = 8;
  let width = 0;
  let height = 0;
  let bitDepth = 0;
  let colorType = 0;
  const imageData = [];
  while (offset < buffer.length) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString("ascii", offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
    } else if (type === "IDAT") {
      imageData.push(data);
    } else if (type === "IEND") {
      break;
    }
    offset += length + 12;
  }
  assert.equal(bitDepth, 8, "Chrome fixture screenshot must use 8-bit PNG channels");
  const channelsByColorType = { 2: 3, 6: 4 };
  const channels = channelsByColorType[colorType];
  assert.ok(channels, `unsupported Chrome screenshot PNG color type ${colorType}`);
  const stride = width * channels;
  const inflated = inflateSync(Buffer.concat(imageData));
  const pixels = Buffer.alloc(height * stride);
  const paeth = (left, above, upperLeft) => {
    const estimate = left + above - upperLeft;
    const leftDistance = Math.abs(estimate - left);
    const aboveDistance = Math.abs(estimate - above);
    const upperLeftDistance = Math.abs(estimate - upperLeft);
    if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) return left;
    if (aboveDistance <= upperLeftDistance) return above;
    return upperLeft;
  };
  let sourceOffset = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[sourceOffset];
    sourceOffset += 1;
    const rowOffset = y * stride;
    for (let x = 0; x < stride; x += 1) {
      const raw = inflated[sourceOffset + x];
      const left = x >= channels ? pixels[rowOffset + x - channels] : 0;
      const above = y > 0 ? pixels[rowOffset + x - stride] : 0;
      const upperLeft = y > 0 && x >= channels ? pixels[rowOffset + x - stride - channels] : 0;
      let predictor = 0;
      if (filter === 1) predictor = left;
      else if (filter === 2) predictor = above;
      else if (filter === 3) predictor = Math.floor((left + above) / 2);
      else if (filter === 4) predictor = paeth(left, above, upperLeft);
      else assert.equal(filter, 0, `unsupported PNG row filter ${filter}`);
      pixels[rowOffset + x] = (raw + predictor) & 0xff;
    }
    sourceOffset += stride;
  }
  return { width, height, channels, pixels };
}

function pixelAt(image, x, y) {
  assert.ok(x >= 0 && x < image.width && y >= 0 && y < image.height, "mask pixel must be within screenshot bounds");
  const offset = (y * image.width + x) * image.channels;
  return [image.pixels[offset], image.pixels[offset + 1], image.pixels[offset + 2]];
}

function prepareFixtureSelections() {
  const draft = document.querySelector("#draft-input");
  draft.focus();
  draft.setSelectionRange(3, 8);
  document.querySelector("#active-pc").selectedIndex = 1;
  const textNode = document.querySelector("#editor-control strong").firstChild;
  const range = document.createRange();
  range.setStart(textNode, 2);
  range.setEnd(textNode, 12);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  window.__n2MaskEvents = [];
  for (const eventName of ["beforeinput", "input", "change", "focus", "blur"]) {
    document.addEventListener(eventName, () => window.__n2MaskEvents.push(eventName));
  }
}

function snapshotFixtureState() {
  const describeNode = (node) => ({
    text: node?.textContent ?? null,
    parentId: node?.parentElement?.id ?? null,
  });
  const selection = window.getSelection();
  const controls = [...document.querySelectorAll("input, textarea, select")].map((element) => ({
    id: element.id,
    value: element.value,
    selectedIndex: typeof element.selectedIndex === "number" ? element.selectedIndex : null,
    selectedValues: element.selectedOptions
      ? [...element.selectedOptions].map((option) => option.value)
      : null,
    selectionStart: typeof element.selectionStart === "number" ? element.selectionStart : null,
    selectionEnd: typeof element.selectionEnd === "number" ? element.selectionEnd : null,
    attributes: [...element.attributes].map((attribute) => [attribute.name, attribute.value]),
    style: element.getAttribute("style"),
  }));
  return {
    html: document.documentElement.outerHTML,
    activeElement: document.activeElement?.id ?? null,
    controls,
    editableSubtrees: [...document.querySelectorAll("[contenteditable='true']")]
      .map((element) => ({ html: element.innerHTML, text: element.textContent })),
    selection: {
      text: selection.toString(),
      anchor: describeNode(selection.anchorNode),
      anchorOffset: selection.anchorOffset,
      focus: describeNode(selection.focusNode),
      focusOffset: selection.focusOffset,
    },
    events: [...(window.__n2MaskEvents ?? [])],
  };
}
