// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";
import {
  MAX_REQUEST_DIAGNOSTIC_BYTES,
  normalizeSocketRequestDiagnostic,
  SocketRequestDiagnosticsCollector,
} from "./request-diagnostics.mjs";

const ORIGIN = "http://127.0.0.1:8370";
const SECRET = "request-secret-never-retain";

function makePage() {
  const page = new EventEmitter();
  return page;
}

function makeCdpPage(session) {
  const page = makePage();
  page.context = () => ({ newCDPSession: async () => session });
  return page;
}

test("diagnostics retain only exact Socket.IO path, bounded metadata, and safe header booleans", async () => {
  const page = makePage();
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN);
  collector.attach(page, "player-a-chrome");
  const request = {
    url: () => `${ORIGIN}/socket.io/?EIO=4&transport=polling&sid=${SECRET}`,
    method: () => "GET",
    allHeaders: async () => ({
      Origin: ORIGIN,
      Host: "127.0.0.1:8370",
      Cookie: `neq_player_session=${SECRET}`,
      Authorization: `Bearer ${SECRET}`,
      "X-Private": SECRET,
    }),
  };
  page.emit("response", { request: () => request, status: () => 200 });
  page.emit("response", { request: () => ({ ...request, url: () => `${ORIGIN}/api/player/snapshot` }), status: () => 200 });
  page.emit("response", { request: () => ({ ...request, url: () => `http://127.0.0.1:8360/socket.io/?transport=polling` }), status: () => 200 });

  const written = [];
  const summary = await collector.flush((record) => written.push(record));
  assert.equal(written.length, 1);
  assert.equal(written[0].path, "/socket.io/");
  assert.equal(written[0].transport, "polling");
  assert.equal(written[0].status, 200);
  assert.equal(written[0].origin_present, true);
  assert.equal(written[0].origin_matches_expected, true);
  assert.equal(written[0].host_matches_expected, true);
  assert.equal(written[0].session_cookie_present, true);
  assert.equal(summary.raw_headers_retained, false);
  assert.equal(summary.raw_urls_retained, false);
  const serialized = JSON.stringify({ summary, written });
  for (const value of [SECRET, "Authorization", "X-Private", "sid="]) {
    assert.equal(serialized.includes(value), false, `request evidence retained ${value}`);
  }
});

test("unobservable headers stay unknown and failure details collapse to an allowlisted category", async () => {
  const page = makePage();
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN);
  collector.attach(page, "player-b-firefox");
  const request = {
    url: () => `${ORIGIN}/socket.io/?transport=websocket&token=${SECRET}`,
    method: () => "GET",
    allHeaders: async () => { throw new Error(SECRET); },
    failure: () => ({ errorText: `Request timed out ${SECRET}` }),
  };
  page.emit("requestfailed", request);
  page.emit("websocket", { url: () => `ws://127.0.0.1:8370/socket.io/?transport=websocket&sid=${SECRET}` });

  const written = [];
  await collector.flush((record) => written.push(record));
  assert.equal(written.length, 2);
  const failed = written.find((item) => item.event_type === "requestfailed");
  assert.equal(failed.failure_category, "timeout");
  assert.equal(failed.status, "unknown");
  assert.equal(failed.origin_present, "unknown");
  assert.equal(failed.origin_matches_expected, "unknown");
  assert.equal(failed.host_matches_expected, "unknown");
  assert.equal(failed.session_cookie_present, "unknown");
  const websocket = written.find((item) => item.event_type === "websocket");
  assert.equal(websocket.transport, "websocket");
  assert.equal(websocket.origin_present, "unknown");
  const serialized = JSON.stringify(written);
  assert.equal(serialized.includes(SECRET), false);
  assert.equal(serialized.includes("Request timed out"), false);
});

