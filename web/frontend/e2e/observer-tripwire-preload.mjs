// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import childProcess from "node:child_process";
import crypto from "node:crypto";
import dns from "node:dns";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { syncBuiltinESMExports } from "node:module";

if (process.env.NEQ_OBSERVER_TRIPWIRES === "1") {
  let violations = 0;
  const originalRandomBytes = crypto.randomBytes.bind(crypto);
  const deny = (name) => (..._args) => {
    violations += 1;
    process.stderr.write(`TRIPWIRE ${name}\n`);
    throw new Error("Observer dry-run side effect denied.");
  };

  for (const name of [
    "writeFileSync", "appendFileSync", "writeSync", "mkdirSync", "renameSync", "copyFileSync",
    "rmSync", "rmdirSync", "unlinkSync", "symlinkSync", "linkSync", "truncateSync", "mkdtempSync",
    "createWriteStream",
  ]) {
    fs[name] = deny(`fs.${name}`);
  }
  for (const name of ["spawn", "spawnSync", "exec", "execSync", "execFile", "execFileSync", "fork"]) {
    childProcess[name] = deny(`child_process.${name}`);
  }
  for (const name of ["createServer", "createConnection", "connect"]) {
    net[name] = deny(`net.${name}`);
  }
  net.Server.prototype.listen = deny("net.Server.listen");
  net.Socket.prototype.connect = deny("net.Socket.connect");
  for (const name of ["lookup", "resolve", "resolve4", "resolve6", "lookupService"]) {
    dns[name] = deny(`dns.${name}`);
  }
  http.request = deny("http.request");
  http.get = deny("http.get");
  http.createServer = deny("http.createServer");
  https.request = deny("https.request");
  https.get = deny("https.get");
  https.createServer = deny("https.createServer");
  crypto.randomBytes = (size, ...args) => size === 32
    ? deny("crypto.randomBytes(32)")()
    : originalRandomBytes(size, ...args);
  crypto.randomUUID = deny("crypto.randomUUID");
  crypto.randomFillSync = deny("crypto.randomFillSync");
  globalThis.fetch = deny("fetch");
  syncBuiltinESMExports();
  process.on("exit", () => {
    if (violations > 0) process.exitCode = 79;
  });
}
