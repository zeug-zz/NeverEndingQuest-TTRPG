// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";

const VERIFIER_PATTERN =
  /^neq-scrypt\$v1\$32768\$8\$1\$[a-f0-9]{32}\$[a-f0-9]{64}$/;
const VERIFIER_SCRIPT = [
  "import sys",
  "from web.extensions.player.auth import make_verifier",
  "sys.stdout.write(make_verifier(sys.stdin.read()))",
].join("\n");

export function rejectInheritedAgentCredentials(environment) {
  if (environment.NEQ_N2_PLAYER_PASSWORD || environment.NEQ_PLAYER_PASSWORD_VERIFIER) {
    throw new Error("--agent-run refuses inherited owner player credentials.");
  }
}

export function createAgentRunCredentials({
  pythonPath,
  repositoryRoot,
  environment = process.env,
  randomBytesImpl = randomBytes,
  spawnSyncImpl = spawnSync,
}) {
  rejectInheritedAgentCredentials(environment);
  const password = randomBytesImpl(32).toString("base64url");
  const pythonEnvironment = { PYTHONPATH: repositoryRoot };
  const generated = spawnSyncImpl(pythonPath, ["-c", VERIFIER_SCRIPT], {
    cwd: repositoryRoot,
    env: pythonEnvironment,
    encoding: "utf8",
    input: password,
    maxBuffer: 4096,
    timeout: 30_000,
    windowsHide: true,
  });
  if (generated.error || generated.status !== 0 || generated.signal !== null) {
    throw new Error("Agent-run player verifier generation failed.");
  }
  const verifier = generated.stdout.trim();
  if (!VERIFIER_PATTERN.test(verifier)) {
    throw new Error("Agent-run player verifier generation returned an invalid verifier.");
  }
  return { password, verifier };
}
