// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { waitForTextOnAnyPage } from "./page-locator-waits.mjs";

const PAGE_VARIABLES = new Set(["playerOne", "playerTwo", "hostPage"]);
const GATE_SOURCE = readFileSync(new URL("./n2-gate.spec.ts", import.meta.url), "utf8");

function crossPageLocatorCompositions(sourceText) {
  const violations = [];
  const expressionSegments = /[^;{}]+/gs;
  for (const segmentMatch of sourceText.matchAll(expressionSegments)) {
    const segment = segmentMatch[0];
    const operators = [...segment.matchAll(/\.(or|and)\s*\(/g)];
    if (operators.length === 0) continue;
    const pageReferences = new Set(
      [...segment.matchAll(/\b(playerOne|playerTwo|hostPage)\b/g)].map((match) => match[1]),
    );
    if (pageReferences.size > 1) {
      const start = (segmentMatch.index ?? 0) + (operators[0].index ?? 0);
      violations.push({
        line: sourceText.slice(0, start).split("\n").length,
        method: operators[0][1],
        pages: [...pageReferences].sort(),
      });
    }
  }
  return violations;
}

test("cross-page locator composition guard catches its synthetic negative controls", () => {
  const synthetic = `
    playerOne.getByText("ready").or(playerTwo.getByText("ready"));
    playerTwo.locator("button").and(playerOne.locator("button"));
  `;
  assert.deepEqual(crossPageLocatorCompositions(synthetic), [
    { line: 2, method: "or", pages: ["playerOne", "playerTwo"] },
    { line: 3, method: "and", pages: ["playerOne", "playerTwo"] },
  ]);
});

test("N2 gate has no locator composition across independent page variables", () => {
  assert.deepEqual(crossPageLocatorCompositions(GATE_SOURCE), []);
});

test("wait helper checks each page separately and returns per-page visibility", async () => {
  const visibility = [false, true];
  const pages = visibility.map((isVisible) => ({
    getByText(text) {
      assert.ok(text instanceof RegExp);
      assert.equal(text.source, "This input was not queued");
      return { isVisible: async () => isVisible };
    },
  }));
  let receivedTimeout;
  const fakeExpect = {
    poll(predicate, options) {
      receivedTimeout = options.timeout;
      return {
        async toBe(expected) {
          assert.equal(await predicate(), expected);
        },
      };
    },
  };

  assert.deepEqual(
    await waitForTextOnAnyPage(pages, /This input was not queued/, fakeExpect, { timeout: 15_000 }),
    visibility,
  );
  assert.equal(receivedTimeout, 15_000);
});
