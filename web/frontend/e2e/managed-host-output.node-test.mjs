// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  attachManagedHostOutputCapture,
  ManagedHostOutputCollector,
  normalizeManagedHostOutput,
  writeManagedHostOutputEvidence,
} from "./managed-host-output.mjs";

const PROJECT_ROOT = resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const TEST_ROOT = join(PROJECT_ROOT, "tmp", "n2", "setup-evidence");

function fakeChild(pid) {
  const child = new EventEmitter();
  child.pid = pid;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  return child;
}

test("managed host integration discards raw stream chunks and bounds counters across restarts", () => {
  const collector = new ManagedHostOutputCollector({ maxStreamBytes: 8, maxProcessRecords: 1 });
  const secret = "host-output-secret";
  const firstChild = fakeChild(55);
  attachManagedHostOutputCapture(firstChild, collector);
  firstChild.stdout.emit("data", Buffer.from("123456"));
  firstChild.stdout.emit("data", Buffer.from(secret));
  firstChild.stderr.emit("data", "12345678");
  firstChild.emit("close", 1, null);

  const secondChild = fakeChild(56);
  attachManagedHostOutputCapture(secondChild, collector);
  secondChild.stderr.emit("data", Buffer.from(secret));
  secondChild.emit("close", null, "SIGTERM");

  const snapshot = collector.snapshot();
  assert.equal(snapshot.total_process_starts, 2);
  assert.equal(snapshot.processes.length, 1);
  assert.equal(snapshot.omitted_process_records, 1);
  assert.equal(snapshot.processes[0].stdout.bytes_observed, 8);
  assert.equal(snapshot.processes[0].stdout.truncated, true);
  assert.equal(snapshot.processes[0].stderr.bytes_observed, 8);
  assert.equal(snapshot.processes[0].stderr.truncated, false);
  assert.equal(snapshot.processes[0].exit_status, 1);
  assert.equal(snapshot.processes[0].close_observed, true);
  assert.equal(snapshot.raw_output_retained, false);
  assert.equal(JSON.stringify(snapshot).includes(secret), false);
  assert.equal(normalizeManagedHostOutput(snapshot).processes.length, 1);
});

test("managed host output writer emits only bounded structured counters", () => {
  mkdirSync(TEST_ROOT, { recursive: true });
  const directory = mkdtempSync(join(TEST_ROOT, "host-output-"));
  try {
    const collector = new ManagedHostOutputCollector({ maxStreamBytes: 32, maxProcessRecords: 2 });
    const child = fakeChild(66);
    attachManagedHostOutputCapture(child, collector);
    child.stdout.emit("data", Buffer.from("authorization=do-not-retain"));
    child.emit("close", 0, null);
    const summary = writeManagedHostOutputEvidence(collector.snapshot(), directory);
    const artifact = readFileSync(join(directory, "managed-host-output.json"), "utf8");
    assert.equal(summary.artifact, "managed-host-output.json");
    assert.equal(summary.raw_output_retained, false);
    assert.equal(artifact.includes("authorization=do-not-retain"), false);
    assert.match(artifact, /"bytes_observed": 27/);
    assert.equal(normalizeManagedHostOutput({
      ...collector.snapshot(),
      total_process_starts: 8,
    }), null);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("host evidence normalization rejects malformed process counters and excess records", () => {
  const collector = new ManagedHostOutputCollector();
  const handle = collector.beginProcess(77);
  handle.capture("stdout", Buffer.from("secret"));
  handle.finish(0, null);
  const snapshot = collector.snapshot();
  assert.equal(normalizeManagedHostOutput({ ...snapshot, raw_output_retained: true }), null);
  assert.equal(normalizeManagedHostOutput({
    ...snapshot,
    processes: [{ ...snapshot.processes[0], stdout: { bytes_observed: 65_537, truncated: true } }],
  }), null);
  assert.equal(normalizeManagedHostOutput({
    ...snapshot,
    processes: [snapshot.processes[0], snapshot.processes[0]],
  }), null);
  assert.equal(normalizeManagedHostOutput({
    ...snapshot,
    processes: undefined,
  }), null);
  assert.equal(normalizeManagedHostOutput({
    ...snapshot,
    total_process_starts: 1_000_001,
    omitted_process_records: 1_000_000,
  }), null);
});
