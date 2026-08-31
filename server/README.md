# KADI Internet Multiplayer — design notes

Server-authoritative play against ONE always-on, publicly-reachable
server, instead of a LAN peer. Reuses LAN multiplayer's wire protocol
and client-side transport completely unmodified — this is "the same
networking layer, pointed at a public server instead of a LAN IP,"
not a separate system. See `network/README.md` for the LAN design this
extends; this document only covers what's different.

## The one deliberate architectural difference from LAN

In LAN play, the hosting player's own machine runs the real
`GameManager` and every other player is a thin client of that machine.
Here, **every player — including whoever created the hosted game — is
a thin client of the SERVER's `GameManager`.** There is no local-host
shortcut. This is what guarantees no player, host included, can ever
see another player's hand: the one place the real hand data lives is a
machine none of the players control.

It also incidentally solves NAT/connectivity: since everyone (the
"host" included) only ever makes an OUTBOUND connection to the one
known server address, nobody needs to accept an inbound connection or
forward a port.

## Module map

| Module | Role |
|---|---|
| `server/connection.py` | `ConnectionManager`: accepts inbound TCP connections and multiplexes messages from ALL of them onto one queue. Same threading rule as `network/host.py`'s `LANHost` (background threads only ever push onto a queue; the main server loop is the only thread that mutates state or sends) — the only structural difference is that this registry is global (many rooms, one listener) rather than scoped to a single game. |
| `server/game_room.py` | `GameRoom`: owns the one real `GameManager` for a single match. `handle_intent`/`_match_hand_cards` are the LAN `HostGame`'s validated-intent logic applied to a connection topology where many rooms share one `ConnectionManager`, rather than one dedicated `LANHost` per game. |
| `server/lobby.py` | `Lobby`: tracks open (not-yet-started) `GameRoom`s for matchmaking, plus started rooms for the duration of their match. |
| `server/kadi_server.py` | The standalone entry point: single-threaded main loop that drains `ConnectionManager`, routes lobby-level messages (create/list/join/start), and ticks+broadcasts every active room. |
| `network/settings_summary.py` | Shared, pygame-free rule-settings helpers (`build_rule_rows`, `rule_settings_payload`, `apply_rule_settings`) used by BOTH `GameRoom` here and LAN's `scenes.py` screens, so a hosting player's own locally-configured rules (turn timer, hints, ace/pickup/jump toggles) actually travel onto the server's `GameManager` instead of silently defaulting — see "Settings & MSOMI parity with LAN" below. |
| `scenes.InternetMenuScene` / `InternetLobbyScene` (in the main `scenes.py`) | Client UI: server address entry, then browse/host/join, then a waiting room — reusing `network.client.LANClient` and `network.client_state.ClientGameManager` completely unmodified. Always hands off to `GameplayScene` with `network_role='client'`, never `'host'` — see the architectural note above. |

Everything else — `network/protocol.py` (wire framing), `network/codec.py`,
`network/event_codec.py`, `network/state_sync.py` (including the
`GameManager._opponent_context` privacy boundary), `network/client.py`,
and `network/client_state.py` — is reused byte-for-byte, unmodified.

## Wire protocol additions

All newline-delimited JSON, same framing as LAN. Reuses `hello`,
`welcome`, `lobby_state`, `start_game`, `reject`, `state_sync`, and
every `intent_*` message verbatim. New messages layered on top for
matchmaking (nothing about the existing set changed shape):

| Message | Direction | Purpose |
|---|---|---|
| `list_games` | client → server | Request the current open-games list. |
| `games_list` | server → client | `{games: [{game_id, host_name, player_count, max_players, rows}]}`. |
| `create_game` | client → server | `{settings: {elimination_mode, ai_count, ai_difficulty, rules, ai_msomi_model, ai_msomi_model_label}}` — creates a new open room with this connection as its host (seat 0 once started). `rules` carries the host's own local rule configuration (see `network/settings_summary.py`); `ai_msomi_model` (optional) is the actual trained-model JSON dict read from the host's local file, not a filename — see "Known limitations" below for why. |
| `join_game` | client → server | `{game_id}`. |
| `request_start_game` | client → server | Host-only; builds `player_configs` from the room's current roster (+ AI seats from its settings) and starts the real `GameManager`, exactly like `HostGame.start_game()` does for LAN. |
| `room_closed` | server → client | Sent to remaining members if the host disconnects (or the room empties) before the game starts — see "Known limitations" below. |

