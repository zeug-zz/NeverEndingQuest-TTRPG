// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0
// Manifest schema: manifest_version, protocol_version, client_build_id,
// shell { file, sha256, bytes, content_type }, assets keyed by flat asset ID
// with { file, sha256, bytes, content_type }. JSON keys are sorted and the
// file ends with one newline. client_build_id is the first 32 hex characters
// of SHA-256 over sorted "asset-id<TAB>sha256<LF>" rows. It excludes the shell
// digest because the shell contains this ID; the shell digest is calculated
// only after the ID has been injected.

import { createHash } from "node:crypto";
import {
  readFile,
  readdir,
  realpath,
  stat,
  writeFile
} from "node:fs/promises";
import { dirname, extname, isAbsolute, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

export const ASSET_ID_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;
export const MAX_ASSET_COUNT = 64;
export const MAX_ASSET_BYTES = 8 * 1024 * 1024;
export const PROTOCOL_VERSION = 1;

export const CONTENT_TYPES = Object.freeze({
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2"
});

const HEX_DIGEST_PATTERN = /^[a-f0-9]{64}$/;
const CONTENT_HASH_PATTERN = /^[A-Za-z0-9_-]{8,}$/;
const BUILD_ID_PLACEHOLDER = "__NEQ_CLIENT_BUILD_ID__";
const FORBIDDEN_OUTPUT_PATTERN = /localhost|127\.0\.0\.1|\/Users\/|sourceMappingURL/i;
const SCRIPT_OPEN_TAG_PATTERN = /<script\b[^>]*>/gi;

export function validateAssetId(assetId) {
  return typeof assetId === "string" && ASSET_ID_PATTERN.test(assetId);
}

export function contentTypeForFile(fileName) {
  if (typeof fileName !== "string" || fileName.includes("/") || fileName.includes("\\")) {
    throw new Error("Player asset file must be a flat filename");
  }
  const contentType = CONTENT_TYPES[extname(fileName).toLowerCase()];
  if (!contentType) {
    throw new Error(`Unsupported player asset extension: ${extname(fileName) || "<none>"}`);
  }
  return contentType;
}

export function hasContentHashedName(fileName) {
  if (typeof fileName !== "string" || fileName.includes("/") || fileName.includes("\\")) {
    return false;
  }
  const extension = extname(fileName);
  const baseName = fileName.slice(0, -extension.length);
  const hashSeparator = baseName.indexOf("-");
  return hashSeparator > 0
    && CONTENT_HASH_PATTERN.test(baseName.slice(hashSeparator + 1));
}

export function isPathWithinRoot(rootPath, candidatePath) {
  const pathFromRoot = relative(resolve(rootPath), resolve(candidatePath));
  return pathFromRoot !== ""
    && pathFromRoot !== ".."
    && !pathFromRoot.startsWith(`..${sep}`)
    && !isAbsolute(pathFromRoot);
}

export function validateAssetSet(assets) {
  if (!Array.isArray(assets)) {
    throw new Error("Player assets must be an array");
  }
  if (assets.length > MAX_ASSET_COUNT) {
    throw new Error(`Player asset count exceeds ${MAX_ASSET_COUNT}`);
  }

  const seenIds = new Set();
  let totalBytes = 0;
  for (const asset of assets) {
    if (!asset || typeof asset !== "object") {
      throw new Error("Player asset record is invalid");
    }
    const { id, file, sha256, bytes, content_type: contentType } = asset;
    if (!validateAssetId(id)) {
      throw new Error("Player asset ID is invalid");
    }
    if (file !== id || !hasContentHashedName(file)) {
      throw new Error(`Player asset filename is not flat and content-hashed: ${String(file)}`);
    }
    if (seenIds.has(id)) {
      throw new Error(`Duplicate player asset ID: ${id}`);
    }
    seenIds.add(id);
    if (!HEX_DIGEST_PATTERN.test(sha256)) {
      throw new Error(`Player asset digest is invalid: ${id}`);
    }
    if (!Number.isSafeInteger(bytes) || bytes < 0) {
      throw new Error(`Player asset byte length is invalid: ${id}`);
    }
    if (contentTypeForFile(file) !== contentType) {
      throw new Error(`Player asset content type is invalid: ${id}`);
    }
    totalBytes += bytes;
    if (!Number.isSafeInteger(totalBytes) || totalBytes > MAX_ASSET_BYTES) {
      throw new Error(`Player asset bytes exceed ${MAX_ASSET_BYTES}`);
    }
  }
  return totalBytes;
}

export function calculateClientBuildId(assets) {
  const rows = [...assets]
    .sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0)
    .map(({ id, sha256 }) => `${id}\t${sha256}\n`)
    .join("");
  return createHash("sha256").update(rows, "ascii").digest("hex").slice(0, 32);
}

