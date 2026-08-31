"""
INTERNET MULTIPLAYER — settings-parity verification (follow-up audit).

Confirms the gap identified in this session's review is actually
fixed: an Internet-hosted game's room now (1) shows the SAME set of
read-only rule rows LAN's host lobby shows (turn timer, hints,
post-play window, jump counter window, ace suit integrity, pickup
shield, ace finisher, jump multi-card) rather than just Elimination
Mode + AI Players, (2) actually APPLIES the creating player's own
locally-configured rule values to the real server-side GameManager —
not just displaying them cosmetically — and (3) a joining client sees
those exact same rows before the match starts. Loopback
(127.0.0.1), server + client connections, per the original phasing.

Run (from the kadi/ directory):  python -m tests.test_internet_settings_parity
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_manager import GameManager
from network.client import LANClient
from network.settings_summary import rule_settings_payload, build_rule_rows
from server.kadi_server import KadiServer

PORT = 52101
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


class Inbox:
    def __init__(self, client: LANClient):
        self.client = client
        self.by_type: dict = {}

    def pump(self):
        for m in self.client.poll():
            self.by_type[m.get('type')] = m

    def has(self, type_name: str) -> bool:
        self.pump()
        return type_name in self.by_type

    def get(self, type_name: str):
        self.pump()
        return self.by_type.get(type_name)


def wait_until(server, pred, timeout=3.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
        if pred():
            return True
        time.sleep(interval)
    return False


def run():
    server = KadiServer(port=PORT)
    server.start()
    try:
        # A host whose LOCAL app settings deliberately deviate from
        # GameManager's own class defaults, the same way a real
        # player's settings.json would after visiting SettingsScene.
        local_gm = GameManager()
        local_gm.timers_enabled = False
        local_gm.turn_timer_secs = 45.0
        local_gm.ace_finisher_enabled = False
        local_gm.jump_multi_card_enabled = False
        local_gm.pickup_shield_qk_allowed = False
        local_gm.hints_enabled = True
        local_gm.hint_threshold_pct = 25.0

        host = LANClient()
        host.connect('127.0.0.1', PORT, name='Alice')
        host_box = Inbox(host)
        server.tick(0.02)

        settings = {
            'elimination_mode': True,
            'ai_count': 0,
            'ai_difficulty': 'MEDIUM',
            'rules': rule_settings_payload(local_gm),
        }
        host.send({'type': 'create_game', 'settings': settings})

        ok = wait_until(server, lambda: host_box.has('welcome'))
        check("host created a game carrying its own local rule settings", ok)
        game_id = host_box.get('welcome')['game_id']

        room = server.lobby.get(game_id)
        check("server room exists", room is not None)

        # (2) Actually applied to the real server-side GameManager —
        # not just cosmetic.
        check("server GameManager picked up timers_enabled=False from the host",
              room.gm.timers_enabled is False)
        check("server GameManager picked up turn_timer_secs=45.0 from the host",
              room.gm.turn_timer_secs == 45.0)
        check("server GameManager picked up ace_finisher_enabled=False from the host",
              room.gm.ace_finisher_enabled is False)
        check("server GameManager picked up jump_multi_card_enabled=False from the host",
              room.gm.jump_multi_card_enabled is False)
        check("server GameManager picked up pickup_shield_qk_allowed=False from the host",
              room.gm.pickup_shield_qk_allowed is False)
        check("server GameManager picked up hints_enabled=True / hint_threshold_pct=25 "
              "from the host",
              room.gm.hints_enabled is True and room.gm.hint_threshold_pct == 25.0)

        # (1) Full parity of DISPLAYED rows — same set LAN's host lobby
        # shows, not a truncated subset.
        expected_rule_rows = build_rule_rows(room.gm)
        rows = room.settings_summary_rows()
        row_labels = [label for label, _ in rows]
        expected_labels = [label for label, _ in expected_rule_rows]
        check("room's displayed rows include every LAN-parity rule row "
              "(Turn Timer, Hints, Post-play window, Jump Counter window, "
              "Ace Suit Integrity, Pickup Shield, Ace Finisher, Jump Multi-card)",
              all(lbl in row_labels for lbl in expected_labels))
        check("Elimination Mode row reflects the host's actual choice (ON)",
              ("Elimination Mode", "ON") in rows)
        check("Turn Timer row reflects the host's actual OFF choice",
              any(lbl == "Turn Timer" and val == "OFF" for lbl, val in rows))
        check("Ace Finisher row reflects the host's actual OFF choice",
              any(lbl == "Ace Finisher" and val == "OFF" for lbl, val in rows))

        # (3) A JOINING client sees the exact same rows before the
        # match starts (not a different/stale copy).
        joiner = LANClient()
        joiner.connect('127.0.0.1', PORT, name='Bob')
        joiner_box = Inbox(joiner)
        server.tick(0.02)
        joiner.send({'type': 'join_game', 'game_id': game_id})
        ok = wait_until(server, lambda: joiner_box.has('welcome'))
        check("joiner joined the room", ok)

        def joiner_sees_rows():
            joiner_box.pump()
            ls = joiner_box.by_type.get('lobby_state')
            return ls is not None and len(ls.get('settings', {}).get('rows', [])) >= len(rows)
        ok = wait_until(server, joiner_sees_rows)
        check("joiner's lobby_state carries the same full row set before Start", ok)
        if ok:
            joiner_rows = [tuple(r) for r in
                          joiner_box.by_type['lobby_state']['settings']['rows']]
            check("joiner's rows exactly match the host's own settings_summary_rows()",
                  joiner_rows == rows)

        host.close()
        joiner.close()
    finally:
        server.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET SETTINGS PARITY: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET SETTINGS PARITY: ALL CHECKS PASSED")
        sys.exit(0)
