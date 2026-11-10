// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { assertHostUi } from "./managed-lifecycle.mjs";

function fakePage({ inputExists = true, inputEnabled = false, buttonEnabled = true, buttonText = "Start Game" }) {
  return {
    async goto() { return { status: () => 200 }; },
    locator(selector) {
      if (selector === "#game-output") return { async waitFor() {} };
      if (selector === "#user-input") {
        return {
          async waitFor() { if (!inputExists) throw new Error("missing #user-input"); },
          async isEnabled() { return inputEnabled; },
        };
      }
      return {
        async waitFor() {},
        async textContent() { return buttonText; },
        async isEnabled() { return buttonEnabled; },
      };
    },
  };
}

test("host UI accepts disabled input while start button is enabled", async () => {
  const result = await assertHostUi(fakePage({ inputEnabled: false, buttonEnabled: true }));
  assert.equal(result.user_input_attached, true);
  assert.equal(result.user_input_enabled, false);
  assert.equal(result.user_input_disabled_until_game_start, true);
  assert.equal(result.host_socket_connected, true);
  assert.equal(result.probe_submitted, false);
});

test("host UI fails when start button never enables", async () => {
  await assert.rejects(
    assertHostUi(fakePage({ buttonEnabled: false }), { timeoutMs: 1 }),
    /host socket did not connect/,
  );
});

test("host UI accepts already-started game", async () => {
  const result = await assertHostUi(fakePage({ buttonEnabled: false, buttonText: "Game Running" }));
  assert.equal(result.host_socket_connected, true);
});

test("host UI fails when gameplay input is missing", async () => {
  await assert.rejects(assertHostUi(fakePage({ inputExists: false })), /missing #user-input/);
});
