// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export async function waitForTextOnAnyPage(pages, text, expect, pollOptions = {}) {
  let visibleByPage = [];
  await expect.poll(async () => {
    visibleByPage = await Promise.all(
      pages.map((page) => page.getByText(text).isVisible()),
    );
    return visibleByPage.some(Boolean);
  }, pollOptions).toBe(true);
  return visibleByPage;
}
