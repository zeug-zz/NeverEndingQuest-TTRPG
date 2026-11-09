// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export async function loginPlayer(page, { playerUrl, password, expect, withSetupStage }) {
  await withSetupStage("player_shell_load", async () => {
    await page.goto(playerUrl, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: "Player login" })).toBeVisible();
  });
  await withSetupStage("player_authentication", async () => {
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page.getByRole("heading", { name: "NeverEndingQuest player" })).toBeVisible();
  });
  await withSetupStage("player_connection_wait", async () => {
    await expect(page.getByText("Connected", { exact: true })).toBeVisible();
  });
  return withSetupStage("client_metadata", () => readPlayerVersion(page));
}

export async function readPlayerVersion(page) {
  return page.evaluate(() => {
    const buildMeta = document.querySelector('meta[name="neq-client-build"]');
    const protocolMeta = document.querySelector('meta[name="neq-protocol-version"]');
    if (!buildMeta?.content || !protocolMeta?.content) {
      throw new Error("Player shell is missing manifest build/protocol metadata.");
    }
    const protocolVersion = Number(protocolMeta.content);
    if (!Number.isInteger(protocolVersion)) throw new Error("Player protocol metadata is invalid.");
    return { clientBuildId: buildMeta.content, protocolVersion };
  });
}
