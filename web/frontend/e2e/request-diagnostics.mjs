// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

const REQUEST_DIAGNOSTIC_SCHEMA = "n2-socket-request.v1";
export const MAX_REQUEST_DIAGNOSTIC_RECORDS = 128;
export const MAX_REQUEST_DIAGNOSTIC_BYTES = 32_768;
const CONTEXTS = new Set([
  "player-a-chrome",
  "player-b-firefox",
  "host-ui-chrome-context",
]);
const METHODS = new Set(["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]);
const TRANSPORTS = new Set(["polling", "websocket", "unknown"]);
const FAILURE_CATEGORIES = new Set([
  "aborted",
  "connection_refused",
  "dns_failure",
  "timeout",
  "request_failed",
]);
const DIAGNOSTIC_KEYS = [
  "schema",
  "event_type",
  "context",
  "method",
  "path",
  "status",
  "transport",
  "origin_present",
  "origin_matches_expected",
  "host_matches_expected",
  "session_cookie_present",
  "failure_category",
  "recorded_at_utc",
].sort();

export function normalizeSocketRequestDiagnostic(value) {
  if (!isRecord(value) || !sameKeys(Object.keys(value).sort(), DIAGNOSTIC_KEYS) ||
      value.schema !== REQUEST_DIAGNOSTIC_SCHEMA ||
      !["response", "requestfailed", "websocket"].includes(value.event_type) ||
      !CONTEXTS.has(value.context) ||
      !(METHODS.has(value.method) || value.method === "OTHER" || value.method === "unknown") ||
      value.path !== "/socket.io/" ||
      !(value.status === "unknown" || (Number.isInteger(value.status) && value.status >= 100 && value.status <= 599)) ||
      !TRANSPORTS.has(value.transport) ||
      !isObservedBoolean(value.origin_present) ||
      !isObservedBoolean(value.origin_matches_expected) ||
      !isObservedBoolean(value.host_matches_expected) ||
      !isObservedBoolean(value.session_cookie_present) ||
      !(value.failure_category === null || FAILURE_CATEGORIES.has(value.failure_category)) ||
      typeof value.recorded_at_utc !== "string" || !Number.isFinite(Date.parse(value.recorded_at_utc))) {
    return null;
  }
  return {
    schema: REQUEST_DIAGNOSTIC_SCHEMA,
    event_type: value.event_type,
    context: value.context,
    method: value.method,
    path: "/socket.io/",
    status: value.status,
    transport: value.transport,
    origin_present: value.origin_present,
    origin_matches_expected: value.origin_matches_expected,
    host_matches_expected: value.host_matches_expected,
    session_cookie_present: value.session_cookie_present,
    failure_category: value.failure_category,
    recorded_at_utc: value.recorded_at_utc.slice(0, 40),
  };
}

export class SocketRequestDiagnosticsCollector {
  constructor(expectedOrigin, {
    maxRecords = MAX_REQUEST_DIAGNOSTIC_RECORDS,
    maxBytes = MAX_REQUEST_DIAGNOSTIC_BYTES,
  } = {}) {
    const parsed = new URL(expectedOrigin);
    if (parsed.origin !== "http://127.0.0.1:8370" || parsed.pathname !== "/" ||
        parsed.username || parsed.password || parsed.search || parsed.hash) {
      throw new Error("Socket request diagnostic origin is invalid.");
    }
    this.expectedOrigin = parsed.origin;
    this.expectedHost = parsed.host.toLowerCase();
    this.maxRecords = boundedInteger(maxRecords, 1, MAX_REQUEST_DIAGNOSTIC_RECORDS);
    this.maxBytes = boundedInteger(maxBytes, 1, MAX_REQUEST_DIAGNOSTIC_BYTES);
    this.records = [];
    this.pending = new Set();
    this.recordsTotal = 0;
    this.bytesTotal = 0;
    this.omittedCount = 0;
    this.writeErrorCount = 0;
    this.flushedCount = 0;
  }

  attach(page, context) {
    if (!CONTEXTS.has(context) || !page || typeof page.on !== "function") {
      throw new TypeError("Socket request diagnostics require an approved page context.");
    }
    const safeContext = context;
    page.on("response", (response) => this.track(() => this.recordResponse(response, safeContext)));
    page.on("requestfailed", (request) => this.track(() => this.recordRequestFailed(request, safeContext)));
    page.on("websocket", (socket) => {
      try {
        this.add(this.createRecord({
          eventType: "websocket",
          context: safeContext,
          url: socket.url(),
          method: "unknown",
          status: "unknown",
          failureCategory: null,
          headers: null,
        }));
      } catch {
        this.omittedCount = incrementCounter(this.omittedCount);
      }
    });
  }

  async flush(writeRecord) {
    await Promise.all([...this.pending]);
    const pendingRecords = this.records.splice(0);
    for (const record of pendingRecords) {
      try {
        await writeRecord(record);
        this.flushedCount += 1;
      } catch {
        this.writeErrorCount += 1;
      }
    }
    return this.summary();
  }

  summary() {
    return {
      schema: REQUEST_DIAGNOSTIC_SCHEMA,
      artifact: this.flushedCount > 0 ? "request-diagnostics.jsonl" : null,
      records_written: this.flushedCount,
      records_omitted: this.omittedCount,
      record_write_failures: this.writeErrorCount,
      truncated: this.omittedCount > 0,
      raw_headers_retained: false,
      raw_urls_retained: false,
    };
  }

  track(operation) {
    if (this.pending.size >= this.maxRecords) {
      this.omittedCount = incrementCounter(this.omittedCount);
      return;
    }
    let pending;
    pending = Promise.resolve()
      .then(operation)
      .catch(() => { this.omittedCount = incrementCounter(this.omittedCount); })
      .finally(() => this.pending.delete(pending));
    this.pending.add(pending);
  }

  async recordResponse(response, context) {
    try {
      const request = response.request();
      const headers = await observeHeaders(request);
      this.add(this.createRecord({
        eventType: "response",
        context,
        url: request.url(),
        method: request.method(),
        status: response.status(),
        failureCategory: null,
        headers,
      }));
    } catch {
      this.omittedCount = incrementCounter(this.omittedCount);
    }
  }

  async recordRequestFailed(request, context) {
    try {
      const headers = await observeHeaders(request);
      this.add(this.createRecord({
        eventType: "requestfailed",
        context,
        url: request.url(),
        method: request.method(),
        status: "unknown",
        failureCategory: classifyFailure(request),
        headers,
      }));
    } catch {
      this.omittedCount = incrementCounter(this.omittedCount);
    }
  }

  createRecord({ eventType, context, url, method, status, failureCategory, headers }) {
    const parsed = new URL(url);
    const requestOrigin = socketRequestOrigin(parsed);
    if (parsed.username || parsed.password || requestOrigin !== this.expectedOrigin || parsed.pathname !== "/socket.io/") {
      return null;
    }
    const transportValue = parsed.searchParams.get("transport");
    const transport = transportValue === "polling" || transportValue === "websocket"
      ? transportValue
      : eventType === "websocket"
        ? "websocket"
        : "unknown";
    const observable = headers !== null && typeof headers === "object";
    const headerOrigin = observable ? safeHeader(headers, "origin") : null;
    const headerHost = observable ? safeHeader(headers, "host") : null;
    const cookie = observable ? safeHeader(headers, "cookie") : null;
    const safeMethod = typeof method === "string" && METHODS.has(method.toUpperCase())
      ? method.toUpperCase()
      : method === "unknown"
        ? "unknown"
        : "OTHER";
    const normalizedStatus = Number.isInteger(status) && status >= 100 && status <= 599 ? status : "unknown";
    return normalizeSocketRequestDiagnostic({
      schema: REQUEST_DIAGNOSTIC_SCHEMA,
      event_type: eventType,
      context,
      method: safeMethod,
      path: "/socket.io/",
      status: normalizedStatus,
      transport,
      origin_present: observable ? headerOrigin !== null : "unknown",
      origin_matches_expected: observable ? headerOrigin === this.expectedOrigin : "unknown",
      host_matches_expected: observable ? headerHost?.toLowerCase() === this.expectedHost : "unknown",
      session_cookie_present: observable ? hasSessionCookie(cookie) : "unknown",
      failure_category: failureCategory,
      recorded_at_utc: new Date().toISOString(),
    });
  }

  add(record) {
    if (record === null) return;
    const normalized = normalizeSocketRequestDiagnostic(record);
    if (normalized === null) {
      this.omittedCount = incrementCounter(this.omittedCount);
      return;
    }
    const bytes = Buffer.byteLength(JSON.stringify(normalized), "utf8") + 1;
    if (this.recordsTotal >= this.maxRecords || this.bytesTotal + bytes > this.maxBytes) {
      this.omittedCount = incrementCounter(this.omittedCount);
      return;
    }
    this.records.push(normalized);
    this.recordsTotal += 1;
    this.bytesTotal += bytes;
  }
}

async function observeHeaders(request) {
  if (typeof request.allHeaders !== "function") return null;
  try {
    const headers = await request.allHeaders();
    return isRecord(headers) ? headers : null;
  } catch {
    return null;
  }
}

function classifyFailure(request) {
  let text = "";
  try {
    const failure = request.failure();
    text = typeof failure?.errorText === "string" ? failure.errorText.toLowerCase() : "";
  } catch {
    return "request_failed";
  }
  if (text.includes("timed out") || text.includes("timeout")) return "timeout";
  if (text.includes("connection refused")) return "connection_refused";
  if (text.includes("dns") || text.includes("name_not_resolved")) return "dns_failure";
  if (text.includes("aborted")) return "aborted";
  return "request_failed";
}

function safeHeader(headers, key) {
  const match = Object.keys(headers).find((name) => name.toLowerCase() === key);
  const value = match === undefined ? null : headers[match];
  return typeof value === "string" ? value : null;
}

function socketRequestOrigin(parsed) {
  if (parsed.protocol === "ws:") return `http://${parsed.host}`;
  if (parsed.protocol === "wss:") return `https://${parsed.host}`;
  return parsed.origin;
}

function hasSessionCookie(value) {
  return typeof value === "string" && /(?:^|;\s*)neq_player_session\s*=/i.test(value);
}

function boundedInteger(value, minimum, maximum) {
  return Number.isInteger(value) ? Math.min(maximum, Math.max(minimum, value)) : maximum;
}

function incrementCounter(value) {
  return Math.min(1_000_000, value + 1);
}

function isObservedBoolean(value) {
  return typeof value === "boolean" || value === "unknown";
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function sameKeys(actual, expected) {
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}
