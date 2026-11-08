// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync, existsSync, readFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  DEFAULT_N2_BROWSER_SET,
  FIREFOX_UNAVAILABLE_REASON,
  createN2BrowserInstances,
  hasN2BrowserVersions,
  launchN2Browsers,
  parseN2BrowserSet,
} from "./browser-contract.mjs";
import { missingScenarioChecks, summarizeN2Results } from "./browser-coverage.mjs";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const N2_TMP = join(REPOSITORY_ROOT, "tmp", "n2");
const GATE_SCRIPT = fileURLToPath(new URL("./n2-gate.mjs", import.meta.url));
const SCENARIOS = JSON.parse(readFileSync(new URL("./scenarios.json", import.meta.url), "utf8"));

test("browser selector preserves the Chrome+Firefox default and accepts Chrome-only", () => {
  assert.equal(DEFAULT_N2_BROWSER_SET, "chrome+firefox");
  assert.deepEqual(parseN2BrowserSet(), ["chrome", "firefox"]);
  assert.deepEqual(parseN2BrowserSet("chrome"), ["chrome"]);
  assert.deepEqual(parseN2BrowserSet("chrome+firefox"), ["chrome", "firefox"]);
  assert.throws(() => parseN2BrowserSet("firefox"), /chrome or chrome\+firefox/);
  assert.throws(() => parseN2BrowserSet("chrome+webkit"), /chrome or chrome\+firefox/);
});

test("Chrome-only launch never invokes Firefox and keeps the host in Player A Chrome", async () => {
  const calls = [];
  const chrome = { close: async () => { calls.push("chrome-close"); } };
  const launched = await launchN2Browsers({
    chromium: { launch: async (options) => { calls.push(["chrome-launch", options]); return chrome; } },
    firefox: { launch: async () => { calls.push("firefox-launch"); throw new Error("must not launch"); } },
  }, parseN2BrowserSet("chrome"));

  assert.equal(launched.chromeBrowser, chrome);
  assert.equal(launched.firefoxBrowser, null);
  assert.equal(calls.some((call) => call === "firefox-launch"), false);
  assert.equal(calls[0][0], "chrome-launch");

  const instances = createN2BrowserInstances("Chrome 132.0", null, ["chrome"]);
  assert.equal(instances.player_b, null);
  assert.equal(instances.host_ui.version, "Chrome 132.0");
  assert.equal(hasN2BrowserVersions(instances, ["chrome"]), true);
  assert.equal(hasN2BrowserVersions(instances, ["chrome", "firefox"]), false);
});

test("scenario catalog classifies every Firefox-dependent check explicitly", () => {
  assert.ok(SCENARIOS.length > 0);
  for (const scenario of SCENARIOS) {
    assert.ok(Array.isArray(scenario.checks) && scenario.checks.length > 0, scenario.id);
    assert.ok(scenario.checks.some((check) => !check.requires_firefox), scenario.id);
    assert.ok(scenario.checks.every((check) =>
      typeof check.id === "string" && typeof check.description === "string" &&
      typeof check.requires_firefox === "boolean",
    ), scenario.id);
  }
  assert.equal(FIREFOX_UNAVAILABLE_REASON, "firefox-unavailable-in-sandbox");
});

test("Chrome PASS outcomes stay visible beside Firefox BLOCKED checks and cannot aggregate to PASS", () => {
  const result = summarizeN2Results([{
    id: "party-coherence",
    verdict: "BLOCKED",
    checks: [
      { id: "chrome-host-party-consistency", verdict: "PASS", observed: { party_size: 4 } },
      {
        id: "firefox-cross-browser-party-consistency",
        verdict: "BLOCKED",
        reason: FIREFOX_UNAVAILABLE_REASON,
      },
    ],
  }], ["chrome"]);

  assert.equal(result.verdict, "BLOCKED");
  assert.equal(result.counts.BLOCKED, 1);
  assert.equal(result.scenarios[0].checks[0].verdict, "PASS");
  assert.deepEqual(result.blocked, [{
    scenario_id: "party-coherence",
    check_id: "firefox-cross-browser-party-consistency",
    reason: FIREFOX_UNAVAILABLE_REASON,
  }]);
  assert.equal(result.browser_coverage_status, "incomplete");

  const inconsistentPass = summarizeN2Results([{
    id: "party-coherence",
    verdict: "PASS",
    checks: [
      { id: "chrome-host-party-consistency", verdict: "PASS" },
      {
        id: "firefox-cross-browser-party-consistency",
        verdict: "BLOCKED",
        reason: FIREFOX_UNAVAILABLE_REASON,
      },
    ],
  }], ["chrome", "firefox"]);
  assert.equal(inconsistentPass.verdict, "BLOCKED");

  const impossiblePass = summarizeN2Results([{
    id: "party-coherence",
    verdict: "PASS",
    checks: [{ id: "chrome-host-party-consistency", verdict: "PASS" }],
  }], ["chrome"]);
  assert.equal(impossiblePass.verdict, "BLOCKED");
  assert.equal(impossiblePass.blocked[0].reason, FIREFOX_UNAVAILABLE_REASON);
});

