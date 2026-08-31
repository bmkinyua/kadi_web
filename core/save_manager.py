"""
KADI - Game progress save/load.

Lets a single-player game be saved to disk and resumed later from the
main menu. Deliberately only supports saving from a safe, simple state
(PLAYING or POST_PLAY) — GameplayScene is responsible for steering the
player through a transient decision (suit pick, jump-counter window)
before offering to save, rather than this module trying to serialize
every mid-decision nuance.
"""
from __future__ import annotations
import json
import os
import uuid
from typing import Any, Dict, Optional

from constants import GameState, Suit, AIDifficulty, PlayDirection
from models.card import Card, Deck
from models.player import HumanPlayer, AIPlayer
from core.rule_engine import RuleEngine
from core.game_logger import base_dir, game_log
from core import decision_logger

SAVE_FILENAME = "savegame.json"

# States it's safe to save from / resume into. Anything else (suit pick,
# jump-counter window, paused-mid-animation, etc.) is a transient
# decision point the UI should resolve one way or another before it ever
# offers to save.
RESUMABLE_STATES = (GameState.PLAYING, GameState.POST_PLAY)


def _save_path() -> str:
    return os.path.join(base_dir(), SAVE_FILENAME)


def has_save_file() -> bool:
    return os.path.isfile(_save_path())


def delete_save_file():
    try:
        path = _save_path()
        if os.path.isfile(path):
            os.remove(path)
    except Exception as e:
        game_log.info(f"Failed to delete save file: {e}")


def _card_to_dict(card: Optional[Card]) -> Optional[dict]:
    if card is None:
        return None
    return {
        'suit': card.suit.name if card.suit else None,
        'rank': card.rank,
        'is_red_joker': card.is_red_joker,
    }


def _card_from_dict(d: Optional[dict]) -> Optional[Card]:
    if d is None:
        return None
    suit = Suit[d['suit']] if d['suit'] else None
    return Card(suit=suit, rank=d['rank'], is_red_joker=d.get('is_red_joker', False))


def _effective_state(gm) -> GameState:
    """The state that actually matters for save/resume purposes — when
    the game is paused (e.g. auto-paused behind the exit-confirm dialog),
    that's the state it'll return to on resume, not GameState.PAUSED
    itself."""
    if gm.state == GameState.PAUSED:
        return gm._pre_pause_state or gm.state
    return gm.state


def can_save(gm) -> bool:
    return _effective_state(gm) in RESUMABLE_STATES


