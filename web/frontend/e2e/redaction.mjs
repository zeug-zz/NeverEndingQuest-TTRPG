// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

const SENSITIVE_FIELDS = new Set([
  "cookie",
  "set-cookie",
  "authorization",
  "password",
  "verifier",
  "password_verifier",
  "password-verifier",
  "neq_player_password_verifier",
  "neq-player-password-verifier",
  "csrf_token",
  "csrf-token",
  "x-neq-player-session",
  "neq_player_session",
  "neq_player_prelogin",
  "cookies",
]);

const SENSITIVE_TEXT_PATTERN =
  /(set-cookie|cookie|authorization|password(?:[_-]?verifier)?|verifier|csrf[_-]?token)\s*[:=]\s*[^\r\n]*/gi;

export function isSensitiveEvidenceField(key) {
  return typeof key === "string" && SENSITIVE_FIELDS.has(key.toLowerCase());
}

export function redactEvidenceText(value, secrets = [], maxLength = 4096) {
  let result = String(value);
  for (const secret of secrets) {
    if (typeof secret === "string" && secret.length > 0) {
      result = result.split(secret).join("[REDACTED]");
    }
  }
  return result
    .replace(SENSITIVE_TEXT_PATTERN, "$1=[REDACTED]")
    .replace(/(neq[_-]player[_-](?:session|prelogin)\s*[:=]\s*)[^,;\s]+/gi, "$1[REDACTED]")
    .slice(0, maxLength);
}
