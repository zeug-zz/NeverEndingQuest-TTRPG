// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

/** Strict browser-side mirrors of the server's version-1 player envelopes. */

export const PLAYER_PROTOCOL_VERSION = 1 as const;

export type PlayerTranscriptMessage = Readonly<{
  id: string;
  sequence: number;
  role: "user" | "assistant";
  text: string;
  author?: string;
}>;

export type PlayerMember = Readonly<{
  name: string;
  level?: number;
  race?: string;
  class?: string;
  background?: string;
  alignment?: string;
  size?: string;
  status?: string;
  condition?: string;
  condition_affected?: readonly string[];
  hitPoints?: number;
  maxHitPoints?: number;
  armorClass?: number;
  initiative?: number;
  speed?: number;
  abilities?: Readonly<Record<string, number>>;
  deathSaves?: Readonly<Record<string, number>>;
  savingThrows?: readonly string[];
  skills?: readonly string[] | Readonly<Record<string, number>>;
  proficiencyBonus?: number;
  portrait_media_id?: string;
}>;

export type PlayerProjection = Readonly<{
  party: Readonly<{
    members: readonly PlayerMember[];
    active_character: string | null;
    active_character_revision: number;
    world: Readonly<Record<string, string | number>>;
  }>;
  transcript?: Readonly<{
    available: boolean;
    messages: readonly PlayerTranscriptMessage[];
  }>;
  combat?: Readonly<{
    available: boolean;
    active: boolean;
    round: number | null;
    phase: "PC_PHASE" | "ENEMY_PHASE" | null;
    turn_order: readonly Readonly<{
      name: string;
      kind: "pc" | "npc" | "monster";
      initiative: number;
      status: "alive" | "unconscious" | "dead" | "defeated";
    }>[];
  }>;
  busy?: boolean;
}>;

export type PlayerSnapshot = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  revision: number;
  event_cursor: number;
  projection: PlayerProjection;
}>;

export type PlayerEvent = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  event_id: number;
  revision: number;
  type: "projection.updated";
  projection: PlayerProjection;
}>;

export type PlayerSnapshotRequest = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
}>;

export type PlayerActivePCSelection = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  character_name: string;
  expected_revision: number;
}>;

export type PlayerCommand = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  request_id: string;
  character_name: string;
  active_character_revision: number;
  text: string;
}>;

export type PlayerReceipt = Readonly<{
  schema_version: 1;
  instance_id: string;
  session_epoch: string;
  request_id: string;
  status: "accepted" | "busy" | "stale" | "rejected" | "uncertain" | "duplicate";
  code?: string;
}>;

export type PlayerError = Readonly<{
  schema_version: 1;
  code: string;
  request_id?: string;
}>;

export type PlayerReplay = Readonly<{
  schema_version: 1;
  kind: "replay";
  instance_id: string;
  session_epoch: string;
  after_cursor: number;
  event_cursor: number;
  events: readonly PlayerEvent[];
}>;

export type PlayerResync = Readonly<{
  schema_version: 1;
  kind: "resync_required";
  reason:
    | "cursor_expired"
    | "event_gap"
    | "future_cursor"
    | "instance_mismatch"
    | "invalid_cursor"
    | "session_epoch_mismatch";
  snapshot: PlayerSnapshot;
}>;

const IDENTITY_PATTERN = /^[A-Za-z0-9_-]{32,128}$/;
const REQUEST_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const ERROR_CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const TRANSCRIPT_ID_PATTERN = /^transcript-[a-f0-9]{32}$/;
const MAX_SNAPSHOT_BYTES = 256 * 1024;
const MAX_EVENT_BYTES = 16 * 1024;
const MAX_PLAYER_TEXT_BYTES = 24 * 1024;
const MAX_TRANSCRIPT_MESSAGES = 15;
const MAX_COMBATANTS = 128;

