// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { io, type Socket } from "socket.io-client";
import type { PlayerClientVersion } from "./client-version";
import {
  isPlayerSnapshot,
  type PlayerSnapshot,
  type PlayerSnapshotRequest,
} from "./player-protocol";
import { PlayerStore } from "./player-store";

type PlayerAppProps = Readonly<{
  clientVersion: PlayerClientVersion;
  preloginCsrfToken: string;
  fetcher?: typeof fetch;
}>;

type SessionGrant = Readonly<{ csrf_token: string; expires_at: number }>;

const PRELOGIN_NONCE_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
const SESSION_CSRF_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;

export function App({
  clientVersion,
  preloginCsrfToken,
  fetcher,
}: PlayerAppProps) {
  const store = useMemo(() => new PlayerStore(), []);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  const socketRef = useRef<Socket | null>(null);
  const [loginAttempted, setLoginAttempted] = useState(false);
  const [loginMessage, setLoginMessage] = useState<string | null>(null);
  const readyForSocket = state.sessionCsrfToken !== null && state.snapshot !== null;

  useEffect(() => {
    if (!readyForSocket || state.status === "reload-required") return;
    const socket = io("/player", {
      path: "/socket.io",
      withCredentials: true,
      autoConnect: false,
      reconnection: true,
      auth: {
        client_build_id: clientVersion.clientBuildId,
        protocol_version: clientVersion.protocolVersion,
      },
    });
    socketRef.current = socket;

    const onConnect = (): void => store.markConnected();
    const onDisconnect = (): void => store.markDisconnected();
    const onConnectError = (error: Error): void => {
      if (isVersionMismatch(error)) {
        store.requireReload();
        socket.disconnect();
      } else {
        store.markDisconnected("Connection failed. Reconnecting will resynchronize player state.");
      }
    };
    const onSnapshot = (payload: unknown): void => {
      store.acceptSnapshot(payload);
    };
    const onEvent = (payload: unknown): void => {
      store.acceptEvent(payload);
    };
    const onReceipt = (payload: unknown): void => {
      store.acceptReceipt(payload);
    };
    const onError = (payload: unknown): void => {
      store.acceptError(payload);
    };

    socket.on("connect", onConnect);
    socket.on("disconnect", onDisconnect);
    socket.on("connect_error", onConnectError);
    socket.on("player.snapshot", onSnapshot);
    socket.on("player.event", onEvent);
    socket.on("player.input.receipt", onReceipt);
    socket.on("player.error", onError);
    store.setSnapshotRequester((request: PlayerSnapshotRequest) => {
      if (socket.connected) socket.emit("player.snapshot.request", request);
    });
    store.setStatus("connecting");
    socket.connect();

    return () => {
      store.setSnapshotRequester(null);
      socket.off("connect", onConnect);
      socket.off("disconnect", onDisconnect);
      socket.off("connect_error", onConnectError);
      socket.off("player.snapshot", onSnapshot);
      socket.off("player.event", onEvent);
      socket.off("player.input.receipt", onReceipt);
      socket.off("player.error", onError);
      socket.disconnect();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [clientVersion.clientBuildId, clientVersion.protocolVersion, readyForSocket, store]);

  async function handleLogin(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (loginAttempted) return;
    setLoginAttempted(true);
    setLoginMessage(null);

    const form = event.currentTarget;
    const fields = new FormData(form);
    const password = fields.get("password");
    const csrfToken = fields.get("csrf_token");
    form.reset();

    if (
      typeof password !== "string" ||
      password.length === 0 ||
      typeof csrfToken !== "string" ||
      !PRELOGIN_NONCE_PATTERN.test(csrfToken)
    ) {
      setLoginMessage("The login form is invalid or expired. Reload the page to try again.");
      return;
    }

    store.beginAuthentication();
    try {
      const loginResponse = await request(fetcher, "/api/player/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password, csrf_token: csrfToken }),
      });
      if (loginResponse.status !== 200) {
        const code = await responseErrorCode(loginResponse);
        setLoginMessage(loginErrorMessage(code, loginResponse.status));
        store.setStatus("logged-out");
        return;
      }

      const grant = await readSessionGrant(loginResponse);
      if (grant === null) {
        store.requireReload("The login response was invalid. Reload this page to continue.");
        return;
      }
      store.beginHydration(grant.csrf_token);

      const snapshotResponse = await request(fetcher, "/api/player/snapshot", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "X-NEQ-Client-Build": clientVersion.clientBuildId,
          "X-NEQ-Protocol-Version": String(clientVersion.protocolVersion),
        },
      });
      if (snapshotResponse.status === 409) {
        store.requireReload();
        return;
      }
      if (!snapshotResponse.ok) {
        const code = await responseErrorCode(snapshotResponse);
        store.requireReload(snapshotErrorMessage(code, snapshotResponse.status));
        return;
      }
      const snapshot: unknown = await snapshotResponse.json();
      if (!isPlayerSnapshot(snapshot)) {
        store.requireReload("The player snapshot was invalid. Reload this page to continue.");
        return;
      }
      store.acceptSnapshot(snapshot);
    } catch {
      store.requireReload("Login could not be completed. Reload this page to try again.");
    }
  }

  async function handleLogout(): Promise<void> {
    const csrfToken = state.sessionCsrfToken;
    if (csrfToken === null) return;
    store.setStatus("logging-out", null);
    try {
      const response = await request(fetcher, "/api/player/logout", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csrf_token: csrfToken }),
      });
      if (response.status !== 204) {
        const code = await responseErrorCode(response);
        store.setStatus("connected", logoutErrorMessage(code, response.status));
        return;
      }
      socketRef.current?.disconnect();
      store.logoutComplete();
      setLoginAttempted(true);
      setLoginMessage("You are logged out. Reload the page to sign in again.");
    } catch {
      store.setStatus("connected", "Logout could not be completed. Please try again.");
    }
  }

  if (state.sessionCsrfToken === null) {
    if (state.status === "reload-required") {
      return (
        <main>
          <h1>Player reload required</h1>
          <p role="status">{state.message}</p>
          <button type="button" onClick={reloadPage}>Reload</button>
        </main>
      );
    }
    return (
      <main>
        <h1>Player login</h1>
        <p role="status">{connectionLabel(state.status)}</p>
        {(loginMessage ?? state.message) !== null && (
          <p role="alert">{loginMessage ?? state.message}</p>
        )}
        <form onSubmit={(event) => void handleLogin(event)}>
          <input type="hidden" name="csrf_token" value={preloginCsrfToken} />
          <label>
            Password
            <input
              type="password"
              name="password"
              autoComplete="current-password"
              maxLength={1024}
              required
              disabled={loginAttempted || !PRELOGIN_NONCE_PATTERN.test(preloginCsrfToken)}
            />
          </label>
          {!loginAttempted && (
            <button
              type="submit"
              disabled={!PRELOGIN_NONCE_PATTERN.test(preloginCsrfToken)}
            >
              Log in
            </button>
          )}
        </form>
        {loginAttempted && <button type="button" onClick={reloadPage}>Reload login page</button>}
      </main>
    );
  }

  const snapshot: PlayerSnapshot | null = state.snapshot;
  return (
    <main>
      <header>
        <h1>NeverEndingQuest player</h1>
        <button type="button" onClick={() => void handleLogout()} disabled={state.status === "logging-out"}>
          Log out
        </button>
      </header>
      <p role="status">{connectionLabel(state.status)}</p>
      {state.message !== null && <p role="alert">{state.message}</p>}
      {state.status === "disconnected" && (
        <button type="button" onClick={() => socketRef.current?.connect()}>
          Reconnect
        </button>
      )}
      {state.status === "reload-required" && (
        <button type="button" onClick={reloadPage}>Reload</button>
      )}
      {snapshot === null ? (
        <p>Loading player snapshot...</p>
      ) : (
        <>
          <section aria-labelledby="party-heading">
            <h2 id="party-heading">Party</h2>
            <ul>
              {snapshot.projection.party.members.map((member) => (
                <li key={member.name}>{member.name}</li>
              ))}
            </ul>
            <p>Active PC: {snapshot.projection.party.active_character ?? "None selected"}</p>
          </section>
          <section aria-labelledby="transcript-heading">
            <h2 id="transcript-heading">Shared transcript</h2>
            {snapshot.projection.transcript === undefined ? (
              <p>Transcript unavailable.</p>
            ) : snapshot.projection.transcript.messages.length === 0 ? (
              <p>No transcript yet.</p>
            ) : (
              <p>Transcript: {snapshot.projection.transcript.messages.length} messages</p>
            )}
          </section>
        </>
      )}
    </main>
  );
}

