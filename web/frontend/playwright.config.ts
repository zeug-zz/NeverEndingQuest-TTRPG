// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { defineConfig } from "playwright/test";

export default defineConfig({
  testDir: "./e2e",
  projects: [{ name: "firefox", use: { browserName: "firefox" } }, { name: "webkit", use: { browserName: "webkit" } }]
});
