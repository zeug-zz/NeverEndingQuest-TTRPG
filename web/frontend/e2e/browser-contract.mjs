// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export const N2_PLAYWRIGHT_PROJECT = "chrome-firefox-pair";
export const DEFAULT_N2_BROWSER_SET = "chrome+firefox";
export const FIREFOX_UNAVAILABLE_REASON = "firefox-unavailable-in-sandbox";

export function parseN2BrowserSet(value = DEFAULT_N2_BROWSER_SET) {
  if (value === "chrome") return Object.freeze(["chrome"]);
  if (value === "chrome+firefox") return Object.freeze(["chrome", "firefox"]);
  throw new Error("--browsers must be chrome or chrome+firefox.");
}

export function formatN2BrowserSet(browsers) {
  if (Array.isArray(browsers) && browsers.length === 1 && browsers[0] === "chrome") {
    return "chrome";
  }
  if (Array.isArray(browsers) && browsers.length === 2 &&
      browsers[0] === "chrome" && browsers[1] === "firefox") {
    return "chrome+firefox";
  }
  throw new Error("The N2 browser set is invalid.");
}

export async function launchN2Browsers(playwright, browsers = ["chrome", "firefox"]) {
  const browserSet = formatN2BrowserSet(browsers);
  const chromeBrowser = await playwright.chromium.launch({ headless: true, channel: "chrome" });
  let firefoxBrowser = null;
  try {
    if (browserSet === "chrome+firefox") {
      firefoxBrowser = await playwright.firefox.launch({ headless: true });
    }
    return { chromeBrowser, firefoxBrowser };
  } catch (error) {
    await chromeBrowser.close().catch(() => {});
    throw error;
  }
}

export function createN2BrowserInstances(
  chromeVersion = null,
  firefoxVersion = null,
  browsers = ["chrome", "firefox"],
) {
  const browserSet = formatN2BrowserSet(browsers);
  return {
    player_a: {
      name: "Chrome",
      version: chromeVersion,
      engine: "chromium",
      channel: "chrome",
    },
    player_b: browserSet === "chrome+firefox"
      ? {
          name: "Firefox",
          version: firefoxVersion,
          engine: "firefox",
        }
      : null,
    host_ui: {
      name: "Chrome",
      version: chromeVersion,
      context: "separate BrowserContext in the Player A Chrome instance",
    },
  };
}

export function hasN2BrowserVersions(browserInstances, browsers = ["chrome", "firefox"]) {
  if (browserInstances === null || typeof browserInstances !== "object") return false;
  const browserSet = formatN2BrowserSet(browsers);
  const requiredRoles = browserSet === "chrome+firefox"
    ? ["player_a", "player_b", "host_ui"]
    : ["player_a", "host_ui"];
  const validVersions = requiredRoles.every((role) => {
    const browser = browserInstances[role];
    return browser !== null && typeof browser === "object" &&
      typeof browser.name === "string" && browser.name.length > 0 &&
      typeof browser.version === "string" && browser.version.length > 0;
  });
  return validVersions && browserInstances.player_a.name === "Chrome" &&
    (browserSet === "chrome" ? browserInstances.player_b === null : browserInstances.player_b.name === "Firefox") &&
    browserInstances.host_ui.name === "Chrome" &&
    browserInstances.host_ui.version === browserInstances.player_a.version;
}
