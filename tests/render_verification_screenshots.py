"""
Renders the verification screenshots for the profile/cosmetics/undo/
ads-removed feature to /mnt/user-data/outputs/.

Run (from the kadi/ directory):  python -m tests.render_verification_screenshots
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame
from constants import GameState, AIDifficulty
from core.game_manager import GameManager
from core import profile_store
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import SceneManager, MainMenuScene, ModeSelectScene, SettingsScene, \
    GameplayScene, RulesScene, ChuoScene, ProfileScene, LANMenuScene, \
    LANHostLobbyScene, LANJoinScene, MultiplayerMenuScene, InternetMenuScene, \
    InternetLobbyScene

OUT_DIR = "/mnt/user-data/outputs"
os.makedirs(OUT_DIR, exist_ok=True)

RES = (1280, 800)


def build_manager(profile):
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    screen = pygame.display.set_mode(RES)

    gm = GameManager()
    gm.resolution = RES
    gm.profile = profile

    assets = AssetLoader()
    assets.init()
    assets.set_equipped_card_back(profile['cosmetics']['equipped_card_back'])

    board = BoardRenderer(assets)
    board.set_felt_theme(profile['cosmetics']['equipped_felt_theme'])
    anim = AnimationManager()

    sm = SceneManager(screen, assets)
    sm.gm = gm
    sm.singleplayer_gm = gm
    sm.board = board
    sm.anim = anim
    sm.make_screen = lambda gm, fullscreen=False: screen

    sm.register('main_menu',   MainMenuScene(sm))
    sm.register('mode_select', ModeSelectScene(sm))
    sm.register('settings',    SettingsScene(sm))
    sm.register('rules',       RulesScene(sm))
    sm.register('chuo',        ChuoScene(sm))
    sm.register('profile',     ProfileScene(sm))
    sm.register('gameplay',    GameplayScene(sm))
    sm.register('multiplayer_menu', MultiplayerMenuScene(sm))
    sm.register('lan_menu',       LANMenuScene(sm))
    sm.register('lan_host_lobby', LANHostLobbyScene(sm))
    sm.register('lan_join',       LANJoinScene(sm))
    sm.register('internet_menu',  InternetMenuScene(sm))
    sm.register('internet_lobby', InternetLobbyScene(sm))

    return sm, screen, gm


def main():
    # ── 1. Profile screen: one earned + one locked badge, non-default
    #      cosmetics equipped ──────────────────────────────────────────
    profile = profile_store.default_profile()
    profile_store.award_badge(profile, 'beat_hard')       # earns felt "crimson"
    profile_store.award_badge(profile, 'first_hotseat_win')  # no cosmetic, just a 2nd earned badge
    # 'finish_question_chain' deliberately left un-awarded -> shows locked
    profile['cosmetics']['equipped_card_back'] = 'crosshatch'  # unlocked by finish_question_chain normally;
    profile['cosmetics']['owned_card_backs'].append('crosshatch')  # simulate ownership for this screenshot
    profile['cosmetics']['equipped_felt_theme'] = 'crimson'  # unlocked by beat_hard above
    profile['games_played']['single_player']['HARD'] = 3
    profile['games_won']['single_player']['HARD'] = 2
    profile['undo_tokens'] = 4

    sm, screen, gm = build_manager(profile)
    sm.switch('profile')
    sm.update(0.016)
    sm.draw()
    path1 = os.path.join(OUT_DIR, "profile_screen_top.png")
    pygame.image.save(screen, path1)
    print(f"Saved {path1}")

    # Scroll down to bring Cosmetics into view for a second screenshot
    prof_scene = sm._scenes['profile']
    prof_scene.scroll_offset = 550
    sm.draw()
    path1b = os.path.join(OUT_DIR, "profile_screen_cosmetics.png")
    pygame.image.save(screen, path1b)
    print(f"Saved {path1b}")
    pygame.quit()

    # ── 2. Ad banner: ads_enabled=True, ads_removed=False -> banner shows
    # ── 3. Ad banner: ads_enabled=True, ads_removed=True  -> banner hidden
    for ads_removed, label in [(False, "ads_shown"), (True, "ads_hidden")]:
        profile2 = profile_store.default_profile()
        profile2['ads_removed'] = ads_removed
        sm, screen, gm = build_manager(profile2)
        gm.ads_enabled = True
        sm.switch('main_menu')
        sm.update(0.016)
        sm.draw()
        path = os.path.join(OUT_DIR, f"banner_{label}.png")
        pygame.image.save(screen, path)
        from scenes import _ads_showing
        print(f"{label}: ads_enabled=True ads_removed={ads_removed} -> "
              f"_ads_showing()={_ads_showing(sm)}  (saved {path})")
        pygame.quit()

    # ── 4. Ad banner: ads_enabled=False, ads_removed=False -> also hidden
    #      (proves the OTHER half of the gate independently)
    profile3 = profile_store.default_profile()
    profile3['ads_removed'] = False
    sm, screen, gm = build_manager(profile3)
    gm.ads_enabled = False
    sm.switch('main_menu')
    sm.update(0.016)
    sm.draw()
    from scenes import _ads_showing
    print(f"ads_disabled_only: ads_enabled=False ads_removed=False -> "
          f"_ads_showing()={_ads_showing(sm)}")
    pygame.quit()


if __name__ == '__main__':
    main()
