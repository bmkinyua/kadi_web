"""
KADI - LAN networking: state snapshot codec.

This is the ONE place that knows how to turn a real, authoritative
GameManager (host side) into a JSON-safe, per-recipient "public view"
snapshot, and how to turn that snapshot back into the mirrored
attributes a network/client_state.ClientGameManager exposes to the UI.

PRIVACY BOUNDARY: exactly the same one GameManager._opponent_context
already defines for AI decision-making (hand *counts*, not contents,
for anyone who isn't the recipient) — reused here rather than
reinvented, so "what an AI is allowed to know about opponents" and
"what a network client is allowed to know about opponents" can never
drift apart. The one addition beyond _opponent_context's shape is the
recipient's OWN full hand, included only in the copy of the snapshot
addressed to that specific player_id.

This module has no pygame dependency and no socket dependency — it's
pure data transformation, which is what makes it independently testable
(see tests/test_phase2_state_sync.py).
"""
from __future__ import annotations
from typing import Dict, List, Optional

from constants import GameState, PlayDirection, AIDifficulty
from network.codec import card_to_dict, cards_to_list
from models.player import AIPlayer


def build_snapshot_for(gm, recipient_id: int, events: Optional[List[dict]] = None) -> dict:
    """Build the state_sync payload addressed to `recipient_id`. Safe
    to call at any point during PLAYING/POST_PLAY/SUIT_PICK/
    JUMP_COUNTER_WINDOW/GAME_OVER — every field either has a sensible
    default or is None when not applicable to the current state, so
    the client never has to guess whether a field is stale. `events`
    is the list of GameEvents (already encoded via
    network/event_codec.encode_event) emitted since the last snapshot
    sent to this recipient — see network/host_game.py, which buffers
    them between broadcasts so nothing emitted between two network
    ticks is ever silently dropped.
    """
    re = gm.rule_engine
    players = []
    for p in gm.players:
        entry = {
            'player_id': p.player_id,
            'name': p.name,
            'is_human': p.is_human,
            'difficulty': p.difficulty.name if isinstance(p, AIPlayer) else None,
            'score': p.score,
            'has_declared_kadi': p.has_declared_kadi,
            'finished': p.finished,
            'finish_place': p.finish_place,
            'hand_count': p.hand.count,
            # Only the recipient gets their own actual cards — everyone
            # else is count-only, mirroring _opponent_context's boundary.
            'hand': cards_to_list(p.hand.cards) if p.player_id == recipient_id else None,
        }
        players.append(entry)

    post_play = None
    if gm.state == GameState.POST_PLAY:
        post_play = {
            'player_id': gm._post_play_player.player_id if gm._post_play_player else None,
            'can_kadi': gm._post_play_can_kadi,
            'timer': gm.post_play_timer,
        }

    return {
        'type': 'state_sync',
        'you': recipient_id,
        'state': gm.state.name,
        'current_player_idx': gm.current_player_idx,
        'direction': gm.direction.name,
        'elimination_mode': gm.elimination_mode,
        'elimination_ai_only_continue': gm.elimination_ai_only_continue,
        'winner_id': gm.winner.player_id if gm.winner else None,
        'finish_order_ids': [p.player_id for p in gm.finish_order],
        'declared_kadi_player_id': (gm.declared_kadi_player.player_id
                                     if gm.declared_kadi_player else None),
        'skipped_player_id': gm.skipped_player.player_id if gm.skipped_player else None,
        'last_effect_text': gm.last_effect_text,
        'last_played_cards': cards_to_list(gm.last_played_cards),
        'pickup_pending_display': gm.pickup_pending_display,
        'players': players,
        'rule_engine': {
            'current_suit': re.current_suit.name if re.current_suit else None,
            'pickup_pending': re.pickup_pending,
            'pickup_rank': re.pickup_rank,
            'pickup_suit': re.pickup_suit.name if re.pickup_suit else None,
            'top_card': card_to_dict(re._top_card),
            'skip_count': re.skip_count,
            'joker_on_top': re.joker_on_top,
            'ace_suit_integrity': re.ace_suit_integrity,
            'pickup_shield_qk_allowed': re.pickup_shield_qk_allowed,
            'ace_finisher_enabled': re.ace_finisher_enabled,
            'jump_multi_card_enabled': re.jump_multi_card_enabled,
        },
        'deck': {
            'draw_count': gm.deck.draw_count,
            'discard_count': gm.deck.discard_count,
        },
        'counter_player_idx': gm.counter_player_idx,
        'jump_player_id': gm.jump_player.player_id if gm.jump_player else None,
        'jump_skip_remaining': gm.jump_skip_remaining,
        'counter_timer': gm.counter_timer,
        'counter_window_secs': gm.counter_window_secs,
        'post_play': post_play,
        'turn_timer': gm.turn_timer,
        'turn_timer_secs': gm.turn_timer_secs,
        'timers_enabled': gm.timers_enabled,
        'post_play_delay_secs': gm.post_play_delay_secs,
        'hints_enabled': gm.hints_enabled,
        'hint_threshold_pct': gm.hint_threshold_pct,
        'undo_available': False,  # undo is host-local only — see network/README.md
        'events': events or [],
    }

