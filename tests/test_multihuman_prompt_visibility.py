"""
Regression test for a real UX bug found in production testing on the
actual deployed Oracle Cloud server: in a multi-human Internet (or LAN)
game, the POST_PLAY "Yes! KADI / Proceed" panel, the Jump-counter
Counter/Pass buttons, and the suit-picker modal were all gated only on
GLOBAL game state (e.g. "state == POST_PLAY"), which is identical on
every connected client's screen at once — so they lit up as active,
clickable prompts for EVERY human player simultaneously, not just
whoever the decision actually belonged to. Confirmed by two field
screenshots showing both players' screens displaying the same active
"Yes! KADI / Proceed" prompt at the same moment.

Fix lives entirely in scenes.py's GameplayScene: a new _my_player()
helper ("whoever is physically looking at this screen" — reliably
players[0] in every currently-functional mode) is now required, in
addition to the existing state checks, everywhere a decision-specific
prompt is drawn, click-routed, or actioned.

This drives a REAL server-authoritative 2-human game (reusing the same
harness pattern as tests/test_internet_phase3_scenes_smoke.py) until a
genuine POST_PLAY window opens via an actual legal play, then asserts
the fix holds on both connected GameplayScene instances.

Run: SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m tests.test_multihuman_prompt_visibility
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
    SceneManager, GameplayScene, InternetMenuScene, InternetLobbyScene, MainMenuScene,
)
from server.kadi_server import KadiServer

PORT = 52105
FAILURES = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        FAILURES.append(label)


def wait_until(server, pred, timeout=5.0, interval=0.02):
    start = time.time()
    while time.time() - start < timeout:
        server.tick(interval)
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

    server = KadiServer(port=PORT)
    server.start()

    sm_a = make_app(screen, assets, board, anim)
    sm_b = make_app(screen, assets, board, anim)

    # ── Get both connected, A hosts, B joins, both reach gameplay ──────────
    sm_a.switch('internet_menu')
    menu_a = sm_a._scenes['internet_menu']
    menu_a._player_name = "Player 1"
    menu_a._addr_text = f"127.0.0.1:{PORT}"
    menu_a._start_connect()
    ok = wait_until(server, lambda: (sm_a.update(0.02) or sm_a._current_name == 'internet_lobby'))
    check("player A connected", ok)

    lobby_a = sm_a._scenes['internet_lobby']
    lobby_a._create_game()
    ok = wait_until(server, lambda: (sm_a.update(0.02) or lobby_a._state == 'lobby'))
    check("player A's room created", ok)
    game_id = lobby_a._game_id

    sm_b.switch('internet_menu')
    menu_b = sm_b._scenes['internet_menu']
    menu_b._player_name = "Player 2"
    menu_b._addr_text = f"127.0.0.1:{PORT}"
    menu_b._start_connect()
    ok = wait_until(server, lambda: (sm_b.update(0.02) or sm_b._current_name == 'internet_lobby'))
    check("player B connected", ok)

    lobby_b = sm_b._scenes['internet_lobby']

    def b_sees_game():
        sm_b.update(0.02)
        return any(g['game_id'] == game_id for g in lobby_b._games)
    ok = wait_until(server, b_sees_game)
    check("player B sees A's open game", ok)
    lobby_b._join_game(game_id)
    ok = wait_until(server, lambda: (sm_a.update(0.02) or sm_b.update(0.02) or
                                     (lobby_b._state == 'lobby' and len(lobby_a._lobby_roster) >= 2)))
    check("player B joined", ok)

    lobby_a._request_start()
    ok = wait_until(server, lambda: (sm_a.update(0.02) or sm_a._current_name == 'gameplay'))
    check("player A reached gameplay", ok)
    ok = wait_until(server, lambda: (sm_b.update(0.02) or sm_b._current_name == 'gameplay'))
    check("player B reached gameplay", ok)

    gp_a = sm_a._scenes.get('gameplay')
    gp_b = sm_b._scenes.get('gameplay')
    if not (gp_a and gp_a._client_gm and gp_b and gp_b._client_gm):
        print("Aborting — one side never reached a live gameplay state.")
        server.stop()
        return

    room = server.lobby.get(game_id)
    gm_ref = room.gm  # the one true server-side GameManager

    def scene_for_seat(seat: int):
        """Which of our two GameplayScene instances corresponds to the
        server-side seat index, found by matching each scene's LANClient
        connection id against the room's own seat<->conn map."""
        conn_id = room._conn_by_seat.get(seat)
        if gp_a._client_gm.client.player_id == conn_id:
            return gp_a
        if gp_b._client_gm.client.player_id == conn_id:
            return gp_b
        return None

    # ── Drive real turns (play when possible, else draw) until a genuine
    #    POST_PLAY window opens via an actual legal play — draw-only
    #    turns (like tests/test_internet_phase2_authority.py's script)
    #    never trigger POST_PLAY at all, so this needs a real play. ──────
    def sync_scenes():
        server.tick(0.02)
        gp_a._client_gm.update(0.0)
        gp_b._client_gm.update(0.0)

    reached_post_play = False
    reached_counter = False
    for _ in range(300):
        sync_scenes()
        if gm_ref.state == GameState.POST_PLAY:
            reached_post_play = True
            break
        if gm_ref.state == GameState.JUMP_COUNTER_WINDOW:
            reached_counter = True
            break
        if gm_ref.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            time.sleep(0.02)
            continue
        actor_seat = gm_ref.current_player_idx
        acting_scene = scene_for_seat(actor_seat)
        if acting_scene is None:
            break
        playable = gm_ref.get_playable_cards()
        actor_hand = gm_ref.players[actor_seat].hand.cards
        playable_indices = [i for i, c in enumerate(actor_hand) if c in playable]
        if playable_indices:
            acting_scene._selected = {playable_indices[0]}
            acting_scene._action_play()
        else:
            acting_scene._action_draw()
        time.sleep(0.02)

    check("test script successfully drove the game into a real POST_PLAY "
         "or JUMP_COUNTER_WINDOW state", reached_post_play or reached_counter)

    if reached_post_play:
        print("\n-- POST_PLAY window: only the deciding player's screen may act on it --")
        pp_seat = None
        for i, p in enumerate(gm_ref.players):
            if p is gm_ref._post_play_player:
                pp_seat = i
        deciding_scene = scene_for_seat(pp_seat)
        other_scene = gp_b if deciding_scene is gp_a else gp_a

        check("deciding player's _my_player() matches the actual post-play player",
             deciding_scene._my_player().name == gm_ref._post_play_player.name)
        check("the OTHER player's _my_player() does NOT match the post-play player",
             other_scene._my_player().name != gm_ref._post_play_player.name)

        state_before = gm_ref.state
        other_scene._action_kadi_no()   # wrong player tries to click Proceed
        sync_scenes()
        check("the wrong player's _action_kadi_no() is a no-op (state unchanged)",
             gm_ref.state == state_before)

        deciding_scene._action_kadi_no()  # correct player proceeds
        ok = wait_until(server, lambda: (sync_scenes() or gm_ref.state != state_before))
        check("the correct player's _action_kadi_no() actually advances the game",
             ok and gm_ref.state != state_before)

    elif reached_counter:
        print("\n-- JUMP_COUNTER_WINDOW: only the deciding player's screen may act on it --")
        cp_seat = gm_ref.counter_player_idx
        deciding_scene = scene_for_seat(cp_seat)
        other_scene = gp_b if deciding_scene is gp_a else gp_a

        check("deciding player's _my_player() matches the actual counter player",
             deciding_scene._my_player().name == gm_ref.players[cp_seat].name)
        check("the OTHER player's _my_player() does NOT match the counter player",
             other_scene._my_player().name != gm_ref.players[cp_seat].name)

        state_before = gm_ref.state
        other_scene._action_pass_counter()   # wrong player tries to pass
        sync_scenes()
        check("the wrong player's _action_pass_counter() is a no-op (state unchanged)",
             gm_ref.state == state_before)

        deciding_scene._action_pass_counter()
        ok = wait_until(server, lambda: (sync_scenes() or gm_ref.state != state_before))
        check("the correct player's _action_pass_counter() actually advances the game",
             ok and gm_ref.state != state_before)

    server.stop()


if __name__ == '__main__':
    run()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"MULTI-HUMAN PROMPT VISIBILITY: {len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("MULTI-HUMAN PROMPT VISIBILITY: ALL CHECKS PASSED")
        sys.exit(0)
