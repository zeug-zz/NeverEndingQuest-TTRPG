// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Socket } from "socket.io-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { PlayerSnapshot } from "./player-protocol";

const mocks = vi.hoisted(() => ({ io: vi.fn() }));

vi.mock("socket.io-client", () => ({ io: mocks.io }));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const CLIENT_VERSION = {
  clientBuildId: "0123456789abcdef0123456789abcdef",
  protocolVersion: 1 as const,
};
const PRELOGIN_NONCE = "N".repeat(43);
const SESSION_CSRF = "S".repeat(43);

type SocketHandler = (...args: unknown[]) => void;

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function makeSnapshot(
  transcript: PlayerSnapshot["projection"]["transcript"] = {
    available: true,
    messages: [],
  },
): PlayerSnapshot {
  return {
    schema_version: 1,
    instance_id: "I".repeat(32),
    session_epoch: "E".repeat(32),
    revision: 4,
    event_cursor: 0,
    projection: {
      party: {
        members: [{ name: "Acheron" }, { name: "Merisiel" }],
        active_character: "Acheron",
        active_character_revision: 3,
        world: {},
      },
      transcript,
      combat: {
        available: true,
        active: false,
        round: null,
        phase: null,
        turn_order: [],
      },
      busy: false,
    },
  };
}

function jsonResponse(status: number, payload: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response;
}

function makeSocketHarness() {
  const handlers = new Map<string, Set<SocketHandler>>();
  const socket = {
    connected: false,
    on: vi.fn((event: string, handler: SocketHandler) => {
      const eventHandlers = handlers.get(event) ?? new Set<SocketHandler>();
      eventHandlers.add(handler);
      handlers.set(event, eventHandlers);
      return socket;
    }),
    off: vi.fn((event: string, handler?: SocketHandler) => {
      if (handler === undefined) handlers.delete(event);
      else handlers.get(event)?.delete(handler);
      return socket;
    }),
    emit: vi.fn(),
    connect: vi.fn(() => {
      socket.connected = true;
      return socket;
    }),
    disconnect: vi.fn(() => {
      socket.connected = false;
      return socket;
    }),
  };

  return {
    socket: socket as unknown as Socket,
    fire(event: string, ...args: unknown[]) {
      for (const handler of handlers.get(event) ?? []) handler(...args);
    },
  };
}

function renderApp(fetcher: typeof fetch, socketHarness = makeSocketHarness()) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  mocks.io.mockReturnValue(socketHarness.socket);
  act(() => {
    root?.render(
      <App
        clientVersion={CLIENT_VERSION}
        preloginCsrfToken={PRELOGIN_NONCE}
        fetcher={fetcher}
      />,
    );
  });
  return socketHarness;
}

async function submitLogin(password = "never-persist-this") {
  const form = container?.querySelector("form");
  const input = container?.querySelector<HTMLInputElement>('input[name="password"]');
  if (form === null || form === undefined || input === null || input === undefined) {
    throw new Error("login form is not rendered");
  }
  input.value = password;
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    for (let step = 0; step < 12; step += 1) await Promise.resolve();
  });
}

