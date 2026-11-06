// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Socket } from "socket.io-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { PlayerMember, PlayerReceipt, PlayerSnapshot } from "./player-protocol";

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
  options: Readonly<{
    members?: readonly PlayerMember[];
    activeCharacter?: string | null;
    activeRevision?: number;
    busy?: boolean;
    includeBusy?: boolean;
    combat?: NonNullable<PlayerSnapshot["projection"]["combat"]>;
  }> = {},
): PlayerSnapshot {
  const members = options.members ?? [makeMember("Acheron"), makeMember("Merisiel")];
  const activeCharacter = options.activeCharacter === undefined
    ? members[0]?.name ?? null
    : options.activeCharacter;
  const projection: PlayerSnapshot["projection"] = {
    party: {
      members,
      active_character: activeCharacter,
      active_character_revision: options.activeRevision ?? 3,
      world: {},
    },
    transcript,
    combat: options.combat ?? {
      available: true,
      active: true,
      round: 2,
      phase: "PC_PHASE",
      turn_order: [
        { name: "Acheron", kind: "pc", initiative: 18, status: "alive" },
        { name: "Merisiel", kind: "pc", initiative: 11, status: "alive" },
        { name: "Goblin", kind: "monster", initiative: 7, status: "alive" },
      ],
    },
    ...(options.includeBusy === false ? {} : { busy: options.busy ?? false }),
  };
  return {
    schema_version: 1,
    instance_id: "I".repeat(32),
    session_epoch: "E".repeat(32),
    revision: 4,
    event_cursor: 0,
    projection,
  };
}

