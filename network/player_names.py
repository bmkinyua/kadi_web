"""
KADI - shared, pygame-free helper for disambiguating player names.

Used by both network/host_game.HostGame.start_game() (LAN) and
server/game_room.GameRoom.start_game() (Internet) right before handing
the final player_configs to GameManager.new_game() — the single place
in each path where the complete roster (every human's chosen name,
plus any AI-fill names) is actually assembled, and therefore the only
place that can reliably see the WHOLE set of names at once to spot a
collision. Individual entry screens (scenes.LANJoinScene,
scenes.InternetMenuScene, etc.) each only know their own local
player's name in isolation — they have no way to know whether some
other joining player left theirs at the same unchanged default too.

Concretely: two+ human players who both leave the name field at its
default ("Player") would otherwise show up identically in the roster,
the turn indicator, the settings panel, etc., with no way to tell them
apart — exactly the confusion a field report flagged (both players'
screens simply said "Player" and "Player's turn" with nothing to
distinguish them).
"""
from __future__ import annotations
from typing import List


def disambiguate_names(names: List[str]) -> List[str]:
    """Given names in seat order, appends " 1", " 2", ... to every
    occurrence of any name that appears more than once (case-sensitive,
    exact match only — "Player" and "player" are treated as distinct
    and left alone). Names that are already unique are returned
    untouched. Order and length of the input list are preserved."""
    counts: dict = {}
    for n in names:
        counts[n] = counts.get(n, 0) + 1

    seen: dict = {}
    out = []
    for n in names:
        if counts[n] <= 1:
            out.append(n)
            continue
        seen[n] = seen.get(n, 0) + 1
        out.append(f"{n} {seen[n]}")
    return out