test("CDP correlates the real WebSocket created, handshake-request, and response events", async () => {
  const session = new EventEmitter();
  const commands = [];
  let detached = false;
  session.send = async (method) => { commands.push(method); };
  session.detach = async () => { detached = true; };
  const page = makeCdpPage(session);
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN, { maxRecords: 1 });
  collector.attach(page, "player-a-chrome");
  await collector.whenReady();

  const privateValues = [
    "private-websocket-query",
    "private-cdp-request-id",
    "private-websocket-cookie",
    "private-websocket-authorization",
  ];
  const targetRequestId = privateValues[1];
  session.emit("Network.webSocketCreated", {
    requestId: targetRequestId,
    url: `ws://127.0.0.1:8370/socket.io/?EIO=4&transport=websocket&sid=${privateValues[0]}`,
    initiator: { type: "script", url: `http://127.0.0.1:8370/?private=${privateValues[0]}` },
  });
  session.emit("Network.webSocketCreated", {
    requestId: "second-private-request-id",
    url: "ws://127.0.0.1:8370/socket.io/?EIO=4&transport=websocket",
    initiator: { type: "script" },
  });
  const actualHandshakeRequest = {
    headers: {
      Origin: ORIGIN,
      Host: "127.0.0.1:8370",
      Cookie: `neq_player_session=${privateValues[2]}`,
      Authorization: `Bearer ${privateValues[3]}`,
    },
  };
  assert.deepEqual(Object.keys(actualHandshakeRequest), ["headers"]);
  session.emit("Network.webSocketWillSendHandshakeRequest", {
    requestId: targetRequestId,
    timestamp: 1,
    wallTime: 1,
    request: actualHandshakeRequest,
  });
  session.emit("Network.webSocketWillSendHandshakeRequest", {
    requestId: "second-private-request-id",
    timestamp: 2,
    wallTime: 2,
    request: { headers: { Origin: "http://attacker.invalid", Host: "attacker.invalid" } },
  });
  session.emit("Network.webSocketHandshakeResponseReceived", {
    requestId: targetRequestId,
    timestamp: 3,
    response: { status: 101, statusText: "Switching Protocols", headers: {} },
  });
  session.emit("Network.webSocketHandshakeResponseReceived", {
    requestId: "second-private-request-id",
    timestamp: 4,
    response: { status: 101, statusText: "Switching Protocols", headers: {} },
  });

  const written = [];
  const summary = await collector.flush((record) => written.push(record));
  assert.deepEqual(commands, ["Network.enable"]);
  assert.equal(await collector.detach(), true);
  assert.equal(detached, true);
  assert.equal(written.length, 1);
  assert.equal(written[0].event_type, "websocket");
  assert.equal(written[0].transport, "websocket");
  assert.equal(written[0].method, "GET");
  assert.equal(written[0].status, 101);
  assert.equal(written[0].origin_present, true);
  assert.equal(written[0].origin_matches_expected, true);
  assert.equal(written[0].host_matches_expected, true);
  assert.equal(written[0].session_cookie_present, true);
  assert.equal(summary.records_omitted, 1);
  assert.equal(summary.truncated, true);
  const serialized = JSON.stringify({ summary, written });
  for (const value of [...privateValues, "second-private-request-id", "Authorization", "Switching Protocols"]) {
    assert.equal(serialized.includes(value), false, `diagnostics retained ${value}`);
  }
});

