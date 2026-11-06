// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export function isSensitiveEvidenceField(key: string): boolean;
export function redactEvidenceText(value: string, secrets?: readonly (string | undefined)[], maxLength?: number): string;
