"""
Verification for: extending card-flight animations to AI opponents and
to remote players in LAN/Internet Multiplayer (network/client_state.py,
scenes.py GameplayScene._on_game_event / _should_animate_from_event /
_animate_play / _animate_draw).

Two things matter here, and both are checked directly against the real
Scene/GameManager/ClientGameManager code (not mocked):

1. EXACTLY-ONCE FIRING. Every 'cards_played'/'card_drawn'/'pickup_drawn'/
   'jump_countered' GameEvent a GameplayScene receives must result in
   exactly one _animate_play/_animate_draw call on that scene — never
   zero (a move that never animates) and never two (the direct-call
   path at the point of action AND the event-driven path in
   _on_game_event both firing for the same move). This is checked by
   spying on both _on_game_event (counting relevant events received)
   and _animate_play/_animate_draw (counting animations fired) per
   scene instance, and asserting the two counts match exactly.

   PART A drives a real local single-player game (1 human + 1 AI)
   headlessly via GameManager.update(), the same way
   test_phase4_regression.py does, to prove AI-opponent moves animate.

   PART B drives a real LAN host + client game over an actual loopback
   socket (127.0.0.1), the same two-SceneManager-apps-in-one-process
   setup test_phase3_scenes_smoke.py uses, scripted so every acting
   player always draws (same trick test_phase2_state_sync.py uses to
   avoid needing real legal-play logic) — proving BOTH that a remote
   player's move animates on the OTHER screen (the actual gap this
   feature closes) and that it does NOT double-animate on the acting
   player's OWN screen.

2. PRIVACY: AN OPPONENT'S DRAWN CARD NEVER RENDERS FACE-UP. Checked
   directly against AnimationManager's real AnimatedCard objects
   (not just trusting the face_up argument was passed correctly) for
   both an AI opponent (Part A) and a remote player (Part B).

Run (from the kadi/ directory):  python -m tests.test_remote_player_animation
"""
from __future__ import annotations
import os
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from constants import GameState, AIDifficulty
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import (
    SceneManager, GameplayScene, LANHostLobbyScene, LANJoinScene, MainMenuScene,
)

PORT_OFFSET = 51981  # distinct from test_phase3_scenes_smoke's port usage
FAILURES = []
ANIMATED_EVENT_KINDS = ('cards_played', 'card_drawn', 'pickup_drawn', 'jump_countered')


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


# ── spying scaffolding ──────────────────────────────────────────────────────
# Keyed by id(scene) so multiple independent GameplayScene instances (one
# per SceneManager "app") never share counters.
_event_counts = {}   # id(scene) -> int
_animate_counts = {} # id(scene) -> int
_orig_on_event = GameplayScene._on_game_event
_orig_animate_play = GameplayScene._animate_play
_orig_animate_draw = GameplayScene._animate_draw


def _spy_on_event(self, event):
    if event.kind in ANIMATED_EVENT_KINDS:
        _event_counts[id(self)] = _event_counts.get(id(self), 0) + 1
    return _orig_on_event(self, event)


def _spy_animate_play(self, player, cards):
    _animate_counts[id(self)] = _animate_counts.get(id(self), 0) + 1
    return _orig_animate_play(self, player, cards)


def _spy_animate_draw(self, player, cards):
    _animate_counts[id(self)] = _animate_counts.get(id(self), 0) + 1
    return _orig_animate_draw(self, player, cards)


def install_spies():
    GameplayScene._on_game_event = _spy_on_event
    GameplayScene._animate_play = _spy_animate_play
    GameplayScene._animate_draw = _spy_animate_draw


def restore_spies():
    GameplayScene._on_game_event = _orig_on_event
    GameplayScene._animate_play = _orig_animate_play
    GameplayScene._animate_draw = _orig_animate_draw


def assert_exact_once(label, scene):
    events = _event_counts.get(id(scene), 0)
    animations = _animate_counts.get(id(scene), 0)
    check(f"{label}: {events} relevant event(s) received, {animations} animation(s) fired "
          f"(no missing, no double-fire)", events > 0 and events == animations)


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


# ── Part A: local single-player, AI opponent must animate ──────────────────
def run_part_a(screen, assets, board):
    print("\n--- Part A: local single-player (AI opponent animation) ---")
    anim = AnimationManager()
    sm = make_app(screen, assets, board, anim)
    sm.switch('gameplay', player_configs=[
        {'name': 'You', 'is_human': True},
        {'name': 'Bot', 'is_human': False, 'difficulty': AIDifficulty.MEDIUM},
    ])
    gp = sm._scenes['gameplay']
    check("single-player GameplayScene entered without a network role",
          gp._network_role is None)

    ai_player = next(p for p in sm.gm.players if not p.is_human)
    human_player = next(p for p in sm.gm.players if p.is_human)

    # ── Direct, surgical check of the face-up fix before the full loop
    # muddies it with many overlapping animations: an AI opponent's own
    # draw must never render face-up, a human's own draw always must.
    if ai_player.hand.cards and human_player.hand.cards:
        anim.clear()
        gp._animate_draw(ai_player, [ai_player.hand.cards[0]])
        ai_anims = anim.get_active_anims()
        check("AI opponent's drawn card animates face-DOWN (privacy)",
              len(ai_anims) == 1 and ai_anims[0].face_up is False)

        anim.clear()
        gp._animate_draw(human_player, [human_player.hand.cards[0]])
        human_anims = anim.get_active_anims()
        check("local human's own drawn card still animates face-UP",
              len(human_anims) == 1 and human_anims[0].face_up is True)
        anim.clear()

    # The two surgical calls just above went straight to _animate_draw,
    # bypassing _on_game_event entirely — deliberately, to isolate the
    # face-up check — so they're not part of the exact-once accounting
    # below. Reset this scene's counters so that check only reflects
    # the real gameplay loop that follows.
    _animate_counts[id(gp)] = 0
    _event_counts[id(gp)] = 0

    # ── Full headless run: AI turns play themselves via the real game
    # loop (GameManager.update through GameplayScene.update), same
    # driving mechanism test_phase4_regression.py uses at the core-only
    # level, but here through the actual Scene so _on_game_event and the
    # animation spies are genuinely exercised. The human's own turns are
    # scripted to always draw (same trick Part B/test_phase2 use) so the
    # loop never stalls waiting on input nobody's providing — the point
    # here is proving the AI side animates, not exercising human input.
    DT = 0.05
    iters = 0
    while sm.gm.state != GameState.GAME_OVER and iters < 20000:
        if sm.gm.state == GameState.POST_PLAY and sm.gm._post_play_player is human_player:
            gp._action_kadi_no()
        elif (sm.gm.state in (GameState.PLAYING, GameState.KADI_DECLARED)
              and sm.gm.current_player is human_player):
            gp._action_draw()
        sm.update(DT)
        iters += 1
        # Stop once the AI has made a meaningful number of moves — we
        # only need to prove the mechanism, not play a full game out.
        if _animate_counts.get(id(gp), 0) >= 15:
            break

    check("game progressed without crashing (state reachable, iterations bounded)",
          iters < 20000)
    assert_exact_once("single-player scene (AI opponent moves)", gp)