test("CDP ignores stale, foreign-origin/path, and oversized-ID events and flushes unanswered metadata as unknown", async () => {
  const session = new EventEmitter();
  session.send = async () => {};
  session.detach = async () => {};
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN);
  collector.attach(makeCdpPage(session), "player-a-chrome");
  await collector.whenReady();

  const attackerHeaders = {
    Origin: ORIGIN,
    Host: "127.0.0.1:8370",
    Cookie: "neq_player_session=must-not-be-attributed",
  };
  session.emit("Network.webSocketWillSendHandshakeRequest", {
    requestId: "stale-cdp-request-id",
    request: { headers: attackerHeaders },
  });
  session.emit("Network.webSocketHandshakeResponseReceived", {
    requestId: "stale-cdp-request-id",
    response: { status: 101, headers: {} },
  });

  for (const [requestId, url] of [
    ["foreign-origin-id", "ws://127.0.0.1:8371/socket.io/?sid=foreign-origin-secret"],
    ["foreign-path-id", "ws://127.0.0.1:8370/private/socket.io/?sid=foreign-path-secret"],
  ]) {
    session.emit("Network.webSocketCreated", { requestId, url, initiator: { type: "script" } });
    session.emit("Network.webSocketWillSendHandshakeRequest", {
      requestId,
      request: { headers: attackerHeaders },
    });
    session.emit("Network.webSocketHandshakeResponseReceived", {
      requestId,
      response: { status: 101, headers: {} },
    });
  }

  session.emit("Network.webSocketCreated", {
    requestId: "r".repeat(129),
    url: "ws://127.0.0.1:8370/socket.io/?sid=oversized-id-secret",
  });
  session.emit("Network.webSocketWillSendHandshakeRequest", {
    requestId: "r".repeat(129),
    request: { headers: attackerHeaders },
  });

  session.emit("Network.webSocketCreated", {
    requestId: "approved-but-unanswered-id",
    url: "ws://127.0.0.1:8370/socket.io/?sid=approved-query-secret",
  });
  session.emit("Network.webSocketHandshakeResponseReceived", {
    requestId: "approved-but-unanswered-id",
    response: { status: 101, headers: {} },
  });
  session.emit("Network.webSocketWillSendHandshakeRequest", {
    requestId: "approved-but-unanswered-id",
    request: {},
  });

  const written = [];
  const summary = await collector.flush((record) => written.push(record));
  assert.equal(written.length, 1);
  assert.equal(written[0].method, "GET");
  assert.equal(written[0].status, "unknown");
  assert.equal(written[0].origin_present, "unknown");
  assert.equal(written[0].origin_matches_expected, "unknown");
  assert.equal(written[0].host_matches_expected, "unknown");
  assert.equal(written[0].session_cookie_present, "unknown");
  assert.equal(summary.records_omitted, 1);
  const serialized = JSON.stringify({ summary, written });
  for (const value of [
    "stale-cdp-request-id",
    "foreign-origin-id",
    "foreign-path-id",
    "oversized-id-secret",
    "approved-query-secret",
    "must-not-be-attributed",
  ]) {
    assert.equal(serialized.includes(value), false, `diagnostics retained ${value}`);
  }
});

test("diagnostic schema rejects raw URL, header, cookie, and unknown fields", () => {
  const safe = {
    schema: "n2-socket-request.v1",
    event_type: "response",
    context: "player-a-chrome",
    method: "GET",
    path: "/socket.io/",
    status: 200,
    transport: "polling",
    origin_present: true,
    origin_matches_expected: true,
    host_matches_expected: true,
    session_cookie_present: true,
    failure_category: null,
    recorded_at_utc: "2026-11-09T12:00:00.000Z",
  };
  assert.deepEqual(normalizeSocketRequestDiagnostic(safe), safe);
  assert.equal(normalizeSocketRequestDiagnostic({ ...safe, url: `${ORIGIN}/socket.io/?sid=${SECRET}` }), null);
  assert.equal(normalizeSocketRequestDiagnostic({ ...safe, cookie: SECRET }), null);
  assert.equal(normalizeSocketRequestDiagnostic({ ...safe, path: "/socket.io/?sid=private" }), null);
  assert.equal(normalizeSocketRequestDiagnostic({ ...safe, status: "500 secret" }), null);
});

