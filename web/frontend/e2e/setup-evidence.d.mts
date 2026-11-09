// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export type SetupFailureStage =
  | "browser_launch"
  | "browser_context_create"
  | "page_create"
  | "player_shell_load"
  | "player_authentication"
  | "player_connection_wait"
  | "host_ui_load"
  | "client_metadata"
  | "setup_evidence_preflight"
  | "unknown";

export type SetupFailureRecord = Readonly<Record<string, unknown>>;
export type CredentialSafeScreenshotResult =
  | { status: "captured"; path: string }
  | { status: "skipped"; reason: string }
  | { status: "failed"; reason: string };

export class SetupStageError extends Error {
  stage: SetupFailureStage;
}

export const SETUP_FAILURE_SCHEMA: string;
export const SETUP_FAILURE_STAGES: readonly SetupFailureStage[];
export function withSetupStage<T>(stage: SetupFailureStage, operation: () => Promise<T>): Promise<T>;
export function settleSetupOperations(operations: readonly Promise<unknown>[]): Promise<void>;
export function setupFailureStage(error: unknown, fallback?: SetupFailureStage): SetupFailureStage;
export function createSetupFailureRecord(input: {
  stage: SetupFailureStage;
  observed: Record<string, unknown>;
  screenshots: readonly Record<string, unknown>[];
  requestDiagnostics?: Record<string, unknown>;
  recordedAt?: string;
}): SetupFailureRecord;
export function normalizeSetupFailureRecord(value: unknown): SetupFailureRecord | null;
export function captureSetupFailureBeforeClose(input: {
  stage: SetupFailureStage;
  observed: Record<string, unknown>;
  pages: readonly { role: string; page?: unknown }[];
  captureScreenshot: (page: unknown, role: string) => Promise<Record<string, unknown>>;
  flushRequestDiagnostics?: () => Promise<Record<string, unknown>> | Record<string, unknown>;
  writeRecord: (record: SetupFailureRecord) => Promise<void> | void;
  closePages: () => Promise<void> | void;
  recordedAt?: string;
}): Promise<{
  record: SetupFailureRecord;
  record_write_status: "written" | "failed";
  page_close_status: "closed" | "failed";
}>;
export function sanitizeSetupScreenshotPage(role: string, documentRef?: Document): { safe: boolean; reason: string | null };
export function captureCredentialSafeScreenshot(page: unknown, role: string, path: string, expectedOrigin: string): Promise<CredentialSafeScreenshotResult>;
export function readSetupFailureEvidence(path: string): { status: "missing" | "invalid" | "valid"; record: SetupFailureRecord | null };
export function normalizeRequestDiagnosticSummary(value: unknown): Record<string, unknown> | null;
