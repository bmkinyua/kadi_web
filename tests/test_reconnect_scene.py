"""
Scene-level verification of the CLIENT side of the mid-match
reconnect feature (see tests/test_disconnect_timeout.py for the
network-layer half): after GameplayScene hands off to network_role=
'client', if the underlying LANClient's socket drops, the background
auto-reconnect built into network.client_state.ClientGameManager
should notice, redial the same host under the same name/token, and
resume play once HostGame.attempt_reconnect reclaims the seat --
without the person having to do anything. GameplayScene's own job is
just to reflect ClientGameManager.connection_status ('ok' /
'reconnecting' / 'lost') as an on-screen banner (self._reconnect_banner
-- see scenes.py's update()); the actual redial loop, its retry
cadence, and the reconnect_info dict all live on ClientGameManager
itself, not on the scene (this file previously assumed scene-level
attributes -- self._reconnect_info, self._reconnecting,
RECONNECT_RETRY_INTERVAL_SECS -- that don't exist; updated to match
the real ClientGameManager-owned shape: self._client_gm.reconnect_info,
self._client_gm.connection_status, RECONNECT_RETRY_INTERVAL).

Run (from the kadi/ directory):  python -m tests.test_reconnect_scene
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
from scenes import SceneManager, GameplayScene, LANHostLobbyScene, LANJoinScene, MainMenuScene
import network.host_game as host_game_module

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

    sm_host.switch('lan_host_lobby')
    lobby = sm_host._scenes['lan_host_lobby']

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

    lobby._elimination_mode = False
    lobby._start_game()

    def client_reaches_gameplay():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return sm_client._current_name == 'gameplay'

    ok = wait_until(client_reaches_gameplay, timeout=5.0)
    check("client scene reached gameplay", ok)
    if not ok:
        print("Aborting — client never reached gameplay.")
        return

    host_gp = sm_host._scenes['gameplay']
    client_gp = sm_client._scenes['gameplay']
    check("GameplayScene's ClientGameManager captured reconnect_info from the join flow",
          client_gp._client_gm is not None
          and client_gp._client_gm.reconnect_info is not None
          and client_gp._client_gm.reconnect_info['mode'] == 'lan'
          and client_gp._client_gm.reconnect_info['name'] == 'Bob')

    # Shrink the grace period so the test doesn't need to wait 45s.
    host_game_module.DISCONNECT_GRACE_SECONDS = 8.0
    # Speed up the client's own background retry cadence for the same
    # reason -- these live on ClientGameManager itself now, not the scene.
    client_gp._client_gm.RECONNECT_GRACE_SECONDS = 6.0
    client_gp._client_gm.RECONNECT_RETRY_INTERVAL = 0.3

    # ── Simulate the client's connection dropping ──────────────────────
    client_gp._client_gm.client.close()

    def client_notices_disconnect():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return client_gp._client_gm.connection_status == 'reconnecting'
    ok = wait_until(client_notices_disconnect, timeout=3.0)
    check("ClientGameManager noticed the socket dropped and started reconnecting", ok)

    def client_shows_reconnect_banner():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return client_gp._reconnect_banner is not None
    ok = wait_until(client_shows_reconnect_banner, timeout=2.0)
    check("GameplayScene surfaced a reconnecting banner", ok)

    def host_sees_bob_unavailable():
        sm_host.update(0.02)
        return bool(host_gp._host_game._disconnected_at)
    ok = wait_until(host_sees_bob_unavailable, timeout=3.0)
    check("host started a grace-period countdown for Bob's seat", ok)

    # ── Let ClientGameManager's own background redial loop reconnect ───
    def client_reconnects():
        sm_host.update(0.05)
        sm_client.update(0.05)
        return client_gp._client_gm.connection_status == 'ok'
    ok = wait_until(client_reconnects, timeout=10.0)
    check("client automatically reconnected without user action", ok)
    check("GameplayScene's reconnecting banner was cleared",
          client_gp._reconnect_banner is None)
    check("host's grace-period countdown was cancelled",
          not host_gp._host_game._disconnected_at)
    check("host game is still in progress (seat wasn't removed)",
          sm_host.gm.state.name != 'GAME_OVER')

    # ── Confirm play can actually continue after reconnecting ──────────
    turns = 0
    max_turns = 6
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
    check("play continued normally through the reconnected client", turns > 0)

    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()
    host_game_module.DISCONNECT_GRACE_SECONDS = 30.0  # restore default

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"RECONNECT SCENE: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RECONNECT SCENE: ALL CHECKS PASSED")


if __name__ == '__main__':
    run()
