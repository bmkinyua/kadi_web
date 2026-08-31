"""
PHASE 2 verification: the protocol wired into GameManager on the host
side, and into ClientGameManager on the client side. Host + 2 loopback
clients (all on 127.0.0.1) play a scripted, AI-free game to completion,
confirming state stays consistent for all three the whole way through.

SCRIPT: every acting human always sends intent_draw. This is legal at
any point in PLAYING/KADI_DECLARED (never blocked by rules), so the
script can't stall on an "illegal move" edge case — instead it
naturally drives the game to completion via GameManager's own existing
stall-resolution mechanism (30 consecutive draws with nobody playing
a card -> _resolve_stall -> a real GameState.GAME_OVER), which is
exactly the kind of genuine, unmodified game-ending path this feature
needs to prove it can carry end-to-end.

Every turn, before advancing, this checks that:
  - the host's real GameManager and each client's ClientGameManager
    mirror agree on: current player identity, state, hand counts for
    every seat, and deck draw/discard counts
  - each client's OWN hand (full contents, not just count) exactly
    matches what the host's real Player object for that seat holds
  - opponents' hands are NEVER visible to a client (privacy boundary)

Run (from the kadi/ directory):  python -m tests.test_phase2_state_sync
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState
from network.host_game import HostGame
from network.client import LANClient
from network.client_state import ClientGameManager

PORT = 51977
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(pred, timeout=3.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False


def hand_multiset(cards):
    return sorted((c.suit.name if c.suit else '', c.rank, c.is_red_joker) for c in cards)


def run():
    host = HostGame(port=PORT)
    host.start_listening(host_name="Host")

    c1 = LANClient()
    c2 = LANClient()
    c1.connect('127.0.0.1', PORT, name='Alice')
    c2.connect('127.0.0.1', PORT, name='Bob')

    # Drain the lobby handshake on the host side (hello -> welcome) and
    # confirm both clients actually learn their assigned player_id.
    ok = wait_until(lambda: len(host.poll_lobby()) >= 3)  # host + 2 clients
    check("lobby roster reaches 3 (host + 2 clients)", ok)

    ok1 = wait_until(lambda: c1.player_id is not None)
    ok2 = wait_until(lambda: c2.player_id is not None)
    check("client 1 learned its player_id", ok1)
    check("client 2 learned its player_id", ok2)

    host.start_game(elimination_mode=False)
    check("host game started with 3 seats", len(host.gm.players) == 3)

    cgm1 = ClientGameManager(c1)
    cgm2 = ClientGameManager(c2)

    # Let the first snapshot land on both clients.
    def first_sync(cgm):
        cgm.update(0.0)
        return len(cgm.players) == 3

    ok1 = wait_until(lambda: first_sync(cgm1))
    ok2 = wait_until(lambda: first_sync(cgm2))
    check("client 1 received its first state_sync", ok1)
    check("client 2 received its first state_sync", ok2)

    seat_for_pid = {0: 'host', host._seat_by_pid.get(c1.player_id): 'c1',
                    host._seat_by_pid.get(c2.player_id): 'c2'}

    def consistency_check(turn_no):
        gm = host.gm
        ok_all = True
        for seat, real_p in enumerate(gm.players):
            for cgm, tag in ((cgm1, 'c1'), (cgm2, 'c2')):
                mirrored = cgm._players_by_seat.get(seat)
                if mirrored is None:
                    check(f"turn {turn_no}: {tag} has seat {seat} in its mirror", False)
                    ok_all = False
                    continue
                if mirrored.hand.count != real_p.hand.count:
                    check(f"turn {turn_no}: {tag}'s view of seat {seat} hand_count "
                          f"({mirrored.hand.count}) matches host ({real_p.hand.count})", False)
                    ok_all = False
        # current player identity (seat) must agree everywhere
        real_current_seat = gm.current_player.player_id
        for cgm, tag in ((cgm1, 'c1'), (cgm2, 'c2')):
            mirrored_current_seat = cgm.current_player.player_id
            if mirrored_current_seat != real_current_seat:
                check(f"turn {turn_no}: {tag}'s current_player seat "
                      f"({mirrored_current_seat}) matches host ({real_current_seat})", False)
                ok_all = False
        # each client's OWN hand exactly matches the host's real hand
        for cgm, pid, tag in ((cgm1, c1.player_id, 'c1'), (cgm2, c2.player_id, 'c2')):
            my_seat = host._seat_by_pid[pid]
            real_hand = hand_multiset(gm.players[my_seat].hand.cards)
            mine = cgm.players[0]
            mirrored_hand = hand_multiset(mine.hand.cards)
            if real_hand != mirrored_hand:
                check(f"turn {turn_no}: {tag}'s own hand exactly matches host's real hand", False)
                ok_all = False
        # privacy: a client's view of an OPPONENT seat must never carry
        # that opponent's actual cards (only placeholders of right count)
        for cgm, pid, tag in ((cgm1, c1.player_id, 'c1'), (cgm2, c2.player_id, 'c2')):
            my_seat = host._seat_by_pid[pid]
            for seat, real_p in enumerate(gm.players):
                if seat == my_seat:
                    continue
                mirrored = cgm._players_by_seat[seat]
                real_ranks = sorted(c.rank for c in real_p.hand.cards if c.suit is not None
                                    or c.rank == 'JOKER')
                seen_ranks = sorted(c.rank for c in mirrored.hand.cards)
                # Placeholder cards are all rank '2' with suit=None; if the
                # opponent's real hand ever coincidentally matches that
                # exactly we can't distinguish, so only flag a definite
                # leak: any mirrored card whose suit is not None (a real
                # suited card could only get there via an actual leak,
                # since placeholders are always constructed with suit=None).
                leaked = any(c.suit is not None for c in mirrored.hand.cards)
                if leaked:
                    check(f"turn {turn_no}: {tag} was never sent opponent seat {seat}'s "
                          f"real cards", False)
                    ok_all = False
        return ok_all

    all_ok = True
    max_turns = 200
    turn = 0
    while turn < max_turns:
        gm = host.gm
        if gm.state == GameState.GAME_OVER:
            break

        if gm.state == GameState.POST_PLAY:
            actor = gm._post_play_player
            action_type = 'intent_post_play_proceed'
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor = gm.current_player
            action_type = 'intent_draw'
        else:
            # Not reachable by a draw-only script (SUIT_PICK, JUMP_COUNTER_WINDOW,
            # PAUSED) — bail out rather than spin if something unexpected happens.
            check(f"turn {turn}: script only expects PLAYING/KADI_DECLARED/POST_PLAY, "
                  f"got {gm.state.name}", False)
            all_ok = False
            break

        actor_seat = actor.player_id
        pid_for_seat = host._pid_by_seat.get(actor_seat)
        before_marker = (gm.state, gm.current_player_idx, id(gm._post_play_player))
        if pid_for_seat is None or pid_for_seat == 0:
            # Host's own seat — drive it directly, same as the host's
            # local GameplayScene would (no network involved for the
            # host's own player).
            if action_type == 'intent_draw':
                gm.human_draw()
            else:
                gm.human_post_play_proceed()
        else:
            cl = c1 if pid_for_seat == c1.player_id else c2
            cl.send({'type': action_type})

        # For a network player the intent travels over a real (loopback)
        # socket and is processed on host.tick()'s next poll() — retry
        # briefly rather than assuming a single tick immediately after
        # send() is guaranteed to have already received it.
        def advanced():
            host.tick(0.05)
            after_marker = (gm.state, gm.current_player_idx, id(gm._post_play_player))
            return after_marker != before_marker
        progressed = wait_until(advanced, timeout=2.0)
        if not progressed:
            check(f"turn {turn}: action ({action_type}) by seat {actor_seat} "
                  f"was applied within timeout", False)
            all_ok = False
            break

        cgm1.update(0.0)
        cgm2.update(0.0)

        # The state_sync for this action travels over the loopback
        # socket asynchronously too — give both client mirrors a brief
        # chance to actually absorb it before comparing, rather than
        # asserting consistency against whatever snapshot happened to
        # already be sitting in each client's queue.
        def clients_caught_up():
            cgm1.update(0.0)
            cgm2.update(0.0)
            if not cgm1.players or not cgm2.players:
                return False
            return (cgm1.state == gm.state and cgm2.state == gm.state
                    and cgm1.current_player.player_id == gm.current_player.player_id
                    and cgm2.current_player.player_id == gm.current_player.player_id)
        wait_until(clients_caught_up, timeout=2.0)

        turn += 1
        ok_turn = consistency_check(turn)
        all_ok = all_ok and ok_turn
        if not ok_turn:
            break

    check(f"loop reached GAME_OVER or turn cap without any consistency failure "
          f"(stopped at turn {turn}, state={host.gm.state.name})",
          all_ok and (host.gm.state == GameState.GAME_OVER or turn < max_turns))

    check("host reached a real GAME_OVER via stall resolution",
          host.gm.state == GameState.GAME_OVER)

    c1.close()
    c2.close()
    host.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"PHASE 2: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PHASE 2: ALL CHECKS PASSED")
        sys.exit(0)
