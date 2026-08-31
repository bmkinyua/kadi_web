"""
KADI - LAN networking: host-side game orchestrator.

Owns the ONE real, authoritative GameManager for a LAN match (the same
class single-player already uses, completely unmodified) plus the
LANHost socket layer. Every non-host player is a thin client: this
module is where their "intentions" (intent_play, intent_draw, ...) get
validated and turned into calls against the real, existing
GameManager.human_play()/human_draw()/etc — never a reimplementation
of any rule.

The host's OWN player does not go through any of this — the host's
local GameplayScene talks directly to self.gm exactly like
single-player already does. Only OTHER connected players are routed
through here.

DISCONNECT / RECONNECT (mid-game only, mirrors
server/game_room.GameRoom's identical Internet Multiplayer feature —
see that module's docstring for the full rationale, not repeated
here): a connected player's socket dying once the game has started
gets DISCONNECT_GRACE_SECONDS before GameManager.force_remove_player
actually takes their seat out of the match, tracked via an opaque
per-pid reconnect token handed out in poll_lobby()'s 'welcome' reply.
A fresh connection presenting that token (a 'rejoin_game' intent,
handled in _drain_intents) before the grace period elapses resumes the
seat under its own new pid and cancels the pending eviction.
"""
from __future__ import annotations
import time
import uuid
from typing import Callable, Dict, List, Optional

from constants import GameState, VERSION
from core.game_manager import GameManager, GameEvent
from models.player import HumanPlayer, AIPlayer
from network.host import LANHost, DEFAULT_PORT
from network.codec import cards_from_list, suit_from_str
from network.state_sync import build_snapshot_for
from network.event_codec import encode_event
from network.player_names import disambiguate_names

# See class docstring above / server/game_room.py's identical constant
# for Internet Multiplayer.
DISCONNECT_GRACE_SECONDS = 30.0


