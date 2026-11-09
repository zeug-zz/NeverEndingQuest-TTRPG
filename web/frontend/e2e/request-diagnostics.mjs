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
    this.pendingWebsocketCount = 0;
    this.pendingWebsocketBytes = 0;
    this.cdpStates = new Set();
    this.cdpSetupPromises = [];
  }

  attach(page, context) {
    if (!CONTEXTS.has(context) || !page || typeof page.on !== "function") {
      throw new TypeError("Socket request diagnostics require an approved page context.");
    }
    const safeContext = context;
    page.on("response", (response) => this.track(() => this.recordResponse(response, safeContext)));
    page.on("requestfailed", (request) => this.track(() => this.recordRequestFailed(request, safeContext)));
    const cdpState = this.createCdpState(page, safeContext);
    page.on("websocket", (socket) => {
      try {
        const record = this.createRecord({
          eventType: "websocket",
          context: safeContext,
          url: socket.url(),
          method: "unknown",
          status: "unknown",
          failureCategory: null,
          headers: null,
        });
        if (record === null) return;
        if (cdpState === null || cdpState.status === "failed") {
          this.add(record);
        } else if (cdpState.status === "pending") {
          this.reserveWebsocketFallback(cdpState, record);
        }
      } catch {
        this.omittedCount = incrementCounter(this.omittedCount);
      }
    });
  }

  async whenReady() {
    await Promise.all(this.cdpSetupPromises);
  }

  async detach() {
    await this.whenReady();
    this.flushPendingWebsocketRecords();
    let success = true;
    for (const state of this.cdpStates) {
      if (state.session === null) continue;
      try {
        await state.session.detach();
      } catch {
        success = false;
      }
      state.session = null;
      state.status = "detached";
    }
    return success;
  }

  async flush(writeRecord) {
    await this.whenReady();
    this.flushPendingWebsocketRecords();
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

  createCdpState(page, context) {
    if (context !== "player-a-chrome" || typeof page.context !== "function") return null;
    if (this.cdpStates.size >= this.maxRecords) return null;
    let browserContext;
    try {
      browserContext = page.context();
    } catch {
      return null;
    }
    if (typeof browserContext?.newCDPSession !== "function") return null;

    const state = {
      context,
      status: "pending",
      session: null,
      pending: new Map(),
      fallbacks: [],
    };
    this.cdpStates.add(state);
    const setup = Promise.resolve().then(async () => {
      const session = await browserContext.newCDPSession(page);
      state.session = session;
      session.on("Network.webSocketCreated", (event) => {
        this.recordCdpWebsocketCreated(state, event);
      });
      session.on("Network.webSocketWillSendHandshakeRequest", (event) => {
        this.recordCdpWebsocketHandshakeRequest(state, event);
      });
      session.on("Network.webSocketHandshakeResponseReceived", (event) => {
        this.recordCdpWebsocketResponse(state, event);
      });
      await session.send("Network.enable");
      state.status = "ready";
      this.releaseWebsocketFallbacks(state, false);
    }).catch(() => {
      state.status = "failed";
      this.releaseWebsocketFallbacks(state, true);
    });
    this.cdpSetupPromises.push(setup);
    return state;
  }

  reserveWebsocketFallback(state, record) {
    if (this.recordsTotal + this.pendingWebsocketCount >= this.maxRecords) {
      this.omittedCount = incrementCounter(this.omittedCount);
      return;
    }
    const bytes = Buffer.byteLength(JSON.stringify(record), "utf8") + 1;
    if (this.bytesTotal + this.pendingWebsocketBytes + bytes > this.maxBytes) {
      this.omittedCount = incrementCounter(this.omittedCount);
      return;
    }
    state.fallbacks.push(record);
    this.pendingWebsocketCount += 1;
    this.pendingWebsocketBytes += bytes;
  }

  releaseWebsocketFallbacks(state, emit) {
    for (const record of state.fallbacks) {
      this.pendingWebsocketCount = Math.max(0, this.pendingWebsocketCount - 1);
      this.pendingWebsocketBytes = Math.max(
        0,
        this.pendingWebsocketBytes - Buffer.byteLength(JSON.stringify(record), "utf8") - 1,
      );
      if (emit) this.add(record);
    }
    state.fallbacks = [];
  }

  recordCdpWebsocketCreated(state, event) {
    try {
      if (!isApprovedWebsocketUrl(event?.url, this.expectedOrigin)) return;
      const requestId = boundedCdpRequestId(event?.requestId);
      if (requestId === null) {
        this.omittedCount = incrementCounter(this.omittedCount);
        return;
      }
      if (state.pending.has(requestId)) return;
      if (state.pending.size >= this.maxRecords ||
          this.recordsTotal + this.pendingWebsocketCount >= this.maxRecords) {
        this.omittedCount = incrementCounter(this.omittedCount);
        return;
      }
      const record = createCdpWebsocketPlaceholder(state.context);
      const bytes = Buffer.byteLength(JSON.stringify(record), "utf8") + 1 +
        Buffer.byteLength(requestId, "utf8");
      if (this.bytesTotal + this.pendingWebsocketBytes + bytes > this.maxBytes) {
        this.omittedCount = incrementCounter(this.omittedCount);
        return;
      }
      state.pending.set(requestId, { record, bytes, handshakeStarted: false });
      this.pendingWebsocketCount += 1;
      this.pendingWebsocketBytes += bytes;
    } catch {
      this.omittedCount = incrementCounter(this.omittedCount);
    }
  }

  recordCdpWebsocketHandshakeRequest(state, event) {
    try {
      const requestId = boundedCdpRequestId(event?.requestId);
      if (requestId === null) return;
      const pending = state.pending.get(requestId);
      if (pending === undefined) return;

      pending.handshakeStarted = true;
      const headers = event?.request?.headers;
      pending.record = applyCdpWebsocketHeaders(
        { ...pending.record, method: "GET" },
        headers,
        this.expectedOrigin,
        this.expectedHost,
      );
    } catch {
      this.omittedCount = incrementCounter(this.omittedCount);
    }
  }

  recordCdpWebsocketResponse(state, event) {
    const requestId = boundedCdpRequestId(event?.requestId);
    if (requestId === null) return;
    const pending = state.pending.get(requestId);
    if (pending === undefined || !pending.handshakeStarted) return;
    state.pending.delete(requestId);
    this.pendingWebsocketCount = Math.max(0, this.pendingWebsocketCount - 1);
    this.pendingWebsocketBytes = Math.max(0, this.pendingWebsocketBytes - pending.bytes);
    const responseStatus = event?.response?.status;
    this.add({
      ...pending.record,
      status: Number.isInteger(responseStatus) && responseStatus >= 100 && responseStatus <= 599
        ? responseStatus
        : "unknown",
    });
  }

  flushPendingWebsocketRecords() {
    for (const state of this.cdpStates) {
      for (const [requestId, pending] of state.pending) {
        state.pending.delete(requestId);
        this.pendingWebsocketCount = Math.max(0, this.pendingWebsocketCount - 1);
        this.pendingWebsocketBytes = Math.max(0, this.pendingWebsocketBytes - pending.bytes);
        this.add(pending.record);
      }
    }
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

function createCdpWebsocketPlaceholder(context) {
  return normalizeSocketRequestDiagnostic({
    schema: REQUEST_DIAGNOSTIC_SCHEMA,
    event_type: "websocket",
    context,
    method: "unknown",
    path: "/socket.io/",
    status: "unknown",
    transport: "websocket",
    origin_present: "unknown",
    origin_matches_expected: "unknown",
    host_matches_expected: "unknown",
    session_cookie_present: "unknown",
    failure_category: null,
    recorded_at_utc: new Date().toISOString(),
  });
}

function applyCdpWebsocketHeaders(record, headers, expectedOrigin, expectedHost) {
  if (!isRecord(headers)) return record;
  const headerOrigin = safeHeader(headers, "origin");
  const headerHost = safeHeader(headers, "host");
  const cookie = safeHeader(headers, "cookie");
  return {
    ...record,
    origin_present: headerOrigin !== null,
    origin_matches_expected: headerOrigin === expectedOrigin,
    host_matches_expected: headerHost?.toLowerCase() === expectedHost,
    session_cookie_present: hasSessionCookie(cookie),
  };
}

function isApprovedWebsocketUrl(value, expectedOrigin) {
  if (typeof value !== "string") return false;
  try {
    const parsed = new URL(value);
    return !parsed.username && !parsed.password && !parsed.hash &&
      socketRequestOrigin(parsed) === expectedOrigin && parsed.pathname === "/socket.io/";
  } catch {
    return false;
  }
}

function boundedCdpRequestId(value) {
  if (typeof value !== "string" || value.length === 0 ||
      Buffer.byteLength(value, "utf8") > 128) {
    return null;
  }
  return value;
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
