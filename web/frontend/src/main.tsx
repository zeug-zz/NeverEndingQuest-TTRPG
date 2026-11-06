// SPDX-FileCopyrightText: 2024 MoonlightByte
// SPDX-License-Identifier: Fair-Source-1.0

import { createRoot } from "react-dom/client";
import { App } from "./App";
import { readPlayerClientVersion } from "./client-version";
import "./player.css";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error("Missing root element");
}

const csrfInput = rootElement.querySelector<HTMLInputElement>('input[name="csrf_token"]');
const preloginCsrfToken = csrfInput?.value ?? "";

createRoot(rootElement).render(
  <App
    clientVersion={readPlayerClientVersion()}
    preloginCsrfToken={preloginCsrfToken}
  />,
);
