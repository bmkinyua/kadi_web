"""
KADI - MSOMI decision logging.

Writes one JSON record per real decision (human or AI) to a JSONL
sidecar file next to the current text log — see
core/game_logger.get_current_jsonl_path. The text log's own MSOMI lines
stay truncated to a top-6 summary for human readability; this file has
EVERYTHING: every legal option this turn, every named feature on it,
and which one was actually chosen. This is the actual training data
Chuo (in-house model training, see the main menu) reads from.

Never lets a logging failure affect the game itself — every write is
best-effort and silently swallowed on error.
"""
from __future__ import annotations
import json
import os
from typing import List, Optional
from models.card import Card
from core.game_logger import get_current_jsonl_path

# Bump this whenever the shape of a logged record changes (a feature
# added/removed/renamed, etc.). Chuo checks this against what it knows
# how to train on and refuses to silently mix incompatible schema
# versions together; a model file trained under one version records
# that version too, so a stale model is caught at load time in the
# MSOMI settings instead of silently misbehaving in a real game.
SCHEMA_VERSION = 1

# The exact set of per-option fields written out — kept as an explicit
# list (rather than just dumping whatever keys happen to be in the
# evaluated dict) so a future change to _evaluate_play's internals
# doesn't silently change the training schema without a version bump.
_OPTION_FIELDS = [
    'score', 'cards_played', 'cards_remaining', 'empties_hand', 'wastes_win',
    'leaves_kadi', 'unanswered_question', 'pickup_value_added', 'has_suit_change',
    'has_skip', 'has_kickback', 'has_question', 'next_is_threat', 'stranded_cluster_cost',
]

_current_game_id: Optional[str] = None


def set_game_id(game_id: str) -> None:
    """Call once per GameManager.new_game() — every decision logged
    afterward is tagged with this until the next new game, so Chuo can
    tell which decisions came from the same game (needed for any future
    outcome-based training, and useful for basic sanity-checking a
    dataset even now)."""
    global _current_game_id
    _current_game_id = game_id


def _card_str(c: Optional[Card]) -> Optional[str]:
    return None if c is None else str(c)


def log_decision(*, is_human: bool, player_name: str, difficulty: str,
                  hand_before: List[Card], evaluated: List[dict], chosen: dict,
                  declared_kadi: bool, pickup_pending: int, top_card: Optional[Card]) -> None:
    """Append one full-fidelity decision record. No-op if logging is
    currently off, and never raises — a failure here must never be able
    to break an actual game in progress."""
    path = get_current_jsonl_path()
    if path is None:
        return
    try:
        chosen_rank = evaluated.index(chosen)
        record = {
            'schema_version': SCHEMA_VERSION,
            'game_id': _current_game_id,
            'is_human': is_human,
            'player_name': player_name,
            'difficulty': difficulty,
            'hand_before': [_card_str(c) for c in hand_before],
            'hand_count': len(hand_before),
            'top_card': _card_str(top_card),
            'pickup_pending': pickup_pending,
            'declared_kadi': declared_kadi,
            'chosen_rank': chosen_rank,
            'num_options': len(evaluated),
            'options': [
                {
                    'cards': [_card_str(c) for c in ev['cards']] if ev['cards'] is not None else None,
                    'is_draw': ev['cards'] is None,
                    **{field: ev[field] for field in _OPTION_FIELDS},
                }
                for ev in evaluated
            ],
        }
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record) + '\n')
    except Exception:
        pass
