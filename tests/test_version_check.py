"""
Verifies the version-check notice added to LAN and Internet
Multiplayer's connect handshake (see constants.VERSION,
network/client.py's 'hello' message, network/host_game.py's and
server/kadi_server.py's 'welcome' replies, and LANJoinScene's /
InternetLobbyScene's own version comparison).

This is deliberately informational-only, never a hard version gate —
so this test checks BOTH that a mismatch produces a visible notice,
AND that gameplay still proceeds normally despite the mismatch (a
regression here would mean someone accidentally turned "just a note"
into a real block).

Run (from the kadi/ directory):  python -m tests.test_version_check
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
import constants
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

PORT = 52099
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


def run_internet_matching():
    print("--- Internet: matching versions -> no notice ---")
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
    lobby_host._create_game()
    ok = wait_until(tick, lambda: lobby_host._state == 'lobby'
                    and lobby_host._reconnect_token is not None)
    check("host reached lobby", ok)
    check("no version notice when versions match",
          lobby_host._version_notice is None)

    server.stop()


def run_internet_mismatch():
    print("--- Internet: mismatched versions -> notice shown, still playable ---")
    # Simulate a deployed SERVER running an older/different version than
    # players' clients — the realistic drift scenario (server and every
    # player's client are two independent things that can go out of
    # sync; see the earlier LAN-vs-Internet maintenance discussion).
    # Patched BEFORE the server starts so its 'welcome' replies carry
    # the fake version. Internet Multiplayer has NO local-host special
    # case (see GameplayScene.on_enter's own comment — only
    # LANHostLobbyScene ever uses network_role='host') — the game's
    # CREATOR is just as much a thin client of the server as anyone who
    # joins, so both sides go through the identical comparison in
    # InternetLobbyScene and should BOTH see the same notice here,
    # symmetrically. (LAN is different — see run_lan_mismatch, where
    # only the joining player compares against the host's version.)
    import server.kadi_server as server_module
    original_version = server_module.VERSION
    server_module.VERSION = "0.9"
    try:
        server = KadiServer(port=PORT + 1)
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
        menu._addr_text = f"127.0.0.1:{PORT + 1}"
        menu._start_connect()
        wait_until(tick, lambda: sm_host._current_name == 'internet_lobby')
        lobby_host = sm_host._scenes['internet_lobby']
        lobby_host._create_game()
        wait_until(tick, lambda: lobby_host._state == 'lobby' and lobby_host._host_id is not None
                   and lobby_host._reconnect_token is not None)
        game_id = lobby_host._game_id

        check("game CREATOR (also just a client here) sees the notice too — "
              "Internet has no local-host special case",
              lobby_host._version_notice is not None)
        if lobby_host._version_notice:
            check("creator's notice text mentions both versions",
                  "0.9" in lobby_host._version_notice and "1.1" in lobby_host._version_notice)

        sm_client.switch('internet_menu')
        menu_c = sm_client._scenes['internet_menu']
        menu_c._player_name = "Bob"
        menu_c._addr_text = f"127.0.0.1:{PORT + 1}"
        menu_c._start_connect()
        wait_until(tick, lambda: sm_client._current_name == 'internet_lobby')
        lobby_client = sm_client._scenes['internet_lobby']
        wait_until(tick, lambda: any(g['game_id'] == game_id for g in lobby_client._games))
        lobby_client._join_game(game_id)
        ok = wait_until(tick, lambda: lobby_client._state == 'lobby'
                        and lobby_client._reconnect_token is not None, timeout=5.0)
        check("joining player still reached the lobby (not blocked)", ok)
        check("joining player also sees the same notice",
              lobby_client._version_notice is not None)

        # Confirm play still proceeds normally despite the mismatch —
        # start the game and verify both sides actually reach gameplay.
        # Version stays patched through this too, since a real deployed
        # server obviously doesn't change version mid-match either.
        wait_until(tick, lambda: len(lobby_host._lobby_roster) >= 2, timeout=5.0)
        lobby_host._request_start()
        ok_h = wait_until(tick, lambda: sm_host._current_name == 'gameplay', timeout=5.0)
        ok_c = wait_until(tick, lambda: sm_client._current_name == 'gameplay', timeout=5.0)
        check("both sides still reached gameplay despite the version mismatch "
              "(confirms this is informational-only, not a real gate)", ok_h and ok_c)

        if ok_h and ok_c:
            sm_host._scenes['gameplay']._action_menu_clicked()
            sm_client._scenes['gameplay']._action_menu_clicked()
        server.stop()
    finally:
        server_module.VERSION = original_version


def run_lan_matching():
    print("--- LAN: matching versions -> no notice ---")
    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    def tick():
        sm_host.update(0.05)
        sm_client.update(0.05)

    sm_host.switch('lan_host')
    host_lobby = sm_host._scenes['lan_host']
    check("LAN host is listening", host_lobby._host is not None and not host_lobby._error)
    if host_lobby._host is None or host_lobby._error:
        print(f"Skipping — host failed to start listening ({host_lobby._error}).")
        return
    port = host_lobby._host.port

    sm_client.switch('lan_join')
    join_scene = sm_client._scenes['lan_join']
    join_scene._player_name = "Bob"
    join_scene._ip_text = f"127.0.0.1:{port}"
    join_scene._start_connect()
    ok = wait_until(tick, lambda: join_scene._state in ('lobby', 'starting')
                    and join_scene._reconnect_token is not None, timeout=5.0)
    check("LAN joiner connected", ok)
    check("no version notice when versions match", join_scene._version_notice is None)

    # Clean up both sockets before the next LAN test phase reuses this
    # port range — leaving these open was causing run_lan_mismatch's
    # fresh host to intermittently fail to bind/connect right after.
    if host_lobby._host is not None:
        host_lobby._host.stop()
    if join_scene._client is not None:
        join_scene._client.close()


def run_lan_mismatch():
    print("--- LAN: mismatched versions -> notice shown, still playable ---")
    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    def tick():
        sm_host.update(0.05)
        sm_client.update(0.05)

    # Simulate the HOST running a newer version this time (covers the
    # other direction — LAN's welcome comes from the host, not a
    # separate server process).
    import network.host_game as host_game_module
    original_version = host_game_module.VERSION
    host_game_module.VERSION = "1.2"
    try:
        sm_host.switch('lan_host')
        host_lobby = sm_host._scenes['lan_host']
        if host_lobby._host is None or host_lobby._error:
            # The default LAN port (51999, fixed — see network/host.py's
            # DEFAULT_PORT) can still be settling from run_lan_matching's
            # host in this same process/sandbox even with SO_REUSEADDR
            # set. Rather than fight OS port-release timing further,
            # just retry once on an explicit different port — HostGame
            # itself accepts a port override even though
            # LANHostLobbyScene's on_enter() doesn't expose one.
            print(f"Default port busy ({host_lobby._error}) — retrying on an alternate port.")
            from network.host_game import HostGame
            host_lobby._host = HostGame(gm=sm_host.gm, port=52996)
            try:
                host_lobby._host.start_listening(host_name=host_lobby._player_name)
                host_lobby._error = ""
            except OSError as e:
                host_lobby._error = f"Couldn't start hosting: {e}"
        if host_lobby._host is None or host_lobby._error:
            print(f"Skipping — host failed to start listening even on retry ({host_lobby._error}).")
            return
        port = host_lobby._host.port

        sm_client.switch('lan_join')
        join_scene = sm_client._scenes['lan_join']
        join_scene._player_name = "Bob"
        join_scene._ip_text = f"127.0.0.1:{port}"
        join_scene._start_connect()
        ok = wait_until(tick, lambda: join_scene._state in ('lobby', 'starting')
                        and join_scene._reconnect_token is not None, timeout=5.0)
        check("mismatched LAN joiner still connected (not blocked)", ok)
    finally:
        host_game_module.VERSION = original_version

    check("mismatched LAN joiner recorded a version notice",
          join_scene._version_notice is not None)
    if join_scene._version_notice:
        check("notice text mentions both versions",
              "1.2" in join_scene._version_notice and "1.1" in join_scene._version_notice)


def run():
    global screen, assets, board, anim
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    run_internet_matching()
    run_internet_mismatch()
    run_lan_matching()
    time.sleep(0.3)  # let the previous phase's sockets fully release
    # (retry-on-alternate-port logic in run_lan_mismatch covers the
    # rest, in case that's still not quite enough in this sandbox)
    run_lan_mismatch()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"VERSION CHECK: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("VERSION CHECK: ALL CHECKS PASSED")
        sys.exit(0)
