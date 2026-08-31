"""
KADI - LAN networking: GameEvent <-> JSON codec.

GameManager already emits a rich stream of GameEvent objects (see every
`self._emit(GameEvent(...))` call in core/game_manager.py) that
GameplayScene._on_game_event consumes to drive toast banners, sounds,
and the win screen. Rather than hand-translating each of the ~25 event
kinds one at a time (fragile — a new event kind added to game_manager.py
later would silently fail to reach network clients), this is a GENERIC
codec: it walks whatever attributes a given GameEvent actually carries,
converts Player -> a player_id reference and Card -> a card dict, and
leaves already-JSON-safe values alone. The client-side decoder reverses
this using its own local Player objects (looked up by the same
player_id every seat already carries — see network/client_state.py),
producing a real GameEvent that GameplayScene's existing handler can
consume completely unmodified.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from models.player import Player
from models.card import Card
from network.codec import card_to_dict, card_from_dict


def encode_event(event) -> dict:
    """Host side: GameEvent -> JSON-safe dict."""
    fields = {}
    for k, v in event.__dict__.items():
        if k == 'kind':
            continue
        fields[k] = _encode_value(v)
    return {'kind': event.kind, 'fields': fields}


def _encode_value(v: Any) -> Any:
    if isinstance(v, Player):
        return {'__player_id__': v.player_id}
    if isinstance(v, Card):
        return {'__card__': card_to_dict(v)}
    if isinstance(v, list):
        return [_encode_value(x) for x in v]
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    # Enums (e.g. a future event carrying a Suit/GameState directly)
    name = getattr(v, 'name', None)
    if isinstance(name, str):
        return name
    return str(v)


def decode_event(msg: dict, players_by_id: Dict[int, Player]):
    """Client side: JSON dict -> a real GameEvent, using the client's
    own local Player objects (looked up by player_id) so downstream
    code (GameplayScene._on_game_event) sees exactly the same shape it
    would from a local game."""
    from core.game_manager import GameEvent  # no pygame dependency
    kind = msg.get('kind', '')
    fields = msg.get('fields', {})
    kwargs = {k: _decode_value(v, players_by_id) for k, v in fields.items()}
    return GameEvent(kind, **kwargs)


def _decode_value(v: Any, players_by_id: Dict[int, Player]) -> Any:
    if isinstance(v, dict):
        if '__player_id__' in v:
            return players_by_id.get(v['__player_id__'])
        if '__card__' in v:
            return card_from_dict(v['__card__'])
        return v
    if isinstance(v, list):
        return [_decode_value(x, players_by_id) for x in v]
    return v
