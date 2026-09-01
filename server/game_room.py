"""
KADI - Internet multiplayer: server-side per-game room.

Same authority model as network/host_game.HostGame: owns the ONE real
core.game_manager.GameManager for this match (completely unmodified)
and validates every client "intent" against the real hand before
calling GameManager's own human_play()/human_draw()/etc -- never a
reimplementation of any rule. The deliberate difference from
HostGame/LANHost's model is that here EVERY player, including whoever
created this room, is a thin client of this same GameRoom instance
running on the server -- there is no "local player" shortcut the way
the LAN host has for its own seat.

The intent-validation logic below (_match_hand_cards, handle_intent)
intentionally mirrors network/host_game.HostGame line-for-line -- it's
the same validated-intent pattern applied to a different connection
topology (many rooms multiplexed over one server-wide
ConnectionManager, rather than one dedicated LANHost per game), not a
redesign. See server/README.md for the full writeup.

DISCONNECT / RECONNECT (mid-game only): a connection dropping before
the game starts still just leaves the lobby outright (see
server/kadi_server.py's _remove_from_room) -- nothing below applies
there. Once started, though, a dropped connection gets a grace period
(DISCONNECT_GRACE_SECONDS) before they're actually removed from the
match, tracked here rather than kicking them out on the very first
lost packet:
  - Every seated connection is given an opaque reconnect token
    (_assign_token) at the moment it joins the room, handed back to
    the client in the 'welcome'/'rejoined' message. The client is
    expected to hold onto it (see network/client.py) for exactly this
    purpose.
  - server/kadi_server.py calls mark_disconnected() the instant the
    TCP connection dies (its own _handle_disconnect), and
    check_disconnect_timeouts() every tick to actually evict anyone
    who's been gone too long -- see that module for both call sites.
  - If a new connection presents that same token (a 'rejoin_game'
    message) before the grace period elapses, reconnect() re-seats it
    under the NEW conn_id and the grace timer is simply forgotten --
    exactly the "timer resets if they come back in time" behavior
    asked for. There's no partial credit for almost making it back in
    time; either the token is still live or the seat's already gone.
  - Eviction itself delegates to GameManager.force_remove_player,
    which is what actually takes them out of the turn rotation and
    ends the round outright if only one player is left in it -- see
    that method's own docstring in core/game_manager.py.
"""
from __future__ import annotations
import time
import uuid
from typing import Dict, List, Optional, Tuple

from constants import GameState, MIN_PLAYERS, MAX_PLAYERS
from core.game_manager import GameManager, GameEvent
from core import msomi_trainer
from network.codec import cards_from_list, suit_from_str
from network.state_sync import build_snapshot_for
from network.event_codec import encode_event
from network.settings_summary import apply_rule_settings, build_rule_rows
from network.player_names import disambiguate_names

# How long a mid-game disconnect gets before the seat is force-removed
# and play continues without them (see class docstring above).
DISCONNECT_GRACE_SECONDS = 30.0


