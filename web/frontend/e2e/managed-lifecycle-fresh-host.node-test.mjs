// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { startFreshHostProcess } from "./managed-lifecycle.mjs";

test("fresh host stops first and starts with player expected and signal", async () => {
  const calls = [];
  const manager = {
    async stop() { calls.push(["stop"]); },
    async start(options) { calls.push(["start", options]); return "started"; },
  };
  const signal = new AbortController().signal;
  assert.equal(await startFreshHostProcess(manager, { signal }), "started");
  assert.deepEqual(calls, [["stop"], ["start", { playerExpected: true, signal }]]);
});

test("fresh host propagates start failure after stopping", async () => {
  const calls = [];
  const failure = new Error("start failed");
  const manager = {
    async stop() { calls.push("stop"); },
    async start() { calls.push("start"); throw failure; },
  };
  await assert.rejects(startFreshHostProcess(manager), (error) => error === failure);
  assert.deepEqual(calls, ["stop", "start"]);
});
