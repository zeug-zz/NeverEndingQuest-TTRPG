// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export type PlayerClientVersion = Readonly<{
  clientBuildId: string;
  protocolVersion: 1;
}>;

const CLIENT_BUILD_ID_PATTERN = /^[a-f0-9]{32}$/;

export function readPlayerClientVersion(
  documentRoot: ParentNode = document,
): PlayerClientVersion {
  const buildTag = documentRoot.querySelector<HTMLMetaElement>(
    'meta[name="neq-client-build"]',
  );
  const protocolTag = documentRoot.querySelector<HTMLMetaElement>(
    'meta[name="neq-protocol-version"]',
  );
  const clientBuildId = buildTag?.content;
  const protocolText = protocolTag?.content;

  if (!clientBuildId || !CLIENT_BUILD_ID_PATTERN.test(clientBuildId)) {
    throw new Error("Player client build metadata is missing or invalid");
  }
  if (protocolText !== "1") {
    throw new Error("Player protocol metadata is missing or unsupported");
  }

  return { clientBuildId, protocolVersion: 1 };
}
