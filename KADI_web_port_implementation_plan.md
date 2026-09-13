# KADI — "One Code, Three Platforms" Implementation Plan
Discord Activities · Telegram Mini Apps · WeChat Mini Games

---

## 0. Framing assumption (read this first)

KADI today is a **Python/pygame desktop app**. None of the three target
platforms can run Python or pygame natively in a browser/webview context
(pygbag/WASM was already considered and rejected earlier in this
conversation for load-time and input-feel reasons). So this plan is **not**
"reuse `scenes.py` and `rendering/board_renderer.py` as-is" — it's:

- **Keep** `core/game_manager.py` + `core/rule_engine.py` and the
  server (`server/kadi_server.py`) exactly where they are, in Python.
  They're already headless, already the sole authority over hidden hand
  state, and already stdlib-only — that part of the existing codebase is
  the biggest asset you have and needs the least work.
- **Build new**: a JavaScript/TypeScript client (renderer + adapters) that
  talks to that same server over WebSocket instead of raw TCP. The
  message *shapes* in `network/protocol.py` get mirrored in JS, not
  reused line-for-line — TypeScript can't import a `.py` file.

So "core (shared)" in the architecture we agreed on means: **one Python
server, unmodified in spirit, serving three JS clients.** The JS client
side is what gets structured into shared-renderer + per-platform-adapter.
I want that stated plainly before the folder layout, so nobody expects a
`git mv` — this is closer to a new client project that reuses your
existing server as-is.

---

## 1. Project Folder Structure

Recommend a **monorepo** alongside (not replacing) the existing Python
repo, using pnpm workspaces (or Turborepo/Nx if the JS layer grows large
— pnpm workspaces alone is enough to start and adds no build-tool
complexity yet).

```
kadi-web/                          # new repo (or a subfolder of the existing one)
├── package.json                   # workspace root
├── pnpm-workspace.yaml
├── tsconfig.base.json
│
├── packages/
│   ├── protocol/                  # TS mirror of network/protocol.py message shapes
│   │   └── src/messages.ts        # hand-kept in sync with the Python side (see §8)
│   │
│   ├── client-core/                # platform-agnostic game STATE (not rules — server owns rules)
│   │   └── src/
│   │       ├── connection.ts       # WebSocket wrapper, reconnect/backoff
│   │       ├── gameState.ts        # local mirror of server-pushed state
│   │       └── events.ts           # typed pub/sub for renderer to subscribe to
│   │
│   ├── renderer/                   # THE shared canvas renderer — no platform code allowed here
│   │   └── src/
│   │       ├── scenes/             # table view, hand view, win screen, lobby — mirrors scenes.py conceptually
│   │       ├── sprites/            # card sprites, avatar sprites, badge sprites
│   │       ├── ui/                 # buttons/menus — CANVAS-DRAWN, see §6
│   │       └── theme.ts            # reads theme tokens from the active adapter, never hardcodes platform colors
│   │
│   └── adapter-interface/          # the CONTRACT — see §2 — no implementation, just the TS interface + types
│       └── src/PlatformAdapter.ts
│
├── adapters/
│   ├── discord/
│   │   └── src/DiscordAdapter.ts   # implements PlatformAdapter using @discord/embedded-app-sdk
│   ├── telegram/
│   │   └── src/TelegramAdapter.ts  # implements PlatformAdapter using window.Telegram.WebApp
│   ├── wechat/
│   │   └── src/WeChatAdapter.ts    # implements PlatformAdapter using wx.* APIs + weapp-adapter
│   └── web/
│       └── src/WebAdapter.ts       # fallback adapter for your own standalone site/PWA — build this FIRST, see §7
│
├── apps/
│   ├── discord-activity/           # thin entry point: imports renderer + DiscordAdapter, Vite build target "discord"
│   │   ├── vite.config.ts
│   │   └── src/main.ts
│   ├── telegram-miniapp/
│   │   ├── vite.config.ts
│   │   └── src/main.ts
│   ├── wechat-minigame/
│   │   ├── project.config.json     # WeChat DevTools project file
│   │   ├── game.json               # WeChat entry manifest
│   │   └── src/main.ts             # bundled via the WeChat-targeting build, see §3
│   └── web-pwa/
│       ├── vite.config.ts
│       └── src/main.ts
│
└── tools/
    ├── protocol-sync-check.ts      # CI script, see §8
    └── build-wechat.ts             # subpackage splitting + size-budget check, see §3
```

**Why this shape:** `renderer/` and `client-core/` never import anything
platform-specific — they only talk to `adapter-interface/`'s TypeScript
*type*, never a concrete adapter class. Each `apps/*` entry point is the
only place that wires a concrete adapter (`DiscordAdapter`,
`TelegramAdapter`, ...) into the shared renderer. That's what makes "no
duplicated files" true: there is exactly one `renderer/` and one
`client-core/`, full stop.

---

## 2. The Adapter Layer (Interface)

```
packages/adapter-interface/src/PlatformAdapter.ts
```

```typescript
export interface PlatformAdapter {
  // Identity
  getPlayerId(): Promise<string>;
  getDisplayName(): Promise<string>;
  getAvatarUrl(): Promise<string | null>;

  // Social / virality hooks
  inviteFriend(gameCode: string): Promise<void>;
  shareResult(payload: ShareResultPayload): Promise<void>;

  // Presentation
  getTheme(): PlatformTheme;          // colors/typography tokens, see renderer/theme.ts
  getSafeAreaInsets(): SafeAreaInsets; // Discord panel vs Telegram fullscreen vs WeChat status bar

  // Platform lifecycle
  onReady(cb: () => void): void;      // fires once host SDK handshake completes
  onSuspend(cb: () => void): void;    // app backgrounded (pause music, etc.)

  // Transport hint (see §5 — most platforms just need the URL)
  getWebSocketUrl(): string;
}

export interface ShareResultPayload {
  resultText: string;    // e.g. "I just beat Kadi-Bot 3-1!"
  cardImageUrl?: string;  // reuses your existing rendering/share_card.py concept, generated server-side
  deepLink: string;       // "join my game" link, see §5 for how this differs per platform
}
```

**Startup platform detection** (in each `apps/*/src/main.ts`, not in
shared code): each `apps/*` entry point is a *separate build target*
(§3), so detection is really just "which entry point got loaded" —
Vite/webpack picks the adapter at **build time**, not runtime, via a
`PLATFORM` env var:

```
apps/discord-activity/src/main.ts:
  import { DiscordAdapter } from '@kadi/adapter-discord';
  bootstrapGame(new DiscordAdapter());
```