class HostGame:
    def __init__(self, port: int = DEFAULT_PORT, max_players: Optional[int] = None,
                gm: Optional[GameManager] = None):
        from constants import MAX_PLAYERS
        self.net = LANHost(port=port, max_players=max_players or MAX_PLAYERS)
        # By default builds its own GameManager (used by the standalone
        # loopback tests). scenes.LANHostLobbyScene instead passes in
        # the SceneManager's single shared GameManager, so the host's
        # own on-screen GameplayScene and the network layer are driving
        # the exact same live object — the host never needs a second,
        # redundant local game running alongside the "real" one.
        self.gm = gm if gm is not None else GameManager()
        self.host_name = "Host"
        # network player_id -> display name. 0 is always the host itself
        # (the host never goes through LANHost — it's a local player).
        self.player_names: Dict[int, str] = {}
        self.started = False
        # Built once at start_game() time: maps each connected network
        # player_id to the GameManager seat index (== Player.player_id)
        # it occupies, and back. NOT assumed to be the identity mapping —
        # a client that joined and left again during the lobby can leave
        # gaps in LANHost's own id sequence (it never reuses ids), so
        # this is computed fresh from whoever's actually still connected
        # at the moment the host clicks Start.
        self._seat_by_pid: Dict[int, int] = {}
        self._pid_by_seat: Dict[int, int] = {}
        self._pending_events: List[dict] = []
        self.on_lobby_change: Optional[Callable] = None
        # Plain chat -- see module docstring's disconnect/reconnect note
        # for the analogous Internet Multiplayer feature this mirrors
        # (server/game_room.py's identical relay, just here the HOST's
        # own player is a local seat rather than a network connection,
        # so its own messages have to be appended here directly rather
        # than ever looping back through LANHost). Each entry is
        # {'from': display name, 'text': str}. scenes.GameplayScene
        # polls this list (diffing by length) rather than a callback,
        # to keep this module UI-agnostic.
        self.chat_log: List[dict] = []

        # ── disconnect / reconnect bookkeeping (see module docstring) ──
        self._token_by_pid: Dict[int, str] = {}
        self._pid_by_token: Dict[str, int] = {}
        self._seat_by_token: Dict[str, int] = {}
        self._disconnected_at: Dict[int, float] = {}  # pid -> time.time() it dropped

    # ── Lobby ──────────────────────────────────────────────────────────────
    def start_listening(self, host_name: str = "Host"):
        self.host_name = host_name
        self.player_names[0] = host_name
        self.net.start()

    def local_ip(self) -> str:
        return self.net.local_ip()

    @property
    def port(self) -> int:
        return self.net.port

    def poll_lobby(self) -> List[dict]:
        """Call every frame while in the lobby (before start_game()).
        Processes connects/hellos/disconnects and returns the current
        roster: [{'player_id', 'name'}, ...] including the host as id 0."""
        changed = False
        for pid, msg in self.net.poll():
            t = msg.get('type')
            if t == 'hello':
                name = str(msg.get('name') or f"Player{pid + 1}")[:24]
                self.net.set_name(pid, name)
                self.player_names[pid] = name
                token = uuid.uuid4().hex
                self._token_by_pid[pid] = token
                self._pid_by_token[token] = pid
                self.net.send_to(pid, {'type': 'welcome', 'player_id': pid,
                                       'reconnect_token': token, 'host_version': VERSION})
                changed = True
            elif t == 'chat':
                text = str(msg.get('text') or '').strip()[:200]
                if text:
                    sender = self.player_names.get(pid, f"Player{pid + 1}")
                    self.chat_log.append({'from': sender, 'text': text})
                    self.net.broadcast({'type': 'chat', 'from': sender, 'text': text}, exclude=pid)
            elif t == '_disconnected':
                self.player_names.pop(pid, None)
                token = self._token_by_pid.pop(pid, None)
                if token is not None:
                    self._pid_by_token.pop(token, None)
                changed = True
        if changed and self.on_lobby_change:
            self.on_lobby_change(self.roster())
        return self.roster()

    def roster(self) -> List[dict]:
        ids = sorted(self.player_names.keys())
        return [{'player_id': i, 'name': self.player_names[i]} for i in ids]

    def broadcast_lobby(self, settings: dict):
        """Let every connected client see the current roster + the
        settings the host has configured (elimination mode, etc.) —
        joining players only see these, they don't set them (per spec:
        'host sets these, joining players just see them')."""
        self.net.broadcast({'type': 'lobby_state', 'players': self.roster(),
                            'settings': settings})

    # ── disconnect / reconnect (mid-game only) ──────────────────────────────
    def mark_disconnected(self, pid: int, now: Optional[float] = None):
        if pid not in self._seat_by_pid:
            return  # not a seated player of this match (or game hasn't started)
        self._disconnected_at[pid] = now if now is not None else time.time()

    def check_disconnect_timeouts(self, now: Optional[float] = None):
        now = now if now is not None else time.time()
        for pid, dropped_at in list(self._disconnected_at.items()):
            if now - dropped_at >= DISCONNECT_GRACE_SECONDS:
                self._evict(pid)

    def _evict(self, pid: int):
        self._disconnected_at.pop(pid, None)
        seat = self._seat_by_pid.get(pid)
        if seat is None or seat >= len(self.gm.players):
            return
        player = self.gm.players[seat]
        self.gm.force_remove_player(player)

    def reconnect(self, new_pid: int, token: Optional[str]) -> bool:
        """See server/game_room.GameRoom.reconnect — identical contract,
        just keyed by LANHost's own pid instead of a conn_id."""
        if not self.started or not token:
            return False
        seat = self._seat_by_token.get(token)
        if seat is None or seat >= len(self.gm.players):
            return False
        player = self.gm.players[seat]
        if player.finished:
            return False
        old_pid = self._pid_by_token.get(token)
        if old_pid is not None:
            self._seat_by_pid.pop(old_pid, None)
            self.player_names.pop(old_pid, None)
            self._disconnected_at.pop(old_pid, None)
        self._seat_by_pid[new_pid] = seat
        self._pid_by_seat[seat] = new_pid
        self._token_by_pid[new_pid] = token
        self._pid_by_token[token] = new_pid
        self.player_names[new_pid] = player.name
        return True

    # ── Starting the game ─────────────────────────────────────────────────
    def start_game(self, elimination_mode: bool = False,
                   elimination_ai_only_continue: bool = True,
                   extra_ai_configs: Optional[List[dict]] = None):
        """Builds player_configs from the CURRENT roster (host first,
        then connected clients in ascending id order), optionally
        padded with AI seats, then starts the real GameManager exactly
        like single-player's ModeSelectScene._start_game does."""
        ids = sorted(self.player_names.keys())
        configs = []
        seats = []
        for pid in ids:
            configs.append({'name': self.player_names[pid], 'is_human': True})
            seats.append(pid)
        for cfg in (extra_ai_configs or []):
            configs.append(cfg)
            seats.append(None)  # AI seat, no owning network connection

        # Two+ human players (the host plus one or more joining
        # clients) who all leave the name field at its default
        # ("Player"/"Host") would otherwise be indistinguishable
        # everywhere (roster, turn indicator, settings panel) — see
        # network/player_names.py, and server/game_room.py's identical
        # fix for Internet Multiplayer's equivalent of this room.
        disambiguated = disambiguate_names([c['name'] for c in configs])
        for cfg, name in zip(configs, disambiguated):
            cfg['name'] = name

        self._seat_by_pid = {pid: seat for seat, pid in enumerate(seats) if pid is not None}
        self._pid_by_seat = {seat: pid for pid, seat in self._seat_by_pid.items()}
        token_by_pid = getattr(self, '_token_by_pid', {})
        self._seat_by_token = {token_by_pid[pid]: seat
                               for pid, seat in self._seat_by_pid.items()
                               if pid in token_by_pid}

        self.gm.subscribe(self._on_event)
        self.gm.new_game(configs, elimination_mode=elimination_mode,
                         elimination_ai_only_continue=elimination_ai_only_continue)
        self.started = True
        self.net.broadcast({'type': 'start_game'})
        self._broadcast_state()

    def _on_event(self, event: GameEvent):
        self._pending_events.append(encode_event(event))

    # ── Per-frame drive ──────────────────────────────────────────────────
    def tick(self, dt: float):
        """Standalone driving method: drains intents, advances the real
        GameManager itself, and broadcasts. Used by the Phase 1/2
        loopback tests, which have no GameplayScene of their own ticking
        gm.update(). scenes.GameplayScene instead calls network_tick()
        (below), since ITS on-screen host already calls self.gm.update()
        every frame the normal single-player way — calling it a second
        time here would double-tick every timer."""
        if not self.started:
            return
        self._drain_intents()
        self.check_disconnect_timeouts()
        self.gm.update(dt)
        self._broadcast_state()

    def network_tick(self):
        """Call once per frame from GameplayScene.update(), AFTER it has
        already called self.gm.update() itself: drains queued client
        intents and broadcasts the resulting state. Does NOT touch
        gm.update() — see tick()'s docstring for why."""
        if not self.started:
            return
        self._drain_intents()
        self.check_disconnect_timeouts()
        self._broadcast_state()

    def send_chat(self, text: str):
        """The HOST's own chat message — never comes through
        _drain_intents (the host isn't its own network client), so this
        is the one path that both appends locally AND broadcasts, vs.
        a joining client's message (handled in _drain_intents below)
        which only needs relaying since the sender already sees their
        own text immediately in their own input box."""
        text = str(text or '').strip()[:200]
        if not text:
            return
        self.chat_log.append({'from': self.host_name, 'text': text})
        self.net.broadcast({'type': 'chat', 'from': self.host_name, 'text': text})

    def _drain_intents(self):
        for pid, msg in self.net.poll():
            t = msg.get('type')
            if t == '_disconnected':
                if self.started:
                    # Mid-game disconnect: give them
                    # DISCONNECT_GRACE_SECONDS to reconnect (a
                    # 'rejoin_game' intent with their token) before
                    # check_disconnect_timeouts() force-removes the
                    # seat via GameManager.force_remove_player. Until
                    # then the round just keeps going without them.
                    self.mark_disconnected(pid, time.time())
                continue
            if t == 'rejoin_game':
                token = msg.get('token')
                ok = self.reconnect(pid, token)
                self.net.send_to(pid, {'type': 'rejoined' if ok else 'reject',
                                       'player_id': pid,
                                       'reconnect_token': token if ok else None,
                                       'reason': None if ok else
                                                 'Could not reconnect — you may have '
                                                 'been removed from the match.'})
                continue
            if t == 'chat':
                text = str(msg.get('text') or '').strip()[:200]
                if not text:
                    continue
                sender = self.player_names.get(pid, f"Player{pid + 1}")
                self.chat_log.append({'from': sender, 'text': text})
                # Relayed to every OTHER client — the sender already
                # has their own message in their own chat_log the
                # instant they sent it (see ClientGameManager.send_chat).
                self.net.broadcast({'type': 'chat', 'from': sender, 'text': text}, exclude=pid)
                continue
            self._handle_intent(pid, msg)

    def _player_for_pid(self, pid: int):
        seat = self._seat_by_pid.get(pid)
        if seat is None:
            return None
        return self.gm.players[seat]

    def _match_hand_cards(self, player, requested):
        """Match client-supplied card dicts against this player's ACTUAL
        server-side hand (by rank+suit, same as Card.__eq__), consuming
        each match at most once so a client can never claim a card it
        doesn't hold or double-spend a duplicate (e.g. two Jokers).
        Returns the real Card objects from player.hand (preserving
        identity for any id()-based code downstream), or None if any
        requested card can't be matched."""
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

    def _handle_intent(self, pid: int, msg: dict):
        player = self._player_for_pid(pid)
        if player is None:
            return  # unknown connection (e.g. joined after game started) — ignored
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
            # Any player -- host or joined client -- can pause/resume;
            # see server/game_room.py's identical handling for the
            # Internet Multiplayer equivalent of this room.
            gm.toggle_pause()
        # Undo is deliberately NOT exposed over the network — see
        # network/README.md's "Known limitations" section.

    def _broadcast_state(self):
        events = self._pending_events
        self._pending_events = []
        for pid in self.net.player_ids():
            seat = self._seat_by_pid.get(pid)
            if seat is None:
                continue
            snap = build_snapshot_for(self.gm, seat, events)
            self.net.send_to(pid, snap)

    def stop(self):
        self.net.stop()
