"""
INTERNET MULTIPLAYER — PHASE 2 verification: game authority actually
moved onto the server (server/game_room.GameRoom driving a real
core.game_manager.GameManager), reusing the pattern established for
LAN. Server process (well -- a KadiServer instance ticked from this
test) + 2-3 client connections all play a full game to completion over
loopback, confirming every client only ever sees what it should --
including the room's CREATOR, who in this architecture is just another
thin client of the server, never a local GameManager owner the way a
LAN host is.

SCRIPT: identical strategy to tests/test_phase2_state_sync.py (LAN) --
every acting human always sends intent_draw, which is legal at any
point in PLAYING/KADI_DECLARED, so the game is driven to a genuine
GAME_OVER via GameManager's own existing stall-resolution mechanism (30
consecutive draws -> _resolve_stall), rather than needing a full
rules-aware bot.

Run (from the kadi/ directory):  python -m tests.test_internet_phase2_authority
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import GameState
from network.client import LANClient
from network.client_state import ClientGameManager
from server.kadi_server import KadiServer

PORT = 52095
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def hand_multiset(cards):
    return sorted((c.suit.name if c.suit else '', c.rank, c.is_red_joker) for c in cards)


def run():
    server = KadiServer(port=PORT)
    server.start()

    host = LANClient()
    c1 = LANClient()
    c2 = LANClient()
    host.connect('127.0.0.1', PORT, name='Alice')
    c1.connect('127.0.0.1', PORT, name='Bob')
    c2.connect('127.0.0.1', PORT, name='Carol')

    def drain_for(client, type_name, timeout=3.0):
        got = {}
        def pred():
            for m in client.poll():
                if m.get('type') == type_name:
                    got['msg'] = m
            return 'msg' in got
        ok = wait_until(server, pred, timeout=timeout)
        return got.get('msg') if ok else None

    server.tick(0.02)
    host.send({'type': 'create_game', 'settings': {'elimination_mode': False}})
    welcome = drain_for(host, 'welcome')
    check("host created the game", welcome is not None)
    game_id = welcome['game_id']

    c1.send({'type': 'join_game', 'game_id': game_id})
    w1 = drain_for(c1, 'welcome')
    check("client 1 joined", w1 is not None)
    c2.send({'type': 'join_game', 'game_id': game_id})
    w2 = drain_for(c2, 'welcome')
    check("client 2 joined", w2 is not None)

    room = server.lobby.get(game_id)
    check("server-side room has 3 members before start",
          room is not None and len(room.member_names) == 3)

    host.send({'type': 'request_start_game'})
    started = wait_until(server, lambda: room.started, timeout=3.0)
    check("host's request_start_game actually started the server-side GameManager", started)
    check("server GameManager has 3 seats", len(room.gm.players) == 3)

    cgm_host = ClientGameManager(host)
    cgm_c1 = ClientGameManager(c1)
    cgm_c2 = ClientGameManager(c2)

    def first_sync(cgm):
        cgm.update(0.0)
        return len(cgm.players) == 3

    ok_h = wait_until(server, lambda: first_sync(cgm_host))
    ok_1 = wait_until(server, lambda: first_sync(cgm_c1))
    ok_2 = wait_until(server, lambda: first_sync(cgm_c2))
    check("host (as a thin client, NOT a local GameManager owner) received its first "
          "state_sync", ok_h)
    check("client 1 received its first state_sync", ok_1)
    check("client 2 received its first state_sync", ok_2)

    seat_by_conn = room._seat_by_conn
    tag_for_seat = {seat_by_conn[host.player_id]: ('host', cgm_host, host),
                   seat_by_conn[c1.player_id]: ('c1', cgm_c1, c1),
                   seat_by_conn[c2.player_id]: ('c2', cgm_c2, c2)}

    def consistency_check(turn_no):
        gm = room.gm
        ok_all = True
        for seat, real_p in enumerate(gm.players):
            for tag, cgm, _ in tag_for_seat.values():
                mirrored = cgm._players_by_seat.get(seat)
                if mirrored is None or mirrored.hand.count != real_p.hand.count:
                    check(f"turn {turn_no}: {tag}'s view of seat {seat} hand_count matches "
                          f"server", False)
                    ok_all = False

        real_current_seat = gm.current_player.player_id
        for tag, cgm, _ in tag_for_seat.values():
            if cgm.current_player.player_id != real_current_seat:
                check(f"turn {turn_no}: {tag}'s current_player seat matches server", False)
                ok_all = False

        for seat, (tag, cgm, client) in tag_for_seat.items():
            real_hand = hand_multiset(gm.players[seat].hand.cards)
            mirrored_hand = hand_multiset(cgm.players[0].hand.cards)
            if real_hand != mirrored_hand:
                check(f"turn {turn_no}: {tag}'s own hand exactly matches server's real hand",
                      False)
                ok_all = False

        # privacy: no client's mirror of an OPPONENT seat may ever
        # carry that opponent's real suited cards (placeholders only).
        for seat, (tag, cgm, client) in tag_for_seat.items():
            for other_seat in range(len(gm.players)):
                if other_seat == seat:
                    continue
                mirrored = cgm._players_by_seat.get(other_seat)
                if mirrored is None:
                    continue
                leaked = any(c.suit is not None for c in mirrored.hand.cards)
                if leaked:
                    check(f"turn {turn_no}: {tag} was never sent opponent seat "
                          f"{other_seat}'s real cards", False)
                    ok_all = False
        return ok_all

    all_ok = True
    max_turns = 200
    turn = 0
    gm = room.gm
    while turn < max_turns:
        if gm.state == GameState.GAME_OVER:
            break
        if gm.state == GameState.POST_PLAY:
            actor = gm._post_play_player
            action_type = 'intent_post_play_proceed'
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor = gm.current_player
            action_type = 'intent_draw'
        else:
            check(f"turn {turn}: script only expects PLAYING/KADI_DECLARED/POST_PLAY, "
                  f"got {gm.state.name}", False)
            all_ok = False
            break

        actor_seat = actor.player_id
        _, _, actor_client = tag_for_seat[actor_seat]
        before_marker = (gm.state, gm.current_player_idx, id(gm._post_play_player))
        actor_client.send({'type': action_type})

        def advanced():
            after_marker = (gm.state, gm.current_player_idx, id(gm._post_play_player))
            return after_marker != before_marker
        progressed = wait_until(server, advanced, timeout=2.0)
        if not progressed:
            check(f"turn {turn}: action ({action_type}) by seat {actor_seat} was applied "
                  f"within timeout", False)
            all_ok = False
            break

        def clients_caught_up():
            for tag, cgm, _ in tag_for_seat.values():
                cgm.update(0.0)
            if not all(cgm.players for _, cgm, _ in tag_for_seat.values()):
                return False
            return all(cgm.state == gm.state
                      and cgm.current_player.player_id == gm.current_player.player_id
                      for _, cgm, _ in tag_for_seat.values())
        wait_until(server, clients_caught_up, timeout=2.0)

        turn += 1
        ok_turn = consistency_check(turn)
        all_ok = all_ok and ok_turn
        if not ok_turn:
            break

    check(f"loop reached GAME_OVER or turn cap without any consistency failure "
          f"(stopped at turn {turn}, state={gm.state.name})",
          all_ok and (gm.state == GameState.GAME_OVER or turn < max_turns))
    check("server-authoritative game reached a real GAME_OVER via stall resolution",
          gm.state == GameState.GAME_OVER)

    host.close()
    c1.close()
    c2.close()
    server.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET PHASE 2: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET PHASE 2: ALL CHECKS PASSED")
        sys.exit(0)
