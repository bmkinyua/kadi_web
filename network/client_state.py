"""
KADI - LAN networking: client-side GameManager mirror.

ClientGameManager exposes (as closely as practical) the same attribute
surface as the real core.game_manager.GameManager, so GameplayScene and
BoardRenderer — built for single-player and never touched by this
feature — can drive a network game exactly the way they already drive
a local one. Concretely this means:

  - self.players is a REAL list of models.player.Player objects,
    ROTATED so index 0 is always "you" (BoardRenderer hardcodes seat 0
    as the face-up hand at the bottom of the screen — see
    rendering/board_renderer.py's _layout_positions/is_seat0 — so
    rotating here is what lets that rendering code work completely
    unmodified rather than needing to special-case network play).
    Rotation preserves circular seating order (the neighbour to your
    left/right is still your actual neighbour), just relabels the
    starting point.
  - self.rule_engine is a REAL core.rule_engine.RuleEngine, rehydrated
    from the host's broadcast every snapshot. Nothing about the rules
    is reimplemented — this just means get_playable_cards()/
    get_hint_card() can call the exact same RuleEngine.is_playable()
    the host itself uses for instant local feedback, rather than
    waiting on a round trip.
  - Action methods (human_play, human_draw, ...) do NOT mutate
    anything locally. They send an "intent" message to the host and
    return immediately — the actual state change arrives on the next
    state_sync broadcast, same as it would for any other player's
    move. This is the server-authoritative model the whole feature is
    built around: the host's real GameManager is the only place any
    rule is ever actually applied.

KNOWN LIMITATIONS (see network/README.md for the full list):
  - Undo is host-local only; human_undo_last_action() is a no-op here.
  - cycle_ai_game_speed()/cycle_ai_spectator_speed() are no-ops — these
    affect host-side pacing only.
  - toggle_pause() sends an 'intent_toggle_pause' message and returns
    immediately, same pattern as human_play/human_draw/etc — the actual
    GameState.PAUSED flip is applied host-side and comes back on the
    next state_sync broadcast, same as any other player's move.
  - Hand order is a purely local, client-side concern: the server only
    ever tells us WHICH cards we hold, never in what order to show
    them, and re-sends the full hand on every snapshot. reorder_hand()
    and the reconciliation in _apply_snapshot() are what let a
    locally-dragged reorder survive the next snapshot instead of
    instantly snapping back.
"""
from __future__ import annotations
import threading
import time as _time
from typing import Callable, Dict, List, Optional

from constants import GameState, PlayDirection
from core.game_manager import GameManager as _RealGameManager
from core.rule_engine import RuleEngine
from core.settings_store import load_persisted_value
from models.card import Card
from models.player import Player, HumanPlayer, Hand
from network.client import LANClient, ConnectError
from network.codec import card_from_dict, cards_from_list, cards_to_list
from network.event_codec import decode_event


class _ClientDeckView:
    """Stand-in for models.card.Deck exposing only what rendering
    reads (draw_count/discard_count/top_card) — a network client is
    never dealt the actual draw pile or the rest of the discard pile,
    only its size and the visible top card, so building a real Deck
    here isn't possible or necessary."""
    def __init__(self):
        self.draw_count = 0
        self.discard_count = 0
        self.top_card: Optional[Card] = None

    @property
    def is_empty(self) -> bool:
        return self.draw_count <= 0


def _rotate_idx(real_seat: int, my_seat: int, n: int) -> int:
    return (real_seat - my_seat) % n


