// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { afterEach, expect, it } from "vitest";
import { readPlayerClientVersion } from "./client-version";

afterEach(() => {
  document.head.replaceChildren();
});

it("exports the build and protocol values from the shell metadata", () => {
  const buildTag = document.createElement("meta");
  buildTag.name = "neq-client-build";
  buildTag.content = "0123456789abcdef0123456789abcdef";
  document.head.append(buildTag);

  const protocolTag = document.createElement("meta");
  protocolTag.name = "neq-protocol-version";
  protocolTag.content = "1";
  document.head.append(protocolTag);

  expect(readPlayerClientVersion()).toEqual({
    clientBuildId: "0123456789abcdef0123456789abcdef",
    protocolVersion: 1,
  });
});

it("rejects missing or malformed shell metadata", () => {
  expect(() => readPlayerClientVersion()).toThrow("build metadata");

  const buildTag = document.createElement("meta");
  buildTag.name = "neq-client-build";
  buildTag.content = "not-a-build-id";
  document.head.append(buildTag);
  const protocolTag = document.createElement("meta");
  protocolTag.name = "neq-protocol-version";
  protocolTag.content = "2";
  document.head.append(protocolTag);

  expect(() => readPlayerClientVersion()).toThrow("build metadata");
  buildTag.content = "0123456789abcdef0123456789abcdef";
  expect(() => readPlayerClientVersion()).toThrow("protocol metadata");
});