`welcome` and `lobby_state` both gained one additional field beyond
their LAN shape: `host_id`, so a client can tell whether it's the one
allowed to click Start. `welcome.player_id` here is the connection's
own globally-unique, never-reused id (assigned by `ConnectionManager`)
rather than a room-local sequence number — this avoids any
resequencing ambiguity if other members join or leave the same lobby
before the match starts.

## Settings & MSOMI parity with LAN

Added in a follow-up pass after an audit found the original Internet
lobby only carried over Elimination Mode + AI count/difficulty,
silently defaulting everything else (turn timer, hints, ace/pickup/jump
toggles) to `GameManager`'s class defaults regardless of what the
hosting player actually had configured locally. Fixed:

- `InternetLobbyScene._create_game()` now sends a `rules` payload
  (`network.settings_summary.rule_settings_payload(self.gm)`) — a
  snapshot of the host's own local `GameManager` settings — inside
  `create_game`. `GameRoom.__init__` applies it
  (`apply_rule_settings()`, clamped/validated, unknown or malformed
  keys silently ignored rather than crashing the room) to the room's
  own `GameManager` before anything else happens.
- `GameRoom.settings_summary_rows()` now shows the full LAN-parity row
  set (`network.settings_summary.build_rule_rows`) instead of just 2
  rows, and both the host and any joining client see it via
  `lobby_state` before Start.
- MSOMI model attachment also works now: since a trained model is just
  a small JSON dict of learned weights (see `core/msomi_trainer.py` —
  no heavy binary), the client reads its own local model file and
  embeds the dict itself (not a filename) in `create_game`'s
  `ai_msomi_model` field; the server validates it
  (`msomi_trainer.validate_model()`) and attaches it directly to each
  AI seat's `Player.msomi_model` right after `GameManager.new_game()`
  creates them. An invalid/missing model degrades to plain AI rather
  than blocking the room (surfaced as "MSOMI Model: ... (invalid,
  ignored)" in the lobby if that happens). `GameManager.new_game()`
  itself was not touched — this is a purely additive attach step in
  `server/game_room.py`.
- Tests: `tests/test_internet_settings_parity.py` and
  `tests/test_internet_msomi_attach.py` (see "Testing" below).
- **Not built**: any server-side persistence/library of MSOMI models.
  A model rides inside one `create_game` message, lives only as long
  as that one `GameRoom` object does, and is never written to disk on
  the server — see "Known limitations" below.

## Threading model

Identical rule to LAN (see `network/README.md`): background socket
threads (accept + one recv thread per connection) only ever push
decoded messages onto a `queue.Queue`. The single main server loop
(`KadiServer.tick()`, called from `run_forever()`) is the only thread
that reads that queue, mutates any `Lobby`/`GameRoom`/`GameManager`
state, or calls `send_to()`/`broadcast()`. Every currently-active
`GameRoom`'s `GameManager` is ticked and broadcast from that same
single loop, one after another, each server tick (20 Hz) — there is no
separate thread per match.

## Testing

- `tests/test_internet_phase1_lobby.py` — the lobby/matchmaking layer
  in isolation (create, list, join, reject-on-unknown-game,
  host-disconnects-before-start), server + several `LANClient`
  connections all on loopback.
- `tests/test_internet_phase2_authority.py` — a real `KadiServer` +
  3 loopback connections play a scripted, AI-free game to a genuine
  `GAME_OVER` via stall resolution, checking every turn that all three
  clients' mirrors agree with the server's real `GameManager` on hand
  counts / current player / own-hand contents, and that no client is
  ever sent an opponent's real cards — including the room's CREATOR,
  who is just as much a thin client here as anyone else.
