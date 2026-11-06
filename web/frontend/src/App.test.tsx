// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it } from "vitest";
import { App } from "./App";

let container: HTMLDivElement | undefined;

afterEach(() => {
  if (container) {
    act(() => createRoot(container!).unmount());
    container.remove();
    container = undefined;
  }
});

it("renders the player heading", () => {
  container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => root.render(<App />));
  expect(container.querySelector("h1")?.textContent).toBe("NeverEndingQuest player");
  act(() => root.unmount());
  container = undefined;
});
