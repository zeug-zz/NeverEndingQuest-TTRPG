// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import {
  existsSync,
  mkdtempSync,
  mkdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createN2BrowserInstances, hasN2BrowserVersions, N2_PLAYWRIGHT_PROJECT } from "./browser-contract.mjs";
import { evidenceDirectory, redactValue, sanitizeText } from "./evidence.ts";
import { assertGatePortsFree, validateManagedSandboxRoot } from "./managed-host.mjs";
import {
  corruptSandboxBundle,
  copySandboxDistFromBackup,
  moveSandboxDistToBackup,
  readVerifiedBundleSnapshot,
  restoreSandboxDist,
} from "./managed-lifecycle.mjs";

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const PROJECT_TMP = join(PROJECT_ROOT, "tmp");

test("browser evidence contract requires Chrome and Firefox instances plus the separate Chrome host context", () => {
  const instances = createN2BrowserInstances("Chrome 132.0", "Firefox 135.0");
  assert.equal(N2_PLAYWRIGHT_PROJECT, "chrome-firefox-pair");
  assert.equal(instances.player_a.name, "Chrome");
  assert.equal(instances.player_a.engine, "chromium");
  assert.equal(instances.player_a.channel, "chrome");
  assert.equal(instances.player_a.version, "Chrome 132.0");
  assert.equal(instances.player_b.name, "Firefox");
  assert.equal(instances.player_b.engine, "firefox");
  assert.equal(instances.player_b.version, "Firefox 135.0");
  assert.equal(instances.host_ui.name, "Chrome");
  assert.equal(instances.host_ui.version, "Chrome 132.0");
  assert.match(instances.host_ui.context, /separate BrowserContext/);
  assert.equal(hasN2BrowserVersions(instances), true);
  assert.equal(hasN2BrowserVersions(createN2BrowserInstances(null, "Firefox 135.0")), false);
  assert.equal(hasN2BrowserVersions({ ...instances, host_ui: { ...instances.host_ui, version: "other" } }), false);
});

test("structured and console evidence redact password and session secrets", () => {
  const secret = "n2-secret-password-219";
  const previousPassword = process.env.NEQ_N2_PLAYER_PASSWORD;
  process.env.NEQ_N2_PLAYER_PASSWORD = secret;
  try {
    const safe = redactValue({
      password: secret,
      nested: {
        "set-cookie": "neq_player_session=session-secret; HttpOnly",
        message: `password=${secret}\nAuthorization: Bearer authorization-secret\nneq_player_prelogin=prelogin-secret`,
      },
    });
    const serialized = JSON.stringify(safe);
    for (const value of [secret, "session-secret", "authorization-secret", "prelogin-secret"]) {
      assert.equal(serialized.includes(value), false, `evidence retained ${value}`);
    }
    assert.equal(safe.password, "[REDACTED]");
    assert.match(sanitizeText("neq_player_session=session-secret"), /\[REDACTED\]/);
  } finally {
    if (previousPassword === undefined) delete process.env.NEQ_N2_PLAYER_PASSWORD;
    else process.env.NEQ_N2_PLAYER_PASSWORD = previousPassword;
  }
});