export function serializeManifest(manifest) {
  const orderedAssets = Object.fromEntries(
    Object.entries(manifest.assets).sort(([left], [right]) => (
      left < right ? -1 : left > right ? 1 : 0
    ))
  );
  const orderedManifest = {
    manifest_version: manifest.manifest_version,
    protocol_version: manifest.protocol_version,
    client_build_id: manifest.client_build_id,
    shell: {
      file: manifest.shell.file,
      sha256: manifest.shell.sha256,
      bytes: manifest.shell.bytes,
      content_type: manifest.shell.content_type
    },
    assets: orderedAssets
  };
  return `${JSON.stringify(orderedManifest, null, 2)}\n`;
}

function assertAscii(value, description) {
  if (/[\u0080-\uFFFF]/.test(value)) {
    throw new Error(`${description} must contain ASCII only`);
  }
}

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

export function assertNoInlineScripts(html) {
  for (const match of html.matchAll(SCRIPT_OPEN_TAG_PATTERN)) {
    const tag = match[0];
    const remainder = html.slice(match.index + tag.length);
    const closingTagIndex = remainder.search(/<\/script\s*[^>]*>/i);
    const body = closingTagIndex === -1 ? remainder : remainder.slice(0, closingTagIndex);
    if (!/\ssrc\s*=/i.test(tag) || body.trim() !== "") {
      throw new Error("Player shell must not contain inline scripts");
    }
  }
}

