# Upstream `/play` provenance inventory

Read-only inventory of upstream commit `32a6fbd758d33a20d9aa13ae35577adc04b2a4da`, dated 2026-11-05. No upstream implementation code is copied.

## 1. Source and license

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| Revision `32a6fbd758d33a20d9aa13ae35577adc04b2a4da`; `LICENSE`; `run_web.py:85`; `desktop/src/contract.ts:8` | Identifies the source, Fair Source License 1.0, Copyright (c) 2024 MoonlightByte, and React app at `/play/`. | reject | This fork does not merge or sync upstream (ADR-0031). Any separately approved adapted piece retains Fair Source attribution. |

## 2. Event typing and Socket.IO argument arity

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `src/contract/events.ts`; `src/services/socket.ts` | Types event names/payloads and makes Socket.IO calls with defined argument arity. Upstream talks to the HOST Flask-SocketIO surface. | recreate | The player uses only N1 `/player` namespace events `player.snapshot.request`, `player.active_pc.select`, `player.input.submit` and emissions `player.snapshot`, `player.event`, `player.input.receipt`, `player.error` (see `openspec/specs/player-capabilities/spec.md` and `web/extensions/player/capabilities.py`). Match N1 arity exactly; host events are rejected. |

## 3. Stores

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `src/stores/*` | Client state using zustand. | recreate | zustand is not approved; use React state/hooks. |

## 4. Components

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `src/components/layout/*`; `log/*`; `party/*`; `sheet/*`; `dialogs/*`; `settings/*` | Layout, transcript/log, party, sheets, dialogs, settings. | recreate / reject | Recreate transcript/log, read-only sheet, and party/active-PC selector. Reject settings, toolkit, party-editing, and lifecycle features as host-only. |

## 5. Hydration and reconnect

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `src/services/hydration.ts`; `src/services/restart.ts` | Hydrates state and handles restart/reconnect. | recreate | Implement against N1 snapshot/cursor/replay/resync; never replay input. |

## 6. UI mode and styling

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `src/modes/*`; `src/theme/*`; fonts; Tailwind configuration | UI modes, styles, and assets. | recreate / reject | Recreate with plain CSS. Reject Tailwind, `@tailwindcss/vite`, and oxlint as unapproved; reject fonts/images unless license is recorded. |

## 7. Browser-test patterns

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `e2e/*.spec.ts`; `playwright.config.ts`; `@testing-library/react` | Browser tests, configuration, and component-test patterns. | recreate | Recreate with Playwright and React DOM test utilities; `@testing-library/react` is not approved. |

## 8. Observed upstream dependency versions

| Upstream path(s) | What it does | Disposition (adapt / recreate / reject) | Rationale |
|---|---|---|---|
| `package.json` | Reference versions observed: `react` `^19.2.7`, `react-dom` `^19.2.7`, `socket.io-client` `^4.8.3`, `vite` `^8.1.1`, `typescript` `~6.0.2`, `@types/react` `^19.2.17`, `@types/react-dom` `^19.2.3`, `vitest` `^4.1.10`, `jsdom` `^29.1.1`, `@playwright/test` `^1.61.1`. | reject | Observations only, not recommendations. This fork's approved set is exactly ten packages: react, react-dom, socket.io-client, vite, typescript, @types/react, @types/react-dom, vitest, jsdom, playwright (dev-only). |
