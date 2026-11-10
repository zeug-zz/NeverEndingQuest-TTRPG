// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

export function hitPointsLabel(sheet) {
  return sheet.locator("dt", { hasText: /^Hit points$/ });
}