- `tests/test_internet_phase3_scenes_smoke.py` — the actual
  `InternetMenuScene`/`InternetLobbyScene`/`GameplayScene` classes
  end-to-end, headless, including real turns via the real
  `_action_draw()`/`_action_kadi_no()` UI handlers and a real
  menu-exit/teardown.
- Phase 4 (regression) is the EXISTING `tests/test_phase4_regression.py`
  (single-player) and the existing `tests/test_phase1..3` (LAN) files,
  rerun unmodified — this feature doesn't touch either code path, so
  proving they still pass as-is is the actual regression check.
- `tests/test_internet_settings_parity.py` — a host with rule settings
  deliberately set AWAY from defaults (timers off, Ace Finisher off,
  etc.) creates a room; confirms the server's real `GameManager`
  actually picks those values up (not just cosmetic), the full
  LAN-parity row set is shown, and a joining client sees the identical
  rows before Start.
- `tests/test_internet_msomi_attach.py` — both the valid-model path
  (the embedded model dict reaches the real server-side `Player`
  object's `.msomi_model`, not just the lobby display) and the
  invalid/corrupt-model path (degrades to plain AI, doesn't block the
  room, is clearly flagged in the lobby rows).

Run any of them from the `kadi/` directory, e.g.:

```
SDL_VIDEODRIVER=dummy python -m tests.test_internet_phase1_lobby
SDL_VIDEODRIVER=dummy python -m tests.test_internet_phase2_authority
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m tests.test_internet_phase3_scenes_smoke
SDL_VIDEODRIVER=dummy python -m tests.test_internet_settings_parity
SDL_VIDEODRIVER=dummy python -m tests.test_internet_msomi_attach
```

## Deploying the server yourself

The server needs the Python standard library plus **pygame** — yes,
pygame, even though the server never renders anything: `constants.py`
does a bare `import pygame` at module level, and `core/game_manager.py`
imports `constants`, so the whole chain pulls pygame in just to
import, not just to run. It does NOT need NumPy — confirmed by tracing
the actual import graph (below) and by empirically blocking NumPy from
being importable and re-running: `core/msomi_trainer.py` only does
`import numpy as np` INSIDE its `train()` function, never at module
level, and the server never calls `train()`.

The exact project files the server's own import graph touches (traced
directly, not assumed) — copying just these (plus pygame's dependency
itself) is enough; everything under `rendering/`, `animation/`,
`effects/`, and `assets/` is unused by the server:

```
constants.py
core/__init__.py  core/game_logger.py  core/decision_logger.py
core/game_manager.py  core/rule_engine.py  core/msomi_trainer.py
models/__init__.py  models/card.py  models/player.py
network/__init__.py  network/protocol.py  network/codec.py
network/event_codec.py  network/state_sync.py  network/settings_summary.py
server/__init__.py  server/connection.py  server/game_room.py
server/lobby.py  server/kadi_server.py
```

In practice it's simplest to just copy the whole `kadi/` project
directory over rather than maintain a partial-copy script — the unused
rendering/asset files are a few extra MB, harmless to have sitting
there unused.

1. Get the whole `kadi/` project directory onto a persistent machine
   with a public (or at least reachable-to-your-players) IP — a small
   cloud VM works fine. You need Python 3.8+ installed (confirmed
   working on 3.8.10); nothing else system-wide, though a venv is
   recommended (see below) since `pip` often isn't preinstalled on a
   minimal box.
2. From inside that `kadi/` directory, run:
   ```
   python3 -m server.kadi_server --port 52010
   ```
   (`--port` is optional; it defaults to 52010 if omitted.)
3. Open that port for inbound TCP on the machine's firewall/security
   group (only THIS one port, on the server — players never need any
   port opened on their own machines, since they only make outbound
   connections). On a cloud VM this is usually TWO separate layers —
   the box's own firewall (e.g. `iptables`/`ufw`) AND the cloud
   provider's own network security rules (e.g. AWS security groups,
   Oracle Cloud Security Lists/NSGs) — both need the port open, or
   connections get silently dropped even though the box-level rule
   looks fine.
