// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { createAgentRunCredentials, rejectInheritedAgentCredentials } from "./agent-run-credentials.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const PYTHON = join(REPOSITORY_ROOT, ".venv", "bin", "python");
const VERIFIER = "neq-scrypt$v1$32768$8$1$0123456789abcdef0123456789abcdef$0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

test("agent-run passes the password only on verifier child stdin and strips inherited owner credentials", () => {
  let observed = null;
  const environment = {
    PATH: process.env.PATH ?? "",
    NEQ_N2_PLAYER_PASSWORD: "",
    NEQ_PLAYER_PASSWORD_VERIFIER: "",
    OPENAI_API_KEY: "must-not-enter-the-verifier-process",
  };
  const credentials = createAgentRunCredentials({
    pythonPath: PYTHON,
    repositoryRoot: REPOSITORY_ROOT,
    environment,
    randomBytesImpl: (size) => Buffer.alloc(size, 0x61),
    spawnSyncImpl: (command, args, options) => {
      observed = { command, args, options };
      return { error: null, status: 0, signal: null, stdout: `${VERIFIER}\n` };
    },
  });

  assert.ok(credentials.password.length >= 32);
  assert.equal(credentials.verifier, VERIFIER);
  assert.equal(observed.command, PYTHON);
  assert.equal(observed.args[0], "-c");
  assert.ok(observed.args[1].includes("make_verifier"));
  assert.equal(observed.args.includes(credentials.password), false);
  assert.equal(observed.options.input, credentials.password);
  assert.deepEqual(observed.options.env, { PYTHONPATH: REPOSITORY_ROOT });
  assert.equal(observed.options.cwd, REPOSITORY_ROOT);
});

test("agent-run rejects conflicting inherited owner credentials before randomness or child creation", () => {
  for (const name of ["NEQ_N2_PLAYER_PASSWORD", "NEQ_PLAYER_PASSWORD_VERIFIER"]) {
    let randomCalled = false;
    let childCalled = false;
    const environment = { [name]: "owner-secret-sentinel" };
    assert.throws(() => createAgentRunCredentials({
      pythonPath: PYTHON,
      repositoryRoot: REPOSITORY_ROOT,
      environment,
      randomBytesImpl: () => { randomCalled = true; throw new Error("unexpected randomness"); },
      spawnSyncImpl: () => { childCalled = true; throw new Error("unexpected child"); },
    }), /refuses inherited owner player credentials/);
    assert.equal(randomCalled, false);
    assert.equal(childCalled, false);
  }
  assert.throws(
    () => rejectInheritedAgentCredentials({ NEQ_N2_PLAYER_PASSWORD: "owner-secret-sentinel" }),
    /refuses inherited owner player credentials/,
  );
});

test("agent verifier is accepted by the real player auth verifier without printing either value", () => {
  const environment = { ...process.env };
  delete environment.NEQ_N2_PLAYER_PASSWORD;
  delete environment.NEQ_PLAYER_PASSWORD_VERIFIER;
  const credentials = createAgentRunCredentials({
    pythonPath: PYTHON,
    repositoryRoot: REPOSITORY_ROOT,
    environment,
  });
  const verification = spawnSync(PYTHON, ["-c", [
    "import sys",
    "from web.extensions.player.auth import parse_verifier",
    "password, verifier = sys.stdin.read().split('\\n', 1)",
    "parsed = parse_verifier(verifier)",
    "sys.stdout.write('VALID' if parsed is not None and parsed.verify(password) else 'INVALID')",
  ].join("\n")], {
    cwd: REPOSITORY_ROOT,
    env: { ...environment, PYTHONPATH: REPOSITORY_ROOT },
    encoding: "utf8",
    input: `${credentials.password}\n${credentials.verifier}`,
    timeout: 30_000,
  });

  assert.equal(verification.status, 0);
  assert.equal(verification.stdout, "VALID");
  assert.equal(verification.stdout.includes(credentials.password), false);
  assert.equal(verification.stdout.includes(credentials.verifier), false);
  assert.equal(verification.stderr.includes(credentials.password), false);
  assert.equal(verification.stderr.includes(credentials.verifier), false);
});
