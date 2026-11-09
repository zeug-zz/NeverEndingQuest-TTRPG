// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  MAX_DRIVER_OUTPUT_BYTES_PER_STREAM,
  PlaywrightDriverOutputCollector,
  normalizePlaywrightDriverOutput,
  runPlaywrightProcess,
  writePlaywrightDriverOutputEvidence,
} from "./playwright-driver-output.mjs";

const PROJECT_ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const TEST_ROOT = join(PROJECT_ROOT, "tmp", "n2", "setup-evidence");

test("driver output collector drops split secrets and malicious chunks while bounding byte counts", () => {
  const collector = new PlaywrightDriverOutputCollector({ maxBytesPerStream: 8 });
  collector.markSpawned();
  collector.capture("stdout", Buffer.from("password="));
  collector.capture("stdout", Buffer.from("split-secret"));
  collector.capture("stderr", Buffer.from("\u001b]0;Authorization: Bearer malicious\u0007"));
  collector.finish(19, "SIGTERM");

  const record = collector.snapshot();
  const serialized = JSON.stringify(record);
  for (const value of ["password=", "split-secret", "Authorization", "malicious", "\u001b"]) {
    assert.equal(serialized.includes(value), false, `driver evidence retained ${JSON.stringify(value)}`);
  }
  assert.deepEqual(record.stdout, { bytes_observed: 8, truncated: true });
  assert.deepEqual(record.stderr, { bytes_observed: 8, truncated: true });
  assert.equal(record.exit_status, 19);
  assert.equal(record.exit_signal, "SIGTERM");
  assert.equal(record.raw_output_retained, false);
  assert.equal(record.max_bytes_per_stream, 8);
  assert.ok(record.max_bytes_per_stream <= MAX_DRIVER_OUTPUT_BYTES_PER_STREAM);
});

test("actual fake Playwright child output is counted and only safe metadata is persisted", async () => {
  const stdoutText = "driver-password-split";
  const stderrText = "Authorization: Bearer fake-malicious-token\n";
  const script = [
    'process.stdout.write("driver-password-");',
    'process.stdout.write("split");',
    'process.stderr.write("Authorization: Bearer fake-malicious-token\\n");',
    "process.exitCode = 17;",
  ].join("\n");
  const child = await runPlaywrightProcess(process.execPath, ["-e", script], {}, { cwd: PROJECT_ROOT });
  assert.equal(child.status, 17);
  assert.equal(child.error, null);
  assert.equal(child.driverOutput.spawn_category, null);
  assert.equal(child.driverOutput.exit_status, 17);
  assert.equal(child.driverOutput.stdout.bytes_observed, Buffer.byteLength(stdoutText, "utf8"));
  assert.equal(child.driverOutput.stderr.bytes_observed, Buffer.byteLength(stderrText, "utf8"));

  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "driver-output-"));
  try {
    const summary = writePlaywrightDriverOutputEvidence(child.driverOutput, directory);
    const artifact = readFileSync(join(directory, "driver-output.json"), "utf8");
    for (const value of ["driver-password", "split", "Authorization", "fake-malicious-token", "process.execPath"]) {
      assert.equal(artifact.includes(value), false, `driver-output.json retained ${value}`);
    }
    assert.equal(summary.artifact, "driver-output.json");
    assert.equal(summary.raw_output_retained, false);
    assert.equal(summary.exit_status, 17);
    assert.equal(JSON.parse(artifact).stdout.bytes_observed, Buffer.byteLength(stdoutText, "utf8"));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("driver spawn failure records only a fixed category without exception text", async () => {
  const result = await runPlaywrightProcess("unused", [], {}, {
    spawnProcess: () => { throw new Error("password=spawn-secret"); },
  });
  assert.equal(result.driverOutput.spawn_category, "spawn_error");
  assert.equal(result.driverOutput.exit_status, null);
  assert.equal(JSON.stringify(result.driverOutput).includes("spawn-secret"), false);
});

test("driver output schema rejects arbitrary raw text fields and unknown signal/category values", () => {
  const safe = new PlaywrightDriverOutputCollector().snapshot();
  assert.deepEqual(normalizePlaywrightDriverOutput(safe), safe);
  assert.equal(normalizePlaywrightDriverOutput({ ...safe, stderr_text: "secret" }), null);
  assert.equal(normalizePlaywrightDriverOutput({ ...safe, exit_signal: "secret" }), null);
  assert.equal(normalizePlaywrightDriverOutput({ ...safe, spawn_category: "secret" }), null);
});