This is deliberately *not* runtime user-agent sniffing — that's fragile
(Discord and Telegram both ultimately run Chromium/WebKit under the
hood, so UA strings aren't a reliable signal). Build-time selection means
zero risk of loading the wrong adapter and zero dead code shipped to a
platform that doesn't need it.

---

## 3. Build & Packaging Pipeline

One Vite (or esbuild) config per `apps/*` target, all pointing at the
same `packages/renderer` and `packages/client-core` source — no copying,
just normal monorepo dependency resolution (pnpm workspace links).

```
pnpm --filter discord-activity build   → dist/discord/   (iframe-hosted bundle, Discord CDN or your own host)
pnpm --filter telegram-miniapp build   → dist/telegram/  (hosted on your own domain, linked from bot)
pnpm --filter wechat-minigame build    → dist/wechat/    (WeChat-specific packaging, see below)
pnpm --filter web-pwa build            → dist/web/       (your own site)
```

**WeChat's 4MB cap — concrete strategies:**

1. **Subpackaging.** WeChat Mini Games support a "main package + lazily
   loaded subpackages" model, same as WeChat Mini Programs. Keep the
   main package to boot + lobby + core card-table scene only; ship win
   -screen animations, badge/cosmetic art, and music as subpackages
   loaded on first use. This is the single biggest lever — don't treat
   4MB as "the whole game," treat it as "the part needed to start
   playing."
2. **Art budget.** Your existing `assets/` is ~4.2MB total (fonts 460K,
   icons 1.8M, music 1.9M, sounds tiny). Music is almost certainly cut
   or deferred to a subpackage — it's your single biggest line item and
   contributes nothing to "can I see my hand and play a card."
   Card/icon art gets converted to WebP (typically 25–35% smaller than
   PNG at equivalent quality) and packed into texture atlases to cut
   per-file overhead.
3. **Font subsetting.** Ship only the glyphs actually used in UI strings
   rather than a full font file — trivial size win, easy to miss.
4. **No unused engine weight.** If the shared renderer is built on a
   general engine (Phaser, etc.), audit what actually ships — dead-code
   elimination / tree-shaking matters more here than on any other target
   because the budget is so tight.
5. **Build-time size gate.** `tools/build-wechat.ts` should fail the
   build (not just warn) if the main package exceeds a threshold you set
   comfortably under 4MB (e.g. 3.5MB) so this is caught in CI, not
   discovered at submission time.

---

## 4. WeChat-Specific Constraints

**Runtime reality:** WeChat Mini Games do **not** run in a browser. No
`document`, no `window`, no DOM — a sandboxed JS runtime (V8 on Android,
JavaScriptCore on iOS) exposing only Canvas 2D/WebGL primitives, one
canvas only. This is the one place the "mostly shared" renderer promise
gets tested for real.

- **Adapter shim:** use WeChat's official `weapp-adapter`, which patches
  in enough of a fake `document`/`Image`/`Canvas` surface for
  browser-oriented rendering code to run unmodified in most cases. If the
  chosen renderer is Phaser, there's community precedent for
  Phaser-on-WeChat via this adapter plus a WeChat-targeting build
  config — **but this needs a throwaway spike before committing**, not
  an assumption baked into the timeline. Recommend Week 1 includes a
  half-day "hello triangle in WeChat DevTools via weapp-adapter + our
  chosen renderer" spike specifically to de-risk this before Phase 3.
- **Single-canvas constraint** reinforces §6 below: every UI element —
  including things that would be a `<button>` or `<input>` anywhere
  else — must already be a sprite drawn on that one canvas, with manual
  hit-testing for taps. That's not extra work *if* §6 is followed from
  day one for Discord/Telegram too; it's a lot of rework if it isn't.

**Testing before the official business license:** this is the one item
in this plan I'd flag as **needs direct verification against WeChat's
current developer terms before you commit a timeline to it** — WeChat's
account-tier rules (individual vs. enterprise, domestic vs. overseas)
around Mini *Games* specifically (as distinct from Mini *Programs*, which
have historically been more permissive for individual/overseas accounts)
change periodically and I don't have confident up-to-date specifics.
What's reliably true: WeChat DevTools (the official desktop IDE) runs a
local simulator that lets you build and iterate against the real WeChat
Mini Game APIs without publishing anything, and there's typically a
"preview via QR code to your own phone's WeChat" developer-preview flow
that doesn't require public release. Treat **local simulator + QR
preview to your own device** as the safe, always-available testing loop,
and treat "can we get it in front of *other* testers before a business
license" as an open question to resolve with WeChat's current docs
before Phase 4 starts.

---

## 5. Discord & Telegram Specifics

Confirmed: both are standard web content in an iframe — real DOM, real
Canvas/WebGL, real WebSocket. No sandboxed-runtime concerns here, unlike
WeChat.

**Discord Activity init** (`adapters/discord/src/DiscordAdapter.ts`):
1. Import `@discord/embedded-app-sdk`, instantiate `DiscordSDK` with the
   app's client ID.
2. `await sdk.ready()` — handshake with the Discord client.
3. Complete the OAuth authorize/token exchange the SDK requires to call
   `authenticate()` and get the calling user's identity — this is the
   `getPlayerId()`/`getDisplayName()` implementation.
4. Register any URL mappings needed in the Discord Developer Portal
   (Activities → URL Mappings) since Discord proxies all external
   requests from the iframe through its own domain — this affects how
   `getWebSocketUrl()` needs to be expressed (may need to be a mapped
   path, not a raw external host, depending on current Discord proxy
   rules — verify against current docs at implementation time).

**Telegram Mini App init** (`adapters/telegram/src/TelegramAdapter.ts`):
1. Load the Telegram Web App JS bridge script.
2. Call `window.Telegram.WebApp.ready()`.
3. Read `window.Telegram.WebApp.initDataUnsafe.user` for identity — note
   "unsafe" in the API name: for anything identity-sensitive (e.g. tying
   a leaderboard entry to a real account), the signed `initData` string
   should be verified **server-side**, not trusted from the client as-is.
4. `window.Telegram.WebApp.expand()` to request full-height display.
5. Invite flow uses Telegram's own share sheet
   (`WebApp.openTelegramLink` / share-to-chat) rather than a generic Web
   Share API call.

Both of these are genuinely "SDK handshake + a few calls," not
architecture — which is the whole reason they can share one renderer.

---

## 6. Rendering Discipline

**Confirmed and non-negotiable given §4:** every piece of in-game UI —
buttons, the "Yes! KADI / Proceed / Undo" panel, menus, text labels, the
pick-up badge we already reworked twice this week — is drawn **on the
canvas as a sprite/text-render call**, never as an HTML `<button>` or
`<div>`. This needs to be a rule enforced from the first line of
`packages/renderer`, not a WeChat-only concession bolted on later,
because:

- It's the only way the *same* renderer code has a chance of running
  unmodified inside WeChat's no-DOM sandbox.
- It also means input handling (hit-testing tap/click coordinates
  against sprite bounds) is written **once**, in `renderer/src/ui/`, and
  reused identically on all four targets — rather than "real HTML
  buttons on Discord/Telegram, fake canvas buttons only for WeChat,"
  which would silently reintroduce three-different-codebases through
  the back door.

Suggested guard rail: a lint rule / CI grep step that fails the build if
any file under `packages/renderer/` contains `document.createElement`,
`innerHTML`, or JSX/HTML-returning code. Cheap to write, catches drift
early.

---

## 6a. Continuous Layout & Scale System (mandatory from LobbyScene onward)

**Status: built, retrofitted onto `LobbyScene`, unit-tested.** This is
the renderer's answer to a problem the Python client only partly
solved — `constants.py`'s `get_chrome_scale(sw, sh)` derives a scale
factor and font-size ladder for fixed-pixel UI chrome, but it's only
ever fed one of 8 resolutions the player explicitly picked from
`RESOLUTIONS` in `scenes.py`, and its own code comments admit roughly
half the Python UI (menus, most buttons/panels) was "never audited"
for what happens when text/layout scales — only the gameplay table and
Settings/Rules panel actually consume it. A browser or mobile viewport
never gives you a picker; it resizes continuously (window drag,
orientation change, a host platform resizing the iframe/panel around
you), so a lookup table isn't the right shape here even as a starting
point.

**Where it lives:** `packages/renderer/src/layout/` —

- `scale.ts` — `computeLayoutScale(viewport)`, the direct successor to
  `get_chrome_scale`: `scale = clamp(min(width/480, height/640), 0.7,
  3.0)`, recomputed from the actual current canvas size every time it
  changes. Also holds the `ui_tiny`/`ui_small`/`ui_normal`/
  `ui_medium`/`ui_large` font ladder (`fontPx()`), the touch-target
  floor (`enforceMinTouchTarget()`, see below), and the supported
  viewport range (`clampViewport()`, see below). Pure, no Phaser/DOM
  imports — fully unit-testable without a canvas.
- `safeArea.ts` — `getSafeContentRect(viewport, insets)` turns
  `PlatformAdapter.getSafeAreaInsets()` (defined since the first pass,
  previously unused by anything) into the actual rectangle content
  should be laid out inside, so host-platform chrome doesn't overlap
  game UI.
- `LobbyLayout.ts` — `computeLobbyLayout(viewport, insets, entryCount)`
  is `LobbyScene`'s entire layout as one pure, testable function: every
  position/font-size that scene used to hard-code against a fixed
  480x640 canvas now comes from here, including working out how many
  leaderboard rows actually fit rather than assuming they always will.

**Phaser wiring:** `packages/renderer/src/index.ts`'s `bootstrapGame()`
configures the Scale Manager with `mode: Phaser.Scale.RESIZE` (canvas
always matches its parent element's real size) plus `min`/`max` set to
the supported viewport range below — deliberately using Phaser's own
Scale Manager rather than reinventing resize-event handling.
`LobbyScene` subscribes to `Phaser.Scale.Events.RESIZE` once in
`create()` and re-runs `computeLobbyLayout()` against the new
`this.scale.width/height` on every firing; it's unsubscribed on scene
shutdown.

**Supported viewport range (Part B):** Discord Activities and Telegram
Mini Apps were checked against their current docs rather than assumed
— see "Sources checked for Part B" below. Neither publishes a fixed
numeric min/max panel size; both explicitly design for continuous
host-driven resizing and tell developers to make UI scale
appropriately rather than target one fixed size. Given that, the range
chosen is a practical one, not a platform-mandated constant:
`MIN_VIEWPORT_WIDTH = 320`, `MIN_VIEWPORT_HEIGHT = 400` (narrow phone
portrait / Telegram's collapsed BottomSheet state), up to
`MAX_VIEWPORT_WIDTH = 3840`, `MAX_VIEWPORT_HEIGHT = 2160` (4K desktop
browser — the scale factor itself additionally clamps at `MAX_SCALE`
so anything larger still renders sanely, just without the canvas
growing further).

**Touch targets (Part C):** `enforceMinTouchTarget(size)` in
`scale.ts` grows (never shrinks) a proposed interactive-element box up
to `MIN_TOUCH_TARGET_PX = 44` — Apple HIG's floor for a tappable area
(also WCAG 2.5.5 AAA's 44×44 CSS px); Google's Material Design
guidance is stricter, at 48×48dp. This is a first-class primitive with
its own dedicated tests, ready for the first scene that adds a real
button. **`LobbyScene` itself has no tappable elements yet** (it's
connection status + a read-only leaderboard), so there was nothing to
retrofit this specific constraint onto in this pass — the next scene
that adds a button must call this on its box before drawing it. Don't
add a fake button just to exercise this function; use it when a real
one is built.

**Safe-area insets (Part D):** `adapters/web/src/WebAdapter.ts`'s
previously-stubbed `getSafeAreaInsets()` now reads real
`env(safe-area-inset-*)` values via a hidden probe element measured
with `getComputedStyle()` — the standard technique, since there's no
JS API for these. `apps/web-pwa/index.html`'s viewport meta tag now
includes `viewport-fit=cover`, which is required for iOS Safari to
report non-zero values at all. `LobbyLayout.ts` folds these insets
into every position it computes via `getSafeContentRect()`.

**This is the mandatory pattern going forward:** every future scene
computes its own `compute<Scene>Layout(viewport, insets, ...)` pure
function in `packages/renderer/src/layout/`, subscribes to
`Phaser.Scale.Events.RESIZE` the same way `LobbyScene` does, and runs
every interactive element's box through `enforceMinTouchTarget()`
before drawing it. This directly closes the "half the UI was never
audited" gap the Python client's own comments flagged — every element
built from here on uses this from day one, not as an opt-in retrofit
later.

**Sources checked for Part B/C (current as of this pass, not assumed
from training knowledge):**
- Discord Activities — `docs.discord.com/developers/activities/design-patterns`
  ("Consider different screen sizes and orientations... make sure UI
  elements scale appropriately"; mobile safe-area guidance) and
  `docs.discord.com/developers/activities/development-guides/mobile.md`
  (safe-area CSS variables, falling back to `env(safe-area-inset-*)`).
  No fixed min/max iframe dimensions are published.
- Telegram Mini Apps — `docs.telegram-mini-apps.com/platform/viewport`
  (BottomSheet-based sizing, `isExpanded`/`stableHeight`, fullscreen
  mode) and `core.telegram.org/bots/webapps` (`mode=compact` opens at
  half-screen height by default). No fixed min/max dimensions are
  published; viewport is host-driven and dynamic by design.
- Touch targets — Apple HIG (44×44pt minimum), Google Material Design
  3 (48×48dp minimum, WCAG 2.5.8 AA baseline of 24×24), WCAG 2.5.5
  (AAA, 44×44 CSS px).

---

## 7. Milestones & Timeline

These are planning-grade estimates for roughly one focused developer
(adjust down with more hands, especially in Phases 2–3 which can run in
parallel once Phase 1 lands). Treat every "week" below as a rough
sizing, not a commitment — the WeChat spike in particular could shift
Phase 4 meaningfully in either direction.

| Phase | Scope | Est. duration |
|---|---|---|
| **1. Foundation** | Monorepo scaffold (§1), `adapter-interface` contract (§2), `client-core` WebSocket wrapper, mirror `network/protocol.py` message shapes into `packages/protocol` (§8), stand up **WebAdapter** + `web-pwa` target first — it's the cheapest way to validate the renderer against a real browser before any platform SDK is in the mix | 2–3 weeks |
| **2. Renderer core** | Table/hand/win-screen scenes in `packages/renderer`, canvas-only UI per §6, wire against the existing Python server over a new WebSocket listener (server-side: adapt `server/connection.py` to accept WS framing alongside/instead of raw TCP — small, contained change) | 3–4 weeks |
| **3. Discord + Telegram adapters** | Both can genuinely proceed in parallel (§5) — real DOM targets, no sandbox surprises expected. SDK handshake, identity, invite/share flows, theme tokens per platform | 2 weeks each (can overlap) |
| **4. WeChat spike → adapter** | Half-day `weapp-adapter` + renderer spike (§4) *before* committing further time; if renderer survives largely unmodified, adapter + subpackage split (§3) + size-budget CI gate; if it doesn't survive unmodified, this phase absorbs the rework and the timeline gets revisited | 1-week spike, then 2–4 weeks depending on spike outcome |
| **5. Social/virality features** | Deep-link invite flow, server-side share-card generation (extends existing `rendering/share_card.py`/`core/social_share.py` concept), leaderboard tie-in per platform | 2 weeks |
| **6. Hardening** | Cross-platform QA pass, CI test suite (§8), WeChat manual QA loop (§4), soft-launch on whichever platform has the least friction first (Discord, most likely, given no business-license gate) | 2 weeks |

**Total: roughly 3–4 months** for a single developer to reach a
soft-launchable state across all three, front-loaded risk resolved
early (Phase 1's `web-pwa` target and Phase 4's WeChat spike are both
explicitly placed to surface problems before they're expensive).

---

## 8. CI/CD & Testing Strategy

Reuse the GitHub Actions familiarity from the existing `build.yml`
pipeline — same platform (GitHub Actions), same "matrix of targets"
shape you already use for Windows/Mac/Linux builds, just building JS
bundles instead of PyInstaller binaries.

- **Build matrix:** one job per `apps/*` target on every PR — catches
  "renderer change broke the WeChat build" immediately rather than at
  release time.
- **Protocol drift check (`tools/protocol-sync-check.ts`):** since
  `packages/protocol` is a **hand-kept TS mirror** of
  `network/protocol.py`'s message shapes (not a shared file — Python and
  TS can't literally share one source), the biggest real risk is silent
  drift between the two. Add a CI step that runs a small Python script
  dumping the server's known message field names/types to JSON, and a
  matching TS check that diffs it against `messages.ts`, failing the
  build on mismatch. This is the automated guard against "server added
  a field, nobody told the client."
- **Renderer tests:** unit tests for `client-core` state transitions
  (pure logic, no rendering, fast) plus a smaller set of Playwright
  browser tests driving the `web-pwa` build end-to-end against a real
  server instance — this is your highest-value automated coverage since
  Discord and Telegram are both standard browser contexts and mostly
  inherit correctness from whatever passes here.
- **Discord/Telegram-specific automation:** both platforms' SDKs are JS
  libraries that can be mocked in the Playwright harness (fake
  `DiscordSDK`/`window.Telegram.WebApp` objects returning canned
  identity data), so adapter logic itself is testable in CI without a
  live Discord/Telegram session.
- **WeChat — be honest about the ceiling here:** WeChat DevTools is a
  manual desktop IDE, not something with an official headless/CI mode
  in common use. Realistic plan is a **manual QA checklist run in the
  simulator before each release**, not full automation — flag this
  explicitly rather than pretend it's CI-covered like the other three.
- **Merge gate:** PRs touching `packages/renderer` or `packages/protocol`
  require the build matrix + protocol-sync-check green; PRs touching a
  single `adapters/*` only need their own target's build to pass.

---

## 9. Feature Parity Tracking

Tracks specific PC-client features/screens against their web-port
status, updated as each is closed out. Not exhaustive — added to as
gaps are found (see the drag-to-reorder row below, disclosed only in
a code comment until manual testing caught it).

| Feature | PC reference | Web status |
|---|---|---|
| Drag-to-reorder own hand | `scenes.py`'s `_reorder_hand()` / `_drag_idx`, `board_renderer.py` per-seat drag rendering | **Done.** Ported into `GameTableScene`'s hand rendering (local-only, no server round-trip — hand order is a pure client display preference, confirmed against `core/game_manager.py`/`ClientGameManager`). Unit-tested (`handOrder.test.ts`); works under mouse and emulated touch. |
| Lobby "Quick Play vs AI" unresponsive after a completed game | — (web-only regression, introduced alongside the drag-to-reorder change) | **Done.** Root cause: `LobbyScene` is a reused Phaser scene instance across `scene.start()` transitions; `quickPlayRequested` was never reset in `init()`, so it stayed `true` from the prior game and both the tap guard and the button's dimmed alpha stuck permanently. Fixed by resetting it in `init()`. |
| Main Menu | `scenes.py`'s `MainMenuScene` | **Done, narrowed scope.** Web `MainMenuScene` offers "Play", "Profile", "Settings", "How to Play", and "Chuo" (all five enabled, all routing to real scenes — "Chuo" newly wired this session, see its own row below for what it opens onto). "Continue Game" and "Quit" are dropped, not disabled: Continue depends on a local-save-file concept with no web equivalent or planned row, and there's no web equivalent of Quit. |
| Mode Select | `scenes.py`'s `ModeSelectScene` (reached directly for AI, or via `MultiplayerMenuScene` for Local/LAN/Internet) | **Done, narrowed scope.** Web `ModeSelectScene` is NOT the PC per-game configuration screen (opponent count, difficulty, elimination mode, MSOMI, hot-seat names) — it's one screen up: which mode. Only two buttons: "Play vs AI" (routes to `LobbyScene` with `autoQuickPlay: true`, skipping a redundant second tap) and "Internet Multiplayer" (routes to `InternetLobbyScene` — see below, no longer plain `LobbyScene`). LAN is **permanently out** (no placeholder button, ever — asserted in `ModeSelectLayout.test.ts`). "Local Multiplayer" (same-device hot-seat) has no planned web row either, since a web build's premise is one device per player. |
| Internet Multiplayer — real join/browse flow | `scenes.py`'s `InternetLobbyScene` (browse/host/join/waiting-room), server/lobby.py + server/kadi_server.py's `create_game`/`join_game`/`rejoin_game`/`request_start_game` (unchanged, already-working server) | **Done.** New `InternetLobbyScene.ts` + `layout/InternetLobbyLayout.ts` (single-column reshape of the PC's two-column layout, unit-tested). Covers: browse open games (polled at 1.5s, matching PC's `LIST_REFRESH_SECS`), host with a name, join by tapping a row, join by name/host search (`_filtered_games()` ported verbatim), a waiting-room roster with host-only Start (gated on `players.length >= 2`, matching server's `MIN_PLAYERS`). `packages/protocol/src/messages.ts`'s `GameSummary` corrected to the real `open_games_summary()` shape (`game_id`/`host_name`/`game_name`/`player_count`/`max_players`/`rows`) — it previously guessed a placeholder `name: string` field that isn't on the wire at all. Verified against the real server: `internetMultiplayerIntegration.test.ts` spins up two independent `KadiConnection`s (no mocks) that browse, one hosts, the other joins by list *and* by name search, both land in `GameTableScene`, and a real 2-player game is driven to `GAME_OVER`. Note on that test: it drives both seats with a deliberately simple bot (not real strategy), which very occasionally produces a slow-converging game under bad-luck shuffles — the timeout is set generously (up to ~4.5 min) to absorb that variance rather than being a sign of a hang; a stuck game was investigated and ruled out (see the test's own comments on the KADI-declare and suit-pick fixes that made this reliable). |
| Internet Multiplayer — reconnect (`rejoin_game`) | `network/client_state.py`'s `ClientGameManager` reconnect loop; server/game_room.py's `GameRoom.reconnect()` (unchanged) | **Done, mid-game only — and that split is a real server-side limit, not a client scope cut.** `GameRoom.reconnect()` requires `self.started`; a pre-start (browse/waiting-room) disconnect is handled by `server/kadi_server.py`'s `_handle_disconnect()` removing the member **immediately, no grace period** (closing the room outright if they were host) — confirmed by reading both, not assumed. So: a drop during `InternetLobbyScene`'s 'browse' state needs nothing (the list simply resumes once `KadiConnection`'s own transport-level auto-reconnect reopens the socket); a drop during 'lobby' (waiting room) is reported plainly and the scene returns to Browse, rather than firing a `rejoin_game` the server was always going to reject. The one place `rejoin_game` genuinely helps — a drop **after** `start_game`, mid-match — is wired into `GameTableScene` (init() now accepts optional `gameId`/`reconnectToken`, handed over by `InternetLobbyScene` on `start_game`; `GameTableScene` sends `hello` + `rejoin_game` once the transport reopens, applies `state_sync` normally on success, and falls back to the main menu on a `reject`). |
| Internet Multiplayer — reconnect status text disappearing on a fast reconnect | — (web-only regression, introduced alongside the reconnect row above) | **Done.** `GameTableScene`'s `statusText` and `InternetLobbyScene`'s `browseStatusText` both set a "Reconnecting…" message the instant the transport drops, then clear/overwrite it the instant it recovers — on a fast drop/recover cycle both calls could land close enough together that the player never actually saw the message, even though the recovery genuinely happened. Fixed with a new, pure, unit-tested `statusText.ts`: a `StatusTextGuard` wraps each scene's real `.setText()` with a minimum-display-duration guard (~500ms) — once a message is shown, a later call can't replace it until that window elapses. The one already-correct terminal case (`GameTableScene`'s "Could not reconnect — <reason>", which already held for its own explicit 2s before this bug was found) deliberately bypasses the guard via `showImmediate()` so its behavior is unchanged. |
| Profile screen | `scenes.py`'s `ProfileScene` (class at line 1061, `draw()` at line 1203) | **Done — five real sections, not the four the original handoff prompt named.** New `ProfileScene.ts` + `layout/ProfileLayout.ts` (pure, unit-tested — 20 tests in `ProfileLayout.test.ts`, plus 19 in `profileData.test.ts` for the ported data model), reached from Main Menu's now-**enabled** "Profile" button. Ported: **Stats**, a **Leaderboard — Your Best Modes** panel (scenes.py lines 1263-1310, omitted from the original task brief's own "four real sections" summary, caught by reading `draw()` directly — same discrepancy pattern as the Settings task's omitted Rules/Player Assistance/Credits cards, see that row below), **Badges** (all 74 from `core/profile_store.py`'s `BADGE_DEFS`, verbatim names/descriptions, grouped by category, earned-vs-locked dot, one **Share** button per earned badge), and **Cosmetics** — Card Backs and Table Felt Themes (owned/locked swatches, Equip buttons, tap-or-hover tooltip showing the unlock requirement or earning badge). Part B (persistence): new `PlatformAdapter.getProfile()`/`saveProfile()`, implemented in `WebAdapter.ts` under its own `kadi.web.profile` `localStorage` key — deliberately separate from Settings' `kadi.web.settings` key (a Settings "Reset to Defaults" must never touch badges/stats; see `PlatformAdapter.ts`'s docstring), verified with the same real cross-process reload rigor as Settings (`WebAdapter.profilePersistence.test.ts`, 6/6: round-trip, null-on-nothing-saved, null-on-corrupt-JSON, last-write-wins, badges/cosmetics survive intact, **and** a dedicated test proving Settings and Profile genuinely don't share storage). Part C (badge sharing): each earned badge's one Share button calls the existing `PlatformAdapter.shareResult()` directly — the PC's PNG-card-generation + platform-picker + `webbrowser.open()` mechanism (`rendering/share_card.py`, `core/social_share.py`) is deliberately NOT ported; this renderer is already inside a browser, so the native share sheet/clipboard fallback `WebAdapter.ts` already implements does the platform-appropriate thing with no PNG asset pipeline needed. Part D (cosmetics actually affecting the table): `GameTableScene.ts` now resolves the equipped felt theme and card back via a new pure `resolveTableCosmetics()` (`profileData.ts`) at its own `create()`, from the SAME persisted profile — felt fill/edge color and the draw pile's/opponents' hidden-card back color are no longer fixed hex literals. Verified at the boundary that's actually testable without a canvas/WebGL context in this environment: `resolveTableCosmetics()` itself is fully unit-tested (different equipped values produce different, correct colors; a corrupt/unknown equipped key falls back to 'default' rather than throwing), and a source-level regression test (`gameTableCosmeticsWiring.test.ts`) asserts `GameTableScene.ts`'s `renderTable()`/`renderPiles()`/`renderSeats()` genuinely read from `this.tableCosmetics` and that the old hardcoded color literals are gone — no test in this codebase instantiates a live Phaser Scene and reads back rendered pixels (none ever has; Scene classes stay thin, unexercised-by-automation appliers of pure functions' output, same split every other `layout/*.ts` module already established), so that boundary is stated here rather than silently assumed past. Part D's card-back swatches (`ProfileScene.ts` and the table) render as a flat two-color gradient, not the PC's real procedural pattern (diagonal/dots/crosshatch/etc.) — this web client has no card-art rendering pipeline at all yet (see `GameTableScene.ts`'s own file-header note, predating this task), so there is no pattern renderer to reuse; `pattern` is still carried as data in `profileData.ts`'s `CARD_BACK_STYLES` for whenever that pipeline exists. **Closed in this delivery, not left as future work:** game-end results now write into the profile for real. New server message `game_summary` (`network/game_summary.py`, sent once per finished game from `server/kadi_server.py`'s existing `GAME_OVER` transition in `tick()`) carries every input `core/profile_store.py`'s `check_badges_after_game()` needs — real port of that function plus `award_badge()` now lives in `profileData.ts` (`checkBadgesAfterGame()`/`awardBadge()`/`applyGameSummary()`), including the `counters` lifetime-tally bucket and win-streak tracking that this section's own prior sentence noted as missing (there was nowhere to fold a finished game's tallies into until now — added to `ProfileData` in this delivery). `GameTableScene.ts` now listens for `game_summary`, re-fetches the current profile (not a stale scene-start snapshot — a long game session could see another write from `ProfileScene`'s equip flow in the meantime), applies it, persists via `adapter.saveProfile()`, and surfaces newly-earned badges on the win screen. A fresh web install's Profile screen now genuinely fills in as games are played, same as the PC.

**The one real gap this surfaced, fixed rather than shipped broken:** `GameManager`'s pre-existing `self._g_*` per-game counters are aggregated across *every* human player in the room — correct for the PC's one-human-per-device design (confirmed from `finalize_profile_stats`'s own docstring: hot-seat deliberately credits every local human's result to one shared `profile.json`), silently wrong for the internet server, which hosts one `GameManager` for potentially several humans on separate devices with separate profiles — would have attributed one player's cards/aces/KADI-declarations to every other seated player's own profile. Fixed with a new per-`player_id` breakdown, `GameManager._g_by_player` (populated alongside the untouched aggregate scalars at every existing increment site — additive only, no gameplay/turn-logic change), which `network/game_summary.py` reads instead of the aggregate. `jump_counter_depth` is the one field kept game-level rather than per-player on purpose — a Jump-counter chain is extended by whichever players choose to counter it, not owned by any one of them, matching how the "Jump Master" badge already reads it as a property of the round. `undo_used_this_game` is always `False` over the network — undo is deliberately never exposed as a network intent (confirmed from `server/game_room.py`'s own comment), carried in the wire shape for schema parity rather than hardcoded out in case that ever changes. `mode`/`difficulty` have no server-side equivalent to read off `GameManager` directly — `GameRoom._mode_and_difficulty()` is a new, explicitly-flagged interpretation (not something existing code already decided): a room that only ever had one human (the rest AI seats — this client's own "Play vs AI" quick match) is treated as the PC's `single_player`/`single_player_elimination` with that room's own configured AI difficulty; two or more humans is real Internet Multiplayer — `internet`, no difficulty.

Verified with a new real-server test, `tests/test_game_summary.py` (21 checks, two genuine games played to real `GAME_OVER` over loopback — a 2-human game and a solo-vs-AI game — confirming per-player `cards_drawn` sums back to the room's true aggregate exactly, `mode`/`difficulty` resolve correctly for both room shapes, the message never double-fires, and `undo_used_this_game` is always `False`), plus `checkBadgesAfterGame.test.ts` (18 tests covering tier thresholds, win-gating, streak tracking, and the `applyGameSummary` counter/badge bookkeeping end to end) and a source-level wiring regression test (`gameSummaryWiring.test.ts`, matching the established pattern `gameTableCosmeticsWiring.test.ts` already set for Scene-level wiring nothing in this package's test environment can mount a live Phaser Scene to verify directly).

Not carried over from the PC, stated plainly: `total_time_played_secs` is never accumulated by `applyGameSummary()` — this web client has no session-elapsed-time tracker anywhere yet (`GameTableScene.ts` never starts one), so the `time_1h`/`time_25h`/`time_100h` tier badges are unreachable on web until a real session timer is built to feed it. Left for a future pass, not silently faked with a guessed delta. |
| Settings screen | `scenes.py`'s `SettingsScene` (class at line 2435, `_flow()` at line 2634) | **Done — all 8 real cards, not the 4 the original handoff prompt named.** New `SettingsScene.ts` + `layout/SettingsLayout.ts` (pure, unit-tested — 27 tests in `SettingsLayout.test.ts`), reached from Main Menu's now-**enabled** "Settings" button. Ported: Timers (3 `NumberBox`es), Deck & Logging (jokers 2/4, log level OFF/LOW/HIGH, max saved log files), **Rules** (all 7 gameplay toggles — omitted from the original task brief, caught by reading `_flow()` directly rather than trusting the brief's own 4-card summary), **Player Assistance** (hint toggle + hint-delay % `NumberBox`, also brief-omitted), Display (resolution dropdown deliberately NOT ported — obsolete per §6a's continuous scale system; the card stays as a note explaining the auto-fit behavior rather than a dead placeholder), Audio (music/SFX toggle + volume slider each), **Credits** (`MUSIC_CREDITS`, verbatim — also brief-omitted), and Back/Reset-to-Defaults buttons. Reuses `layout/scrollPhysics.ts` exactly as planned in this section's earlier note. New in this delivery, not present before: `PlatformAdapter.getSettings()`/`saveSettings()` (Part C — see below) and this scene's own interaction model (click-to-focus + keyboard digit entry for `NumberBox`es with accelerating hold-to-repeat steppers, drag-or-click sliders, discrete choice buttons) — the first genuinely interactive (not just read-and-scroll) scene in this codebase; see `SettingsScene.ts`'s own header for what's new there versus carried over from `RulesScene.ts`. |
| Settings persistence (Part C) | `core/settings_store.py`'s `save_settings()`/`load_settings()`/`reset_to_defaults()` (file-based, per-user app-data dir) | **Done.** Web equivalent chosen: `localStorage`, one JSON blob under `kadi.web.settings` (mirrors the PC's own "one file, whole object at once" shape), via two new `PlatformAdapter` methods (`getSettings()`/`saveSettings()`) implemented in `WebAdapter.ts` — kept off the adapter-interface's typed surface deliberately (see `PlatformAdapter.ts`'s docstring: that package sits below `packages/renderer` in the dependency graph, so the concrete `SettingsValues` shape stays renderer-side; `getSettings()` returns a loose bag that `SettingsScene.ts` merges over `DEFAULT_SETTINGS` field-by-field). Saved on every discrete change, a 2s autosave tick, and on scene shutdown (committing any in-progress numbox edit first). Verified with a **real cross-process reload test**, not a same-process mock: `WebAdapter.persistence.test.ts` spawns two independent Node subprocesses sharing one on-disk file via `--experimental-webstorage --localstorage-file=<path>` — a genuinely new runtime re-reading persisted state each time, the same "spawn the real thing" philosophy `client-core`'s server-integration tests already use. 4/4 passing: round-trip across processes, `null` (not a throw) when nothing was ever saved, `null` on corrupt stored JSON (matching `load_settings()`'s own failure fallback), and last-write-wins across a simulated second session. Note on scope: only the *editing* UI and its own local persistence were built this pass — no create/host-game flow in this codebase yet reads these values into an actual server-side game (Internet Multiplayer's `create_game` doesn't take rule-toggle params today), so that wiring, and the accompanying host-vs-joining-client nuance (`network/client_state.py`'s `ClientGameManager` treats most of these as host-authoritative snapshot fields once a game is live, with `card_animations_enabled` the one genuinely client-local-only exception — confirmed by reading `client_state.py` directly), is left for whenever that flow is built, not assumed away. |
| How to Play / Rules screen | `scenes.py`'s `RulesScene` | **Done.** New `RulesScene.ts` + `layout/RulesLayout.ts` (pure panel/text-flow math, unit-tested — `RulesLayout.test.ts`), reached from Main Menu's now-**enabled** "How to Play" button. Section content (`RULES_SECTIONS`) is the PC's `SECTIONS` copy verbatim. Two deliberate, documented departures from a literal port (see `RulesLayout.ts`'s own header): card width is a continuous function of `scale` rather than PC's per-resolution `get_ui_scale().menu_w` lookup table (no such fixed-resolution picker exists on web); `wrapText()` estimates glyph width (no canvas/DOM text metrics available to a pure, Phaser-free layout module) instead of measuring real glyphs via `pygame.font.Font.size()`, tuned to wrap slightly early rather than risk an overflowing line. Scroll-limit "bounce" physics (bounded overshoot + eased ease-out-back settle) are ported into a new shared `layout/scrollPhysics.ts` from `scenes.py`'s module-level `_scroll_wheel_delta()`/`_settle_scroll()` — shared, not `RulesScene`-specific, ready for a future `SettingsScene` to reuse exactly as the PC side already shares it across `SettingsScene`/`RulesScene`/`ChuoScene`. One genuine web-side addition, not a port: touch-drag scrolling alongside mouse-wheel, since a touch-first surface with no scrollbar and no wheel needs some way to read past the first screenful — both input paths feed the same shared physics, so the feel matches regardless of which drove it. Off-screen panels are skipped (not just hidden) and the whole scrollable region is clipped with a Phaser `Graphics` geometry mask on a `Container` (this codebase's first use of a mask — no earlier scene needed real scroll-clipping). |
| LAN Multiplayer | `scenes.py`'s `lan_menu` | **Permanently out of scope for web** — no LAN-discovery equivalent planned on any of the three target platforms (browser/Discord/Telegram/WeChat sandboxes). |
| Chuo / MSOMI (train-your-own-AI) | `scenes.py`'s `ChuoScene`, `msomi_trainer` | **Done.** New `ChuoScene.ts` + `layout/ChuoLayout.ts` (pure, unit-tested — 16 tests in `ChuoLayout.test.ts`), reached from Main Menu's now-**enabled** "Chuo" button. All four real tabs ported (Data, Features, Model, Train & Results) — one unified scrollable row list per active tab, rather than the PC's pinned-buttons-above-a-list layout (a phone-width column doesn't need pinned headers the way a desktop window does; same simplification `SettingsLayout.ts` already made). **Storage decision (was "still open" here as of the previous revision of this row — that was stale; decided this session, not left unresolved):** two backends behind one shared `MsomiStore` interface (`packages/adapter-interface/src/MsomiStore.ts`) — the File System Access API where the browser supports it (`FileSystemAccessMsomiStore.ts`, a real native file/folder picker, genuinely capable of reading the PC desktop client's own `logs/`/`msomi_models/` folder directly if pointed at it) falling back to IndexedDB elsewhere (`IndexedDbMsomiStore.ts`), chosen via feature detection in `createMsomiStore.ts` (checks for `showDirectoryPicker`, never user-agent sniffing). Both backends are genuinely unit-tested — 31 tests total (`IndexedDbMsomiStore.test.ts` against real `fake-indexeddb`; `FileSystemAccessMsomiStore.test.ts` against small in-memory fakes implementing the same narrow handle interface the real code calls, since no live browser is available in this environment — manual browser-only test steps for the real file-picker path are documented at the bottom of `FileSystemAccessMsomiStore.ts` itself). **Trainer port:** `msomi_trainer.train()`'s plain-NumPy conditional-logit gradient descent is reimplemented directly in TypeScript (`packages/renderer/src/msomi/trainer.ts`) with ordinary arrays — no new dependency (`mathjs` was considered and rejected as overkill for ≤13 features); parity with the real Python trainer is verified directly, not assumed — `trainer.test.ts` trains on a fixed decision set and asserts the TS output matches `core/msomi_trainer.py`'s own `train()` output on the same input to 6 decimal places (the fixture was generated by actually running the Python trainer once, not hand-derived). 21 tests total for the trainer/loader/scorer/validator. **One genuine web-side addition beyond the PC scope:** a "Saved models" list with per-model Load/Delete on the Train & Results tab — the PC `ChuoScene` has no delete affordance anywhere (confirmed by grepping the whole codebase, not assumed), added here as the natural low-cost counterpart of local save/load, not because it was asked for as a literal port. **Deliberately not ported this pass** (see `ChuoLayout.ts`'s own header): the in-app Help overlay (`HelpOverlay`/`HELP_SECTIONS` + its MSOMI-attach illustration splice) — Chuo's four tabs are fully functional without it; a good-sized follow-up on its own, reusing `RulesLayout.ts`'s `wrapText()`/`estimateTextWidth()`. Also simplified vs. the PC's `NumberBox`: the two numeric fields (human weight, training iterations) use +/- steppers only, no click-to-focus keyboard digit entry — both fields are coarse-grained enough (step 1 and step 50 respectively) that this doesn't cost real precision, and it avoids this already-large scene needing its own copy of `SettingsScene.ts`'s keyboard-focus state machine for two fields. **Explicitly still out of scope, not this delivery's job:** attaching a trained model to an AI opponent (`MSOMIPickerWidget`/`ModeSelectScene`'s own "Attach Model..." flow on the PC side) — Chuo's own "Load" button validates a saved model and shows its weights, which is useful standalone, but doesn't wire into gameplay; that's a separate task scoped to `ModeSelectScene.ts`, which this delivery does not touch. |

**Rule going forward:** any delivery that touches a row in this table
must update its STATUS in this same section, in the same change — not
as a follow-up. A delivery summary claiming "done" for something this
table still marks ❌ is a discrepancy to resolve before trusting the
delivery, not after.

**Prompt-writing convention (adopted from this point on):** every
handoff prompt cites the exact PC source — file, class/function name,
and line number *as of the snapshot the prompt was written against*.
Class/function names are the durable anchor; line numbers are a
bonus pointer, not a guarantee — the PC codebase can shift between
when a prompt is written and when it's read, so re-grep rather than
trust a stale number blindly (this happened once already while
writing the Settings prompt below — caught immediately by re-checking
against the actual snapshot rather than assumed).

### Known Issues (living list — resolve before trusting `npm run test`)

_(none open. Closed this session: `ChuoScene.ts`'s tab bar and Back
button were rendering completely invisible in a real browser — found
via a live screenshot after the "done" delivery above, not caught by
any test, since no test in this codebase mounts a live Phaser Scene
(Scene classes stay thin, unexercised-by-automation appliers of pure
functions' output — the same split this doc's Profile and Settings
rows above already established for `gameTableCosmeticsWiring.test.ts`/
`gameSummaryWiring.test.ts`; this is exactly the kind of bug that gap
lets through). Root cause: `renderTabButton()`/`renderBackButton()`/
`renderBackendLabel()` were adding their game objects into the SAME
masked `this.content` Container the scrollable row list uses —
correct for the rows, since that mask is what clips them to the
scroll viewport band, but the tab bar sits ABOVE that band and Back/
the storage label sit BELOW it, so the mask was clipping all three
into invisibility. They existed, they just couldn't be seen. Fixed by
adding a `trackUnmasked()` path for exactly those three elements —
same destroy-and-rebuild-per-`render()` bookkeeping as `track()`, but
left in the Scene's own root display list rather than reparented into
`this.content`. Confirmed with a real production `npm run build`
after the fix, and the full `ChuoLayout.test.ts` / `trainer.test.ts`
suites re-passing — though neither of those could have caught this
either, since both test pure layout/training math, never the Phaser
rendering code that had the actual bug; flagged here rather than
treated as "tests still pass, so it's fine.")_

### Flagged Risks — Chuo/MSOMI delivery (not bugs, nothing currently broken — watch for drift)

These are forward-looking maintenance notes, not open issues blocking
anything today. Listed here (not just in source comments) so they
don't need rediscovering from scratch later:

- **Schema-version manual sync (`packages/renderer/src/msomi/trainer.ts`):**
  `DECISION_SCHEMA_VERSION`/`MODEL_SCHEMA_VERSION` are copied constants
  from `core/decision_logger.SCHEMA_VERSION`/
  `core/msomi_trainer.MODEL_SCHEMA_VERSION` as of this port — there is
  no shared source of truth across the Python and TypeScript
  codebases. If either ever bumps its version (a logged-feature shape
  change), the TS constant must be bumped by hand to match, or a
  model/log trained under the new PC format will be silently
  mismatched against here (or the reverse: an old assumption silently
  accepted). No incident yet — flagged so whoever next changes either
  schema version knows to check both sides.
- **File System Access backend is copy-in, not a live folder link
  (`MsomiStore.ts`, `FileSystemAccessMsomiStore.ts`):** even when
  pointed at the PC desktop client's own data folder, this backend
  reads a snapshot at import time — it does not keep watching that
  folder for files added/changed afterward. A real live-rescan design
  (keeping a `showDirectoryPicker()` handle open across sessions and
  re-listing on demand) was considered and deliberately not built this
  pass, since a finished game's log is already complete by the time
  anyone opens Chuo — but it means "import" has to be repeated by hand
  if new PC-side logs appear later in the same browser session.
- **Chuo's Help overlay (`HelpOverlay`/`HELP_SECTIONS`, incl. the
  MSOMI-attach illustration splice) is not ported.** Chuo's four tabs
  are fully functional without it; this is pure in-app documentation.
  Scoped follow-up: reuse `RulesLayout.ts`'s `wrapText()`/
  `estimateTextWidth()` against the PC's own `HELP_SECTIONS` copy.
- **Chuo's two `NumberBox` fields (human weight, training iterations)
  use +/- steppers only, no click-to-focus keyboard digit entry**
  (unlike `SettingsScene.ts`'s own numeric fields). Both fields are
  coarse-grained (step 1 and step 50 respectively) so this reaches
  every valid value just as fast as typing would — a deliberate
  simplification, not a precision gap, so no follow-up is expected
  here specifically.
- **Attaching a trained model to an AI opponent is explicitly out of
  scope for this delivery** — that's `MSOMIPickerWidget`/
  `ModeSelectScene`'s "Attach Model..." flow on the PC side.
  `ModeSelectScene.ts` was not touched. Chuo's own "Load Model" button
  validates a saved file and shows its weights, which is useful
  standalone but doesn't wire into gameplay.

**Regression found during Profile-delivery verification — the exact
failure mode this section already warned about, recurring, not a new
kind of bug — now fixed and verified, not just diagnosed:**
`packages/client-core/src/__tests__/internetMultiplayerFlow.test.ts`
was present in the snapshot delivered for this task, despite this
same section's own prior entry stating it had been "deleted for real
this time, confirmed via `ls`." It hadn't stayed deleted. This file is
a near-verbatim duplicate of `internetMultiplayerIntegration.test.ts`
(same 7-step browse/host/join/waiting-room/play flow, same spawn
pattern, same assertions) — running both back to back meant the
second real 2-connection game-to-`GAME_OVER` race was contending for
the same class of timing-sensitive server state the first one had
just finished exercising, and it reliably ran past this task's own
verification time budget without ever producing output, error, or a
crash — indistinguishable from a genuine hang from the outside, which
is exactly the symptom this section's prior entry already described
producing "several full-workspace test runs during PM-level
verification hung with zero output." Deleted again — confirmed via
`ls` on `packages/client-core/src/__tests__/` immediately afterward
(present in this same delivery's own tool output, not just a summary
claim: only `gameIntegration.test.ts` and
`internetMultiplayerIntegration.test.ts` remain). `npm run test`
(all three workspaces) re-run in full afterward: 265/265 passing,
completing in well under a minute — not just the previously-hanging
file's own suite in isolation, to rule out the deletion having broken
anything else that imported from it (nothing did; `grep` for the
filename elsewhere in the repo turns up nothing).

**Process note for whoever next touches
`packages/client-core/src/__tests__/`:** this is now the SECOND time
this exact file has reappeared after being reported deleted (once
during the Settings delivery's own verification, once here). If it
turns up a third time, don't just delete and move on — that points at
whatever process produces these delivery snapshots (a stale branch,
a bad merge base, a snapshot-generation step that isn't actually
reading from the post-deletion tree) rather than at this file itself,
and that process is the thing to actually fix.

**Server-side regression found during Settings-delivery verification
— now fixed and verified, not just diagnosed:** `server/game_room.py`'s
`winner_conn_id()` helper (added earlier for the leaderboard
identity-key work) and `server/leaderboard_store.py`'s entire
identity-key implementation (3-arg `record_win(identity_key,
display_name, game_id)`, the `{name, count}` entry shape, the
load-time migration for legacy int entries) had both reverted to an
older, pre-identity-key form — likely a different chat editing from a
stale snapshot of these two files at some point. `server/kadi_server.py`
was never affected and still correctly called the newer 3-arg/
`winner_conn_id()`-based interface throughout, which is exactly why
this surfaced as a hard crash (`AttributeError`, then a `TypeError`
right behind it once the first was patched) the instant any real
game reported a winner — not a silent behavior change.

Both files restored to their identity-key-aware form (verbatim
content, not reconstructed from guesswork — this is the same code
originally written for that feature). `tests/test_global_leaderboard.py`
had also reverted its own call site back to the old 2-arg
`record_win()` form (the exact same one-line fix applied once before,
also lost the same way) — reapplied.

**Verified, not assumed:** all 4 previously-failing standalone
scripts (`test_disconnect_timeout`, `test_global_leaderboard`,
`test_internet_phase2_authority`, `test_network_client_win_profile_stats`)
now pass. Full `pytest` suite: 47/47. Full renderer unit suite: 206
passing (up from the 179 at the last checkpoint — the Settings/Rules/
scrollPhysics additions accounted for). The real 2-connection network
integration test and the real cross-process settings-persistence test
both independently reconfirmed passing after these fixes, to rule out
any interaction between the server-side restore and the web-client
work sitting on top of it.

**Process note for whoever next edits `server/game_room.py` or
`server/leaderboard_store.py`:** both files now carry an explicit
in-file comment describing this exact regression, specifically so
that if either gets edited from another stale snapshot again, the
diff against `server/kadi_server.py`'s actual call sites is the first
thing checked, not the last.

---

## Open items to resolve before Phase 1 starts

1. Confirm current Discord URL-mapping/proxy behavior for external
   WebSocket connections (§5) against Discord's live docs — this affects
   `getWebSocketUrl()`'s exact shape.
2. Confirm current WeChat Mini Game account-tier requirements for
   testing-before-license (§4) directly against WeChat's developer
   portal — flagged as uncertain above rather than guessed at.
3. ~~Decide the renderer engine~~ — **Resolved: Phaser.** See §0a.