def save_game(gm) -> bool:
    """Serialize the current game to disk. Returns True on success.
    Refuses to save from a non-resumable state (see RESUMABLE_STATES) —
    callers should steer the player to Proceed/decide first."""
    if not can_save(gm):
        game_log.info(f"save_game: refusing to save from state {gm.state}")
        return False
    try:
        state = _effective_state(gm)
        data: Dict[str, Any] = {
            'version': 1,
            'elimination_mode': gm.elimination_mode,
            'elimination_ai_only_continue': gm.elimination_ai_only_continue,
            'joker_count': gm.joker_count,
            'ace_suit_integrity': gm.ace_suit_integrity,
            'suit_change_after_shield': gm.suit_change_after_shield,
            'current_player_idx': gm.current_player_idx,
            'direction': gm.direction.name,
            'state': state.name,
            'pickup_pending_display': gm.pickup_pending_display,
            'last_effect_text': gm.last_effect_text,
            'declared_kadi_player_id': (gm.declared_kadi_player.player_id
                                        if gm.declared_kadi_player else None),
            'finish_order_ids': [p.player_id for p in gm.finish_order],
            'players': [],
            'deck': {
                'joker_count': gm.deck.joker_count,
                'draw_pile': [_card_to_dict(c) for c in gm.deck._draw_pile],
                'discard_pile': [_card_to_dict(c) for c in gm.deck._discard_pile],
            },
            'rule_engine': {
                'current_suit': gm.rule_engine.current_suit.name if gm.rule_engine.current_suit else None,
                'pickup_pending': gm.rule_engine.pickup_pending,
                'pickup_rank': gm.rule_engine.pickup_rank,
                'pickup_suit': gm.rule_engine.pickup_suit.name if gm.rule_engine.pickup_suit else None,
                'top_card': _card_to_dict(gm.rule_engine._top_card),
                'skip_count': gm.rule_engine.skip_count,
                'joker_on_top': gm.rule_engine.joker_on_top,
            },
        }
        for p in gm.players:
            data['players'].append({
                'name': p.name,
                'is_human': p.is_human,
                'difficulty': p.difficulty.name if isinstance(p, AIPlayer) else None,
                'score': p.score,
                'has_declared_kadi': p.has_declared_kadi,
                'finished': p.finished,
                'finish_place': p.finish_place,
                'hand': [_card_to_dict(c) for c in p.hand.cards],
            })
        if state == GameState.POST_PLAY:
            data['post_play'] = {
                'player_id': gm._post_play_player.player_id if gm._post_play_player else None,
                'can_kadi': gm._post_play_can_kadi,
                'result': gm._post_play_result,
            }

        with open(_save_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        game_log.info(f"Failed to save game: {e}")
        return False


def load_game(gm) -> bool:
    """Rehydrate gm in-place from the save file. Returns True on success.
    On any failure, the save file is left untouched but load fails
    cleanly (gm is not left half-modified — validation happens against
    the raw dict before anything is assigned)."""
    path = _save_path()
    if not os.path.isfile(path):
        return False
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Rebuild players first
        players = []
        for i, pd in enumerate(data['players']):
            if pd['is_human']:
                p = HumanPlayer(pd['name'], i)
            else:
                diff = AIDifficulty[pd['difficulty']] if pd['difficulty'] else AIDifficulty.MEDIUM
                p = AIPlayer(pd['name'], i, diff)
            p.score = pd.get('score', 0)
            p.has_declared_kadi = pd.get('has_declared_kadi', False)
            p.finished = pd.get('finished', False)
            p.finish_place = pd.get('finish_place')
            p.hand._cards = [_card_from_dict(c) for c in pd['hand']]
            players.append(p)

        deck = Deck(joker_count=data['deck']['joker_count'])
        deck._draw_pile = [_card_from_dict(c) for c in data['deck']['draw_pile']]
        deck._discard_pile = [_card_from_dict(c) for c in data['deck']['discard_pile']]

        re_data = data['rule_engine']
        rule_engine = RuleEngine()
        rule_engine.current_suit = Suit[re_data['current_suit']] if re_data['current_suit'] else None
        rule_engine.pickup_pending = re_data['pickup_pending']
        rule_engine.pickup_rank = re_data['pickup_rank']
        rule_engine.pickup_suit = Suit[re_data['pickup_suit']] if re_data['pickup_suit'] else None
        rule_engine._top_card = _card_from_dict(re_data['top_card'])
        rule_engine.skip_count = re_data['skip_count']
        rule_engine.joker_on_top = re_data['joker_on_top']
        rule_engine.ace_suit_integrity = data.get('ace_suit_integrity', gm.ace_suit_integrity)

        # Everything parsed OK — now actually apply it to gm.
        gm.players = players
        gm.deck = deck
        gm.rule_engine = rule_engine
        gm.elimination_mode = data.get('elimination_mode', False)
        gm.elimination_ai_only_continue = data.get('elimination_ai_only_continue', True)
        gm.joker_count = data.get('joker_count', gm.joker_count)
        gm.ace_suit_integrity = rule_engine.ace_suit_integrity
        gm.suit_change_after_shield = data.get('suit_change_after_shield', gm.suit_change_after_shield)
        gm.current_player_idx = data['current_player_idx']
        gm.direction = PlayDirection[data['direction']]
        gm.state = GameState[data['state']]
        gm.pickup_pending_display = data.get('pickup_pending_display', 0)
        gm.last_effect_text = data.get('last_effect_text', "")
        gm.winner = None
        dk_id = data.get('declared_kadi_player_id')
        gm.declared_kadi_player = gm.players[dk_id] if dk_id is not None else None
        gm.finish_order = [gm.players[i] for i in data.get('finish_order_ids', [])]

        # A resumed game is still a "new" game as far as game_id/stat
        # tracking goes — normally these are set in new_game(), but
        # loading a save bypasses that entirely. Without this, gm.game_id
        # and gm._stats_recorded_for_game_id are simply never set (nothing
        # else initializes them), and finalize_profile_stats() crashes
        # with an AttributeError the moment this resumed game ends.
        gm.game_id = str(uuid.uuid4())
        gm._stats_recorded_for_game_id = None
        decision_logger.set_game_id(gm.game_id)

        gm.skipped_player = None
        gm._undo_snapshot = None
        gm._consecutive_draws = 0
        gm.turn_timer = gm.turn_timer_secs
        gm._turn_timer_active = False
        gm._ai_thinking = False

        gm._post_play_player = None
        gm._post_play_result = None
        gm._post_play_can_kadi = False

        # Re-arm whatever's actually driving the current state, reusing
        # the real turn-start / post-play-open logic rather than trying
        # to hand-reconstruct AI-thinking flags and timers here. Both are
        # safe to call again on an in-progress (not brand new) turn —
        # neither touches hand/deck, they only (re)compute display/timer
        # state from what's already there.
        if gm.state == GameState.PLAYING:
            gm._start_turn()
        elif gm.state == GameState.POST_PLAY and 'post_play' in data:
            pp = data['post_play']
            pp_player = gm.players[pp['player_id']] if pp['player_id'] is not None else gm.current_player
            gm._open_post_play(pp_player, pp.get('result') or {}, None)

        return True
    except Exception as e:
        game_log.info(f"Failed to load game ({e}) — save file left untouched")
        return False
