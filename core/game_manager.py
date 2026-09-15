"""
KADI - Game Manager
Central state machine: drives turns, effects, win detection.
"""
from __future__ import annotations
import random
import uuid
from collections import Counter
from typing import List, Optional, Callable, Union, TYPE_CHECKING
from models.card import Card, Deck
from models.player import (Player, HumanPlayer, AIPlayer, Hand,
                           enumerate_legal_plays, evaluate_play, evaluate_draw)
from core.rule_engine import RuleEngine
from core.game_logger import game_log
from core import decision_logger
from core import msomi_trainer
from constants import (
    GameState, PlayDirection, CardType, Suit, AIDifficulty,
    STARTING_HAND, COUNTER_WINDOW_SECS, MIN_PLAYERS, MAX_PLAYERS
)

if TYPE_CHECKING:
    pass


class GameEvent:
    """Lightweight event object passed to UI callbacks."""
    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        self.__dict__.update(kwargs)

    def __repr__(self):
        return f"GameEvent({self.kind})"


def classify_finish_kind(cards: List[Card]) -> Optional[str]:
    """Classify a winning play's cards into one of the four distinct
    multi-card finish mechanics tracked in the player profile (Part 1/4),
    or None for an ordinary single-card (or otherwise unclassified)
    finish. Derived from card_type shape rather than tracked separately
    through play, since GameManager doesn't otherwise tag *why* a play
    was legal.

    IMPORTANT — this mirrors RuleEngine.order_for_closing's ACTUAL
    grammar, which is stricter than it might look at a glance: every
    multi-card close is a run of "leader" cards (all one non-FINISHING
    type) capped by a trailing "answer" of CardType.FINISHING cards —
    see order_for_closing's `if not finishing: return None`, which
    applies to EVERY shape except a same-rank all-FINISHING set.
    Neither QUESTION (8/Q) nor KICKBACK (K) is ever CardType.FINISHING,
    so a play made of *only* Question cards or *only* Kickback cards
    can NEVER legally close a hand — an earlier version of this
    function required exactly that (`all(t == CardType.QUESTION ...)`
    over the whole play), which made 'question_chain' and
    'kickback_run' unearnable in practice. Fixed to split on
    leaders-vs-finishing instead, matching jump_bundle's shape, which
    was already correct.

      - question_chain: a run of Question (8/Q) leaders followed by a
        trailing FINISHING-type answer.
      - kickback_run: an EVEN-count run of Kickback (K) leaders
        followed by a trailing FINISHING-type answer (the "even-
        Kickback-run" house rule — see order_for_closing).
      - jump_bundle: a run of Jump (J) leaders followed by a trailing
        FINISHING-type answer.
      - ace_finisher: a single ACE (SUIT_CHANGE) leader, with or
        without a trailing FINISHING answer (order_for_closing allows
        ACE+finishing with no suit/rank constraints on the answer;
        see its SUIT_CHANGE branch) — this one doesn't require the
        whole play to be ACE-only, just that an ACE is the leader.
    """
    if not cards:
        return None
    types = [c.card_type for c in cards]
    finishing = [t for t in types if t == CardType.FINISHING]
    leaders = [t for t in types if t != CardType.FINISHING]
    if not leaders:
        return None  # a same-rank all-FINISHING close — ordinary finish, no multi-card badge
    if len(set(leaders)) != 1:
        return None  # mixed leader types never occur in a legal play, but guard anyway
    leader_type = leaders[0]

    if leader_type == CardType.SUIT_CHANGE:
        return 'ace_finisher'
    if not finishing:
        return None  # Question/Kickback/Jump leaders with no FINISHING answer can't legally close
    if leader_type == CardType.QUESTION:
        return 'question_chain'
    if leader_type == CardType.KICKBACK and len(leaders) % 2 == 0:
        return 'kickback_run'
    if leader_type == CardType.JUMP:
        return 'jump_bundle'
    return None


