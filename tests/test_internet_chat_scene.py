"""
Scene-level verification of in-match chat for INTERNET Multiplayer
specifically (see tests/test_chat_scene.py for the LAN equivalent).
Internet Multiplayer has no local-host special case -- whoever creates
a game and whoever joins it are BOTH network_role='client' thin
clients of the server's authoritative GameRoom (see
InternetLobbyScene's own docstring) -- so this exercises a genuinely
different code path than the LAN test: GameplayScene._dispatch_chat's
'client' branch for BOTH participants (via network.client_state.
ClientGameManager.send_chat) and server/kadi_server.py's 'chat'
routing/relay (which excludes the sender -- each client appends their
own outgoing message locally under 'from': 'You' immediately, per
ClientGameManager.send_chat, rather than waiting on an echo).

NOTE: chat was refactored out of a standalone rendering.widgets.
ChatPanel into plain GameplayScene state/methods (self._chat_log(),
self._dispatch_chat(), self._chat_seen_count -- see scenes.py); this
file was updated to match.

Run (from the kadi/ directory):  python -m tests.test_internet_chat_scene
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import SceneManager, GameplayScene, InternetMenuScene, InternetLobbyScene, MainMenuScene
from server.kadi_server import KadiServer

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, sms, pred, timeout=5.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        for sm in sms:
            sm.update(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def make_app(screen, assets, board, anim):
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
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    PORT = 52990
    server = KadiServer(port=PORT)
    server.start()
    try:
        sm_host = make_app(screen, assets, board, anim)
        sm_client = make_app(screen, assets, board, anim)
        sms = [sm_host, sm_client]

        sm_host.switch('internet_menu')
        host_menu = sm_host._scenes['internet_menu']
        host_menu._player_name = "Alice"
        host_menu._addr_text = f"127.0.0.1:{PORT}"
        host_menu._start_connect()
        ok = wait_until(server, sms, lambda: sm_host._current_name == 'internet_lobby', timeout=5.0)
        check("host connected to the server", ok)

        lobby = sm_host._scenes['internet_lobby']
        lobby._game_name_text = "Test Table"
        lobby._create_game()
        ok = wait_until(server, sms, lambda: lobby._state == 'lobby', timeout=5.0)
        check("host created and entered the room", ok)

        sm_client.switch('internet_menu')
        client_menu = sm_client._scenes['internet_menu']
        client_menu._player_name = "Bob"
        client_menu._addr_text = f"127.0.0.1:{PORT}"
        client_menu._start_connect()
        ok = wait_until(server, sms, lambda: sm_client._current_name == 'internet_lobby', timeout=5.0)
        check("joiner connected to the server", ok)

        client_lobby = sm_client._scenes['internet_lobby']

        def client_finds_and_joins():
            if client_lobby._state == 'browse' and client_lobby._games:
                check("joiner's browse list shows the host's actual game name",
                      client_lobby._games[0].get('game_name') == "Test Table")
                client_lobby._join_game(client_lobby._games[0]['game_id'])
            return client_lobby._state in ('joining', 'lobby')

        ok = wait_until(server, sms, client_finds_and_joins, timeout=5.0)
        check("joiner found and requested to join the room", ok)
        ok = wait_until(server, sms, lambda: client_lobby._state == 'lobby', timeout=5.0)
        check("joiner entered the lobby", ok)

        lobby._request_start()
        ok = wait_until(server, sms, lambda: sm_host._current_name == 'gameplay'
                        and sm_client._current_name == 'gameplay', timeout=5.0)
        check("both reached gameplay", ok)
        if not ok:
            print("Aborting.")
            return

        host_gp = sm_host._scenes['gameplay']
        client_gp = sm_client._scenes['gameplay']
        check("host's GameplayScene is network_role='client' (Internet has no local-host "
              "special case)", host_gp._network_role == 'client')
        check("host's GameplayScene has chat wired up", host_gp._client_gm is not None)
        check("joiner's GameplayScene has chat wired up", client_gp._client_gm is not None)

        # Host -> joiner
        host_gp._dispatch_chat("Hello from host!")
        ok = wait_until(server, sms, lambda: any(
            m['from'] == "Alice" and m['text'] == "Hello from host!"
            for m in client_gp._chat_log()), timeout=3.0)
        check("joiner received the host's chat message over Internet Multiplayer", ok)
        check("host's own message also appears in the host's own log (as 'You')",
              any(m['from'] == "You" and m['text'] == "Hello from host!"
                  for m in host_gp._chat_log()))

        # Joiner -> host, as a reaction
        client_gp._dispatch_chat("[heart]")
        ok = wait_until(server, sms, lambda: any(
            m['text'] == "[heart]" for m in host_gp._chat_log()), timeout=3.0)
        check("host received the joiner's reaction over Internet Multiplayer", ok)

        host_gp._action_menu_clicked()
        client_gp._action_menu_clicked()
    finally:
        server.stop()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET CHAT SCENE: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET CHAT SCENE: ALL CHECKS PASSED")


if __name__ == '__main__':
    run()
