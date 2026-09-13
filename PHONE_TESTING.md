# Testing on a real phone, over your own WiFi

Emulation (browser dev tools' device mode) can approximate viewport
size, but it can't tell you whether the layout actually feels good
under a real thumb, or whether touch targets, tap latency, and card
readability hold up on real mobile Safari/Chrome. This is the
walkthrough for testing the actual thing on an actual phone, on the
same WiFi as your dev machine.

## 1. Find your PC's LAN IP

- **Windows (PowerShell):** `ipconfig` → look for **IPv4 Address**
  under your active adapter (something like `192.168.1.42`).
- **macOS:** `ifconfig | grep "inet "` (or System Settings → Wi-Fi →
  Details).
- **Linux:** `ip addr` or `hostname -I`.

Call this `<PC-LAN-IP>` below.

## 2. Vite's dev server must accept connections from other devices

By default Vite only binds to `localhost`, which a phone on the same
WiFi cannot reach at all — the connection just times out before the
page even loads. This repo's `web-client/apps/web-pwa/vite.config.ts`
already sets `server: { host: true }` for exactly this reason, so you
shouldn't need to change anything here — just confirm it's still
there if you've edited that file.

## 3. The game connection now auto-targets whatever host served the page

`adapters/web/src/WebAdapter.ts` resolves the WebSocket URL to the
SAME HOST the page itself was loaded from (falling back to
`location.hostname`, not a hardcoded `localhost`), on the default game
port `53010`. So opening `http://<PC-LAN-IP>:5173` on a phone already
gets you `ws://<PC-LAN-IP>:53010` automatically — **no `.env.local`
needed** for the common case (dev server and game server both running
on your PC).

You only need to create `web-client/apps/web-pwa/.env.local` (copy
`.env.local.example` in that same folder) if:

- the game server runs on a **different machine** than the one
  serving the page, or
- you started the server with a **non-default** `--ws-port`.

```
VITE_WS_URL=ws://<game-server-host>:<ws-port>
```

`.env.local` is already gitignored (`web-client/.gitignore`). Restart
`npm run dev:web-pwa` after creating/editing it — Vite only reads
`.env.local` at startup.

## 4. Start the server so it's reachable on your LAN

```
python3 -m server.kadi_server
```

No flags needed for the common case — `server/connection.py`'s
`DEFAULT_PORT`/`DEFAULT_WS_PORT` are `52010`/`53010`, matching the
default the browser now targets automatically (step 3), and
`ConnectionManager` already binds both listeners to `0.0.0.0` (all
interfaces), not just `127.0.0.1` — so nothing server-side needs to
change for LAN reachability. If you do need a non-default WS port for
some reason, match it on both sides:

```
python3 -m server.kadi_server --ws-port <WS_PORT>
```

and set `VITE_WS_URL=ws://<PC-LAN-IP>:<WS_PORT>` in `.env.local` to match.

## 5. Allow the port through your firewall

- **Windows:** the first time the server binds a listening socket,
  Windows Defender Firewall should prompt to allow Python on Private
  networks — allow it. If you don't get a prompt (e.g. it was
  previously blocked), add an inbound rule for TCP port `53010` (and
  `52010` if you also want LAN-desktop-client testing) scoped to your
  Private network profile.
- **macOS:** System Settings → Network → Firewall will prompt
  similarly the first time; allow incoming connections for `python3`.

## 6. Connect from the phone

On the phone, same WiFi, visit:

```
http://<PC-LAN-IP>:5173
```

You should see the Lobby load (status text, leaderboard) — that
confirms both fixes are working together: the page itself loading
proves step 2 (Vite's `host: true`); the Lobby actually reaching
"Connected"/populating the leaderboard (rather than sitting on
"Reconnecting…") proves step 3 (the WebSocket auto-targeting your
PC's LAN IP instead of "localhost").

## 7. Play a couple of real turns

Tap **Quick Play vs AI**, and once seated at the table: tap cards to
select/deselect them, tap **Play** or **Draw**, work through a
POST_PLAY KADI/Proceed decision if one comes up. This is the part
emulation can't substitute for — check specifically for:

- Can you comfortably tap a single card in a fan without fat-fingering
  its neighbor, especially once your hand has 6+ cards?
- Do the Play/Draw/KADI/Proceed/Pass buttons feel reachable and
  correctly sized (they're all enforced to the platform's minimum
  touch-target size in code — see `layout/scale.ts`'s
  `enforceMinTouchTarget` — but code enforcement and "feels right
  under a real thumb" are different questions)?
- Does anything get clipped or crowded at your phone's actual safe-area
  insets (notch, home-indicator bar) versus how it renders in desktop
  browser emulation?
- Any visible lag between a tap and the card/button reacting?

If something feels off, note which screen/action and roughly where on
the layout — that's much more actionable than "mobile felt off."

## Troubleshooting: page loads on the phone, but it never leaves "Reconnecting…"

This means step 2 worked (the phone reached Vite over LAN) but the
WebSocket to the game server isn't getting through. The status text
shows the exact URL it's trying (e.g. `Reconnecting…
(ws://192.168.1.102:53010)`) — check that first:

- **Still shows `ws://localhost:53010`** — this used to be the
  DEFAULT (the original bug this doc was written to fix) but no
  longer should be, since `WebAdapter.ts` now derives the host from
  the page's own address instead of hardcoding `localhost`. If you
  still see `localhost` here:
  - Check whether `.env.local` exists and explicitly sets
    `VITE_WS_URL=ws://localhost:...` — an explicit override always
    wins over the auto-detected host, so a leftover/copied-wrong
    `.env.local` from before this fix will still reproduce the old bug.
    Delete it (or fix the host in it) and restart `npm run dev:web-pwa`.
  - Otherwise, you're likely running an older build — pull the latest
    code and restart `npm run dev:web-pwa` (Vite dev mode doesn't need
    a rebuild, but it does need a restart to pick up source changes to
    `resolveWebSocketUrl()` if the process was already running before
    you updated).
- **Shows the right LAN IP (e.g. `ws://192.168.1.102:53010`) but still
  never connects** — the page load and the WebSocket use **different
  ports** (5173 vs 53010), so a firewall rule that allowed the first
  doesn't automatically cover the second:
  - **Windows:** check for a SEPARATE firewall prompt for `python.exe`
    (distinct from the one for Node/Vite) — if you don't remember
    seeing one, it may have been silently blocked. Add an inbound rule
    for TCP port `53010` on your **Private** network profile
    (Windows Defender Firewall → Advanced Settings → Inbound Rules →
    New Rule). Also worth checking: is your WiFi network itself set to
    "Private" in Windows Settings → Network & Internet? If it's
    "Public", Windows blocks inbound connections to apps by default
    regardless of any app-specific rule.
  - Confirm the server is actually running and didn't crash/exit —
    check its terminal window for a `listening on port` line and no
    stack trace after it.
  - Double-check the IP itself hasn't changed (DHCP can reassign it,
    especially after the PC sleeps/reconnects to WiFi) — re-run
    `ipconfig` and compare against what's in `.env.local`.
- **Shows the right IP, server confirmed running, firewall rule
  confirmed present, still stuck** — try reaching the WS port from
  another tool on the phone/another PC on the same network (e.g. a
  browser dev-tools console on a laptop, `new
  WebSocket('ws://<PC-LAN-IP>:53010')`, watch for `onopen` vs
  `onerror`) to isolate whether it's phone-specific or network-wide.
