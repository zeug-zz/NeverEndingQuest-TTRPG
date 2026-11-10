// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { hitPointsLabel } from "./sheet-locator.mjs";

function matchingCount(labels, options) {
  return labels.filter((label) => options.hasText.test(label)).length;
}

test("exact Hit points locator excludes Maximum hit points and keeps count strict", () => {
  let captured;
  const sheet = { locator: (selector, options) => (captured = { selector, options }) };
  hitPointsLabel(sheet);
  assert.equal(captured.selector, "dt");
  assert.equal(matchingCount(["Hit points", "Maximum hit points"], captured.options), 1);
  assert.equal(matchingCount(["Maximum hit points"], captured.options), 0);
  assert.equal(matchingCount(["Hit points", "Hit points"], captured.options), 2);
});
