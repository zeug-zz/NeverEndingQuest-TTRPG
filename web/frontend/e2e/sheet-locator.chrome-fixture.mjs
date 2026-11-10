// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { chromium } from "playwright";
import test from "node:test";
import { launchN2Browsers } from "./browser-contract.mjs";
import { hitPointsLabel } from "./sheet-locator.mjs";

test("offline Chrome confirms exact sheet label locator cardinality", async () => {
  const { chromeBrowser } = await launchN2Browsers({ chromium }, ["chrome"]);
  try {
    const page = await chromeBrowser.newPage();
    await page.setContent("<article><dl><dt>Hit points</dt><dd>8</dd><dt>Maximum hit points</dt><dd>12</dd></dl></article>");
    const sheet = page.locator("article");
    assert.equal(await sheet.locator("dt", { hasText: "Hit points" }).count(), 2);
    assert.equal(await hitPointsLabel(sheet).count(), 1);
    await page.setContent("<article><dt>Maximum hit points</dt></article>");
    assert.equal(await hitPointsLabel(page.locator("article")).count(), 0);
    await page.setContent("<article><dt>Hit points</dt><dt>Hit points</dt></article>");
    assert.equal(await hitPointsLabel(page.locator("article")).count(), 2);
  } finally {
    await chromeBrowser.close();
  }
});
