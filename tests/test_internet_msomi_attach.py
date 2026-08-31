"""
INTERNET MULTIPLAYER — MSOMI model attachment verification.

Confirms the follow-up feature request is actually wired end-to-end:
a host with an AI-fill seat and an MSOMI model "attached" (in this
test, a hand-built model dict standing in for one
InternetLobbyScene would have read from a local file via
core.msomi_trainer.load_model()) has that model's actual JSON content
embedded in create_game's settings, the server validates and stores
it, the resulting AI Player object in the real server-side
GameManager actually has it set on .msomi_model (not just displayed
cosmetically), and the lobby's settings rows surface it before Start
— plus the invalid-model-degrades-gracefully path.

Run (from the kadi/ directory):  python -m tests.test_internet_msomi_attach
"""
from __future__ import annotations
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import msomi_trainer
from network.client import LANClient
from server.kadi_server import KadiServer

PORT = 52103
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


def make_valid_model() -> dict:
    """Same shape core.msomi_trainer.train()/save_model() produce —
    what InternetLobbyScene._create_game() would have gotten back
    from msomi_trainer.load_model(self._msomi.model_name) on a real
    client machine."""
    return {
        'schema_version': msomi_trainer.MODEL_SCHEMA_VERSION,
        'decision_schema_version': msomi_trainer.DECISION_SCHEMA_VERSION,
        'model_type': 'conditional_logit',
        'features': ['cards_played', 'empties_hand'],
        'weights': {'cards_played': 0.42, 'empties_hand': 1.7},
        'training': {'num_decisions': 10, 'num_human_decisions': 10,
                    'num_ai_decisions': 0, 'human_weight': 2.0,
                    'iterations': 500, 'learning_rate': 0.1,
                    'train_agreement': 0.9, 'train_agreement_human_only': 0.9},
    }


def run_valid_model_case():
    print("\n-- valid MSOMI model: embedded, validated, attached to the real AI seat --")
    server = KadiServer(port=PORT)
    server.start()
    try:
        host = LANClient()
        host.connect('127.0.0.1', PORT, name='Alice')
        host_box = Inbox(host)
        server.tick(0.02)

        model = make_valid_model()
        settings = {
            'elimination_mode': False,
            'ai_count': 1,
            'ai_difficulty': 'MEDIUM',
            'ai_msomi_model': model,
            'ai_msomi_model_label': 'my_trained_model.json',
        }
        host.send({'type': 'create_game', 'settings': settings})
        ok = wait_until(server, lambda: host_box.has('welcome'))
        check("host created a game with an MSOMI model attached", ok)
        game_id = host_box.get('welcome')['game_id']
        room = server.lobby.get(game_id)

        check("server validated the embedded model and kept it (no error)",
              room._msomi_model is not None and room._msomi_model_error is None)

        rows = room.settings_summary_rows()
        check("lobby settings rows surface the MSOMI model's label before Start",
              ("  MSOMI Model", "my_trained_model.json") in rows)

        err = room.start_game(extra_ai_configs=[
            {'name': 'Kadi-Bot', 'is_human': False}])
        check("start_game succeeded", err is None)

        ai_players = [p for p in room.gm.players if not p.is_human]
        check("exactly one AI seat was created", len(ai_players) == 1)
        check("the AI seat's msomi_model is the EXACT dict the host sent "
              "(not just displayed — actually wired to the real Player object)",
              len(ai_players) == 1 and ai_players[0].msomi_model == model)

        host.close()
    finally:
        server.stop()


def run_invalid_model_case():
    print("\n-- invalid/corrupt MSOMI model: degrades gracefully, doesn't block the room --")
    server = KadiServer(port=PORT + 1)
    server.start()
    try:
        host = LANClient()
        host.connect('127.0.0.1', PORT + 1, name='Alice')
        host_box = Inbox(host)
        server.tick(0.02)

        bad_model = {'schema_version': 999, 'weights': {}}  # wrong schema version
        settings = {
            'elimination_mode': False,
            'ai_count': 1,
            'ai_difficulty': 'MEDIUM',
            'ai_msomi_model': bad_model,
            'ai_msomi_model_label': 'stale_model.json',
        }
        host.send({'type': 'create_game', 'settings': settings})
        ok = wait_until(server, lambda: host_box.has('welcome'))
        check("host's create_game still succeeds even with a bad model attached "
              "(room creation isn't blocked)", ok)
        game_id = host_box.get('welcome')['game_id']
        room = server.lobby.get(game_id)

        check("server correctly rejected the invalid model (schema mismatch)",
              room._msomi_model is None and room._msomi_model_error is not None)

        rows = room.settings_summary_rows()
        check("lobby rows clearly flag the model as invalid/ignored, not silently dropped",
              any(label == "  MSOMI Model" and "invalid" in val for label, val in rows))

        err = room.start_game(extra_ai_configs=[
            {'name': 'Kadi-Bot', 'is_human': False}])
        check("the game still starts fine despite the bad model", err is None)
        ai_players = [p for p in room.gm.players if not p.is_human]
        check("the AI seat just plays as plain AI (msomi_model left None), no crash",
              len(ai_players) == 1 and ai_players[0].msomi_model is None)

        host.close()
    finally:
        server.stop()


if __name__ == '__main__':
    run_valid_model_case()
    run_invalid_model_case()

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"INTERNET MSOMI ATTACH: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("INTERNET MSOMI ATTACH: ALL CHECKS PASSED")
        sys.exit(0)
