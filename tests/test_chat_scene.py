"""
Scene-level verification of the in-match chat/emoji-reaction feature
for LAN Multiplayer: GameplayScene wires up chat for network_role in
('host', 'client') (see scenes.py's _chat_log/_dispatch_chat/
_action_toggle_chat -- chat was refactored out of a standalone
rendering.widgets.ChatPanel into plain GameplayScene state/methods;
this file was updated to match), messages typed/sent by either side
reach the other, quick-reaction shortcodes round-trip correctly, and
the unread badge increments while the panel is closed.

(The underlying network relay -- server/game_room.GameRoom.
build_chat_payload and network/host_game.HostGame._relay_chat/
send_chat -- is exercised directly, without any scene/pygame layer,
in ad-hoc form during development; this file covers the actual
GameplayScene/ChatPanel wiring on top of it.)

Run (from the kadi/ directory):  python -m tests.test_chat_scene
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
from scenes import SceneManager, GameplayScene, LANHostLobbyScene, LANJoinScene, MainMenuScene

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
    sm.register('lan_host_lobby', LANHostLobbyScene(sm))
    sm.register('lan_join', LANJoinScene(sm))
    return sm


def run():
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)
    anim = AnimationManager()

    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    sm_host.switch('lan_host_lobby')
    lobby = sm_host._scenes['lan_host_lobby']
    sm_client.switch('lan_join')
    join = sm_client._scenes['lan_join']
    join._player_name = "Bob"
    join._ip_text = "127.0.0.1"
    join._start_connect()

    def roster_ready():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return lobby._host is not None and len(lobby._host.roster()) >= 2

    ok = wait_until(roster_ready)
    check("client joined the LAN lobby", ok)

    lobby._elimination_mode = False
    lobby._start_game()

    def gameplay_ready():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return sm_client._current_name == 'gameplay'

    ok = wait_until(gameplay_ready, timeout=5.0)
    check("both scenes reached gameplay", ok)
    if not ok:
        print("Aborting.")
        return

    host_gp = sm_host._scenes['gameplay']
    client_gp = sm_client._scenes['gameplay']
    check("host's GameplayScene has chat wired up (network_role='host')",
          host_gp._network_role == 'host' and host_gp._host_game is not None)
    check("client's GameplayScene has chat wired up (network_role='client')",
          client_gp._network_role == 'client' and client_gp._client_gm is not None)

    # Simulate the host typing and sending a message.
    host_gp._dispatch_chat("Hello from host!")

    def client_gets_it():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return any(m['from'] == "Host" and m['text'] == "Hello from host!"
                   for m in client_gp._chat_log())

    ok = wait_until(client_gets_it, timeout=3.0)
    check("client received the host's chat message", ok)
    client_unread = len(client_gp._chat_log()) - client_gp._chat_seen_count
    check("unread badge incremented on the client (panel starts closed)",
          client_unread >= 1)

    client_gp._action_toggle_chat()
    client_unread_after_open = len(client_gp._chat_log()) - client_gp._chat_seen_count
    check("opening the panel clears the unread badge", client_unread_after_open == 0)

    # Simulate the client sending a quick-reaction.
    client_gp._dispatch_chat("[thumbsup]")

    def host_gets_it():
        sm_host.update(0.02)
        sm_client.update(0.02)
        return any(m['text'] == "[thumbsup]" for m in host_gp._chat_log())

    ok = wait_until(host_gets_it, timeout=3.0)
    check("host received the client's reaction shortcode", ok)

    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"CHAT SCENE: {len(FAILURES)} FAILURE(S)")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("CHAT SCENE: ALL CHECKS PASSED")


if __name__ == '__main__':
    run()