function assertSameOriginAssetTags(html) {
  const assetTagPattern = /<(?:script|link)\b[^>]*(?:src|href)\s*=\s*(["'])(.*?)\1[^>]*>/gi;
  for (const match of html.matchAll(assetTagPattern)) {
    const url = match[2];
    if (!url.startsWith("/static/player/") || url.includes("..") || url.includes("\\")) {
      throw new Error(`Player shell asset URL is not same-origin and bounded: ${url}`);
    }
    const id = url.slice("/static/player/".length);
    if (!validateAssetId(id)) {
      throw new Error(`Player shell asset URL has an invalid ID: ${url}`);
    }
  }
}

async function readBuildAssets(distPath) {
  const distRealPath = await realpath(distPath);
  const entries = await readdir(distRealPath, { withFileTypes: true });
  const assets = [];
  let totalBytes = 0;

  for (const entry of entries) {
    if (entry.name === "index.html" || entry.name === "player-manifest.json") {
      continue;
    }
    if (!entry.isFile() || entry.isSymbolicLink()) {
      throw new Error(`Player build output must be flat regular files: ${entry.name}`);
    }
    const id = entry.name;
    if (!validateAssetId(id)) {
      throw new Error(`Player asset ID is invalid: ${id}`);
    }
    if (!hasContentHashedName(id)) {
      throw new Error(`Player asset filename is not content-hashed: ${id}`);
    }
    const contentType = contentTypeForFile(id);
    const filePath = resolve(distRealPath, id);
    const fileRealPath = await realpath(filePath);
    if (!isPathWithinRoot(distRealPath, fileRealPath)) {
      throw new Error(`Player asset is outside dist: ${id}`);
    }
    const fileInfo = await stat(fileRealPath);
    if (!fileInfo.isFile()) {
      throw new Error(`Player asset is not a regular file: ${id}`);
    }
    if (!Number.isSafeInteger(fileInfo.size) || fileInfo.size < 0) {
      throw new Error(`Player asset byte length is invalid: ${id}`);
    }
    totalBytes += fileInfo.size;
    if (assets.length >= MAX_ASSET_COUNT) {
      throw new Error(`Player asset count exceeds ${MAX_ASSET_COUNT}`);
    }
    if (!Number.isSafeInteger(totalBytes) || totalBytes > MAX_ASSET_BYTES) {
      throw new Error(`Player asset bytes exceed ${MAX_ASSET_BYTES}`);
    }
    const content = await readFile(fileRealPath);
    assets.push({
      id,
      file: id,
      sha256: sha256(content),
      bytes: content.byteLength,
      content_type: contentType
    });
  }

  assets.sort((left, right) => left.id < right.id ? -1 : left.id > right.id ? 1 : 0);
  validateAssetSet(assets);
  return { assets, distRealPath };
}

export async function writeManifest(distPath) {
  const { assets, distRealPath } = await readBuildAssets(distPath);
  const assetIndex = Object.fromEntries(assets.map((asset) => [asset.id, {
    file: asset.file,
    sha256: asset.sha256,
    bytes: asset.bytes,
    content_type: asset.content_type
  }]));
  const clientBuildId = calculateClientBuildId(assets);
  const shellPath = resolve(distRealPath, "index.html");
  const shellRealPath = await realpath(shellPath);
  if (!isPathWithinRoot(distRealPath, shellRealPath)) {
    throw new Error("Player shell is outside dist");
  }
  const shellInfo = await stat(shellRealPath);
  if (!shellInfo.isFile()) {
    throw new Error("Player shell is not a regular file");
  }

  let shell = (await readFile(shellRealPath)).toString("utf8");
  const placeholderCount = shell.split(BUILD_ID_PLACEHOLDER).length - 1;
  if (placeholderCount !== 1) {
    throw new Error("Player shell must contain exactly one build ID placeholder");
  }
  if (!/<meta\s+name=["']neq-client-build["']\s+content=["']__NEQ_CLIENT_BUILD_ID__["']\s*\/?\s*>/i.test(shell)) {
    throw new Error("Player shell build ID metadata is missing or invalid");
  }
  if (!/<meta\s+name=["']neq-protocol-version["']\s+content=["']1["']\s*\/?\s*>/i.test(shell)) {
    throw new Error("Player shell protocol version metadata is missing or invalid");
  }
  shell = shell.replace(BUILD_ID_PLACEHOLDER, clientBuildId);
  assertNoInlineScripts(shell);
  assertSameOriginAssetTags(shell);
  assertAscii(shell, "Player shell");

  const shellBuffer = Buffer.from(shell, "utf8");
  await writeFile(shellRealPath, shellBuffer);
  const outputs = [shell, ...await Promise.all(assets.map(async (asset) => (
    (await readFile(resolve(distRealPath, asset.file))).toString("utf8")
  )))];
  if (outputs.some((output) => FORBIDDEN_OUTPUT_PATTERN.test(output))) {
    throw new Error("Player build contains a host path, loopback hostname, or source map marker");
  }

  const manifest = {
    manifest_version: 1,
    protocol_version: PROTOCOL_VERSION,
    client_build_id: clientBuildId,
    shell: {
      file: "index.html",
      sha256: sha256(shellBuffer),
      bytes: shellBuffer.byteLength,
      content_type: "text/html; charset=utf-8"
    },
    assets: assetIndex
  };
  const manifestText = serializeManifest(manifest);
  assertAscii(manifestText, "Player manifest");
  await writeFile(resolve(distRealPath, "player-manifest.json"), manifestText, "ascii");
  return manifest;
}

async function main() {
  const scriptDirectory = dirname(fileURLToPath(import.meta.url));
  const distPath = resolve(scriptDirectory, "../dist");
  await writeManifest(distPath);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(`Player manifest build failed: ${error.message}`);
    process.exitCode = 1;
  });
}
