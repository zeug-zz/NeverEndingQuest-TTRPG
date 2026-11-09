// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const MANAGED_HOST_OUTPUT_ARTIFACT = "managed-host-output.json";
export const MAX_HOST_OUTPUT_BYTES_PER_STREAM = 65_536;
export const MAX_HOST_PROCESS_RECORDS = 32;
export const MAX_HOST_OUTPUT_ARTIFACT_BYTES = 32_768;

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

export class ManagedHostOutputCollector {
  constructor({ maxStreamBytes = MAX_HOST_OUTPUT_BYTES_PER_STREAM, maxProcessRecords = MAX_HOST_PROCESS_RECORDS } = {}) {
    this.maxStreamBytes = boundedInteger(maxStreamBytes, 1, MAX_HOST_OUTPUT_BYTES_PER_STREAM);
    this.maxProcessRecords = boundedInteger(maxProcessRecords, 1, MAX_HOST_PROCESS_RECORDS);
    this.totalProcessStarts = 0;
    this.omittedProcessRecords = 0;
    this.processes = [];
  }

  beginProcess(pid) {
    this.totalProcessStarts = Math.min(1_000_000, this.totalProcessStarts + 1);
    const record = {
      process_index: this.totalProcessStarts,
      pid: Number.isSafeInteger(pid) && pid > 0 ? pid : null,
      stdout: createStreamCount(),
      stderr: createStreamCount(),
      exit_status: null,
      exit_signal: "unknown",
      close_observed: false,
    };
    const retained = this.processes.length < this.maxProcessRecords;
    if (retained) this.processes.push(record);
    else this.omittedProcessRecords = Math.min(1_000_000, this.omittedProcessRecords + 1);

    return {
      capture: (stream, chunk) => {
        if (stream !== "stdout" && stream !== "stderr") return;
        const streamRecord = record[stream];
        const byteLength = chunkByteLength(chunk);
        const next = streamRecord.bytes_observed + byteLength;
        if (next > this.maxStreamBytes) {
          streamRecord.bytes_observed = this.maxStreamBytes;
          streamRecord.truncated = true;
        } else {
          streamRecord.bytes_observed = next;
        }
      },
      finish: (status, signal) => {
        record.exit_status = Number.isInteger(status) && status >= 0 ? status : null;
        record.exit_signal = typeof signal === "string" && SAFE_SIGNALS.has(signal) ? signal : "unknown";
        record.close_observed = true;
      },
    };
  }

  snapshot() {
    return {
      schema: "n2-managed-host-output.v1",
      retention_policy: "counters-only; raw host stdout and stderr are discarded immediately",
      raw_output_retained: false,
      max_stream_bytes_per_process: this.maxStreamBytes,
      max_process_records: this.maxProcessRecords,
      total_process_starts: this.totalProcessStarts,
      omitted_process_records: this.omittedProcessRecords,
      process_records_truncated: this.omittedProcessRecords > 0,
      processes: this.processes.map((record) => ({
        process_index: record.process_index,
        pid: record.pid,
        stdout: { ...record.stdout },
        stderr: { ...record.stderr },
        exit_status: record.exit_status,
        exit_signal: record.exit_signal,
        close_observed: record.close_observed,
      })),
    };
  }
}

export function attachManagedHostOutputCapture(child, collector) {
  if (!(collector instanceof ManagedHostOutputCollector) || !child || typeof child.once !== "function") {
    throw new TypeError("Managed host output capture requires an owned child and collector.");
  }
  const capture = collector.beginProcess(child.pid);
  child.stdout?.on("data", (chunk) => capture.capture("stdout", chunk));
  child.stderr?.on("data", (chunk) => capture.capture("stderr", chunk));
  child.once("close", (status, signal) => capture.finish(status, signal));
  return capture;
}

