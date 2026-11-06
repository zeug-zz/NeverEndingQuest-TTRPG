// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0
/// <reference types="vitest/config" />

import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/static/player/",
  build: {
    assetsDir: ".",
    modulePreload: { polyfill: false },
    sourcemap: false,
    rolldownOptions: {
      output: {
        entryFileNames: "[name]-[hash].js",
        chunkFileNames: "[name]-[hash].js",
        assetFileNames: "[name]-[hash][extname]"
      }
    }
  },
  test: {
    environment: "jsdom"
  }
});
