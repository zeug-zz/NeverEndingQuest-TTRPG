// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import type { Page } from "playwright";
import type { withSetupStage } from "./setup-evidence.mjs";

export type PlayerVersion = Readonly<{
  clientBuildId: string;
  protocolVersion: number;
}>;

export function loginPlayer(
  page: Page,
  options: {
    playerUrl: string;
    password: string;
    expect: typeof import("playwright/test").expect;
    withSetupStage: typeof withSetupStage;
  },
): Promise<PlayerVersion>;

export function readPlayerVersion(page: Page): Promise<PlayerVersion>;
