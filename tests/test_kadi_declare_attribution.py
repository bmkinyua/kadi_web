"""
Bugfix verification: core/game_manager.py increments the aggregate
self._g_kadi_declarations at THREE call sites, but only ONE of them
(_finish_play, the declare-while-playing path) also updated the new
per-player self._g_by_player tally that network/game_summary.py's
per-recipient attribution reads. The other two --
human_declare_kadi() (declare-BEFORE-playing) and
human_post_play_declare_kadi() (the POST_PLAY confirm-KADI path) --
silently left that player's own game_summary.kadi_declarations at 0.

tests/test_game_summary.py's own game-loop helper only ever sends
intent_draw -- it never exercises any of the three real KADI-declare
paths, so it could not have caught this and must not be trusted to
cover it. This file drives a real 2-human game (real KadiServer, real
LANClient connections, real server/game_room.py intent routing) and
exercises each of the three declare-KADI paths in turn via the exact
same wire intents server/game_room.py's handle_intent() routes them
through, matching each one to its GameManager call site:

  intent_declare_kadi            -> human_declare_kadi()            (site 1, was broken)
  intent_play (declare_kadi=True) -> _finish_play                   (site 2, reference/already correct)
  intent_post_play_declare_kadi  -> human_post_play_declare_kadi()  (site 3, was broken)

Hand/state setup between scenarios is deliberately white-box (directly
manipulating room.gm.players[...]/rule_engine, same established
pattern as tests/test_cardless_pickup_debt.py) rather than dealt from
a real shuffled deck -- reaching each of these three specific
game-state preconditions (KADI-eligible hand, POST_PLAY with
_post_play_can_kadi set, etc.) via genuinely random play would be
unreliable to engineer deterministically and isn't needed to isolate
this bug: what's under test is whether the DECLARE ACTION, routed
through the real server intent handler, updates the per-player tally
-- not whether a real shuffle can produce a KADI-eligible hand (a
separate, already-covered concern).

Verified at two levels for each site, both real, neither faked:
  1. room.gm._g_by_player[seat]['kadi_declarations'] -- the exact
     data structure the bug lived in.
  2. room.game_summary_for(conn_id)['kadi_declarations'] -- the
     ACTUAL wire payload a real client would receive, built through
     the real network/game_summary.py code path (not hand-copied from
     #1 -- this catches a bug in build_game_summary_for() itself, not
     just in game_manager.py). Called directly rather than only after
     a driven-to-completion GAME_OVER, since the two OTHER
     game_summary fields that genuinely need GAME_OVER to be final
     (won, finish_kind) aren't what this file is testing -- a
     deliberate, stated scope narrowing, not an oversight.

Run (from the kadi/ directory):  python -m tests.test_kadi_declare_attribution
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState, Suit
from models.card import Card
from network.client import LANClient
from server.kadi_server import KadiServer

PORT = 52098
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    import time
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def drain_for(server, client, type_name, timeout=2.0):
    got = {}
    def pred():
        for m in client.poll():
            if m.get('type') == type_name:
                got['msg'] = m
        return 'msg' in got
    ok = wait_until(server, pred, timeout=timeout)
    return got.get('msg') if ok else None


def start_two_human_game():
    """Real server, real 2-human room, started but deliberately NOT
    driven toward GAME_OVER -- each scenario below takes over from
    here with its own controlled hand/state."""
    server = KadiServer(port=PORT)
    server.start()
    host = LANClient()
    c1 = LANClient()
    host.connect('127.0.0.1', PORT, name='Alice')
    c1.connect('127.0.0.1', PORT, name='Bob')
    server.tick(0.02)

    host.send({'type': 'create_game', 'settings': {'elimination_mode': False}})
    welcome = drain_for(server, host, 'welcome')
    check("host created the game", welcome is not None)
    game_id = welcome['game_id']

    c1.send({'type': 'join_game', 'game_id': game_id})
    w1 = drain_for(server, c1, 'welcome')
    check("client 1 joined", w1 is not None)

    room = server.lobby.get(game_id)
    host.send({'type': 'request_start_game'})
    started = wait_until(server, lambda: room.started, timeout=3.0)
    check("game started", started)

    return server, host, c1, room


def give_kadi_eligible_hand(gm, player):
    """A 2-card, same-rank, all-FINISHING-type hand is the simplest
    shape order_for_closing()/can_declare_kadi() accepts (see
    core/rule_engine.py's own docstring on that shape) -- suit doesn't
    matter for it. Also clears the top card to None so is_playable()
    is unconditionally True (RuleEngine.is_playable's own top-is-None
    short-circuit) -- removes any suit/rank-matching engineering from
    every scenario below; only the KADI-declare shape itself is what's
    under test here."""
    player.hand.remove(list(player.hand.cards))
    player.hand.add([Card(suit=Suit.SPADES, rank='5'), Card(suit=Suit.LOVE, rank='5')])
    gm.rule_engine._top_card = None
    gm.rule_engine.pickup_pending = 0


def reset_declare_state(gm, player):
    player.has_declared_kadi = False
    gm.declared_kadi_player = None


def seats(room):
    seat_by_conn = room._seat_by_conn
    conn_by_seat = {seat: conn for conn, seat in seat_by_conn.items()}
    return seat_by_conn, conn_by_seat


def run():
    server, host, c1, room = start_two_human_game()
    gm = room.gm
    seat_by_conn, conn_by_seat = seats(room)
    host_seat = seat_by_conn[host.player_id]
    c1_seat = seat_by_conn[c1.player_id]
    player = gm.players[host_seat]

    # ── Site 1: human_declare_kadi() via intent_declare_kadi ───────────────
    print("\n-- Site 1: declare-before-playing (human_declare_kadi) --")
    gm.state = GameState.PLAYING
    gm.current_player_idx = host_seat
    give_kadi_eligible_hand(gm, player)
    reset_declare_state(gm, player)

    host.send({'type': 'intent_declare_kadi'})
    wait_until(server, lambda: player.has_declared_kadi, timeout=1.0)

    check("site 1: the declaration actually registered (has_declared_kadi)",
          player.has_declared_kadi)
    check("site 1: per-player tally shows exactly 1 kadi_declarations",
          gm._g_by_player.get(host_seat, {}).get('kadi_declarations') == 1)
    site1_summary = room.game_summary_for(conn_by_seat[host_seat])
    check("site 1: the real game_summary payload reflects it (kadi_declarations == 1)",
          site1_summary is not None and site1_summary['kadi_declarations'] == 1)
    other_summary = room.game_summary_for(conn_by_seat[c1_seat])
    check("site 1: the OTHER seated player's own game_summary is untouched (still 0)",
          other_summary is not None and other_summary['kadi_declarations'] == 0)

    # ── Site 2 (reference, already correct): _finish_play via
    #    intent_play(declare_kadi=True) ─────────────────────────────────────
    # NOTE: declare_kadi at PLAY time means "my REMAINING hand after this
    # play is still closeable" (see core/game_manager.py's _do_play: it
    # checks can_declare_kadi() on what's left AFTER removing the played
    # cards) -- not "this play finishes the game" (an empty remaining
    # hand fails that same check, can_declare_kadi's own docstring/
    # order_for_closing short-circuit on an empty card list). So this
    # scenario needs a 4-card hand: play 2 of them (a normal same-rank
    # set), leaving the other 2 (also same-rank) as the still-closeable
    # remainder -- unlike sites 1/3's simpler 2-card "whole hand is
    # already closeable" shape.
    print("\n-- Site 2: declare-while-playing (_finish_play) — reference/regression check --")
    gm.state = GameState.PLAYING
    gm.current_player_idx = host_seat
    player.hand.remove(list(player.hand.cards))
    player.hand.add([
        Card(suit=Suit.SPADES, rank='5'), Card(suit=Suit.LOVE, rank='5'),
        Card(suit=Suit.SPADES, rank='6'), Card(suit=Suit.LOVE, rank='6'),
    ])
    gm.rule_engine._top_card = None
    gm.rule_engine.pickup_pending = 0
    reset_declare_state(gm, player)

    host.send({
        'type': 'intent_play',
        'cards': [
            {'suit': 'SPADES', 'rank': '5', 'is_red_joker': False},
            {'suit': 'LOVE', 'rank': '5', 'is_red_joker': False},
        ],
        'declare_kadi': True,
    })
    wait_until(server, lambda: player.has_declared_kadi, timeout=1.0)

    check("site 2: the declaration actually registered (has_declared_kadi)",
          player.has_declared_kadi)
    check("site 2: per-player tally is exactly 2 (1 from site 1 above + 1 here — "
          "cumulative across real declares, matching the lifetime-counter model)",
          gm._g_by_player.get(host_seat, {}).get('kadi_declarations') == 2)
    check("site 2: NOT 3 or more — confirms this single call site's aggregate/"
          "per-player pair still increments exactly once each, no double-count",
          gm._g_by_player.get(host_seat, {}).get('kadi_declarations') != 3)
    site2_summary = room.game_summary_for(conn_by_seat[host_seat])
    check("site 2: the real game_summary payload reflects the running total (== 2)",
          site2_summary is not None and site2_summary['kadi_declarations'] == 2)

    # ── Site 3: human_post_play_declare_kadi() via
    #    intent_post_play_declare_kadi ─────────────────────────────────────
    print("\n-- Site 3: POST_PLAY confirm-KADI (human_post_play_declare_kadi) --")
    give_kadi_eligible_hand(gm, player)
    reset_declare_state(gm, player)
    gm.state = GameState.POST_PLAY
    gm._post_play_player = player
    gm._post_play_can_kadi = True

    host.send({'type': 'intent_post_play_declare_kadi'})
    wait_until(server, lambda: player.has_declared_kadi, timeout=1.0)

    check("site 3: the declaration actually registered (has_declared_kadi)",
          player.has_declared_kadi)
    check("site 3: per-player tally is exactly 3 (2 from sites 1+2 above + 1 here)",
          gm._g_by_player.get(host_seat, {}).get('kadi_declarations') == 3)
    site3_summary = room.game_summary_for(conn_by_seat[host_seat])
    check("site 3: the real game_summary payload reflects the running total (== 3)",
          site3_summary is not None and site3_summary['kadi_declarations'] == 3)

    # Whole-run sanity: the OTHER player's own attribution was never
    # touched by any of host's three declarations across this run —
    # re-checks the ORIGINAL per-player-attribution fix (from the prior
    # delivery) still holds after this bugfix, not just this bug's own
    # three sites in isolation.
    final_other = room.game_summary_for(conn_by_seat[c1_seat])
    check("whole run: the other player's own kadi_declarations is still 0 "
          "(host's declares never leaked onto their profile)",
          final_other is not None and final_other['kadi_declarations'] == 0)

    server.stop()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All KADI-declare per-player attribution checks passed (all 3 sites).")


if __name__ == '__main__':
    run()