const CHARACTER_STRING_FIELDS = new Set([
  "race",
  "class",
  "background",
  "alignment",
  "size",
  "status",
  "condition",
]);
const CHARACTER_INTEGER_FIELDS = new Set([
  "level",
  "hitPoints",
  "maxHitPoints",
  "armorClass",
  "initiative",
  "speed",
  "proficiencyBonus",
]);
const CHARACTER_FIELDS = new Set([
  "name",
  ...CHARACTER_STRING_FIELDS,
  ...CHARACTER_INTEGER_FIELDS,
  "condition_affected",
  "abilities",
  "deathSaves",
  "savingThrows",
  "skills",
  "portrait_media_id",
]);
const WORLD_FIELDS = new Set([
  "year",
  "month",
  "day",
  "time",
  "weather",
  "season",
  "dayNightCycle",
  "moonPhase",
  "currentLocation",
  "currentArea",
]);
const ABILITY_FIELDS = new Set([
  "strength",
  "dexterity",
  "constitution",
  "intelligence",
  "wisdom",
  "charisma",
]);
const DEATH_SAVE_FIELDS = new Set(["successes", "failures"]);
const SKILL_FIELDS = new Set([
  "Acrobatics",
  "Animal Handling",
  "Arcana",
  "Athletics",
  "Deception",
  "History",
  "Insight",
  "Intimidation",
  "Investigation",
  "Medicine",
  "Nature",
  "Perception",
  "Performance",
  "Persuasion",
  "Religion",
  "Sleight of Hand",
  "Stealth",
  "Survival",
]);
const SAVING_THROW_FIELDS = new Set([
  "Strength",
  "Dexterity",
  "Constitution",
  "Intelligence",
  "Wisdom",
  "Charisma",
]);
const RESYNC_REASONS = new Set([
  "cursor_expired",
  "event_gap",
  "future_cursor",
  "instance_mismatch",
  "invalid_cursor",
  "session_epoch_mismatch",
]);

export function isPlayerSnapshot(value: unknown): value is PlayerSnapshot {
  return (
    isExactRecord(value, [
      "schema_version",
      "instance_id",
      "session_epoch",
      "revision",
      "event_cursor",
      "projection",
    ]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch) &&
    isNonnegativeInteger(value.revision) &&
    isNonnegativeInteger(value.event_cursor) &&
    isPlayerProjection(value.projection) &&
    isWithinJsonBytes(value, MAX_SNAPSHOT_BYTES)
  );
}

export function isPlayerEvent(value: unknown): value is PlayerEvent {
  return (
    isExactRecord(value, [
      "schema_version",
      "instance_id",
      "session_epoch",
      "event_id",
      "revision",
      "type",
      "projection",
    ]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch) &&
    isPositiveInteger(value.event_id) &&
    isNonnegativeInteger(value.revision) &&
    value.type === "projection.updated" &&
    isPlayerProjection(value.projection) &&
    isWithinJsonBytes(value, MAX_EVENT_BYTES)
  );
}

export function isPlayerSnapshotRequest(value: unknown): value is PlayerSnapshotRequest {
  return (
    isExactRecord(value, ["schema_version", "instance_id", "session_epoch"]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch)
  );
}

export function isPlayerActivePCSelection(value: unknown): value is PlayerActivePCSelection {
  return (
    isExactRecord(value, [
      "schema_version",
      "instance_id",
      "session_epoch",
      "character_name",
      "expected_revision",
    ]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch) &&
    isCharacterName(value.character_name) &&
    isNonnegativeInteger(value.expected_revision) &&
    isWithinJsonBytes(value, MAX_EVENT_BYTES)
  );
}

export function isPlayerCommand(value: unknown): value is PlayerCommand {
  return (
    isExactRecord(value, [
      "schema_version",
      "instance_id",
      "session_epoch",
      "request_id",
      "character_name",
      "active_character_revision",
      "text",
    ]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch) &&
    isRequestId(value.request_id) &&
    isCharacterName(value.character_name) &&
    isNonnegativeInteger(value.active_character_revision) &&
    isBoundedString(value.text, 4 * 1024) &&
    value.text.trim().length > 0 &&
    !value.text.includes("\0") &&
    isWithinJsonBytes(value, MAX_EVENT_BYTES)
  );
}

