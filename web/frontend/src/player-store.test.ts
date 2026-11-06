// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { describe, expect, it, vi } from "vitest";
import { PlayerStore } from "./player-store";
import type { PlayerEvent, PlayerSnapshot } from "./player-protocol";

const INSTANCE_ID = "I".repeat(32);
const SESSION_EPOCH = "E".repeat(32);

function snapshot(eventCursor = 0): PlayerSnapshot {
  return {
    schema_version: 1,
    instance_id: INSTANCE_ID,
    session_epoch: SESSION_EPOCH,
    revision: 1,
    event_cursor: eventCursor,
    projection: {
      party: {
        members: [{ name: "Acheron" }],
        active_character: "Acheron",
        active_character_revision: 0,
        world: {},
      },
      transcript: { available: true, messages: [] },
    },
  };
}

function event(eventId: number, name: string): PlayerEvent {
  return {
    schema_version: 1,
    instance_id: INSTANCE_ID,
    session_epoch: SESSION_EPOCH,
    event_id: eventId,
    revision: eventId + 1,
    type: "projection.updated",
    projection: {
      party: {
        members: [{ name }],
        active_character: name,
        active_character_revision: eventId,
        world: {},
      },
      transcript: { available: true, messages: [] },
    },
  };
}

function hydratedStore(): PlayerStore {
  const store = new PlayerStore();
  store.beginHydration("S".repeat(43));
  expect(store.acceptSnapshot(snapshot())).toBe(true);
  return store;
}

describe("PlayerStore ordered cache", () => {
  it("applies contiguous events in cursor order and suppresses duplicates", () => {
    const store = hydratedStore();
    expect(store.acceptEvent(event(1, "Merisiel"))).toBe(true);
    expect(store.acceptEvent(event(2, "Acheron"))).toBe(true);
    expect(store.acceptEvent(event(1, "Merisiel"))).toBe(true);
    expect(store.getSnapshot().snapshot?.event_cursor).toBe(2);
    expect(store.getSnapshot().snapshot?.projection.party.active_character).toBe("Acheron");
  });

  it("requests a snapshot on a cursor gap and does not guess the missing update", () => {
    const store = hydratedStore();
    const requestSnapshot = vi.fn();
    store.setSnapshotRequester(requestSnapshot);

    expect(store.acceptEvent(event(2, "Merisiel"))).toBe(false);
    expect(store.getSnapshot().snapshot?.event_cursor).toBe(0);
    expect(store.getSnapshot().snapshot?.projection.party.active_character).toBe("Acheron");
    expect(requestSnapshot).toHaveBeenCalledWith({
      schema_version: 1,
      instance_id: INSTANCE_ID,
      session_epoch: SESSION_EPOCH,
    });
    expect(store.acceptEvent(event(3, "Merisiel"))).toBe(false);
    expect(requestSnapshot).toHaveBeenCalledTimes(1);

    expect(store.acceptSnapshot(snapshot(2))).toBe(true);
    expect(store.acceptEvent(event(3, "Merisiel"))).toBe(true);
    expect(store.getSnapshot().snapshot?.event_cursor).toBe(3);
  });

  it("requests resynchronization for malformed events and changed identities", () => {
    const store = hydratedStore();
    const requestSnapshot = vi.fn();
    store.setSnapshotRequester(requestSnapshot);

    expect(store.acceptEvent({ ...event(1, "Merisiel"), host_route: "/admin" })).toBe(false);
    expect(store.acceptEvent({ ...event(1, "Merisiel"), instance_id: "X".repeat(32) })).toBe(false);
    expect(requestSnapshot).toHaveBeenCalledTimes(1);

    store.acceptSnapshot(snapshot());
    expect(store.acceptError({ schema_version: 1, code: "session_epoch_changed" })).toBe(true);
    expect(requestSnapshot).toHaveBeenCalledTimes(2);
  });
});
