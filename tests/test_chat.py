"""
Feature test: plain in-match chat relay for both LAN and Internet
Multiplayer (see network/host_game.HostGame.send_chat /
server/kadi_server.py's 'chat' handling / network/client_state
.ClientGameManager.send_chat). Only exercises the relay/plumbing —
scenes.GameplayScene's chat panel UI itself isn't covered here (no
display to drive headlessly against), but every non-UI hop a message
takes between two players is.

Run: SDL_VIDEODRIVER=dummy python -m tests.test_chat
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.host_game import HostGame
from network.client import LANClient
from network.client_state import ClientGameManager
from server.kadi_server import KadiServer

FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(pred, timeout=3.0, interval=0.02, host=None, dt=0.02):
    start = time.time()
    while time.time() - start < timeout:
        if host is not None:
            host.tick(dt)
        if pred():
            return True
        time.sleep(interval)
    return False


def run_lan_chat_test():
    print("\n-- LAN: chat relays both ways, host <-> joiner --")
    host = HostGame(port=52310)
    host.start_listening(host_name="Host")
    try:
        joiner = LANClient()
        joiner.connect('127.0.0.1', 52310, name='Joiner')
        wait_until(lambda: host.poll_lobby() and 'Joiner' in host.player_names.values(),
                  timeout=2.0)
        host.start_game(elimination_mode=False)

        client_gm = ClientGameManager(joiner, resolution=(1280, 800))

        # Host -> joiner
        host.send_chat("Hello from the host!")
        ok = False
        deadline = time.time() + 2.0
        while time.time() < deadline and not ok:
            client_gm.update(0.02)
            ok = any(m.get('text') == "Hello from the host!" for m in client_gm.chat_log)
            time.sleep(0.02)
        check("joiner receives the host's chat message",
              ok and any(m.get('from') == 'Host' for m in client_gm.chat_log))

        for _ in range(5):
            client_gm.update(0.02)

        # Joiner -> host
        client_gm.send_chat("Hi from the joiner!")
        check("joiner's own message appears in its own log immediately",
              any(m.get('text') == "Hi from the joiner!" for m in client_gm.chat_log))
        ok = wait_until(lambda: any(m.get('text') == "Hi from the joiner!"
                                    for m in host.chat_log),
                        timeout=2.0, host=host)
        check("host receives the joiner's chat message",
              ok and any(m.get('from') == 'Joiner' for m in host.chat_log))

        # An emoji is just another short chat string.
        client_gm.send_chat("🎉")
        ok = wait_until(lambda: any(m.get('text') == "🎉" for m in host.chat_log),
                        timeout=2.0, host=host)
        check("an emoji reaction relays like any other chat message", ok)
    finally:
        host.stop()


def run_internet_chat_test():
    print("\n-- Internet: chat relays between two clients via the server --")
    server = KadiServer(port=52311)
    server.start()
    try:
        alice = LANClient()
        alice.connect('127.0.0.1', 52311, name='Alice')
        server.tick(0.02)
        alice.send({'type': 'create_game', 'settings': {'ai_count': 0}})

        game_id = None
        deadline = time.time() + 2.0
        while time.time() < deadline and game_id is None:
            server.tick(0.02)
            for m in alice.poll():
                if m.get('type') == 'welcome':
                    game_id = m['game_id']
            time.sleep(0.02)
        check("Alice's room created", game_id is not None)

        bob = LANClient()
        bob.connect('127.0.0.1', 52311, name='Bob')
        server.tick(0.02)
        bob.send({'type': 'join_game', 'game_id': game_id})

        joined = False
        deadline = time.time() + 2.0
        while time.time() < deadline and not joined:
            server.tick(0.02)
            for m in bob.poll():
                if m.get('type') == 'welcome':
                    joined = True
            time.sleep(0.02)
        check("Bob joined", joined)

        alice_gm = ClientGameManager(alice, resolution=(1280, 800))
        bob_gm = ClientGameManager(bob, resolution=(1280, 800))

        alice_gm.send_chat("Good luck!")
        ok = False
        deadline = time.time() + 2.0
        while time.time() < deadline and not ok:
            server.tick(0.02)
            bob_gm.update(0.02)
            ok = any(m.get('text') == "Good luck!" for m in bob_gm.chat_log)
            time.sleep(0.02)
        check("Bob receives Alice's chat message",
              ok and any(m.get('from') == 'Alice' for m in bob_gm.chat_log))
        check("Alice does NOT see her own message echoed back a second time",
              sum(1 for m in alice_gm.chat_log if m.get('text') == "Good luck!") <= 1)

        alice.close()
        bob.close()
    finally:
        server.stop()


if __name__ == '__main__':
    run_lan_chat_test()
    run_internet_chat_test()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"CHAT: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("CHAT: ALL CHECKS PASSED")
        sys.exit(0)
