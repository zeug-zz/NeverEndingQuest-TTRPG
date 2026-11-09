// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  type ChangeEvent,
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
  isPlayerCommand,
  isPlayerSnapshot,
  type PlayerActivePCSelection,
  type PlayerCommand,
  type PlayerMember,
  type PlayerReceipt,
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
type DraftContext = Readonly<{ characterName: string; revision: number }>;

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
  const [draft, setDraft] = useState("");
  const [draftContext, setDraftContext] = useState<DraftContext | null>(null);
  const [inputNotice, setInputNotice] = useState<string | null>(null);
  const readyForSocket = state.sessionCsrfToken !== null && state.snapshot !== null;

  useEffect(() => {
    if (!readyForSocket || state.status === "reload-required") return;
    const socket = io("/player", {
      path: "/socket.io",
      transports: ["websocket"],
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

  useEffect(() => {
    if (state.lastReceipt?.status === "accepted") {
      setDraft("");
      setDraftContext(null);
      setInputNotice(null);
    }
  }, [state.lastReceipt]);

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
      setInputNotice(null);
      setLoginAttempted(true);
      setLoginMessage("You are logged out. Reload the page to sign in again.");
    } catch {
      store.setStatus("connected", "Logout could not be completed. Please try again.");
    }
  }

  function handleActivePCChange(event: ChangeEvent<HTMLSelectElement>): void {
    const current = store.getSnapshot();
    const snapshot = current.snapshot;
    const socket = socketRef.current;
    const characterName = event.currentTarget.value;
    if (
      current.status !== "connected" ||
      snapshot === null ||
      socket === null ||
      !socket.connected ||
      !snapshot.projection.party.members.some((member) => member.name === characterName)
    ) {
      return;
    }
    const selection: PlayerActivePCSelection = {
      schema_version: 1,
      instance_id: snapshot.instance_id,
      session_epoch: snapshot.session_epoch,
      character_name: characterName,
      expected_revision: snapshot.projection.party.active_character_revision,
    };
    socket.emit("player.active_pc.select", selection);
  }

  function handleDraftChange(event: ChangeEvent<HTMLTextAreaElement>): void {
    const value = event.currentTarget.value;
    setDraft(value);
    setInputNotice(null);
    if (value.length === 0) {
      setDraftContext(null);
      return;
    }
    if (draftContext === null) {
      const snapshot = store.getSnapshot().snapshot;
      const characterName = snapshot?.projection.party.active_character;
      if (snapshot !== null && characterName !== null && characterName !== undefined) {
        setDraftContext({
          characterName,
          revision: snapshot.projection.party.active_character_revision,
        });
      }
    }
  }

  function handleInputSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const current = store.getSnapshot();
    const snapshot = current.snapshot;
    const socket = socketRef.current;
    const characterName = snapshot?.projection.party.active_character;
    const revision = snapshot?.projection.party.active_character_revision;
    const staleDraft =
      draft.length > 0 &&
      draftContext !== null &&
      (draftContext.characterName !== characterName || draftContext.revision !== revision);
    if (
      current.status !== "connected" ||
      snapshot === null ||
      socket === null ||
      !socket.connected ||
      characterName === null ||
      characterName === undefined ||
      revision === undefined ||
      snapshot.projection.busy === true ||
      current.requiresResync ||
      current.pendingInput?.status === "pending" ||
      staleDraft ||
      draft.trim().length === 0
    ) {
      return;
    }

    let requestId: string;
    try {
      requestId = createRequestId();
    } catch {
      setInputNotice("A secure request ID could not be created. Reload the player page to try again.");
      return;
    }

    const command: PlayerCommand = {
      schema_version: 1,
      instance_id: snapshot.instance_id,
      session_epoch: snapshot.session_epoch,
      request_id: requestId,
      character_name: characterName,
      active_character_revision: revision,
      text: draft,
    };
    if (!isPlayerCommand(command)) {
      setInputNotice("Input is invalid or exceeds the player text limit. Shorten it before submitting.");
      return;
    }
    if (!store.beginInput(requestId, characterName, revision)) {
      store.requestSnapshot(true);
      return;
    }
    setInputNotice(null);
    try {
      socket.emit("player.input.submit", command);
    } catch {
      store.markDisconnected("The input connection ended before confirmation. Its result is uncertain.");
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
  const members = snapshot?.projection.party.members ?? [];
  const activeCharacter = snapshot?.projection.party.active_character ?? null;
  const activeCharacterRevision = snapshot?.projection.party.active_character_revision ?? null;
  const selectedMember = members.find((member) => member.name === activeCharacter) ?? null;
  const staleDraft =
    draft.length > 0 &&
    draftContext !== null &&
    (draftContext.characterName !== activeCharacter ||
      draftContext.revision !== activeCharacterRevision);
  const gameplayInputDisabled =
    state.status !== "connected" ||
    snapshot === null ||
    snapshot.projection.busy === true ||
    state.pendingInput?.status === "pending" ||
    state.requiresResync ||
    activeCharacter === null ||
    staleDraft;
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
            <label htmlFor="active-pc">Active PC</label>
            <select
              id="active-pc"
              value={activeCharacter ?? ""}
              onChange={handleActivePCChange}
              disabled={state.status !== "connected" || members.length === 0}
            >
              {activeCharacter === null && <option value="">No active PC selected</option>}
              {members.map((member) => (
                <option key={member.name} value={member.name}>{member.name}</option>
              ))}
            </select>
            <p>Active PC: {snapshot.projection.party.active_character ?? "None selected"}</p>
          </section>
          <section aria-labelledby="transcript-heading">
            <h2 id="transcript-heading">Shared transcript</h2>
            {snapshot.projection.transcript === undefined ||
            !snapshot.projection.transcript.available ? (
              <p>Transcript unavailable.</p>
            ) : snapshot.projection.transcript.messages.length === 0 ? (
              <p>No transcript yet.</p>
            ) : (
              <ol className="transcript-list">
                {snapshot.projection.transcript.messages.map((message) => (
                  <li key={message.id}>
                    <article>
                      <h3>{message.author ?? (message.role === "assistant" ? "Narrator" : "Player")}</h3>
                      <p className="transcript-message">{message.text}</p>
                    </article>
                  </li>
                ))}
              </ol>
            )}
          </section>
          <section aria-labelledby="sheet-heading">
            <h2 id="sheet-heading">Character sheet</h2>
            {selectedMember === null ? (
              <p>No active PC sheet is available.</p>
            ) : (
              <CharacterSheet member={selectedMember} />
            )}
          </section>
          <section aria-labelledby="combat-heading">
            <h2 id="combat-heading">Initiative and combat</h2>
            {snapshot.projection.combat === undefined ||
            !snapshot.projection.combat.available ? (
              <p>Combat information unavailable.</p>
            ) : !snapshot.projection.combat.active ? (
              <p>No active combat.</p>
            ) : (
              <>
                <p>
                  Round {snapshot.projection.combat.round ?? "unknown"}; phase {snapshot.projection.combat.phase ?? "unknown"}
                </p>
                {snapshot.projection.combat.turn_order.length === 0 ? (
                  <p>No initiative entries.</p>
                ) : (
                  <ol aria-label="Initiative order">
                    {snapshot.projection.combat.turn_order.map((combatant, index) => (
                      <li key={`${index}-${combatant.name}`} data-combatant={combatant.name}>
                        {combatant.name} ({combatant.kind}) - initiative {combatant.initiative} - {combatant.status}
                      </li>
                    ))}
                  </ol>
                )}
              </>
            )}
          </section>
          <section aria-labelledby="input-heading">
            <h2 id="input-heading">Gameplay input</h2>
            {snapshot.projection.busy === undefined ? (
              <p role="status">Busy status unavailable.</p>
            ) : snapshot.projection.busy ? (
              <p role="status">The game is busy. Please wait before submitting input.</p>
            ) : (
              <p role="status">The game is ready for input.</p>
            )}
            {state.pendingInput?.status === "pending" && (
              <p role="status">
                Sending input for {state.pendingInput.characterName} at revision {state.pendingInput.activeCharacterRevision}...
              </p>
            )}
            {state.pendingInput?.status === "uncertain" && (
              <p role="alert">
                The connection ended while this input was pending. The action may or may not have applied. {state.requiresResync
                  ? "Resynchronize before deciding what to do; it will not be resubmitted."
                  : "Player state has been refreshed. Decide manually what to do next; it was not resubmitted."}
              </p>
            )}
            {state.lastReceipt !== null && (
              <p role={state.lastReceipt.status === "rejected" ? "alert" : "status"}>
                {receiptMessage(state.lastReceipt, state.requiresResync)}
              </p>
            )}
            {state.requiresResync && state.lastReceipt?.status !== "stale" && state.lastReceipt?.status !== "uncertain" && state.pendingInput?.status !== "uncertain" && (
              <p role="status">Resynchronizing player state before more input can be submitted.</p>
            )}
            {inputNotice !== null && <p role="alert">{inputNotice}</p>}
            {staleDraft && (
              <>
                <p role="alert">
                  The active PC or revision changed while you were composing. Review the refreshed state before continuing.
                </p>
                {activeCharacter !== null && activeCharacterRevision !== null && (
                  <button
                    type="button"
                    onClick={() => setDraftContext({
                      characterName: activeCharacter,
                      revision: activeCharacterRevision,
                    })}
                  >
                    Confirm refreshed state for {activeCharacter}
                  </button>
                )}
              </>
            )}
            <form onSubmit={handleInputSubmit}>
              <label htmlFor="gameplay-input">Your action or message</label>
              <textarea
                id="gameplay-input"
                name="text"
                rows={4}
                maxLength={4096}
                value={draft}
                onChange={handleDraftChange}
                disabled={gameplayInputDisabled}
              />
              <button
                type="submit"
                disabled={gameplayInputDisabled || draft.trim().length === 0}
              >
                Submit input
              </button>
            </form>
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

function receiptMessage(receipt: PlayerReceipt, requiresResync: boolean): string {
  switch (receipt.status) {
    case "accepted":
      return "Input accepted for queue admission. This does not mean the action is complete.";
    case "busy":
      return "The game is busy. This input was not queued; review the state and submit again when ready.";
    case "stale":
      return requiresResync
        ? "Input rejected as stale. Refreshing state; review the active PC and revision before submitting again."
        : "Input rejected as stale. Review the refreshed active PC and revision before submitting again.";
    case "rejected":
      return receipt.code === undefined
        ? "Input rejected. Review the input and current state before trying again."
        : `Input rejected (${receipt.code}). Review the input and current state before trying again.`;
    case "uncertain":
      return requiresResync
        ? "The action may or may not have applied. Resynchronize before deciding what to do; this input will never be automatically resubmitted."
        : "The action may or may not have applied. State has been refreshed; decide manually what to do next. This input was not resubmitted.";
    case "duplicate":
      return "This request was already received. No second action was sent.";
  }
}

function CharacterSheet({ member }: Readonly<{ member: PlayerMember }>) {
  const portraitMediaId = member.portrait_media_id;
  const portraitUrl =
    portraitMediaId !== undefined && /^[A-Za-z0-9_-]{1,128}$/.test(portraitMediaId)
      ? `/api/player/media/${encodeURIComponent(portraitMediaId)}`
      : null;
  const fields = characterSheetFields(member);
  return (
    <article aria-label={`${member.name} read-only sheet`}>
      <h3>{member.name}</h3>
      {portraitUrl !== null && (
        <img src={portraitUrl} alt={`${member.name} portrait`} loading="lazy" />
      )}
      <dl>
        {fields.map(([label, value]) => {
          const formatted = formatSheetValue(value);
          return formatted === null ? null : (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{formatted}</dd>
            </div>
          );
        })}
      </dl>
    </article>
  );
}

function characterSheetFields(member: PlayerMember): readonly (readonly [string, unknown])[] {
  return [
    ["Level", member.level],
    ["Race", member.race],
    ["Class", member.class],
    ["Background", member.background],
    ["Alignment", member.alignment],
    ["Size", member.size],
    ["Status", member.status],
    ["Condition", member.condition],
    ["Affected by", member.condition_affected],
    ["Hit points", member.hitPoints],
    ["Maximum hit points", member.maxHitPoints],
    ["Armor class", member.armorClass],
    ["Initiative", member.initiative],
    ["Speed", member.speed],
    ["Proficiency bonus", member.proficiencyBonus],
    ["Abilities", member.abilities],
    ["Death saves", member.deathSaves],
    ["Saving throws", member.savingThrows],
    ["Skills", member.skills],
  ];
}

function formatSheetValue(value: unknown): string | null {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.join(", ");
  }
  if (typeof value === "object" && value !== null && !Array.isArray(value)) {
    const entries = Object.entries(value)
      .filter((entry): entry is [string, number] => typeof entry[1] === "number")
      .sort(([left], [right]) => left.localeCompare(right));
    return entries.length === 0
      ? null
      : entries.map(([field, item]) => `${field}: ${item}`).join(", ");
  }
  return null;
}

function createRequestId(): string {
  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi?.randomUUID === "function") return cryptoApi.randomUUID();
  if (typeof cryptoApi?.getRandomValues !== "function") {
    throw new Error("Cryptographic randomness is unavailable");
  }
  const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
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
