"""
Regression test for a real crash report: finishing an Internet
Multiplayer game as either participant (or a LAN Multiplayer game as
the JOINING player) crashed with:

    AttributeError: 'ClientGameManager' object has no attribute 'profile'

...raised from GameplayScene._record_profile_stats() when the win
screen tried to update the local player's profile stats.

Root cause: network.client_state.ClientGameManager never defines a
.profile attribute at all (unlike the real GameManager, which always
has one, possibly None). _record_profile_stats' old guard
(`if self.gm.profile is None: return`) assumed the attribute always at
least existed. For network_role == 'client' — which is BOTH
participants in Internet Multiplayer, and the JOINING player in LAN
Multiplayer (only the LAN host keeps the real GameManager as self.gm;
see GameplayScene.on_enter's own comment) — self.gm IS a
ClientGameManager, so the plain attribute access raised instead of
returning None.

This is exactly why the existing tests/test_internet_phase3_scenes_smoke.py
never caught this: it deliberately caps play at 40 turns as a quick
smoke test and never actually drives the game to GAME_OVER, so the win
screen / _record_profile_stats code path was never exercised there.
This test reuses that same real client-server scaffolding but plays
until the game genuinely finishes, on BOTH the Internet Multiplayer
path and the LAN Multiplayer path (joining player specifically, since
that's the one that goes through ClientGameManager).

Run (from the kadi/ directory):  python -m tests.test_network_client_win_profile_stats
"""
from __future__ import annotations
import os
import sys
import time
import shutil

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from constants import GameState
from core.game_manager import GameManager
from core import profile_store
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import (
    SceneManager, GameplayScene, InternetMenuScene, InternetLobbyScene, MainMenuScene,
    LANHostLobbyScene, LANJoinScene,
)
from server.kadi_server import KadiServer