test("missing checks retain the exact Firefox block reason while missing Chrome checks fail", () => {
  const scenario = {
    id: "party-coherence",
    checks: [
      { id: "chrome-check", description: "Chrome check", requires_firefox: false },
      { id: "firefox-check", description: "Firefox check", requires_firefox: true },
    ],
  };
  const missing = missingScenarioChecks(scenario, ["chrome"], "FAIL", "scenario-result-missing");
  assert.deepEqual(missing.map((check) => [check.id, check.verdict, check.reason]), [
    ["chrome-check", "FAIL", "required-check-did-not-record-an-outcome"],
    ["firefox-check", "BLOCKED", FIREFOX_UNAVAILABLE_REASON],
  ]);
});

test("managed dry-runs for both party sizes and browser sets create no files, secrets, random credential, or child process", () => {
  mkdirSync(N2_TMP, { recursive: true });
  const scratch = mkdtempSync(join(N2_TMP, `browser-selection-${process.pid}-`));
  const hookPath = join(scratch, "no-child-hook.mjs");
  writeFileSync(hookPath, [
    'import childProcess from "node:child_process";',
    'import crypto from "node:crypto";',
    'import { syncBuiltinESMExports } from "node:module";',
    'childProcess.spawn = () => { throw new Error("dry-run-spawn-forbidden"); };',
    'childProcess.spawnSync = () => { throw new Error("dry-run-spawnSync-forbidden"); };',
    'crypto.randomBytes = () => { throw new Error("dry-run-secret-generation-forbidden"); };',
    'syncBuiltinESMExports();',
  ].join("\n"), { encoding: "ascii", flag: "wx" });

  try {
    for (const partySize of ["1", "4"]) {
      for (const browserSet of ["chrome", "chrome+firefox"]) {
        const absoluteEvidenceDir = join(scratch, `evidence-${partySize}-${browserSet.replaceAll("+", "-")}`);
        const evidenceDir = relative(REPOSITORY_ROOT, absoluteEvidenceDir);
        const args = [
          "--import", hookPath,
          GATE_SCRIPT,
          "--dry-run",
          "--manage-sandbox-host",
          "--party-size", partySize,
          "--evidence-dir", evidenceDir,
          "--browsers", browserSet,
          ...(browserSet === "chrome" ? ["--agent-run"] : []),
        ];
        const result = spawnSync(process.execPath, args, {
          cwd: REPOSITORY_ROOT,
          encoding: "utf8",
          env: {
            ...process.env,
            NEQ_N2_HOST_URL: "",
            NEQ_N2_PLAYER_URL: "",
            NEQ_N2_PLAYER_PASSWORD: browserSet === "chrome" ? "" : "owner-password-sentinel",
            NEQ_PLAYER_PASSWORD_VERIFIER: browserSet === "chrome" ? "" : "owner-verifier-sentinel",
          },
        });
        assert.equal(result.status, 0, `dry-run failed for ${partySize}/${browserSet}`);
        assert.equal(result.stdout.includes("owner-password-sentinel"), false);
        assert.equal(result.stdout.includes("owner-verifier-sentinel"), false);
        const plan = JSON.parse(result.stdout);
        assert.equal(plan.party_size, partySize);
        assert.equal(plan.browser_set, browserSet);
        assert.deepEqual(plan.browsers_run, []);
        assert.equal(plan.agent_run, browserSet === "chrome");
        assert.equal(existsSync(absoluteEvidenceDir), false);
        if (browserSet === "chrome") {
          assert.ok(plan.blocked.some((check) => check.reason === FIREFOX_UNAVAILABLE_REASON));
        } else {
          assert.deepEqual(plan.blocked, []);
        }
      }
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});

test("invalid browser and agent-run modes fail before endpoint, git, sandbox, or evidence I/O", () => {
  mkdirSync(N2_TMP, { recursive: true });
  const scratch = mkdtempSync(join(N2_TMP, `browser-invalid-${process.pid}-`));
  const cases = [
    { args: ["--browsers", "firefox"], pattern: /--browsers must be chrome or chrome\+firefox/ },
    { args: ["--agent-run", "--browsers", "chrome+firefox", "--manage-sandbox-host"], pattern: /--agent-run requires --browsers chrome/ },
    { args: ["--agent-run", "--browsers", "chrome"], pattern: /--agent-run requires --manage-sandbox-host/ },
    {
      args: ["--agent-run", "--browsers", "chrome", "--manage-sandbox-host"],
      pattern: /--agent-run refuses inherited owner player credentials/,
      environment: { NEQ_N2_PLAYER_PASSWORD: "owner-password-sentinel" },
    },
  ];
  try {
    for (const [index, scenario] of cases.entries()) {
      const evidenceDir = join(scratch, `evidence-${index}`);
      const result = spawnSync(process.execPath, [
        GATE_SCRIPT,
        ...scenario.args,
        "--evidence-dir",
        relative(REPOSITORY_ROOT, evidenceDir),
      ], {
        cwd: REPOSITORY_ROOT,
        encoding: "utf8",
        env: {
          ...process.env,
          NEQ_N2_HOST_URL: "",
          NEQ_N2_PLAYER_URL: "",
          ...(scenario.environment ?? {}),
        },
      });
      assert.equal(result.status, 2);
      assert.match(result.stderr, scenario.pattern);
      assert.equal(existsSync(evidenceDir), false);
    }
  } finally {
    rmSync(scratch, { recursive: true, force: true });
  }
});