class ClientGameManager:
    # Rendering code reads this off the instance (self.gm.SPECTATOR_SPEEDS);
    # reuse the exact same ladder as the real GameManager rather than
    # duplicating the list and risking the two drifting apart.
    SPECTATOR_SPEEDS = _RealGameManager.SPECTATOR_SPEEDS

    def __init__(self, client: LANClient, resolution: tuple = (1280, 800),
                reconnect_info: Optional[dict] = None):
        self.client = client
        self.resolution = resolution

        # A dropped connection mid-match (see _on_disconnected below)
        # triggers an automatic background reconnect attempt using
        # these -- {'host', 'port', 'name', 'token', 'game_id' (LAN:
        # None), 'mode': 'lan'|'internet'} -- the same info the lobby
        # scene (LANJoinScene / InternetLobbyScene) already had on hand
        # from its own original connect + 'welcome' reply. Without
        # this (e.g. a caller that never passes it) a drop just goes
        # straight to 'lost', same as before this feature existed.
        self.reconnect_info = reconnect_info
        # 'ok' -- connected normally.
        # 'reconnecting' -- connection dropped, background retry in flight.
        # 'lost' -- gave up (no reconnect_info, or grace window expired).
        # GameplayScene reads this to show a banner / bail to the menu.
        self.connection_status = 'ok'
        self._reconnect_thread: Optional[threading.Thread] = None
        self._pending_client: Optional[LANClient] = None
        self._pending_lock = threading.Lock()

        # ── mirrored state (overwritten wholesale by every snapshot) ──
        self.state: GameState = GameState.PLAYING
        self.direction: PlayDirection = PlayDirection.CLOCKWISE
        self.elimination_mode = False
        self.elimination_ai_only_continue = True
        self.winner: Optional[Player] = None
        self.finish_order: List[Player] = []
        self.declared_kadi_player: Optional[Player] = None
        self.skipped_player: Optional[Player] = None
        self.last_effect_text = ""
        self.last_played_cards: List[Card] = []
        self.pickup_pending_display = 0
        self.players: List[Player] = []
        self.rule_engine = RuleEngine()
        self.deck = _ClientDeckView()
        self.current_player_idx = 0
        self.counter_player_idx = 0
        self.jump_player: Optional[Player] = None
        self.jump_skip_remaining = 0
        self.counter_timer = 0.0
        self.counter_window_secs = 5.0
        self._post_play_player: Optional[Player] = None
        self._post_play_can_kadi = False
        self.post_play_timer = 0.0
        self.post_play_delay_secs = 0.0
        self.turn_timer = 0.0
        self.turn_timer_secs = 30.0
        self.timers_enabled = True
        self.hints_enabled = False
        self.hint_threshold_pct = 50.0
        self.undo_available = False
        # Purely local, per-viewer display preference — like every other
        # field mirrored in __init__, NOT part of the host's
        # authoritative state (whether animations play is a decision
        # for whoever's looking at THIS screen, not something the host
        # broadcasts), so it's never in a snapshot and _apply_snapshot
        # never touches it. Sourced from the same settings.json the
        # local single-player GameManager loads at startup (see
        # core/settings_store.py) so a user who's turned animations off
        # gets that respected in network games too, rather than
        # silently defaulting on. See scenes.GameplayScene._animate_play/
        # _animate_draw, which read this exactly like they read the
        # real GameManager's own attribute of the same name.
        self.card_animations_enabled: bool = bool(
            load_persisted_value('card_animations_enabled'))
        self.ai_game_speed = 1.0
        self.ai_spectator_speed = 1.0
        self._turn_timer_active = True

        self._my_seat: Optional[int] = None
        self._players_by_seat: Dict[int, Player] = {}
        self._event_callbacks: List[Callable] = []
        self.started = False
        # Plain chat -- see network/host_game.HostGame.chat_log's
        # identical docstring for the LAN side of this. Each entry is
        # {'from': str, 'text': str}. scenes.GameplayScene polls this
        # list (diffing by length) rather than a callback, to keep this
        # module UI-agnostic.
        self.chat_log: List[dict] = []

        # Locally-remembered display order for MY OWN hand only (see
        # reorder_hand() and the reconciliation step in
        # _apply_snapshot() below) — the server has no notion of hand
        # order at all, so without this every snapshot would rebuild
        # our hand in whatever order the server happens to send it,
        # undoing any drag-to-reorder the instant the next snapshot
        # arrives.
        self._my_hand_order: List[Card] = []

    # ── wiring ────────────────────────────────────────────────────────────
    def subscribe(self, callback: Callable):
        self._event_callbacks.append(callback)

    def unsubscribe(self, callback: Callable):
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def _emit(self, event):
        for cb in list(self._event_callbacks):
            cb(event)

    def new_game(self, *args, **kwargs):
        # No-op: the host already started the real game. GameplayScene's
        # on_enter() calls new_game() for single-player; for network
        # play the caller (scenes.LANGameplayAdapter — see scenes.py)
        # skips this call entirely for clients, but it's kept as a
        # harmless no-op rather than an error in case anything ever
        # calls it defensively.
        pass

    # ── per-frame drive ──────────────────────────────────────────────────
    def update(self, dt: float):
        """No local simulation to run — the host ticks the real
        GameManager and broadcasts state every frame; this just drains
        whatever arrived since the last call and applies the latest
        snapshot(s) in order (in case more than one arrived between
        frames, only the fields matter, so re-applying older ones
        first is harmless — we just don't skip any 'events' lists)."""
        # A background reconnect (see _reconnect_loop) hands its new,
        # already-connected client back here rather than swapping
        # self.client directly from that thread -- this is the only
        # thread allowed to touch self.client, same rule every other
        # network module in this codebase follows.
        with self._pending_lock:
            if self._pending_client is not None:
                self.client = self._pending_client
                self._pending_client = None
                self.connection_status = 'ok'
        for msg in self.client.poll():
            self._handle_message(msg)

    def _handle_message(self, msg: dict):
        t = msg.get('type')
        if t == 'state_sync':
            self._apply_snapshot(msg)
        elif t == 'start_game':
            self.started = True
        elif t == 'chat':
            sender = str(msg.get('from') or '?')
            text = str(msg.get('text') or '')
            if text:
                self.chat_log.append({'from': sender, 'text': text})
        elif t == '_disconnected':
            self._on_disconnected()
        # 'lobby_state' / 'welcome' etc. are handled by the lobby scene
        # directly via client.poll(), not here — this object only
        # exists once the game has actually started.

    def send_chat(self, text: str):
        """Sent to the server/host, which relays it to everyone else
        (see server/kadi_server.py's 'chat' handling / network/host_game
        .HostGame._drain_intents's identical LAN relay) — and appended
        here immediately so the sender sees their own message right
        away rather than waiting on a round-trip echo."""
        text = str(text or '').strip()[:200]
        if not text:
            return
        self.chat_log.append({'from': "You", 'text': text})
        try:
            self.client.send({'type': 'chat', 'text': text})
        except Exception:
            pass  # a mid-send drop is caught by the usual reconnect path

    def _on_disconnected(self):
        if self.state == GameState.GAME_OVER:
            return  # match's already over -- nothing to reconnect to
        if self.connection_status == 'reconnecting':
            return  # a retry loop is already in flight
        if not self.reconnect_info:
            self.connection_status = 'lost'
            return
        self.connection_status = 'reconnecting'
        self._reconnect_thread = threading.Thread(target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    # A hair under the server/host-side grace window (both currently
    # 30s -- server/game_room.DISCONNECT_GRACE_SECONDS /
    # network/host_game.DISCONNECT_GRACE_SECONDS) so this gives up
    # slightly before the seat is actually evicted rather than slightly
    # after, and never reports 'ok' for a reconnect that only "succeeds"
    # because the seat happened to still be there by luck of timing.
    RECONNECT_GRACE_SECONDS = 28.0
    RECONNECT_RETRY_INTERVAL = 1.5

    def _reconnect_loop(self):
        """Runs on a background thread (never touches self.client,
        self.players, or anything else this object exposes to the main
        thread -- only self._pending_client, under _pending_lock, and
        self.connection_status, a single plain attribute write which is
        safe from any thread in CPython). Keeps retrying the SAME
        server address + identity + reconnect token until either a
        fresh connection is accepted back into the match (see
        server/game_room.GameRoom.reconnect / network/host_game
        .HostGame.reconnect) or the grace window runs out."""
        info = self.reconnect_info
        deadline = _time.time() + self.RECONNECT_GRACE_SECONDS
        while _time.time() < deadline:
            new_client = LANClient()
            try:
                new_client.connect(info['host'], info['port'], info['name'])
            except ConnectError:
                _time.sleep(self.RECONNECT_RETRY_INTERVAL)
                continue
            rejoin_msg = {'type': 'rejoin_game', 'token': info.get('token')}
            if info.get('game_id'):
                rejoin_msg['game_id'] = info['game_id']
            new_client.send(rejoin_msg)

            reply = None
            wait_deadline = _time.time() + 2.5
            while _time.time() < wait_deadline:
                for m in new_client.poll():
                    if m.get('type') in ('rejoined', 'reject'):
                        reply = m
                if reply is not None:
                    break
                _time.sleep(0.1)

            if reply is not None and reply.get('type') == 'rejoined':
                with self._pending_lock:
                    self._pending_client = new_client
                return
            new_client.close()
            _time.sleep(self.RECONNECT_RETRY_INTERVAL)
        self.connection_status = 'lost'

    # ── snapshot application ───────────────────────────────────────────────
    def _apply_snapshot(self, snap: dict):
        my_seat = snap['you']
        self._my_seat = my_seat
        n = len(snap['players'])

        seat_players: List[Player] = []
        by_seat: Dict[int, Player] = {}
        for entry in snap['players']:
            seat = entry['player_id']
            p = HumanPlayer(name=entry['name'], player_id=seat) if entry['is_human'] else \
                Player(name=entry['name'], player_id=seat, is_human=False)
            p.score = entry['score']
            p.has_declared_kadi = entry['has_declared_kadi']
            p.finished = entry['finished']
            p.finish_place = entry['finish_place']
            p.hand = Hand()
            if entry['hand'] is not None:
                p.hand.add(cards_from_list(entry['hand']))
            else:
                # Opponent's hand contents are never sent (see
                # network/state_sync.py's privacy boundary) — only the
                # count. Placeholder cards of the right COUNT let
                # rendering lay out the correct number of face-down
                # card backs; their rank/suit is never read because
                # HandRenderer/get_card_surface short-circuits to the
                # card-back art whenever face_up=False.
                placeholder = Card(suit=None, rank='2')
                p.hand.add([placeholder] * entry['hand_count'])
            seat_players.append(p)
            by_seat[seat] = p
        self._players_by_seat = by_seat

        rotated = seat_players[my_seat:] + seat_players[:my_seat]

        # Reapply our locally-remembered order to OUR OWN hand
        # (rotated[0]) before publishing it. The server sent the
        # correct SET of cards we hold, just not necessarily in the
        # order we last arranged them, so: keep everything from
        # _my_hand_order that's still in the new hand (in that
        # order), then append anything new (e.g. a just-drawn card)
        # that wasn't in _my_hand_order yet, in the order the server
        # sent it. Cards we no longer hold (e.g. just played) simply
        # drop out. See reorder_hand() below for how a drag updates
        # _my_hand_order in the first place.
        my_hand = rotated[0].hand._cards
        pool = list(my_hand)
        reordered: List[Card] = []
        for c in self._my_hand_order:
            if c in pool:
                pool.remove(c)
                reordered.append(c)
        reordered.extend(pool)
        rotated[0].hand._cards = reordered
        self._my_hand_order = list(reordered)

        self.players = rotated

        self.state = GameState[snap['state']]
        self.current_player_idx = _rotate_idx(snap['current_player_idx'], my_seat, n)
        self.direction = PlayDirection[snap['direction']]
        self.elimination_mode = snap['elimination_mode']
        self.elimination_ai_only_continue = snap['elimination_ai_only_continue']
        self.winner = by_seat.get(snap['winner_id']) if snap['winner_id'] is not None else None
        self.finish_order = [by_seat[i] for i in snap['finish_order_ids'] if i in by_seat]
        self.declared_kadi_player = (by_seat.get(snap['declared_kadi_player_id'])
                                     if snap['declared_kadi_player_id'] is not None else None)
        self.skipped_player = (by_seat.get(snap['skipped_player_id'])
                               if snap['skipped_player_id'] is not None else None)
        self.last_effect_text = snap['last_effect_text']
        self.last_played_cards = cards_from_list(snap['last_played_cards'])
        self.pickup_pending_display = snap['pickup_pending_display']

        re_data = snap['rule_engine']
        re = RuleEngine()
        re.current_suit = _suit_or_none(re_data['current_suit'])
        re.pickup_pending = re_data['pickup_pending']
        re.pickup_rank = re_data['pickup_rank']
        re.pickup_suit = _suit_or_none(re_data['pickup_suit'])
        re._top_card = card_from_dict(re_data['top_card'])
        re.skip_count = re_data['skip_count']
        re.joker_on_top = re_data['joker_on_top']
        re.ace_suit_integrity = re_data['ace_suit_integrity']
        re.pickup_shield_qk_allowed = re_data['pickup_shield_qk_allowed']
        re.ace_finisher_enabled = re_data['ace_finisher_enabled']
        re.jump_multi_card_enabled = re_data['jump_multi_card_enabled']
        self.rule_engine = re

        self.deck.draw_count = snap['deck']['draw_count']
        self.deck.discard_count = snap['deck']['discard_count']
        self.deck.top_card = re._top_card

        self.counter_player_idx = _rotate_idx(snap['counter_player_idx'], my_seat, n)
        self.jump_player = (by_seat.get(snap['jump_player_id'])
                            if snap['jump_player_id'] is not None else None)
        self.jump_skip_remaining = snap['jump_skip_remaining']
        self.counter_timer = snap['counter_timer']
        self.counter_window_secs = snap['counter_window_secs']

        pp = snap['post_play']
        if pp:
            self._post_play_player = by_seat.get(pp['player_id'])
            self._post_play_can_kadi = pp['can_kadi']
            self.post_play_timer = pp['timer']
        else:
            self._post_play_player = None
            self._post_play_can_kadi = False
            self.post_play_timer = 0.0

        self.turn_timer = snap['turn_timer']
        self.turn_timer_secs = snap['turn_timer_secs']
        self.timers_enabled = snap['timers_enabled']
        self.post_play_delay_secs = snap['post_play_delay_secs']
        self.hints_enabled = snap['hints_enabled']
        self.hint_threshold_pct = snap['hint_threshold_pct']
        self.undo_available = False

        for ev_msg in snap.get('events', []):
            event = decode_event(ev_msg, by_seat)
            self._emit(event)

    # ── read-only derived properties (mirroring GameManager's own) ────────
    @property
    def current_player(self) -> Player:
        return self.players[self.current_player_idx]

    @property
    def human_player(self) -> Optional[Player]:
        return self.players[0] if self.players else None

    @property
    def is_paused(self) -> bool:
        return self.state == GameState.PAUSED

    @property
    def is_ai_spectator_mode(self) -> bool:
        if not self.elimination_mode or self.state == GameState.GAME_OVER:
            return False
        active = [p for p in self.players if not p.finished]
        if not active:
            return False
        return not any(p.is_human for p in active)

    @property
    def hint_should_show(self) -> bool:
        if not self.hints_enabled or not self.timers_enabled:
            return False
        if self.turn_timer_secs <= 0:
            return False
        if self.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return False
        if not self.current_player.is_human:
            return False
        elapsed = self.turn_timer_secs - self.turn_timer
        fraction = elapsed / self.turn_timer_secs
        return fraction >= (self.hint_threshold_pct / 100.0)

    def get_playable_cards(self) -> List[Card]:
        return self.current_player.hand.get_playable(self.rule_engine)

    def get_hint_card(self) -> Optional[Card]:
        player = self.current_player
        if not player.is_human:
            return None
        playable = player.hand.get_playable(self.rule_engine)
        return playable[0] if playable else None

    def cycle_ai_game_speed(self, direction: int):
        pass  # host-side pacing only — see module docstring

    def cycle_ai_spectator_speed(self, direction: int):
        pass  # host-side pacing only — see module docstring

    def toggle_pause(self):
        self.client.send({'type': 'intent_toggle_pause'})

    def reorder_hand(self, from_idx: int, to_idx: int):
        """Rearrange OUR OWN hand's display order. Purely local/cosmetic
        — the server doesn't track or care about card order — but the
        new order is remembered in _my_hand_order so it survives the
        next state_sync's snapshot (see _apply_snapshot's
        reconciliation step)."""
        if not self.players:
            return
        cards = self.players[0].hand._cards
        if not (0 <= from_idx < len(cards)) or not (0 <= to_idx < len(cards)):
            return
        card = cards.pop(from_idx)
        cards.insert(to_idx, card)
        self._my_hand_order = list(cards)

    # ── actions: send an intent, don't mutate locally ─────────────────────
    def human_play(self, cards: List[Card], declare_kadi: bool = False,
                   declared_suit=None):
        self.client.send({
            'type': 'intent_play',
            'cards': cards_to_list(cards),
            'declare_kadi': declare_kadi,
            'declared_suit': declared_suit.name if declared_suit else None,
        })

    def human_draw(self):
        self.client.send({'type': 'intent_draw'})

    def human_declare_kadi(self):
        self.client.send({'type': 'intent_declare_kadi'})

    def human_choose_suit(self, suit):
        self.client.send({'type': 'intent_choose_suit', 'suit': suit.name})

    def human_counter(self, cards: List[Card]):
        self.client.send({'type': 'intent_counter', 'cards': cards_to_list(cards)})

    def human_pass_counter(self):
        self.client.send({'type': 'intent_pass_counter'})

    def human_post_play_declare_kadi(self):
        self.client.send({'type': 'intent_post_play_declare_kadi'})

    def human_post_play_proceed(self):
        self.client.send({'type': 'intent_post_play_proceed'})

    def human_undo_last_action(self):
        pass  # undo is host-local only — see module docstring


def _suit_or_none(name: Optional[str]):
    if not name:
        return None
    from constants import Suit
    return Suit[name]