export function normalizeManagedHostOutput(value) {
  if (!isRecord(value) || value.schema !== "n2-managed-host-output.v1" ||
      value.retention_policy !== "counters-only; raw host stdout and stderr are discarded immediately" ||
      value.raw_output_retained !== false ||
      !Number.isInteger(value.max_stream_bytes_per_process) || value.max_stream_bytes_per_process < 1 ||
      value.max_stream_bytes_per_process > MAX_HOST_OUTPUT_BYTES_PER_STREAM ||
      !Number.isInteger(value.max_process_records) || value.max_process_records < 1 ||
      value.max_process_records > MAX_HOST_PROCESS_RECORDS ||
      !Number.isInteger(value.total_process_starts) || value.total_process_starts < 0 ||
      value.total_process_starts > 1_000_000 ||
      !Number.isInteger(value.omitted_process_records) || value.omitted_process_records < 0 ||
      value.omitted_process_records > 1_000_000 ||
      !Array.isArray(value.processes) ||
      value.total_process_starts !== value.processes.length + value.omitted_process_records ||
      value.process_records_truncated !== (value.omitted_process_records > 0) ||
      value.processes.length > value.max_process_records) {
    return null;
  }

  const processes = [];
  const seen = new Set();
  for (const record of value.processes) {
    if (!isRecord(record) || !Number.isInteger(record.process_index) || record.process_index < 1 ||
        record.process_index > value.total_process_starts || seen.has(record.process_index) ||
        !(record.pid === null || (Number.isSafeInteger(record.pid) && record.pid > 0)) ||
        !isStreamCount(record.stdout, value.max_stream_bytes_per_process) ||
        !isStreamCount(record.stderr, value.max_stream_bytes_per_process) ||
        !(record.exit_status === null || (Number.isInteger(record.exit_status) && record.exit_status >= 0)) ||
        !(record.exit_signal === "unknown" || SAFE_SIGNALS.has(record.exit_signal)) ||
        typeof record.close_observed !== "boolean") {
      return null;
    }
    seen.add(record.process_index);
    processes.push({
      process_index: record.process_index,
      pid: record.pid,
      stdout: { bytes_observed: record.stdout.bytes_observed, truncated: record.stdout.truncated },
      stderr: { bytes_observed: record.stderr.bytes_observed, truncated: record.stderr.truncated },
      exit_status: record.exit_status,
      exit_signal: record.exit_signal,
      close_observed: record.close_observed,
    });
  }
  return {
    schema: "n2-managed-host-output.v1",
    retention_policy: "counters-only; raw host stdout and stderr are discarded immediately",
    raw_output_retained: false,
    max_stream_bytes_per_process: value.max_stream_bytes_per_process,
    max_process_records: value.max_process_records,
    total_process_starts: value.total_process_starts,
    omitted_process_records: value.omitted_process_records,
    process_records_truncated: value.process_records_truncated,
    processes,
  };
}

export function writeManagedHostOutputEvidence(snapshot, evidenceDirectory) {
  const safe = normalizeManagedHostOutput(snapshot);
  if (safe === null) throw new Error("Managed host output evidence is invalid.");
  const serialized = `${JSON.stringify(safe, null, 2)}\n`;
  if (Buffer.byteLength(serialized, "utf8") > MAX_HOST_OUTPUT_ARTIFACT_BYTES) {
    throw new Error("Managed host output evidence exceeds its fixed size limit.");
  }
  const path = join(evidenceDirectory, MANAGED_HOST_OUTPUT_ARTIFACT);
  const pendingPath = `${path}.pending`;
  writeFileSync(pendingPath, serialized, { encoding: "utf8", flag: "wx" });
  renameSync(pendingPath, path);
  return {
    artifact: MANAGED_HOST_OUTPUT_ARTIFACT,
    total_process_starts: safe.total_process_starts,
    process_records_written: safe.processes.length,
    omitted_process_records: safe.omitted_process_records,
    raw_output_retained: false,
  };
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
