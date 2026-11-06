// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import {
  isPlayerError,
  isPlayerEvent,
  isPlayerReceipt,
  isPlayerSnapshot,
  type PlayerError,
  type PlayerReceipt,
  type PlayerSnapshot,
  type PlayerSnapshotRequest,
} from "./player-protocol";

export type PlayerConnectionStatus =
  | "logged-out"
  | "authenticating"
  | "hydrating"
  | "connecting"
  | "connected"
  | "disconnected"
  | "logging-out"
  | "reload-required";

export type PlayerStoreState = Readonly<{
  status: PlayerConnectionStatus;
  sessionCsrfToken: string | null;
  snapshot: PlayerSnapshot | null;
  message: string | null;
  lastReceipt: PlayerReceipt | null;
  pendingInput: PendingPlayerInput | null;
  requiresResync: boolean;
}>;

export type PendingPlayerInput = Readonly<{
  requestId: string;
  characterName: string;
  activeCharacterRevision: number;
  status: "pending" | "uncertain";
}>;

export type SnapshotRequester = (request: PlayerSnapshotRequest) => void;

const RESYNC_ERROR_CODES = new Set([
  "cursor_expired",
  "event_gap",
  "future_cursor",
  "instance_mismatch",
  "invalid_cursor",
  "resync_required",
  "server_instance_changed",
  "session_epoch_changed",
  "session_epoch_mismatch",
  "stale_context",
]);

export class PlayerStore {
  private currentState: PlayerStoreState = {
    status: "logged-out",
    sessionCsrfToken: null,
    snapshot: null,
    message: null,
    lastReceipt: null,
    pendingInput: null,
    requiresResync: false,
  };
  private readonly listeners = new Set<() => void>();
  private snapshotRequester: SnapshotRequester | null = null;
  private snapshotRequestPending = false;

  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  readonly getSnapshot = (): PlayerStoreState => this.currentState;

  beginAuthentication(): void {
    this.update({ status: "authenticating", message: null });
  }

  beginHydration(sessionCsrfToken: string): void {
    this.snapshotRequestPending = false;
    this.update({
      status: "hydrating",
      sessionCsrfToken,
      snapshot: null,
      message: null,
      lastReceipt: null,
      pendingInput: null,
      requiresResync: false,
    });
  }

  setSnapshotRequester(requester: SnapshotRequester | null): void {
    this.snapshotRequester = requester;
    if (requester !== null && this.snapshotRequestPending) {
      this.dispatchSnapshotRequest();
    }
  }

  acceptSnapshot(payload: unknown): boolean {
    if (!isPlayerSnapshot(payload)) {
      this.requestSnapshot();
      return false;
    }
    this.snapshotRequestPending = false;
    const currentSnapshot = this.currentState.snapshot;
    const pendingInput = this.currentState.pendingInput;
    const identityChanged =
      currentSnapshot !== null &&
      (currentSnapshot.instance_id !== payload.instance_id ||
        currentSnapshot.session_epoch !== payload.session_epoch);
    this.update({
      snapshot: payload,
      status: this.currentState.status === "hydrating" ? "connecting" : this.currentState.status,
      message: null,
      pendingInput:
        pendingInput?.status === "pending" && identityChanged
          ? { ...pendingInput, status: "uncertain" }
          : pendingInput,
      requiresResync: false,
    });
    return true;
  }

  acceptEvent(payload: unknown): boolean {
    if (!isPlayerEvent(payload)) {
      this.requestSnapshot();
      return false;
    }
    const current = this.currentState.snapshot;
    if (current === null) {
      this.requestSnapshot();
      return false;
    }
    if (
      payload.instance_id !== current.instance_id ||
      payload.session_epoch !== current.session_epoch
    ) {
      this.requestSnapshot();
      return false;
    }
    if (payload.event_id <= current.event_cursor) return true;
    if (payload.event_id !== current.event_cursor + 1) {
      this.requestSnapshot();
      return false;
    }
    this.update({
      snapshot: {
        ...current,
        revision: payload.revision,
        event_cursor: payload.event_id,
        projection: payload.projection,
      },
      message: null,
    });
    return true;
  }