class GameManager:
    def __init__(self):
        # Core objects
        self.deck: Optional[Deck] = None
        self.players: List[Player] = []
        self.rule_engine = RuleEngine()

        # Game settings
        self.joker_count: int = 2
        self.suit_change_after_shield: bool = False
        self.ace_suit_integrity: bool = False  # True = ACE must match suit to be played
        # True (default) = an ACE ending a Question or Kickback(even)
        # chain may still shield (fully cancel) a pending pick-up, e.g.
        # [Q♦, A♦] cancelling a pending +7 — not just a lone/leading ACE.
        # False restricts shielding to a solo/ACE-led play only. A
        # Jump-led shield is never allowed either way — see
        # RuleEngine.pickup_shield_qk_allowed's docstring.
        self.pickup_shield_qk_allowed: bool = True
        # Master on/off for the "ACE + finishing cards" multi-card KADI
        # shape and the "Jump-chain + extra card" multi-card KADI
        # shape/play, respectively — see RuleEngine.ace_finisher_enabled
        # and RuleEngine.jump_multi_card_enabled's docstrings. Kept as
        # separate toggles since they're each a genuinely different,
        # fairly complex mechanic from the simpler Q/K-chain shapes.
        self.ace_finisher_enabled: bool = True
        self.jump_multi_card_enabled: bool = True
        self.ai_difficulty: AIDifficulty = AIDifficulty.MEDIUM
        # Logging: 'OFF', 'LOW' (major events), 'HIGH' (everything, for debugging)
        # Default HIGH (not OFF) — shipped builds log by default so that
        # Chuo/MSOMI has real games to train from out of the box, without
        # anyone needing to know to turn logging on first. See the Chuo
        # onboarding help for the corresponding player-facing guidance.
        self.log_level: str = 'HIGH'
        # Cap on how many LOG_*.log(+.jsonl) pairs are kept in logs/;
        # 0 = unlimited (default). See core.game_logger.cleanup_old_logs.
        self.max_log_pairs: int = 0
        # Turn timer settings (seconds; 0 = no timer)
        self.turn_timer_secs: float = 150.0
        self.post_play_delay_secs: float = 60.0   # next-player delay / KADI check window
        self.counter_window_secs: float = 60.0    # J counter window duration
        self.timers_enabled: bool = True
        # Card-play hints: after hint_threshold_pct of the turn timer has
        # elapsed, highlight one legal card the human could play. This is
        # deliberately NOT a strong AI suggestion — see get_hint_card().
        self.hints_enabled: bool = False
        self.hint_threshold_pct: float = 50.0
        # Window resolution (width, height)
        self.resolution: tuple = (1280, 800)
        # If True, the startup resolution picker (main.py) is skipped and
        # `resolution` above is used directly — set when the player ticks
        # "Don't ask again" in that picker. Deliberately re-shown anyway if
        # the saved resolution no longer fits the detected display (see
        # main.py's _should_show_startup_picker()), so this flag can never
        # by itself leave someone stuck the way an oversized resolution did
        # before the picker existed.
        self.skip_startup_resolution_picker: bool = False
        # Background music + Chuo drum layer on/off, and its volume
        # (0.0-1.0). Sound effects have their own independent on/off +
        # volume, applied in AssetLoader.
        self.music_enabled: bool = True
        self.music_volume: float = 0.5
        self.sfx_enabled: bool = True
        self.sfx_volume: float = 0.5
        # Placeholder banner ad slot (see scenes.py's AdBanner) — dev-only
        # toggle, no real ad network wired in. Defaults to False (see the
        # matching default in core/settings_store.py for why: Steam's
        # policy against third-party ad networks, decided as part of the
        # itch.io -> Steam -> publisher distribution plan) so the banner
        # never renders or reserves layout space out of the box. Kept as
        # a live toggle rather than deleted, in case that decision changes.
        self.ads_enabled: bool = False

        # Card animations (play-to-discard, draw-from-deck, initial
        # deal, jump-in counters, penalty-draw stacks — see
        # animation/animator.py's AnimationManager and this scene's
        # wiring in GameplayScene). Defaults on: this is the intended
        # game feel, not a debug feature — off is for players who
        # prefer snappier/instant card resolution, or find motion
        # distracting.
        self.card_animations_enabled: bool = True

        # Runtime state
        self.state: GameState = GameState.MAIN_MENU
        self.direction: PlayDirection = PlayDirection.CLOCKWISE
        self.current_player_idx: int = 0
        self.declared_kadi_player: Optional[Player] = None
        self.pending_suit_change: bool = False
        self.pending_suit_card: Optional[Card] = None
        self.pending_suit_cards: Optional[List[Card]] = None  # full set being played

        # Public play history per player_id: which suits they've actually
        # played, used only by AIPlayer._pick_suit() at higher difficulty
        # to guess a threatening opponent's likely suit "signature" and
        # steer a suit change away from it. Built entirely from cards
        # already visible on the discard pile — never hidden hand info.
        self.suit_history: dict = {}

        # J-counters-J (the only counter mechanic in the game)
        self.counter_timer: float = 0.0
        self.counter_player_idx: int = 0   # which player is being asked to counter
        self.jump_player: Optional[Player] = None
        self.jump_skip_remaining: int = 0
        # If the play that opened the current counter window bundled a
        # non-Jump "extra" card behind its Jump chain (e.g. [J♦, J♣, 2♣]
        # — two Jumps answered by a pick-up card — see
        # RuleEngine.jump_bundle_legal), this holds everything needed to
        # give that card back if the chain gets successfully countered:
        # who played it, the card(s) themselves, the rule-engine state
        # from just before the whole combo, and the last Jump actually
        # played (to restore as the top card in place of the bundled
        # one). None means the play that opened this window had no such
        # bundled extra card. See _finish_play (where this is set) and
        # _execute_jump_counter (where a successful counter reverses it).
        self._jump_bundle: Optional[dict] = None

        # AI state
        self._ai_thinking: bool = False
        self._extra_turn_remaining: int = 0

        # Turn timer (counts down for human turns)
        self.turn_timer: float = 0.0        # current countdown
        self._turn_timer_active: bool = False

        # Post-play KADI declaration window
        self._pending_kadi_player: Optional[Player] = None
        self._pending_kadi_cards: Optional[List[Card]] = None
        self._pending_kadi_result: Optional[dict] = None
        self._pending_kadi_declare_kadi: bool = False
        self._pending_kadi_declared_suit: Optional['Suit'] = None
        self.kadi_window_timer: float = 0.0
        self._kadi_window_active: bool = False

        # Unified post-play delay (replaces separate KADI window)
        self.post_play_timer: float = 0.0
        self._post_play_result: Optional[dict] = None
        self._post_play_player: Optional[Player] = None
        self._post_play_can_kadi: bool = False

        # Stall detection
        self._consecutive_draws: int = 0
        self._max_consecutive_draws: int = 30

        # Pause
        self._pre_pause_state: Optional[GameState] = None

        # Message/event bus
        self._event_callbacks: List[Callable] = []

        # Last play info (for UI)
        self.last_played_cards: List[Card] = []
        self.last_effect_text: str = ""
        self.pickup_pending_display: int = 0

        # Round result
        self.winner: Optional[Player] = None
        # Elimination Mode: when on, the game doesn't end at the first
        # win — that player is set aside and play continues among the
        # rest until only one player is left holding cards (the loser).
        # finish_order records placement: index 0 finished first (best),
        # the last entry is whoever was left holding cards (worst).
        self.elimination_mode: bool = False
        self.finish_order: List[Player] = []
        # Players force_remove_player() has taken out of the match for
        # being disconnected too long, but not yet finalized into
        # finish_order — see _finalize_round_end for why this has to
        # be a separate holding pen rather than appending them to
        # finish_order immediately: leaving the match early must never
        # earn a better placement than actually finishing it, no
        # matter how much EARLIER in real time the disconnect happened
        # relative to anyone else's legitimate finish.
        self._disconnected_removed: List[Player] = []
        # When all human players have finished in Elimination Mode, this
        # decides what happens to the AI players still playing it out:
        # True (default) = keep going and let the AIs play to a real
        # last-place loser — useful for previewing/prepping multiplayer.
        # False = end the round the moment no humans are left active,
        # ranking whichever AIs remain by finishing cards in hand.
        self.elimination_ai_only_continue: bool = True

        # AI Spectator Mode: once every human has finished (see
        # elimination_ai_only_continue above) the remaining AIs play the
        # round out on their own — see is_ai_spectator_mode below.
        # ai_spectator_speed scales dt during that stretch only (the
        # scene multiplies its dt by this before calling update()), so
        # someone watching can slow the AI-vs-AI play down to actually
        # follow it, or speed it up to skip through it. 1.0 = normal.
        self.ai_spectator_speed: float = 1.0

        # Same idea as ai_spectator_speed above, but for ordinary play —
        # scales how fast AI turns move (their "thinking" pause and
        # post-play delay) any time it's not spectator mode. Kept as a
        # separate dial from ai_spectator_speed rather than reusing it:
        # someone might want AI-vs-human turns to move briskly during
        # normal play but still want the fully-automated spectator
        # stretch at the end to run at its own, separately-chosen pace.
        self.ai_game_speed: float = 1.0

        # Track skipped players for UI
        self.skipped_player: Optional[Player] = None

        # Undo: a one-shot snapshot taken right before the most recent play
        # or draw, so the human player can back out of it during the
        # POST_PLAY (KADI check) window and choose a different move instead.
        # Cleared whenever a new turn begins or it's actually used.
        self._undo_snapshot: Optional[dict] = None

        # Profile (persistent player progress — see core/profile_store.py).
        # None until main.py loads one and assigns it here; every profile-
        # aware code path below (undo tokens, stat/badge recording) treats
        # a None profile as "profile system not wired up in this context"
        # and simply skips itself rather than raising, so tests/tools that
        # construct a bare GameManager without going through main.py keep
        # working unchanged.
        self.profile: Optional[dict] = None
        # Newly-earned badge ids from the most recently finalized game,
        # for the UI to pop notifications for (see finalize_profile_stats
        # and scenes.py's consumption of it). Cleared by the UI after
        # reading, not by GameManager itself.
        self.pending_badge_notifications: List[str] = []

        # game_id / _stats_recorded_for_game_id are normally (re)set by
        # new_game() for a freshly-started match. Defaulted here too so
        # any code path that rehydrates a GameManager without going
        # through new_game() (e.g. save_manager.load_game()) still has
        # them defined — finalize_profile_stats() reads both unconditionally.
        self.game_id: str = str(uuid.uuid4())
        self._stats_recorded_for_game_id = None  # see finalize_profile_stats
        self._reset_game_trackers()

    # ─── Setup ────────────────────────────────────────────────────────────────

    def set_log_level(self, level: str):
        from core.game_logger import set_log_level as _set
        self.log_level = level
        _set(level)
        game_log.info(f"Log level set to {level}")

    def new_game(self, player_configs: List[dict], elimination_mode: bool = False,
                 elimination_ai_only_continue: bool = True):
        """
        player_configs: list of {'name': str, 'is_human': bool, 'difficulty': AIDifficulty}
        """
        assert MIN_PLAYERS <= len(player_configs) <= MAX_PLAYERS

        self.elimination_mode = elimination_mode
        self.elimination_ai_only_continue = elimination_ai_only_continue
        self.finish_order = []
        self._disconnected_removed = []

        # Tags every decision logged this game (see core/decision_logger)
        # so Chuo can tell which decisions belong to the same game —
        # needed for any future outcome-based training, and useful even
        # now for basic dataset sanity checks.
        self.game_id = str(uuid.uuid4())
        decision_logger.set_game_id(self.game_id)

        self.deck = Deck(joker_count=self.joker_count)
        self.players = []
        for i, cfg in enumerate(player_configs):
            if cfg['is_human']:
                p = HumanPlayer(cfg['name'], i)
            else:
                p = AIPlayer(cfg['name'], i, cfg.get('difficulty', self.ai_difficulty))
                model_name = cfg.get('msomi_model_name')
                if model_name:
                    try:
                        model = msomi_trainer.load_model(model_name)
                        problem = msomi_trainer.validate_model(model)
                        if problem:
                            game_log.info(f"MSOMI model '{model_name}' for {cfg['name']} "
                                          f"rejected: {problem}")
                        else:
                            p.msomi_model = model
                    except Exception as e:
                        game_log.info(f"MSOMI model '{model_name}' for {cfg['name']} "
                                      f"failed to load: {e}")
            self.players.append(p)

        self._deal_starting_hands()
        start_card = self.deck.place_start_card()
        self.rule_engine = RuleEngine()
        self.rule_engine.set_top_card(start_card)
        self.rule_engine.ace_suit_integrity = self.ace_suit_integrity
        self.rule_engine.pickup_shield_qk_allowed = self.pickup_shield_qk_allowed
        self.rule_engine.ace_finisher_enabled = self.ace_finisher_enabled
        self.rule_engine.jump_multi_card_enabled = self.jump_multi_card_enabled

        self.direction = PlayDirection.CLOCKWISE
        # Who goes first is random every game — previously this was
        # hardcoded to seat 0, which in the current single-player setup
        # (one human + AI bots) is always the human, so the person was
        # unfairly guaranteed the opening move every single game. This
        # is the single-player version of that choice; a proper
        # multi-human "wheel of fortune"-style pick is future work for
        # when real multiplayer exists (see network/), not something to
        # fake here.
        self.current_player_idx = random.randrange(len(self.players))
        self.declared_kadi_player = None
        self.winner = None
        self.last_played_cards = []
        self.last_effect_text = ""
        self.pickup_pending_display = 0
        self.skipped_player = None
        self._undo_snapshot = None
        self.suit_history = {p.player_id: Counter() for p in self.players}
        self._jump_bundle = None
        self._stats_recorded_for_game_id = None  # see finalize_profile_stats
        self._session_elapsed = 0.0  # see update()/finalize_profile_stats
        self._reset_game_trackers()

        # Undo tokens (Profile Part 3) reset to the default balance (or
        # a bit higher — see the bonus-on-return system in
        # profile_store.py) at the start of every new game —
        # single-player, hot-seat, AND a freshly-hosted LAN/Internet
        # match (this last one is a deliberate extension beyond the
        # spec's literal "single-player" wording: see the READ FIRST
        # report — undo in LAN/Internet is host-local only and runs
        # through this exact same GameManager, so resetting it here too
        # keeps the host's token balance from silently running out and
        # staying stuck at 0 across unrelated matches). Never touched
        # for a client-side ClientGameManager, which doesn't have
        # tokens or call new_game() at all.
        if self.profile is not None:
            from core.profile_store import (compute_game_start_undo_tokens,
                                             mark_played_now, save_profile)
            # Compute BEFORE marking — mark_played_now stamps "now" as
            # last_played_at, which would zero out the elapsed-time
            # bonus calculation if done first.
            self.profile['undo_tokens'] = compute_game_start_undo_tokens(self.profile)
            mark_played_now(self.profile)
            # Force a save right here (rather than waiting for the next
            # natural save point — a token spend, a badge, game-end)
            # so last_played_at is durable even if this game is quit
            # immediately; otherwise a same-session-only stamp would
            # never actually measure real time away between sessions.
            save_profile(self.profile)

        self.state = GameState.PLAYING

        # Log every pre-game setting that shapes how this round is
        # played — most importantly each AI player's actual difficulty,
        # which was previously invisible in the log (every AI turn just
        # showed the bot's name, so a log couldn't confirm whether a
        # given play came from EASY, MEDIUM, or HARD).
        player_summary = ", ".join(
            f"{p.name}={'HUMAN' if p.is_human else p.difficulty.name}"
            for p in self.players
        )
        game_log.info(
            "=== New game — players: [%s] — elimination_mode=%s "
            "elimination_ai_only_continue=%s ace_suit_integrity=%s "
            "pickup_shield_qk_allowed=%s ace_finisher_enabled=%s "
            "jump_multi_card_enabled=%s "
            "joker_count=%s suit_change_after_shield=%s "
            "timers_enabled=%s turn_timer_secs=%s post_play_delay_secs=%s "
            "counter_window_secs=%s hints_enabled=%s hint_threshold_pct=%s "
            "ai_spectator_speed=%s ===" % (
                player_summary, self.elimination_mode,
                self.elimination_ai_only_continue, self.ace_suit_integrity,
                self.pickup_shield_qk_allowed, self.ace_finisher_enabled,
                self.jump_multi_card_enabled,
                self.joker_count, self.suit_change_after_shield,
                self.timers_enabled, self.turn_timer_secs,
                self.post_play_delay_secs, self.counter_window_secs,
                self.hints_enabled, self.hint_threshold_pct,
                self.ai_spectator_speed,
            )
        )

        self._emit(GameEvent('game_started', start_card=start_card, players=self.players))
        self._start_turn()

    def _deal_starting_hands(self):
        self.deck.shuffle()
        for p in self.players:
            p.hand = Hand()
            p.has_declared_kadi = False
            cards = self.deck.deal(STARTING_HAND)
            p.hand.add(cards)

    # ─── Turn management ──────────────────────────────────────────────────────

    def _start_turn(self):
        # Elimination Mode is the usual reason a seated player can be
        # `finished` mid-round, but it's not the only one any more --
        # force_remove_player() can mark a disconnected human finished
        # in STANDARD mode too, so this skip is unconditional rather
        # than gated on self.elimination_mode. In standard mode this
        # loop is simply a no-op until that happens (the game already
        # ends outright at the first ordinary finish), so nothing
        # about existing behavior changes.
        n = len(self.players)
        step = self.direction.value
        guard = 0
        while self.players[self.current_player_idx].finished:
            self.current_player_idx = (self.current_player_idx + step) % n
            guard += 1
            if guard > n * 2:
                # Shouldn't happen — force_remove_player/_eliminate_player
                # already end the game once only one non-finished player
                # remains — but bail out rather than spin forever if
                # state ever gets inconsistent.
                break

        player = self.current_player
        self.skipped_player = None
        # A fresh turn invalidates any leftover undo snapshot from the
        # previous action — undo only ever applies to the most recent
        # discretionary play/draw, not anything earlier.
        self._undo_snapshot = None
        difficulty_tag = "HUMAN" if player.is_human else player.difficulty.name
        game_log.info(f"--- Turn: {player.name} (human={player.is_human}, "
                      f"difficulty={difficulty_tag}) "
                      f"hand_count={player.hand.count} pickup_pending="
                      f"{self.rule_engine.pickup_pending} top={self.rule_engine._top_card} "
                      f"hand={player.hand.cards} ---")

        # KADI persistence fix: clear KADI declaration if player didn't win
        # (they can re-declare next time they're eligible)
        # Only clear if they still have cards AND haven't just declared this turn
        # This is reset via kadi_cancelled events when needed

        # Cardless player: normally auto-draw exactly 1 card on their
        # turn. But if there's an outstanding pickup debt, THIS player
        # owes it right now — they have no cards to counter with, so
        # it's their obligation, not a "maybe later" — route through
        # the same forced-pickup path _do_draw() already uses so the
        # FULL pending amount is paid immediately by them.
        #
        # Previously this branch ignored pickup_pending completely,
        # dealt them the generic 1 card, and let the turn move on with
        # the debt still sitting on the rule engine, unresolved and not
        # tied to any player. It would then get charged to whichever
        # OTHER player next happened to voluntarily draw — even one who
        # had already discharged their own turn earlier by countering.
        # (Field report: BMK went cardless owing a pick-10 pickup;
        # Player 2, who had already played their turn, was the one who
        # ended up drawing the 10 cards instead of BMK.)
        if player.hand.is_empty() and self.rule_engine.pickup_pending > 0:
            self._emit(GameEvent('turn_start', player=player))
            self._do_draw(player)
            return

        # Cardless player: auto-draw 1 card on their turn
        if player.hand.is_empty():
            drawn = self.deck.deal(1)
            if drawn:
                player.hand.add(drawn)
                self._emit(GameEvent('cardless_draw', player=player, card=drawn[0]))
                # Cardless auto-draw always resolves through POST_PLAY for a
                # human — whether or not the drawn card is a finishing card.
                # If it IS finishing, POST_PLAY lets them declare KADI (or
                # Proceed). If it's NOT finishing, they are definitely not
                # KADI this turn — POST_PLAY's existing "Proceed" button is
                # what advances to the next player, instead of silently
                # dropping them into a full normal turn that then demands a
                # second, manual draw before the turn can end.
                if player.is_human:
                    self._emit(GameEvent('turn_start', player=player))
                    self._open_post_play(player, {}, None)
                    return
            else:
                # Deck empty — stall
                self._resolve_stall()
                return

        self._emit(GameEvent('turn_start', player=player))

        if not player.is_human:
            player.start_thinking()
            self._ai_thinking = True
            self._turn_timer_active = False
        else:
            self._ai_thinking = False
            if self.timers_enabled:
                self.turn_timer = self.turn_timer_secs
                self._turn_timer_active = self.turn_timer > 0
            else:
                self._turn_timer_active = False

    def _advance_turn(self, skip: bool = False):
        n = len(self.players)
        step = self.direction.value
        self.current_player_idx = (self.current_player_idx + step) % n

        if skip and n > 2:
            skipped = self.players[self.current_player_idx]
            self.skipped_player = skipped
            self._emit(GameEvent('turn_skipped', player=skipped))
            self.current_player_idx = (self.current_player_idx + step) % n
        elif skip and n == 2:
            # In 2-player: J gives current player an extra turn — stay on same player
            # We already advanced above; reverse back to stay
            self.current_player_idx = (self.current_player_idx - step) % n

        self._start_turn()

    def _advance_turn_no_skip(self):
        """Advance without skip — used after 2-player J extra turn."""
        n = len(self.players)
        step = self.direction.value
        self.current_player_idx = (self.current_player_idx + step) % n
        self._start_turn()

    def _reverse_direction(self, count: int = 1):
        if count % 2 == 1:
            if self.direction == PlayDirection.CLOCKWISE:
                self.direction = PlayDirection.COUNTER_CLOCKWISE
            else:
                self.direction = PlayDirection.CLOCKWISE

    # ─── Human actions ────────────────────────────────────────────────────────

    def human_play(self, cards: List[Card], declare_kadi: bool = False,
                   declared_suit: Optional[Suit] = None) -> bool:
        """Called by UI when human plays cards. Returns True if accepted."""
        if self.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return False
        player = self.current_player
        if not player.is_human:
            return False
        self._turn_timer_active = False
        snapshot = self._pre_decision_snapshot(player)
        ok = self._do_play(player, cards, declare_kadi, declared_suit)
        if ok:
            self._log_human_choice(snapshot, cards)
        return ok

    def human_draw(self) -> Optional[Card]:
        """Called by UI when human draws a card."""
        if self.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return None
        player = self.current_player
        if not player.is_human:
            return None
        self._turn_timer_active = False
        snapshot = self._pre_decision_snapshot(player)
        result = self._do_draw(player)
        self._log_human_choice(snapshot, None)
        return result

    def _pre_decision_snapshot(self, player: Player) -> Optional[dict]:
        """Capture every legal option available to `player` RIGHT NOW,
        before their actual play/draw mutates anything — used to log
        their real decision against the full legal option set afterward,
        the same way an AI's decisions already are (see
        core/decision_logger). This is the piece that lets Chuo learn
        from HUMAN play, not just AI play, per the original MSOMI
        priority: "learn from humans first."

        Returns None (and skips the — nontrivial — enumeration work
        entirely) whenever decision logging is currently off, so this
        never costs anything when nobody's collecting training data."""
        if decision_logger.get_current_jsonl_path() is None:
            return None
        try:
            opponents = self._opponent_context(player)
            hand_before = list(player.hand.cards)
            options = enumerate_legal_plays(hand_before, self.rule_engine, opponents)
            # profile=None -> evaluate_play falls back to a neutral
            # default (MEDIUM's dials) for the score, since a human has
            # no AI difficulty profile of their own. Every named
            # feature besides the score is profile-independent anyway.
            evaluated = [evaluate_play(hand_before, seq, self.rule_engine,
                                       player.has_declared_kadi, opponents, profile=None)
                         for seq in options]
            evaluated.append(evaluate_draw(len(hand_before)))
            return {
                'player_name': player.name,
                'hand_before': hand_before,
                'evaluated': evaluated,
                'declared_kadi': player.has_declared_kadi,
                'pickup_pending': self.rule_engine.pickup_pending,
                'top_card': self.rule_engine._top_card,
            }
        except Exception:
            return None

    def _log_human_choice(self, snapshot: Optional[dict], chosen_cards: Optional[List[Card]]):
        """Match what was actually played/drawn against the pre-decision
        snapshot's evaluated option list (by card identity — see
        AIPlayer._remaining_after for why identity, not the Card
        equality override, is the correct match here) and log it. Silent
        no-op if snapshot capture failed/was skipped, or if the actual
        cards played can't be matched to any enumerated option (should
        only happen if something upstream is already broken — never
        worth guessing at partial/incorrect training data)."""
        if snapshot is None:
            return
        evaluated = snapshot['evaluated']
        chosen = None
        if chosen_cards is None:
            chosen = next((ev for ev in evaluated if ev['cards'] is None), None)
        else:
            chosen_ids = {id(c) for c in chosen_cards}
            for ev in evaluated:
                if ev['cards'] is not None and {id(c) for c in ev['cards']} == chosen_ids:
                    chosen = ev
                    break
        if chosen is None:
            return
        decision_logger.log_decision(
            is_human=True, player_name=snapshot['player_name'], difficulty='HUMAN',
            hand_before=snapshot['hand_before'], evaluated=evaluated, chosen=chosen,
            declared_kadi=snapshot['declared_kadi'], pickup_pending=snapshot['pickup_pending'],
            top_card=snapshot['top_card'])

    def human_declare_kadi(self) -> bool:
        """Human explicitly declares KADI before playing."""
        if self.state != GameState.PLAYING:
            return False
        player = self.current_player
        # For explicit declaration (no cards played yet), check full hand
        if not self.rule_engine.can_declare_kadi(player.hand):
            self._emit(GameEvent('invalid_kadi'))
            return False
        player.has_declared_kadi = True
        self.declared_kadi_player = player
        if player.is_human:
            self._g_kadi_declarations += 1
            self._player_tally(player.player_id)['kadi_declarations'] += 1
        self._emit(GameEvent('kadi_declared', player=player))
        return True

    def human_choose_suit(self, suit: Suit):
        """Called when human picks a suit after playing an A card."""
        if self.state != GameState.SUIT_PICK:
            return
        cards = self.pending_suit_cards or ([self.pending_suit_card] if self.pending_suit_card else [])
        self.pending_suit_change = False
        self.pending_suit_card = None
        self.pending_suit_cards = None
        self.state = GameState.PLAYING
        self._finish_play(self.current_player, cards, False, suit)

    def human_counter(self, cards: Union[Card, List[Card]]) -> bool:
        """Human plays one or more J's to counter a pending J (Jump) play.

        Only J cards may counter a J — this is the ONLY counter mechanic
        in the game. There is no such thing as countering a KADI finish;
        a KADI win can only be blocked by another player being cardless
        (handled in _finish_play).

        Accepts either a single Card (kept for backward compatibility)
        or a list of Cards — playing multiple J's in one counter stacks
        their skip effect exactly like leading with multiple J's does
        (see RuleEngine._process_single's skip_count accumulation), so
        countering with 2 J's jumps the field forward by 2 instead of 1."""
        if self.state != GameState.JUMP_COUNTER_WINDOW:
            return False
        cards = [cards] if isinstance(cards, Card) else list(cards)
        if not cards:
            return False
        cp = self.players[self.counter_player_idx]
        if any(c.card_type != CardType.JUMP for c in cards):
            return False
        hand_cards = list(cp.hand.cards)
        for c in cards:
            if c not in hand_cards:
                return False
            hand_cards.remove(c)  # guard against selecting the same physical card twice
        self._execute_jump_counter(cp, cards)
        return True

    def human_pass_counter(self):
        """Human declines to counter the pending J — they will be jumped."""
        if self.state != GameState.JUMP_COUNTER_WINDOW:
            return
        self._jump_counter_declined()

    def toggle_pause(self):
        """Pause or resume the game, freezing all timers."""
        if self.state == GameState.PAUSED:
            # Resume
            self.state = self._pre_pause_state or GameState.PLAYING
            self._pre_pause_state = None
            self._emit(GameEvent('game_resumed'))
        elif self.state in (GameState.PLAYING, GameState.KADI_DECLARED,
                            GameState.POST_PLAY, GameState.JUMP_COUNTER_WINDOW,
                            GameState.SUIT_PICK):
            self._pre_pause_state = self.state
            self.state = GameState.PAUSED
            self._emit(GameEvent('game_paused'))

    @property
    def is_paused(self) -> bool:
        return self.state == GameState.PAUSED

    # ─── Core play logic ──────────────────────────────────────────────────────

    def _do_play(self, player: Player, cards: List[Card],
                 declare_kadi: bool, declared_suit: Optional[Suit]) -> bool:
        # Validate
        if not cards:
            return False
        if not self.rule_engine.is_playable(cards[0]):
            self._emit(GameEvent('invalid_play', reason="Card not playable"))
            return False
        # Validate set: all same rank (except special sequences)
        if not self._valid_set(cards):
            self._emit(GameEvent('invalid_play', reason="Invalid card set"))
            return False

        # Traditional Jump-bundle rule (see RuleEngine.jump_bundle_legal /
        # Settings: jump_multi_card_enabled) — bundling a non-Jump extra
        # card behind a Jump chain is only legal with exactly enough
        # Jumps to route the turn back to this player first.
        if not self.rule_engine.jump_bundle_legal(cards, self._active_player_count()):
            self._emit(GameEvent('invalid_play',
                                 reason="Jump count doesn't meet the traditional rule "
                                        "for bundling another card with it"))
            return False

        # If a pick-up chain is currently active, the play MUST actually
        # resolve/extend it (end in a pick-up card, Joker, or shielding ACE).
        # A lone Question (8/Q) card is allowed to PRECEDE a counter inside
        # the same multi-card play, but cannot be played alone — otherwise
        # the pick-up debt silently stays active behind the scenes with no
        # visible indicator, confusing the player and later forcing a huge
        # forced draw. This was the root cause of the "unclear draw" bugs.
        pickup_was_pending = self.rule_engine.pickup_pending > 0
        if pickup_was_pending:
            last = cards[-1]
            resolves_pickup = (
                last.is_pickup
                or last.rank == 'JOKER'
                or (last.card_type == CardType.SUIT_CHANGE
                    and self.rule_engine.ace_shields_pickup(cards))
            )
            if not resolves_pickup:
                game_log.info(f"Rejected play {cards} — does not resolve pending "
                               f"pickup of {self.rule_engine.pickup_pending}")
                self._emit(GameEvent('invalid_play',
                                     reason="Must play a pick-up card, Joker, "
                                            "or ACE to counter the pending pick-up"))
                return False

        # KADI finishing play — if declared, check if valid finish. A
        # pending pick-up overrides this too (same as it overrides
        # everything else): the check above already guarantees `cards`
        # legally resolves it, and a resolving play's last card (pick-up/
        # Joker/ACE-shield) can never simultaneously be a finishing card,
        # so demanding is_valid_kadi_finish here as well would make it
        # IMPOSSIBLE for a declared player to ever survive an incoming
        # pick-up — every resolving play would get rejected for not
        # finishing, and every finishing play would already have been
        # rejected above for not resolving. has_declared_kadi is left
        # True; they're still on the hook to actually finish once no
        # pick-up is standing in the way.
        if player.has_declared_kadi and not pickup_was_pending:
            if not self.rule_engine.is_valid_kadi_finish(cards):
                # Check if player has ANY playable finishing card
                finishing_playable = [
                    c for c in player.hand.get_playable(self.rule_engine)
                    if c.is_finishing
                ]
                if not finishing_playable:
                    # No finishing cards playable — auto-cancel KADI, allow normal play
                    player.has_declared_kadi = False
                    self.declared_kadi_player = None
                    game_log.info(f"{player.name} KADI cancelled — no finishing card "
                                  f"available (hand={player.hand.cards})")
                    self._emit(GameEvent('kadi_cancelled', player=player,
                                         reason="No finishing card available"))
                    # Re-validate as normal play
                    if not self.rule_engine.is_playable(cards[0]):
                        self._emit(GameEvent('invalid_play', reason="Card not playable"))
                        return False
                else:
                    game_log.info(f"{player.name} rejected — after KADI must play a "
                                  f"finishing card, tried {cards} (hand={player.hand.cards})")
                    self._emit(GameEvent('invalid_play',
                                         reason="After KADI you must play a finishing card"))
                    return False

        # Handle KADI declaration — check on hand AFTER removing played cards
        if declare_kadi:
            played_ids = {id(c) for c in cards}
            remaining_cards = [c for c in player.hand.cards if id(c) not in played_ids]
            from models.player import Hand
            remaining_hand = Hand()
            remaining_hand.add(remaining_cards)
            if not remaining_hand.can_declare_kadi(self.rule_engine):
                game_log.info(f"{player.name} KADI declaration rejected — remaining "
                              f"hand {remaining_cards} not closeable (played {cards})")
                self._emit(GameEvent('invalid_kadi'))
                return False
            player.has_declared_kadi = True
            self.declared_kadi_player = player
            game_log.info(f"{player.name} declared KADI — played {cards}, "
                          f"remaining hand={remaining_cards}")
            self._emit(GameEvent('kadi_declared', player=player))

        # Check if suit change is needed:
        # Only when an A card was played and it's NOT shielding a pickup
        # We detect shield by checking if pickup was pending BEFORE this play
        pickup_was_pending = self.rule_engine.pickup_pending > 0
        has_suit_change = any(c.card_type == CardType.SUIT_CHANGE for c in cards)
        needs_suit_pick = (has_suit_change
                           and not pickup_was_pending
                           and not player.has_declared_kadi
                           and declared_suit is None)

        if needs_suit_pick:
            # Pause for suit selection — do NOT remove cards yet
            self.pending_suit_change = True
            self.pending_suit_cards = list(cards)
            self.pending_suit_card = next(c for c in cards if c.card_type == CardType.SUIT_CHANGE)
            self.last_played_cards = cards
            self.state = GameState.SUIT_PICK
            self._emit(GameEvent('suit_pick_required', player=player, cards=cards))
            return True

        return self._finish_play(player, cards, declare_kadi, declared_suit)

    def _active_player_count(self) -> int:
        """How many players are still actually in the round — everyone,
        outside Elimination Mode (nobody finishes early there; the first
        win ends the whole game), or just the not-yet-finished players
        when Elimination Mode is on. Used by the traditional Jump-bundle
        rule (RuleEngine.jump_bundle_legal), which gets easier to
        satisfy as Elimination Mode thins the table down over a game."""
        if not self.elimination_mode:
            return len(self.players)
        return sum(1 for p in self.players if not p.finished)

    def _valid_set(self, cards: List[Card]) -> bool:
        """Delegate to RuleEngine. Returns False for invalid sets.
        QUESTION_NO_ANSWER is handled separately in _finish_play."""
        ok, reason = self.rule_engine.is_valid_sequence(cards)
        if not ok and reason != "QUESTION_NO_ANSWER":
            self._emit(GameEvent('invalid_play', reason=reason))
            return False
        return True  # QUESTION_NO_ANSWER treated as valid play (penalty applied later)

    def _finish_play(self, player: Player, cards: List[Card],
                     declare_kadi: bool, declared_suit: Optional[Suit]):
        # Snapshot state BEFORE any mutation so a human player can undo
        # this exact play later, during its POST_PLAY (KADI check) window.
        if player.is_human:
            self._capture_undo_snapshot(player)

        # Check for Q-without-answer:
        # Single Q card OR multi-Q cards with no answer = draw 1 penalty
        has_only_questions = (
            len(cards) >= 1
            and all(c.card_type == CardType.QUESTION for c in cards)
        )
        if has_only_questions:
            q_no_answer = True
        else:
            _, reason = self.rule_engine.is_valid_sequence(cards)
            q_no_answer = (reason == "QUESTION_NO_ANSWER")

        player.hand.remove(cards)

        # Snapshot what a Jump-led combo bundling a non-Jump "extra" card
        # would need to be rolled back to if that Jump gets successfully
        # countered — see _jump_bundle's definition in __init__ and
        # _execute_jump_counter for the rollback itself.
        j_count = 0
        for c in cards:
            if c.card_type == CardType.JUMP:
                j_count += 1
            else:
                break
        pre_state = {
            'top_card': self.rule_engine._top_card,
            'current_suit': self.rule_engine.current_suit,
            'pickup_pending': self.rule_engine.pickup_pending,
            'pickup_suit': self.rule_engine.pickup_suit,
            'pickup_rank': self.rule_engine.pickup_rank,
        }

        result = self.rule_engine.process_play(cards, declared_suit)

        # Profile Part 5 per-game tallies (human-attributed only — see
        # _reset_game_trackers). Kept right here, in the one place every
        # successful play (leading or answering) funnels through, rather
        # than scattered across each specific play path.
        if player.is_human:
            pt = self._player_tally(player.player_id)
            self._g_cards_played += len(cards)
            pt['cards_played'] += len(cards)
            for c in cards:
                if c.card_type == CardType.SUIT_CHANGE:
                    self._g_aces_played += 1
                    pt['aces_played'] += 1
                elif c.card_type == CardType.JUMP:
                    self._g_jump_skips_dealt += 1
                    pt['jump_skips_dealt'] += 1
                elif c.card_type == CardType.KICKBACK:
                    self._g_kickback_reversals += 1
                    pt['kickback_reversals'] += 1
            if result.get('shielded'):
                blocked = pre_state['pickup_pending']
                self._g_ace_shield_uses += 1
                self._g_ace_shield_biggest = max(self._g_ace_shield_biggest, blocked)
                pt['ace_shield_uses'] += 1
                pt['ace_shield_biggest'] = max(pt['ace_shield_biggest'], blocked)
            if declare_kadi:
                self._g_kadi_declarations += 1
                pt['kadi_declarations'] += 1
                # "The Trap" (Kuficha Joker): playing a held pickup card
                # AND declaring KADI in the same move.
                if any(c.card_type in (CardType.PICKUP_2, CardType.PICKUP_3, CardType.JOKER)
                       for c in cards):
                    self._g_kuficha_trap_attempted = True
                    pt['kuficha_trap_attempted'] = True
                # "Poker Face": a lone ACE finishing move (leaves exactly
                # one card behind) where the requested suit ISN'T that
                # remaining card's own suit — a genuine decoy request,
                # not the honest/obvious one.
                if (len(cards) == 1 and cards[0].card_type == CardType.SUIT_CHANGE
                        and len(player.hand.cards) == 1
                        and declared_suit is not None
                        and player.hand.cards[0].suit is not None
                        and declared_suit != player.hand.cards[0].suit):
                    self._g_bluff_attempted = True
                    pt['bluff_attempted'] = True
            if len(player.hand.cards) == 1:
                self._g_near_kadi_count += 1
                pt['near_kadi_count'] += 1

        if result['skip'] and 0 < j_count < len(cards):
            self._jump_bundle = {
                'owner': player,
                'extra_cards': list(cards[j_count:]),
                'last_leader': cards[j_count - 1],
                'pre_state': pre_state,
            }
        else:
            self._jump_bundle = None

        self.deck.discard_many(cards)
        self.last_played_cards = cards
        # Public play-history tracking (used only for AI suit-blocking
        # heuristics — see _opponent_context). Every one of these cards
        # is now face-up on the discard pile, so this is purely public
        # information, same as what a sharp human opponent would notice.
        hist = self.suit_history.setdefault(player.player_id, Counter())
        for c in cards:
            if c.suit:
                hist[c.suit] += 1
        # IMPORTANT: reflect the rule engine's *actual current* pending
        # pickup total here, not result['pickup_total'] (which is only the
        # amount contributed by *this* play and would wrongly reset the
        # on-screen "Pick up: +N" indicator to 0 even when a pick-up debt
        # is still silently active, e.g. after answering with a Question
        # card). This was the root cause of "unclear draw" confusion.
        self.pickup_pending_display = self.rule_engine.pickup_pending
        game_log.debug(f"{player.name} played {cards} -> pickup_pending_display="
                        f"{self.pickup_pending_display}")

        # Q without answer: player draws exactly 1 card (never more, regardless of Q count)
        if q_no_answer:
            penalty = self.deck.deal(1)
            if penalty:
                player.hand.add(penalty)
                if player.has_declared_kadi:
                    player.has_declared_kadi = False
                    self.declared_kadi_player = None
                    self._emit(GameEvent('kadi_cancelled', player=player,
                                         reason="Question unanswered"))
            self._emit(GameEvent('question_no_answer', player=player, cards=cards))

        # Build effect text
        texts = []
        if result.get('k_return'):
            texts.append("Returns to you!")
        elif result['reverse']:
            texts.append("Direction reversed!")
        if result['skip']:
            count = result.get('skip_count', 1)
            texts.append(f"{count} player(s) skipped!")
        if result['pickup_total'] > 0:
            # Name the next player who must pick. Must skip already-finished
            # players (Elimination Mode) the same way turn advancement and
            # the jump-counter window do — see _next_active_idx — otherwise
            # this banner can name a player who already won and left.
            step = self.direction.value
            next_idx = self._next_active_idx(self.current_player_idx, step)
            next_player = self.players[next_idx]
            texts.append(f"{next_player.name} picks {result['pickup_total']}!")
        if result['suit_changed']:
            # ASCII-only — U+2192 (→) isn't in any of this project's
            # bundled fonts (Poppins/Cinzel), same reason SUIT_ICON/
            # SUIT_LETTER exist for suit glyphs. Using it here rendered
            # as a tofu box between "Suit" and the suit name.
            texts.append(f"Suit: {declared_suit.value if declared_suit else '?'}!")
        if result['shielded']:
            texts.append("Pick-up blocked!")
        if q_no_answer:
            texts.append("Q unanswered — draw 1!")
        self.last_effect_text = " ".join(texts)

        self._emit(GameEvent('cards_played', player=player, cards=cards,
                             result=result, effect_text=self.last_effect_text))
        self._consecutive_draws = 0

        # Check win
        if player.hand.is_empty():
            if player.has_declared_kadi and cards[-1].is_finishing:
                # Check if any other still-active player is cardless —
                # only valid blocker. Players who already finished earlier
                # in Elimination Mode are cardless by definition (they're
                # done and out), so they don't count as blockers here —
                # otherwise no one could ever win a second round.
                cardless_others = [p for p in self.players
                                   if p != player and p.hand.is_empty()
                                   and not p.finished]
                if cardless_others:
                    # Cannot win while another player is cardless
                    self._emit(GameEvent('kadi_blocked_by_cardless',
                                         player=player,
                                         blocked_by=cardless_others))
                    # Fall through — game continues
                elif self.elimination_mode:
                    self._eliminate_player(player, result)
                    return True
                else:
                    # Legitimate KADI win — no counter finish mechanic
                    self._declare_winner(player)
                    return True
            # Went cardless without KADI — game continues, draw 1 next turn
            player.has_declared_kadi = False
            if self.declared_kadi_player == player:
                self.declared_kadi_player = None
            self._emit(GameEvent('player_cardless', player=player))

        # POST_PLAY delay for ALL human plays — always show proceed + KADI check
        if player.is_human:
            self._open_post_play(player, result, declared_suit)
            return True

        self._do_advance_after_play(player, result)
        return True

    def _open_post_play(self, player: Player, result: dict,
                        declared_suit: Optional[Suit]):
        """Open the post-play delay window for human players — always."""
        self.state = GameState.POST_PLAY
        delay = self.post_play_delay_secs if self.timers_enabled else 5.0
        self.post_play_timer   = max(delay, 1.0)   # minimum 1s always
        self._post_play_result = result
        self._post_play_player = player
        # KADI eligible: same grammar-aware check as everywhere else in
        # the game — see RuleEngine.can_close_hand_with. Recognizes a
        # same-rank finishing set, OR a Question/Kickback(even)/Jump
        # chain answered by a same-rank finishing set, OR a lone ACE
        # answered by any finishing cards — not just the old "every
        # remaining card must already be finishing" check, which wrongly
        # rejected legitimate declarations whenever a Question, Kickback,
        # or Jump card remained in hand as part of a valid future
        # closing combo (e.g. hand = [Q, Q, 6, 6] after this play).
        self._post_play_can_kadi = (
            not player.hand.is_empty()
            and player.hand.can_declare_kadi(self.rule_engine)
            and not player.has_declared_kadi
        )
        self._turn_timer_active = False
        self._emit(GameEvent('post_play_open', player=player,
                             can_kadi=self._post_play_can_kadi,
                             timer=self.post_play_timer))

    def human_post_play_proceed(self):
        """Human clicks Proceed — skip remaining post-play delay."""
        if self.state != GameState.POST_PLAY:
            return
        self._close_post_play(declare_kadi=False)

    def human_post_play_declare_kadi(self):
        """Human declares KADI during post-play window."""
        if self.state != GameState.POST_PLAY:
            return False
        if not self._post_play_can_kadi:
            # Previously this just silently returned False, leaving the
            # button looking clickable but doing nothing — confusing.
            # Now: tell the player clearly it's not a valid KADI moment,
            # and treat the click as "Proceed" so the game keeps moving.
            game_log.info(f"{self._post_play_player.name if self._post_play_player else '?'} "
                          f"clicked Yes!KADI while not eligible")
            self._emit(GameEvent('invalid_kadi', reason="Not KADI — hand isn't all finishing cards"))
            self._close_post_play(declare_kadi=False)
            return False
        player = self._post_play_player
        player.has_declared_kadi = True
        self.declared_kadi_player = player
        if player.is_human:
            self._g_kadi_declarations += 1
            self._player_tally(player.player_id)['kadi_declarations'] += 1
        self._emit(GameEvent('kadi_declared', player=player))
        self._close_post_play(declare_kadi=True)
        return True

    @property
    def undo_available(self) -> bool:
        """True while the most recent play/voluntary-draw can still be
        undone (POST_PLAY window open and a snapshot was captured for it).
        Forced pickup draws and AI/cardless auto-draws are never undoable."""
        return self.state == GameState.POST_PLAY and self._undo_snapshot is not None

    def _capture_undo_snapshot(self, player: Player):
        """Snapshot all mutable state right before a discretionary play or
        voluntary draw, so it can be reverted via human_undo_last_action()
        while the POST_PLAY (KADI check) window for this action is open."""
        self._undo_snapshot = {
            'player': player,
            'hand_cards': list(player.hand.cards),
            'draw_pile': list(self.deck._draw_pile),
            'discard_pile': list(self.deck._discard_pile),
            'rule_current_suit': self.rule_engine.current_suit,
            'rule_pickup_pending': self.rule_engine.pickup_pending,
            'rule_pickup_rank': self.rule_engine.pickup_rank,
            'rule_pickup_suit': self.rule_engine.pickup_suit,
            'rule_top_card': self.rule_engine._top_card,
            'rule_skip_count': self.rule_engine.skip_count,
            'rule_joker_on_top': self.rule_engine.joker_on_top,
            'pickup_pending_display': self.pickup_pending_display,
            'last_played_cards': list(self.last_played_cards),
            'last_effect_text': self.last_effect_text,
            'player_has_declared_kadi': player.has_declared_kadi,
            'declared_kadi_player': self.declared_kadi_player,
            'consecutive_draws': self._consecutive_draws,
            # Where the action started — usually PLAYING, but a jump
            # counter (playing a J to counter a pending J) starts from
            # JUMP_COUNTER_WINDOW, and undoing it needs to put the player
            # back into that window (still facing the same pending jump),
            # not into a normal PLAYING turn.
            'origin_state': self.state,
            'counter_player_idx': self.counter_player_idx,
            'jump_player': self.jump_player,
            'jump_skip_remaining': self.jump_skip_remaining,
            'counter_timer': self.counter_timer,
            'suit_history': {pid: Counter(c) for pid, c in self.suit_history.items()},
            'jump_bundle': self._jump_bundle,
        }

    @property
    def undo_tokens_available(self) -> bool:
        """Whether the profile (if any) currently has an undo token to
        spend. True when there's no profile wired up at all (e.g. bare
        GameManager in a test/tool context) so token-gating only ever
        applies when a real profile is attached — see undo_available's
        docstring update below for how this combines with the existing
        POST_PLAY-window check."""
        if self.profile is None:
            return True
        return self.profile.get('undo_tokens', 0) > 0

    def human_undo_last_action(self) -> bool:
        """Undo the most recent play or voluntary draw while its POST_PLAY
        (KADI check) window is still open, restoring the hand/deck/rule
        state to exactly how it was beforehand so the player can choose a
        different move. Only one action — the current one — can ever be
        undone; there's no multi-step undo history.

        Also spends one undo token from the attached profile (Part 3),
        if one is attached — see undo_tokens_available. The UI is
        expected to grey out the undo button at 0 tokens (see
        scenes.py), but this is checked here too so a stray call can
        never bypass the limit."""
        if not self.undo_available:
            return False
        if not self.undo_tokens_available:
            return False
        if self.profile is not None:
            self.profile['undo_tokens'] = max(0, self.profile.get('undo_tokens', 0) - 1)
            from core.profile_store import save_profile
            save_profile(self.profile)
        self._g_undo_used = True
        snap = self._undo_snapshot
        player = snap['player']
        if player.is_human:
            self._player_tally(player.player_id)['undo_used'] = True

        player.hand._cards = list(snap['hand_cards'])
        self.deck._draw_pile = list(snap['draw_pile'])
        self.deck._discard_pile = list(snap['discard_pile'])
        self.rule_engine.current_suit = snap['rule_current_suit']
        self.rule_engine.pickup_pending = snap['rule_pickup_pending']
        self.rule_engine.pickup_rank = snap['rule_pickup_rank']
        self.rule_engine.pickup_suit = snap['rule_pickup_suit']
        self.rule_engine._top_card = snap['rule_top_card']
        self.rule_engine.skip_count = snap['rule_skip_count']
        self.rule_engine.joker_on_top = snap['rule_joker_on_top']
        self.pickup_pending_display = snap['pickup_pending_display']
        self.last_played_cards = list(snap['last_played_cards'])
        self.last_effect_text = snap['last_effect_text']
        player.has_declared_kadi = snap['player_has_declared_kadi']
        self.declared_kadi_player = snap['declared_kadi_player']
        self._consecutive_draws = snap['consecutive_draws']
        self.suit_history = {pid: Counter(c) for pid, c in snap['suit_history'].items()}
        self._jump_bundle = snap['jump_bundle']

        # Close the post-play window WITHOUT advancing the turn — the same
        # player gets to act again, exactly as if their turn just started.
        # If the undone action was countering a pending jump, put them
        # back into that same JUMP_COUNTER_WINDOW instead — they still
        # face the original jump and can choose again (counter with a
        # different J, or pass).
        origin_state = snap['origin_state']
        self._post_play_result = None
        self._post_play_player = None
        self._post_play_can_kadi = False
        self._undo_snapshot = None
        if origin_state == GameState.JUMP_COUNTER_WINDOW:
            self.state = GameState.JUMP_COUNTER_WINDOW
            self.counter_player_idx = snap['counter_player_idx']
            self.jump_player = snap['jump_player']
            self.jump_skip_remaining = snap['jump_skip_remaining']
            self.counter_timer = snap['counter_timer']
            cp = self.players[self.counter_player_idx]
            if not cp.is_human and isinstance(cp, AIPlayer):
                cp.start_thinking()
            game_log.info(f"{player.name} undid their jump counter")
            self._emit(GameEvent('move_undone', player=player))
            return True

        self.state = GameState.PLAYING
        if self.timers_enabled:
            self.turn_timer = self.turn_timer_secs
            self._turn_timer_active = self.turn_timer > 0
        else:
            self._turn_timer_active = False

        game_log.info(f"{player.name} undid their last action")
        self._emit(GameEvent('move_undone', player=player))
        return True

    def _reset_game_trackers(self):
        """Per-game tallies feeding the Profile Part 5 numeric/mechanic
        badge ladders (see core.profile_store.check_badges_after_game).
        Reset at the start of every game (both __init__, as a safe
        default matching the fix in _stats_recorded_for_game_id, and
        new_game()) and folded into the persistent profile['counters']
        exactly once, in finalize_profile_stats() at game end. Only
        human-attributed actions are counted — see the is_human guards
        at each increment site — matching how mode/difficulty stats are
        already only ever credited to "my_player".

        self._g_by_player (added alongside the pre-existing aggregate
        self._g_* scalars above, which are UNCHANGED and still what
        finalize_profile_stats()/the PC single-profile-per-device path
        reads) is a per-player_id breakdown of the same tallies. It
        exists because these scalars sum EVERY is_human player's
        actions together — correct for the PC's single-human-per-
        device assumption (finalize_profile_stats's own docstring: for
        hot-seat, crediting every local human's result to one shared
        profile.json is deliberate), but wrong for the internet
        server, where GameManager is authoritative for MULTIPLE human
        players each on their own device with their own separate
        profile (see server/game_room.py) — summing would attribute
        one player's cards/aces/etc. to every other human player's own
        profile. See network/game_summary.py, the one consumer of
        this per-player breakdown."""
        self._g_cards_played = 0
        self._g_cards_drawn = 0
        self._g_biggest_pickup_absorbed = 0
        self._g_kadi_declarations = 0
        self._g_aces_played = 0
        self._g_jump_skips_dealt = 0
        self._g_kickback_reversals = 0
        self._g_ace_shield_uses = 0
        self._g_ace_shield_biggest = 0
        self._g_undo_used = False
        self._g_near_kadi_count = 0
        self._g_jump_chain_depth = 0       # current chain, resets each fresh Jump
        self._g_jump_chain_depth_max = 0
        self._g_bluff_attempted = False    # see "Poker Face" detection in _finish_play
        self._g_kuficha_trap_attempted = False  # see "The Trap" detection in _finish_play
        self._g_by_player: dict = {}

    def _player_tally(self, player_id: int) -> dict:
        """Per-player_id counterpart to the aggregate self._g_* scalars
        (see _reset_game_trackers's docstring) — created lazily on
        first touch so a player who genuinely never took an action
        that increments any of these (shouldn't happen in a finished
        game, but not assumed) simply reads back all-zero/False
        defaults rather than a KeyError."""
        t = self._g_by_player.get(player_id)
        if t is None:
            t = {
                'cards_played': 0, 'cards_drawn': 0, 'biggest_pickup_absorbed': 0,
                'kadi_declarations': 0, 'aces_played': 0, 'jump_skips_dealt': 0,
                'kickback_reversals': 0, 'ace_shield_uses': 0, 'ace_shield_biggest': 0,
                'near_kadi_count': 0, 'undo_used': False,
                'bluff_attempted': False, 'kuficha_trap_attempted': False,
            }
            self._g_by_player[player_id] = t
        return t

    def finalize_profile_stats(self, *, mode: str, difficulty: Optional[str] = None,
                                my_player: Optional[Player] = None) -> List[str]:
        """Update self.profile's stats/badges for the game that just
        ended (self.state == GameState.GAME_OVER) and persist it.
        Returns the list of newly-earned badge ids for the UI to show
        notifications for (also stashed on self.pending_badge_notifications).

        `mode` is one of 'single_player', 'single_player_elimination',
        'lan', 'internet', 'hot_seat' — the caller (scenes.py) is what
        actually knows which of those this match was, since that's
        UI/menu-flow context GameManager itself doesn't track. `my_player`
        is whichever Player represents "you" on this device; for
        hot-seat with multiple humans sharing one profile, this is
        deliberately just the first human seat (see scenes.py's existing
        my_seat convention for the win screen) — crediting every local
        human's individual result to one shared profile.json isn't
        well-defined otherwise, and splitting into per-name sub-profiles
        is future work, not something to guess at here.

        Guarded by game_id so calling this more than once for the same
        game (e.g. a stray duplicate event) never double-counts — only
        the first call per game_id actually mutates anything."""
        if self.profile is None:
            return []
        if self._stats_recorded_for_game_id == self.game_id:
            return []
        self._stats_recorded_for_game_id = self.game_id

        from core import profile_store
        profile = self.profile
        won = bool(my_player is not None and self.winner is my_player)

        gp, gw = profile['games_played'], profile['games_won']
        if mode in ('single_player', 'single_player_elimination'):
            diff_key = difficulty or 'MEDIUM'
            gp[mode][diff_key] = gp[mode].get(diff_key, 0) + 1
            if won:
                gw[mode][diff_key] = gw[mode].get(diff_key, 0) + 1
        elif mode in ('lan', 'internet', 'hot_seat'):
            gp[mode] += 1
            if won:
                gw[mode] += 1

        finish_kind = None
        if won and self.last_played_cards:
            finish_kind = classify_finish_kind(self.last_played_cards)
            if finish_kind:
                profile['multi_card_finishes'][finish_kind] += 1

        opponent_had_msomi = any(
            getattr(p, 'msomi_model', None) is not None for p in self.players
        )
        if opponent_had_msomi:
            profile['msomi']['games_played_with_msomi'] += 1
            if won:
                profile['msomi']['games_won_with_msomi'] += 1

        profile['total_time_played_secs'] = (
            profile.get('total_time_played_secs', 0.0) + getattr(self, '_session_elapsed', 0.0))

        newly = profile_store.check_badges_after_game(
            profile, won=won, mode=mode, difficulty=difficulty,
            finish_kind=finish_kind, opponent_had_msomi=(won and opponent_had_msomi),
            cards_played=self._g_cards_played,
            cards_drawn=self._g_cards_drawn,
            biggest_pickup_absorbed=self._g_biggest_pickup_absorbed,
            kadi_declarations=self._g_kadi_declarations,
            aces_played=self._g_aces_played,
            jump_skips_dealt=self._g_jump_skips_dealt,
            kickback_reversals=self._g_kickback_reversals,
            ace_shield_uses=self._g_ace_shield_uses,
            ace_shield_biggest=self._g_ace_shield_biggest,
            jump_counter_depth=self._g_jump_chain_depth_max,
            near_kadi_count=self._g_near_kadi_count,
            undo_used_this_game=self._g_undo_used,
            bluff_suit_win=(won and self._g_bluff_attempted),
            kuficha_trap_win=(won and self._g_kuficha_trap_attempted),
            elimination_mode=(mode == 'single_player_elimination'))

        profile_store.save_profile(profile)
        self.pending_badge_notifications = list(newly)
        return newly

    def _close_post_play(self, declare_kadi: bool):
        self.state  = GameState.PLAYING
        result      = self._post_play_result or {}
        player      = self._post_play_player
        self._post_play_result  = None
        self._post_play_player  = None
        self._post_play_can_kadi = False
        self._undo_snapshot = None
        self._do_advance_after_play(player, result)

    # Keep old KADI window methods for backward compat (now delegates to POST_PLAY)
    def human_declare_kadi_window(self):
        return self.human_post_play_declare_kadi()

    def human_skip_kadi_window(self):
        self.human_post_play_proceed()

    def _open_kadi_window(self, player, result, declared_suit):
        self._open_post_play(player, result, declared_suit)

    def _close_kadi_window(self, declared):
        self._close_post_play(declare_kadi=declared)

    def _do_advance_after_play(self, player: Player, result: dict):
        """Common turn-advance: handle reverse, K-return, J-skips, normal advance."""
        n = len(self.players)
        step = self.direction.value

        # K stack: even count → same player plays again; odd → reverse direction
        if result.get('k_return'):
            # Even Ks: return to the player who played them
            self._start_turn()
            return

        if result.get('reverse'):
            self._reverse_direction(result.get('reverse_count', 1))

        skip_count = result.get('skip_count', 0) if result.get('skip') else 0

        if skip_count > 0:
            self._start_jump_counter(player, skip_count)
            return

        self._extra_turn_remaining = 0
        self._advance_turn(skip=False)

    def _do_draw(self, player: Player) -> Optional[Card]:
        # Pending pickup — forced draw, voids KADI
        if self.rule_engine.pickup_pending > 0:
            # A forced pickup draw is a mandatory penalty, not a
            # discretionary move — it's not something to undo, so make
            # sure any leftover snapshot from earlier this turn is cleared.
            self._undo_snapshot = None
            count = self.rule_engine.resolve_pickup()
            cards = self.deck.deal(count)
            player.hand.add(cards)
            if player.is_human:
                self._g_cards_drawn += count
                self._g_biggest_pickup_absorbed = max(self._g_biggest_pickup_absorbed, count)
                pt = self._player_tally(player.player_id)
                pt['cards_drawn'] += count
                pt['biggest_pickup_absorbed'] = max(pt['biggest_pickup_absorbed'], count)
            game_log.info(f"{player.name} forced to draw {count} cards (pickup): {cards}")
            if player.has_declared_kadi:
                player.has_declared_kadi = False
                self.declared_kadi_player = None
                self._emit(GameEvent('kadi_cancelled', player=player,
                                     reason="Forced to pick up cards"))
            self.pickup_pending_display = 0
            self._emit(GameEvent('pickup_drawn', player=player, cards=cards, count=count))
            # Open POST_PLAY for human after forced draw too
            if player.is_human:
                self._open_post_play(player, {}, None)
                return cards[-1] if cards else None
            self._advance_turn()
            return cards[-1] if cards else None

        # Snapshot state BEFORE this voluntary draw so a human player can
        # undo it later, during its POST_PLAY (KADI check) window.
        if player.is_human:
            self._capture_undo_snapshot(player)

        # Safety: trim massive hands
        MAX_HAND = 30
        if player.hand.count >= MAX_HAND:
            discard_cards = [c for c in player.hand.cards if not c.is_finishing]
            discard_cards = discard_cards[len(discard_cards)//2:]
            if discard_cards:
                player.hand.remove(discard_cards)
                self.deck.discard_many(discard_cards)

        # Normal draw — cancels KADI declaration
        card = self.deck.draw_one()
        if card:
            player.hand.add([card])
            if player.is_human:
                self._g_cards_drawn += 1
                self._player_tally(player.player_id)['cards_drawn'] += 1
            # This used to be the ONE turn-action with no game_log line at
            # all — a forced pickup draw logs, an AI's decision logs, but a
            # plain voluntary draw (by a human OR an AI) left nothing in
            # the log between one "--- Turn: ... ---" line and the next,
            # which reads exactly like the player was skipped even though
            # they weren't. Log it like every other action.
            game_log.info(f"{player.name} drew a card: {card}")
            if player.has_declared_kadi:
                player.has_declared_kadi = False
                self.declared_kadi_player = None
                self._emit(GameEvent('kadi_cancelled', player=player,
                                     reason="Voluntarily drew a card"))
            self._emit(GameEvent('card_drawn', player=player, card=card))
        else:
            game_log.info(f"{player.name} tried to draw but the deck was empty")

        self._consecutive_draws += 1
        if self._consecutive_draws >= self._max_consecutive_draws:
            self._resolve_stall()
            return card

        # Open POST_PLAY for human after voluntary draw too
        if player.is_human:
            self._open_post_play(player, {}, None)
            return card

        self._advance_turn()
        return card

    def _resolve_stall(self):
        """Force-resolve a stalled game (draw pile exhausted) — rank
        currently-active players by finishing cards in hand. In standard
        mode the best of those wins outright, same as before. In
        Elimination Mode this ends the whole round immediately using
        that ranking rather than trying to keep playing with an empty
        deck — already-finished players keep their earlier placements,
        and everyone still active gets ranked in behind them."""
        self._consecutive_draws = 0
        active = [p for p in self.players if not p.finished]
        if not active:
            return  # everyone already finished somehow — nothing to do
        ranked = sorted(active,
                        key=lambda p: sum(1 for c in p.hand.cards if c.is_finishing),
                        reverse=True)
        best = ranked[0]
        self._emit(GameEvent('stall_resolved', player=best))

        if self.elimination_mode:
            for p in ranked:
                p.finished = True
                p.finish_place = len(self.finish_order) + 1
                self.finish_order.append(p)
            self.winner = self.finish_order[0]
            self.winner.score += 1
            self.state = GameState.GAME_OVER
            self._emit(GameEvent('game_over', winner=self.winner,
                                 finish_order=list(self.finish_order)))
            return

        self._declare_winner(best)

    # ─── J-counters-J ───────────────────────────────────────────────────────
    # The ONLY counter mechanic in the game: a pending J (Jump) play can be
    # countered by the player about to be jumped if they play a J of their
    # own, within counter_window_secs. A KADI finish can NEVER be countered —
    # the only thing that stops a declared KADI from winning is another
    # player being cardless at the moment the KADI play resolves (see
    # _finish_play's cardless_others check above).

    def _next_active_idx(self, from_idx: int, step: int) -> int:
        """Next seat index stepping from from_idx, skipping any player
        already finished (Elimination Mode). By the time a jump-counter
        window opens there are always at least 2 active players (the
        game ends the instant only one remains — see _eliminate_player),
        so this always finds a valid target; the guard is just a safety
        net against ever spinning forever if state gets inconsistent."""
        n = len(self.players)
        idx = (from_idx + step) % n
        guard = 0
        while self.players[idx].finished:
            idx = (idx + step) % n
            guard += 1
            if guard > n * 2:
                break
        return idx

    def _start_jump_counter(self, jumper: Player, skip_count: int):
        # A fresh Jump play (not itself a counter) starts a brand new
        # chain — see _execute_jump_counter for where depth increments.
        self._g_jump_chain_depth = 1
        self._g_jump_chain_depth_max = max(self._g_jump_chain_depth_max, 1)
        self.state = GameState.JUMP_COUNTER_WINDOW
        self.counter_timer = 0.0
        self.jump_player = jumper
        self.jump_skip_remaining = skip_count
        step = self.direction.value
        self.counter_player_idx = self._next_active_idx(jumper.player_id, step)
        cp = self.players[self.counter_player_idx]
        if not cp.is_human and isinstance(cp, AIPlayer):
            # Without this, cp._think_timer is whatever it was left at from
            # cp's last normal turn (usually already >= _think_duration),
            # so update_thinking() would return True on the very next
            # frame — the AI "decides" instantly with no visible delay,
            # making the counter window invisible even though it fired.
            cp.start_thinking()
        self._emit(GameEvent('jump_counter_open', jumper=jumper,
                             counter_player=cp))


    def update_counter_window(self, dt: float):
        """Called each frame during the J-counter window."""
        if self.state != GameState.JUMP_COUNTER_WINDOW:
            return
        self.counter_timer += dt
        limit = self.counter_window_secs if self.timers_enabled else 5.0
        if self.counter_timer >= limit:
            self._jump_counter_declined()

    def _jump_counter_declined(self):
        """The player at counter_player_idx failed (or chose not) to counter
        the pending J in time — they are jumped."""
        cp = self.players[self.counter_player_idx]
        self.skipped_player = cp
        self._emit(GameEvent('turn_skipped', player=cp))
        n = len(self.players)
        step = self.direction.value

        if n == 2:
            # Only one other player exists — once they fail to counter,
            # the jumper simply takes their turn(s) back.
            self.current_player_idx = self.jump_player.player_id
            self.state = GameState.PLAYING
            # The jump landed uncountered — any extra card bundled into
            # the combo that opened this window stands as-played;
            # nothing to roll back, just stop tracking it (see
            # _jump_bundle).
            self._jump_bundle = None
            self._start_turn()
            return

        self.jump_skip_remaining -= 1
        if self.jump_skip_remaining <= 0:
            self.current_player_idx = (self.counter_player_idx + step) % n
            self.state = GameState.PLAYING
            self._jump_bundle = None
            self._start_turn()
        else:
            # Chain isn't over yet — the next player still gets a shot
            # at countering, so any bundled extra card from the original
            # combo is still "live" and shouldn't be cleared yet.
            self.counter_player_idx = self._next_active_idx(self.counter_player_idx, step)
            self.counter_timer = 0.0
            next_cp = self.players[self.counter_player_idx]
            if not next_cp.is_human and isinstance(next_cp, AIPlayer):
                next_cp.start_thinking()
            self._emit(GameEvent('jump_counter_next', player=next_cp))

    def _execute_jump_counter(self, player: Player, cards: Union[Card, List[Card]]):
        """A player successfully counters the pending J with one or more
        of their own. Playing multiple J's here stacks the skip effect
        just like leading with multiple J's does (see process_play below),
        so e.g. countering with 2 J's re-jumps the field forward by 2."""
        cards = [cards] if isinstance(cards, Card) else list(cards)
        # "Jump Master" tracking: each successful counter re-triggers the
        # window one level deeper — see _start_jump_counter for where a
        # fresh (non-counter) Jump play resets this to 1.
        self._g_jump_chain_depth += 1
        self._g_jump_chain_depth_max = max(self._g_jump_chain_depth_max, self._g_jump_chain_depth)
        # Snapshot BEFORE mutation so a human can undo this counter — see
        # _capture_undo_snapshot's 'origin_state' handling for how undo
        # correctly returns them to this same JUMP_COUNTER_WINDOW rather
        # than a normal turn.
        if player.is_human:
            self._capture_undo_snapshot(player)

        for card in cards:
            player.hand.remove_one(card)
            self.deck.discard(card)

        # A successful counter fully reverses the Jump-bundle it's
        # answering — the extra non-Jump card that rode along with the
        # countered Jump(s) goes back to whoever played it, unplayed,
        # and the rule engine's state rewinds to how it was right after
        # just the Jumps (not the bundled extra) would have been
        # processed. This is what makes leading with the Jumps "safe" —
        # see RuleEngine.jump_bundle_legal's docstring — the bundled
        # card never really happened if the chain gets interrupted here.
        if self._jump_bundle is not None:
            bundle = self._jump_bundle
            owner = bundle['owner']
            extra_cards = bundle['extra_cards']
            self.deck.undiscard(extra_cards)
            owner.hand.add(extra_cards)
            pre = bundle['pre_state']
            self.rule_engine.pickup_pending = pre['pickup_pending']
            self.rule_engine.pickup_suit = pre['pickup_suit']
            self.rule_engine.pickup_rank = pre['pickup_rank']
            self.rule_engine.set_top_card(bundle['last_leader'])
            self.rule_engine.current_suit = pre['current_suit']
            self._jump_bundle = None
            self._emit(GameEvent('jump_counter_voided_bundle', player=owner, cards=extra_cards))

        result = self.rule_engine.process_play(cards, None)
        # Counter cards can't themselves bundle an extra card, but clear
        # this so a stale bundle from the play being countered never
        # leaks into whatever happens next.
        self._jump_bundle = None
        self.pickup_pending_display = self.rule_engine.pickup_pending
        # Keep this in sync with every other play path (_finish_play
        # does the same) — otherwise, if this counter itself chains into
        # ANOTHER counter window for the next player, that window's
        # banner would still show the ORIGINAL triggering combo instead
        # of the counter card(s) that actually just re-triggered it.
        self.last_played_cards = list(cards)
        self._emit(GameEvent('jump_countered', player=player, card=cards[0], cards=cards))
        self.state = GameState.PLAYING
        self.current_player_idx = player.player_id

        # Treat this exactly like any other discretionary play: humans
        # always get the POST_PLAY (KADI-check) window first. Previously
        # a successful counter jumped straight to continuing/ending the
        # chain, so a player who countered and was left holding only
        # finishing cards had no opportunity to declare KADI. Once they
        # proceed, _do_advance_after_play (invoked from _close_post_play)
        # naturally resumes the counter chain via its own skip_count
        # check — exactly as it would for a normal J play.
        if player.is_human:
            self._open_post_play(player, result, None)
            return

        # AI: auto-declare KADI here too, for consistency with every other
        # AI play path — decide_counter() itself has no KADI awareness.
        if (not player.has_declared_kadi and not player.hand.is_empty()
                and player.hand.can_declare_kadi(self.rule_engine)):
            player.has_declared_kadi = True
            self.declared_kadi_player = player
            self._emit(GameEvent('kadi_declared', player=player))
        self._do_advance_after_play(player, result)

    # ─── AI Update ────────────────────────────────────────────────────────────

    def update(self, dt: float):
        """Call every frame with delta time."""
        # Cheap live-sync: previously ace_suit_integrity was only pushed
        # into rule_engine at new_game() time, so toggling it in Settings
        # mid-session had no effect until the next new game — easy to miss
        # and confusing if a player expects a rule change to apply right
        # away.
        self.rule_engine.ace_suit_integrity = self.ace_suit_integrity
        self.rule_engine.pickup_shield_qk_allowed = self.pickup_shield_qk_allowed
        self.rule_engine.ace_finisher_enabled = self.ace_finisher_enabled
        self.rule_engine.jump_multi_card_enabled = self.jump_multi_card_enabled
        if self.state == GameState.PAUSED:
            return
        # Session play-time accumulator for profile['total_time_played_secs']
        # (Part 1) — only while actually playing, not paused. Reset in
        # new_game(), added into the profile once in finalize_profile_stats().
        self._session_elapsed = getattr(self, '_session_elapsed', 0.0) + dt

        if self.state == GameState.JUMP_COUNTER_WINDOW:
            self.update_counter_window(dt)
            # AI counter check
            cp = self.players[self.counter_player_idx]
            if not cp.is_human and isinstance(cp, AIPlayer):
                if cp.update_thinking(dt):
                    counter_card = cp.decide_counter(self.rule_engine)
                    if counter_card:
                        self._execute_jump_counter(cp, counter_card)
                    else:
                        self._jump_counter_declined()
            return

        if self.state == GameState.SUIT_PICK:
            actor = self.players[self.current_player_idx]
            if not actor.is_human and isinstance(actor, AIPlayer):
                chosen = actor._pick_suit([], self._opponent_context(actor))
                self.human_choose_suit(chosen)
            return

        # POST_PLAY delay countdown
        if self.state == GameState.POST_PLAY:
            if self.timers_enabled:
                self.post_play_timer -= dt
                if self.post_play_timer <= 0:
                    self.post_play_timer = 0
                    self._emit(GameEvent('post_play_expired',
                                         player=self._post_play_player))
                    self._close_post_play(declare_kadi=False)
            return

        # Legacy KADI_WINDOW — redirect to POST_PLAY logic
        if self.state == GameState.KADI_WINDOW:
            self.state = GameState.POST_PLAY
            return

        if self.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return

        # Tick turn timer for human players
        if self._turn_timer_active and self.current_player.is_human:
            self.turn_timer -= dt
            if self.turn_timer <= 0:
                self.turn_timer = 0
                self._turn_timer_active = False
                self._emit(GameEvent('turn_timer_expired', player=self.current_player))
                self._do_draw(self.current_player)  # force draw on timeout
                return

        player = self.current_player
        if not player.is_human and isinstance(player, AIPlayer) and self._ai_thinking:
            if player.update_thinking(dt):
                self._ai_thinking = False
                self._execute_ai_turn(player)

    def _opponent_context(self, for_player: Player) -> List[dict]:
        """Public-information snapshot of every other player, handed to
        AIPlayer.decide()/_pick_suit() so higher difficulties can play
        purposefully (disrupt a player about to win, avoid handing them
        the suit they look like they need) using only what's actually
        visible on the table — hand *sizes*, KADI declarations, and each
        player's own history of suits they've played. Never their actual
        hidden cards."""
        n = len(self.players)
        step = self.direction.value
        next_idx = (for_player.player_id + step) % n if n else for_player.player_id
        context = []
        for p in self.players:
            if p is for_player:
                continue
            hist = self.suit_history.get(p.player_id)
            likely_suit = None
            if hist:
                most_common = hist.most_common(1)
                if most_common:
                    likely_suit = most_common[0][0]
            context.append({
                'player_id': p.player_id,
                'hand_count': p.hand.count,
                'has_declared_kadi': p.has_declared_kadi,
                'finished': p.finished,
                'is_next': (self.players[next_idx] is p) if n else False,
                'likely_suit': likely_suit,
            })
        return context

    def _execute_ai_turn(self, player: AIPlayer):
        action = player.decide(self.rule_engine, self.deck, self._opponent_context(player))
        game_log.debug(f"{player.name} AI decided: {action}")
        if action['type'] == 'draw':
            self._do_draw(player)
        elif action['type'] == 'play':
            cards = action['cards']
            suit  = action.get('suit')
            declare = action.get('declare_kadi', False)
            success = self._do_play(player, cards, declare, suit)
            if not success:
                game_log.info(f"{player.name} AI play {cards} was rejected — falling back to draw")
                # Play was rejected — fall back to draw to prevent deadlock
                self._do_draw(player)

    # ─── Win ──────────────────────────────────────────────────────────────────

    def _declare_winner(self, player: Player):
        player.score += 1
        self.winner = player
        self.state = GameState.GAME_OVER
        game_log.info(f"=== GAME OVER — winner: {player.name} (score={player.score}) ===")
        self._emit(GameEvent('game_over', winner=player))

    def _finalize_round_end(self, remaining: List[Player]):
        """Called the instant the match is actually over — either every
        seat is finished/removed, or exactly one player is still
        holding cards. `remaining` is whoever's still genuinely in it
        at that moment (usually the 1 loser stuck with cards; can be
        several AIs at once under the "stop once all humans are done"
        cutoff — see _eliminate_player). Ranks them by finishing cards
        in hand, best first, and appends them to the existing
        finish_order.

        Then — regardless of which of the two call sites reached this
        point, and regardless of what elimination_mode is set to —
        every player force_remove_player() has been holding in
        self._disconnected_removed gets appended AFTER that, in the
        order they actually disconnected. This is the one part that
        isn't just "whoever's left, ranked by hand" bookkeeping: a
        disconnect can happen at ANY point in real time relative to
        everyone else's legitimate finishes, but it must never be
        allowed to land ahead of a player who was still at the table
        when the round ended, no matter how early that disconnect
        happened to occur. Leaving the match is always the worst
        placement available, full stop — that's the whole reason this
        is a separate holding pen rather than something finish_place is
        assigned to immediately in force_remove_player."""
        ranked = sorted(remaining,
                        key=lambda p: sum(1 for c in p.hand.cards if c.is_finishing),
                        reverse=True)
        for p in ranked:
            p.finished = True
            p.finish_place = len(self.finish_order) + 1
            self.finish_order.append(p)
        for p in self._disconnected_removed:
            p.finish_place = len(self.finish_order) + 1
            self.finish_order.append(p)
        self._disconnected_removed = []

        self.winner = self.finish_order[0]
        self.winner.score += 1
        self.state = GameState.GAME_OVER
        standings = ", ".join(f"{p.finish_place}:{p.name}" for p in self.finish_order)
        game_log.info(f"=== GAME OVER — winner: {self.winner.name} "
                      f"(score={self.winner.score}) — standings: {standings} ===")
        self._emit(GameEvent('game_over', winner=self.winner,
                             finish_order=list(self.finish_order)))

    def _eliminate_player(self, player: Player, result: dict):
        """Elimination Mode: a legitimate win doesn't end the game here —
        the player is set aside as finished (in placement order) and play
        continues among whoever's left, until either only one player is
        still holding cards (the loser) or — if
        elimination_ai_only_continue is off — no human players are left
        active, whichever comes first. Whoever's left unfinished at that
        point is appended to finish_order (ranked by finishing cards in
        hand if there's more than one), so finish_order always ends up as
        the full standings, best to worst."""
        player.finished = True
        player.finish_place = len(self.finish_order) + 1
        self.finish_order.append(player)
        game_log.info(f"{player.name} finished in place {player.finish_place}")
        self._emit(GameEvent('player_finished', player=player,
                             place=player.finish_place))

        remaining = [p for p in self.players if not p.finished]
        no_humans_left = not any(p.is_human for p in remaining)
        end_now = len(remaining) <= 1 or (no_humans_left and not self.elimination_ai_only_continue)

        if end_now:
            self._finalize_round_end(remaining)
            return

        # Still 2+ players in it (and, if relevant, still a human among
        # them) — resolve this play's effects and move on exactly like a
        # normal play. There's nothing left for `player` to decide (they
        # just won), so no POST_PLAY window regardless of human/AI.
        # _start_turn's finished-player skip (see there) takes care of
        # never landing back on them.
        self._do_advance_after_play(player, result)

    def force_remove_player(self, player: Player) -> None:
        """Takes a player out of the match because the connection layer
        (server/game_room.GameRoom for Internet play, network/host_game
        .HostGame + network/host.LANHost for LAN play) decided they've
        been unavailable past its own grace timeout -- see each of
        those modules for the actual timer bookkeeping. This is NEVER
        called for AI seats.

        Unlike a normal finish this isn't a placement the player
        earned: they go into self._disconnected_removed, a holding pen
        _finalize_round_end always empties out AFTER whoever's still
        actually at the table when the round ends -- so leaving early
        can never land ahead of a player (or AI) who kept playing, no
        matter how much earlier in real time the disconnect happened.
        Two humans and no elimination mode is the simplest case this
        produces: the remaining player is the only "real" finisher
        there is, so they land in finish_order position 1 (the winner)
        with the disconnector after them. Otherwise the bookkeeping
        mirrors _eliminate_player: marked `finished` (so _start_turn /
        _next_active_idx skip them from here on, regardless of
        elimination_mode), and if that leaves only one player still in
        it, the round ends now via the same _finalize_round_end this
        and _eliminate_player both funnel through.

        If it was this player's turn (or their pending decision — a
        jump counter, a post-play KADI window, an ace suit pick) that
        decision is force-resolved with the least eventful outcome
        (pass / proceed / whatever suit they're already holding most
        of) rather than left hanging forever waiting on input that
        will never come."""
        if self.state == GameState.GAME_OVER or player.finished:
            return
        game_log.info(f"{player.name} force-removed from the match "
                      f"(disconnected past the grace period)")
        is_current = self.current_player is player
        # Marked out FIRST so whichever unblock call below triggers a
        # turn advance, that advance's own _start_turn skip already
        # treats this player as gone.
        player.finished = True
        player.disconnected = True

        if (self.state == GameState.JUMP_COUNTER_WINDOW
                and self.players[self.counter_player_idx] is player):
            self.human_pass_counter()
        elif self.state == GameState.POST_PLAY and self._post_play_player is player:
            self._close_post_play(declare_kadi=False)
        elif self.state == GameState.SUIT_PICK and is_current:
            counts = Counter(c.suit for c in player.hand.cards)
            suit = counts.most_common(1)[0][0] if counts else Suit.SPADES
            self.human_choose_suit(suit)
        elif self.state in (GameState.PLAYING, GameState.KADI_DECLARED) and is_current:
            self._turn_timer_active = False
            self._advance_turn()

        if self.state == GameState.GAME_OVER:
            return  # one of the calls above already ended the round

        # NOT appended to finish_order here — see _finalize_round_end
        # for why leaving early must never earn a better placement
        # than a player who was still at the table when the round
        # actually ends. This just holds them until that happens.
        self._disconnected_removed.append(player)
        self._emit(GameEvent('player_disconnected_removed', player=player))

        remaining = [p for p in self.players if not p.finished]
        if len(remaining) <= 1:
            self._finalize_round_end(remaining)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @property
    def current_player(self) -> Player:
        return self.players[self.current_player_idx]

    @property
    def human_player(self) -> Optional[Player]:
        for p in self.players:
            if p.is_human:
                return p
        return None

    @property
    def is_ai_spectator_mode(self) -> bool:
        """True once every human player has finished in Elimination Mode
        (elimination_ai_only_continue=True keeps the round going) — there's
        nobody left for the person at the keyboard to control, only the
        remaining AIs playing each other out to a final ranking. The
        gameplay scene uses this to flip AI hands face-up and offer a
        speed control, since this stretch is now purely for watching."""
        if not self.elimination_mode or self.state == GameState.GAME_OVER:
            return False
        active = [p for p in self.players if not p.finished]
        if not active:
            return False
        return not any(p.is_human for p in active)

    # Fine-grained at the slow end (this is the part people actually asked
    # for — 0.25x was still too fast to follow what the AIs were doing)
    # and coarser toward the fast end, where nobody needs a 0.1x-sized
    # step to skip through the remainder.
    SPECTATOR_SPEEDS = [0.1, 0.15, 0.2, 0.25, 0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 3.0, 4.0]

    def cycle_ai_spectator_speed(self, step: int):
        """Move up/down the SPECTATOR_SPEEDS ladder by one step, clamped
        to both ends rather than wrapping — repeatedly hammering + or -
        should just settle at the fastest/slowest setting, not loop back
        around to the opposite extreme."""
        speeds = self.SPECTATOR_SPEEDS
        cur = min(range(len(speeds)), key=lambda i: abs(speeds[i] - self.ai_spectator_speed))
        new_idx = max(0, min(len(speeds) - 1, cur + step))
        self.ai_spectator_speed = speeds[new_idx]

    def cycle_ai_game_speed(self, step: int):
        """Same ladder, same clamping behaviour as
        cycle_ai_spectator_speed above, but for ai_game_speed — the
        dial that applies during ordinary play rather than the
        end-of-round AI-only spectator stretch."""
        speeds = self.SPECTATOR_SPEEDS
        cur = min(range(len(speeds)), key=lambda i: abs(speeds[i] - self.ai_game_speed))
        new_idx = max(0, min(len(speeds) - 1, cur + step))
        self.ai_game_speed = speeds[new_idx]

    def get_playable_cards(self) -> List[Card]:
        return self.current_player.hand.get_playable(self.rule_engine)

    def get_hint_card(self) -> Optional[Card]:
        """Suggest one legal card the current human player could play
        right now. Deliberately NOT a strong/strategic AI — it's just the
        first legal option in hand order — so it nudges a stuck player
        without playing the game for them. Returns None if hints don't
        apply right now (not human's turn, nothing playable, etc.)."""
        player = self.current_player
        if not player.is_human:
            return None
        playable = player.hand.get_playable(self.rule_engine)
        return playable[0] if playable else None

    @property
    def hint_should_show(self) -> bool:
        """True once hints are enabled and the human has been sitting on
        their turn for hint_threshold_pct of their configured turn timer.
        Requires an actual turn timer (timers_enabled and turn_timer_secs
        > 0) since the threshold is defined as a percentage of it."""
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

    def subscribe(self, callback: Callable):
        # Idempotent: re-subscribing the same bound method (e.g. a scene's
        # on_enter running again after "Play Again", without a matching
        # unsubscribe) used to silently stack duplicate callbacks, so every
        # subsequent event — including effect-text messages like
        # "X picks N!" — fired once per stacked subscription and rendered
        # as visibly overlapping duplicate text.
        if callback in self._event_callbacks:
            return
        self._event_callbacks.append(callback)

    def unsubscribe(self, callback: Callable):
        if callback in self._event_callbacks:
            self._event_callbacks.remove(callback)

    def _emit(self, event: GameEvent):
        for cb in self._event_callbacks:
            cb(event)

    def get_player_at_position(self, pos_index: int) -> Optional[Player]:
        """Get player relative to current layout position."""
        if pos_index < len(self.players):
            return self.players[pos_index]
        return None