afterEach(() => {
  if (root !== undefined) {
    act(() => root?.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
});

beforeEach(() => {
  vi.clearAllMocks();
});

describe("player login and session bootstrap", () => {
  it("submits login, hydrates a versioned snapshot, and connects to the player namespace", async () => {
    const snapshot = makeSnapshot({
      available: true,
      messages: [
        {
          id: `transcript-${"a".repeat(32)}`,
          sequence: 1,
          role: "assistant",
          text: "Welcome to the table.",
        },
      ],
    });
    const responses = [
      jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }),
      jsonResponse(200, snapshot),
    ];
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
      return responses.shift() ?? jsonResponse(500, { error: "unexpected_request" });
    });
    const socket = makeSocketHarness();
    renderApp(fetcher, socket);
    const passwordInput = container?.querySelector<HTMLInputElement>('input[name="password"]');

    await submitLogin();

    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0]?.[0]).toBe("/api/player/login");
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    });
    expect(JSON.parse(String(fetcher.mock.calls[0]?.[1]?.body))).toEqual({
      password: "never-persist-this",
      csrf_token: PRELOGIN_NONCE,
    });
    expect(passwordInput?.value).toBe("");

    expect(fetcher.mock.calls[1]?.[0]).toBe("/api/player/snapshot");
    expect(fetcher.mock.calls[1]?.[1]).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: {
        "X-NEQ-Client-Build": CLIENT_VERSION.clientBuildId,
        "X-NEQ-Protocol-Version": "1",
      },
    });
    expect(container?.textContent).toContain("Acheron");
    expect(container?.textContent).toContain("Merisiel");
    expect(container?.textContent).toContain("Active PC: Acheron");
    expect(container?.textContent).toContain("Transcript: 1 messages");
    expect(mocks.io).toHaveBeenCalledWith(
      "/player",
      expect.objectContaining({
        path: "/socket.io",
        withCredentials: true,
        autoConnect: false,
        auth: {
          client_build_id: CLIENT_VERSION.clientBuildId,
          protocol_version: 1,
        },
      }),
    );
    expect(socket.socket.connect).toHaveBeenCalledTimes(1);
  });

  it("shows a user-visible bounded message for CSRF, rate-limit, and invalid credentials", async () => {
    const cases = [
      [403, { error: "csrf_rejected" }, "login form expired"],
      [429, { error: "rate_limited" }, "Too many login attempts"],
      [401, { error: "invalid_credentials" }, "password was not accepted"],
    ] as const;

    for (const [status, payload, message] of cases) {
      const fetcher = vi.fn(async () => jsonResponse(status, payload));
      renderApp(fetcher);
      await submitLogin();
      expect(container?.textContent?.toLowerCase()).toContain(message.toLowerCase());
      expect(container?.querySelector<HTMLInputElement>('input[name="password"]')?.value).toBe("");
      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(mocks.io).not.toHaveBeenCalled();
      act(() => root?.unmount());
      root = undefined;
      container?.remove();
      container = undefined;
      vi.clearAllMocks();
    }
  });

  it("requests an authoritative snapshot after socket reconnect and exposes disconnect state", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }))
      .mockResolvedValueOnce(jsonResponse(200, makeSnapshot()));
    const socket = makeSocketHarness();
    renderApp(fetcher, socket);
    await submitLogin();

    act(() => socket.fire("connect"));
    expect(container?.textContent).toContain("Connected");
    expect(socket.socket.emit).toHaveBeenCalledWith("player.snapshot.request", {
      schema_version: 1,
      instance_id: "I".repeat(32),
      session_epoch: "E".repeat(32),
    });

    act(() => socket.fire("disconnect", "transport close"));
    expect(container?.textContent).toContain("Disconnected");
    const reconnect = [...(container?.querySelectorAll("button") ?? [])].find(
      (button) => button.textContent === "Reconnect",
    );
    expect(reconnect).toBeDefined();
    act(() => reconnect?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(socket.socket.connect).toHaveBeenCalledTimes(2);
    act(() => socket.fire("connect"));
    expect(socket.socket.emit).toHaveBeenCalledTimes(2);
  });

  it("requires reload on HTTP or socket client-version mismatch without retrying the socket", async () => {
    const httpFetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }))
      .mockResolvedValueOnce(jsonResponse(409, { error: "client_version_mismatch" }));
    renderApp(httpFetcher);
    await submitLogin();
    expect(document.body.textContent).toContain("Reload required");
    expect(container?.textContent).toContain("out of date");
    expect(mocks.io).not.toHaveBeenCalled();

    act(() => root?.unmount());
    root = undefined;
    container?.remove();
    container = undefined;
    vi.clearAllMocks();

    const socketFetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }))
      .mockResolvedValueOnce(jsonResponse(200, makeSnapshot()));
    const socket = makeSocketHarness();
    renderApp(socketFetcher, socket);
    await submitLogin();
    act(() => socket.fire("connect_error", new Error("client_version_mismatch")));
    expect(document.body.textContent).toContain("Reload required");
    expect(socket.socket.disconnect).toHaveBeenCalled();
    expect(socket.socket.connect).toHaveBeenCalledTimes(1);
  });

  it("renders an explicit empty-transcript message and logs out through the player route", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }))
      .mockResolvedValueOnce(jsonResponse(200, makeSnapshot()))
      .mockResolvedValueOnce(jsonResponse(204, null));
    renderApp(fetcher);
    await submitLogin();
    expect(container?.textContent).toContain("No transcript yet.");

    const logout = [...(container?.querySelectorAll("button") ?? [])].find(
      (button) => button.textContent === "Log out",
    );
    await act(async () => {
      logout?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      for (let step = 0; step < 8; step += 1) await Promise.resolve();
    });
    expect(fetcher.mock.calls[2]?.[0]).toBe("/api/player/logout");
    expect(JSON.parse(String(fetcher.mock.calls[2]?.[1]?.body))).toEqual({ csrf_token: SESSION_CSRF });
    expect(container?.textContent).toContain("You are logged out");
    expect(container?.textContent).toContain("Reload the page to sign in again");
  });
});
