"""
KADI - Internet multiplayer: end-of-game stat/badge disclosure.

Builds the ONE-TIME 'game_summary' message sent to each human
recipient the instant their room's authoritative GameManager reaches
GAME_OVER (see server/kadi_server.py's tick(), the one call site).
Deliberately separate from network/state_sync.py's per-tick
'state_sync' (see KADI_web_port_implementation_plan.md §9's
"Explicitly NOT wired this pass" note this closes) -- this fires
exactly once per finished game, carries data state_sync never has
(the raw inputs core/profile_store.check_badges_after_game() needs),
and is never redacted per-recipient the way state_sync's hand
contents are, since every field here is either public-at-GAME_OVER
information or the recipient's own personal tally.

PER-PLAYER ATTRIBUTION (the one real gap found while building this):
core.game_manager.GameManager's pre-existing self._g_* counters
(cards_played, aces_played, ...) are a SINGLE aggregate across every
is_human player in the game -- correct for the PC's one-human-per-
device assumption (see GameManager._reset_game_trackers's own
docstring), wrong here, where one GameManager is authoritative for
potentially several humans on separate devices with separate
profiles. This module reads GameManager._g_by_player (the per-
player_id breakdown added alongside those aggregates for exactly this
purpose) instead of the aggregate scalars, so each recipient's
game_summary only ever carries THEIR OWN contribution -- never
another seated human's.

jump_counter_depth is the one exception, kept as a single game-level
value (GameManager._g_jump_chain_depth_max) rather than per-player --
a Jump-counter chain is extended by whichever players choose to
counter it, not owned by any one of them, matching how the "Jump
Master" badge already reads it as a property of the ROUND rather than
of a particular player's own actions (see
core/profile_store.py's check_badges_after_game).

undo_used_this_game is always False from this module: undo is
deliberately never exposed over the network (see
server/game_room.py's handle_intent() comment) -- carried in the wire
shape anyway for schema parity with the PC/LAN inputs to
check_badges_after_game, not hardcoded out, in case that ever changes.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from core.game_manager import classify_finish_kind

# Same defaulting purpose as GameManager._player_tally()'s own lazily-
# created dict -- a recipient who (in theory) never triggered a single
# tracked action this game reads back all-zero/False here rather than
# a KeyError, without needing GameManager to pre-populate an entry for
# every seat up front.
_EMPTY_TALLY: Dict[str, Any] = {
    'cards_played': 0, 'cards_drawn': 0, 'biggest_pickup_absorbed': 0,
    'kadi_declarations': 0, 'aces_played': 0, 'jump_skips_dealt': 0,
    'kickback_reversals': 0, 'ace_shield_uses': 0, 'ace_shield_biggest': 0,
    'near_kadi_count': 0, 'undo_used': False,
    'bluff_attempted': False, 'kuficha_trap_attempted': False,
}


def build_game_summary_for(gm, recipient_id: int, *, mode: str,
                            difficulty: Optional[str]) -> dict:
    """Build the 'game_summary' payload for `recipient_id` (a seat /
    player_id in `gm`). Only meaningful once gm.state == GAME_OVER
    (same precondition network/state_sync.build_snapshot_for documents
    for its own GAME_OVER case) -- _g_by_player/last_played_cards/
    winner are all final by then, not mid-game snapshots.

    `mode`/`difficulty` are supplied by the caller (see
    server/game_room.py's _mode_and_difficulty()) since GameManager
    itself has no "mode" concept -- mirroring how
    core.game_manager.finalize_profile_stats's own `mode` argument is
    always supplied by ITS caller (scenes.py) on the PC side, never
    inferred by GameManager itself there either.
    """
    winner = gm.winner
    won = bool(winner is not None and winner.player_id == recipient_id)

    finish_kind = None
    if won and gm.last_played_cards:
        finish_kind = classify_finish_kind(gm.last_played_cards)

    # Same "checks every seat including the recipient's own" shape as
    # core.game_manager.GameManager.finalize_profile_stats's identical
    # line -- harmless, since a human player's own msomi_model is
    # always None (only AIPlayer ever gets one set, see
    # server/game_room.py's start_game()).
    #
    # Sent RAW (NOT gated on `won`) deliberately -- matching
    # finalize_profile_stats, which increments
    # profile['msomi']['games_played_with_msomi'] off this same raw
    # value regardless of who won, and only gates it with `won` at
    # ITS OWN check_badges_after_game() call site, purely for the
    # 'beat_msomi' badge check. Gating it here would silently lose
    # the "opponent had MSOMI but I lost" case the client-side
    # games_played_with_msomi counter needs -- see profileData.ts's
    # applyGameSummary(), which re-derives the won-gated value itself,
    # only for that one badge check, the same split as the PC.
    opponent_had_msomi = any(
        getattr(p, 'msomi_model', None) is not None for p in gm.players
    )

    tally = dict(_EMPTY_TALLY)
    tally.update(gm._g_by_player.get(recipient_id, {}))

    return {
        'type': 'game_summary',
        'you': recipient_id,
        'won': won,
        'mode': mode,
        'difficulty': difficulty,
        'finish_kind': finish_kind,
        'opponent_had_msomi': bool(opponent_had_msomi),
        'elimination_mode': bool(gm.elimination_mode),
        'cards_played': tally['cards_played'],
        'cards_drawn': tally['cards_drawn'],
        'biggest_pickup_absorbed': tally['biggest_pickup_absorbed'],
        'kadi_declarations': tally['kadi_declarations'],
        'aces_played': tally['aces_played'],
        'jump_skips_dealt': tally['jump_skips_dealt'],
        'kickback_reversals': tally['kickback_reversals'],
        'ace_shield_uses': tally['ace_shield_uses'],
        'ace_shield_biggest': tally['ace_shield_biggest'],
        'jump_counter_depth': gm._g_jump_chain_depth_max,
        'near_kadi_count': tally['near_kadi_count'],
        'undo_used_this_game': bool(tally['undo_used']),
        'bluff_suit_win': bool(won and tally['bluff_attempted']),
        'kuficha_trap_win': bool(won and tally['kuficha_trap_attempted']),
    }