function makeMember(name: string, overrides: Partial<PlayerMember> = {}): PlayerMember {
  return {
    name,
    level: 4,
    race: "Human",
    class: "Ranger",
    hitPoints: 24,
    maxHitPoints: 30,
    armorClass: 16,
    abilities: { strength: 12, dexterity: 16 },
    portrait_media_id: `pc-${name.toLowerCase()}`,
    ...overrides,
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
    emit: socket.emit,
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

async function hydrateGameplay(
  snapshot = makeSnapshot(),
  socket = makeSocketHarness(),
) {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(jsonResponse(200, { csrf_token: SESSION_CSRF, expires_at: 1000 }))
    .mockResolvedValueOnce(jsonResponse(200, snapshot));
  renderApp(fetcher, socket);
  await submitLogin();
  act(() => socket.fire("connect"));
  return socket;
}

function changeGameplayInput(value: string): void {
  const textarea = container?.querySelector<HTMLTextAreaElement>("#gameplay-input");
  if (textarea === null || textarea === undefined) throw new Error("gameplay input is not rendered");
  const setter = Object.getOwnPropertyDescriptor(
    HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  act(() => {
    setter?.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function submitGameplayInput(): void {
  const form = container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.form;
  if (form === null || form === undefined) throw new Error("gameplay input form is not rendered");
  act(() => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

function inputCommand(socket: ReturnType<typeof makeSocketHarness>) {
  const call = socket.emit.mock.calls.find(([event]) => event === "player.input.submit");
  if (call === undefined) throw new Error("player input was not emitted");
  return call[1] as {
    request_id: string;
    character_name: string;
    active_character_revision: number;
    text: string;
  };
}

function makeReceipt(
  requestId: string,
  status: PlayerReceipt["status"],
  code?: string,
): PlayerReceipt {
  return {
    schema_version: 1,
    instance_id: "I".repeat(32),
    session_epoch: "E".repeat(32),
    request_id: requestId,
    status,
    ...(code === undefined ? {} : { code }),
  };
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
    expect(container?.textContent).toContain("Welcome to the table.");
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

describe("player gameplay projection and interactions", () => {
  it.each([
    {
      label: "1-PC",
      members: [makeMember("Acheron")],
      activeCharacter: "Acheron",
      order: ["Acheron", "Goblin"],
    },
    {
      label: "4-PC",
      members: [
        makeMember("Acheron"),
        makeMember("Merisiel"),
        makeMember("Taldor"),
        makeMember("Selene"),
      ],
      activeCharacter: "Merisiel",
      order: ["Acheron", "Merisiel", "Taldor", "Selene", "Goblin"],
    },
  ])("renders $label selector, selected read-only sheet, portrait, and initiative order", async ({
    members,
    activeCharacter,
    order,
  }) => {
    const turnOrder = order.map((name, index) => ({
      name,
      kind: name === "Goblin" ? "monster" as const : "pc" as const,
      initiative: 20 - index,
      status: "alive" as const,
    }));
    const snapshot = makeSnapshot(undefined, {
      members,
      activeCharacter,
      combat: {
        available: true,
        active: true,
        round: 1,
        phase: "PC_PHASE",
        turn_order: turnOrder,
      },
    });
    await hydrateGameplay(snapshot);

    const selector = container?.querySelector<HTMLSelectElement>("#active-pc");
    expect([...((selector?.options ?? []) as HTMLOptionsCollection)].map((option) => option.value))
      .toEqual(members.map((member) => member.name));
    expect(selector?.value).toBe(activeCharacter);
    expect(container?.querySelector("article[aria-label*='read-only sheet']")?.getAttribute("aria-label"))
      .toBe(`${activeCharacter} read-only sheet`);
    expect(container?.textContent).toContain("Ranger");
    expect(container?.querySelector("img")?.getAttribute("src"))
      .toBe(`/api/player/media/pc-${activeCharacter.toLowerCase()}`);
    expect([...((container?.querySelectorAll("[data-combatant]") ?? []) as NodeListOf<HTMLElement>)]
      .map((item) => item.getAttribute("data-combatant")))
      .toEqual(order);
  });

  it("emits active-PC selection with the observed revision and resynchronizes stale errors", async () => {
    const socket = await hydrateGameplay(makeSnapshot());
    const selector = container?.querySelector<HTMLSelectElement>("#active-pc");
    if (selector === null || selector === undefined) throw new Error("active-PC selector is missing");
    act(() => {
      selector.value = "Merisiel";
      selector.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(socket.emit).toHaveBeenCalledWith("player.active_pc.select", {
      schema_version: 1,
      instance_id: "I".repeat(32),
      session_epoch: "E".repeat(32),
      character_name: "Merisiel",
      expected_revision: 3,
    });

    act(() => socket.fire("player.error", { schema_version: 1, code: "stale_context" }));
    expect(socket.emit).toHaveBeenCalledWith("player.snapshot.request", {
      schema_version: 1,
      instance_id: "I".repeat(32),
      session_epoch: "E".repeat(32),
    });
    expect(container?.textContent).toContain("selection was stale");
  });

  it.each([
    ["accepted", "Input accepted for queue admission", true],
    ["busy", "The game is busy", false],
    ["stale", "Input rejected as stale", false],
    ["rejected", "Input rejected (runtime_admission_rejected)", false],
    ["uncertain", "The action may or may not have applied", false],
    ["duplicate", "This request was already received", false],
  ] as const)("shows the %s receipt distinctly", async (status, message, clearsText) => {
    const socket = await hydrateGameplay(makeSnapshot());
    changeGameplayInput("I look around.");
    submitGameplayInput();
    const command = inputCommand(socket);
    expect(command.request_id).toMatch(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
    expect(command.character_name).toBe("Acheron");
    expect(command.active_character_revision).toBe(3);
    expect(command.text).toBe("I look around.");

    act(() => socket.fire(
      "player.input.receipt",
      makeReceipt(command.request_id, status, status === "rejected" ? "runtime_admission_rejected" : undefined),
    ));
    expect(container?.textContent).toContain(message);
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.value)
      .toBe(clearsText ? "" : "I look around.");
    if (status === "stale" || status === "uncertain") {
      expect(socket.emit).toHaveBeenCalledWith("player.snapshot.request", {
        schema_version: 1,
        instance_id: "I".repeat(32),
        session_epoch: "E".repeat(32),
      });
    }
  });

  it("ignores receipts for unknown request IDs and keeps one submission in flight", async () => {
    const socket = await hydrateGameplay(makeSnapshot());
    changeGameplayInput("Check the door.");
    submitGameplayInput();
    const command = inputCommand(socket);
    expect(container?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);

    act(() => socket.fire("player.input.receipt", makeReceipt("unknown-request", "accepted")));
    expect(container?.textContent).toContain("Sending input for Acheron at revision 3");
    expect(container?.textContent).not.toContain("Input accepted for queue admission");
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.value)
      .toBe("Check the door.");
    expect(command.request_id).not.toBe("unknown-request");
  });

  it("marks a disconnected pending input uncertain and never resubmits it", async () => {
    const socket = await hydrateGameplay(makeSnapshot());
    changeGameplayInput("Talk to the guard.");
    submitGameplayInput();
    const inputEmitsBeforeDisconnect = socket.emit.mock.calls
      .filter(([event]) => event === "player.input.submit").length;
    expect(inputEmitsBeforeDisconnect).toBe(1);

    act(() => socket.fire("disconnect", "transport close"));
    expect(container?.textContent).toContain("The action may or may not have applied");
    expect(container?.textContent).toContain("it will not be resubmitted");
    act(() => socket.fire("connect"));
    expect(socket.emit.mock.calls.filter(([event]) => event === "player.input.submit")).toHaveLength(1);

    act(() => socket.fire("player.snapshot", makeSnapshot()));
    expect(container?.textContent).toContain("The connection ended while this input was pending");
    expect(socket.emit.mock.calls.filter(([event]) => event === "player.input.submit")).toHaveLength(1);
  });

  it("disables input while the server projection is busy", async () => {
    await hydrateGameplay(makeSnapshot(undefined, { busy: true }));
    expect(container?.textContent).toContain("The game is busy");
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.disabled).toBe(true);
    expect(container?.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true);
  });

  it("requires confirmation when the active PC changes while composing", async () => {
    const initial = makeSnapshot();
    const socket = await hydrateGameplay(initial);
    changeGameplayInput("I open the chest.");
    const refreshed = makeSnapshot(undefined, {
      members: initial.projection.party.members,
      activeCharacter: "Merisiel",
      activeRevision: 4,
    });
    act(() => socket.fire("player.event", {
      schema_version: 1,
      instance_id: "I".repeat(32),
      session_epoch: "E".repeat(32),
      event_id: 1,
      revision: 5,
      type: "projection.updated",
      projection: refreshed.projection,
    }));
    expect(container?.textContent).toContain("changed while you were composing");
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.disabled).toBe(true);

    const confirm = [...(container?.querySelectorAll("button") ?? [])]
      .find((button) => button.textContent?.includes("Confirm refreshed state"));
    act(() => confirm?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.disabled).toBe(false);
    submitGameplayInput();
    const command = inputCommand(socket);
    expect(command.character_name).toBe("Merisiel");
    expect(command.active_character_revision).toBe(4);
  });

  it("renders markup-like transcript and input content only as text", async () => {
    const hostileText = '<script>alert("x")</script>\n<a href="javascript:alert(1)">open</a>';
    await hydrateGameplay(makeSnapshot({
      available: true,
      messages: [{
        id: `transcript-${"a".repeat(32)}`,
        sequence: 1,
        role: "assistant",
        text: hostileText,
      }],
    }));
    changeGameplayInput('<a href="javascript:alert(2)">input</a>');
    expect(container?.querySelector("script")).toBeNull();
    expect(container?.querySelector("a")).toBeNull();
    expect(container?.textContent).toContain(hostileText);
    expect(container?.querySelector<HTMLTextAreaElement>("#gameplay-input")?.value)
      .toBe('<a href="javascript:alert(2)">input</a>');
  });

  it("shows neutral unavailable states for transcript, combat, and busy projections", async () => {
    await hydrateGameplay(makeSnapshot(
      { available: false, messages: [] },
      {
        includeBusy: false,
        combat: {
          available: false,
          active: true,
          round: null,
          phase: null,
          turn_order: [],
        },
      },
    ));
    expect(container?.textContent).toContain("Transcript unavailable.");
    expect(container?.textContent).toContain("Combat information unavailable.");
    expect(container?.textContent).toContain("Busy status unavailable.");
  });
});