export function isPlayerReceipt(value: unknown): value is PlayerReceipt {
  const statuses = new Set([
    "accepted",
    "busy",
    "stale",
    "rejected",
    "uncertain",
    "duplicate",
  ]);
  return (
    isExactRecord(
      value,
      ["schema_version", "instance_id", "session_epoch", "request_id", "status"],
      ["code"],
    ) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isIdentity(value.instance_id) &&
    isIdentity(value.session_epoch) &&
    isRequestId(value.request_id) &&
    typeof value.status === "string" &&
    statuses.has(value.status) &&
    (!Object.hasOwn(value, "code") || isErrorCode(value.code)) &&
    isWithinJsonBytes(value, MAX_EVENT_BYTES)
  );
}

export function isPlayerError(value: unknown): value is PlayerError {
  return (
    isExactRecord(value, ["schema_version", "code"], ["request_id"]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    isErrorCode(value.code) &&
    (!Object.hasOwn(value, "request_id") || isRequestId(value.request_id)) &&
    isWithinJsonBytes(value, MAX_EVENT_BYTES)
  );
}

export function isPlayerReplay(value: unknown): value is PlayerReplay {
  if (
    !isExactRecord(value, [
      "schema_version",
      "kind",
      "instance_id",
      "session_epoch",
      "after_cursor",
      "event_cursor",
      "events",
    ]) ||
    value.schema_version !== PLAYER_PROTOCOL_VERSION ||
    value.kind !== "replay" ||
    !isIdentity(value.instance_id) ||
    !isIdentity(value.session_epoch) ||
    !isNonnegativeInteger(value.after_cursor) ||
    !isNonnegativeInteger(value.event_cursor) ||
    !Array.isArray(value.events) ||
    value.events.length > 256 ||
    !isWithinJsonBytes(value, MAX_SNAPSHOT_BYTES)
  ) {
    return false;
  }
  let expected = value.after_cursor + 1;
  for (const event of value.events) {
    if (
      !isPlayerEvent(event) ||
      event.instance_id !== value.instance_id ||
      event.session_epoch !== value.session_epoch ||
      event.event_id !== expected
    ) {
      return false;
    }
    expected += 1;
  }
  return value.events.length === 0
    ? value.after_cursor === value.event_cursor
    : value.events[value.events.length - 1]?.event_id === value.event_cursor;
}

export function isPlayerResync(value: unknown): value is PlayerResync {
  return (
    isExactRecord(value, ["schema_version", "kind", "reason", "snapshot"]) &&
    value.schema_version === PLAYER_PROTOCOL_VERSION &&
    value.kind === "resync_required" &&
    typeof value.reason === "string" &&
    RESYNC_REASONS.has(value.reason) &&
    isPlayerSnapshot(value.snapshot) &&
    isWithinJsonBytes(value, MAX_SNAPSHOT_BYTES)
  );
}

function isPlayerProjection(value: unknown): value is PlayerProjection {
  if (
    !isExactRecord(value, ["party"], ["transcript", "combat", "busy"]) ||
    !isPlayerParty(value.party)
  ) {
    return false;
  }
  if (Object.hasOwn(value, "transcript") && !isPlayerTranscript(value.transcript)) {
    return false;
  }
  if (Object.hasOwn(value, "combat") && !isPlayerCombat(value.combat)) {
    return false;
  }
  return !Object.hasOwn(value, "busy") || typeof value.busy === "boolean";
}

function isPlayerParty(value: unknown): boolean {
  if (
    !isExactRecord(value, [
      "members",
      "active_character",
      "active_character_revision",
      "world",
    ]) ||
    !Array.isArray(value.members) ||
    !value.members.every(isPlayerMember) ||
    !(value.active_character === null || isCharacterName(value.active_character)) ||
    !isNonnegativeInteger(value.active_character_revision) ||
    !isPlayerWorld(value.world)
  ) {
    return false;
  }
  const names = new Set(value.members.map((member) => member.name));
  return value.active_character === null || names.has(value.active_character);
}

function isPlayerMember(value: unknown): value is PlayerMember {
  if (
    !isExactRecord(value, ["name"], [...CHARACTER_FIELDS].filter((field) => field !== "name")) ||
    !isCharacterName(value.name)
  ) {
    return false;
  }
  for (const field of CHARACTER_STRING_FIELDS) {
    if (Object.hasOwn(value, field) && !isBoundedString(value[field], MAX_PLAYER_TEXT_BYTES)) {
      return false;
    }
  }
  for (const field of CHARACTER_INTEGER_FIELDS) {
    if (Object.hasOwn(value, field) && !isSafeInteger(value[field])) {
      return false;
    }
  }
  if (
    Object.hasOwn(value, "condition_affected") &&
    !isStringList(value.condition_affected, 128, MAX_PLAYER_TEXT_BYTES)
  ) {
    return false;
  }
  if (
    Object.hasOwn(value, "savingThrows") &&
    !isStringList(value.savingThrows, 128, 128, SAVING_THROW_FIELDS)
  ) {
    return false;
  }
  if (
    Object.hasOwn(value, "abilities") &&
    !isIntegerRecord(value.abilities, ABILITY_FIELDS)
  ) {
    return false;
  }
  if (
    Object.hasOwn(value, "deathSaves") &&
    !isIntegerRecord(value.deathSaves, DEATH_SAVE_FIELDS)
  ) {
    return false;
  }
  if (Object.hasOwn(value, "skills")) {
    const skills = value.skills;
    if (
      !isStringList(skills, 128, 128, SKILL_FIELDS) &&
      !isIntegerRecord(skills, SKILL_FIELDS)
    ) {
      return false;
    }
  }
  return (
    !Object.hasOwn(value, "portrait_media_id") ||
    (isBoundedString(value.portrait_media_id, 128) &&
      /^[A-Za-z0-9_-]{1,128}$/.test(value.portrait_media_id))
  );
}

function isPlayerWorld(value: unknown): boolean {
  if (!isRecord(value)) return false;
  for (const [field, item] of Object.entries(value)) {
    if (!WORLD_FIELDS.has(field)) return false;
    if (field === "year" || field === "day") {
      if (!isSafeInteger(item)) return false;
    } else if (!isBoundedString(item, MAX_PLAYER_TEXT_BYTES)) {
      return false;
    }
  }
  return true;
}

function isPlayerTranscript(value: unknown): boolean {
  if (
    !isExactRecord(value, ["available", "messages"]) ||
    typeof value.available !== "boolean" ||
    !Array.isArray(value.messages) ||
    value.messages.length > MAX_TRANSCRIPT_MESSAGES
  ) {
    return false;
  }
  if (!value.messages.every(isPlayerTranscriptMessage)) return false;
  if (!value.available) return value.messages.length === 0;
  let previousSequence = 0;
  const ids = new Set<string>();
  for (const message of value.messages) {
    if (message.sequence <= previousSequence || ids.has(message.id)) return false;
    previousSequence = message.sequence;
    ids.add(message.id);
  }
  return true;
}

function isPlayerTranscriptMessage(value: unknown): value is PlayerTranscriptMessage {
  return (
    isExactRecord(value, ["id", "sequence", "role", "text"], ["author"]) &&
    typeof value.id === "string" &&
    TRANSCRIPT_ID_PATTERN.test(value.id) &&
    isPositiveInteger(value.sequence) &&
    (value.role === "user" || value.role === "assistant") &&
    isBoundedString(value.text, MAX_PLAYER_TEXT_BYTES) &&
    (!Object.hasOwn(value, "author") || isBoundedString(value.author, 1024))
  );
}

function isPlayerCombat(value: unknown): boolean {
  if (
    !isExactRecord(value, ["available", "active", "round", "phase", "turn_order"]) ||
    typeof value.available !== "boolean" ||
    typeof value.active !== "boolean" ||
    !Array.isArray(value.turn_order) ||
    value.turn_order.length > MAX_COMBATANTS
  ) {
    return false;
  }
  if (!value.turn_order.every(isPlayerCombatant)) return false;
  if (!value.available) {
    return (
      value.active &&
      value.round === null &&
      value.phase === null &&
      value.turn_order.length === 0
    );
  }
  if (!value.active) {
    return value.round === null && value.phase === null && value.turn_order.length === 0;
  }
  return (
    isPositiveInteger(value.round) &&
    (value.phase === null || value.phase === "PC_PHASE" || value.phase === "ENEMY_PHASE")
  );
}

function isPlayerCombatant(value: unknown): boolean {
  return (
    isExactRecord(value, ["name", "kind", "initiative", "status"]) &&
    isCharacterName(value.name) &&
    (value.kind === "pc" || value.kind === "npc" || value.kind === "monster") &&
    isSafeInteger(value.initiative) &&
    value.initiative >= -1000 &&
    value.initiative <= 1000 &&
    (value.status === "alive" ||
      value.status === "unconscious" ||
      value.status === "dead" ||
      value.status === "defeated")
  );
}

function isIntegerRecord(value: unknown, allowedFields: ReadonlySet<string>): boolean {
  if (!isRecord(value)) return false;
  return Object.entries(value).every(
    ([field, item]) => allowedFields.has(field) && isSafeInteger(item),
  );
}

function isStringList(
  value: unknown,
  maxItems: number,
  maxBytes: number,
  allowedFields?: ReadonlySet<string>,
): boolean {
  return (
    Array.isArray(value) &&
    value.length <= maxItems &&
    value.every(
      (item) =>
        isBoundedString(item, maxBytes) &&
        (allowedFields === undefined || allowedFields.has(item)),
    )
  );
}

function isCharacterName(value: unknown): value is string {
  return (
    isBoundedString(value, 128) &&
    value.trim() === value &&
    value.length > 0 &&
    value !== "." &&
    value !== ".." &&
    !value.includes("/") &&
    !value.includes("\\") &&
    !/[\p{C}]/u.test(value)
  );
}

function isIdentity(value: unknown): value is string {
  return typeof value === "string" && IDENTITY_PATTERN.test(value);
}

function isRequestId(value: unknown): value is string {
  return typeof value === "string" && REQUEST_ID_PATTERN.test(value);
}

function isErrorCode(value: unknown): value is string {
  return typeof value === "string" && ERROR_CODE_PATTERN.test(value);
}

function isBoundedString(value: unknown, maxBytes: number): value is string {
  if (typeof value !== "string") return false;
  try {
    return new TextEncoder().encode(value).byteLength <= maxBytes;
  } catch {
    return false;
  }
}

function isSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function isNonnegativeInteger(value: unknown): value is number {
  return isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isNonnegativeInteger(value) && value > 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isExactRecord(
  value: unknown,
  requiredKeys: readonly string[],
  optionalKeys: readonly string[] = [],
): value is Record<string, unknown> {
  if (!isRecord(value)) return false;
  const allowedKeys = new Set([...requiredKeys, ...optionalKeys]);
  const keys = Object.keys(value);
  return (
    requiredKeys.every((key) => Object.hasOwn(value, key)) &&
    keys.every((key) => allowedKeys.has(key))
  );
}

function isWithinJsonBytes(value: unknown, maxBytes: number): boolean {
  try {
    const json = JSON.stringify(value);
    return typeof json === "string" && new TextEncoder().encode(json).byteLength <= maxBytes;
  } catch {
    return false;
  }
}