  acceptReceipt(payload: unknown): boolean {
    if (!isPlayerReceipt(payload)) {
      this.requestSnapshot();
      return false;
    }
    const pendingInput = this.currentState.pendingInput;
    if (pendingInput === null || pendingInput.requestId !== payload.request_id) {
      return false;
    }
    const requiresResync =
      this.currentState.requiresResync ||
      payload.status === "stale" ||
      payload.status === "uncertain";
    this.update({
      pendingInput: null,
      lastReceipt: payload,
      requiresResync,
    });
    if (payload.status === "stale" || payload.status === "uncertain") {
      this.requestSnapshot(true);
    }
    return true;
  }

  beginInput(
    requestId: string,
    characterName: string,
    activeCharacterRevision: number,
  ): boolean {
    const snapshot = this.currentState.snapshot;
    const existing = this.currentState.pendingInput;
    if (
      this.currentState.status !== "connected" ||
      snapshot === null ||
      this.currentState.requiresResync ||
      existing?.status === "pending" ||
      snapshot.projection.party.active_character !== characterName ||
      snapshot.projection.party.active_character_revision !== activeCharacterRevision
    ) {
      return false;
    }
    this.update({
      pendingInput: {
        requestId,
        characterName,
        activeCharacterRevision,
        status: "pending",
      },
      lastReceipt: null,
      message: null,
    });
    return true;
  }

  acceptError(payload: unknown): boolean {
    if (!isPlayerError(payload)) {
      this.requestSnapshot();
      return false;
    }
    if (RESYNC_ERROR_CODES.has(payload.code)) {
      this.requestSnapshot();
    }
    this.update({ message: messageForPlayerError(payload) });
    return true;
  }

  requestSnapshot(force = false): boolean {
    if (this.currentState.snapshot === null) return false;
    if (this.snapshotRequestPending && !force) return false;
    this.snapshotRequestPending = true;
    this.dispatchSnapshotRequest();
    return true;
  }

  markConnected(): void {
    if (this.currentState.status === "reload-required") return;
    this.update({ status: "connected", message: null });
    this.requestSnapshot(true);
  }

  markDisconnected(message = "Disconnected. Reconnect to resynchronize."): void {
    if (
      this.currentState.status === "reload-required" ||
      this.currentState.status === "logged-out"
    ) {
      return;
    }
    const pendingInput = this.currentState.pendingInput;
    const inputWasPending = pendingInput?.status === "pending";
    this.update({
      status: "disconnected",
      message,
      pendingInput: inputWasPending ? { ...pendingInput, status: "uncertain" } : pendingInput,
      requiresResync: this.currentState.requiresResync || inputWasPending,
    });
  }

  setStatus(status: PlayerConnectionStatus, message: string | null = null): void {
    this.update({ status, message });
  }

  requireReload(message = "This player build is out of date. Reload this page to continue."): void {
    this.snapshotRequestPending = false;
    const pendingInput = this.currentState.pendingInput;
    const inputWasPending = pendingInput?.status === "pending";
    this.update({
      status: "reload-required",
      message,
      pendingInput: inputWasPending ? { ...pendingInput, status: "uncertain" } : pendingInput,
      requiresResync: this.currentState.requiresResync || inputWasPending,
    });
  }

  logoutComplete(): void {
    this.snapshotRequestPending = false;
    this.snapshotRequester = null;
    this.currentState = {
      status: "logged-out",
      sessionCsrfToken: null,
      snapshot: null,
      message: null,
      lastReceipt: null,
      pendingInput: null,
      requiresResync: false,
    };
    this.notify();
  }

  private dispatchSnapshotRequest(): void {
    const snapshot = this.currentState.snapshot;
    if (snapshot === null || this.snapshotRequester === null) return;
    this.snapshotRequester({
      schema_version: 1,
      instance_id: snapshot.instance_id,
      session_epoch: snapshot.session_epoch,
    });
  }

  private update(patch: Partial<PlayerStoreState>): void {
    this.currentState = { ...this.currentState, ...patch };
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

function messageForPlayerError(error: PlayerError): string | null {
  if (error.code === "stale_context") {
    return "The active-PC selection was stale. Reviewing the refreshed state.";
  }
  if (RESYNC_ERROR_CODES.has(error.code)) return "Resynchronizing player state...";
  if (error.code === "rate_limited") return "Please wait before requesting another update.";
  if (error.code === "snapshot_unavailable") return "The player snapshot is temporarily unavailable.";
  return null;
}