function connectionLabel(status: string): string {
  switch (status) {
    case "authenticating":
      return "Logging in...";
    case "hydrating":
      return "Loading player snapshot...";
    case "connecting":
      return "Connecting...";
    case "connected":
      return "Connected";
    case "disconnected":
      return "Disconnected";
    case "logging-out":
      return "Logging out...";
    case "reload-required":
      return "Reload required";
    default:
      return "Not connected";
  }
}

function isVersionMismatch(error: unknown): boolean {
  if (typeof error !== "object" || error === null) return false;
  const candidate = error as { message?: unknown; data?: unknown };
  if (candidate.message === "client_version_mismatch") return true;
  if (typeof candidate.data === "string") {
    return candidate.data === "client_version_mismatch";
  }
  if (
    Array.isArray(candidate.data) &&
    candidate.data.includes("client_version_mismatch")
  ) {
    return true;
  }
  if (typeof candidate.data === "object" && candidate.data !== null) {
    const data = candidate.data as { error?: unknown; message?: unknown };
    return (
      data.error === "client_version_mismatch" ||
      data.message === "client_version_mismatch"
    );
  }
  return false;
}

async function request(
  fetcher: typeof fetch | undefined,
  url: string,
  options: RequestInit,
): Promise<Response> {
  const fetchFunction = fetcher ?? globalThis.fetch;
  return fetchFunction(url, options);
}