test("evidence writer rejects a destination outside repository tmp", () => {
  const previousDirectory = process.env.NEQ_N2_EVIDENCE_DIR;
  process.env.NEQ_N2_EVIDENCE_DIR = "plans/n2-evidence-test";
  try {
    assert.throws(evidenceDirectory, /below this repository's tmp/);
  } finally {
    if (previousDirectory === undefined) delete process.env.NEQ_N2_EVIDENCE_DIR;
    else process.env.NEQ_N2_EVIDENCE_DIR = previousDirectory;
  }
});

test("managed host accepts only the exact non-symlink tmp/combat_capture root", () => {
  const fixture = makeSandboxFixture();
  try {
    assert.equal(
      validateManagedSandboxRoot(fixture.repositoryRoot),
      fixture.sandboxRoot,
    );
    assert.throws(
      () => validateManagedSandboxRoot(fixture.repositoryRoot, join(fixture.repositoryRoot, "characters")),
      /only this repository's tmp\/combat_capture/,
    );

    const realSandbox = join(fixture.repositoryRoot, "tmp", "real-combat-capture");
    const expectedSandbox = join(fixture.repositoryRoot, "tmp", "combat_capture");
    rmSync(expectedSandbox, { recursive: true, force: true });
    symlinkSync(realSandbox, expectedSandbox, "dir");
    assert.throws(
      () => validateManagedSandboxRoot(fixture.repositoryRoot),
      /must not traverse symlinks/,
    );
  } finally {
    rmSync(fixture.testRoot, { recursive: true, force: true });
  }
});

test("managed bundle swap, corruption, restore, and digest verification stay sandbox-local", () => {
  const fixture = makeSandboxFixture();
  try {
    const original = readVerifiedBundleSnapshot(fixture.repositoryRoot, fixture.sandboxRoot);
    const missingBackup = moveSandboxDistToBackup(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      fixture.evidenceRoot,
      "missing-bundle",
    );
    assert.equal(exists(join(fixture.sandboxRoot, "web", "frontend", "dist")), false);
    restoreSandboxDist(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      missingBackup.backupPath,
      missingBackup.snapshot,
    );
    assert.deepEqual(readVerifiedBundleSnapshot(fixture.repositoryRoot, fixture.sandboxRoot), original);

    const brokenBackup = moveSandboxDistToBackup(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      fixture.evidenceRoot,
      "broken-bundle",
    );
    copySandboxDistFromBackup(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      brokenBackup.backupPath,
    );
    const corruptedAsset = corruptSandboxBundle(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      brokenBackup.snapshot,
    );
    assert.throws(
      () => readVerifiedBundleSnapshot(fixture.repositoryRoot, fixture.sandboxRoot),
      /does not match its manifest digest/,
    );
    assert.equal(corruptedAsset, "player-12345678.js");
    restoreSandboxDist(
      fixture.repositoryRoot,
      fixture.sandboxRoot,
      brokenBackup.backupPath,
      brokenBackup.snapshot,
    );
    assert.deepEqual(readVerifiedBundleSnapshot(fixture.repositoryRoot, fixture.sandboxRoot), original);
    assert.equal(exists(join(fixture.repositoryRoot, "web", "frontend", "dist")), false);
  } finally {
    rmSync(fixture.testRoot, { recursive: true, force: true });
  }
});

test("managed port-free preflight checks only 8360 and 8370 and fails closed", async () => {
  const observed = [];
  assert.deepEqual(await assertGatePortsFree(async (port) => {
    observed.push(port);
    return true;
  }), [8360, 8370]);
  assert.deepEqual(observed, [8360, 8370]);
  await assert.rejects(
    assertGatePortsFree(async (port) => port !== 8370),
    /occupied: 8370/,
  );
});

function makeSandboxFixture() {
  const testRoot = mkdtempSync(join(PROJECT_TMP, "n2-managed-test-"));
  const repositoryRoot = join(testRoot, "fixture-repo");
  const sandboxRoot = join(repositoryRoot, "tmp", "combat_capture");
  const distRoot = join(sandboxRoot, "web", "frontend", "dist");
  const evidenceRoot = join(repositoryRoot, "tmp", "evidence");
  mkdirSync(distRoot, { recursive: true });
  mkdirSync(evidenceRoot, { recursive: true });
  writeFileSync(join(sandboxRoot, "run_web.py"), "# fixture\n");
  writeFileSync(join(sandboxRoot, "config.py"), "WEB_PORT = 8360\n");
  const shell = Buffer.from("<!doctype html><title>fixture</title>\n");
  const asset = Buffer.from("export const fixture = true;\n");
  writeFileSync(join(distRoot, "index.html"), shell);
  writeFileSync(join(distRoot, "player-12345678.js"), asset);
  const manifest = {
    manifest_version: 1,
    protocol_version: 1,
    client_build_id: "fixture-build",
    shell: {
      file: "index.html",
      sha256: hash(shell),
      bytes: shell.byteLength,
      content_type: "text/html; charset=utf-8",
    },
    assets: {
      "player-12345678.js": {
        file: "player-12345678.js",
        sha256: hash(asset),
        bytes: asset.byteLength,
        content_type: "text/javascript; charset=utf-8",
      },
    },
  };
  writeFileSync(join(distRoot, "player-manifest.json"), `${JSON.stringify(manifest)}\n`);
  return { testRoot, repositoryRoot, sandboxRoot, evidenceRoot };
}

function hash(contents) {
  return createHash("sha256").update(contents).digest("hex");
}

function exists(path) {
  return existsSync(path);
}
