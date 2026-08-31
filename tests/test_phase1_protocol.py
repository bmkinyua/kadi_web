"""
PHASE 1 verification: network protocol + host/client core, in complete
isolation from game/UI code. A host and 2 "client" instances all talk
over 127.0.0.1, confirming messages actually flow correctly (framing,
ordering, disconnect handling) before any game integration exists.

Run (from the kadi/ directory):  python -m tests.test_phase1_protocol
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from network.host import LANHost
from network.client import LANClient
from network.protocol import FrameBuffer, encode_message, ProtocolError

PORT = 51988
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


def test_framing_unit():
    print("\n-- FrameBuffer unit test (no sockets) --")
    buf = FrameBuffer()
    m1 = encode_message({'type': 'a', 'x': 1})
    m2 = encode_message({'type': 'b', 'y': [1, 2, 3]})
    # Feed a message split across two feed() calls, and a second
    # message coalesced right after it in the same call, to prove
    # partial/merged TCP chunks are handled correctly either way.
    part_a, part_b = m1[:5], m1[5:]
    out1 = buf.feed(part_a)
    check("no message from partial frame", out1 == [])
    out2 = buf.feed(part_b + m2)
    check("two messages recovered from split+coalesced bytes",
          out2 == [{'type': 'a', 'x': 1}, {'type': 'b', 'y': [1, 2, 3]}])

    try:
        buf.feed(b'{not json}\n')
        check("malformed frame raises ProtocolError", False)
    except ProtocolError:
        check("malformed frame raises ProtocolError", True)


def test_loopback_connect_and_message_flow():
    print("\n-- Loopback host + 2 clients --")
    host = LANHost(port=PORT)
    host.start()
    try:
        c1 = LANClient()
        c2 = LANClient()
        c1.connect('127.0.0.1', PORT, name='Alice')
        c2.connect('127.0.0.1', PORT, name='Bob')

        # Host should see two _connected events, each followed by the
        # client's 'hello'.
        seen_hello = {}

        def drain_host_until_two_hellos():
            for pid, msg in host.poll():
                if msg.get('type') == 'hello':
                    seen_hello[pid] = msg.get('name')
            return len(seen_hello) >= 2

        ok = wait_until(drain_host_until_two_hellos)
        check("host received hello from both clients", ok)
        check("host assigned distinct player_ids", len(set(seen_hello.keys())) == 2)
        check("names round-tripped correctly",
              set(seen_hello.values()) == {'Alice', 'Bob'})

        # Host sends each client a personalized welcome with their id.
        for pid in seen_hello:
            host.send_to(pid, {'type': 'welcome', 'player_id': pid})

        def c1_has_welcome():
            for m in c1.poll():
                if m.get('type') == 'welcome':
                    c1._test_welcome = m
            return getattr(c1, '_test_welcome', None) is not None

        def c2_has_welcome():
            for m in c2.poll():
                if m.get('type') == 'welcome':
                    c2._test_welcome = m
            return getattr(c2, '_test_welcome', None) is not None

        ok1 = wait_until(c1_has_welcome)
        ok2 = wait_until(c2_has_welcome)
        check("client 1 received its welcome", ok1)
        check("client 2 received its welcome", ok2)
        check("client player_id set from welcome",
              c1.player_id is not None and c2.player_id is not None
              and c1.player_id != c2.player_id)

        # Broadcast from host reaches both clients, in order, with a
        # non-trivial nested payload (as a real state_sync would have).
        payload = {'type': 'lobby_state',
                   'players': [{'id': 0, 'name': 'Host'},
                               {'id': c1.player_id, 'name': 'Alice'},
                               {'id': c2.player_id, 'name': 'Bob'}]}
        host.broadcast(payload)

        def got_lobby(c):
            for m in c.poll():
                if m.get('type') == 'lobby_state':
                    c._test_lobby = m
            return getattr(c, '_test_lobby', None) is not None

        ok1 = wait_until(lambda: got_lobby(c1))
        ok2 = wait_until(lambda: got_lobby(c2))
        check("broadcast reached client 1 intact", ok1 and c1._test_lobby == payload)
        check("broadcast reached client 2 intact", ok2 and c2._test_lobby == payload)

        # Client -> host direct message (an "intent" in the real protocol).
        c1.send({'type': 'intent_draw'})

        def host_got_intent():
            for pid, msg in host.poll():
                if msg.get('type') == 'intent_draw':
                    host._test_intent_from = pid
            return getattr(host, '_test_intent_from', None) is not None

        ok = wait_until(host_got_intent)
        check("host received client intent with correct player_id",
              ok and host._test_intent_from == c1.player_id)

        # Disconnect handling: closing a client should surface a
        # disconnect event to the host without taking anything else down.
        c2.close()

        def host_saw_disconnect():
            for pid, msg in host.poll():
                if msg.get('type') == '_disconnected':
                    host._test_disc = pid
            return getattr(host, '_test_disc', None) is not None

        ok = wait_until(host_saw_disconnect)
        check("host detected client 2 disconnect", ok and host._test_disc == c2.player_id)

        # Host should still be able to talk to the still-connected client 1.
        host.send_to(c1.player_id, {'type': 'ping'})

        def c1_got_ping():
            for m in c1.poll():
                if m.get('type') == 'ping':
                    c1._test_ping = True
            return getattr(c1, '_test_ping', False)

        ok = wait_until(c1_got_ping)
        check("host->client1 still works after client2 disconnected", ok)

        c1.close()
    finally:
        host.stop()


def test_max_players_reject():
    print("\n-- MAX_PLAYERS reject --")
    host = LANHost(port=PORT + 1, max_players=2)  # host + 1 client max
    host.start()
    try:
        c1 = LANClient()
        c1.connect('127.0.0.1', PORT + 1, name='OnlySlot')
        time.sleep(0.2)
        check("first client connects when under capacity", c1.connected)

        c2 = LANClient()
        try:
            c2.connect('127.0.0.1', PORT + 1, name='Overflow')
            time.sleep(0.3)
            msgs = c2.poll()
            rejected = any(m.get('type') == 'reject' for m in msgs)
            check("second client receives reject at capacity", rejected)
        except Exception as e:
            check(f"second client connect handled ({e})", False)
        c1.close()
        c2.close()
    finally:
        host.stop()


if __name__ == '__main__':
    test_framing_unit()
    test_loopback_connect_and_message_flow()
    test_max_players_reject()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"PHASE 1: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("PHASE 1: ALL CHECKS PASSED")
        sys.exit(0)