async function readSessionGrant(response: Response): Promise<SessionGrant | null> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload !== "object" ||
      payload === null ||
      Array.isArray(payload) ||
      Object.keys(payload).some((key) => key !== "csrf_token" && key !== "expires_at")
    ) {
      return null;
    }
    const record = payload as Record<string, unknown>;
    if (
      typeof record.csrf_token !== "string" ||
      !SESSION_CSRF_PATTERN.test(record.csrf_token) ||
      typeof record.expires_at !== "number" ||
      !Number.isSafeInteger(record.expires_at) ||
      record.expires_at < 0
    ) {
      return null;
    }
    return { csrf_token: record.csrf_token, expires_at: record.expires_at };
  } catch {
    return null;
  }
}

async function responseErrorCode(response: Response): Promise<string | null> {
  try {
    const payload: unknown = await response.json();
    if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
      return null;
    }
    const code = (payload as Record<string, unknown>).error;
    return typeof code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(code)
      ? code
      : null;
  } catch {
    return null;
  }
}

function loginErrorMessage(code: string | null, status: number): string {
  if (code === "csrf_rejected") {
    return "The login form expired. Reload the page to get a new form.";
  }
  if (code === "rate_limited" || status === 429) {
    return "Too many login attempts. Wait a moment, then reload the login page.";
  }
  if (code === "invalid_credentials" || code === "invalid") {
    return "The password was not accepted. Reload the login page to try again.";
  }
  return "Login failed. Reload the page to try again.";
}

function snapshotErrorMessage(code: string | null, status: number): string {
  if (code === "rate_limited" || status === 429) {
    return "Snapshot requests are temporarily rate limited. Reload the page to continue.";
  }
  return "The player snapshot could not be loaded. Reload this page to continue.";
}

function logoutErrorMessage(code: string | null, status: number): string {
  if (code === "csrf_rejected") return "Logout was rejected. Reload and sign in again.";
  if (code === "rate_limited" || status === 429) return "Logout is temporarily rate limited.";
  return "Logout failed. Please try again.";
}

function reloadPage(): void {
  window.location.reload();
}
