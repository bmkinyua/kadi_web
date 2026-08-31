"""
KADI Card Game — Main entry point.

Controls:
  Click cards to select/deselect (gold glow = selected, green = playable).
  Select cards then click Play Card, OR click confirmed set then Play.
  Click Draw Card or the draw pile to draw.
  Click Declare KADI! on your second-to-last turn.
  During suit pick: click a suit button.
  During counter window: click Counter! (J/K) or Pass.
  ESC = back to menu.

────────────────────────────────────────────────────────────────────────
HIDDEN AD-RELATED FEATURES — READ ME BEFORE RE-ENABLING ANYTHING ADS
────────────────────────────────────────────────────────────────────────
As of the itch.io -> Steam -> publisher distribution decision (Part B),
there is currently NO real ad network integrated anywhere in KADI, and
none is planned until real traffic justifies one (Bidstack, the one
ad network that supports PC, requires ~10K DAU minimum — see that
discussion). Two placeholder/ad-adjacent features exist in the code
but are currently HIDDEN from players. Nothing was deleted — every
piece below is a quick, deliberate un-hide, not a rebuild:

1. Banner ad slot (main menu / gameplay HUD)
   - What: a reserved on-screen banner slot; see scenes.py's AdBanner
     class and the _ads_showing() gate function just above it.
   - Currently: OFF by default — core/game_manager.py's
     self.ads_enabled and core/settings_store.py's DEFAULTS both
     default to False, and the "Advertising (Dev)" card that used to
     expose ads_enabled / ads_removed toggles in the Settings screen
     was removed from scenes.py's SettingsScene (search
     "_ads_toggle_key" there for the full explanation).
   - To bring back: flip the two ads_enabled defaults to True, and/or
     re-add a Settings card wiring up self._ads_toggle_key and
     self._ads_removed_btn (same shape as the card just above where it
     used to sit — see the comment left in its place).

2. "Watch to Refill" rewarded-ad undo-token top-up (pause menu)
   - What: a pause-menu button that was meant to grant +1 undo token
     after watching a rewarded ad; see scenes.py's _action_undo_refill
     (still fully intact/callable — it just grants the token directly
     right now, since there's no real ad to gate it behind).
   - Currently: HIDDEN — the pause-menu block that drew the token
     balance + refill button no longer runs; self._pause_undo_refill_rect
     is left None, which makes the existing click-handling naturally
     no-op. Search "Watch to Refill" in scenes.py for the full
     comment/context.
   - To bring back: restore that pause-menu drawing block (see the
     comment left in its place, right before _action_undo_refill's
     definition, for exactly what was removed).

Both are one-file, scoped changes (all in scenes.py, plus the two
ads_enabled defaults) — re-enabling either is quick once there's an
actual ad network worth wiring up.
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygame
from constants import FPS, TITLE, resource_base_dir
from core.game_manager import GameManager
from rendering.asset_loader import AssetLoader
from rendering.board_renderer import BoardRenderer
from animation.animator import AnimationManager
from scenes import (
    SceneManager, MainMenuScene, ModeSelectScene,
    SettingsScene, GameplayScene, RulesScene, ChuoScene, ProfileScene,
    LANMenuScene, LANHostLobbyScene, LANJoinScene, MultiplayerMenuScene,
    InternetMenuScene, InternetLobbyScene,
)
from core.settings_store import load_settings, save_settings
from core import save_manager, profile_store, msomi_trainer, game_logger
from startup_picker import should_show_startup_picker, run_startup_resolution_picker


def make_screen(gm: GameManager, fullscreen: bool = False) -> pygame.Surface:
    w, h = gm.resolution
    # Try SCALED first (best quality), fall back to plain window if it fails.
    # `fullscreen` is baked into the flags for a single, atomic set_mode()
    # call — the old code did a plain set_mode() and then a *separate*
    # pygame.display.toggle_fullscreen() call to layer fullscreen on top.
    # That two-step dance is what left the window stuck: on Windows, once
    # SDL had already been through one minimize/restore + toggle cycle,
    # a second toggle_fullscreen() call would silently no-op, so pressing
    # the fullscreen button again did nothing. Requesting the exact target
    # state directly avoids relying on toggle_fullscreen()'s internal
    # "previous state" tracking altogether.
    #
    # RESIZABLE used to be kept on in windowed mode so the window could be
    # dragged to an arbitrary size. That's also the actual cause of reports
    # of blurry text even at resolutions the display can clearly handle:
    # SDL's SCALED flag renders everything to a FIXED logical-size buffer
    # (gm.resolution) and then bilinear-stretches that buffer to fit
    # whatever the real window's pixel size is. The moment the real window
    # isn't exactly gm.resolution — not perfectly maximized, OS display
    # scaling (Windows 125%/150%, a HiDPI panel), a few pixels off from
    # dragging a corner — every single frame gets resampled, and text edges
    # show that resampling far more than anything else on screen. Dropping
    # RESIZABLE here makes windowed mode behave like fullscreen already
    # does: the window is a fixed size that always exactly matches the
    # logical buffer, so there's nothing for SDL to stretch. The tradeoff
    # is losing free-form window resizing by dragging — the Settings
    # resolution picker is the intended way to change size instead now.
    #
    # Note this does NOT fix a *separate*, harder problem: on genuinely
    # HiDPI/Retina displays, classic pygame/SDL2 has no reliable
    # cross-platform way to request a HiDPI-aware backbuffer, so the OS
    # itself may still upscale the whole window after SDL hands it a
    # lower-resolution surface than the physical panel. If text is still
    # soft after this change specifically on a HiDPI laptop screen, that's
    # the remaining suspect — worth checking the OS's display/text scaling
    # percentage as the practical mitigation, since there's no code-level
    # fix for it in this pygame version.
    flags = pygame.SCALED | (pygame.FULLSCREEN if fullscreen else 0)
    try:
        return pygame.display.set_mode((w, h), flags)
    except pygame.error:
        try:
            plain_flags = pygame.FULLSCREEN if fullscreen else 0
            return pygame.display.set_mode((w, h), plain_flags)
        except pygame.error:
            return pygame.display.set_mode((w, h))


def main():
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.display.set_caption(TITLE)
    # Window/taskbar icon — must be set before/at window creation to take
    # effect reliably across platforms (set_mode() happens later, inside
    # make_screen()). Uses constants.resource_base_dir() — NOT a plain
    # __file__-relative path — so this keeps working once packaged (see
    # that function's docstring for the frozen/_MEIPASS story; this used
    # to be the exact gap flagged as pending PC packaging work).
    try:
        icon_path = os.path.join(resource_base_dir(), 'assets', 'icon', 'kadi_icon.png')
        pygame.display.set_icon(pygame.image.load(icon_path))
    except (pygame.error, FileNotFoundError) as e:
        print(f"Warning: could not load window icon ({e}) — using default.")

    gm    = GameManager()
    load_settings(gm)               # restore saved timers/rules/hints/etc, if any
    gm.set_log_level(gm.log_level)  # initializes logging system (HIGH by default — see
                                     # core/settings_store.py's DEFAULTS)

    # One cheap probe at startup, no-op unless the player has opted into
    # a cap (default is unlimited) — mirrors the seed_bundled_reference_
    # model_if_empty pattern just below. Runs AFTER set_log_level() so
    # it never touches the file just opened for this session.
    game_logger.cleanup_old_logs(gm.max_log_pairs)

    # Persistent player progress (Profile Part 1) — its own file/lifecycle,
    # separate from settings.json, so Settings' "Reset to Defaults" never
    # touches it. Attached directly to gm since GameManager needs it live
    # (undo tokens, ads_removed) — see core.game_manager.GameManager.profile.
    gm.profile = profile_store.load_profile()

    # One-time, harmless if it's a no-op: gives a genuinely fresh install
    # an attachable MSOMI model right away instead of an empty Chuo
    # picker — see core.msomi_trainer.seed_bundled_reference_model_if_empty's
    # own docstring for exactly when this does/doesn't do anything.
    msomi_trainer.seed_bundled_reference_model_if_empty()

    # Resolve the resolution BEFORE the real window is created. This is
    # what prevents ever again ending up looking at an oversized,
    # unusable window with no visible way back into Settings — see
    # startup_picker.py.
    if should_show_startup_picker(gm):
        run_startup_resolution_picker(gm)   # sets gm.resolution in place
        save_settings(gm)                   # persist the choice immediately,
                                             # so a crash before the normal
                                             # exit-time save still keeps it

    screen = make_screen(gm)
    clock  = pygame.time.Clock()

    assets = AssetLoader()
    assets.init()

    board = BoardRenderer(assets)
    anim  = AnimationManager()

    # Apply the profile's equipped cosmetics (Part 2) now that assets/board
    # exist — falls back to 'default' harmlessly if the profile is fresh
    # or references an unknown/legacy style key (see set_equipped_card_back
    # / set_felt_theme's own fallback handling).
    assets.set_equipped_card_back(gm.profile['cosmetics']['equipped_card_back'])
    board.set_felt_theme(gm.profile['cosmetics']['equipped_felt_theme'])

    sm = SceneManager(screen, assets)
    sm.gm    = gm
    # Stable reference to the ONE real single-player GameManager, kept
    # even while sm.gm is temporarily pointed at a network
    # ClientGameManager during LAN play as a client — see
    # scenes.GameplayScene.on_exit(), which restores sm.gm from this.
    sm.singleplayer_gm = gm
    sm.board = board
    sm.anim  = anim
    sm.make_screen = make_screen   # allow settings to trigger resize

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

    def recreate_screen(fullscreen: bool):
        nonlocal screen
        screen = make_screen(gm, fullscreen=fullscreen)
        sm.screen = screen

    sm.window_controls.on_toggle_fullscreen = recreate_screen

    sm.switch('main_menu')

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        dt = min(dt, 0.1)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                # If a resumable game is mid-session, save it silently on
                # the way out rather than losing it outright — covers the
                # custom close button, Alt+F4, and the OS window-close X,
                # since all of them post this same event. Skipped for a
                # LAN match (network_role set) — a ClientGameManager isn't
                # something save_manager can serialize, and "resuming" a
                # network game later doesn't mean anything once everyone's
                # disconnected; the host's own game, being a real
                # GameManager, WOULD technically serialize fine, but a
                # solo "continue" of somebody else's LAN match afterward
                # isn't a feature this needs, so it's excluded uniformly.
                gp = sm._scenes['gameplay']
                if sm._current_name == 'gameplay' and not gp._network_role:
                    if save_manager.can_save(sm.gm):
                        save_manager.save_game(sm.gm)
                running = False
            if event.type == pygame.WINDOWRESTORED:
                # SDL/pygame can leave the display surface black and
                # unresponsive after a *fullscreen* window is minimized
                # and then restored (observed on Windows) — plain
                # windowed mode already survives minimize/restore fine,
                # so this only needs to act when fullscreen was active.
                # Fix: recreate the video mode directly in the target
                # state (windowed or fullscreen) in one set_mode() call.
                # Previously this did a plain set_mode() and then a
                # *separate* toggle_fullscreen() call to layer fullscreen
                # back on — that two-step sequence is what left the
                # fullscreen button permanently dead afterwards (SDL's
                # toggle_fullscreen() would silently stop responding to
                # later presses once it had already been driven through
                # one restore cycle on Windows).
                recreate_screen(sm.window_controls._maximized)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if sm._current_name == 'gameplay':
                        gp = sm._scenes['gameplay']
                        if gp._exit_confirm_pending:
                            # ESC while the save/discard/cancel dialog is
                            # already open acts as Cancel — closes the
                            # dialog and un-pauses if the dialog itself
                            # was what paused the game.
                            gp._action_exit_cancel()
                        elif sm.gm.is_paused:
                            # If the game is currently paused, ESC should
                            # resume play rather than silently exit to the
                            # main menu — previously this was the only way
                            # out of a paused game when the on-screen
                            # window controls were hard to see under the
                            # pause overlay, so players hit ESC expecting
                            # to dismiss the pause and lost their game.
                            sm.gm.toggle_pause()
                        else:
                            # Mid-game: offer to save before leaving,
                            # exactly like clicking Menu — ESC used to
                            # jump straight to the main menu and silently
                            # lose all progress.
                            gp._action_menu_clicked()
                    else:
                        running = False
            # Resolution change from settings
            if event.type == pygame.VIDEORESIZE:
                pass  # SCALED handles this automatically
            sm.handle_event(event)

        sm.update(dt)

        # If settings changed resolution, recreate window
        if hasattr(sm, '_pending_resolution'):
            gm.resolution = sm._pending_resolution
            del sm._pending_resolution
            recreate_screen(sm.window_controls._maximized)

        sm.draw()
        pygame.display.flip()

    save_settings(gm)
    profile_store.save_profile(gm.profile)
    pygame.quit()
    sys.exit(0)


if __name__ == '__main__':
    main()
