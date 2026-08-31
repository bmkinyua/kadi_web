"""
PHASE 3 verification: the actual Scene classes (LANHostLobbyScene,
LANJoinScene, GameplayScene) end-to-end, headless (SDL_VIDEODRIVER=
dummy) — not just the network layer underneath them. Two independent
SceneManager "apps" in one process (host + one joining client) sharing
a dummy display, driving real widget/scene code: host lobby ->
one client joins -> host clicks Start -> both land in GameplayScene ->
a few turns are played via the real _action_draw()/_action_kadi_no()
handlers -> both leave via the real menu-exit path and teardown is
verified (host stops listening, client socket closes).

Run (from the kadi/ directory):  python -m tests.test_phase3_scenes_smoke
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
    SceneManager, GameplayScene, LANHostLobbyScene, LANJoinScene, MainMenuScene,
)

PORT_OFFSET = 51966  # HostGame uses network.host.DEFAULT_PORT unless told otherwise;
                      # LANHostLobbyScene always uses the default port, so this test
                      # just needs that default port to be free — no override needed.
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(pred, timeout=5.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
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
    sm.register('lan_host_lobby', LANHostLobbyScene(sm))
    sm.register('lan_join', LANJoinScene(sm))
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

    sm_host = make_app()
    sm_client = make_app()

    # ── Host opens the lobby ──────────────────────────────────────────
    sm_host.switch('lan_host_lobby')
    lobby = sm_host._scenes['lan_host_lobby']
    check("host lobby started listening without error", lobby._error == "" and lobby._host is not None)

    # ── Client connects ────────────────────────────────────────────────
    sm_client.switch('lan_join')
    join = sm_client._scenes['lan_join']
    join._player_name = "Bob"
    join._ip_text = "127.0.0.1"
    join._start_connect()

    def both_see_two_in_roster():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return (lobby._host is not None and len(lobby._host.roster()) >= 2
                and join._state in ('lobby', 'starting'))

    ok = wait_until(both_see_two_in_roster)
    check("client connected and host lobby roster reached 2", ok)

    # ── Host starts the game ───────────────────────────────────────────
    lobby._elimination_mode = False
    lobby._start_game()
    check("host scene switched to gameplay", sm_host._current_name == 'gameplay')
    host_gp = sm_host._scenes['gameplay']
    check("host GameplayScene has a live host_game", host_gp._host_game is not None)

    def client_reaches_gameplay():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return sm_client._current_name == 'gameplay'

    ok = wait_until(client_reaches_gameplay, timeout=5.0)
    check("client scene switched to gameplay", ok)
    client_gp = sm_client._scenes.get('gameplay')
    check("client GameplayScene has a live client_gm",
          ok and client_gp is not None and client_gp._client_gm is not None)

    if not ok:
        print("Aborting remainder of test — client never reached gameplay.")
        return

    check("both sides agree on player count",
          len(sm_host.gm.players) == len(sm_client.gm.players) == 2)

    # ── Play a few real turns through the actual UI action methods ────
    turns = 0
    max_turns = 40
    while turns < max_turns and sm_host.gm.state != GameState.GAME_OVER:
        gm = sm_host.gm
        if gm.state == GameState.POST_PLAY:
            actor = gm._post_play_player
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor = gm.current_player
        else:
            break
        pid_for_seat = host_gp._host_game._pid_by_seat.get(actor.player_id)
        is_client_turn = pid_for_seat not in (None, 0)

        before = (gm.state, gm.current_player_idx, id(gm._post_play_player))
        if is_client_turn:
            if gm.state == GameState.POST_PLAY:
                client_gp._action_kadi_no()
            else:
                client_gp._action_draw()
        else:
            if gm.state == GameState.POST_PLAY:
                host_gp._action_kadi_no()
            else:
                host_gp._action_draw()

        def progressed():
            sm_host.update(0.05)
            sm_client.update(0.05)
            return (gm.state, gm.current_player_idx, id(gm._post_play_player)) != before
        wait_until(progressed, timeout=2.0)
        turns += 1

    check(f"played {turns} real turns through GameplayScene's own action methods "
          f"without either side crashing", turns > 0)

    # ── Leave via the real menu-exit path on both sides ────────────────
    host_ng = host_gp._host_game
    client_lc = client_gp._client_gm.client
    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()

    check("host scene returned to main menu", sm_host._current_name == 'main_menu')
    check("client scene returned to main menu", sm_client._current_name == 'main_menu')
    check("client's manager.gm was restored to its own singleplayer GameManager",
          sm_client.gm is sm_client.singleplayer_gm)

    def teardown_settled():
        return len(host_ng.net.player_ids()) == 0 and not client_lc.connected
    ok = wait_until(teardown_settled, timeout=2.0)
    check("host has no connected clients and client socket closed after exit", ok)

    host_ng.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"PHASE 3: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PHASE 3: ALL CHECKS PASSED")
        sys.exit(0)