# ── Part B: LAN host + client, remote player must animate on BOTH sides ────
def run_part_b(screen, assets, board):
    print("\n--- Part B: LAN host + client (remote player animation) ---")
    anim = AnimationManager()
    sm_host = make_app(screen, assets, board, anim)
    sm_client = make_app(screen, assets, board, anim)

    sm_host.switch('lan_host_lobby')
    lobby = sm_host._scenes['lan_host_lobby']
    check("host lobby started listening without error",
          lobby._error == "" and lobby._host is not None)

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
    if not ok:
        print("Aborting Part B — client never joined the lobby.")
        return

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
        print("Aborting remainder of Part B — client never reached gameplay.")
        return

    check("both sides agree on player count",
          len(sm_host.gm.players) == len(sm_client.gm.players) == 2)

    # ── Scripted play: every acting player always draws (same trick
    # test_phase2_state_sync.py uses) — legal at any point in
    # PLAYING/KADI_DECLARED, so this reliably drives real 'card_drawn'
    # (and, once pickups start chaining from stall resolution, possibly
    # 'pickup_drawn') events through the real host<->client wire without
    # needing real legal-play card matching.
    gm = sm_host.gm
    turns = 0
    max_turns = 40
    while turns < max_turns and gm.state != GameState.GAME_OVER:
        if gm.state == GameState.POST_PLAY:
            actor = gm._post_play_player
        elif gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            actor = gm.current_player
        else:
            break
        pid_for_seat = host_gp._host_game._pid_by_seat.get(actor.player_id)
        is_client_turn = pid_for_seat not in (None, 0)

        before = (gm.state, gm.current_player_idx, id(gm._post_play_player))
        actor_scene = client_gp if is_client_turn else host_gp
        if gm.state == GameState.POST_PLAY:
            actor_scene._action_kadi_no()
        else:
            actor_scene._action_draw()

        def progressed():
            sm_host.update(0.05)
            sm_client.update(0.05)
            return (gm.state, gm.current_player_idx, id(gm._post_play_player)) != before
        wait_until(progressed, timeout=2.0)
        turns += 1

    check(f"played {turns} real scripted turns over a real loopback socket "
          f"without either side crashing", turns > 0)

    # ── The core assertions: on EACH screen, every relevant event fired
    # exactly one animation — including for the OTHER seat's moves (the
    # actual remote-player-animation gap), and without double-firing on
    # the acting player's own screen.
    assert_exact_once("host screen (own + client's moves)", host_gp)
    assert_exact_once("client screen (own + host's moves)", client_gp)

    # ── Face-down privacy check for a genuinely remote draw: fabricate
    # one directly against the live client scene/state, same surgical
    # style as Part A, so it isn't diluted by however many animations
    # already fired during scripted play.
    if sm_client.gm.players and len(sm_client.gm.players) >= 2:
        remote_player = sm_client.gm.players[1]  # never rotated to "me" (seat 0)
        if remote_player.hand.cards:
            anim.clear()
            client_gp._animate_draw(remote_player, [remote_player.hand.cards[0]])
            remote_anims = anim.get_active_anims()
            check("a remote opponent's drawn card animates face-DOWN on the client "
                  "screen (privacy)",
                  len(remote_anims) == 1 and remote_anims[0].face_up is False)
            anim.clear()

    # ── Teardown via the real menu-exit path, same as test_phase3 ──────
    host_ng = host_gp._host_game
    client_lc = client_gp._client_gm.client
    host_gp._action_menu_clicked()
    client_gp._action_menu_clicked()

    def teardown_settled():
        return len(host_ng.net.player_ids()) == 0 and not client_lc.connected
    ok = wait_until(teardown_settled, timeout=2.0)
    check("host has no connected clients and client socket closed after exit", ok)
    host_ng.stop()


def run():
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode((1280, 800))
    assets = AssetLoader()
    assets.init()
    board = BoardRenderer(assets)

    install_spies()
    try:
        run_part_a(screen, assets, board)
        run_part_b(screen, assets, board)
    finally:
        restore_spies()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"REMOTE/AI ANIMATION: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("REMOTE/AI ANIMATION: ALL CHECKS PASSED")
        sys.exit(0)