test("diagnostic collector bounds pending events, record count, and bytes", async () => {
  const page = makePage();
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN, { maxRecords: 1, maxBytes: 16_384 });
  collector.attach(page, "player-a-chrome");
  const request = {
    url: () => `${ORIGIN}/socket.io/?transport=polling`,
    method: () => "GET",
    allHeaders: async () => ({}),
  };
  for (let index = 0; index < 10; index += 1) {
    page.emit("response", { request: () => request, status: () => 200 });
  }
  const written = [];
  const summary = await collector.flush((record) => written.push(record));
  assert.equal(written.length, 1);
  assert.equal(summary.records_omitted, 9);
  assert.equal(summary.truncated, true);
  assert.ok(Buffer.byteLength(JSON.stringify(written), "utf8") < 16_384);
});

test("record limit is total for the run across repeated flushes", async () => {
  const page = makePage();
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN, { maxRecords: 2 });
  collector.attach(page, "player-a-chrome");
  const request = {
    url: () => `${ORIGIN}/socket.io/?transport=polling`,
    method: () => "GET",
    allHeaders: async () => ({}),
  };
  const written = [];

  page.emit("response", { request: () => request, status: () => 200 });
  await collector.flush((record) => written.push(record));
  for (let index = 0; index < 2; index += 1) {
    page.emit("response", { request: () => request, status: () => 200 });
  }
  const afterSecondFlush = await collector.flush((record) => written.push(record));
  page.emit("response", { request: () => request, status: () => 200 });
  const finalSummary = await collector.flush((record) => written.push(record));

  assert.equal(written.length, 2);
  assert.equal(afterSecondFlush.records_written, 2);
  assert.equal(finalSummary.records_written, 2);
  assert.equal(finalSummary.records_omitted, 2);
  assert.equal(finalSummary.truncated, true);
});

test("serialized byte limit is total for the run across repeated flushes", async () => {
  const request = {
    url: () => `${ORIGIN}/socket.io/?transport=polling`,
    method: () => "GET",
    allHeaders: async () => ({}),
  };
  const samplePage = makePage();
  const sampleCollector = new SocketRequestDiagnosticsCollector(ORIGIN);
  sampleCollector.attach(samplePage, "player-a-chrome");
  let sampleRecord;
  samplePage.emit("response", { request: () => request, status: () => 200 });
  await sampleCollector.flush((record) => { sampleRecord = record; });
  const recordBytes = Buffer.byteLength(JSON.stringify(sampleRecord), "utf8") + 1;

  const page = makePage();
  const maxBytes = recordBytes * 2;
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN, { maxBytes });
  collector.attach(page, "player-a-chrome");
  const written = [];
  const emit = () => page.emit("response", { request: () => request, status: () => 200 });

  emit();
  await collector.flush((record) => written.push(record));
  emit();
  emit();
  const afterSecondFlush = await collector.flush((record) => written.push(record));
  emit();
  const finalSummary = await collector.flush((record) => written.push(record));
  const serializedBytes = written.reduce(
    (total, record) => total + Buffer.byteLength(JSON.stringify(record), "utf8") + 1,
    0,
  );

  assert.equal(written.length, 2);
  assert.equal(afterSecondFlush.records_written, 2);
  assert.equal(finalSummary.records_written, 2);
  assert.equal(finalSummary.records_omitted, 2);
  assert.equal(serializedBytes, maxBytes);
  assert.ok(serializedBytes <= MAX_REQUEST_DIAGNOSTIC_BYTES);
});

test("collector accepts only a fixed loopback HTTP origin", () => {
  for (const origin of [
    "https://127.0.0.1:8370",
    "http://user:password@127.0.0.1:8370",
    "http://127.0.0.1:8370/path",
    "http://127.0.0.1:8370/?token=secret",
  ]) {
    assert.throws(() => new SocketRequestDiagnosticsCollector(origin));
  }
});

test("collector rejects an unapproved page context rather than mislabeling it", () => {
  const collector = new SocketRequestDiagnosticsCollector(ORIGIN);
  assert.throws(() => collector.attach(makePage(), "untrusted-context"), /approved page context/);
});