4. Keep it running persistently — e.g. under `tmux`/`screen` for a
   quick start, or as a proper background service (recommended: it
   auto-restarts on crash and auto-starts on reboot):
   ```bash
   # one-time setup, if pip isn't already installed:
   sudo apt-get update && sudo apt-get install -y python3-pip python3-venv

   cd /path/to/kadi
   python3 -m venv venv
   source venv/bin/activate
   pip install pygame
   deactivate
   ```
   ```ini
   # /etc/systemd/system/kadi-server.service
   [Unit]
   Description=KADI Internet Multiplayer server
   After=network.target

   [Service]
   Type=simple
   WorkingDirectory=/path/to/kadi
   Environment=SDL_VIDEODRIVER=dummy
   Environment=SDL_AUDIODRIVER=dummy
   ExecStart=/path/to/kadi/venv/bin/python3 -m server.kadi_server --port 52010
   Restart=on-failure
   RestartSec=3
   User=your-linux-username

   [Install]
   WantedBy=multi-user.target
   ```
   The two `SDL_*=dummy` lines aren't strictly required for the server
   to IMPORT successfully (`constants.py` only does a bare
   `import pygame`, never `pygame.init()`/`pygame.display.set_mode()`
   — confirmed empirically with both env vars unset) but are set here
   defensively anyway, matching this project's own convention
   everywhere it runs headless, since SDL backend behavior on an
   unfamiliar box (different distro/SDL build/no framebuffer at all)
   isn't something to bet on sight-unseen.
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now kadi-server
   sudo systemctl status kadi-server   # should show "active (running)"
   ```
5. Tell your players the server's address as `host:port`
   (e.g. `203.0.113.7:52010`). In the game, that's what goes in
   Multiplayer → Internet Multiplayer → **Server Address**.

The server prints nothing sensitive and logs only to stdout; there's
no persistence between restarts (an in-progress match's room state is
lost if the server process restarts — see "Known limitations" below).

## Known limitations (deliberate scope cuts, matching LAN's own)

- **No mid-game reconnection.** A disconnected player's turn resolves
  via the existing turn-timer timeout (forced draw) exactly like an
  unresponsive LAN client — the server doesn't crash or freeze, but
  there's no way for that player to rejoin the same match. This was
  explicitly out of scope for this pass.
- **Host disconnecting before Start closes the room outright** (all
  waiting members get `room_closed` and return to the browse list).
  There's no host handoff — simplest correct behavior for a lobby that
  can no longer be started by anyone.
- **No persistence across a server restart.** All rooms/games are
  in-memory only; restarting `kadi_server.py` drops every open lobby
  and in-progress match. Fine for the always-on-VM deployment model
  above, but worth knowing if you ever need to restart it mid-session.
- **No chat/emoticons** — explicitly a later, separate phase per spec.
- **AI-fill seats DO support MSOMI model attachment**, same as LAN's
  per-seat picker — but the mechanism differs out of necessity: the
  trained model file lives on the HOST PLAYER's own machine, not the
  server, so there's nothing for a filename to resolve to over there.
  Instead the client reads its own local model file (a small JSON dict
  of learned feature weights — see `core/msomi_trainer.py`, no heavy
  binary) and embeds its contents directly in the `create_game`
  settings payload; the server validates it with the exact same
  `msomi_trainer.validate_model()` LAN/single-player use, then attaches
  it directly to each AI seat's `Player.msomi_model` attribute right
  after `GameManager.new_game()` creates them (see
  `server/game_room.py`'s `start_game()`) — `GameManager.new_game()`
  itself, and its existing `msomi_model_name`-from-file loading path
  that single-player/LAN both rely on, are untouched. An invalid or
  missing model degrades to plain (non-MSOMI) AI rather than blocking
  the room — surfaced in the lobby's settings panel as
  "MSOMI Model: ... (invalid, ignored)" if that happens.
- Every other LAN limitation (undo is unavailable over the network,
  pause/AI-pacing dials are not player-controllable client-side, no
  save/resume for a network match, "Play Again" returns to the main
  menu) applies identically here, for the identical reasons — see
  `network/README.md`'s own "Known limitations" section.
