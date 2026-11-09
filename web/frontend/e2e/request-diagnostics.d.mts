// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export type SocketRequestDiagnostic = Readonly<{
  schema: "n2-socket-request.v1";
  event_type: "response" | "requestfailed" | "websocket";
  context: "player-a-chrome" | "player-b-firefox" | "host-ui-chrome-context";
  method: string;
  path: "/socket.io/";
  status: number | "unknown";
  transport: "polling" | "websocket" | "unknown";
  origin_present: boolean | "unknown";
  origin_matches_expected: boolean | "unknown";
  host_matches_expected: boolean | "unknown";
  session_cookie_present: boolean | "unknown";
  failure_category: string | null;
  recorded_at_utc: string;
}>;

export function normalizeSocketRequestDiagnostic(value: unknown): SocketRequestDiagnostic | null;
export const MAX_REQUEST_DIAGNOSTIC_RECORDS: number;
export const MAX_REQUEST_DIAGNOSTIC_BYTES: number;

export class SocketRequestDiagnosticsCollector {
  constructor(expectedOrigin: string, options?: { maxRecords?: number; maxBytes?: number });
  attach(page: import("playwright").Page, context: string): void;
  flush(writeRecord: (record: SocketRequestDiagnostic) => Promise<void> | void): Promise<{
    schema: string;
    artifact: string | null;
    records_written: number;
    records_omitted: number;
    record_write_failures: number;
    truncated: boolean;
    raw_headers_retained: false;
    raw_urls_retained: false;
  }>;
  summary(): Record<string, unknown>;
}
