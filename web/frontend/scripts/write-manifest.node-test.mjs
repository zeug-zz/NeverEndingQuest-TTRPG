// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import assert from "node:assert/strict";
import test from "node:test";
import {
  ASSET_ID_PATTERN,
  MAX_ASSET_BYTES,
  MAX_ASSET_COUNT,
  calculateClientBuildId,
  contentTypeForFile,
  hasContentHashedName,
  isPathWithinRoot,
  serializeManifest,
  validateAssetId,
  validateAssetSet
} from "./write-manifest.mjs";

const validAsset = (overrides = {}) => ({
  id: "index-A1b2C3d4.js",
  file: "index-A1b2C3d4.js",
  sha256: "a".repeat(64),
  bytes: 10,
  content_type: "text/javascript; charset=utf-8",
  ...overrides
});

test("accepts bounded ASCII asset IDs and rejects traversal or non-ASCII IDs", () => {
  assert.equal(ASSET_ID_PATTERN.test("A-1._x"), true);
  assert.equal(validateAssetId("A-1._x"), true);
  for (const id of ["", "../asset.js", "nested/asset.js", "asset\\name.js", "x".repeat(129), "caf\u00e9.js"]) {
    assert.equal(validateAssetId(id), false, id);
  }
});

test("accepts only the fixed MIME extension map and content-hashed names", () => {
  assert.equal(contentTypeForFile("bundle-AbCdEf12.js"), "text/javascript; charset=utf-8");
  assert.equal(contentTypeForFile("player-AbCdEf12.css"), "text/css; charset=utf-8");
  assert.equal(contentTypeForFile("portrait-AbCdEf12.svg"), "image/svg+xml");
  assert.equal(contentTypeForFile("portrait-AbCdEf12.png"), "image/png");
  assert.equal(contentTypeForFile("font-AbCdEf12.woff2"), "font/woff2");
  assert.equal(hasContentHashedName("bundle-AbCdEf12.js"), true);
  assert.equal(hasContentHashedName("index-BWPy-UGx.css"), true);
  assert.equal(hasContentHashedName("bundle.js"), false);
  assert.throws(() => contentTypeForFile("bundle-AbCdEf12.map"), /Unsupported/);
  assert.throws(() => contentTypeForFile("nested/bundle-AbCdEf12.js"), /flat/);
});

test("rejects invalid records, duplicate IDs, and out-of-bound asset sets", () => {
  assert.equal(validateAssetSet([validAsset()]), 10);
  assert.throws(() => validateAssetSet([validAsset({ id: "../escape.js" })]), /ID/);
  assert.throws(() => validateAssetSet([validAsset({ sha256: "short" })]), /digest/);
  assert.throws(() => validateAssetSet([validAsset({ bytes: -1 })]), /byte length/);
  assert.throws(() => validateAssetSet([
    validAsset(),
    validAsset()
  ]), /Duplicate/);
  assert.throws(() => validateAssetSet(Array.from(
    { length: MAX_ASSET_COUNT + 1 },
    (_, index) => validAsset({
      id: `bundle-${String(index).padStart(8, "0")}.js`,
      file: `bundle-${String(index).padStart(8, "0")}.js`
    })
  )), /count/);
  assert.throws(() => validateAssetSet([
    validAsset({ bytes: MAX_ASSET_BYTES + 1 })
  ]), /bytes/);
});

test("calculates a deterministic build ID from sorted asset digests", () => {
  const first = validAsset({ id: "a-A1b2C3d4.js", file: "a-A1b2C3d4.js", sha256: "a".repeat(64) });
  const second = validAsset({ id: "b-B1c2D3e4.css", file: "b-B1c2D3e4.css", sha256: "b".repeat(64) });
  assert.equal(calculateClientBuildId([first, second]), calculateClientBuildId([second, first]));
  assert.notEqual(calculateClientBuildId([first, second]), calculateClientBuildId([
    first,
    { ...second, sha256: "c".repeat(64) }
  ]));
});

test("checks resolved file containment and serializes sorted ASCII JSON with newline", () => {
  assert.equal(isPathWithinRoot("web/frontend/dist", "web/frontend/dist/index.html"), true);
  assert.equal(isPathWithinRoot("web/frontend/dist", "web/frontend/secrets.json"), false);

  const manifest = {
    manifest_version: 1,
    protocol_version: 1,
    client_build_id: "a".repeat(32),
    shell: {
      file: "index.html",
      sha256: "b".repeat(64),
      bytes: 1,
      content_type: "text/html; charset=utf-8"
    },
    assets: {
      "z-Z1b2C3d4.js": { file: "z-Z1b2C3d4.js", sha256: "d".repeat(64), bytes: 2, content_type: "text/javascript; charset=utf-8" },
      "a-A1b2C3d4.js": { file: "a-A1b2C3d4.js", sha256: "c".repeat(64), bytes: 3, content_type: "text/javascript; charset=utf-8" }
    }
  };
  const serialized = serializeManifest(manifest);
  assert.equal(serialized.endsWith("\n"), true);
  assert.equal(serialized.indexOf('"a-A1b2C3d4.js"') < serialized.indexOf('"z-Z1b2C3d4.js"'), true);
  assert.match(serialized, /^[\x00-\x7F]+$/);
});
