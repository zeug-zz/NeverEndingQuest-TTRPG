// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { spawn } from "node:child_process";
import { renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { StringDecoder } from "node:string_decoder";

export const PLAYWRIGHT_DRIVER_OUTPUT_ARTIFACT = "driver-output.json";
export const MAX_DRIVER_OUTPUT_BYTES_PER_STREAM = 2 * 1024 * 1024;
export const MAX_DRIVER_OUTPUT_ARTIFACT_BYTES = 4096;

const SAFE_SIGNALS = new Set([
  "SIGHUP",
  "SIGINT",
  "SIGQUIT",
  "SIGILL",
  "SIGTRAP",
  "SIGABRT",
  "SIGBUS",
  "SIGFPE",
  "SIGKILL",
  "SIGUSR1",
  "SIGSEGV",
  "SIGUSR2",
  "SIGPIPE",
  "SIGALRM",
  "SIGTERM",
]);
const SPAWN_CATEGORIES = new Set(["not_started", "spawn_error"]);

export class PlaywrightDriverOutputCollector {
  constructor({ maxBytesPerStream = MAX_DRIVER_OUTPUT_BYTES_PER_STREAM } = {}) {
    this.maxBytesPerStream = boundedInteger(maxBytesPerStream, 1, MAX_DRIVER_OUTPUT_BYTES_PER_STREAM);
    this.stdout = createStreamCount();
    this.stderr = createStreamCount();
    this.exitStatus = null;
    this.exitSignal = "unknown";
    this.spawnCategory = "not_started";
  }

  markSpawned() {
    this.spawnCategory = null;
  }

  capture(stream, chunk) {
    if (stream !== "stdout" && stream !== "stderr") return;
    const counter = this[stream];
    const next = counter.bytes_observed + chunkByteLength(chunk);
    if (next > this.maxBytesPerStream) {
      counter.bytes_observed = this.maxBytesPerStream;
      counter.truncated = true;
    } else {
      counter.bytes_observed = next;
    }
  }

  finish(status, signal, spawnError = false) {
    this.exitStatus = Number.isInteger(status) && status >= 0 && status <= 255 ? status : null;
    this.exitSignal = typeof signal === "string" && SAFE_SIGNALS.has(signal) ? signal : "unknown";
    this.spawnCategory = spawnError ? "spawn_error" : null;
  }

  snapshot() {
    return normalizePlaywrightDriverOutput({
      schema: "n2-playwright-driver-output.v1",
      retention_policy: "counters-only; raw Playwright stdout and stderr are discarded from evidence",
      raw_output_retained: false,
      max_bytes_per_stream: this.maxBytesPerStream,
      stdout: { ...this.stdout },
      stderr: { ...this.stderr },
      exit_status: this.exitStatus,
      exit_signal: this.exitSignal,
      spawn_category: this.spawnCategory,
    });
  }
}

export function createUnstartedPlaywrightDriverOutput() {
  return new PlaywrightDriverOutputCollector().snapshot();
}

export function createPlaywrightSpawnFailureOutput() {
  const collector = new PlaywrightDriverOutputCollector();
  collector.finish(null, null, true);
  return collector.snapshot();
}

export function normalizePlaywrightDriverOutput(value) {
  const expectedKeys = [
    "schema",
    "retention_policy",
    "raw_output_retained",
    "max_bytes_per_stream",
    "stdout",
    "stderr",
    "exit_status",
    "exit_signal",
    "spawn_category",
  ].sort();
  if (!isRecord(value) || !sameKeys(Object.keys(value).sort(), expectedKeys) ||
      value.schema !== "n2-playwright-driver-output.v1" ||
      value.retention_policy !== "counters-only; raw Playwright stdout and stderr are discarded from evidence" ||
      value.raw_output_retained !== false ||
      !Number.isInteger(value.max_bytes_per_stream) || value.max_bytes_per_stream < 1 ||
      value.max_bytes_per_stream > MAX_DRIVER_OUTPUT_BYTES_PER_STREAM ||
      !isStreamCount(value.stdout, value.max_bytes_per_stream) ||
      !isStreamCount(value.stderr, value.max_bytes_per_stream) ||
      !(value.exit_status === null || (Number.isInteger(value.exit_status) && value.exit_status >= 0 && value.exit_status <= 255)) ||
      !(value.exit_signal === "unknown" || SAFE_SIGNALS.has(value.exit_signal)) ||
      !(value.spawn_category === null || SPAWN_CATEGORIES.has(value.spawn_category))) {
    return null;
  }
  return {
    schema: "n2-playwright-driver-output.v1",
    retention_policy: "counters-only; raw Playwright stdout and stderr are discarded from evidence",
    raw_output_retained: false,
    max_bytes_per_stream: value.max_bytes_per_stream,
    stdout: { bytes_observed: value.stdout.bytes_observed, truncated: value.stdout.truncated },
    stderr: { bytes_observed: value.stderr.bytes_observed, truncated: value.stderr.truncated },
    exit_status: value.exit_status,
    exit_signal: value.exit_signal,
    spawn_category: value.spawn_category,
  };
}

export function writePlaywrightDriverOutputEvidence(snapshot, evidenceDirectory) {
  const safe = normalizePlaywrightDriverOutput(snapshot);
  if (safe === null) throw new Error("Playwright driver output evidence is invalid.");
  const serialized = `${JSON.stringify(safe, null, 2)}\n`;
  if (Buffer.byteLength(serialized, "utf8") > MAX_DRIVER_OUTPUT_ARTIFACT_BYTES) {
    throw new Error("Playwright driver output evidence exceeds its fixed size limit.");
  }
  const path = join(evidenceDirectory, PLAYWRIGHT_DRIVER_OUTPUT_ARTIFACT);
  const pendingPath = `${path}.pending`;
  writeFileSync(pendingPath, serialized, { encoding: "utf8", flag: "wx" });
  renameSync(pendingPath, path);
  return {
    artifact: PLAYWRIGHT_DRIVER_OUTPUT_ARTIFACT,
    raw_output_retained: false,
    stdout: { ...safe.stdout },
    stderr: { ...safe.stderr },
    exit_status: safe.exit_status,
    exit_signal: safe.exit_signal,
    spawn_category: safe.spawn_category,
  };
}

export function runPlaywrightProcess(playwrightPath, args, environment, {
  cwd = process.cwd(),
  spawnProcess = spawn,
  onSpawn = () => {},
  onClose = () => {},
} = {}) {
  return new Promise((resolveRun) => {
    const collector = new PlaywrightDriverOutputCollector();
    let runner;
    try {
      runner = spawnProcess(playwrightPath, args, {
        cwd,
        env: environment,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch {
      collector.finish(null, null, true);
      resolveRun({
        status: null,
        signal: null,
        error: true,
        stdout: "",
        stderr: "",
        driverOutput: collector.snapshot(),
      });
      return;
    }

    collector.markSpawned();
    onSpawn(runner);
    let stdout = "";
    let stderr = "";
    let spawnError = null;
    const stdoutDecoder = new StringDecoder("utf8");
    const stderrDecoder = new StringDecoder("utf8");
    const maxTerminalBuffer = MAX_DRIVER_OUTPUT_BYTES_PER_STREAM;
    const collectTerminalText = (current, text) => `${current}${text}`.slice(-maxTerminalBuffer);
    runner.stdout?.on("data", (chunk) => {
      collector.capture("stdout", chunk);
      stdout = collectTerminalText(stdout, stdoutDecoder.write(chunk));
    });
    runner.stderr?.on("data", (chunk) => {
      collector.capture("stderr", chunk);
      stderr = collectTerminalText(stderr, stderrDecoder.write(chunk));
    });
    runner.once("error", () => { spawnError = true; });
    runner.once("close", (status, signal) => {
      stdout = collectTerminalText(stdout, stdoutDecoder.end());
      stderr = collectTerminalText(stderr, stderrDecoder.end());
      if (spawnError) collector.finish(status, signal, true);
      else collector.finish(status, signal);
      onClose(runner);
      resolveRun({
        status,
        signal,
        error: spawnError,
        stdout,
        stderr,
        driverOutput: collector.snapshot(),
      });
    });
  });
}

function createStreamCount() {
  return { bytes_observed: 0, truncated: false };
}

function isStreamCount(value, maximum) {
  return isRecord(value) && Number.isInteger(value.bytes_observed) &&
    value.bytes_observed >= 0 && value.bytes_observed <= maximum &&
    typeof value.truncated === "boolean";
}

function chunkByteLength(chunk) {
  if (Buffer.isBuffer(chunk)) return chunk.byteLength;
  if (typeof chunk === "string") return Buffer.byteLength(chunk, "utf8");
  if (ArrayBuffer.isView(chunk)) return chunk.byteLength;
  if (chunk instanceof ArrayBuffer) return chunk.byteLength;
  return 0;
}

function boundedInteger(value, minimum, maximum) {
  return Number.isInteger(value) ? Math.min(maximum, Math.max(minimum, value)) : maximum;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sameKeys(actual, expected) {
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}
