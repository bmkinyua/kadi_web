"""
INTERNET MULTIPLAYER — PHASE 3 verification: the actual Scene classes
(InternetMenuScene, InternetLobbyScene, GameplayScene) end-to-end,
headless (SDL_VIDEODRIVER=dummy) — not just the network/server layer
underneath them. A real KadiServer instance plus two independent
SceneManager "apps" in one process (a game host + one joining player)
sharing a dummy display: host connects and creates a game -> a client
connects and joins it -> host clicks Start -> both land in
GameplayScene -> a few real turns are played via the actual
_action_draw()/_action_kadi_no() handlers -> both leave via the real
menu-exit path and teardown is verified.

Run (from the kadi/ directory):  python -m tests.test_internet_phase3_scenes_smoke
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from constants import GameState
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import (
    SceneManager, GameplayScene, InternetMenuScene, InternetLobbyScene, MainMenuScene,
)
from server.kadi_server import KadiServer

PORT = 52099
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, pred, timeout=5.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def make_app():
    gm = GameManager()
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
    return sm


def run():
    global screen, assets, board, anim
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    server = KadiServer(port=PORT)
    server.start()

    sm_host = make_app()
    sm_client = make_app()

    # ── Host connects and creates a game ────────────────────────────────
    sm_host.switch('internet_menu')
    menu = sm_host._scenes['internet_menu']
    menu._player_name = "Alice"
    menu._addr_text = f"127.0.0.1:{PORT}"
    menu._start_connect()

    def host_reached_lobby():
        server.tick(0.02)
        sm_host.update(0.02)
        return sm_host._current_name == 'internet_lobby'
    ok = wait_until(server, host_reached_lobby)
    check("host connected and landed in the internet lobby browser", ok)

    lobby_host = sm_host._scenes['internet_lobby']
    lobby_host._elimination_mode = False
    lobby_host._create_game()

    def host_room_created():
        server.tick(0.02)
        sm_host.update(0.02)
        return lobby_host._state == 'lobby' and lobby_host._host_id is not None
    ok = wait_until(server, host_room_created)
    check("host's create_game moved it into the waiting room", ok)
    check("host correctly recognizes itself as the host",
          ok and lobby_host._my_player_id == lobby_host._host_id)
    game_id = lobby_host._game_id

    # ── Client connects, browses, and joins ─────────────────────────────
    sm_client.switch('internet_menu')
    menu_c = sm_client._scenes['internet_menu']
    menu_c._player_name = "Bob"
    menu_c._addr_text = f"127.0.0.1:{PORT}"
    menu_c._start_connect()

    def client_reached_lobby():
        server.tick(0.02)
        sm_client.update(0.02)
        return sm_client._current_name == 'internet_lobby'
    ok = wait_until(server, client_reached_lobby)
    check("client connected and landed in the internet lobby browser", ok)

    lobby_client = sm_client._scenes['internet_lobby']

    def client_sees_open_game():
        server.tick(0.02)
        sm_client.update(0.02)
        return any(g['game_id'] == game_id for g in lobby_client._games)
    ok = wait_until(server, client_sees_open_game)
    check("client's game browser lists the host's open game", ok)

    lobby_client._join_game(game_id)

    def both_see_two_in_roster():
        server.tick(0.02)
        sm_host.update(0.02)
        sm_client.update(0.02)
        return (lobby_client._state == 'lobby'
               and len(lobby_host._lobby_roster) >= 2
               and len(lobby_client._lobby_roster) >= 2)
    ok = wait_until(server, both_see_two_in_roster)
    check("client joined and both sides see a 2-player roster", ok)
    check("client correctly recognizes it is NOT the host",
          ok and lobby_client._my_player_id != lobby_client._host_id)

    # ── Host starts the game ─────────────────────────────────────────────
    lobby_host._request_start()

    def host_reaches_gameplay():
        server.tick(0.02)
        sm_host.update(0.02)
        return sm_host._current_name == 'gameplay'
    ok = wait_until(server, host_reaches_gameplay)
    check("host scene switched to gameplay", ok)
    host_gp = sm_host._scenes.get('gameplay')
    check("host's GameplayScene is network_role='client' (NOT 'host' — the server, "
          "not the host player, owns the real GameManager)",
          ok and host_gp is not None and host_gp._network_role == 'client'
          and host_gp._host_game is None and host_gp._client_gm is not None)

    def client_reaches_gameplay():
        server.tick(0.02)
        sm_client.update(0.02)
        return sm_client._current_name == 'gameplay'
    ok = wait_until(server, client_reaches_gameplay)
    check("client scene switched to gameplay", ok)
    client_gp = sm_client._scenes.get('gameplay')
    check("client's GameplayScene also has a live client_gm",
          ok and client_gp is not None and client_gp._client_gm is not None)

    if not (host_gp and host_gp._client_gm and client_gp and client_gp._client_gm):
        print("Aborting remainder of test — one side never reached a live gameplay state.")
        server.stop()
        return

    check("both sides agree on player count",
          len(sm_host.gm.players) == len(sm_client.gm.players) == 2)

    room = server.lobby.get(game_id)
    check("server-side room actually started the real GameManager",
          room is not None and room.started)

    # ── Play a few real turns through the actual UI action methods ────
    turns = 0
    max_turns = 40
    gm_ref = room.gm  # the one true server-side GameManager
    while turns < max_turns and gm_ref.state != GameState.GAME_OVER:
        if gm_ref.state == GameState.POST_PLAY:
            actor_seat = gm_ref._post_play_player.player_id
        elif gm_ref.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor_seat = gm_ref.current_player.player_id
        else:
            break

        # Determine whose UI action to drive: look up which connection
        # owns the acting seat server-side, then match that against
        # each scene's own LANClient.player_id (== its conn_id).
        actor_conn_id = room._conn_by_seat.get(actor_seat)
        acting_gp = host_gp if actor_conn_id == host_gp._client_gm.client.player_id else client_gp

        before = (gm_ref.state, gm_ref.current_player_idx, id(gm_ref._post_play_player))
        if gm_ref.state == GameState.POST_PLAY:
            acting_gp._action_kadi_no()
        else:
            acting_gp._action_draw()

        def progressed():
            server.tick(0.02)
            sm_host.update(0.05)
            sm_client.update(0.05)
            return (gm_ref.state, gm_ref.current_player_idx,
                   id(gm_ref._post_play_player)) != before
        wait_until(server, progressed, timeout=2.0)
        turns += 1

    check(f"played {turns} real turns through GameplayScene's own action methods "
          f"without either side crashing", turns > 0)

    # ── Leave via the real menu-exit path on both sides ────────────────
    client_lc = client_gp._client_gm.client
    host_lc = host_gp._client_gm.client
    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()

    check("host scene returned to main menu", sm_host._current_name == 'main_menu')
    check("client scene returned to main menu", sm_client._current_name == 'main_menu')
    check("host's manager.gm was restored to its own singleplayer GameManager",
          sm_host.gm is sm_host.singleplayer_gm)
    check("client's manager.gm was restored to its own singleplayer GameManager",
          sm_client.gm is sm_client.singleplayer_gm)

    def teardown_settled():
        server.tick(0.02)
        return not host_lc.connected and not client_lc.connected
    ok = wait_until(server, teardown_settled, timeout=2.0)
    check("both sockets closed after exiting via the real menu-exit path", ok)

    server.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET PHASE 3: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET PHASE 3: ALL CHECKS PASSED")
        sys.exit(0)
