"""
KADI - Internet multiplayer: matchmaking lobby.

Tracks every currently-open (not-yet-started) GameRoom so a connecting
player can list and join one, plus every STARTED room for the
duration of its match (so intents/ticks can still be routed to it).
A room is dropped once its game reaches GAME_OVER, or (pre-start only)
once its host disconnects / every member leaves -- see
server/kadi_server.py's _remove_from_room / tick.

Anyone can create a hosted game and configure its settings; anyone
can browse open games and join one; there is no fixed "always host" /
"always joiner" role -- exactly the flow specified for this feature.
Whoever calls create_game happens to occupy seat 0 in that particular
room once it starts (needed for a stable, LAN-style seat-index
scheme), nothing more -- they get no other privilege besides being the
only one allowed to click Start.
"""
from __future__ import annotations
import itertools
import threading
from typing import Dict, List, Optional

from server.game_room import GameRoom


class Lobby:
    def __init__(self):
        # Guards _rooms / the id counter. In practice only ever
        # touched by the single main server thread (see
        # server/kadi_server.py's tick()), but kept explicit rather
        # than assumed, the same defensive style network/host.py uses
        # for its own registry lock.
        self._lock = threading.Lock()
        self._rooms: Dict[str, GameRoom] = {}
        self._id_counter = itertools.count(1)

    def create_game(self, host_conn_id: int, host_name: str, settings: dict) -> GameRoom:
        game_id = f"game{next(self._id_counter)}"
        room = GameRoom(game_id, host_conn_id, host_name, settings)
        with self._lock:
            self._rooms[game_id] = room
        return room

    def get(self, game_id: str) -> Optional[GameRoom]:
        with self._lock:
            return self._rooms.get(game_id)

    def remove(self, game_id: str):
        with self._lock:
            self._rooms.pop(game_id, None)

    def open_games_summary(self) -> List[dict]:
        """Browsable listing: open (not started, not closed) rooms
        only -- a started match has nothing left to join."""
        with self._lock:
            rooms = list(self._rooms.values())
        out = []
        for r in rooms:
            if r.started or r.closed:
                continue
            out.append({
                'game_id': r.game_id,
                'host_name': r.member_names.get(r.host_conn_id, '?'),
                # Empty string (not the display fallback) when the
                # host left it blank, so the client can decide how to
                # render that itself (see InternetLobbyScene.draw()'s
                # "g.get('game_name') or f\"{host}'s game\"" pattern) —
                # keeps the raw "did they actually name it?" fact
                # available client-side too, e.g. for the search filter.
                'game_name': r.game_name,
                'player_count': len(r.member_names),
                'max_players': 6,
                'rows': [list(row) for row in r.settings_summary_rows()],
            })
        return out

    def room_for_conn(self, conn_id: int) -> Optional[GameRoom]:
        with self._lock:
            rooms = list(self._rooms.values())
        for r in rooms:
            if conn_id in r.member_names:
                return r
        return None

    def all_rooms(self) -> List[GameRoom]:
        with self._lock:
            return list(self._rooms.values())
