# KADI LAN Multiplayer — design notes

Server-authoritative LAN play, reusing the existing single-player
`GameManager`/`RuleEngine` completely unmodified as the sole authority.
Every non-host player is a thin client that sends *intentions* and
renders whatever the host broadcasts.

## Module map

| Module | Role |
|---|---|
| `network/protocol.py` | Newline-delimited JSON wire framing (`FrameBuffer`, `encode_message`). No game or socket knowledge. |
| `network/host.py` / `network/client.py` | Threaded TCP socket layer. One accept thread + one recv thread per connection on the host; one recv thread on the client. Every thread only ever pushes decoded messages onto a `queue.Queue` — nothing off the main thread touches game/UI state. |
| `network/codec.py` | Card/Suit ↔ JSON, mirroring `core/save_manager.py`'s own format. |
| `network/event_codec.py` | Generic `GameEvent` ↔ JSON codec (walks event attributes; Player→player_id, Card→dict) so every event kind reaches clients for toasts/sounds without hand-translating each one. |
| `network/state_sync.py` | Builds a per-recipient public snapshot from the real `GameManager`, reusing `GameManager._opponent_context`'s exact privacy boundary (hand *counts* for opponents, full hand only for the recipient). |
| `network/host_game.py` | `HostGame`: owns the real `GameManager` (optionally the SceneManager's own shared instance) + `LANHost`. Validates turn ownership and matches requested cards against the real hand before calling the existing `human_play()`/`human_draw()`/etc. — never reimplements a rule. |
| `network/client_state.py` | `ClientGameManager`: a thin mirror exposing the same attribute surface `GameplayScene`/`BoardRenderer` already expect. Rotates the seat list so "you" are always index 0 (matching `BoardRenderer`'s hardcoded seat-0-is-me-face-up layout) and reconstructs a real `RuleEngine` client-side so `get_playable_cards()`/hints work instantly, without a round trip. Action methods send intents; they never mutate state locally. |
| `scenes.py`: `LANMenuScene`, `LANHostLobbyScene`, `LANJoinScene` | Lobby UI. `GameplayScene` gained `network_role`/`host_game`/`client_gm` params to `on_enter`, an `on_exit()` for teardown, and one added line in `update()` calling `host_game.network_tick()`. |

## Threading model

Exactly one rule, applied identically on host and client:
background socket threads (accept/recv) **only** push decoded messages
onto a `queue.Queue`. The main (pygame) thread is the **only** thread
that ever reads that queue, mutates `GameManager`/`ClientGameManager`,
or calls `send`/`broadcast`. This is what makes it safe without a lock
around any game state — the only genuinely shared mutable structure is
the queue itself (internally locked) and a small connection registry
dict (separately guarded).

One real bug this caught during Phase 1 testing: closing a socket from
a different thread than the one blocked in `recv()` does not reliably
unblock that thread or deliver a FIN to the peer on this platform.
Fixed by calling `shutdown(SHUT_RDWR)` before `close()` on both ends
(see the comments in `network/client.py`'s `close()` and
`network/host.py`'s `_close_client()`).

## Wire protocol

Newline-delimited JSON. One JSON object per line via
`json.dumps(..., separators=(',', ':'))` (never contains a raw
newline) + `b'\n'`. Chosen over length-prefixing because payloads here
are small (single game snapshots, not bulk transfer) and this is
trivially debuggable — you can `nc` into the port and read/paste JSON
by hand.

Message types: `hello`, `welcome`, `reject`, `lobby_state`, `start_game`
(lobby); `state_sync` (host→client, every frame); `intent_play`,
`intent_draw`, `intent_declare_kadi`, `intent_choose_suit`,
`intent_counter`, `intent_pass_counter`, `intent_post_play_declare_kadi`,
`intent_post_play_proceed` (client→host).

## Seat numbering

Network `player_id` == `GameManager` seat index (`Player.player_id`),
by construction: `HostGame.start_game()` builds `player_configs` from
the *current* roster (host, id 0, first; then connected clients in
ascending id order), computing an explicit `pid → seat index` map at
that moment — not assumed to be the identity mapping, since `LANHost`
never reuses ids and a client leaving mid-lobby can leave gaps.

## Testing

- `tests/test_phase1_protocol.py` — protocol + host/client core in
  isolation, loopback only.
- `tests/test_phase2_state_sync.py` — host + 2 loopback clients wired
  into a real `GameManager`, scripted draw-only game to a genuine
  `GAME_OVER` via stall resolution, checking hand-count/own-hand/
  privacy consistency every turn.
- `tests/test_phase3_scenes_smoke.py` — the actual `LANHostLobbyScene`/
  `LANJoinScene`/`GameplayScene` classes end-to-end, headless, including
  real turns via the real `_action_draw()`/`_action_kadi_no()` UI
  handlers and a real exit/teardown.
- `tests/test_phase4_regression.py` — 100 headless AI-vs-AI games (no
  networking imported at all) proving single-player is unaffected.

Run any of them from the `kadi/` directory, e.g.:

```
SDL_VIDEODRIVER=dummy python -m tests.test_phase1_protocol
SDL_VIDEODRIVER=dummy python -m tests.test_phase2_state_sync
SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m tests.test_phase3_scenes_smoke
SDL_VIDEODRIVER=dummy python -m tests.test_phase4_regression
```

## Known limitations (deliberate scope cuts)

- **LAN only.** No NAT traversal, relay, or matchmaking — join by
  typing the host's IP. UDP broadcast auto-discovery was intentionally
  skipped in favor of manual entry (always works; broadcast discovery
  is easy to get subtly wrong and wasn't worth the risk for v1).
- **Undo** (`human_undo_last_action`) is host-local only. A client's
  button is a no-op.
- **Pause** can only be *triggered* by the host (`toggle_pause()` is a
  no-op on a client) — but a host-triggered pause IS still correctly
  reflected on every client, since `state` becomes `GameState.PAUSED`
  like any other broadcast field.
- **AI pacing dials** (`cycle_ai_game_speed`/`cycle_ai_spectator_speed`)
  only affect the host's own simulation pace; a client's buttons are
  no-ops.
- **Drag-to-reorder** a client's own hand will visually snap back —
  the host broadcasts a fresh snapshot (rebuilt from its own hand
  order) every frame, and this feature doesn't send a "my preferred
  order" intent. Doesn't affect gameplay (cards are matched by
  content, never by position) — purely cosmetic.
- **No mid-game reconnection / seat takeover.** A disconnected
  client's turn will still resolve via the existing turn-timer
  timeout (forced draw) — the host doesn't crash or freeze — but
  there's no way for that player to rejoin the same match.
- **No save/resume for LAN games.** Save-and-exit is skipped entirely
  for a network match (see `GameplayScene._action_menu_clicked`) — a
  `ClientGameManager` isn't something `save_manager` can serialize, and
  reloading someone else's LAN match later isn't meaningful.
- **"Play Again"** after a LAN match returns to the main menu instead
  of restarting locally (renegotiating a fresh lobby is out of scope).
- Host and client player counts are validated against `MIN_PLAYERS`/
  `MAX_PLAYERS` from `constants.py` the same as single-player, but the
  lobby only exposes the **Elimination Mode** toggle — the many other
  per-game settings (timers, hints, rule variants) use whatever the
  host's own currently-saved single-player settings are.

## Optional AI-fill seats

The host lobby (`LANHostLobbyScene`) has an **AI Players to add**
stepper (default 0 — off) plus an Easy/Medium/Hard difficulty picker.
This lets a solo host, or a small group that didn't fill every seat,
start right away instead of waiting for a full table — it's a
suggestion the host can take or leave, never automatic. The stepper is
clamped live (recomputed every frame) to `MAX_PLAYERS - <humans
currently in the roster>`, so it's impossible to exceed the same
`MAX_PLAYERS = 6` single-player already enforces, no matter when
someone else joins or leaves while the host is deciding. The chosen
count + difficulty is broadcast to every connected client as an extra
row in the same settings panel they already see (`network/host_game.py`
passes it through as `extra_ai_configs` straight into the existing,
unmodified `GameManager.new_game()` — no new game logic, just more
seats in the same config list single-player already builds).

MSOMI models can also be attached to those AI-filled seats, exactly
like ModeSelectScene lets single-player do it — same underlying
`core.msomi_trainer` calls, same modal (pick from this device's saved
models, or Browse for any file). Lives in `scenes.MSOMIPickerWidget`, a
standalone reusable widget kept deliberately separate from
`ModeSelectScene`'s own MSOMI code (rather than refactored to share
it), so this addition carries zero risk to the already-shipped,
well-tested single-player MSOMI flow.

## Join screen guidance

The IP field on `LANJoinScene` accepts either a bare IP
(`192.168.1.42`) or the full `IP:PORT` string the Host lobby screen
itself displays (`192.168.1.42:51999`) — so a joining player can just
copy-paste exactly what's shown on the host's screen rather than
needing to know to strip the port off. Empty, it shows a greyed-out
`e.g. 192.168.1.42:51999` placeholder, and a line underneath reminds
the player to ask the host, since that's the one piece of information
they can't guess themselves.