class GameRoom:
    def __init__(self, game_id: str, host_conn_id: int, host_name: str,
                settings: Optional[dict] = None):
        self.game_id = game_id
        self.host_conn_id = host_conn_id
        self.settings = settings or {}
        # Purely a browse-list label ("look for 'Friday Night KADI'"
        # instead of an opaque game id) -- has zero effect on gameplay.
        # Capped defensively server-side too (not just trusting the
        # client's own 40-char cap in InternetLobbyScene._create_game)
        # since this is untrusted client input.
        self.game_name = str(self.settings.get('game_name') or '').strip()[:40]
        self.gm = GameManager()
        # The room creator's OWN locally-configured rules (turn timer,
        # hints, ace/pickup/jump toggles -- whatever their Settings
        # screen last saved) travel onto this room's GameManager right
        # away, the same way they'd already be "baked in" for free if
        # this were a LAN host's own live GameManager. See
        # network/settings_summary.py and InternetLobbyScene._create_game().
        apply_rule_settings(self.gm, (self.settings or {}).get('rules'))
        # MSOMI, unlike every other setting here, can't just be a
        # filename -- the trained model file lives on the HOST
        # PLAYER's own machine, not this server, so there's nothing on
        # disk here for a filename to resolve to. Instead the client
        # embeds the small model dict itself (see
        # core/msomi_trainer.save_model's format -- a couple dozen
        # floats, trivially JSON-embeddable) directly in the settings
        # payload, and this validates it the exact same way
        # ModeSelectScene/LANHostLobbyScene's own "attach a model" flow
        # does. An invalid/missing model degrades to plain AI (no
        # crash, no blocked room) -- see settings_summary_rows() for
        # how that's surfaced to players before Start.
        self._msomi_model: Optional[dict] = None
        self._msomi_model_error: Optional[str] = None
        raw_model = self.settings.get('ai_msomi_model')
        if raw_model is not None:
            problem = msomi_trainer.validate_model(raw_model)
            if problem:
                self._msomi_model_error = problem
            else:
                self._msomi_model = raw_model
        self.started = False
        self.closed = False
        # conn_id -> display name, in JOIN order (an ordinary dict
        # preserves insertion order). The host is always first, since
        # the constructor is only ever called with the host as the
        # first (and at that point only) member -- see
        # server/lobby.py's create_game.
        self.member_names: Dict[int, str] = {host_conn_id: host_name}
        self._seat_by_conn: Dict[int, int] = {}
        self._conn_by_seat: Dict[int, int] = {}
        self._pending_events: List[dict] = []

        # ── disconnect / reconnect bookkeeping (see class docstring) ──
        self._token_by_conn: Dict[int, str] = {}
        self._conn_by_token: Dict[str, int] = {}
        self._seat_by_token: Dict[str, int] = {}
        self._disconnected_at: Dict[int, float] = {}  # conn_id -> time.time() it dropped
        self._assign_token(host_conn_id)

    # ── disconnect / reconnect ───────────────────────────────────────────
    def _assign_token(self, conn_id: int) -> str:
        token = uuid.uuid4().hex
        self._token_by_conn[conn_id] = token
        self._conn_by_token[token] = conn_id
        return token

    def token_for(self, conn_id: int) -> Optional[str]:
        return self._token_by_conn.get(conn_id)

    def mark_disconnected(self, conn_id: int, now: Optional[float] = None):
        """Called the instant this room's owning connection dies mid-
        game (see server/kadi_server.py's _handle_disconnect). Doesn't
        remove anything by itself -- just starts the grace-period
        clock that check_disconnect_timeouts() polls every tick."""
        if conn_id not in self._seat_by_conn:
            return  # not a seated player of THIS room (or game hasn't started)
        self._disconnected_at[conn_id] = now if now is not None else time.time()

    def check_disconnect_timeouts(self, now: Optional[float] = None):
        """Call once per server tick for every started room. Evicts
        anyone who's been disconnected past DISCONNECT_GRACE_SECONDS
        without reconnecting."""
        now = now if now is not None else time.time()
        for conn_id, dropped_at in list(self._disconnected_at.items()):
            if now - dropped_at >= DISCONNECT_GRACE_SECONDS:
                self._evict(conn_id)

    def _evict(self, conn_id: int):
        self._disconnected_at.pop(conn_id, None)
        seat = self._seat_by_conn.get(conn_id)
        if seat is None or seat >= len(self.gm.players):
            return
        player = self.gm.players[seat]
        self.gm.force_remove_player(player)

    def reconnect(self, new_conn_id: int, token: Optional[str]) -> bool:
        """A fresh connection is presenting a token from an earlier
        'welcome'/'rejoined' message, asking to resume the seat it
        names. Returns False (nothing changed) if the token is
        unknown, belongs to a seat that's already been evicted/
        finished, or this room hasn't started -- any of which just
        means "too late, or never valid" to the caller."""
        if not self.started or self.closed or not token:
            return False
        seat = self._seat_by_token.get(token)
        if seat is None or seat >= len(self.gm.players):
            return False
        player = self.gm.players[seat]
        if player.finished:
            return False  # already evicted (or legitimately finished) -- no seat to give back
        old_conn_id = self._conn_by_token.get(token)
        if old_conn_id is not None:
            self._seat_by_conn.pop(old_conn_id, None)
            self.member_names.pop(old_conn_id, None)
            self._disconnected_at.pop(old_conn_id, None)
        self._seat_by_conn[new_conn_id] = seat
        self._conn_by_seat[seat] = new_conn_id
        self._token_by_conn[new_conn_id] = token
        self._conn_by_token[token] = new_conn_id
        self.member_names[new_conn_id] = player.name
        return True

    # ── global leaderboard (Part B) ──────────────────────────────────────
    def winner_name(self) -> Optional[str]:
        """Display name of this room's winning HUMAN player, once
        gm.state == GAME_OVER -- or None if there's no winner yet, or
        the winner's seat is an AI (extra_ai_configs seats are never
        entered in _conn_by_seat -- see start_game() below). AI wins
        are deliberately never credited to the global leaderboard: see
        server/leaderboard_store.py's docstring for why only a
        server-authoritative HUMAN win both can't be spoofed AND has a
        real display name to key off."""
        conn_id = self.winner_conn_id()
        if conn_id is None:
            return None
        return self.member_names.get(conn_id)

    def winner_conn_id(self) -> Optional[int]:
        """Companion to winner_name() -- the winning connection's own
        id, needed (alongside its display name) to look up its
        platform identity for the leaderboard (see
        server/leaderboard_store.py's identity-key docstring)."""
        winner = self.gm.winner
        if winner is None:
            return None
        return self._conn_by_seat.get(winner.player_id)

    # ── lobby ──────────────────────────────────────────────────────────────
    def roster(self) -> List[dict]:
        # player_id here is the connection's own stable, globally
        # unique conn_id -- NOT a room-local position -- so a client's
        # "(you)" comparison against its own id never breaks if
        # someone else joins or leaves the lobby in between.
        return [{'player_id': conn_id, 'name': name}
               for conn_id, name in self.member_names.items()]

    def conn_ids(self) -> List[int]:
        return list(self.member_names.keys())

    def display_name(self) -> str:
        """The name shown in the browse list and lobby waiting-room —
        whatever the host typed, or a sensible fallback (the exact
        string the browse list has always shown by default) if they
        left it blank."""
        return self.game_name or f"{self.member_names.get(self.host_conn_id, '?')}'s game"

    def is_host(self, conn_id: int) -> bool:
        return conn_id == self.host_conn_id

    def add_member(self, conn_id: int, name: str) -> bool:
        """Returns False if the room is full, already started, or closed."""
        if self.started or self.closed:
            return False
        if len(self.member_names) >= MAX_PLAYERS:
            return False
        self.member_names[conn_id] = name
        self._assign_token(conn_id)
        return True

    def remove_member(self, conn_id: int):
        self.member_names.pop(conn_id, None)
        token = self._token_by_conn.pop(conn_id, None)
        if token is not None:
            self._conn_by_token.pop(token, None)

    def settings_summary_rows(self) -> List[Tuple[str, str]]:
        """Full LAN-parity settings summary: Elimination Mode (read
        from this room's OWN settings dict, since gm.elimination_mode
        itself isn't set until start_game() runs — see start_game()
        below), the same read-only rule rows LAN's host lobby shows
        (network.settings_summary.build_rule_rows, sourced from this
        room's GameManager, which already has the host's own rules
        applied — see __init__ above), AI-fill, and — if the host
        attached one — the MSOMI model, exactly like LAN's own
        settings panel (see __init__ for how an embedded model dict
        gets validated)."""
        elimination_mode = bool(self.settings.get('elimination_mode'))
        rows: List[Tuple[str, str]] = [
            ("Elimination Mode", "ON" if elimination_mode else "OFF"),
        ]
        if elimination_mode:
            rows.append(("  AI continues alone", "ON"))  # see start_game(): always True
        rows.extend(build_rule_rows(self.gm))
        ai_count = int(self.settings.get('ai_count', 0) or 0)
        ai_difficulty = str(self.settings.get('ai_difficulty', 'MEDIUM')).title()
        rows.append(("AI Players", f"{ai_count} ({ai_difficulty})" if ai_count else "None"))
        if ai_count and self.settings.get('ai_msomi_model') is not None:
            label = self.settings.get('ai_msomi_model_label') or "model"
            if self._msomi_model is not None:
                rows.append(("  MSOMI Model", label))
            else:
                rows.append(("  MSOMI Model", f"{label} (invalid, ignored)"))
        return rows

    # ── starting ─────────────────────────────────────────────────────────
    def start_game(self, extra_ai_configs: Optional[List[dict]] = None) -> Optional[str]:
        """Builds player_configs from the CURRENT roster (host first,
        then joiners in join order, mirroring HostGame.start_game's
        seat-assignment rule), then starts the real GameManager.
        Returns an error string on failure, None on success."""
        extra_ai_configs = extra_ai_configs or []
        n_humans = len(self.member_names)
        if n_humans + len(extra_ai_configs) < MIN_PLAYERS:
            return f"Need at least {MIN_PLAYERS} players total."
        if n_humans + len(extra_ai_configs) > MAX_PLAYERS:
            return f"Too many players (max {MAX_PLAYERS})."

        configs = []
        seats = []
        for conn_id, name in self.member_names.items():
            configs.append({'name': name, 'is_human': True})
            seats.append(conn_id)
        for cfg in extra_ai_configs:
            configs.append(cfg)
            seats.append(None)  # AI seat, no owning connection

        # Two+ human players who both leave the name field at its
        # default ("Player") would otherwise be indistinguishable
        # everywhere (roster, turn indicator, settings panel) — this is
        # the one point that sees every seat's name at once, so it's
        # the only place that CAN catch that collision. See
        # network/player_names.py.
        disambiguated = disambiguate_names([c['name'] for c in configs])
        for cfg, name in zip(configs, disambiguated):
            cfg['name'] = name

        self._seat_by_conn = {conn_id: seat for seat, conn_id in enumerate(seats)
                              if conn_id is not None}
        self._conn_by_seat = {seat: conn_id for conn_id, seat in self._seat_by_conn.items()}
        self._seat_by_token = {self._token_by_conn[conn_id]: seat
                               for conn_id, seat in self._seat_by_conn.items()
                               if conn_id in self._token_by_conn}

        self.gm.subscribe(self._on_event)
        self.gm.new_game(configs, elimination_mode=bool(self.settings.get('elimination_mode')),
                         elimination_ai_only_continue=True)
        if self._msomi_model is not None:
            # Attaching post-construction (rather than threading a
            # model dict through GameManager.new_game()'s own
            # cfg['msomi_model_name'] file-loading path, which single-
            # player/LAN both rely on and which this deliberately
            # leaves untouched) -- msomi_model is just a plain
            # instance attribute AIPlayer reads at decision time (see
            # models/player.py), so setting it here, on every AI seat,
            # right after new_game() has actually created those
            # AIPlayer objects, has the identical effect.
            for seat, conn_id in enumerate(seats):
                if conn_id is None:
                    self.gm.players[seat].msomi_model = self._msomi_model
        self.started = True
        return None

    def _on_event(self, event: GameEvent):
        self._pending_events.append(encode_event(event))

    # ── per-tick drive ──────────────────────────────────────────────────────
    def tick(self, dt: float):
        if not self.started:
            return
        self.gm.update(dt)

    def _player_for_conn(self, conn_id: int):
        seat = self._seat_by_conn.get(conn_id)
        if seat is None:
            return None
        return self.gm.players[seat]

    def _match_hand_cards(self, player, requested):
        """See network/host_game.HostGame._match_hand_cards -- same
        logic verbatim: match client-supplied card dicts against this
        player's ACTUAL server-side hand, consuming each match at most
        once, so a client can never claim a card it doesn't hold or
        double-spend a duplicate."""
        pool = list(player.hand.cards)
        matched = []
        for rc in requested:
            found = None
            for c in pool:
                if c == rc:
                    found = c
                    break
            if found is None:
                return None
            pool.remove(found)
            matched.append(found)
        return matched

    def handle_intent(self, conn_id: int, msg: dict):
        """Identical validation rules to
        network/host_game.HostGame._handle_intent -- see that
        module's docstring for the rationale of each check. The only
        difference is looking up the acting player by conn_id via
        this room's own seat map instead of a LANHost player_id."""
        player = self._player_for_conn(conn_id)
        if player is None:
            return  # unknown connection for this room -- ignored
        t = msg.get('type')
        gm = self.gm

        if t == 'intent_play':
            if player is not gm.current_player:
                return
            cards = self._match_hand_cards(player, cards_from_list(msg.get('cards', [])))
            if cards is None:
                return
            gm.human_play(cards, declare_kadi=bool(msg.get('declare_kadi', False)),
                          declared_suit=suit_from_str(msg.get('declared_suit')))
        elif t == 'intent_draw':
            if player is not gm.current_player:
                return
            gm.human_draw()
        elif t == 'intent_declare_kadi':
            if player is not gm.current_player:
                return
            gm.human_declare_kadi()
        elif t == 'intent_choose_suit':
            if gm.state != GameState.SUIT_PICK or player is not gm.current_player:
                return
            suit = suit_from_str(msg.get('suit'))
            if suit is None:
                return
            gm.human_choose_suit(suit)
        elif t == 'intent_counter':
            if gm.state != GameState.JUMP_COUNTER_WINDOW:
                return
            if gm.players[gm.counter_player_idx] is not player:
                return
            cards = self._match_hand_cards(player, cards_from_list(msg.get('cards', [])))
            if cards is None:
                return
            gm.human_counter(cards)
        elif t == 'intent_pass_counter':
            if gm.state != GameState.JUMP_COUNTER_WINDOW:
                return
            if gm.players[gm.counter_player_idx] is not player:
                return
            gm.human_pass_counter()
        elif t == 'intent_post_play_declare_kadi':
            if gm.state != GameState.POST_PLAY or gm._post_play_player is not player:
                return
            gm.human_post_play_declare_kadi()
        elif t == 'intent_post_play_proceed':
            if gm.state != GameState.POST_PLAY or gm._post_play_player is not player:
                return
            gm.human_post_play_proceed()
        elif t == 'intent_toggle_pause':
            # Any seated player (not just the host) can pause/resume --
            # unlike turn-scoped intents above there's no "whose turn
            # is it" concept to gate this on, and every client is
            # equally a thin client of this room's authoritative gm
            # (see this module's class docstring), so there's no
            # special host-only path to fall back on either.
            gm.toggle_pause()
        # Undo is deliberately NOT exposed over the network -- same
        # scope cut as LAN (see network/README.md).

    def take_pending_events(self) -> List[dict]:
        events = self._pending_events
        self._pending_events = []
        return events

    def snapshot_for(self, conn_id: int, events: List[dict]) -> Optional[dict]:
        seat = self._seat_by_conn.get(conn_id)
        if seat is None:
            return None
        return build_snapshot_for(self.gm, seat, events)
