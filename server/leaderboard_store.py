"""
KADI - Internet multiplayer: server-side GLOBAL leaderboard persistence.

Tracks per-player-name win counts for Internet Multiplayer games ONLY.
The increment happens at the one point the server's own authoritative
GameManager reaches GAME_OVER for a room (see server/kadi_server.py's
tick() -> GameRoom.winner_name()), using gm.winner -- never anything a
client claims. Single-player and LAN wins are self-reported by
whichever client submits them and are trivially fakeable by a modified
client, so they're deliberately never fed into this store; see the
task's PART B design note.

A flat JSON file is entirely sufficient at this scale -- this follows
the same DEFAULTS/load/save shape core/profile_store.py already uses
for the client's own local profile.json, just keyed by display name
instead of nested under one player's own progress.

NAME-KEYED, NOT ACCOUNT-KEYED: Internet Multiplayer has no login/
account system -- a player is only ever the free-text display name
typed on InternetMenuScene's connect screen (see
server/kadi_server.py's 'hello' handling). Nothing stops two different
people using the same name, or one person using a different name each
session -- this leaderboard is therefore a best-effort ranking under
that limitation, not a verified identity system. A real account system
is explicitly out of scope for this pass (see the task's READ FIRST
section) -- don't build one here.
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional, Tuple

LEADERBOARD_FILENAME = "leaderboard.json"

# How many recently-credited game_ids to remember for the exactly-once
# increment guard (see record_win) -- reusing the same "must fire
# exactly once per finished game" requirement
# core.game_manager.GameManager._stats_recorded_for_game_id exists for
# (that one guards one GameManager instance; this guards the server's
# whole set of concurrent rooms, so it's a list of ids rather than a
# single attribute). A room is dropped from the Lobby the instant its
# game reaches GAME_OVER (see server/kadi_server.py's tick()), so in
# practice a given game_id is only ever offered to record_win once --
# this is belt-and-braces against any future code path that might call
# it again, not a response to an observed bug. Capped so the file
# doesn't grow forever across a long-running server's lifetime.
MAX_RECORDED_GAME_IDS = 2000


def _default_store() -> Dict[str, Any]:
    return {
        # display_name -> total Internet Multiplayer wins.
        "wins": {},
        "recorded_game_ids": [],
    }


class LeaderboardStore:
    """Thread-unsafe by design, same as Lobby/GameRoom: only ever
    touched from the single main server tick thread (see
    server/kadi_server.py's tick()/_handle_message()) -- background
    recv threads never reach in here directly, only via the incoming
    queue that tick() drains."""

    def __init__(self, path: str):
        self._path = path
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self._path):
            try:
                with open(self._path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get('wins'), dict):
                    data.setdefault('recorded_game_ids', [])
                    return data
            except Exception:
                pass
        return _default_store()

    def _save(self):
        try:
            tmp = self._path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            pass  # persistence is best-effort -- in-memory counts stay correct regardless

    def record_win(self, name: str, game_id: str) -> bool:
        """Increment `name`'s win count, unless `game_id` has already
        been recorded (exactly-once guard -- see class docstring).
        Returns True if this call actually incremented anything."""
        if not name or not game_id:
            return False
        recorded = self._data['recorded_game_ids']
        if game_id in recorded:
            return False
        recorded.append(game_id)
        if len(recorded) > MAX_RECORDED_GAME_IDS:
            del recorded[: len(recorded) - MAX_RECORDED_GAME_IDS]
        wins = self._data['wins']
        wins[name] = wins.get(name, 0) + 1
        self._save()
        return True

    def _ranked(self) -> List[Tuple[str, int]]:
        # Ties broken alphabetically (case-insensitive) so top() and
        # rank_for() always agree on ordering.
        return sorted(self._data['wins'].items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def top(self, n: int = 20) -> List[Tuple[str, int]]:
        return self._ranked()[:max(1, n)]

    def rank_for(self, name: str) -> Optional[Tuple[int, int]]:
        """(1-based rank, win count) for `name`, or None if they have
        no recorded wins yet."""
        for i, (n_, w) in enumerate(self._ranked(), start=1):
            if n_ == name:
                return i, w
        return None
