// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export const N2_PLAYWRIGHT_PROJECT = "chrome-firefox-pair";

export function createN2BrowserInstances(chromeVersion = null, firefoxVersion = null) {
  return {
    player_a: {
      name: "Chrome",
      version: chromeVersion,
      engine: "chromium",
      channel: "chrome",
    },
    player_b: {
      name: "Firefox",
      version: firefoxVersion,
      engine: "firefox",
    },
    host_ui: {
      name: "Chrome",
      version: chromeVersion,
      context: "separate BrowserContext in the Player A Chrome instance",
    },
  };
}

export function hasN2BrowserVersions(browserInstances) {
  if (browserInstances === null || typeof browserInstances !== "object") return false;
  const validVersions = ["player_a", "player_b", "host_ui"].every((role) => {
    const browser = browserInstances[role];
    return browser !== null && typeof browser === "object" &&
      typeof browser.name === "string" && browser.name.length > 0 &&
      typeof browser.version === "string" && browser.version.length > 0;
  });
  return validVersions && browserInstances.player_a.name === "Chrome" &&
    browserInstances.player_b.name === "Firefox" &&
    browserInstances.host_ui.name === "Chrome" &&
    browserInstances.host_ui.version === browserInstances.player_a.version;
}
