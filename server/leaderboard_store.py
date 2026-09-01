"""
KADI - Internet multiplayer: server-side GLOBAL leaderboard persistence.

Tracks per-player win counts for Internet Multiplayer games ONLY. The
increment happens at the one point the server's own authoritative
GameManager reaches GAME_OVER for a room (see server/kadi_server.py's
tick() -> GameRoom.winner_name()), using gm.winner -- never anything a
client claims. Single-player and LAN wins are self-reported by
whichever client submits them and are trivially fakeable by a modified
client, so they're deliberately never fed into this store; see the
task's PART B design note.

A flat JSON file is entirely sufficient at this scale -- this follows
the same DEFAULTS/load/save shape core/profile_store.py already uses
for the client's own local profile.json, just keyed by player identity
instead of nested under one player's own progress.

IDENTITY KEY, NOT ACCOUNT SYSTEM: originally this store was purely
NAME-KEYED -- Internet Multiplayer had no login/account system, a
player was only ever the free-text display name typed on
InternetMenuScene's connect screen, and "a real account system" was
explicitly out of scope for that pass. That's still true for the
desktop TCP client today: nothing about its capabilities changed, so
it still only ever has a name to offer, and is still keyed by it
(still trivially spoofable/collidable by that same free-text name --
that hasn't changed either).

What HAS changed, for the web port: a browser-based client running
inside Discord or Telegram gets handed a stable, platform-issued user
id as part of that platform's own login the person already did to be
in that chat/voice channel at all -- see server/kadi_server.py's
'hello' handling for how `external_id` gets attached to a connection.
Entries for a connection that has one are keyed by that
`"{platform}:{external_id}"` string instead of by name, which is a
straightforward, real improvement in that one narrow way: it can't be
spoofed by retyping someone else's display name, the way the old
purely-name-keyed scheme could.

What this does NOT do -- and where the line to "real account system"
still sits, unmoved -- is merge a player's history ACROSS platforms.
Someone who plays as "Alice" on Discord and also on Telegram gets two
separate leaderboard entries, `discord:123...` and `telegram:456...`,
each correctly unspoofable on its own platform but with zero
relationship to each other. Building that link (one canonical profile
multiple platform identities attach to) is a real, larger feature --
some kind of link/claim flow -- and is deliberately NOT built here,
for the identical reason the original note deferred accounts
entirely: it's real added scope, tracked as a future item, not a
silent side effect of adding WebSocket support.

One more honest limit, worth stating plainly rather than glossing
over: this store trusts whatever `external_id` server/kadi_server.py
hands it. Verifying that a claimed Discord/Telegram id is genuine
(checking a signed OAuth token / Telegram's initData HMAC, rather than
trusting a client-supplied field at face value) is real, platform-
specific work that belongs in each platform adapter once it's actually
being built -- it does not exist yet, since no Discord/Telegram app
credentials exist yet either. Until that verification lands, treat
`external_id`-keyed entries as "not spoofable by retyping a name" but
NOT yet as "cryptographically verified" -- an honest middle ground
between today's pure name-keying and a fully verified identity system.
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
        # identity_key -> {"name": last-seen display name, "count": wins}.
        # identity_key is "{platform}:{external_id}" when the winning
        # connection had one, otherwise the display name itself
        # (exactly today's pre-identity-key behavior) -- see this
        # module's docstring.
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
                    data['wins'] = self._migrate_wins(data['wins'])
                    return data
            except Exception:
                pass
        return _default_store()

    @staticmethod
    def _migrate_wins(wins: Dict[str, Any]) -> Dict[str, Any]:
        """Upgrade any pre-identity-key entries (plain int win counts,
        keyed directly by display name -- the only shape this file
        ever had before) into the current {"name", "count"} shape, in
        place. A file that's already current just passes through
        unchanged. This runs on every load, not as a one-off migration
        script, so a leaderboard.json from before this change keeps
        working with zero manual steps."""
        migrated = {}
        for key, value in wins.items():
            if isinstance(value, dict):
                migrated[key] = {
                    "name": str(value.get("name", key)),
                    "count": int(value.get("count", 0)),
                }
            else:
                # Legacy shape: key WAS the display name, value WAS the count.
                migrated[key] = {"name": key, "count": int(value)}
        return migrated

    def _save(self):
        try:
            tmp = self._path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp, self._path)
        except OSError:
            pass  # persistence is best-effort -- in-memory counts stay correct regardless

    def record_win(self, identity_key: str, display_name: str, game_id: str) -> bool:
        """Increment `identity_key`'s win count (creating it, remembering
        `display_name` for display, if this is its first win), unless
        `game_id` has already been recorded (exactly-once guard -- see
        class docstring). Returns True if this call actually
        incremented anything.

        `identity_key` is "{platform}:{external_id}" for a connection
        that had one, or `display_name` itself otherwise -- see this
        module's docstring for what that does and doesn't guarantee.
        `display_name` is stored separately and refreshed on every win
        so a later name change shows up on the leaderboard without
        losing win history tied to the stable key.
        """
        if not identity_key or not display_name or not game_id:
            return False
        recorded = self._data['recorded_game_ids']
        if game_id in recorded:
            return False
        recorded.append(game_id)
        if len(recorded) > MAX_RECORDED_GAME_IDS:
            del recorded[: len(recorded) - MAX_RECORDED_GAME_IDS]
        wins = self._data['wins']
        entry = wins.get(identity_key)
        if not isinstance(entry, dict):
            entry = {"name": display_name, "count": 0}
        entry["name"] = display_name
        entry["count"] = entry.get("count", 0) + 1
        wins[identity_key] = entry
        self._save()
        return True

    def _ranked(self) -> List[Tuple[str, str, int]]:
        # (identity_key, display_name, count), ties broken alphabetically
        # by display name (case-insensitive) so top() and rank_for()
        # always agree on ordering.
        items = [(key, entry["name"], entry["count"]) for key, entry in self._data['wins'].items()]
        return sorted(items, key=lambda t: (-t[2], t[1].lower()))

    def top(self, n: int = 20) -> List[Tuple[str, int]]:
        """(display_name, count) pairs -- unchanged external shape, so
        every existing caller (server/kadi_server.py's 'get_leaderboard'
        handling) needs no changes even though entries are now keyed
        internally by identity_key rather than name."""
        return [(name, count) for _key, name, count in self._ranked()[:max(1, n)]]

    def rank_for(self, identity_key: str) -> Optional[Tuple[int, int]]:
        """(1-based rank, win count) for `identity_key`, or None if it
        has no recorded wins yet. Callers now pass the same
        identity_key record_win() was given -- see
        server/kadi_server.py's 'get_my_rank' handling -- not a raw
        display name, since two different people can share a display
        name but never a real identity_key."""
        for i, (key, _name, count) in enumerate(self._ranked(), start=1):
            if key == identity_key:
                return i, count
        return None