PORT = 52098
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(tick_fn, pred, timeout=5.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        tick_fn()
        if pred():
            return True
        time.sleep(interval)
    return False


def make_app(screen, assets, board, anim):
    gm = GameManager()
    gm.profile = profile_store.default_profile()
    sm = SceneManager(screen, assets)
    sm.gm = gm
    sm.singleplayer_gm = gm
    sm.board = board
    sm.anim = anim
    sm.make_screen = lambda *a, **kw: screen
    sm.register('main_menu', MainMenuScene(sm))
    sm.register('gameplay', GameplayScene(sm))
    sm.register('internet_menu', InternetMenuScene(sm))
    sm.register('internet_lobby', InternetLobbyScene(sm))
    sm.register('lan_host', LANHostLobbyScene(sm))
    sm.register('lan_join', LANJoinScene(sm))
    return sm


def play_to_game_over(host_gp, client_gp, gm_ref, room, tick_fn, max_turns=400):
    turns = 0
    while turns < max_turns and gm_ref.state != GameState.GAME_OVER:
        if gm_ref.state == GameState.POST_PLAY:
            actor_seat = gm_ref._post_play_player.player_id
        elif gm_ref.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor_seat = gm_ref.current_player.player_id
        else:
            break
        actor_conn_id = room._conn_by_seat.get(actor_seat)
        acting_gp = host_gp if actor_conn_id == host_gp._client_gm.client.player_id else client_gp

        before = (gm_ref.state, gm_ref.current_player_idx, id(gm_ref._post_play_player))
        if gm_ref.state == GameState.POST_PLAY:
            acting_gp._action_kadi_no()
        else:
            acting_gp._action_draw()

        def progressed():
            tick_fn()
            return (gm_ref.state, gm_ref.current_player_idx,
                    id(gm_ref._post_play_player)) != before
        wait_until(tick_fn, progressed, timeout=2.0)
        turns += 1
    return turns


def run_internet():
    print("--- Internet Multiplayer: play a real game to GAME_OVER ---")
    server = KadiServer(port=PORT)
    server.start()

    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    def tick():
        server.tick(0.02)
        sm_host.update(0.05)
        sm_client.update(0.05)

    sm_host.switch('internet_menu')
    menu = sm_host._scenes['internet_menu']
    menu._player_name = "Alice"
    menu._addr_text = f"127.0.0.1:{PORT}"
    menu._start_connect()
    wait_until(tick, lambda: sm_host._current_name == 'internet_lobby')

    lobby_host = sm_host._scenes['internet_lobby']
    lobby_host._elimination_mode = False
    lobby_host._create_game()
    wait_until(tick, lambda: lobby_host._state == 'lobby' and lobby_host._host_id is not None)
    game_id = lobby_host._game_id

    sm_client.switch('internet_menu')
    menu_c = sm_client._scenes['internet_menu']
    menu_c._player_name = "Bob"
    menu_c._addr_text = f"127.0.0.1:{PORT}"
    menu_c._start_connect()
    wait_until(tick, lambda: sm_client._current_name == 'internet_lobby')

    lobby_client = sm_client._scenes['internet_lobby']
    wait_until(tick, lambda: any(g['game_id'] == game_id for g in lobby_client._games))
    lobby_client._join_game(game_id)
    wait_until(tick, lambda: lobby_client._state == 'lobby' and len(lobby_host._lobby_roster) >= 2)

    lobby_host._request_start()
    wait_until(tick, lambda: sm_host._current_name == 'gameplay')
    wait_until(tick, lambda: sm_client._current_name == 'gameplay')
    host_gp = sm_host._scenes['gameplay']
    client_gp = sm_client._scenes['gameplay']
    check("both sides reached gameplay as network_role='client' (Internet has no "
          "local-host special case)",
          host_gp._network_role == 'client' and client_gp._network_role == 'client')

    room = server.lobby.get(game_id)
    gm_ref = room.gm
    turns = play_to_game_over(host_gp, client_gp, gm_ref, room, tick)
    check(f"game actually reached GAME_OVER (took {turns} turns)",
          gm_ref.state == GameState.GAME_OVER)

    if gm_ref.state != GameState.GAME_OVER:
        print("Aborting Internet portion — game didn't finish in time.")
        server.stop()
        return

    # This is the exact call site that used to crash — both sides.
    try:
        host_gp._record_profile_stats()
        host_ok = True
    except AttributeError as e:
        host_ok = False
        print(f"    host raised: {e}")
    check("host's _record_profile_stats() did not crash", host_ok)

    try:
        client_gp._record_profile_stats()
        client_ok = True
    except AttributeError as e:
        client_ok = False
        print(f"    client raised: {e}")
    check("client's _record_profile_stats() did not crash "
          "(THE BUG — used to raise AttributeError here)", client_ok)

    if client_ok:
        client_profile = sm_client.singleplayer_gm.profile
        check("client's own local profile recorded an Internet game played",
              client_profile['games_played']['internet'] == 1)
        winner_conn_id = None
        if gm_ref.winner is not None:
            winner_seat = gm_ref.winner.player_id
            winner_conn_id = room._conn_by_seat.get(winner_seat)
        client_won = (winner_conn_id == client_gp._client_gm.client.player_id)
        expected_wins = 1 if client_won else 0
        check(f"client's recorded win count matches the actual outcome "
              f"(client {'won' if client_won else 'lost'})",
              client_profile['games_won']['internet'] == expected_wins)

    if host_ok:
        host_profile = sm_host.singleplayer_gm.profile
        check("host's own local profile also recorded an Internet game played",
              host_profile['games_played']['internet'] == 1)

    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()
    server.stop()


def run_lan():
    print("--- LAN Multiplayer: play a real game to GAME_OVER (joining player) ---")
    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    def tick():
        sm_host.update(0.05)
        sm_client.update(0.05)

    # LANHostLobbyScene starts listening immediately in on_enter() —
    # there's no separate "start hosting" step to call.
    sm_host.switch('lan_host')
    host_lobby = sm_host._scenes['lan_host']
    check("LAN host is listening", host_lobby._host is not None and not host_lobby._error)
    if host_lobby._host is None:
        print("Aborting LAN portion — host failed to start listening.")
        return
    port = host_lobby._host.port

    sm_client.switch('lan_join')
    join_scene = sm_client._scenes['lan_join']
    join_scene._player_name = "Bob"
    join_scene._ip_text = f"127.0.0.1:{port}"
    join_scene._start_connect()
    ok = wait_until(tick, lambda: join_scene._state in ('lobby', 'starting'), timeout=5.0)
    check("LAN joiner connected", ok)

    ok = wait_until(tick, lambda: len(host_lobby._host.roster()) >= 2, timeout=5.0)
    check("host sees 2 players in its roster", ok)

    host_lobby._elimination_mode = False
    host_lobby._start_game()

    ok = wait_until(tick, lambda: sm_host._current_name == 'gameplay', timeout=5.0)
    check("LAN host reached gameplay", ok)
    ok = wait_until(tick, lambda: sm_client._current_name == 'gameplay', timeout=5.0)
    check("LAN joiner reached gameplay", ok)
    if sm_host._current_name != 'gameplay' or sm_client._current_name != 'gameplay':
        print("Aborting LAN portion — one side never reached gameplay.")
        return

    host_gp = sm_host._scenes['gameplay']
    client_gp = sm_client._scenes['gameplay']
    check("LAN host's GameplayScene is network_role='host' (the real GameManager)",
          host_gp._network_role == 'host')
    check("LAN joiner's GameplayScene is network_role='client' (a ClientGameManager "
          "— the exact case that crashed)", client_gp._network_role == 'client')

    gm_ref = sm_host.gm  # host's own manager.gm IS the authoritative GameManager
    turns = 0
    max_turns = 400
    while turns < max_turns and gm_ref.state != GameState.GAME_OVER:
        if gm_ref.state == GameState.POST_PLAY:
            actor = gm_ref._post_play_player
        elif gm_ref.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor = gm_ref.current_player
        else:
            break
        # Simplest correct rule for this 2-seat scaffold: seat 0 is
        # always the host (see HostGame.start_listening), everyone else
        # is the joining client.
        acting_gp = host_gp if gm_ref.players.index(actor) == 0 else client_gp

        before = (gm_ref.state, gm_ref.current_player_idx, id(gm_ref._post_play_player))
        if gm_ref.state == GameState.POST_PLAY:
            acting_gp._action_kadi_no()
        else:
            acting_gp._action_draw()

        def progressed():
            tick()
            return (gm_ref.state, gm_ref.current_player_idx,
                    id(gm_ref._post_play_player)) != before
        wait_until(tick, progressed, timeout=2.0)
        turns += 1

    check(f"LAN game actually reached GAME_OVER (took {turns} turns)",
          gm_ref.state == GameState.GAME_OVER)
    if gm_ref.state != GameState.GAME_OVER:
        print("Aborting LAN portion — game didn't finish in time.")
        return

    try:
        client_gp._record_profile_stats()
        client_ok = True
    except AttributeError as e:
        client_ok = False
        print(f"    LAN joiner raised: {e}")
    check("LAN joiner's _record_profile_stats() did not crash "
          "(THE BUG, LAN side — used to raise AttributeError here too)", client_ok)

    if client_ok:
        client_profile = sm_client.singleplayer_gm.profile
        check("LAN joiner's own local profile recorded a LAN game played",
              client_profile['games_played']['lan'] == 1)

    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()


def run():
    global screen, assets, board, anim
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    # This test saves real profile.json files via profile_store's real
    # per-user path (same as normal play would) — back up whatever's
    # there first so this doesn't clobber anyone's actual save data,
    # and restore it afterward no matter what happens.
    real_path = profile_store._profile_path()
    backup_path = real_path + '.test_backup'
    had_existing = os.path.isfile(real_path)
    if had_existing:
        shutil.copy2(real_path, backup_path)
    try:
        run_internet()
        run_lan()
    finally:
        if had_existing:
            shutil.move(backup_path, real_path)
        elif os.path.isfile(real_path):
            os.remove(real_path)


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"NETWORK CLIENT WIN PROFILE STATS: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("NETWORK CLIENT WIN PROFILE STATS: ALL CHECKS PASSED")
        sys.exit(0)
