// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0
/// <reference types="vitest/config" />

import { defineConfig } from "vitest/config";

// The player always uses its page origin; remove the localhost literal while
// preserving Engine.IO's offline detection instead of its localhost dev exception.
const engineIoSameOriginHostReferences = {
  name: "player-browser-only-engine-io-host-references",
  enforce: "pre" as const,
  transform(source: string, id: string) {
    if (!id.includes("/node_modules/engine.io-client/build/esm/socket.js")) {
      return null;
    }
    const withoutFallback = source.replace(
      /\(\s*typeof location !== "undefined"\s*\?\s*location\.hostname\s*:\s*"localhost"\s*\)/,
      "location.hostname",
    );
    const updated = withoutFallback.replace(
      'this.hostname !== "localhost"',
      "true",
    );
    if (withoutFallback === source || updated === withoutFallback) {
      throw new Error("Pinned Engine.IO browser module host references changed");
    }
    return updated;
  },
};

export default defineConfig({
  base: "/static/player/",
  plugins: [engineIoSameOriginHostReferences],
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
