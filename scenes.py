"""
KADI - Scene system (v2)
Fixes:
  - Multi-card set selection with Confirm button (Q+7+7 type combos)
  - Turn timer bar (configurable, auto-draw on expiry)
  - Separate KADI declaration timer
  - Configurable window resolution (settings)
  - Declare KADI! button stays visible until pressed
  - Timer events shown in UI
"""
from __future__ import annotations
import pygame
import math
import random
import os
import re
import threading
from datetime import datetime
from typing import Optional, List, Dict, Callable, Tuple

from constants import (
    CARD_W, CARD_H, GameState, AIDifficulty, VERSION, resource_base_dir,
    TABLE_FELT, TABLE_GREEN, TABLE_EDGE,
    WHITE, BLACK, DARK_GRAY, MID_GRAY, LIGHT_GRAY, GOLD, GOLD_LIGHT,
    BTN_NORMAL, BTN_HOVER, BTN_PRESSED,
    Suit, SUIT_SYMBOL, SUIT_ICON, SUIT_ACCENT, SUIT_COLOR,
    KADI_COLOR, PlayDirection, COUNTER_WINDOW_SECS, OVERLAY_ALPHA,
    MIN_PLAYERS, MAX_PLAYERS,
    AD_BANNER_Y, get_banner_size, get_ad_reserved_top, get_ui_scale,
    get_chrome_scale, FELT_THEMES, CARD_BACK_STYLES,
)
from models.player import HumanPlayer, AIPlayer
from core.game_manager import GameManager, GameEvent
from core import profile_store
from rendering.asset_loader import AssetLoader, MUSIC_CREDITS
from rendering.board_renderer import BoardRenderer, DISCARD_POS, DRAW_POS
from rendering.widgets import (
    Button, Panel, SuitPicker, MessageBanner, KADIBanner, WinScreen, draw_icon, wrap_text,
    render_cards_inline, PassAndPlayOverlay, draw_rounded_rect, HelpOverlay, make_help_button
)
from animation.animator import AnimationManager, Tween

_help_image_cache: Dict[str, Optional[pygame.Surface]] = {}


def _load_help_image(relpath: str) -> Optional[pygame.Surface]:
    """Loads a static illustration for a HelpOverlay section (e.g. the
    drag-to-reorder arrow diagram) from assets/help/<relpath>. Cached
    process-wide since these are static content, not per-scene-instance
    state, and re-decoding the same PNG every time a scene is entered
    would be wasteful. Returns None (never raises) if the file is
    missing — a HelpOverlay section just silently skips the image and
    keeps its surrounding text, rather than crashing the whole screen
    over a missing illustration."""
    if relpath in _help_image_cache:
        return _help_image_cache[relpath]
    path = os.path.join(resource_base_dir(), 'assets', 'help', relpath)
    try:
        img = pygame.image.load(path).convert_alpha()
    except (pygame.error, FileNotFoundError):
        img = None
    _help_image_cache[relpath] = img
    return img

# ─── Phase 4: scroll-limit "bounce" (overshoot then settle) ──────────────────
# Shared by SettingsScene, RulesScene, and ChuoScene's scrollable lists so a
# mouse-wheel scroll that hits the top/bottom doesn't just hard-stop — it
# overshoots a little past the limit and eases back with ease_out_back.
SCROLL_OVERSHOOT = 42
SCROLL_SETTLE_DURATION = 0.32

def _scroll_wheel_delta(current: float, wheel_y: int, step: float, max_scroll: float) -> float:
    """New scroll value for a wheel tick, allowed to overshoot the valid
    [0, max_scroll] range by a small bounded amount."""
    target = current - wheel_y * step
    return max(-SCROLL_OVERSHOOT, min(max_scroll + SCROLL_OVERSHOOT, target))

def _settle_scroll(current: float, bounce_tween: Optional[Tween], dt: float,
                   max_scroll: float) -> Tuple[float, Optional[Tween]]:
    """Call every frame. While current is out of [0, max_scroll], eases it
    back to the nearest bound with an overshoot-then-settle curve. Returns
    the (possibly updated) value and the (possibly new/finished) tween."""
    if current < 0 or current > max_scroll:
        bound = 0 if current < 0 else max_scroll
        if bounce_tween is None:
            bounce_tween = Tween(current, bound, SCROLL_SETTLE_DURATION, easing='ease_out_back')
        bounce_tween.update(dt)
        return bounce_tween.value, (None if bounce_tween.done else bounce_tween)
    return current, None
from core.settings_store import save_settings, reset_to_defaults
from core import save_manager
from core import game_logger
from core import msomi_trainer
from core import native_dialog
from network.host_game import HostGame
from network.host import DEFAULT_PORT
from network.client import LANClient, ConnectError
from network.client_state import ClientGameManager
from server.connection import DEFAULT_PORT as INTERNET_DEFAULT_PORT
from network import settings_summary
from network.player_names import disambiguate_names
from core import social_share
from rendering import share_card

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sw(gm): return gm.resolution[0]
def _sh(gm): return gm.resolution[1]


def _slugify(text: str) -> str:
    """Filesystem-safe fragment for a share-image filename — used for
    both a player's typed display name and a badge id (see
    _save_and_share_card call sites in GameplayScene/ProfileScene)."""
    s = re.sub(r'[^A-Za-z0-9]+', '_', text).strip('_')
    return s[:40] or "kadi"


def _save_and_share_card(surface: pygame.Surface, filename_prefix: str,
                         platform_key: str, tweet_text: str) -> str:
    """Shared Part C save+share flow for both the win-screen card and
    the badge card: save the rendered surface as a PNG (see
    core.social_share.save_share_image for where that lands), then
    either copy the caption to the clipboard (COPY_ACTION_KEY) or open
    a pre-filled share-compose window for `tweet_text` on
    `platform_key` in the person's own browser (best-effort — see
    open_share_intent's docstring for why a failure there doesn't undo
    the save). Returns a short status string for the caller to
    display."""
    filename = f"{filename_prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    try:
        path = social_share.save_share_image(surface, filename)
    except Exception as e:
        return f"Couldn't save the share image ({e}). Nothing was shared."
    # Best-effort: get the saved file's location open and visible right
    # away, so it's one drag away from being manually attached to
    # whatever share window is about to open below — see
    # reveal_in_file_manager's own docstring for exactly what this can
    # and can't do (it cannot auto-attach the file to anything; no
    # platform's share dialog allows that from a plain URL).
    social_share.reveal_in_file_manager(path)
    # The on-screen message shows just the filename, not the full
    # absolute path — a real Windows path like
    # "C:\Users\<name>\Pictures\KADI Shares\kadi_win_<name>_<timestamp>.png"
    # is long enough on its own, before any surrounding sentence, that
    # at the smallest supported resolution (1024x640) with the share
    # row expanded it could still overflow past the bottom of the
    # screen even after WinScreen.draw()'s own wrap-wider-first
    # fallback (see that method's comments) — a real screenshot at
    # exactly that combination is what this was found from. The folder
    # itself is already opened in the file manager (see
    # reveal_in_file_manager above), so the full path isn't needed here
    # to locate the file — just its name.
    display_name = os.path.basename(path)
    if platform_key == social_share.COPY_ACTION_KEY:
        if social_share.copy_text_to_clipboard(tweet_text):
            return (f"Saved {display_name} — its folder just opened — caption "
                    "copied to your clipboard, paste it anywhere.")
        return (f"Saved {display_name} — its folder just opened. Couldn't copy "
                f"the caption automatically — copy it yourself: \"{tweet_text}\"")
    opened = social_share.open_share_intent(platform_key, tweet_text)
    label = social_share.platform_label(platform_key)
    if opened:
        return (f"Saved {display_name} — its folder just opened — drag it into "
                f"the {label} window that opened alongside it.")
    return (f"Saved {display_name} — its folder just opened. Couldn't open "
            f"{label} automatically — attach the saved image to a post yourself.")



# ─── Base Scene ───────────────────────────────────────────────────────────────

class Scene:
    def __init__(self, manager: 'SceneManager'):
        self.manager = manager
        self.assets: AssetLoader = manager.assets

    @property
    def gm(self): return self.manager.gm

    def _ad_top_pad(self) -> int:
        """Pixels this scene's top-anchored content (title, etc.) needs
        to shift down to clear the ad banner strip, this frame — 0 when
        ads aren't showing. Shared by every ad-eligible scene (see
        AD_ELIGIBLE_SCENES) so they can't drift out of sync with each
        other or with AdBanner.draw()'s own decision about what to
        render — GameplayScene had its own copy of this exact logic
        before it moved here; every other eligible scene had NONE, so
        their titles would render UNDER the ad banner (SceneManager
        draws the banner AFTER the current scene, i.e. on top of it)
        the moment ads_enabled ever turns on for a real build, even
        though nothing showed this during dev testing (ads_enabled
        defaults to False — see core/game_manager.py). Currently off
        by default, but the reserved space here is exact whether ads
        end up used or not, not a guess."""
        if not _ads_showing(self.manager):
            return 0
        sw, sh = self.gm.resolution
        return get_ad_reserved_top(sw, sh)

    def on_enter(self, **kwargs): pass
    def on_exit(self):            pass
    def handle_event(self, event: pygame.event.Event): pass
    def update(self, dt: float):  pass
    def draw(self, surf: pygame.Surface): pass


# ─── Scene Manager ────────────────────────────────────────────────────────────

class SceneManager:
    def __init__(self, screen: pygame.Surface, assets: AssetLoader):
        self.screen  = screen
        self.assets  = assets
        self._scenes: Dict[str, Scene] = {}
        self._current: Optional[Scene] = None
        self._current_name: str = ""
        self.window_controls = WindowControls(assets.font('ui_small'))
        self.audio_controls = AudioControls(self, assets.font('ui_small'))
        self.ad_banner = AdBanner(assets)

    def register(self, name: str, scene: Scene):
        self._scenes[name] = scene

    def switch(self, name: str, **kwargs):
        if self._current:
            self._current.on_exit()
        self._current_name = name
        self._current = self._scenes[name]
        self._current.on_enter(**kwargs)
        # Drive the menu/gameplay/Chuo crossfade off the same single
        # switch() chokepoint every scene transition already goes
        # through — see rendering/music_manager.py.
        self.assets.music.on_scene_changed(name)

    def handle_event(self, event):
        # Window controls sit on top of every scene — give them first
        # look at click events so a click on Close/Maximize/Minimize
        # never also gets interpreted as a click on whatever happens to
        # be underneath it in the active scene.
        if self.audio_controls.handle_event(event):
            return
        if self.window_controls.handle_event(event):
            return
        if self._current:
            self._current.handle_event(event)

    def update(self, dt):
        sw, sh = self.screen.get_size()
        self.window_controls.update(dt, sw, sh, pygame.mouse.get_pos())
        self.audio_controls.update(dt, sw, sh, pygame.mouse.get_pos())
        self.ad_banner.update(dt)
        if self._current:
            self._current.update(dt)
        # Single chokepoint for both the persisted toggles (so Settings,
        # load_settings(), and reset_to_defaults() all take effect without
        # each needing their own hook) and the actual per-frame crossfade.
        gm = getattr(self, 'gm', None)
        if gm is not None:
            self.assets.music.enabled = getattr(gm, 'music_enabled', True)
            self.assets.music.volume = getattr(gm, 'music_volume', 0.7)
            self.assets.sfx_enabled = getattr(gm, 'sfx_enabled', True)
            self.assets._sound_volume = getattr(gm, 'sfx_volume', 0.7)
        self.assets.music.update(dt)

    def draw(self):
        if self._current:
            self._current.draw(self.screen)
        # Ad banner drawn after the scene but before the corner controls,
        # which always take visual priority (drawn last so they're always
        # reachable — see below).
        self.ad_banner.draw(self.screen, self)
        # Drawn last so they're always on top — including over
        # GameplayScene's pause overlay, which is exactly what lets a
        # paused player still reach these controls (see the ESC/pause fix
        # in main.py).
        self.window_controls.draw(self.screen)
        self.audio_controls.draw(self.screen)


class WindowControls:
    """Minimize / maximize / close controls shown top-right on every
    screen — main menu, mode select, settings, rules, and gameplay
    (including while paused) — instead of being duplicated per-scene.

    Hidden by default. Fades in when the mouse nears the top-right
    corner (or is directly over one of the three buttons) and fades back
    out shortly after the mouse leaves, so they don't sit permanently on
    top of menu art but are still easy to find."""

    # Base (1280x800, scale=1.0) pixel geometry — every value below is
    # this times get_chrome_scale(sw, sh), recomputed every frame in
    # _layout() so the buttons (and AudioControls/AdBanner, which anchor
    # off these real rects rather than duplicating the numbers) always
    # match the current resolution.
    BASE_BTN_W    = 34
    BASE_BTN_H    = 28
    BASE_MARGIN   = 10   # inset from the top/right screen edge
    BASE_GAP      = 10   # gap between adjacent buttons in the cluster
    BASE_REVEAL_ZONE_W = 170   # px from the right edge that counts as "near"
    BASE_REVEAL_ZONE_H = 70    # px from the top edge that counts as "near"
    HOLD_SECONDS  = 0.7   # stay visible this long after mouse leaves
    FADE_SECONDS  = 0.25  # fade duration each way

    def __init__(self, font: pygame.font.Font):
        self._maximized = False
        self.alpha  = 0.0
        self._hold  = 0.0
        # Scaled every frame by _layout() — start at the base (1x)
        # values so anything reading these before the first update()
        # call still gets a sane number.
        self.reveal_zone_w = self.BASE_REVEAL_ZONE_W
        self.reveal_zone_h = self.BASE_REVEAL_ZONE_H
        # Set by main.py once the real window-recreation function is
        # available. Preferred over calling pygame.display.toggle_fullscreen()
        # directly — see _do_toggle_maximize for why.
        self.on_toggle_fullscreen: Optional[Callable[[bool], None]] = None

        self._btn_close = Button(
            pygame.Rect(0, 0, 34, 28), "", font,
            color=(140, 30, 30), hover_color=(200, 50, 50),
            on_click=self._do_close)
        self._btn_maximize = Button(
            pygame.Rect(0, 0, 34, 28), "", font,
            color=(60, 60, 80), hover_color=(90, 90, 120),
            on_click=self._do_toggle_maximize)
        self._btn_minimize = Button(
            pygame.Rect(0, 0, 34, 28), "", font,
            color=(60, 60, 80), hover_color=(90, 90, 120),
            on_click=self._do_minimize)
        self._buttons = [self._btn_minimize, self._btn_maximize, self._btn_close]

    # ── actions ──────────────────────────────────────────────────────────
    def _do_close(self):
        pygame.event.post(pygame.event.Event(pygame.QUIT))

    def _do_toggle_maximize(self):
        self._maximized = not self._maximized
        if self.on_toggle_fullscreen:
            # Rebuilds the window in one shot with the flags for the
            # target state baked in — see main.py for why this replaced
            # the old pygame.display.toggle_fullscreen() call.
            self.on_toggle_fullscreen(self._maximized)
        else:
            try:
                pygame.display.toggle_fullscreen()
            except Exception:
                pass

    def _do_minimize(self):
        try:
            pygame.display.iconify()
        except Exception:
            pass

    # ── layout / update / draw ───────────────────────────────────────────
    def _layout(self, sw: int, sh: int):
        scale = get_chrome_scale(sw, sh)
        btn_w  = round(self.BASE_BTN_W * scale)
        btn_h  = round(self.BASE_BTN_H * scale)
        margin = round(self.BASE_MARGIN * scale)
        gap    = round(self.BASE_GAP * scale)
        step   = btn_w + gap
        wc_y = margin
        wc_x = sw - margin - btn_w
        self._btn_close.rect    = pygame.Rect(wc_x,          wc_y, btn_w, btn_h)
        self._btn_maximize.rect = pygame.Rect(wc_x - step,   wc_y, btn_w, btn_h)
        self._btn_minimize.rect = pygame.Rect(wc_x - 2*step, wc_y, btn_w, btn_h)
        self.reveal_zone_w = round(self.BASE_REVEAL_ZONE_W * scale)
        self.reveal_zone_h = round(self.BASE_REVEAL_ZONE_H * scale)

    def update(self, dt: float, sw: int, sh: int, mouse_pos: Tuple[int, int]):
        self._layout(sw, sh)
        mx, my = mouse_pos
        near_corner = (mx >= sw - self.reveal_zone_w) and (0 <= my <= self.reveal_zone_h)
        over_btn = any(b.rect.collidepoint(mouse_pos) for b in self._buttons)
        self._hold = self.HOLD_SECONDS if (near_corner or over_btn) else max(0.0, self._hold - dt)

        target = 255.0 if self._hold > 0 else 0.0
        speed = 255.0 / self.FADE_SECONDS
        if self.alpha < target:
            self.alpha = min(target, self.alpha + speed * dt)
        else:
            self.alpha = max(target, self.alpha - speed * dt)

        # Buttons only react to the real cursor once mostly visible —
        # otherwise a button fading out could still flash a hover state.
        active_mouse = mouse_pos if self.alpha > 40 else (-10000, -10000)
        for b in self._buttons:
            b.update(dt, active_mouse)

    def handle_event(self, event) -> bool:
        """Returns True if a button consumed this event, so callers can
        skip forwarding it to whatever's underneath."""
        if self.alpha < 40:
            return False  # hidden/fading — ignore clicks on ghost buttons
        consumed = False
        for b in self._buttons:
            if b.handle_event(event):
                consumed = True
        return consumed

    def draw(self, surf: pygame.Surface):
        if self.alpha <= 2:
            return
        left   = self._btn_minimize.rect.left - 6
        top    = self._btn_minimize.rect.top - 6
        right  = self._btn_close.rect.right + 6
        bottom = self._btn_close.rect.bottom + 6
        cluster_rect = pygame.Rect(left, top, right - left, bottom - top)

        tmp = pygame.Surface(cluster_rect.size, pygame.SRCALPHA)
        icons = {
            id(self._btn_minimize): 'minimize',
            id(self._btn_maximize): 'restore' if self._maximized else 'maximize',
            id(self._btn_close):    'close',
        }
        for b in self._buttons:
            saved_rect = b.rect
            b.rect = saved_rect.move(-cluster_rect.left, -cluster_rect.top)
            b.draw(tmp)
            draw_icon(tmp, b.rect, icons[id(b)], WHITE)
            b.rect = saved_rect
        tmp.set_alpha(int(self.alpha))
        surf.blit(tmp, cluster_rect.topleft)


class AudioControls:
    """Shared sound-effects / music on-off toggles, drawn top-right on
    every screen — main menu through gameplay (including while paused)
    — the audio counterpart to WindowControls. Unlike WindowControls
    these stay fully visible at all times rather than fading in near
    the corner, matching how the sound-effects toggle already behaved
    back when it lived only in GameplayScene.

    Sits immediately to the left of wherever WindowControls' cluster
    would be, so the two never overlap once WindowControls fades in."""

    # Base (1280x800, scale=1.0) pixel geometry — scaled every frame by
    # get_chrome_scale(sw, sh) in _layout(), same as WindowControls.
    BASE_BTN_W = 44
    BASE_BTN_H = 28
    BASE_GAP        = 6   # gap between the sfx and music buttons
    BASE_CLUSTER_GAP = 6  # gap between this cluster and WindowControls'

    def __init__(self, manager: 'SceneManager', font: pygame.font.Font):
        self.manager = manager
        self._btn_sfx = Button(
            pygame.Rect(0, 0, self.BASE_BTN_W, self.BASE_BTN_H), "", font,
            color=(50, 70, 50), hover_color=(70, 100, 70),
            on_click=self._toggle_sfx)
        self._btn_music = Button(
            pygame.Rect(0, 0, self.BASE_BTN_W, self.BASE_BTN_H), "", font,
            color=(50, 70, 50), hover_color=(70, 100, 70),
            on_click=self._toggle_music)
        self._buttons = [self._btn_sfx, self._btn_music]

    # ── actions ──────────────────────────────────────────────────────────
    def _toggle_sfx(self):
        gm = self.manager.gm
        if gm is None:
            return
        gm.sfx_enabled = not getattr(gm, 'sfx_enabled', True)
        save_settings(gm)

    def _toggle_music(self):
        gm = self.manager.gm
        if gm is None:
            return
        gm.music_enabled = not getattr(gm, 'music_enabled', True)
        save_settings(gm)

    # ── layout / update / draw ───────────────────────────────────────────
    def _layout(self, sw: int, sh: int):
        scale = get_chrome_scale(sw, sh)
        btn_w = round(self.BASE_BTN_W * scale)
        btn_h = round(self.BASE_BTN_H * scale)
        gap = round(self.BASE_GAP * scale)
        cluster_gap = round(self.BASE_CLUSTER_GAP * scale)
        # Anchored off WindowControls' own (already-scaled) rect rather
        # than duplicating its geometry here — SceneManager.update() runs
        # WindowControls.update() first every frame, so by the time this
        # runs, .rect is current for this frame. Falls back to a bare
        # right-edge margin if WindowControls hasn't laid out yet (e.g. a
        # standalone unit test constructing AudioControls in isolation).
        wc = getattr(self.manager, 'window_controls', None)
        if wc is not None and wc._btn_minimize.rect.width > 0:
            wc_left = wc._btn_minimize.rect.left
            top = wc._btn_minimize.rect.top
        else:
            wc_left = sw - round(10 * scale) - round(34 * scale)
            top = round(10 * scale)
        music_x = wc_left - cluster_gap - btn_w
        sfx_x = music_x - (btn_w + gap)
        self._btn_sfx.rect   = pygame.Rect(sfx_x, top, btn_w, btn_h)
        self._btn_music.rect = pygame.Rect(music_x, top, btn_w, btn_h)

    def update(self, dt: float, sw: int, sh: int, mouse_pos: Tuple[int, int]):
        self._layout(sw, sh)
        for b in self._buttons:
            b.update(dt, mouse_pos)

    def handle_event(self, event) -> bool:
        consumed = False
        for b in self._buttons:
            if b.handle_event(event):
                consumed = True
        return consumed

    def draw(self, surf: pygame.Surface):
        gm = self.manager.gm
        sfx_on   = getattr(gm, 'sfx_enabled', True) if gm is not None else True
        music_on = getattr(gm, 'music_enabled', True) if gm is not None else True
        self._btn_sfx.draw(surf)
        draw_icon(surf, self._btn_sfx.rect, 'unmute' if sfx_on else 'mute', WHITE)
        self._btn_music.draw(surf)
        draw_icon(surf, self._btn_music.rect, 'music_on' if music_on else 'music_off', WHITE)


# ─── Ad banner slot (placeholder — no real ad network wired in yet) ─────────
# Scenes on which the banner is eligible to show at all (subject to the
# ads_enabled setting). Chuo and Settings are deliberately excluded —
# they stay ad-free regardless of ads_enabled.
AD_ELIGIBLE_SCENES = {
    'main_menu', 'mode_select', 'multiplayer_menu', 'lan_menu',
    'lan_host_lobby', 'lan_join', 'internet_menu', 'internet_lobby',
    'gameplay',
}


def _ads_showing(manager: 'SceneManager') -> bool:
    """Whether the ad banner should render right now: ads_enabled (the
    dev/testing SETTING) AND NOT ads_removed (the per-player PURCHASE
    flag in profile.json — Part 5) AND the current scene is one of the
    eligible ones. All three conditions, independently — ads_enabled and
    ads_removed are deliberately checked as two separate, unrelated
    gates rather than folded into one, since they come from two
    different files with two different lifecycles (a settings reset
    must never touch ads_removed, and vice versa). Centralized here so
    GameplayScene's board-layout push-down and the AdBanner's own draw()
    can never disagree about whether ads are "on" for this frame."""
    gm = getattr(manager, 'gm', None)
    if gm is None or not getattr(gm, 'ads_enabled', True):
        return False
    # ads_removed lives on the profile of THIS device's own player, which
    # is a per-device/per-purchase concept independent of which network
    # role is currently active — during LAN/Internet play manager.gm is
    # temporarily swapped to a ClientGameManager (no .profile attribute
    # at all), so this always reads from manager.singleplayer_gm instead
    # of manager.gm, the same stable reference GameplayScene.on_exit()
    # restores sm.gm from. Otherwise a player who paid to remove ads
    # would see them return the moment they joined a LAN/Internet match.
    local_gm = getattr(manager, 'singleplayer_gm', None) or gm
    profile = getattr(local_gm, 'profile', None)
    if profile is not None and profile.get('ads_removed', False):
        return False
    return manager._current_name in AD_ELIGIBLE_SCENES


class AdBanner:
    """Static placeholder banner ad slot — full-width strip along the top
    of the screen, drawn centrally (like WindowControls/AudioControls)
    so every eligible scene gets it automatically instead of each scene
    needing its own copy of this logic.

    Placeholder-only: a plain rounded rect + "Advertisement" text via the
    existing font rendering, cycling through a small rotation every ~20s.
    No image assets, no network calls, no real ad-SDK integration — that
    is an explicit later step once there's an actual ad-network account.

    Horizontal placement: centered within the gap between whatever's
    already anchored in the top corners — AudioControls/WindowControls on
    the right always, and (GameplayScene only) the Menu/Pause buttons on
    the left — rather than stretched to fill that entire gap. The banner's
    own width/height are now computed dynamically per resolution
    (get_banner_size() in constants.py), anchored to real IAB standard
    banner sizes and scaled up from there, instead of a flat 34px sliver
    that either stretched absurdly wide at large resolutions or stayed a
    fixed thin height while everything else on screen got bigger around
    it. Vertical placement: a strip in the same header row as those corner
    controls — every eligible scene's own title/content starts well below
    this banner's bottom edge, so no other scene needs to shift anything
    to make room. GameplayScene is the one exception (its human hand +
    turn indicator share that same horizontal-center strip) — see
    GameplayScene._ad_top_pad() and BoardRenderer's top_margin, which push
    the whole table down by get_ad_reserved_top() to clear it there
    instead.

    When ads_enabled is False, draw() simply returns — no layout space
    is reserved anywhere for it (GameplayScene's push-down is driven by
    the same _ads_showing() check), so disabling ads leaves no dead
    space behind.
    """

    ROTATE_SECS = 20.0
    # (background color, label) — plain generated placeholders, not real
    # ad creative, since there's no ad network wired in yet anyway.
    CREATIVES = [
        ((45, 60, 80), "Advertisement"),
        ((60, 50, 75), "Your Ad Could Be Here"),
        ((50, 65, 55), "KADI — Remove Ads in Settings"),
    ]

    def __init__(self, assets: AssetLoader):
        self.assets = assets
        self._t = 0.0
        self._idx = 0

    def update(self, dt: float):
        self._t += dt
        if self._t >= self.ROTATE_SECS:
            self._t -= self.ROTATE_SECS
            self._idx = (self._idx + 1) % len(self.CREATIVES)

    def draw(self, surf: pygame.Surface, manager: 'SceneManager'):
        if not _ads_showing(manager):
            return
        sw, sh = surf.get_size()
        bw, bh = get_banner_size(sw, sh)
        # Both insets are derived from the corner controls' actual current
        # rects (not hardcoded pixel numbers) — see the doc comment above:
        # this is what keeps the banner correctly clear of those controls
        # now that WindowControls/AudioControls/Menu-Pause are all
        # resolution-scaled themselves.
        # Both insets are derived from the corner controls' actual current
        # rects (not hardcoded pixel numbers) — see the doc comment above:
        # this is what keeps the banner correctly clear of those controls
        # now that WindowControls/AudioControls/Menu-Pause are all
        # resolution-scaled themselves. Left/right use different gap
        # constants (10 vs 12) because that's what the original hardcoded
        # 210/244 actually worked out to relative to Pause's right edge
        # (200) and the audio cluster's left edge (sw-232) — matching
        # them keeps 1280x800 pixel-identical to before this pass.
        cs = get_chrome_scale(sw, sh)
        left_gap = round(10 * cs)
        right_gap = round(12 * cs)
        gameplay_scene = manager._scenes.get('gameplay')
        pause_btn = getattr(gameplay_scene, '_btn_pause', None)
        if manager._current_name == 'gameplay' and pause_btn is not None and pause_btn.rect.width > 0:
            left_x = pause_btn.rect.right + left_gap
        else:
            left_x = 8
        sfx_rect = manager.audio_controls._btn_sfx.rect
        if sfx_rect.width > 0:
            right_x = sfx_rect.left - right_gap
        else:
            right_x = sw - 244   # defensive fallback if audio controls haven't laid out yet
        avail_w = right_x - left_x
        if avail_w < 120:
            # Extreme edge case (very narrow window) — not worth showing
            # a squashed sliver of a banner.
            return
        width = min(bw, avail_w)
        rect_x = left_x + (avail_w - width) // 2  # centered in the gap
        rect = pygame.Rect(rect_x, AD_BANNER_Y, width, bh)
        bg_color, label = self.CREATIVES[self._idx]
        panel = pygame.Surface(rect.size, pygame.SRCALPHA)
        pygame.draw.rect(panel, (*bg_color, 210), panel.get_rect(), border_radius=6)
        pygame.draw.rect(panel, (*WHITE, 50), panel.get_rect(), width=1, border_radius=6)
        surf.blit(panel, rect.topleft)
        # Font scales with the banner's own height, not the general UI
        # font_scale — a 250px-tall Billboard-tier banner at 8K needs much
        # bigger label text than a 50px Mobile-Leaderboard one at 1024px,
        # independent of how big everything else on screen is.
        font_scale = max(0.8, bh / 50)
        font = self.assets.font_scaled('ui_small', font_scale)
        txt = font.render(label, True, (*WHITE, 220))
        surf.blit(txt, (rect.centerx - txt.get_width() // 2,
                        rect.centery - txt.get_height() // 2))
        # Small "Ad" tag, bottom-right corner of the strip, so it reads
        # unambiguously as a placeholder ad slot rather than a game panel.
        tag_font = self.assets.font_scaled('ui_small', max(0.7, font_scale * 0.85))
        tag = tag_font.render("Ad", True, (*WHITE, 140))
        surf.blit(tag, (rect.right - tag.get_width() - 6, rect.bottom - tag.get_height() - 3))


# ─── Slider widget ────────────────────────────────────────────────────────────

class Slider:
    """Horizontal slider: value between min_val and max_val."""
    def __init__(self, rect: pygame.Rect, min_val: float, max_val: float,
                 value: float, step: float = 1.0, label: str = "",
                 value_fmt: Optional[Callable[[float], str]] = None):
        self.rect    = rect
        self.min_val = min_val
        self.max_val = max_val
        self.value   = value
        self.step    = step
        self.label   = label
        # Optional formatter for the value shown next to the label —
        # defaults to the original "Xs"/"Off" seconds style below so
        # existing callers don't need to change. Volume sliders pass a
        # percentage formatter instead.
        self.value_fmt = value_fmt
        self._dragging = False

    def handle_event(self, event) -> bool:
        hit_rect = self.rect.inflate(0, 24)   # generous vertical grab area
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hit_rect.collidepoint(event.pos):
                self._dragging = True
                self._set_from_x(event.pos[0])
                return True
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False
        if event.type == pygame.MOUSEMOTION and self._dragging:
            self._set_from_x(event.pos[0])
            return True
        return False

    def _set_from_x(self, x: int):
        t = max(0.0, min(1.0, (x - self.rect.x) / self.rect.width))
        raw = self.min_val + t * (self.max_val - self.min_val)
        self.value = round(raw / self.step) * self.step
        self.value = max(self.min_val, min(self.max_val, self.value))

    def draw(self, surf: pygame.Surface, font: pygame.font.Font):
        # Track
        pygame.draw.rect(surf, (50, 80, 55), self.rect, border_radius=4)
        # Fill
        t = (self.value - self.min_val) / (self.max_val - self.min_val)
        fill_w = int(self.rect.width * t)
        if fill_w > 0:
            fill_r = pygame.Rect(self.rect.x, self.rect.y, fill_w, self.rect.height)
            pygame.draw.rect(surf, GOLD, fill_r, border_radius=4)
        # Border
        pygame.draw.rect(surf, (*WHITE, 80), self.rect, width=1, border_radius=4)
        # Knob
        knob_x = self.rect.x + fill_w
        pygame.draw.circle(surf, WHITE, (knob_x, self.rect.centery), 9)
        pygame.draw.circle(surf, GOLD, (knob_x, self.rect.centery), 7)
        # Value label
        if self.value_fmt is not None:
            val_str = self.value_fmt(self.value)
        else:
            val_str = f"{int(self.value)}s" if self.value >= 1 else "Off"
        lbl = font.render(f"{self.label}: {val_str}", True, WHITE)
        surf.blit(lbl, (self.rect.x, self.rect.y - lbl.get_height() - 4))


def fit_stack_start_y(preferred_top: int, total_h: int, sh: int, bottom_margin: int = 40) -> int:
    """Shared by every scene that lays out a vertical stack of buttons
    (Main Menu, Multiplayer, LAN) — returns the y to start the stack at.
    Normally that's just `preferred_top`, but if the stack's actual
    height (`total_h`, already resolution-scaled) would run past the
    bottom edge, this pulls the whole stack up just far enough to keep
    the last button fully on screen, with a small margin at the very
    bottom. Centralizes the fix originally written for MainMenuScene
    (Quit landing ~30px off-screen at 1024x640) so every button-stack
    scene gets the same off-screen protection instead of only the one
    that happened to hit the bug first."""
    if preferred_top + total_h > sh - bottom_margin:
        return max(10, sh - bottom_margin - total_h)
    return preferred_top


# ─── Main Menu ────────────────────────────────────────────────────────────────

class MainMenuScene(Scene):
    HELP_SECTIONS = [
        ("What each button does", [
            "Play vs AI — a single-player game against 1-5 computer "
            "opponents, with adjustable difficulty.",
            "Multiplayer — play with other people: on this device "
            "(hot-seat), over a local network (LAN), or with anyone "
            "online (Internet, via KADI's own server).",
            "How to Play — the full rules reference, built from the "
            "actual rules the game enforces.",
            "Settings — timers, jokers per deck, logging, hints, "
            "display resolution, and sound.",
            "Chuo (Swahili for \"university\") — train your own AI "
            "model (MSOMI) from your own logged games, then attach it "
            "to an AI opponent in Play vs AI.",
            "Profile — your badges, unlocked cosmetics (card backs and "
            "felt themes), and local/global leaderboards.",
        ]),
    ]

    def on_enter(self, **kwargs):
        self._stars = [
            {'x': random.randint(0, 1280), 'y': random.randint(0, 800),
             'r': random.uniform(1, 3), 'spd': random.uniform(0.2, 0.8)}
            for _ in range(80)
        ]
        self._t = 0.0
        self._rebuild_buttons()

        cs = get_chrome_scale(*self.gm.resolution)
        self._help = HelpOverlay("KADI — Quick Guide", self.HELP_SECTIONS,
                                 self.assets.font_scaled('ui_large', cs),
                                 self.assets.font_scaled('ui_medium', cs),
                                 self.assets.font_scaled('ui_normal', cs))
        self._help_btn = make_help_button(pygame.Rect(0, 0, 1, 1),
                                          self.assets.font_scaled('ui_small', cs),
                                          on_click=self._help.open)

    def _layout_help_btn(self, sw: int, sh: int):
        ac = getattr(self.manager, 'audio_controls', None)
        cs = get_chrome_scale(sw, sh)
        sz = round(32 * cs)
        if ac is not None and ac._btn_sfx.rect.width > 0:
            x = ac._btn_sfx.rect.left - round(6 * cs) - sz
            y = ac._btn_sfx.rect.top
        else:
            x, y = sw - round(10 * cs) - sz, round(10 * cs)
        self._help_btn.rect = pygame.Rect(x, y, sz, sz)

    def _rebuild_buttons(self):
        sw, sh = self.gm.resolution
        cx = sw // 2
        chrome_scale = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', chrome_scale)
        btn_w = round(260 * chrome_scale)
        half_w = btn_w // 2
        self._has_save = save_manager.has_save_file()

        # Anchored to the title block's OWN actual rendered position
        # (see draw()'s title/sub placement — sh//4, then +64*cs) rather
        # than an independent sh//2-90 formula: that old formula and the
        # title block's position both happened to scale with sh, but by
        # different, unrelated math, so the gap between them wasn't
        # fixed — it collapsed to almost nothing at 1024x640 (the
        # subtitle's own underline was touching the first button) while
        # opening into a large, unbalanced gap at 3840x2160+. Deriving
        # top_margin from where the subtitle block actually ends keeps
        # a real, fixed, proportional gap between the two at every
        # resolution instead of leaving it to coincidence.
        title_h = self.assets.font_scaled('ui_title', chrome_scale).get_height()
        sub_h = self.assets.font_scaled('ui_medium', chrome_scale).get_height()
        subtitle_bottom = sh // 4 + round(64 * chrome_scale) + sub_h
        gap_after_title = round(40 * chrome_scale)
        top_margin, bottom_margin = subtitle_bottom + gap_after_title, 40
        n_buttons = 7 + (1 if self._has_save else 0)
        avail_h = sh - top_margin - bottom_margin
        step_min, step_max = round(50 * chrome_scale), round(65 * chrome_scale)
        step = max(step_min, min(step_max, avail_h // n_buttons))
        btn_h_min, btn_h_max = round(38 * chrome_scale), round(52 * chrome_scale)
        btn_h = max(btn_h_min, min(btn_h_max, step - round(8 * chrome_scale)))
        y = top_margin
        # If even the minimum sizing doesn't fit (extreme edge case),
        # pull the whole stack up instead of letting it run off either
        # edge.
        total_h = step * (n_buttons - 1) + btn_h
        if top_margin + total_h > sh - 10:
            y = max(10, sh - 10 - total_h)

        self._buttons = []
        if self._has_save:
            self._buttons.append(
                Button(pygame.Rect(cx - half_w, y, btn_w, btn_h), "Continue Game", font_lg,
                       color=(180, 140, 20), hover_color=(215, 170, 40),
                       on_click=self._continue_game))
            y += step

        self._buttons += [
            Button(pygame.Rect(cx - half_w, y, btn_w, btn_h), "Play vs AI", font_lg,
                   on_click=lambda: self.manager.switch('mode_select', vs_ai=True)),
            Button(pygame.Rect(cx - half_w, y + step, btn_w, btn_h), "Multiplayer", font_lg,
                   color=(60, 90, 130), hover_color=(80, 120, 165),
                   on_click=lambda: self.manager.switch('multiplayer_menu')),
            Button(pygame.Rect(cx - half_w, y + step*2, btn_w, btn_h), "How to Play", font_lg,
                   color=(50, 90, 120), hover_color=(70, 120, 155),
                   on_click=lambda: self.manager.switch('rules')),
            Button(pygame.Rect(cx - half_w, y + step*3, btn_w, btn_h), "Settings", font_lg,
                   color=(80, 60, 120), hover_color=(110, 85, 160),
                   on_click=lambda: self.manager.switch('settings')),
            Button(pygame.Rect(cx - half_w, y + step*4, btn_w, btn_h), "Chuo", font_lg,
                   color=(140, 100, 20), hover_color=(180, 130, 30),
                   on_click=lambda: self.manager.switch('chuo')),
            Button(pygame.Rect(cx - half_w, y + step*5, btn_w, btn_h), "Profile", font_lg,
                   color=(30, 110, 90), hover_color=(45, 140, 115),
                   on_click=lambda: self.manager.switch('profile')),
            Button(pygame.Rect(cx - half_w, y + step*6, btn_w, btn_h), "Quit", font_lg,
                   color=(120, 40, 40), hover_color=(160, 60, 60),
                   on_click=lambda: pygame.event.post(pygame.event.Event(pygame.QUIT))),
        ]

    def _continue_game(self):
        if save_manager.load_game(self.gm):
            # Continuing consumes the save slot — if the player exits
            # mid-game again, a fresh save is written reflecting the new
            # progress. Prevents ever resuming a stale/already-finished
            # save.
            save_manager.delete_save_file()
            self.manager.switch('gameplay', resume=True)
        else:
            # Corrupt/unreadable save — don't leave a dead "Continue"
            # button around forever.
            save_manager.delete_save_file()
            self._has_save = False
            self._rebuild_buttons()

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        self._help.notice_activity()
        if self._help.handle_event(event, sw, sh):
            return
        self._help_btn.handle_event(event)
        for btn in self._buttons:
            btn.handle_event(event)

    def update(self, dt):
        sw, sh = self.gm.resolution
        self._layout_help_btn(sw, sh)
        self._help.update_idle_glow(dt)
        self._t += dt
        mp = pygame.mouse.get_pos()
        self._help_btn.update(dt, mp)
        for btn in self._buttons:
            btn.update(dt, mp)
        for star in self._stars:
            star['y'] = (star['y'] + star['spd']) % self.gm.resolution[1]

        # Chuo hover easter egg: the "Chuo" button is always the last one
        # in _buttons (see _rebuild_buttons) — collidepoint check rather
        # than btn._hovered so this doesn't depend on Button's private
        # animation-timing internals.
        chuo_btn = next((b for b in self._buttons if b.text == "Chuo"), None)
        if chuo_btn is not None:
            self.assets.music.set_chuo_hover(chuo_btn.rect.collidepoint(mp))

    def draw(self, surf):
        sw, sh = self.gm.resolution
        for y in range(sh):
            t = y / sh
            pygame.draw.line(surf, (int(8+20*t), int(20+40*t), int(35+55*t)), (0,y),(sw,y))
        for star in self._stars:
            a = int(150 + 100 * math.sin(self._t * 0.8 + star['x']))
            s = pygame.Surface((int(star['r']*2), int(star['r']*2)), pygame.SRCALPHA)
            pygame.draw.circle(s, (*WHITE, a), (int(star['r']), int(star['r'])), int(star['r']))
            surf.blit(s, (int(star['x']), int(star['y'])))

        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        title_font = self.assets.font_scaled('ui_title', cs)
        title = title_font.render("KADI", True, GOLD_LIGHT)
        for ox, oy in [(2,2),(-2,-2),(2,-2),(-2,2)]:
            g = title_font.render("KADI", True, (180,120,0))
            surf.blit(g, (cx - title.get_width()//2 + ox, sh//4 + oy))
        surf.blit(title, (cx - title.get_width()//2, sh//4))

        sub = self.assets.font_scaled('ui_medium', cs).render("The Card Game", True, (*WHITE, 180))
        surf.blit(sub, (cx - sub.get_width()//2, sh//4 + s(64)))

        for i, suit in enumerate(Suit):
            angle = self._t * 0.4 + i * math.pi / 2
            orbit_r = s(200)
            sx = cx + orbit_r * math.cos(angle)
            sy = sh//4 + s(104) + s(30) * math.sin(angle)
            sym_sz = s(24)
            sym = pygame.Surface((sym_sz, sym_sz), pygame.SRCALPHA)
            draw_icon(sym, sym.get_rect(), SUIT_ICON[suit], (*SUIT_COLOR[suit], 120), width=2)
            surf.blit(sym, (int(sx), int(sy)))

        for btn in self._buttons:
            btn.draw(surf)

        ver = self.assets.font_scaled('ui_tiny', cs).render(f"v{VERSION} — Python/Pygame", True, (*WHITE, 80))
        surf.blit(ver, (s(10), sh - s(20)))

        self._help.draw_button_glow(surf, self._help_btn.rect)
        self._help_btn.draw(surf)
        self._help.draw(surf)


# ─── Profile ───────────────────────────────────────────────────────────────

class ProfileScene(Scene):
    """Stats, badges, and cosmetics inventory (Profile Part 4). Reads/
    writes self.gm.profile directly — same dict GameManager reads for
    undo tokens and ads_removed, so equip/badge changes here are visible
    immediately in-game with no reload needed."""

    def on_enter(self, **kwargs):
        self.scroll_offset = 0.0
        self._content_height = 0
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', cs)
        self._back_btn = Button(pygame.Rect(20, 16, round(120 * cs), round(40 * cs)),
                                 "< Back", font_lg,
                                 color=(70, 70, 70), hover_color=(95, 95, 95),
                                 on_click=lambda: self.manager.switch('main_menu'))
        self._equip_buttons: list = []  # rebuilt each draw() call to reflect current scroll position
        # Persistent across frames (unlike _equip_buttons above) — Button
        # tracks its own _pressed state between mouse-down and mouse-up,
        # so the SAME instance must see both events. Keyed by
        # (kind, style_key); _draw_cosmetic_row repositions the cached
        # button's rect each frame instead of constructing a new one.
        self._equip_button_cache: dict = {}
        # Cosmetic info bubble: hover shows it, click pins/unpins it
        # (useful on touch or if the mouse can't linger). Covers BOTH
        # locked swatches (shows the unlock requirement) and already-
        # unlocked ones (shows which badge earned it) — see
        # _draw_cosmetic_row. Rebuilt each draw() call; the pinned key
        # persists across frames until toggled off or the scene re-enters.
        self._cosmetic_hitboxes: list = []   # [(rect, key, label_text), ...]
        self._hover_tooltip_key = None
        self._pinned_tooltip_key = None
        # Badge Share buttons (Part C) — see _draw badges loop and
        # _share_badge below. Cache follows the same rule as
        # _equip_button_cache: Button must be the SAME instance across
        # frames to track its own pressed state between mouse-down/up.
        self._badge_share_button_cache: dict = {}
        self._badge_share_buttons: list = []
        self._badge_share_status: str = ""
        # Only one badge's platform-picker row open at a time (same
        # single-open-at-a-time rule as _pinned_tooltip_key above) —
        # avoids a wall of platform buttons if several badges got
        # clicked in a row.
        self._badge_share_menu_open: Optional[str] = None
        self._badge_share_platform_buttons: list = []
        self._badge_share_platform_button_cache: dict = {}

    def _profile(self) -> dict:
        return self.gm.profile if self.gm.profile is not None else profile_store.default_profile()

    def _max_scroll(self, sh: int) -> int:
        viewport_h = sh - 80
        return max(0, self._content_height - viewport_h)

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        self._back_btn.handle_event(event)
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = _scroll_wheel_delta(
                self.scroll_offset, event.y, 50, self._max_scroll(sh))
            return
        for btn in self._equip_buttons:
            btn.handle_event(event)
        for btn in self._badge_share_buttons:
            btn.handle_event(event)
        for _key, btn in self._badge_share_platform_buttons:
            btn.handle_event(event)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            clicked_key = None
            for rect, key, _hint in self._cosmetic_hitboxes:
                if rect.collidepoint(event.pos):
                    clicked_key = key
                    break
            # Tap a swatch to pin its tooltip open (handy on touch, or
            # for anyone who doesn't want to hold the mouse still); tap
            # it again, or anywhere else, to dismiss.
            self._pinned_tooltip_key = (None if clicked_key == self._pinned_tooltip_key
                                        else clicked_key)

    def update(self, dt):
        mp = pygame.mouse.get_pos()
        self._back_btn.update(dt, mp)
        for btn in self._equip_buttons:
            btn.update(dt, mp)
        for btn in self._badge_share_buttons:
            btn.update(dt, mp)
        for _key, btn in self._badge_share_platform_buttons:
            btn.update(dt, mp)
        self._hover_tooltip_key = None
        for rect, key, _hint in self._cosmetic_hitboxes:
            if rect.collidepoint(mp):
                self._hover_tooltip_key = key
                break

    def _equip_card_back(self, style_key: str):
        p = self._profile()
        if style_key not in p['cosmetics']['owned_card_backs']:
            return
        p['cosmetics']['equipped_card_back'] = style_key
        self.assets.set_equipped_card_back(style_key)
        profile_store.save_profile(p)

    def _equip_felt_theme(self, theme_key: str):
        p = self._profile()
        if theme_key not in p['cosmetics']['owned_felt_themes']:
            return
        p['cosmetics']['equipped_felt_theme'] = theme_key
        self.manager.board.set_felt_theme(theme_key)
        profile_store.save_profile(p)

    def _share_badge_toggle(self, badge_id: str):
        """The badge Share button no longer shares directly — it
        opens/closes a small per-platform picker row right under that
        badge (see the loop in draw() below), mirroring the pinned-
        tooltip toggle pattern already used for cosmetic swatches
        above. Only one badge's picker is open at a time."""
        self._badge_share_menu_open = (
            None if self._badge_share_menu_open == badge_id else badge_id)

    def _share_badge(self, badge_id: str, platform_key: str):
        """Part C: render + save a shareable PNG for an earned badge,
        then open a pre-filled share-compose window on `platform_key`.
        See core/social_share.py and rendering/share_card.py for the
        actual image/URL work — this just supplies the badge-specific
        text and player name."""
        info = profile_store.BADGE_DEFS.get(badge_id)
        if info is None:
            return
        player_name = "Player"
        if self.gm.players:
            humans = [pl for pl in self.gm.players if pl.is_human]
            if humans:
                player_name = humans[0].name
        card = share_card.render_badge_share_card(
            player_name, info['name'], info['desc'],
            self.assets.font('kadi_banner'), self.assets.font('ui_large'),
            self.assets.font('ui_medium'), self.assets.font('ui_small'))
        tweet_text = social_share.build_badge_share_text(info['name'])
        self._badge_share_status = _save_and_share_card(
            card, f"kadi_badge_{_slugify(badge_id)}", platform_key, tweet_text)
        self._badge_share_menu_open = None

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((14, 22, 18))
        cs = get_chrome_scale(sw, sh)
        font_title = self.assets.font_scaled('ui_title', cs * 0.55)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)
        font_xs = self.assets.font_scaled('ui_small', cs)

        title = font_title.render("Profile", True, GOLD_LIGHT)
        surf.blit(title, (sw // 2 - title.get_width() // 2, 16))

        p = self._profile()
        self._equip_buttons = []
        self._cosmetic_hitboxes = []
        self._badge_share_buttons = []
        self._badge_share_platform_buttons = []
        card_w = max(360, min(get_ui_scale(sw, sh)['menu_w'], sw - 80))
        left = sw // 2 - card_w // 2
        y = 80 - int(self.scroll_offset)
        top0 = y

        clip_rect = pygame.Rect(0, 72, sw, sh - 72)
        prev_clip = surf.get_clip()
        surf.set_clip(clip_rect)

        def panel_header(txt, yy):
            h = font_md.render(txt, True, GOLD_LIGHT)
            surf.blit(h, (left, yy))
            return yy + h.get_height() + 8

        # ── Stats ────────────────────────────────────────────────────────
        y = panel_header("Stats", y)
        gp, gw = p['games_played'], p['games_won']
        lines = [
            f"Single-player — Easy: {gw['single_player'].get('EASY',0)}/{gp['single_player'].get('EASY',0)} won   "
            f"Medium: {gw['single_player'].get('MEDIUM',0)}/{gp['single_player'].get('MEDIUM',0)}   "
            f"Hard: {gw['single_player'].get('HARD',0)}/{gp['single_player'].get('HARD',0)}",
            f"Elimination Mode — Easy: {gw['single_player_elimination'].get('EASY',0)}/{gp['single_player_elimination'].get('EASY',0)}   "
            f"Medium: {gw['single_player_elimination'].get('MEDIUM',0)}/{gp['single_player_elimination'].get('MEDIUM',0)}   "
            f"Hard: {gw['single_player_elimination'].get('HARD',0)}/{gp['single_player_elimination'].get('HARD',0)}",
            f"LAN: {gw['lan']}/{gp['lan']} won     Internet: {gw['internet']}/{gp['internet']} won     "
            f"Hot-seat: {gw['hot_seat']}/{gp['hot_seat']} won",
            f"Total games played: {profile_store.total_games_played(p)}",
            "Multi-card finishes — " + ", ".join(
                f"{k.replace('_',' ').title()}: {v}" for k, v in p['multi_card_finishes'].items()),
            f"MSOMI/Chuo — Models trained: {p['msomi']['models_trained']}   "
            f"Games vs MSOMI: {p['msomi']['games_played_with_msomi']}   "
            f"Won vs MSOMI: {p['msomi']['games_won_with_msomi']}",
            f"Total time played: {int(p['total_time_played_secs'] // 3600)}h "
            f"{int((p['total_time_played_secs'] % 3600) // 60)}m",
            f"Undo tokens: {p['undo_tokens']} / {profile_store.UNDO_TOKENS_MAX}",
        ]
        for line in lines:
            for wrapped in wrap_text(font_xs, line, card_w):
                t = font_xs.render(wrapped, True, (*WHITE, 210))
                surf.blit(t, (left, y))
                y += t.get_height() + 2
        y += 20

        # ── Leaderboard (Part A: local-only, your own record — there's
        # nothing else in profile.json to rank against, so this is
        # framed as "your best modes" rather than a competitive
        # ranking. See InternetLobbyScene's Global Leaderboard tab for
        # the server-backed Internet Multiplayer ranking against other
        # players — that one needs a live server connection this
        # screen doesn't have, so it lives there instead.) ────────────
        y = panel_header("Leaderboard — Your Best Modes", y)
        mode_rows = []
        for key, label in (('lan', 'LAN'), ('internet', 'Internet'), ('hot_seat', 'Hot-seat')):
            played = gp[key]
            if played > 0:
                mode_rows.append((label, gw[key], played))
        for base_key, base_label in (('single_player', 'Single-Player'),
                                     ('single_player_elimination', 'Elimination')):
            for d in profile_store.DIFFICULTIES:
                played = gp[base_key].get(d, 0)
                if played > 0:
                    mode_rows.append((f"{base_label} ({d.title()})",
                                      gw[base_key].get(d, 0), played))
        mode_rows.sort(key=lambda r: (-(r[1] / r[2]), -r[2]))
        if not mode_rows:
            t = font_xs.render("Play a game in any mode to start building your record.",
                               True, (*WHITE, 170))
            surf.blit(t, (left, y))
            y += t.get_height() + 4
        else:
            for rank, (label, wins, played) in enumerate(mode_rows, start=1):
                rate = 100.0 * wins / played
                col = GOLD_LIGHT if rank <= 3 else (*WHITE, 210)
                t = font_xs.render(f"{rank}. {label} — {wins}/{played} won ({rate:.0f}%)",
                                   True, col)
                surf.blit(t, (left, y))
                y += t.get_height() + 3
        y += 6
        best_finish = max(p['multi_card_finishes'].items(), key=lambda kv: kv[1], default=None)
        if best_finish and best_finish[1] > 0:
            t = font_xs.render(
                f"Signature finish: {best_finish[0].replace('_',' ').title()} "
                f"({best_finish[1]} time{'s' if best_finish[1] != 1 else ''})",
                True, (*WHITE, 200))
            surf.blit(t, (left, y))
            y += t.get_height() + 3
        badge_t = font_xs.render(
            f"Badges earned: {len(p['badges'])} / {len(profile_store.BADGE_DEFS)}",
            True, (*WHITE, 200))
        surf.blit(badge_t, (left, y))
        y += badge_t.get_height() + 3
        y += 14

        # ── Badges ───────────────────────────────────────────────────────
        y = panel_header("Badges", y)
        by_cat: Dict[str, list] = {}
        for bid, info in profile_store.BADGE_DEFS.items():
            by_cat.setdefault(info['category'], []).append(bid)
        for cat, bids in by_cat.items():
            cat_t = font_sm.render(cat, True, (*GOLD, 220))
            surf.blit(cat_t, (left, y))
            y += cat_t.get_height() + 4
            for bid in bids:
                info = profile_store.BADGE_DEFS[bid]
                earned = bid in p['badges']
                # Vector marker instead of a Unicode star glyph — this
                # project's font (Poppins) doesn't have ★/☆, and a tofu
                # box is exactly the failure mode already fixed
                # elsewhere for suit/emoji glyphs (see rendering/
                # widgets.py's draw_icon helpers). A small filled-vs-
                # hollow circle reads the same at a glance.
                dot_r = 5
                dot_cx, dot_cy = left + 12 + dot_r, y + dot_r + 2
                if earned:
                    pygame.draw.circle(surf, GOLD_LIGHT, (dot_cx, dot_cy), dot_r)
                else:
                    pygame.draw.circle(surf, (90, 90, 90), (dot_cx, dot_cy), dot_r, width=1)
                # Plain RGB (no alpha component) — relying on per-pixel
                # alpha in a rendered text surface to visibly dim it
                # against an opaque background doesn't reliably read as
                # "greyed out", so earned/locked contrast comes from two
                # genuinely different RGB tones instead.
                col = (235, 235, 235) if earned else (95, 95, 95)
                btn_w, btn_h = round(64 * cs), round(22 * cs)
                # Reserve room for the Share button (earned badges
                # only) so long badge descriptions wrap instead of
                # running underneath it — see the overlap this fixed
                # in an earlier screenshot pass.
                text_max_w = card_w - 26 - (btn_w + 12 if earned else 0)
                text_lines = wrap_text(font_xs, f"{info['name']} — {info['desc']}", text_max_w)
                text_h = 0
                for line in text_lines:
                    lt = font_xs.render(line, True, col)
                    surf.blit(lt, (left + 26, y + text_h))
                    text_h += lt.get_height() + 1
                row_h = max(text_h, dot_r * 2)
                if earned:
                    # Share button (Part C) — only meaningful for a
                    # badge actually earned; nothing to share for a
                    # locked one. Cached per badge id the same way
                    # _draw_cosmetic_row caches its Equip buttons (see
                    # that method's comment) — Button needs to be the
                    # SAME instance across frames to track press state.
                    btn_rect = pygame.Rect(left + card_w - btn_w, y - round(2 * cs), btn_w, btn_h)
                    btn = self._badge_share_button_cache.get(bid)
                    if btn is None:
                        btn = Button(btn_rect, "Share", self.assets.font_scaled('ui_tiny', cs),
                                     color=(30, 110, 160), hover_color=(45, 140, 195),
                                     on_click=(lambda b=bid: self._share_badge_toggle(b)))
                        self._badge_share_button_cache[bid] = btn
                    else:
                        btn.rect = btn_rect
                    btn.draw(surf)
                    self._badge_share_buttons.append(btn)
                    row_h = max(row_h, btn_h)
                    if self._badge_share_menu_open == bid:
                        # Small platform-picker row, reflowed into the
                        # list right under this badge (not an overlay —
                        # an overlay would sit on top of the next
                        # badge's text at this list's line spacing).
                        plat_y = y + row_h + round(6 * cs)
                        plat_bw, plat_bh, plat_gap = round(92 * cs), round(24 * cs), round(6 * cs)
                        px = left + round(26 * cs)
                        for key, label in social_share.SHARE_UI_OPTIONS:
                            cache_key = (bid, key)
                            prect = pygame.Rect(px, plat_y, plat_bw, plat_bh)
                            pbtn = self._badge_share_platform_button_cache.get(cache_key)
                            if pbtn is None:
                                pbtn = Button(prect, label, self.assets.font_scaled('ui_tiny', cs),
                                             color=(45, 45, 65), hover_color=(65, 65, 95),
                                             on_click=(lambda b=bid, k=key: self._share_badge(b, k)))
                                self._badge_share_platform_button_cache[cache_key] = pbtn
                            else:
                                pbtn.rect = prect
                            pbtn.draw(surf)
                            self._badge_share_platform_buttons.append((cache_key, pbtn))
                            px += plat_bw + plat_gap
                            if px + plat_bw > left + card_w:
                                px = left + 26
                                plat_y += plat_bh + plat_gap
                        row_h = (plat_y + plat_bh) - y
                y += row_h + 4
            y += 10
        y += 10
        if self._badge_share_status:
            for wrapped in wrap_text(font_xs, self._badge_share_status, card_w):
                st = font_xs.render(wrapped, True, (180, 220, 240))
                surf.blit(st, (left, y))
                y += st.get_height() + 2
            y += 8

        # ── Cosmetics ────────────────────────────────────────────────────
        y = panel_header("Cosmetics — Card Backs", y)
        y = self._draw_cosmetic_row(surf, left, y, card_w, font_xs,
                                     kind='card_back',
                                     owned=p['cosmetics']['owned_card_backs'],
                                     equipped=p['cosmetics']['equipped_card_back'],
                                     style_defs=CARD_BACK_STYLES)
        y += 16
        y = panel_header("Cosmetics — Table Felt Themes", y)
        y = self._draw_cosmetic_row(surf, left, y, card_w, font_xs,
                                     kind='felt_theme',
                                     owned=p['cosmetics']['owned_felt_themes'],
                                     equipped=p['cosmetics']['equipped_felt_theme'],
                                     style_defs=FELT_THEMES)
        y += 30

        self._content_height = (y - top0) + self.scroll_offset
        surf.set_clip(prev_clip)
        self._back_btn.draw(surf)
        self._draw_cosmetic_tooltip(surf, font_xs, sw, sh)

    def _draw_cosmetic_tooltip(self, surf, font_xs, sw, sh):
        """Info bubble for whichever cosmetic swatch is currently hovered
        or pinned (see _cosmetic_hitboxes, populated by
        _draw_cosmetic_row) — the unlock requirement for a locked one,
        or which badge earned it for an unlocked one. Drawn last, after
        the scroll clip is lifted, so it's never cut off at the panel
        edge."""
        active_key = self._pinned_tooltip_key or self._hover_tooltip_key
        if active_key is None:
            return
        match = next((h for h in self._cosmetic_hitboxes if h[1] == active_key), None)
        if match is None:
            return
        rect, _key, hint = match
        if not hint:
            return
        pad = 10
        max_w = min(260, sw - 40)
        lines = wrap_text(font_xs, hint, max_w - 2 * pad)
        line_h = font_xs.get_height()
        box_w = max((font_xs.size(l)[0] for l in lines), default=0) + 2 * pad
        box_h = line_h * len(lines) + 2 * pad

        bx = min(max(rect.centerx - box_w // 2, 8), sw - box_w - 8)
        # Prefer just below the swatch; flip above it if that would run
        # off the bottom of the window.
        by = rect.bottom + 44
        if by + box_h > sh - 8:
            by = rect.top - box_h - 8
        box_rect = pygame.Rect(bx, by, box_w, box_h)

        draw_rounded_rect(surf, (20, 24, 22, 245), box_rect, 8,
                          border_color=GOLD_LIGHT, border_width=1)
        ty = box_rect.y + pad
        for l in lines:
            t = font_xs.render(l, True, (235, 235, 235))
            surf.blit(t, (box_rect.centerx - t.get_width() // 2, ty))
            ty += line_h

    def _draw_cosmetic_row(self, surf, left, y, card_w, font_xs, *, kind, owned, equipped, style_defs):
        cs = get_chrome_scale(*self.gm.resolution)
        s = lambda px: round(px * cs)
        swatch_w, swatch_h, gap = s(90), s(60), s(12)
        x = left
        row_bottom = y
        for style_key, style in style_defs.items():
            is_owned = style_key in owned
            is_equipped = style_key == equipped
            rect = pygame.Rect(x, y, swatch_w, swatch_h)
            if x + swatch_w > left + card_w:
                x = left
                y += swatch_h + s(40)
                rect = pygame.Rect(x, y, swatch_w, swatch_h)

            col = style.get('felt') or ((style['a'][0]+style['b'][0])//2,
                                         (style['a'][1]+style['b'][1])//2,
                                         (style['a'][2]+style['b'][2])//2)
            fill = col if is_owned else tuple(c // 3 for c in col)
            pygame.draw.rect(surf, fill, rect, border_radius=6)
            border_col = GOLD_LIGHT if is_equipped else ((210, 210, 210) if is_owned else (70, 70, 70))
            pygame.draw.rect(surf, border_col, rect, width=2 if is_equipped else 1, border_radius=6)

            label = style.get('label', style_key)
            lt = font_xs.render(label, True, (235, 235, 235) if is_owned else (110, 110, 110))
            surf.blit(lt, (rect.centerx - lt.get_width() // 2, rect.bottom + 2))

            if is_owned and not is_equipped:
                key = (kind, style_key)
                # More breathing room below the label than before, and a
                # slightly taller button — plus this button must be the
                # SAME object across frames (see _equip_button_cache),
                # since Button tracks _pressed state between mouse-down
                # and mouse-up; a fresh instance every draw() call would
                # silently drop that state and the click would never fire.
                btn_rect = pygame.Rect(rect.x, rect.bottom + s(22), swatch_w, s(24))
                btn = self._equip_button_cache.get(key)
                if btn is None:
                    btn = Button(btn_rect, "Equip", self.assets.font_scaled('ui_tiny', cs),
                                 color=(40, 110, 60), hover_color=(55, 140, 78),
                                 on_click=(lambda k=style_key, kd=kind:
                                           self._equip_card_back(k) if kd == 'card_back' else self._equip_felt_theme(k)))
                    self._equip_button_cache[key] = btn
                else:
                    btn.rect = btn_rect  # reposition only — keeps _pressed/_hovered state intact
                btn.draw(surf)
                self._equip_buttons.append(btn)
            elif is_equipped:
                eq_t = font_xs.render("Equipped", True, GOLD_LIGHT)
                surf.blit(eq_t, (rect.centerx - eq_t.get_width() // 2, rect.bottom + 18))
            elif not is_owned:
                lock_t = font_xs.render("Locked", True, (110, 110, 110))
                surf.blit(lock_t, (rect.centerx - lock_t.get_width() // 2, rect.bottom + 18))

            # Hover/click info bubble — for locked items this is the
            # unlock requirement; for already-unlocked ones (equipped or
            # not) it's a reminder of which badge earned it. Skipped for
            # the handful of always-owned defaults, which have no badge
            # behind them (cosmetic_unlock_hint returns None for those).
            hint = profile_store.cosmetic_unlock_hint(kind, style_key)
            if hint:
                label_text = ("Unlocked — " if is_owned else "Locked — ") + hint
                hit_rect = pygame.Rect(rect.x, rect.y, rect.width, rect.height + 44)
                self._cosmetic_hitboxes.append((hit_rect, (kind, style_key), label_text))

            x += swatch_w + gap
            row_bottom = max(row_bottom, y + swatch_h + 44)
        return row_bottom



class ModeSelectScene(Scene):
    def _compute_viewport_top(self) -> int:
        """Where the title ("Play vs AI" / "Local Multiplayer") actually
        ends, plus a fixed gap — NOT an independent constant. The old
        fixed self._viewport_top=110 and the title's own font size both
        happened to scale with resolution, but via unrelated math, so
        the gap between them wasn't guaranteed: at 4K the title grew
        tall enough to overlap "Your Name:", the first thing drawn
        starting at _viewport_top (confirmed via a real screenshot).
        Called from on_enter/_relayout AND draw() so both the initial
        layout and every redraw agree on the same value within a given
        frame — same reasoning as SettingsScene._flow()'s constant
        shadowing."""
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        title_font = self.assets.font_scaled('ui_large', cs)
        # Ad banner sits in the same top header row on every eligible
        # scene (see AdBanner's own docstring and Scene._ad_top_pad())
        # — MainMenuScene's title (sh//4) already clears it by a wide
        # margin, but this scene's original round(60*cs) offset did
        # NOT, at any resolution (confirmed: even at 1024x640 the
        # banner needs 56px and this only reserved 48). Added at the
        # base here so everything derived from title_y (viewport_top,
        # and the actual title blit in draw()) inherits the same
        # correction automatically.
        title_y = round(60 * cs) + self._ad_top_pad()
        return title_y + title_font.get_height() + round(24 * cs)

    def on_enter(self, vs_ai=True, **kwargs):
        self.vs_ai = vs_ai
        self._player_name = "Player 1"
        self._n_opponents = 3
        self._difficulty = AIDifficulty.MEDIUM
        self._elimination_mode = False
        self._elimination_ai_only_continue = True
        self._name_active = False
        # MSOMI (see Chuo): orthogonal to difficulty, not a 4th tier —
        # greyed out until a trained model is attached. No threshold
        # gating on log volume per the final spec; attaching a real,
        # validated model file is the only requirement.
        self._msomi_enabled = False
        self._msomi_model_name: Optional[str] = None
        self._msomi_picker_open = False
        self._msomi_available_models = msomi_trainer.list_models()
        self._msomi_modal_scroll = 0
        self._msomi_status = ""
        self._msomi_browse_rect = pygame.Rect(0, 0, 1, 1)
        self._msomi_cancel_rect = pygame.Rect(0, 0, 1, 1)
        self._t = 0.0

        # Local Multiplayer (hot-seat) other-player names — up to 5
        # opponents (matches the max on _opp_buttons below). Only
        # player 1 could be renamed before; these give every other
        # seat the same treatment so everyone knows who they are
        # before the device starts getting passed around. Indexed by
        # opponent slot (0 -> "Player 2", etc.) and kept across
        # _relayout() calls, which only rebuild rects, not values.
        self._local_names = [f"Player {i+2}" for i in range(5)]
        self._local_name_active = [False] * 5
        self._local_name_rects: List[pygame.Rect] = []

        # Scroll state — as more opponents/options are added the flow
        # below can grow taller than the screen (up to 5 hot-seat name
        # fields plus every other option), which used to shove Start
        # Game/Back down past the bottom edge or on top of other rows.
        # Scrolling the whole flow inside a viewport (same pattern as
        # SettingsScene) means those buttons are always reachable —
        # just scroll to them — instead of being displaced off-screen.
        self.scroll_offset: float = 0.0
        self._scroll_bounce: Optional[Tween] = None
        self._content_height: int = 0
        self._viewport_top: int = 110  # recomputed properly by _update_viewport_top() below
        self._scrollbar_dragging: bool = False
        self._scrollbar_rect: Optional[pygame.Rect] = None
        self._scrollbar_track: Optional[pygame.Rect] = None

        # Created ONCE here and reused for the rest of this scene's
        # life — _relayout() below only ever mutates .rect on these,
        # never reassigns self._start_btn/_back_btn to a new Button().
        # That matters because _relayout() now runs every single frame
        # (to keep rects in sync with scrolling): Button.handle_event()
        # tracks a click across two events (MOUSEBUTTONDOWN sets
        # self._pressed=True, MOUSEBUTTONUP checks it) — if a fresh
        # Button object replaced it in between those two events (which
        # a plain frame boundary guarantees, since update() runs after
        # handle_event() every frame), the pressed flag from the first
        # event lives on an object nobody references anymore and the
        # click never fires. This is exactly what made Start/Back
        # non-clickable.
        font_lg = self.assets.font_scaled('ui_large', get_chrome_scale(*self.gm.resolution))
        font_md = self.assets.font_scaled('ui_medium', get_chrome_scale(*self.gm.resolution))
        self._start_btn = Button(pygame.Rect(0, 0, 260, 52), "Start Game", font_lg,
                                 on_click=self._start_game)
        self._back_btn = Button(pygame.Rect(0, 0, 260, 48), "Back", font_md,
                                color=(80, 60, 120), hover_color=(110, 85, 160),
                                on_click=lambda: self.manager.switch('main_menu'))

        self._relayout()

        font_help_title = self.assets.font_scaled('ui_large', get_chrome_scale(*self.gm.resolution))
        font_help_head = self.assets.font_scaled('ui_medium', get_chrome_scale(*self.gm.resolution))
        font_help_body = self.assets.font_scaled('ui_normal', get_chrome_scale(*self.gm.resolution))
        self._help = HelpOverlay(
            "Play vs AI — Quick Guide" if self.vs_ai else "Local Multiplayer — Quick Guide",
            self._help_sections(), font_help_title, font_help_head, font_help_body)
        self._help_btn = make_help_button(pygame.Rect(0, 0, 1, 1), font_help_body,
                                          on_click=self._help.open)

    def _help_sections(self):
        if self.vs_ai:
            return [
                ("Setting up your game", [
                    "Number of Opponents sets how many AI players you'll "
                    "face. AI Difficulty applies to ALL of them at once — "
                    "there's no per-opponent difficulty yet.",
                    "MSOMI lets you attach a model you trained yourself in "
                    "Chuo to make an AI opponent play more like a human. "
                    "It's separate from difficulty, not a 4th tier — it "
                    "layers on top of whichever difficulty is picked. See "
                    "the ? on the Chuo screen for the full training guide.",
                ]),
                ("Elimination Mode", [
                    "Off (default): the game ends the moment the first "
                    "player finishes their cards — everyone else is "
                    "ranked by cards remaining.",
                    "On: finished players are set aside as they go, and "
                    "play continues until only one player is left holding "
                    "cards — that player loses. \"Continue with AI\" "
                    "controls what happens if every human finishes before "
                    "the AI players do.",
                ]),
            ]
        else:
            return [
                ("Setting up local multiplayer", [
                    "Everyone plays on this ONE device, passing it around "
                    "turn by turn. Give each player a name so it's clear "
                    "whose turn it is.",
                    "A privacy screen appears between turns so players "
                    "can't see each other's hands while the device is "
                    "being handed over — just tap through it once you've "
                    "got the device.",
                ]),
                ("Elimination Mode", [
                    "Off (default): the game ends the moment the first "
                    "player finishes their cards — everyone else is "
                    "ranked by cards remaining.",
                    "On: finished players are set aside as they go, and "
                    "play continues until only one player is left holding "
                    "cards — that player loses.",
                ]),
            ]

    def _layout_help_btn(self, sw: int, sh: int):
        ac = getattr(self.manager, 'audio_controls', None)
        cs = get_chrome_scale(sw, sh)
        sz = round(32 * cs)
        if ac is not None and ac._btn_sfx.rect.width > 0:
            x = ac._btn_sfx.rect.left - round(6 * cs) - sz
            y = ac._btn_sfx.rect.top
        else:
            x, y = sw - round(10 * cs) - sz, round(10 * cs)
        self._help_btn.rect = pygame.Rect(x, y, sz, sz)

    def _relayout(self):
        """(Re)build every rect in this screen from current state —
        called on_enter, whenever _n_opponents changes, and every
        frame from handle_event()/update()/draw() (same rule
        SettingsScene's _flow() follows), since the current scroll
        offset is baked into every rect here so hit-testing can never
        drift out of sync with what's on screen. Only ever MUTATES
        existing widgets' .rect — never reassigns self._start_btn /
        self._back_btn to new objects (see on_enter for why)."""
        sw, sh = self.gm.resolution
        cx = sw // 2
        chrome_scale = get_chrome_scale(sw, sh)
        s = lambda px: round(px * chrome_scale)
        self._viewport_top = self._compute_viewport_top()

        top0 = self._viewport_top - int(self.scroll_offset) + s(34)
        y = top0
        self._name_rect = pygame.Rect(cx - s(150), y, s(300), s(45))
        y += s(45) + s(45)

        self._opp_buttons = []
        for i, n in enumerate([1,2,3,4,5]):
            r = pygame.Rect(cx - s(160) + i*s(68), y, s(60), s(40))
            self._opp_buttons.append((n, r))
        y += s(40) + s(40)

        self._local_name_rects = []
        if not self.vs_ai:
            for i in range(self._n_opponents):
                # Same height as the "Your Name" box above (_name_rect,
                # 45px) — these used to be drawn at 32px, visibly
                # smaller/thinner than Player 1's own field.
                r = pygame.Rect(cx - s(150), y, s(300), s(45))
                self._local_name_rects.append(r)
                # Each box's label is drawn 26px above the box (see
                # _draw_text_field) — the gap here must clear that, or
                # the next label prints on top of this box's bottom
                # edge. 32 (label height + breathing room) keeps them apart.
                y += s(45) + s(32)
            y += s(6)

        self._diff_buttons = []
        self._msomi_toggle_rect = None
        self._msomi_attach_rect = None
        if self.vs_ai:
            for i, (d, lbl) in enumerate([
                (AIDifficulty.EASY, "Easy"),
                (AIDifficulty.MEDIUM, "Medium"),
                (AIDifficulty.HARD, "Hard"),
            ]):
                r = pygame.Rect(cx - s(180) + i*s(130), y, s(120), s(40))
                self._diff_buttons.append((d, lbl, r))
            y += s(40) + s(40)

            # MSOMI — orthogonal to the difficulty picked above, not a
            # 4th tier. Greyed out (see draw()) until a model is
            # attached via the picker opened by _msomi_attach_rect.
            self._msomi_toggle_rect = pygame.Rect(cx - s(180), y, s(170), s(40))
            self._msomi_attach_rect = pygame.Rect(cx - s(4), y, s(184), s(40))
            y += s(40) + s(28)

        # Elimination Mode toggle — same mechanic works for vs-AI or local
        # multiplayer, so it's offered either way ("even in single
        # player" was explicitly requested).
        self._elim_toggle_rect = pygame.Rect(cx - s(90), y, s(180), s(40))
        y += s(40) + s(50)

        # Only meaningful for vs-AI games: once every human has finished,
        # should the AIs keep playing it out to a real last-place loser,
        # or should the round just end there? Local Multiplayer has no AI
        # seats, so this choice doesn't apply.
        self._ai_continue_toggle_rect = None
        if self.vs_ai:
            self._ai_continue_toggle_rect = pygame.Rect(cx - s(130), y, s(260), s(40))
            y += s(40) + s(28)

        start_w, start_h = round(260 * chrome_scale), round(52 * chrome_scale)
        back_w, back_h = round(260 * chrome_scale), round(48 * chrome_scale)
        self._start_btn.rect = pygame.Rect(cx - start_w // 2, y, start_w, start_h)
        y += start_h + round(12 * chrome_scale)
        self._back_btn.rect  = pygame.Rect(cx - back_w // 2, y, back_w, back_h)
        y += back_h + round(16 * chrome_scale)

        # Content height is measured in *unscrolled* terms (relative to
        # top0, which already has scroll baked in) — same trick
        # SettingsScene's _flow() uses — so this comes out the same
        # regardless of the current scroll_offset.
        self._content_height = (y - top0) + 16

    def _max_scroll(self, sh: int) -> int:
        viewport_h = sh - self._viewport_top - 10
        return max(0, self._content_height - viewport_h)

    def _set_scroll(self, value: float, sh: int):
        self.scroll_offset = max(0, min(self._max_scroll(sh), value))

    def _msomi_modal_rect(self) -> pygame.Rect:
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        w, h = round(520 * cs), min(round(480 * cs), sh - 100)
        return pygame.Rect(sw // 2 - w // 2, sh // 2 - h // 2, w, h)

    def _msomi_modal_row_rect(self, i: int) -> pygame.Rect:
        modal = self._msomi_modal_rect()
        cs = get_chrome_scale(*self.gm.resolution)
        list_top = modal.y + round(96 * cs)
        return pygame.Rect(modal.x + round(20 * cs), list_top + i * round(38 * cs) - self._msomi_modal_scroll,
                           modal.width - round(40 * cs), round(34 * cs))

    def _msomi_modal_list_area(self) -> pygame.Rect:
        modal = self._msomi_modal_rect()
        cs = get_chrome_scale(*self.gm.resolution)
        list_top = modal.y + round(96 * cs)
        list_bottom = modal.bottom - round(96 * cs)
        return pygame.Rect(modal.x + round(20 * cs), list_top, modal.width - round(40 * cs), list_bottom - list_top)

    def _msomi_browse_for_model(self):
        if not native_dialog.is_available():
            self._msomi_status = "File browsing isn't available on this system."
            return
        path = native_dialog.ask_open_file(
            title="Attach an MSOMI model",
            filetypes=[("MSOMI model", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            model = msomi_trainer.load_model(path)
            problem = msomi_trainer.validate_model(model)
        except Exception as e:
            self._msomi_status = f"Couldn't read that file: {e}"
            return
        if problem:
            self._msomi_status = problem
            return
        self._msomi_model_name = path
        self._msomi_enabled = True
        self._msomi_picker_open = False
        self._msomi_status = ""

    def _msomi_pick_model(self, name: str):
        self._msomi_model_name = name
        self._msomi_enabled = True
        self._msomi_picker_open = False
        self._msomi_status = ""

    def _start_game(self):
        save_manager.delete_save_file()  # starting fresh discards any pending save
        configs = [{'name': self._player_name or "Player 1", 'is_human': True}]
        if self.vs_ai:
            names = ["Kadi-Bot","Smart AI","Trickster","Blitz","Shadow"]
            model_name = self._msomi_model_name if self._msomi_enabled else None
            for i in range(self._n_opponents):
                configs.append({'name': names[i % len(names)],
                                 'is_human': False, 'difficulty': self._difficulty,
                                 'msomi_model_name': model_name})
        else:
            for i in range(self._n_opponents):
                nm = self._local_names[i].strip() if i < len(self._local_names) else ""
                configs.append({'name': nm or f"Player {i+2}", 'is_human': True})
            # Same collision guard LAN/Internet already apply right
            # before handing the roster to GameManager — two hot-seat
            # players who both typed (or both left) the same name
            # would otherwise be indistinguishable at the table.
            disambiguated = disambiguate_names([c['name'] for c in configs])
            for c, name in zip(configs, disambiguated):
                c['name'] = name
        self.manager.switch('gameplay', player_configs=configs,
                            elimination_mode=self._elimination_mode,
                            elimination_ai_only_continue=self._elimination_ai_only_continue)

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        self._help.notice_activity()
        if self._msomi_picker_open:
            # Don't let the help overlay open (or the '?' button eat a
            # click) while the MSOMI model-picker modal is already up —
            # two floating modals at once would be confusing, and the
            # rest of this screen's own buttons already follow the same
            # "picker modal wins" rule (see btn_mp in update()).
            pass
        elif self._help.handle_event(event, sw, sh):
            return
        else:
            self._help_btn.handle_event(event)
        if event.type == pygame.MOUSEWHEEL and self._msomi_picker_open:
            list_area = self._msomi_modal_list_area()
            max_scroll = max(0, len(self._msomi_available_models) * 38 - list_area.height)
            self._msomi_modal_scroll = max(0, min(max_scroll, self._msomi_modal_scroll - event.y * 38))
            return

        # Scrolling the main flow — only when the picker modal isn't up,
        # same priority rule the modal already gets above.
        if not self._msomi_picker_open:
            max_scroll = self._max_scroll(sh)
            if event.type == pygame.MOUSEWHEEL:
                self.scroll_offset = _scroll_wheel_delta(self.scroll_offset, event.y, 50, max_scroll)
                self._scroll_bounce = None
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._scrollbar_rect and self._scrollbar_rect.collidepoint(event.pos):
                    self._scrollbar_dragging = True
                    return
                if self._scrollbar_track and self._scrollbar_track.collidepoint(event.pos) \
                        and max_scroll > 0:
                    track = self._scrollbar_track
                    t = (event.pos[1] - track.y) / max(1, track.height)
                    self._set_scroll(t * max_scroll, sh)
                    return
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._scrollbar_dragging = False
            if event.type == pygame.MOUSEMOTION and self._scrollbar_dragging:
                track = self._scrollbar_track
                if track:
                    t = (event.pos[1] - track.y) / max(1, track.height)
                    self._set_scroll(t * max_scroll, sh)
                return

        # Recompute every rect NOW, with the current scroll offset, so
        # hit-testing below always matches what's actually on screen.
        self._relayout()

        # Clicks above the viewport (the title) never hit scrollable content.
        if hasattr(event, 'pos') and event.type == pygame.MOUSEBUTTONDOWN \
                and event.pos[1] < self._viewport_top and not self._msomi_picker_open:
            return

        if event.type == pygame.MOUSEBUTTONDOWN:
            if self._msomi_picker_open:
                # While the picker's open, its own controls take
                # priority over everything else underneath it.
                if self._msomi_browse_rect.collidepoint(event.pos):
                    self._msomi_browse_for_model()
                    return
                if self._msomi_cancel_rect.collidepoint(event.pos):
                    self._msomi_picker_open = False
                    return
                list_area = self._msomi_modal_list_area()
                if list_area.collidepoint(event.pos):
                    for i, name in enumerate(self._msomi_available_models):
                        row = self._msomi_modal_row_rect(i)
                        if row.collidepoint(event.pos):
                            self._msomi_pick_model(name)
                            return
                    return  # clicked in the list area but not on a row — stay open
                if not self._msomi_modal_rect().collidepoint(event.pos):
                    self._msomi_picker_open = False  # clicked outside the modal — dismiss
                return

            if self._name_rect.collidepoint(event.pos): self._name_active = True
            else: self._name_active = False
            for i in range(len(self._local_name_active)):
                self._local_name_active[i] = (
                    i < len(self._local_name_rects)
                    and self._local_name_rects[i].collidepoint(event.pos))
            for n, r in self._opp_buttons:
                if r.collidepoint(event.pos) and n != self._n_opponents:
                    self._n_opponents = n
                    self._relayout()
            for d, lbl, r in self._diff_buttons:
                if r.collidepoint(event.pos): self._difficulty = d
            if self._msomi_toggle_rect and self._msomi_toggle_rect.collidepoint(event.pos):
                if self._msomi_model_name:
                    self._msomi_enabled = not self._msomi_enabled
            if self._msomi_attach_rect and self._msomi_attach_rect.collidepoint(event.pos):
                self._msomi_available_models = msomi_trainer.list_models()
                self._msomi_modal_scroll = 0
                self._msomi_status = ""
                self._msomi_picker_open = True
            if self._elim_toggle_rect.collidepoint(event.pos):
                self._elimination_mode = not self._elimination_mode
            if (self._ai_continue_toggle_rect is not None and self._elimination_mode
                    and self._ai_continue_toggle_rect.collidepoint(event.pos)):
                self._elimination_ai_only_continue = not self._elimination_ai_only_continue
        if event.type == pygame.KEYDOWN and self._name_active:
            if event.key == pygame.K_BACKSPACE: self._player_name = self._player_name[:-1]
            elif event.key == pygame.K_RETURN:  self._name_active = False
            elif len(self._player_name) < 16 and event.unicode.isprintable():
                self._player_name += event.unicode
        if event.type == pygame.KEYDOWN:
            for i, active in enumerate(self._local_name_active):
                if not active:
                    continue
                if event.key == pygame.K_BACKSPACE:
                    self._local_names[i] = self._local_names[i][:-1]
                elif event.key == pygame.K_RETURN:
                    self._local_name_active[i] = False
                elif len(self._local_names[i]) < 16 and event.unicode.isprintable():
                    self._local_names[i] += event.unicode
        self._start_btn.handle_event(event)
        self._back_btn.handle_event(event)

    def update(self, dt):
        self._t += dt
        sw, sh = self.gm.resolution
        self._layout_help_btn(sw, sh)
        self._help.update_idle_glow(dt)
        if not pygame.mouse.get_pressed()[0]:
            self._scrollbar_dragging = False
        self._relayout()   # re-clamp / re-place on resize, keep buttons live
        self.scroll_offset, self._scroll_bounce = _settle_scroll(
            self.scroll_offset, self._scroll_bounce, dt, self._max_scroll(sh))

        mp = pygame.mouse.get_pos()
        in_viewport = mp[1] >= self._viewport_top
        btn_mp = mp if (in_viewport and not self._msomi_picker_open) else (-1, -1)
        self._help_btn.update(dt, mp)
        self._start_btn.update(dt, btn_mp)
        self._back_btn.update(dt, btn_mp)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 30, 20))
        cx = sw // 2
        _ms_cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', _ms_cs)
        font_md = self.assets.font_scaled('ui_medium', _ms_cs)
        font_sm = self.assets.font_scaled('ui_normal', _ms_cs)

        mode_str = "Play vs AI" if self.vs_ai else "Local Multiplayer"
        title = font_lg.render(mode_str, True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width()//2, round(60 * _ms_cs) + self._ad_top_pad()))

        # Everything below the title scrolls inside this viewport — see
        # _relayout()/_max_scroll(). Clipping (rather than just letting
        # rects run past the bottom) is what actually stops the lower
        # controls from being displaced/cut off as more players are added.
        viewport_h = sh - self._viewport_top - 10
        viewport_rect = pygame.Rect(0, self._viewport_top, sw, viewport_h)
        prev_clip = surf.get_clip()
        surf.set_clip(viewport_rect)

        name_lbl = font_sm.render("Your Name:", True, WHITE)
        surf.blit(name_lbl, (cx-150, self._name_rect.y - round(26 * _ms_cs)))
        bc = GOLD_LIGHT if self._name_active else (*WHITE, 120)
        pygame.draw.rect(surf, (30,60,40), self._name_rect, border_radius=6)
        pygame.draw.rect(surf, bc, self._name_rect, width=2, border_radius=6)
        ns = font_md.render(self._player_name, True, WHITE)
        surf.blit(ns, (self._name_rect.x+10, self._name_rect.y+8))
        if self._name_active and int(self._t*2) % 2 == 0:
            cx2 = self._name_rect.x + 10 + ns.get_width() + 2
            pygame.draw.line(surf, WHITE, (cx2, self._name_rect.y+8),
                             (cx2, self._name_rect.y+35), 2)

        opp_lbl = font_sm.render(
            "Number of Opponents:" if self.vs_ai else "Number of Other Players:", True, WHITE)
        surf.blit(opp_lbl, (cx-160, self._opp_buttons[0][1].y - round(26 * _ms_cs)))
        for n, r in self._opp_buttons:
            sel = (n == self._n_opponents)
            pygame.draw.rect(surf, GOLD if sel else (50,90,60), r, border_radius=6)
            pygame.draw.rect(surf, GOLD_LIGHT if sel else (80,130,80), r, width=2, border_radius=6)
            num_s = font_md.render(str(n), True, WHITE)
            surf.blit(num_s, (r.centerx-num_s.get_width()//2, r.centery-num_s.get_height()//2))

        if not self.vs_ai and self._local_name_rects:
            for i, r in enumerate(self._local_name_rects):
                _draw_text_field(surf, font_sm, font_md, f"Player {i+2} Name:", r,
                                 self._local_names[i], self._local_name_active[i], self._t,
                                 placeholder=f"Player {i+2}")

        if self.vs_ai and self._diff_buttons:
            diff_lbl = font_sm.render("AI Difficulty:", True, WHITE)
            surf.blit(diff_lbl, (cx-180, self._diff_buttons[0][2].y - round(26 * _ms_cs)))
            for d, lbl, r in self._diff_buttons:
                sel = (d == self._difficulty)
                cols = {AIDifficulty.EASY:((40,120,50),(60,180,70)),
                        AIDifficulty.MEDIUM:((100,80,20),(180,140,30)),
                        AIDifficulty.HARD:((120,30,30),(200,50,50))}
                c = cols[d][1 if sel else 0]
                pygame.draw.rect(surf, c, r, border_radius=6)
                pygame.draw.rect(surf, (*WHITE, 200 if sel else 80), r, width=2, border_radius=6)
                ls = font_sm.render(lbl, True, WHITE)
                surf.blit(ls, (r.centerx-ls.get_width()//2, r.centery-ls.get_height()//2))

            # MSOMI — greyed out until a model's actually attached, per
            # spec: no log-volume threshold, just "is there a valid
            # model file". Orthogonal to the difficulty above it.
            msomi_lbl = font_sm.render("MSOMI:", True, WHITE)
            surf.blit(msomi_lbl, (self._msomi_toggle_rect.x, self._msomi_toggle_rect.y - round(26 * _ms_cs)))
            can_enable = self._msomi_model_name is not None
            on = self._msomi_enabled and can_enable
            t_col = (100, 80, 20) if not can_enable else ((180, 140, 30) if on else (70, 70, 80))
            pygame.draw.rect(surf, t_col, self._msomi_toggle_rect, border_radius=8)
            pygame.draw.rect(surf, (*WHITE, 60 if not can_enable else (180 if on else 90)),
                             self._msomi_toggle_rect, width=2, border_radius=8)
            t_txt = "ON" if on else "OFF"
            ts = font_sm.render(t_txt, True, (*WHITE, 120) if not can_enable else WHITE)
            surf.blit(ts, (self._msomi_toggle_rect.centerx - ts.get_width()//2,
                          self._msomi_toggle_rect.centery - ts.get_height()//2))

            pygame.draw.rect(surf, (60, 60, 80), self._msomi_attach_rect, border_radius=8)
            pygame.draw.rect(surf, (*WHITE, 100), self._msomi_attach_rect, width=2, border_radius=8)
            attach_label = (os.path.basename(self._msomi_model_name) if self._msomi_model_name
                            else "Attach Model...")
            attach_font = self.assets.font_scaled('ui_tiny', _ms_cs)
            attach_label = _truncate_to_width(attach_label, attach_font,
                                              self._msomi_attach_rect.width - 16)
            as_ = attach_font.render(attach_label, True, WHITE)
            surf.blit(as_, (self._msomi_attach_rect.centerx - as_.get_width()//2,
                            self._msomi_attach_rect.centery - as_.get_height()//2))

        # Elimination Mode toggle
        elim_lbl = font_sm.render("Elimination Mode:", True, WHITE)
        surf.blit(elim_lbl, (self._elim_toggle_rect.x - round(4 * _ms_cs), self._elim_toggle_rect.y - round(26 * _ms_cs)))
        on = self._elimination_mode
        pygame.draw.rect(surf, (40,120,50) if on else (70,70,80), self._elim_toggle_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 180 if on else 90), self._elim_toggle_rect, width=2, border_radius=8)
        et_s = font_sm.render("ON" if on else "OFF", True, WHITE)
        surf.blit(et_s, (self._elim_toggle_rect.centerx - et_s.get_width()//2,
                         self._elim_toggle_rect.centery - et_s.get_height()//2))
        hint = self.assets.font_scaled('ui_tiny', _ms_cs).render(
            "Winners are set aside as they finish — last one holding cards loses",
            True, (170, 176, 168))
        surf.blit(hint, (cx - hint.get_width()//2, self._elim_toggle_rect.bottom + 4))

        # AI-continue choice — only relevant (and only shown as active)
        # for vs-AI games with Elimination Mode on. Drawn dimmed and
        # non-clickable otherwise rather than removed, so the layout
        # below it doesn't jump around as the player toggles things.
        if self._ai_continue_toggle_rect is not None:
            active = self._elimination_mode
            r = self._ai_continue_toggle_rect
            label = self.assets.font_scaled('ui_tiny', _ms_cs).render(
                "When all humans finish:", True, WHITE if active else (110, 114, 108))
            surf.blit(label, (r.x, r.y - round(20 * _ms_cs)))
            fill = (40, 90, 130) if (active and self._elimination_ai_only_continue) else \
                   (90, 70, 30) if active else (55, 55, 62)
            pygame.draw.rect(surf, fill, r, border_radius=8)
            pygame.draw.rect(surf, (*WHITE, 180 if active else 60), r, width=2, border_radius=8)
            txt = "Continue with AI" if self._elimination_ai_only_continue else "End the game"
            ac_s = font_sm.render(txt, True, WHITE if active else (140, 144, 138))
            surf.blit(ac_s, (r.centerx - ac_s.get_width()//2, r.centery - ac_s.get_height()//2))

        self._start_btn.draw(surf)
        self._back_btn.draw(surf)

        surf.set_clip(prev_clip)

        # ── Scrollbar ────────────────────────────────────────────────
        max_scroll = self._max_scroll(sh)
        font_xs = self.assets.font_scaled('ui_tiny', _ms_cs)
        if max_scroll > 0:
            track = pygame.Rect(sw - 10, self._viewport_top, 6, viewport_h)
            self._scrollbar_track = track
            pygame.draw.rect(surf, (40, 45, 60), track, border_radius=3)
            thumb_h = max(30, int(viewport_h * viewport_h / max(1, self._content_height)))
            thumb_y = track.y + int((viewport_h - thumb_h) * (self.scroll_offset / max_scroll))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            self._scrollbar_rect = thumb
            pygame.draw.rect(surf, GOLD if self._scrollbar_dragging else (140, 150, 200),
                             thumb, border_radius=3)
            hint = font_xs.render("scroll", True, (170, 176, 188))
            surf.blit(hint, (sw - hint.get_width() - 16, self._viewport_top - 20))
        else:
            self._scrollbar_track = None
            self._scrollbar_rect = None

        if self._msomi_picker_open:
            self._draw_msomi_modal(surf)
        else:
            self._help.draw_button_glow(surf, self._help_btn.rect)
            self._help_btn.draw(surf)
            self._help.draw(surf)

    def _draw_msomi_modal(self, surf: pygame.Surface):
        """Drawn LAST, after everything else in this scene, so it's
        always visibly on top — this used to render inline with the
        rest of the layout and could end up hidden behind whatever was
        drawn after it (Elimination Mode, etc.)."""
        sw, sh = self.gm.resolution
        _mm_cs = get_chrome_scale(sw, sh)
        _mm_s = lambda px: round(px * _mm_cs)
        font = self.assets.font_scaled('ui_normal', _mm_cs)
        font_sm = self.assets.font_scaled('ui_small', _mm_cs)
        font_md = self.assets.font_scaled('ui_medium', _mm_cs)

        # Dim the whole screen behind the modal so it reads clearly as
        # being on top, not just another panel among many.
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(dim, (0, 0))

        modal = self._msomi_modal_rect()
        Panel(modal, color=(32, 34, 46)).draw(surf)

        title = font_md.render("Attach MSOMI Model", True, GOLD_LIGHT)
        surf.blit(title, (modal.centerx - title.get_width() // 2, modal.y + _mm_s(16)))
        sub = font_sm.render("From this device's saved models, or browse anywhere:",
                            True, (*WHITE, 170))
        surf.blit(sub, (modal.x + _mm_s(20), modal.y + _mm_s(52)))

        list_area = self._msomi_modal_list_area()
        pygame.draw.rect(surf, (20, 22, 30), list_area, border_radius=6)
        clip = surf.get_clip()
        surf.set_clip(list_area)
        if not self._msomi_available_models:
            es = font_sm.render("No saved models yet — train one in Chuo, or Browse below.",
                                True, (*WHITE, 160))
            surf.blit(es, (list_area.x + _mm_s(12), list_area.y + _mm_s(12)))
        for i, name in enumerate(self._msomi_available_models):
            row = self._msomi_modal_row_rect(i)
            if row.bottom < list_area.y or row.y > list_area.bottom:
                continue
            hovered = row.collidepoint(pygame.mouse.get_pos())
            is_current = (name == self._msomi_model_name)
            color = (85, 65, 130) if is_current else ((60, 60, 80) if hovered else (45, 45, 60))
            pygame.draw.rect(surf, color, row, border_radius=6)
            ns = font_sm.render(name, True, WHITE)
            surf.blit(ns, (row.x + _mm_s(10), row.centery - ns.get_height() // 2))
        surf.set_clip(clip)

        self._msomi_browse_rect = pygame.Rect(modal.x + _mm_s(20), list_area.bottom + _mm_s(14), _mm_s(230), _mm_s(40))
        self._msomi_cancel_rect = pygame.Rect(modal.right - _mm_s(150), list_area.bottom + _mm_s(14), _mm_s(130), _mm_s(40))
        pygame.draw.rect(surf, (50, 90, 130), self._msomi_browse_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 150), self._msomi_browse_rect, width=2, border_radius=8)
        bs = font_sm.render("Browse for file...", True, WHITE)
        surf.blit(bs, (self._msomi_browse_rect.centerx - bs.get_width() // 2,
                      self._msomi_browse_rect.centery - bs.get_height() // 2))

        pygame.draw.rect(surf, (70, 70, 80), self._msomi_cancel_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 120), self._msomi_cancel_rect, width=2, border_radius=8)
        cs = font_sm.render("Cancel", True, WHITE)
        surf.blit(cs, (self._msomi_cancel_rect.centerx - cs.get_width() // 2,
                      self._msomi_cancel_rect.centery - cs.get_height() // 2))

        if self._msomi_status:
            st = self.assets.font_scaled('ui_tiny', _mm_cs).render(self._msomi_status, True, (240, 140, 100))
            surf.blit(st, (modal.x + _mm_s(20), self._msomi_browse_rect.bottom + _mm_s(8)))


# ─── Settings ─────────────────────────────────────────────────────────────────

RESOLUTIONS = [(1280,800),(1024,640),(1440,900),(1600,1000),(1920,1080),
               (2560,1440),(3840,2160),(7680,4320)]
RES_LABELS  = ["1280×800","1024×640","1440×900","1600×1000","1920×1080",
               "2560×1440 (2K)","3840×2160 (4K)","7680×4320 (8K)"]

# Shared with the resolution-picker LIST styling below and in
# startup_picker.py's own copies (that module can't import these back —
# see its own docstring on staying self-contained) — kept in sync by hand.
NOT_RECOMMENDED_COLOR = (220, 120, 90)
RECOMMENDED_COLOR     = (140, 220, 150)

# ── Display capability detection ────────────────────────────────────────────
# Queried once and cached — the physical/virtual desktop doesn't change
# mid-session, and pygame's own display-info calls aren't free enough to
# want them running every time a resolution option is drawn or clicked.
_display_caps_cache: Optional[tuple] = None

def _detect_display_caps() -> tuple:
    """Returns the best-known (max_w, max_h) this machine's display(s) can
    actually present, used to flag *any* resolution — small or large —
    that exceeds it, rather than hardcoding a fixed 'this tier and up'
    cutoff. Falls back gracefully if pygame can't answer (headless/CI,
    older SDL): in that case nothing gets flagged, since we'd rather stay
    silent than nag on a false positive."""
    global _display_caps_cache
    if _display_caps_cache is not None:
        return _display_caps_cache
    max_w, max_h = 0, 0
    try:
        # get_desktop_sizes() (pygame 2.x) reports every connected
        # monitor's *actual* desktop resolution — take the largest, since
        # a window can be dragged to whichever screen is biggest.
        for w, h in pygame.display.get_desktop_sizes():
            max_w, max_h = max(max_w, w), max(max_h, h)
    except Exception:
        pass
    if max_w == 0 or max_h == 0:
        try:
            info = pygame.display.Info()
            if info.current_w > 0 and info.current_h > 0:
                max_w, max_h = info.current_w, info.current_h
        except Exception:
            pass
    _display_caps_cache = (max_w, max_h) if (max_w and max_h) else (0, 0)
    return _display_caps_cache

def _resolution_exceeds_display(res: tuple) -> bool:
    """True if `res` is larger, in either dimension, than what
    _detect_display_caps() found — i.e. picking it means the window will
    be upscaled/letterboxed past the real screen rather than shown
    pixel-for-pixel. Applies uniformly across the whole RESOLUTIONS list,
    not just the 4K/8K entries, since a machine could in principle be
    below 1280×800 too."""
    max_w, max_h = _detect_display_caps()
    if max_w == 0 or max_h == 0:
        return False  # couldn't detect anything — don't guess
    rw, rh = res
    return rw > max_w or rh > max_h

def _optimum_resolution_idx() -> int:
    """Picks the best entry in RESOLUTIONS for this machine's detected
    display: the largest one that still fits within _detect_display_caps()
    (by pixel count), since that's the closest match to the real screen
    without being upscaled past it. If nothing fits (a display smaller
    than every listed option — unlikely, but possible), falls back to the
    smallest entry rather than leaving the player with no suggestion."""
    max_w, max_h = _detect_display_caps()
    if max_w == 0 or max_h == 0:
        return 4  # can't detect anything — default to 1920×1080
    fitting = [i for i, r in enumerate(RESOLUTIONS) if not _resolution_exceeds_display(r)]
    if fitting:
        return max(fitting, key=lambda i: RESOLUTIONS[i][0] * RESOLUTIONS[i][1])
    return min(range(len(RESOLUTIONS)), key=lambda i: RESOLUTIONS[i][0] * RESOLUTIONS[i][1])


class NumberBox:
    """Click-to-edit integer field (seconds). Click to focus & type digits,
    Enter/click-away commits, small +/- steppers for mouse-only use."""
    def __init__(self, rect: pygame.Rect, value: int, min_val: int, max_val: int,
                 step: int = 1, label: str = "", unit: str = "s",
                 zero_label: Optional[str] = "Off"):
        self.rect    = rect
        self.minus_rect = pygame.Rect(0, 0, 1, 1)
        self.plus_rect  = pygame.Rect(0, 0, 1, 1)
        self.value   = int(value)
        self.min_val = min_val
        self.max_val = max_val
        self.step    = step
        self.label   = label
        self.unit    = unit
        # Text shown when value == 0. Use None to just show "0<unit>"
        # instead of a special word (e.g. a percentage box has no need
        # for "Off").
        self.zero_label = zero_label
        self.focused = False
        self.text    = str(int(value))
        # Hold-to-repeat state for the +/- steppers — lets players hold
        # the button down to run the value up/down quickly instead of
        # having to click one step at a time (especially useful for
        # reaching a high max like 300s).
        self._hold_dir = 0
        self._hold_elapsed = 0.0
        self._hold_interval = 0.0

    def update(self, dt: float, mouse_pos: Tuple[int, int], mouse_down: bool):
        held_minus = mouse_down and self.minus_rect.collidepoint(mouse_pos)
        held_plus  = mouse_down and self.plus_rect.collidepoint(mouse_pos)
        direction = -1 if held_minus else (1 if held_plus else 0)

        if direction == 0:
            self._hold_dir = 0
            self._hold_elapsed = 0.0
            self._hold_interval = 0.0
            return

        if direction != self._hold_dir:
            # Just started holding — the initial nudge already happened via
            # the MOUSEBUTTONDOWN in handle_event, so just arm the repeat
            # delay; don't nudge again immediately.
            self._hold_dir = direction
            self._hold_elapsed = 0.0
            self._hold_interval = 0.45   # delay before auto-repeat kicks in
            return

        self._hold_elapsed += dt
        if self._hold_elapsed >= self._hold_interval:
            self._hold_elapsed = 0.0
            # Accelerate: each repeat fires a little sooner than the last,
            # down to a fast floor, so holding ramps up to the max quickly.
            self._hold_interval = max(0.035, self._hold_interval * 0.8)
            self.nudge(direction * self.step)

    def start_edit(self):
        self.focused = True
        self.text = str(int(self.value))

    def commit(self):
        try:
            v = int(self.text) if self.text.strip() != "" else self.min_val
        except ValueError:
            v = int(self.value)
        self.value = max(self.min_val, min(self.max_val, v))
        self.text = str(self.value)
        self.focused = False

    def nudge(self, delta: int):
        if self.focused:
            self.commit()
        self.value = max(self.min_val, min(self.max_val, int(self.value) + delta))
        self.text = str(self.value)

    def handle_event(self, event) -> bool:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.minus_rect.collidepoint(event.pos):
                self.nudge(-self.step)
                return True
            if self.plus_rect.collidepoint(event.pos):
                self.nudge(self.step)
                return True
            if self.rect.collidepoint(event.pos):
                if not self.focused:
                    self.start_edit()
                return True
            elif self.focused:
                self.commit()
        if self.focused and event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
                self.commit()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
                return True
            elif event.unicode.isdigit() and len(self.text) < 3:
                self.text += event.unicode
                return True
        return False

    def draw(self, surf: pygame.Surface, font: pygame.font.Font, small_font: pygame.font.Font):
        focused_color = GOLD_LIGHT if self.focused else (130, 160, 135)
        pygame.draw.rect(surf, (24, 46, 32), self.rect, border_radius=6)
        pygame.draw.rect(surf, focused_color, self.rect, width=2, border_radius=6)
        if self.focused:
            txt = self.text if self.text else "0"
        else:
            if self.value > 0 or not self.zero_label:
                txt = f"{int(self.value)}{self.unit}"
            else:
                txt = self.zero_label
        ts = font.render(txt, True, WHITE)
        surf.blit(ts, (self.rect.centerx - ts.get_width() // 2,
                       self.rect.centery - ts.get_height() // 2))
        for r, sym in [(self.minus_rect, "-"), (self.plus_rect, "+")]:
            pygame.draw.rect(surf, (40, 70, 48), r, border_radius=5)
            pygame.draw.rect(surf, (*WHITE, 60), r, width=1, border_radius=5)
            ss = small_font.render(sym, True, WHITE)
            surf.blit(ss, (r.centerx - ss.get_width() // 2, r.centery - ss.get_height() // 2))


class SettingsScene(Scene):
    """
    Settings drawn as a single vertical flow grouped into cards, with all
    widget rects computed in absolute screen space (already accounting for
    scroll). Both draw() and handle_event() call the same _flow() each time,
    so hit-testing can never drift out of sync with what's on screen.
    """

    PAD_OUTER  = 24   # inside-card padding
    CARD_GAP   = 18   # space between cards
    ROW_H      = 56   # label+control row height

    def on_enter(self, **kwargs):
        gm = self.gm
        self._res_idx = RESOLUTIONS.index(gm.resolution) if gm.resolution in RESOLUTIONS else 0

        self.scroll_offset: float = 0.0
        self._scroll_bounce: Optional[Tween] = None
        self._content_height: int = 0
        self._viewport_top: int = 64
        self._scrollbar_dragging: bool = False
        self._scrollbar_rect: Optional[pygame.Rect] = None
        self._scrollbar_track: Optional[pygame.Rect] = None

        self._numboxes = [
            NumberBox(pygame.Rect(0, 0, 1, 1), gm.turn_timer_secs,      0, 300, step=5, label="Turn timer"),
            NumberBox(pygame.Rect(0, 0, 1, 1), gm.post_play_delay_secs, 0, 120, step=1, label="Next-player delay / KADI check"),
            NumberBox(pygame.Rect(0, 0, 1, 1), gm.counter_window_secs,  0, 120, step=1, label="J counter window"),
        ]
        self._hint_pct_box = NumberBox(pygame.Rect(0, 0, 1, 1), gm.hint_threshold_pct,
                                       0, 100, step=5, label="Hint delay (% of turn timer)",
                                       unit="%", zero_label=None)
        self._log_cap_box = NumberBox(pygame.Rect(0, 0, 1, 1), gm.max_log_pairs,
                                      0, 999, step=10, label="Max saved log files",
                                      unit=" pairs", zero_label="Unlimited")

        chrome_scale = get_chrome_scale(*gm.resolution)
        self._back_btn = Button(pygame.Rect(0, 0, 220, 48), "Back",
                                self.assets.font_scaled('ui_large', chrome_scale),
                                color=(60, 40, 100), hover_color=(90, 60, 140),
                                on_click=lambda: self.manager.switch('main_menu'))

        self._reset_btn = Button(pygame.Rect(0, 0, 220, 48), "Reset to Defaults",
                                 self.assets.font_scaled('ui_normal', chrome_scale),
                                 color=(120, 40, 40), hover_color=(150, 55, 55),
                                 on_click=self._on_reset_defaults)
        self._reset_confirm_timer = 0.0

        self._joker_btns = {
            2: Button(pygame.Rect(0, 0, 1, 1), "2", self.assets.font_scaled('ui_medium', chrome_scale),
                      on_click=lambda: setattr(gm, 'joker_count', 2)),
            4: Button(pygame.Rect(0, 0, 1, 1), "4", self.assets.font_scaled('ui_medium', chrome_scale),
                      on_click=lambda: setattr(gm, 'joker_count', 4)),
        }
        self._log_btns = {
            lvl: Button(pygame.Rect(0, 0, 1, 1), lvl, self.assets.font_scaled('ui_normal', chrome_scale),
                        on_click=(lambda lv=lvl: gm.set_log_level(lv)))
            for lvl in ('OFF', 'LOW', 'HIGH')
        }
        self._toggle_keys = [
            ('timers_enabled',           "Turn Timers Enabled"),
            ('suit_change_after_shield', "Suit Change After Shield"),
            ('ace_suit_integrity',       "ACE (A) Card Suit Integrity"),
            ('pickup_shield_qk_allowed', "Question/Kickback+ACE Can Shield Pick-up"),
            ('ace_finisher_enabled',     "ACE Multi-Card Finish"),
            ('jump_multi_card_enabled',  "Jump Multi-Card Play"),
        ]
        self._hint_toggle_key = ('hints_enabled', "Card Play Hints")
        self._music_toggle_key = ('music_enabled', "Background Music")
        self._sfx_toggle_key = ('sfx_enabled', "Sound Effects")
        # Dev-only toggle for the placeholder banner ad slot — see
        # scenes.py's AdBanner. No real ad network or purchase flow yet;
        # this just lets the ads-off layout path be tested.
        #
        # NOT surfaced in the Settings UI (see the removed "Advertising
        # (Dev)" card below) — per the Part B "real ad network"
        # discussion, Steam's policy rules out third-party ad networks
        # as a business model, and there's no plan to pursue one for
        # now, so this toggle has no reason to be player-visible. The
        # key/flag itself, gm.ads_enabled, the AdBanner class, and the
        # ads_enabled-AND-NOT-ads_removed render gate (_ads_showing())
        # are all left fully intact and default OFF — if this ever gets
        # revisited (e.g. real traffic clears Bidstack's ~10K DAU
        # minimum — see that discussion), re-enabling only needs a code
        # change (flip the default, or re-add a settings-UI card), not
        # a rebuild of the underlying mechanism.
        self._ads_toggle_key = ('ads_enabled', "Show Ads (Dev Toggle)")
        # Dev-only toggle for the profile's ads_removed PURCHASE flag
        # (Part 5) — same spirit as ads_enabled above; also no longer
        # surfaced in the Settings UI, same reasoning. Lives on
        # gm.profile (a dict), not a plain gm attribute, so it needs its
        # own Button rather than joining the generic _toggle_btns dict
        # below, which always does setattr(gm, key, ...).
        self._ads_removed_btn = Button(
            pygame.Rect(0, 0, 1, 1), "", self.assets.font_scaled('ui_normal', chrome_scale),
            on_click=self._toggle_ads_removed)
        self._toggle_btns = {
            key: Button(pygame.Rect(0, 0, 1, 1), "", self.assets.font_scaled('ui_normal', chrome_scale),
                        on_click=(lambda k=key: setattr(gm, k, not getattr(gm, k))))
            for key, _ in self._toggle_keys + [self._hint_toggle_key, self._music_toggle_key,
                                                self._sfx_toggle_key]
            # _ads_toggle_key deliberately excluded — see comment above.
        }
        pct_fmt = lambda v: f"{int(round(v * 100))}%"
        self._music_vol_slider = Slider(
            pygame.Rect(0, 0, 1, 1), 0.0, 1.0, gm.music_volume,
            step=0.05, label="Music Volume", value_fmt=pct_fmt)
        self._sfx_vol_slider = Slider(
            pygame.Rect(0, 0, 1, 1), 0.0, 1.0, gm.sfx_volume,
            step=0.05, label="Sound Effects Volume", value_fmt=pct_fmt)
        # Resolution picker — a click-to-expand list, same UX as the
        # startup picker (startup_picker.py's run_startup_resolution_picker):
        # every option is shown with its own Recommended/Not Recommended
        # label up front, and picking one applies it immediately. Replaces
        # the old Prev/Next stepper + separate "Not Recommended" warning
        # modal — that combo meant you couldn't see which resolutions were
        # safe until AFTER landing on one and getting the warning, and the
        # modal itself needed three differently-worded buttons just to
        # cover what the list view now shows inline for every row at once.
        self._res_dropdown_open: bool = False
        self._res_dropdown_rect: pygame.Rect = pygame.Rect(0, 0, 1, 1)
        self._res_row_rects: list = []

        self._all_buttons: list = []   # flattened each frame for update()/draw()
        self._autosave_timer: float = 0.0

    def on_exit(self):
        for nb in self._numboxes:
            if nb.focused:
                nb.commit()
        if self._hint_pct_box.focused:
            self._hint_pct_box.commit()
        if self._log_cap_box.focused:
            self._log_cap_box.commit()
        save_settings(self.gm)

    # ── Resolution change ───────────────────────────────────────────────────

    def _apply_resolution(self):
        self.manager._pending_resolution = RESOLUTIONS[self._res_idx]

    def _select_resolution(self, idx: int):
        """Applies a resolution directly. The list already shows every
        option's Recommended/Not Recommended status up front (see
        _draw_res_dropdown), so — unlike the old Prev/Next stepper —
        there's nothing left to warn about after the fact; picking a
        Not-Recommended entry is an informed choice made right there in
        the list, not a surprise a modal has to interrupt to explain."""
        self._res_idx = idx % len(RESOLUTIONS)
        self._apply_resolution()

    def _on_reset_defaults(self):
        reset_to_defaults(self.gm)
        gm = self.gm
        # Re-sync every widget that caches its own copy of a gm value —
        # otherwise the screen would keep showing stale numbers/positions
        # until the settings screen was re-entered.
        self._numboxes[0].value = gm.turn_timer_secs
        self._numboxes[0].text  = str(int(gm.turn_timer_secs))
        self._numboxes[1].value = gm.post_play_delay_secs
        self._numboxes[1].text  = str(int(gm.post_play_delay_secs))
        self._numboxes[2].value = gm.counter_window_secs
        self._numboxes[2].text  = str(int(gm.counter_window_secs))
        self._hint_pct_box.value = gm.hint_threshold_pct
        self._hint_pct_box.text  = str(int(gm.hint_threshold_pct))
        self._log_cap_box.value = gm.max_log_pairs
        self._log_cap_box.text  = str(int(gm.max_log_pairs))
        self._music_vol_slider.value = gm.music_volume
        self._sfx_vol_slider.value = gm.sfx_volume
        self._res_idx = RESOLUTIONS.index(gm.resolution) if gm.resolution in RESOLUTIONS else 0
        self._apply_resolution()
        self._reset_confirm_timer = 2.0

    def _toggle_res_dropdown(self):
        self._res_dropdown_open = not self._res_dropdown_open

    def _wrap_note(self, text: str, cw: int) -> list:
        """Word-wrap a note against the same tiny font used to draw it,
        so multi-sentence notes fit inside their card instead of
        overflowing past its edges."""
        font_xs = self.assets.font_scaled('ui_tiny', get_chrome_scale(*self.gm.resolution))
        return wrap_text(font_xs, text, cw - 2 * self.PAD_OUTER)

    def _toggle_ads_removed(self):
        """Flip the profile's ads_removed PURCHASE flag (Part 5) — a
        dev-only stand-in for the eventual real purchase completing.
        No-op if there's no profile attached (shouldn't happen once
        main.py wires one up, but keeps this button harmless in any
        context that constructs a bare GameManager)."""
        gm = self.gm
        if gm.profile is None:
            return
        gm.profile['ads_removed'] = not gm.profile.get('ads_removed', False)
        from core.profile_store import save_profile
        save_profile(gm.profile)

    # ── Layout ───────────────────────────────────────────────────────────────

    def _flow(self, sw: int, sh: int) -> list:
        """Builds the full list of (card_rect, [row specs]) groups, with every
        widget rect already placed in *absolute screen space* — i.e. the
        scroll offset is baked in here, once, so draw() and handle_event()
        can never disagree about where anything is."""
        cx        = sw // 2
        card_w    = max(360, min(get_ui_scale(sw, sh)['menu_w'], sw - 80))
        left      = cx - card_w // 2
        top0      = self._viewport_top - int(self.scroll_offset) + 16
        cs        = get_chrome_scale(sw, sh)
        chrome_scale = cs  # kept as an alias — this name is used further down already
        s         = lambda px: round(px * cs)
        # Shadow the class-level baseline constants with this frame's
        # scaled values — _flow() always runs to completion (and is
        # always called fresh, once per draw() — see that method's own
        # call site) before anything else in this scene reads them, so
        # every self.PAD_OUTER/CARD_GAP/ROW_H access below and any
        # later in the same draw() pass sees the correctly-scaled
        # value, not the 1280x800-baseline pixel constant.
        self.PAD_OUTER = s(24)
        self.CARD_GAP  = s(18)
        self.ROW_H     = s(56)

        cards = []
        y = top0

        def card_start(title):
            nonlocal y
            y += self.PAD_OUTER
            header_y = y
            y += s(30)
            return header_y

        # ── Card: Timers ─────────────────────────────────────────────────
        card_top = y
        hy = card_start("Timers")
        rows = []
        box_w, box_h = s(130), s(36)
        step_w = s(28)
        for nb in self._numboxes:
            row_y = y
            label_y = row_y
            nb.rect = pygame.Rect(left + card_w - self.PAD_OUTER - box_w, row_y, box_w, box_h)
            nb.minus_rect = pygame.Rect(nb.rect.x - step_w - s(6), row_y, step_w, box_h)
            nb.plus_rect  = pygame.Rect(nb.rect.right + s(6), row_y, step_w, box_h)
            rows.append(('numbox', nb, left, label_y, card_w))
            y += self.ROW_H
        note_y = y
        note_lines = self._wrap_note("Set to 0 to disable timers", card_w)
        rows.append(('note', note_lines, left, note_y, card_w))
        y += s(20) * len(note_lines) + s(6)
        y += self.PAD_OUTER
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Timers", rows))
        y += self.CARD_GAP

        # ── Card: Deck & Logging ─────────────────────────────────────────
        card_top = y
        hy = card_start("Deck & Logging")
        rows = []
        rows.append(('label', "Jokers per Deck:", left, y, card_w))
        y += s(30)
        bw = s(90)
        gap = s(14)
        total = bw * 2 + gap
        bx = left + (card_w - total) // 2
        self._joker_btns[2].rect = pygame.Rect(bx, y, bw, s(40))
        self._joker_btns[4].rect = pygame.Rect(bx + bw + gap, y, bw, s(40))
        rows.append(('joker', y))
        y += s(40) + self.PAD_OUTER

        rows.append(('label', "Logging (for bug reports):", left, y, card_w))
        y += s(30)
        bw2 = s(110)
        gap2 = s(12)
        total2 = bw2 * 3 + gap2 * 2
        bx2 = left + (card_w - total2) // 2
        for i, lvl in enumerate(('OFF', 'LOW', 'HIGH')):
            self._log_btns[lvl].rect = pygame.Rect(bx2 + i * (bw2 + gap2), y, bw2, s(40))
        rows.append(('loglevel', y))
        y += s(40) + s(6)
        log_note_lines = self._wrap_note(
            "HIGH writes a detailed log file to the 'logs' folder — share it when reporting bugs",
            card_w)
        rows.append(('note', log_note_lines, left, y, card_w))
        y += s(20) * len(log_note_lines) + s(6)
        y += self.PAD_OUTER

        box_w3, box_h3 = s(150), s(36)
        self._log_cap_box.rect = pygame.Rect(left + card_w - self.PAD_OUTER - box_w3, y, box_w3, box_h3)
        self._log_cap_box.minus_rect = pygame.Rect(self._log_cap_box.rect.x - step_w - s(6), y, step_w, box_h3)
        self._log_cap_box.plus_rect  = pygame.Rect(self._log_cap_box.rect.right + s(6), y, step_w, box_h3)
        rows.append(('logcap', self._log_cap_box, left, y, card_w))
        # This row draws TWO stacked lines on its left side (the "Max
        # saved log files" label, then a shorter "(0 = unlimited)"
        # sub-label right below it — see the 'logcap' branch of
        # draw()), which together are slightly taller than box_h3
        # alone. Advancing y by only box_h3 left the sub-label's own
        # text overlapping the note paragraph that follows (confirmed
        # via a real screenshot at both 1024x640 and 3840x2160 — this
        # wasn't a resolution-specific glitch, the row was simply
        # under-sized at every scale). Sized from the same two fonts
        # draw() actually renders that text with, not a fixed guess.
        _logcap_two_line_h = (self.assets.font_scaled('ui_normal', cs).get_height() + 1
                              + self.assets.font_scaled('ui_tiny', cs).get_height())
        y += max(box_h3, _logcap_two_line_h) + s(6)
        cap_note_lines = self._wrap_note(
            "Deletes oldest saved logs beyond this count — they're also Chuo/MSOMI "
            "training data, so keep unlimited unless disk space is a concern",
            card_w)
        rows.append(('note', cap_note_lines, left, y, card_w))
        y += s(20) * len(cap_note_lines) + s(6)
        y += self.PAD_OUTER
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Deck & Logging", rows))
        y += self.CARD_GAP

        # ── Card: Rules ───────────────────────────────────────────────────
        card_top = y
        hy = card_start("Rules")
        rows = []
        for key, label in self._toggle_keys:
            rows.append(('toggle_label', label, left, y, card_w))
            y += s(28)
            btn_w = s(110)
            self._toggle_btns[key].rect = pygame.Rect(cx - btn_w // 2, y, btn_w, s(38))
            rows.append(('toggle', key))
            y += s(38) + s(16)
        y += self.PAD_OUTER - s(16)
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Rules", rows))
        y += self.CARD_GAP

        # ── Card: Player Assistance ─────────────────────────────────────
        card_top = y
        hy = card_start("Player Assistance")
        rows = []
        hint_key, hint_label = self._hint_toggle_key
        rows.append(('toggle_label', hint_label, left, y, card_w))
        y += s(28)
        btn_w = s(110)
        self._toggle_btns[hint_key].rect = pygame.Rect(cx - btn_w // 2, y, btn_w, s(38))
        rows.append(('toggle', hint_key))
        y += s(38) + s(18)

        box_w2, box_h2 = s(130), s(36)
        self._hint_pct_box.rect = pygame.Rect(left + card_w - self.PAD_OUTER - box_w2, y, box_w2, box_h2)
        self._hint_pct_box.minus_rect = pygame.Rect(self._hint_pct_box.rect.x - step_w - s(6), y, step_w, box_h2)
        self._hint_pct_box.plus_rect  = pygame.Rect(self._hint_pct_box.rect.right + s(6), y, step_w, box_h2)
        rows.append(('hintpct', self._hint_pct_box, left, y, card_w))
        y += self.ROW_H
        hint_note_lines = self._wrap_note(
            "Highlights one legal card once you've used this % of your turn "
            "timer. Needs Turn Timers Enabled and a non-zero Turn Timer "
            "above. Not a strategy hint — just something you can legally "
            "play.", card_w)
        rows.append(('note', hint_note_lines, left, y, card_w))
        y += s(20) * len(hint_note_lines) + s(6)
        y += self.PAD_OUTER
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Player Assistance", rows))
        y += self.CARD_GAP

        # ── Card: Advertising (Dev) — REMOVED from the Settings UI ────────
        # No longer shown to players (see the comment on self._ads_toggle_key
        # above for why). The underlying gm.ads_enabled / gm.profile
        # ['ads_removed'] flags, the AdBanner class, and the render gate
        # in _ads_showing() are untouched and still fully functional —
        # only this settings card was removed. Re-adding a card here
        # (same shape as the "Player Assistance" card just above) is
        # all it'd take to bring the dev toggles back if ever needed.

        # ── Card: Display ────────────────────────────────────────────────
        card_top = y
        hy = card_start("Display")
        rows = []
        rows.append(('label', "Window Resolution:", left, y, card_w))
        y += s(30)
        res_box_h = s(44)
        self._res_dropdown_rect = pygame.Rect(left, y, card_w, res_box_h)
        rows.append(('res', left, y, card_w, res_box_h))
        y += res_box_h + s(6)
        res_note_lines = self._wrap_note("Resolution change takes effect immediately", card_w)
        rows.append(('note', res_note_lines, left, y, card_w))
        y += s(20) * len(res_note_lines) + s(6)
        y += self.PAD_OUTER
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Display", rows))
        y += self.CARD_GAP

        # ── Card: Audio ──────────────────────────────────────────────────
        card_top = y
        hy = card_start("Audio")
        rows = []
        btn_w = s(110)
        slider_w = card_w - 2 * self.PAD_OUTER
        slider_h = s(14)

        key, label = self._music_toggle_key
        rows.append(('toggle_label', label, left, y, card_w))
        y += s(28)
        self._toggle_btns[key].rect = pygame.Rect(cx - btn_w // 2, y, btn_w, s(38))
        rows.append(('toggle', key))
        y += s(38) + s(24)

        self._music_vol_slider.rect = pygame.Rect(left + self.PAD_OUTER, y, slider_w, slider_h)
        rows.append(('slider', self._music_vol_slider))
        y += slider_h + s(22)

        music_note_lines = self._wrap_note(
            "Controls the menu/gameplay music and the Chuo drum layer together.", card_w)
        rows.append(('note', music_note_lines, left, y, card_w))
        y += s(20) * len(music_note_lines) + s(14)

        sfx_key, sfx_label = self._sfx_toggle_key
        rows.append(('toggle_label', sfx_label, left, y, card_w))
        y += s(28)
        self._toggle_btns[sfx_key].rect = pygame.Rect(cx - btn_w // 2, y, btn_w, s(38))
        rows.append(('toggle', sfx_key))
        y += s(38) + s(24)

        self._sfx_vol_slider.rect = pygame.Rect(left + self.PAD_OUTER, y, slider_w, slider_h)
        rows.append(('slider', self._sfx_vol_slider))
        y += slider_h + s(22)

        sfx_note_lines = self._wrap_note(
            "Controls card-play and UI sound effects.", card_w)
        rows.append(('note', sfx_note_lines, left, y, card_w))
        y += s(20) * len(sfx_note_lines) + s(6)
        y += self.PAD_OUTER
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Audio", rows))
        y += self.CARD_GAP

        # ── Card: Credits ────────────────────────────────────────────────
        card_top = y
        hy = card_start("Credits")
        rows = []
        for entry in MUSIC_CREDITS:
            line = f"{entry['slot']}: \"{entry['title']}\" by {entry['author']} ({entry['license']})"
            rows.append(('note', self._wrap_note(line, card_w), left, y, card_w))
            y += s(20) * len(self._wrap_note(line, card_w)) + s(8)
        y += self.PAD_OUTER - s(8)
        cards.append(('panel', pygame.Rect(left, card_top, card_w, y - card_top), "Credits", rows))
        y += self.CARD_GAP

        # ── Back / Reset buttons ─────────────────────────────────────────
        back_w, back_h = round(220 * chrome_scale), round(48 * chrome_scale)
        back_rect = pygame.Rect(cx - back_w // 2, y, back_w, back_h)
        self._back_btn.rect = back_rect
        cards.append(('back', back_rect))
        y += back_h + round(16 * chrome_scale)

        reset_rect = pygame.Rect(cx - back_w // 2, y, back_w, back_h)
        self._reset_btn.rect = reset_rect
        cards.append(('reset', reset_rect))
        y += back_h + round(24 * chrome_scale)

        # Content height is measured in *unscrolled* terms, i.e. relative to
        # the viewport top, so re-derive it from where we'd have ended up
        # with scroll_offset == 0.
        self._content_height = (y - top0) + 16
        return cards

    # ── Scroll helpers ───────────────────────────────────────────────────────

    def _max_scroll(self, sh: int) -> int:
        viewport_h = sh - self._viewport_top - 10
        return max(0, self._content_height - viewport_h)

    def _set_scroll(self, value: float, sh: int):
        self.scroll_offset = max(0, min(self._max_scroll(sh), value))

    def _gather_buttons(self):
        return [self._back_btn, self._reset_btn,
                self._joker_btns[2], self._joker_btns[4],
                self._log_btns['OFF'], self._log_btns['LOW'], self._log_btns['HIGH'],
                *self._toggle_btns.values(),
                # _ads_removed_btn deliberately excluded — its card was
                # removed from the Settings UI (see self._ads_toggle_key's
                # comment); its .rect is never updated so it'd sit inert
                # at (0,0,1,1) even if left in, but omitting it here is
                # cleaner than leaving a dead 1x1 click target around.
                ]

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event):
        gm = self.gm
        sw, sh = gm.resolution
        max_scroll = self._max_scroll(sh)

        # Resolution picker list — nothing else on this screen (scroll,
        # other toggles) should be reachable while it's open, same
        # modal-gating pattern the old warning dialog used.
        if self._res_dropdown_open:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for i, r in enumerate(self._res_row_rects):
                    if r.collidepoint(event.pos):
                        self._select_resolution(i)
                        break
                self._res_dropdown_open = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._res_dropdown_open = False
            return

        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = _scroll_wheel_delta(self.scroll_offset, event.y, 50, max_scroll)
            self._scroll_bounce = None
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._scrollbar_rect and self._scrollbar_rect.collidepoint(event.pos):
                self._scrollbar_dragging = True
                return
            if self._scrollbar_track and self._scrollbar_track.collidepoint(event.pos) \
                    and max_scroll > 0:
                track = self._scrollbar_track
                t = (event.pos[1] - track.y) / max(1, track.height)
                self._set_scroll(t * max_scroll, sh)
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._scrollbar_dragging = False
        if event.type == pygame.MOUSEMOTION and self._scrollbar_dragging:
            track = self._scrollbar_track
            if track:
                t = (event.pos[1] - track.y) / max(1, track.height)
                self._set_scroll(t * max_scroll, sh)
            return

        # Recompute layout NOW, with the current scroll offset, so every rect
        # used below is exactly what's currently on screen.
        self._flow(sw, sh)

        # Clicks above the title/viewport never hit content.
        if hasattr(event, 'pos') and event.type == pygame.MOUSEBUTTONDOWN \
                and event.pos[1] < self._viewport_top:
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 \
                and self._res_dropdown_rect.collidepoint(event.pos):
            self._res_dropdown_open = True
            return

        # Number boxes (typing works regardless of mouse position, clicks are
        # rect-checked internally).
        for nb in self._numboxes:
            nb.handle_event(event)
        self._hint_pct_box.handle_event(event)
        self._log_cap_box.handle_event(event)
        self._music_vol_slider.handle_event(event)
        self._sfx_vol_slider.handle_event(event)

        for btn in self._gather_buttons():
            btn.handle_event(event)

    def update(self, dt):
        gm = self.gm

        if self._res_dropdown_open:
            # Row hover is computed directly in _draw_res_dropdown from
            # the live mouse position each frame — nothing to update.
            return

        gm.turn_timer_secs      = self._numboxes[0].value
        gm.post_play_delay_secs = self._numboxes[1].value
        gm.counter_window_secs  = self._numboxes[2].value
        gm.hint_threshold_pct   = self._hint_pct_box.value
        gm.max_log_pairs        = self._log_cap_box.value
        gm.music_volume         = self._music_vol_slider.value
        gm.sfx_volume           = self._sfx_vol_slider.value
        if not pygame.mouse.get_pressed()[0]:
            self._scrollbar_dragging = False

        sw, sh = gm.resolution
        self._flow(sw, sh)   # re-clamp / re-place on resize, keep buttons live
        self.scroll_offset, self._scroll_bounce = _settle_scroll(
            self.scroll_offset, self._scroll_bounce, dt, self._max_scroll(sh))

        mouse_pos = pygame.mouse.get_pos()
        mouse_down = pygame.mouse.get_pressed()[0]
        in_viewport = mouse_pos[1] >= self._viewport_top
        for btn in self._gather_buttons():
            btn.update(dt, mouse_pos if in_viewport else (-1, -1))
        for nb in self._numboxes:
            nb.update(dt, mouse_pos if in_viewport else (-1, -1), mouse_down)
        self._hint_pct_box.update(dt, mouse_pos if in_viewport else (-1, -1), mouse_down)
        self._log_cap_box.update(dt, mouse_pos if in_viewport else (-1, -1), mouse_down)

        if self._reset_confirm_timer > 0:
            self._reset_confirm_timer = max(0.0, self._reset_confirm_timer - dt)

        # Autosave periodically while sitting on the Settings screen, in
        # addition to the save on_exit — cheap (a few dozen bytes of JSON)
        # and means settings survive even an unexpected quit mid-tweak.
        self._autosave_timer += dt
        if self._autosave_timer >= 2.0:
            self._autosave_timer = 0.0
            save_settings(gm)

    # ── Draw ──────────────────────────────────────────────────────────────────

    def draw(self, surf):
        gm = self.gm
        sw, sh = gm.resolution
        cx = sw // 2

        surf.fill((12, 25, 18))
        _cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', _cs)
        font_md = self.assets.font_scaled('ui_medium', _cs)
        font_sm = self.assets.font_scaled('ui_normal', _cs)
        font_xs = self.assets.font_scaled('ui_tiny', _cs)

        title = font_lg.render("Settings", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, 18))

        viewport_h = sh - self._viewport_top - 10
        viewport_rect = pygame.Rect(0, self._viewport_top, sw, viewport_h)

        cards = self._flow(sw, sh)

        prev_clip = surf.get_clip()
        surf.set_clip(viewport_rect)

        for entry in cards:
            if entry[0] == 'back':
                self._back_btn.draw(surf)
                continue
            if entry[0] == 'reset':
                self._reset_btn.draw(surf)
                if self._reset_confirm_timer > 0:
                    msg = font_xs.render("Settings reset to defaults and saved",
                                         True, (140, 220, 150))
                    surf.blit(msg, (cx - msg.get_width() // 2,
                                   self._reset_btn.rect.bottom + 6))
                continue

            _, rect, card_title, rows = entry
            if rect.bottom < self._viewport_top or rect.top > self._viewport_top + viewport_h:
                continue  # fully offscreen, skip drawing (still positioned for hit-testing)

            Panel(rect, color=(20, 42, 28)).draw(surf)
            hdr = font_md.render(card_title, True, GOLD_LIGHT)
            surf.blit(hdr, (rect.x + self.PAD_OUTER, rect.y + self.PAD_OUTER - 2))

            for row in rows:
                kind = row[0]

                if kind == 'numbox':
                    _, nb, lx, ly, cw = row
                    lbl = font_sm.render(nb.label, True, (220, 224, 216))
                    surf.blit(lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2))
                    max_lbl = font_xs.render(f"(max {nb.max_val}s)", True, (150, 158, 148))
                    surf.blit(max_lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2
                                         + lbl.get_height() + 1))
                    nb.draw(surf, font_sm, font_xs)

                elif kind == 'label':
                    _, text, lx, ly, cw = row
                    lbl = font_md.render(text, True, WHITE)
                    surf.blit(lbl, (cx - lbl.get_width() // 2, ly))

                elif kind == 'note':
                    _, lines, lx, ly, cw = row
                    for li, line in enumerate(lines):
                        ns = font_xs.render(line, True, (160, 168, 158))
                        surf.blit(ns, (cx - ns.get_width() // 2, ly + li * 20))

                elif kind == 'hintpct':
                    _, nb, lx, ly, cw = row
                    lbl = font_sm.render(nb.label, True, (220, 224, 216))
                    surf.blit(lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2))
                    max_lbl = font_xs.render(f"(max {nb.max_val}{nb.unit})", True, (150, 158, 148))
                    surf.blit(max_lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2
                                         + lbl.get_height() + 1))
                    nb.draw(surf, font_sm, font_xs)

                elif kind == 'logcap':
                    _, nb, lx, ly, cw = row
                    lbl = font_sm.render(nb.label, True, (220, 224, 216))
                    surf.blit(lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2))
                    max_lbl = font_xs.render("(0 = unlimited)", True, (150, 158, 148))
                    surf.blit(max_lbl, (lx + self.PAD_OUTER, ly + nb.rect.height // 2 - lbl.get_height() // 2
                                         + lbl.get_height() + 1))
                    nb.draw(surf, font_sm, font_xs)

                elif kind == 'joker':
                    for val, btn in self._joker_btns.items():
                        sel = (val == gm.joker_count)
                        btn.color = GOLD if sel else (50, 90, 60)
                        btn.hover_color = GOLD_LIGHT if sel else (65, 110, 75)
                        btn.draw(surf)

                elif kind == 'loglevel':
                    for lvl, btn in self._log_btns.items():
                        sel = (lvl == gm.log_level)
                        btn.color = GOLD if sel else (50, 90, 60)
                        btn.hover_color = GOLD_LIGHT if sel else (65, 110, 75)
                        btn.draw(surf)

                elif kind == 'toggle_label':
                    _, label, lx, ly, cw = row
                    lbl = font_sm.render(f"{label}:", True, WHITE)
                    surf.blit(lbl, (cx - lbl.get_width() // 2, ly))

                elif kind == 'toggle':
                    _, key = row
                    state = getattr(gm, key)
                    btn = self._toggle_btns[key]
                    btn.color = (40, 140, 50) if state else (100, 40, 40)
                    btn.hover_color = (55, 165, 65) if state else (130, 55, 55)
                    btn.text = "ON" if state else "OFF"
                    btn.draw(surf)

                elif kind == 'toggle_profile':
                    # Same visuals as 'toggle', but state lives on
                    # gm.profile (a dict) rather than a plain gm
                    # attribute — see ads_removed (Part 5).
                    _, getter, btn = row
                    state = getter()
                    btn.color = (40, 140, 50) if state else (100, 40, 40)
                    btn.hover_color = (55, 165, 65) if state else (130, 55, 55)
                    btn.text = "ON" if state else "OFF"
                    btn.draw(surf)

                elif kind == 'res':
                    _, bx, by, bw, bh = row
                    box = pygame.Rect(bx, by, bw, bh)
                    pygame.draw.rect(surf, (30, 55, 40), box, border_radius=round(8 * _cs))
                    pygame.draw.rect(surf, GOLD if self._res_dropdown_open else (90, 110, 95), box,
                                     width=2, border_radius=round(8 * _cs))
                    optimum_idx = _optimum_resolution_idx()
                    cur_label = RES_LABELS[self._res_idx]
                    if self._res_idx == optimum_idx:
                        cur_label += "  (Recommended)"
                        cur_color = RECOMMENDED_COLOR
                    elif _resolution_exceeds_display(RESOLUTIONS[self._res_idx]):
                        cur_label += "  (Not Recommended)"
                        cur_color = NOT_RECOMMENDED_COLOR
                    else:
                        cur_color = WHITE
                    cur = font_sm.render(cur_label, True, cur_color)
                    surf.blit(cur, (box.x + round(14 * _cs), box.centery - cur.get_height() // 2))
                    # Vector-drawn chevron, not a Unicode triangle glyph
                    # (\u25B2/\u25BC) — neither is in any of this
                    # project's bundled fonts, so it rendered as a tofu
                    # box. Same fix pattern as SUIT_ICON/draw_icon
                    # already use for suit glyphs.
                    chevron_kind = 'chevron_up' if self._res_dropdown_open else 'chevron_down'
                    chevron_rect = pygame.Rect(0, 0, round(20 * _cs), round(20 * _cs))
                    chevron_rect.center = (box.right - round(22 * _cs), box.centery)
                    draw_icon(surf, chevron_rect, chevron_kind, WHITE, width=2)

                elif kind == 'slider':
                    _, slider = row
                    slider.draw(surf, font_sm)

        surf.set_clip(prev_clip)

        # ── Scrollbar ────────────────────────────────────────────────────────
        max_scroll = self._max_scroll(sh)
        if max_scroll > 0:
            track = pygame.Rect(sw - 10, self._viewport_top, 6, viewport_h)
            self._scrollbar_track = track
            pygame.draw.rect(surf, (40, 60, 45), track, border_radius=3)
            thumb_h = max(30, int(viewport_h * viewport_h / max(1, self._content_height)))
            thumb_y = track.y + int((viewport_h - thumb_h) * (self.scroll_offset / max_scroll))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            self._scrollbar_rect = thumb
            pygame.draw.rect(surf, GOLD if self._scrollbar_dragging else (110, 150, 120),
                             thumb, border_radius=3)
            hint = font_xs.render("scroll", True, (160, 168, 158))
            surf.blit(hint, (sw - hint.get_width() - 16, self._viewport_top - 20))
        else:
            self._scrollbar_track = None
            self._scrollbar_rect = None

        if self._res_dropdown_open:
            self._draw_res_dropdown(surf)

    def _draw_res_dropdown(self, surf: pygame.Surface):
        """Full list of every resolution, each labelled Recommended/Not
        Recommended right there in the row — same information the old
        after-the-fact warning modal only showed for whichever one you'd
        already picked. Styled after startup_picker.py's own list (see
        solution_Selecting_Resolutions_InGame.png), shown here as a
        centered overlay rather than an inline dropdown so it's never at
        risk of being clipped by the Settings screen's own scroll
        viewport."""
        gm = self.gm
        sw, sh = gm.resolution
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(overlay, (0, 0))

        cs2 = get_chrome_scale(sw, sh)
        s2 = lambda px: round(px * cs2)
        font_md = self.assets.font_scaled('ui_medium', cs2)
        font_sm = self.assets.font_scaled('ui_normal', cs2)
        font_xs = self.assets.font_scaled('ui_tiny', cs2)

        optimum_idx = _optimum_resolution_idx()

        def label_for(i: int) -> str:
            label = RES_LABELS[i]
            if i == optimum_idx:
                label += "  (Recommended)"
            elif _resolution_exceeds_display(RESOLUTIONS[i]):
                label += "  (Not Recommended)"
            return label

        def color_for(i: int):
            if i == optimum_idx:
                return RECOMMENDED_COLOR
            if _resolution_exceeds_display(RESOLUTIONS[i]):
                return NOT_RECOMMENDED_COLOR
            return WHITE

        row_h = s2(44)
        row_gap = s2(4)
        pw = min(s2(460), sw - s2(60))
        header_h = s2(60)
        ph = min(header_h + (row_h + row_gap) * len(RESOLUTIONS) + s2(16), sh - s2(30))
        panel = pygame.Rect(sw // 2 - pw // 2, sh // 2 - ph // 2, pw, ph)
        Panel(panel, color=(20, 42, 28)).draw(surf)

        title = font_md.render("Select Display Resolution", True, GOLD_LIGHT)
        surf.blit(title, (panel.centerx - title.get_width() // 2, panel.y + s2(12)))

        max_w, max_h = _detect_display_caps()
        if max_w and max_h:
            det = font_xs.render(f"Detected display: {max_w}\u00d7{max_h}", True, (190, 196, 186))
            surf.blit(det, (panel.centerx - det.get_width() // 2,
                            panel.y + s2(12) + title.get_height() + s2(2)))

        list_top = panel.y + header_h
        mouse_pos = pygame.mouse.get_pos()
        self._res_row_rects = []
        for i in range(len(RESOLUTIONS)):
            r = pygame.Rect(panel.x + s2(10), list_top + i * (row_h + row_gap),
                            panel.w - s2(20), row_h)
            self._res_row_rects.append(r)
            hovered = r.collidepoint(mouse_pos)
            if i == self._res_idx:
                bg = (55, 95, 65)
            elif hovered:
                bg = (45, 75, 55)
            else:
                bg = (30, 55, 40)
            pygame.draw.rect(surf, bg, r, border_radius=s2(6))
            pygame.draw.rect(surf, (70, 90, 75), r, width=1, border_radius=s2(6))
            lbl = font_sm.render(label_for(i), True, color_for(i))
            surf.blit(lbl, (r.x + s2(14), r.centery - lbl.get_height() // 2))


class RulesScene(Scene):
    """Read-only 'How to Play' reference, built from the rule engine's actual
    behaviour. Reuses the same single-source-of-truth scroll pattern as
    SettingsScene: _flow() computes absolute on-screen rects for the current
    scroll offset, called identically by draw() and handle_event()."""

    PAD_OUTER = 22
    CARD_GAP  = 16
    LINE_GAP  = 6
    PARA_GAP  = 12

    SECTIONS = [
        ("The Basics", [
            "KADI is played with a standard 52-card deck across 4 suits "
            "(Spades, Love, Dice, Flowers), plus 2 or 4 Jokers depending on "
            "the Jokers per Deck setting.",
            "Each player starts with 4 cards. The discard pile always opens "
            "on a plain Finishing card (4, 5, 6, 7, 9, or 10).",
            "On your turn, play a card (or a valid multi-card combo) that "
            "matches the suit or rank of the top discard card, or draw a "
            "card if you can't or don't want to play.",
        ]),
        ("Card Effects", [
            "4, 5, 6, 7, 9, 10 - Finishing: plain cards with no special "
            "effect. You can only end your hand on one of these.",
            "8 and Q - Question: must be followed in the same play by a "
            "connecting answer card (any Finishing, pick-up, J, K, or ACE). "
            "Play Questions with no answer and you draw 1 penalty card.",
            "J - Jump: skips the next player's turn. Several Js played "
            "together skip that many players (in a 2-player game this "
            "instead grants you an extra turn). The player about to be "
            "jumped can counter by playing a J of their own within the "
            "counter window (see Settings) - if they don't, they're "
            "jumped. J is the only card that can counter a J.",
            "K - Kickback: reverses the direction of play. An odd number "
            "of Ks must be played alone. Play an even number of Ks "
            "together and the reversal cancels out, returning the turn "
            "to you instead - you may then bundle any valid answer card "
            "onto that same play.",
            "ACE (A): lets you declare a new current suit, or shields you "
            "from an active pick-up chain instead of drawing.",
            "2: forces the next player to pick up 2 cards or counter. "
            "3: forces the next player to pick up 3 cards or counter.",
            "Joker: wild pick-up-5 card. Always playable and always "
            "counters a pick-up chain, regardless of suit.",
        ]),
        ("Pick-up Chains", [
            "When a 2, 3, or Joker is played, the next player must either "
            "play another pick-up card to stack the total, or draw the full "
            "accumulated total.",
            "Cards of the same rank always stack (e.g. 2 then 2). Mixing 2s "
            "and 3s requires matching the suit of the previous card in the "
            "chain.",
            "A Joker resets the suit requirement - any pick-up card can "
            "follow a Joker, regardless of suit.",
            "An ACE can shield (cancel) an active pick-up chain entirely "
            "instead of being drawn against.",
        ]),
        ("Playing Multiple Cards", [
            "Cards of the same rank can always be played together as a set "
            "(e.g. three 7s).",
            "Question cards (8/Q) can be chained together as long as each "
            "links to the one before it by suit or rank, then must be "
            "followed by a connecting answer.",
            "J and K chains work the same way - any number of them played "
            "together, optionally followed by a connecting answer card.",
            "An ACE can answer any of these chains, and connects to "
            "anything.",
        ]),
        ("Declaring KADI & Winning", [
            "Before the play that would empty your hand, you must declare "
            "KADI. You can only declare it if your hand will be left with "
            "only Finishing cards - or, if other cards remain, you must "
            "also hold a Question card among them.",
            "If you declare KADI but then draw a card, get forced to pick "
            "up, or fail to finish with a Finishing card, the declaration "
            "is cancelled and you'll need to declare again later.",
            "Going cardless without having declared KADI doesn't win the "
            "game - play continues and you draw 1 card on your next turn.",
            "If you legitimately KADI out and no other player is currently "
            "cardless at that moment, you win immediately - there is no "
            "way to counter a KADI finish itself. The only thing that can "
            "stop a KADI win is another player being cardless when your "
            "turn comes around.",
        ]),
        ("Settings That Change The Rules", [
            "Jokers per Deck (2 or 4): more Jokers means bigger possible "
            "pick-up chains can build up.",
            "ACE (A) Card Suit Integrity (OFF by default): when ON, ACE "
            "cards must also match the current suit or rank to be played or "
            "to shield a pick-up chain - the same restriction already "
            "placed on Q/J/K.",
            "J Counter Window: how long the jumped player has to play a "
            "J in response before the jump takes effect.",
        ]),
    ]

    def on_enter(self, **kwargs):
        self.scroll_offset: float = 0.0
        self._scroll_bounce: Optional[Tween] = None
        self._content_height: int = 0
        self._viewport_top: int = 64
        self._scrollbar_dragging: bool = False
        self._scrollbar_rect: Optional[pygame.Rect] = None
        self._scrollbar_track: Optional[pygame.Rect] = None

        self._back_btn = Button(pygame.Rect(0, 0, 220, 48), "Back",
                                self.assets.font_scaled('ui_large', get_chrome_scale(*self.gm.resolution)),
                                color=(60, 40, 100), hover_color=(90, 60, 140),
                                on_click=lambda: self.manager.switch('main_menu'))

    # ── Layout (single source of truth for draw + hit-testing) ─────────────

    def _flow(self, sw: int, sh: int) -> list:
        cx     = sw // 2
        card_w = max(380, min(get_ui_scale(sw, sh)['menu_w'] + 100, sw - 80))
        left   = cx - card_w // 2
        top0   = self._viewport_top - int(self.scroll_offset) + 16

        chrome_scale = get_chrome_scale(sw, sh)
        # Shadow the class-level baseline gap constants with this
        # frame's scaled values — same pattern as SettingsScene._flow()
        # (see that method's own comment for why this is safe: _flow()
        # always runs to completion, once per draw()/handle_event()/
        # update() call, before anything else reads these).
        self.PAD_OUTER = round(22 * chrome_scale)
        self.CARD_GAP  = round(16 * chrome_scale)
        self.LINE_GAP  = round(6 * chrome_scale)
        self.PARA_GAP  = round(12 * chrome_scale)
        text_w = card_w - 2 * self.PAD_OUTER

        font_md = self.assets.font_scaled('ui_medium', chrome_scale)
        font_sm = self.assets.font_scaled('ui_normal', chrome_scale)

        cards = []
        y = top0

        for title, paragraphs in self.SECTIONS:
            card_top = y
            y += self.PAD_OUTER
            y += font_md.get_height() + 8   # header

            wrapped_blocks = []
            for para in paragraphs:
                lines = wrap_text(font_sm, para, text_w)
                wrapped_blocks.append(lines)
                y += len(lines) * (font_sm.get_height() + self.LINE_GAP)
                y += self.PARA_GAP
            y += self.PAD_OUTER - self.PARA_GAP

            rect = pygame.Rect(left, card_top, card_w, y - card_top)
            cards.append(('panel', rect, title, wrapped_blocks))
            y += self.CARD_GAP

        chrome_scale = get_chrome_scale(sw, sh)
        back_w, back_h = round(220 * chrome_scale), round(48 * chrome_scale)
        back_rect = pygame.Rect(cx - back_w // 2, y, back_w, back_h)
        self._back_btn.rect = back_rect
        cards.append(('back', back_rect))
        y += back_h + round(24 * chrome_scale)

        self._content_height = (y - top0) + 16
        return cards

    def _max_scroll(self, sh: int) -> int:
        viewport_h = sh - self._viewport_top - 10
        return max(0, self._content_height - viewport_h)

    def _set_scroll(self, value: float, sh: int):
        self.scroll_offset = max(0, min(self._max_scroll(sh), value))

    # ── Events ───────────────────────────────────────────────────────────────

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        max_scroll = self._max_scroll(sh)

        if event.type == pygame.MOUSEWHEEL:
            self.scroll_offset = _scroll_wheel_delta(self.scroll_offset, event.y, 50, max_scroll)
            self._scroll_bounce = None
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._scrollbar_rect and self._scrollbar_rect.collidepoint(event.pos):
                self._scrollbar_dragging = True
                return
            if self._scrollbar_track and self._scrollbar_track.collidepoint(event.pos) \
                    and max_scroll > 0:
                track = self._scrollbar_track
                t = (event.pos[1] - track.y) / max(1, track.height)
                self._set_scroll(t * max_scroll, sh)
                return
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._scrollbar_dragging = False
        if event.type == pygame.MOUSEMOTION and self._scrollbar_dragging:
            track = self._scrollbar_track
            if track:
                t = (event.pos[1] - track.y) / max(1, track.height)
                self._set_scroll(t * max_scroll, sh)
            return

        self._flow(sw, sh)   # refresh rects for current scroll before hit-testing

        if hasattr(event, 'pos') and event.type == pygame.MOUSEBUTTONDOWN \
                and event.pos[1] < self._viewport_top:
            return

        self._back_btn.handle_event(event)

        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.manager.switch('main_menu')

    def update(self, dt):
        if not pygame.mouse.get_pressed()[0]:
            self._scrollbar_dragging = False
        sw, sh = self.gm.resolution
        self._flow(sw, sh)
        self.scroll_offset, self._scroll_bounce = _settle_scroll(
            self.scroll_offset, self._scroll_bounce, dt, self._max_scroll(sh))
        mouse_pos = pygame.mouse.get_pos()
        in_viewport = mouse_pos[1] >= self._viewport_top
        self._back_btn.update(dt, mouse_pos if in_viewport else (-1, -1))

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surf):
        sw, sh = self.gm.resolution
        cx = sw // 2

        surf.fill((12, 25, 18))
        _rs_cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', _rs_cs)
        font_md = self.assets.font_scaled('ui_medium', _rs_cs)
        font_sm = self.assets.font_scaled('ui_normal', _rs_cs)

        title_y = round(18 * _rs_cs)
        title = font_lg.render("How to Play", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, title_y))
        # Derived from the title's own actual rendered bottom rather
        # than an independent fixed 64 — that fixed value and the
        # title's font size both scaled with resolution, but via
        # unrelated math, so the card panel below was overlapping the
        # title's own text at higher resolutions (confirmed via a real
        # screenshot at 3840x2160).
        self._viewport_top = title_y + title.get_height() + round(20 * _rs_cs)

        viewport_h = sh - self._viewport_top - 10
        viewport_rect = pygame.Rect(0, self._viewport_top, sw, viewport_h)
        cards = self._flow(sw, sh)

        prev_clip = surf.get_clip()
        surf.set_clip(viewport_rect)

        for entry in cards:
            if entry[0] == 'back':
                self._back_btn.draw(surf)
                continue

            _, rect, sec_title, wrapped_blocks = entry
            if rect.bottom < self._viewport_top or rect.top > self._viewport_top + viewport_h:
                continue

            Panel(rect, color=(20, 42, 28)).draw(surf)
            hdr = font_md.render(sec_title, True, GOLD_LIGHT)
            surf.blit(hdr, (rect.x + self.PAD_OUTER, rect.y + self.PAD_OUTER - 2))

            ly = rect.y + self.PAD_OUTER + font_md.get_height() + 8
            for lines in wrapped_blocks:
                for line in lines:
                    ls = font_sm.render(line, True, (225, 228, 220))
                    surf.blit(ls, (rect.x + self.PAD_OUTER, ly))
                    ly += font_sm.get_height() + self.LINE_GAP
                ly += self.PARA_GAP

        surf.set_clip(prev_clip)

        # ── Scrollbar ────────────────────────────────────────────────────────
        max_scroll = self._max_scroll(sh)
        if max_scroll > 0:
            track = pygame.Rect(sw - 10, self._viewport_top, 6, viewport_h)
            self._scrollbar_track = track
            pygame.draw.rect(surf, (40, 60, 45), track, border_radius=3)
            thumb_h = max(30, int(viewport_h * viewport_h / max(1, self._content_height)))
            thumb_y = track.y + int((viewport_h - thumb_h) * (self.scroll_offset / max_scroll))
            thumb = pygame.Rect(track.x, thumb_y, track.width, thumb_h)
            self._scrollbar_rect = thumb
            pygame.draw.rect(surf, GOLD if self._scrollbar_dragging else (110, 150, 120),
                             thumb, border_radius=3)
            hint = self.assets.font_scaled('ui_tiny', _rs_cs).render("scroll", True, (160, 168, 158))
            surf.blit(hint, (sw - hint.get_width() - 16, self._viewport_top - 20))
        else:
            self._scrollbar_track = None
            self._scrollbar_rect = None



# ─── Chuo (MSOMI in-house training) ───────────────────────────────────────────

# Friendly display names for the trainable features — keeps Chuo's
# checkbox list readable without renaming the underlying feature keys
# (which stay exactly as _evaluate_play/decision_logger produce them).
_FEATURE_LABELS = {
    'cards_played':          "Cards played",
    'cards_remaining':       "Cards remaining after",
    'empties_hand':          "Empties hand",
    'wastes_win':            "Wastes a win (cardless, no KADI)",
    'leaves_kadi':           "Leaves a KADI-ready hand",
    'unanswered_question':   "Unanswered Question",
    'pickup_value_added':    "Pick-up value added",
    'has_suit_change':       "Includes a suit change (ACE)",
    'has_skip':              "Includes a Jump (skip)",
    'has_kickback':          "Includes a Kickback (reverse)",
    'has_question':          "Includes a Question",
    'next_is_threat':        "Next player is a threat",
    'stranded_cluster_cost': "Stranded same-rank cluster cost",
}


class ChuoScene(Scene):
    """CHUO (Swahili: university) — in-house MSOMI model training.

    Four tabs, left to right: pick which logged decisions to train on,
    pick which features to train with, configure the model, then train
    and save it. Everything here reads/writes plain JSON/JSONL files
    under logs/ and msomi_models/ — no live game state is touched, and
    nothing here affects a game in progress; a saved model only ever
    does anything once attached to an AI player via the MSOMI setting.
    """

    HELP_SECTIONS = [
        ("Before you start: turn on logging", [
            "Chuo trains a model from LOGGED decisions — human and AI "
            "moves recorded during real games. If logging is off, "
            "there's nothing here to train from.",
            "Go to Settings -> Deck & Logging -> Logging (for bug "
            "reports) and set it to HIGH, then go play a few games "
            "(any mode). Each finished game adds a new .jsonl file "
            "under the logs folder — that's what shows up in the "
            "Data tab below.",
        ]),
        ("The 4 tabs, in order", [
            "Data — pick which logged .jsonl files to train from (no "
            "limit on how many). Select All / Select None help with a "
            "long list; Browse for files... lets you pick logs from "
            "somewhere else on disk. Click Load Selected Logs once "
            "you've picked which ones to use.",
            "Features — choose which signals the model is allowed to "
            "learn from (what cards are in play, hand size, current "
            "suit, and so on). Leaving everything selected is a "
            "reasonable default; deselecting some is for experimenting.",
            "Model — set the human decision weight (how much more a "
            "human's move counts vs. an AI's, since human play is "
            "usually the more useful signal) and training iterations "
            "(higher = slower but usually better).",
            "Train & Results — click Train Model, then Save Model once "
            "you're happy with the results shown. Training runs "
            "locally and doesn't touch a game in progress.",
        ]),
        ("Using a trained model in a game", [
            "A saved model does nothing by itself — it has to be "
            "attached to an AI opponent. Go to Play vs AI, pick a "
            "difficulty (Easy/Medium/Hard), then use the MSOMI toggle "
            "next to the difficulty buttons to attach the model you "
            "just trained to that AI opponent.",
            "MSOMI is separate from difficulty, not a 4th tier — it "
            "layers on top of whichever difficulty is picked.",
        ]),
    ]

    ROW_H = 40
    LIST_VISIBLE_ROWS = 8

    def on_enter(self, **kwargs):
        self._tab = 0
        self._log_files = self._scan_log_files()
        self._selected_logs: set = set()
        self._loaded_decisions: Optional[list] = None
        self._load_stats: Optional[dict] = None

        self._feature_selected = {f: True for f in msomi_trainer.TRAINABLE_FEATURES}

        self._human_weight_box = NumberBox(
            pygame.Rect(0, 0, 1, 1), 2, 1, 10, step=1,
            label="Human decision weight", unit="x", zero_label=None)
        self._iterations_box = NumberBox(
            pygame.Rect(0, 0, 1, 1), 300, 50, 3000, step=50,
            label="Training iterations", unit="", zero_label=None)

        self._model_tier = 'light'
        self._trained_model: Optional[dict] = None
        self._saved_path: Optional[str] = None
        self._status = ""
        self._status_color = WHITE
        self._data_scroll = 0
        self._results_scroll = 0
        self._data_scroll_bounce: Optional[Tween] = None
        self._results_scroll_bounce: Optional[Tween] = None

        # Fixed-pixel buttons — box and label font scaled together via
        # get_chrome_scale(), same pattern as every other menu button in
        # this file. Tab buttons, log/feature row buttons, and
        # NumberBoxes are 1x1 placeholders resized every frame in
        # draw()/update() (see those methods for the scaled versions —
        # this whole scene, not just this construction block, now
        # scales with resolution).
        cs = get_chrome_scale(*self.gm.resolution)
        font_normal_s = self.assets.font_scaled('ui_normal', cs)
        font_small_s  = self.assets.font_scaled('ui_small', cs)
        font_large_s  = self.assets.font_scaled('ui_large', cs)
        self._chrome_scale = cs

        def csz(w, h):
            return pygame.Rect(0, 0, round(w * cs), round(h * cs))

        self._back_btn = Button(csz(140, 44), "Back", font_normal_s,
                                color=(60, 40, 100), hover_color=(90, 60, 140),
                                on_click=lambda: self.manager.switch('main_menu'))
        self._tab_btns = [
            Button(pygame.Rect(0, 0, 1, 1), name, font_normal_s,
                   on_click=(lambda i=i: self._set_tab(i)))
            for i, name in enumerate(["Data", "Features", "Model", "Train & Results"])
        ]

        self._select_all_logs_btn = Button(csz(150, 34), "Select All",
                                           font_small_s,
                                           on_click=self._select_all_logs)
        self._select_none_logs_btn = Button(csz(150, 34), "Select None",
                                            font_small_s,
                                            on_click=self._select_none_logs)
        self._load_btn = Button(csz(220, 44), "Load Selected Logs",
                                font_normal_s, on_click=self._load_selected_logs)
        self._refresh_btn = Button(csz(150, 34), "Refresh List",
                                   font_small_s, on_click=self._refresh_logs)
        self._browse_logs_btn = Button(csz(190, 34), "Browse for files...",
                                       font_small_s,
                                       color=(50, 90, 130), hover_color=(70, 115, 160),
                                       on_click=self._browse_for_logs)

        self._select_all_feat_btn = Button(csz(150, 34), "Select All",
                                           font_small_s,
                                           on_click=self._select_all_features)
        self._select_none_feat_btn = Button(csz(150, 34), "Select None",
                                            font_small_s,
                                            on_click=self._select_none_features)

        self._tier_light_btn = Button(csz(260, 60), "Light (Re-weighted Scorer)",
                                      font_small_s,
                                      on_click=lambda: setattr(self, '_model_tier', 'light'))
        self._tier_heavy_btn = Button(csz(260, 60), "Heavy (Tree Ensemble)",
                                      font_small_s)
        self._tier_heavy_btn.enabled = False  # reserved for Tier 2

        self._train_btn = Button(csz(220, 52), "Train Model",
                                 font_large_s,
                                 color=(160, 30, 30), hover_color=(200, 50, 50),
                                 on_click=self._do_train)
        self._save_btn = Button(csz(220, 44), "Save Model", font_normal_s,
                                color=(60, 110, 60), hover_color=(80, 145, 80),
                                on_click=self._do_save)
        self._save_btn.enabled = False

        self._feature_btns: Dict[str, Button] = {}
        self._log_btns: Dict[str, Button] = {}

        font_help_title = font_large_s
        font_help_head = font_normal_s
        font_help_body = font_small_s
        # Splice the MSOMI-attach illustration into "Using a trained
        # model in a game" — same pattern as GameplayScene's drag
        # illustration (see that scene's _build_buttons for why this
        # can't just live in the HELP_SECTIONS class constant).
        help_sections = [(heading, list(paras)) for heading, paras in self.HELP_SECTIONS]
        msomi_img = _load_help_image('help_msomi_attach.png')
        if msomi_img is not None:
            for i, (heading, paras) in enumerate(help_sections):
                if heading == "Using a trained model in a game":
                    paras.append(('image', msomi_img,
                                  "The MSOMI \"Attach Model...\" button, on the Play vs AI screen."))
                    help_sections[i] = (heading, paras)
                    break
        self._help = HelpOverlay("Chuo — Training Guide", help_sections,
                                 font_help_title, font_help_head, font_help_body)
        self._help_btn = make_help_button(pygame.Rect(0, 0, 1, 1), font_normal_s,
                                          on_click=self._help.open)

    def _layout_help_btn(self, sw: int, sh: int):
        # Same anchoring trick as MultiplayerMenuScene's — immediately
        # left of the shared sfx/music icon cluster.
        ac = getattr(self.manager, 'audio_controls', None)
        sz = round(32 * self._chrome_scale)
        if ac is not None and ac._btn_sfx.rect.width > 0:
            x = ac._btn_sfx.rect.left - round(6 * self._chrome_scale) - sz
            y = ac._btn_sfx.rect.top
        else:
            x, y = sw - round(10 * self._chrome_scale) - sz, round(10 * self._chrome_scale)
        self._help_btn.rect = pygame.Rect(x, y, sz, sz)

    # ── Data tab helpers ─────────────────────────────────────────────────────

    def _scan_log_files(self):
        d = game_logger.get_log_dir()
        try:
            files = [f for f in os.listdir(d) if f.endswith('.jsonl')]
        except OSError:
            files = []
        files.sort(reverse=True)
        return [(f, os.path.join(d, f)) for f in files]

    def _refresh_logs(self):
        builtin = self._scan_log_files()
        builtin_paths = {p for _, p in builtin}
        # Keep any externally-browsed files that are still selected, so
        # refreshing the built-in folder doesn't silently drop files
        # someone shared from elsewhere on the machine.
        external = [(f, p) for f, p in self._log_files
                    if p not in builtin_paths and p in self._selected_logs]
        self._log_files = builtin + external
        self._selected_logs = {p for _, p in self._log_files if p in self._selected_logs}
        self._status = f"Found {len(builtin)} log file(s) in the game's logs folder."
        self._status_color = WHITE

    def _select_all_logs(self):
        self._selected_logs = {p for _, p in self._log_files}

    def _select_none_logs(self):
        self._selected_logs = set()

    def _browse_for_logs(self):
        """Add .jsonl files from ANYWHERE on the computer — e.g. ones
        someone else shared — not just the game's own logs/ folder."""
        if not native_dialog.is_available():
            self._status = "File browsing isn't available on this system."
            self._status_color = (220, 120, 40)
            return
        paths = native_dialog.ask_open_files_multi(
            title="Select log files to train from",
            filetypes=[("MSOMI decision log", "*.jsonl"), ("All files", "*.*")])
        if not paths:
            return
        existing_paths = {p for _, p in self._log_files}
        added = 0
        for p in paths:
            if p not in existing_paths:
                self._log_files.append((os.path.basename(p), p))
                existing_paths.add(p)
                added += 1
            self._selected_logs.add(p)
        self._status = f"Added {added} external file(s) — now selected for loading."
        self._status_color = (140, 220, 140)

    def _load_selected_logs(self):
        if not self._selected_logs:
            self._status = "Select at least one log file first."
            self._status_color = (220, 120, 40)
            return
        try:
            decisions, stats = msomi_trainer.load_decisions(sorted(self._selected_logs))
        except Exception as e:
            self._status = f"Couldn't load logs: {e}"
            self._status_color = (220, 80, 80)
            return
        self._loaded_decisions = decisions
        self._load_stats = stats
        msg = (f"Loaded {stats['loaded']} decisions "
               f"({stats['human_count']} human, {stats['ai_count']} AI).")
        if stats['skipped_schema_mismatch']:
            msg += f" Skipped {stats['skipped_schema_mismatch']} (schema mismatch)."
        if stats['skipped_unparseable']:
            msg += f" Skipped {stats['skipped_unparseable']} (unreadable)."
        self._status = msg
        self._status_color = (140, 220, 140)

    # ── Feature tab helpers ──────────────────────────────────────────────────

    def _select_all_features(self):
        for f in self._feature_selected:
            self._feature_selected[f] = True

    def _select_none_features(self):
        for f in self._feature_selected:
            self._feature_selected[f] = False

    # ── Training ──────────────────────────────────────────────────────────────

    def _do_train(self):
        if self._loaded_decisions is None:
            self._status = "Load some log files in the Data tab first."
            self._status_color = (220, 120, 40)
            self._set_tab(0)
            return
        selected_features = [f for f, on in self._feature_selected.items() if on]
        if not selected_features:
            self._status = "Select at least one feature in the Features tab first."
            self._status_color = (220, 120, 40)
            self._set_tab(1)
            return
        try:
            model = msomi_trainer.train(
                self._loaded_decisions, selected_features,
                human_weight=float(self._human_weight_box.value),
                iterations=int(self._iterations_box.value),
                learning_rate=0.3)
        except Exception as e:
            self._status = f"Training failed: {e}"
            self._status_color = (220, 80, 80)
            self._trained_model = None
            self._save_btn.enabled = False
            return
        self._trained_model = model
        self._saved_path = None
        self._save_btn.enabled = True

        # Profile stat/badge (Part 4: "train your first model in Chuo").
        # No toast here — ChuoScene doesn't have GameplayScene's
        # MessageBanner mechanism, and building a new notification path
        # just for this one event isn't worth it; the badge still shows
        # up next time the Profile screen is opened.
        if self.gm.profile is not None:
            self.gm.profile['msomi']['models_trained'] += 1
            profile_store.award_badge(self.gm.profile, 'first_model_trained')
            if self.gm.profile['msomi']['models_trained'] >= 5:
                profile_store.award_badge(self.gm.profile, 'iterator')
            profile_store.save_profile(self.gm.profile)

        t = model['training']
        self._status = (f"Trained on {t['num_decisions']} decisions "
                        f"({t['num_human_decisions']} human) — "
                        f"agreement {t['train_agreement']*100:.1f}%.")
        self._status_color = (140, 220, 140)
        self._set_tab(3)

    def _do_save(self):
        if self._trained_model is None:
            return
        import datetime
        stamp = datetime.datetime.now().strftime("%d%m%Y_%H%M%S")
        filename = f"msomi_{stamp}.json"
        try:
            path = msomi_trainer.save_model(self._trained_model, filename)
        except Exception as e:
            self._status = f"Couldn't save model: {e}"
            self._status_color = (220, 80, 80)
            return
        self._saved_path = path
        self._status = f"Saved: {os.path.basename(path)}"
        self._status_color = (140, 220, 140)

    def _set_tab(self, i: int):
        self._tab = i

    # ── Events / update ──────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event):
        sw, sh = self.gm.resolution
        self._help.notice_activity()
        if self._help.handle_event(event, sw, sh):
            return
        self._help_btn.handle_event(event)

        if event.type == pygame.MOUSEWHEEL:
            if self._tab == 0:
                max_scroll = max(0, len(self._log_files) - self.LIST_VISIBLE_ROWS) * self.ROW_H
                self._data_scroll = _scroll_wheel_delta(self._data_scroll, event.y, self.ROW_H, max_scroll)
                self._data_scroll_bounce = None
            elif self._tab == 3 and self._trained_model:
                n = len(self._trained_model['weights'])
                max_scroll = max(0, n - self.LIST_VISIBLE_ROWS) * self.ROW_H
                self._results_scroll = _scroll_wheel_delta(self._results_scroll, event.y, self.ROW_H, max_scroll)
                self._results_scroll_bounce = None
            return

        self._back_btn.handle_event(event)
        for btn in self._tab_btns:
            btn.handle_event(event)

        if self._tab == 0:
            self._select_all_logs_btn.handle_event(event)
            self._select_none_logs_btn.handle_event(event)
            self._load_btn.handle_event(event)
            self._refresh_btn.handle_event(event)
            self._browse_logs_btn.handle_event(event)
            for btn in self._log_btns.values():
                btn.handle_event(event)
        elif self._tab == 1:
            self._select_all_feat_btn.handle_event(event)
            self._select_none_feat_btn.handle_event(event)
            for btn in self._feature_btns.values():
                btn.handle_event(event)
        elif self._tab == 2:
            self._tier_light_btn.handle_event(event)
            self._tier_heavy_btn.handle_event(event)
            self._human_weight_box.handle_event(event)
            self._iterations_box.handle_event(event)
        elif self._tab == 3:
            self._train_btn.handle_event(event)
            self._save_btn.handle_event(event)

    def update(self, dt: float):
        sw, sh = self.gm.resolution
        self._chrome_scale = get_chrome_scale(sw, sh)
        # Shadowed here (not just in draw()) so handle_event()'s scroll
        # math and draw()'s row layout always agree on the same ROW_H
        # within a given frame — same "run before anything else needs
        # it" reasoning as SettingsScene._flow()'s own constant shadowing.
        self.ROW_H = round(40 * self._chrome_scale)
        self._layout_help_btn(sw, sh)
        self._help.update_idle_glow(dt)
        mp = pygame.mouse.get_pos()
        mouse_down = pygame.mouse.get_pressed()[0]
        self._help_btn.update(dt, mp)
        self._back_btn.update(dt, mp)
        for btn in self._tab_btns:
            btn.update(dt, mp)

        data_max_scroll = max(0, len(self._log_files) - self.LIST_VISIBLE_ROWS) * self.ROW_H
        self._data_scroll, self._data_scroll_bounce = _settle_scroll(
            self._data_scroll, self._data_scroll_bounce, dt, data_max_scroll)
        if self._trained_model:
            n = len(self._trained_model['weights'])
            results_max_scroll = max(0, n - self.LIST_VISIBLE_ROWS) * self.ROW_H
            self._results_scroll, self._results_scroll_bounce = _settle_scroll(
                self._results_scroll, self._results_scroll_bounce, dt, results_max_scroll)

        if self._tab == 0:
            self._select_all_logs_btn.update(dt, mp)
            self._select_none_logs_btn.update(dt, mp)
            self._load_btn.update(dt, mp)
            self._refresh_btn.update(dt, mp)
            self._browse_logs_btn.update(dt, mp)
            for btn in self._log_btns.values():
                btn.update(dt, mp)
        elif self._tab == 1:
            self._select_all_feat_btn.update(dt, mp)
            self._select_none_feat_btn.update(dt, mp)
            for btn in self._feature_btns.values():
                btn.update(dt, mp)
        elif self._tab == 2:
            self._tier_light_btn.update(dt, mp)
            self._tier_heavy_btn.update(dt, mp)
            self._human_weight_box.update(dt, mp, mouse_down)
            self._iterations_box.update(dt, mp, mouse_down)
        elif self._tab == 3:
            self._train_btn.update(dt, mp)
            self._save_btn.update(dt, mp)

    # ── Draw ─────────────────────────────────────────────────────────────────

    def draw(self, surf: pygame.Surface):
        gm = self.gm
        sw, sh = gm.resolution
        surf.fill((22, 26, 34))
        cs = get_chrome_scale(sw, sh)
        self._chrome_scale = cs
        s = lambda px: round(px * cs)

        font_title = self.assets.font_scaled('ui_large', cs)
        title = font_title.render("CHUO", True, GOLD_LIGHT)
        title_y = s(14)
        surf.blit(title, (sw // 2 - title.get_width() // 2, title_y))
        sub_font = self.assets.font_scaled('ui_tiny', cs)
        sub = sub_font.render(
            "In-house MSOMI training — Swahili for \"university\"", True, (*WHITE, 150))
        sub_y = title_y + title.get_height() + s(2)
        surf.blit(sub, (sw // 2 - sub.get_width() // 2, sub_y))

        self._back_btn.rect.topleft = (s(16), s(16))
        self._back_btn.draw(surf)

        # Derived from the title+subtitle block's OWN actual rendered
        # height rather than a fixed s(70) unrelated to it — that fixed
        # value and the title/subtitle stack both happened to scale
        # with cs, but by unconnected math, so the gap between them
        # wasn't guaranteed — the subtitle's own text was overlapping
        # the tab row above it at every resolution checked (confirmed
        # via real screenshots at 1024x640 and 3840x2160 — this was
        # never resolution-specific, just always slightly too tight).
        tab_y = max(s(70), sub_y + sub.get_height() + s(14))
        tab_w = s(200)
        total_w = tab_w * len(self._tab_btns)
        start_x = sw // 2 - total_w // 2
        for i, btn in enumerate(self._tab_btns):
            btn.font = self.assets.font_scaled('ui_normal', cs)
            btn.rect = pygame.Rect(start_x + i * tab_w, tab_y, tab_w - s(6), s(40))
            btn.color = (90, 70, 140) if i == self._tab else (45, 45, 60)
            btn.hover_color = (115, 90, 170) if i == self._tab else (65, 65, 85)
            btn.draw(surf)

        content_top = max(tab_y + s(56), self._back_btn.rect.bottom + s(16))
        content_rect = pygame.Rect(s(40), content_top, sw - s(80), sh - content_top - s(20))
        Panel(content_rect, color=(30, 34, 44)).draw(surf)

        if self._tab == 0:
            self._draw_data_tab(surf, content_rect)
        elif self._tab == 1:
            self._draw_features_tab(surf, content_rect)
        elif self._tab == 2:
            self._draw_model_tab(surf, content_rect)
        elif self._tab == 3:
            self._draw_results_tab(surf, content_rect)

        self._help.draw_button_glow(surf, self._help_btn.rect)
        self._help_btn.draw(surf)
        self._help.draw(surf)

    def _draw_data_tab(self, surf, rect):
        cs = self._chrome_scale
        s = lambda px: round(px * cs)
        font = self.assets.font_scaled('ui_normal', cs)
        font_sm = self.assets.font_scaled('ui_small', cs)
        pad = s(20)
        header = font.render("Select log files (.jsonl) to train from — no limit on how many:",
                             True, WHITE)
        surf.blit(header, (rect.x + pad, rect.y + pad))

        log_dir = game_logger.get_log_dir()
        list_top = rect.y + pad + s(34)
        list_rect = pygame.Rect(rect.x + pad, list_top, rect.width - 2 * pad,
                                self.ROW_H * self.LIST_VISIBLE_ROWS)
        pygame.draw.rect(surf, (20, 22, 28), list_rect, border_radius=6)

        clip = surf.get_clip()
        surf.set_clip(list_rect)
        if not self._log_files:
            empty = font_sm.render("No .jsonl logs found yet — play some games with logging "
                                   "on (Settings) to generate training data.", True, (*WHITE, 160))
            surf.blit(empty, (list_rect.x + s(12), list_rect.y + s(12)))
        for i, (fname, fpath) in enumerate(self._log_files):
            y = list_rect.y + i * self.ROW_H - self._data_scroll
            if y + self.ROW_H < list_rect.y or y > list_rect.bottom:
                continue
            row_rect = pygame.Rect(list_rect.x, y, list_rect.width, self.ROW_H)
            btn = self._log_btns.get(fpath)
            if btn is None:
                btn = Button(pygame.Rect(0, 0, 1, 1), "", font_sm,
                            on_click=(lambda p=fpath: self._toggle_log(p)))
                self._log_btns[fpath] = btn
            else:
                btn.font = font_sm
            checked = fpath in self._selected_logs
            is_external = os.path.dirname(os.path.abspath(fpath)) != os.path.abspath(log_dir)
            tag = "  [external]" if is_external else ""
            btn.rect = row_rect.inflate(-8, -6)
            btn.text = f"{'[x]' if checked else '[ ]'}  {fname}{tag}"
            btn.color = (55, 75, 55) if checked else (40, 40, 50)
            btn.hover_color = (70, 95, 70) if checked else (55, 55, 68)
            btn.draw(surf)
        surf.set_clip(clip)

        gap = round(10 * self._chrome_scale)
        btn_y = list_rect.bottom + s(12)
        self._select_all_logs_btn.rect.topleft = (list_rect.x, btn_y)
        x = list_rect.x + self._select_all_logs_btn.rect.width + gap
        self._select_none_logs_btn.rect.topleft = (x, btn_y)
        x += self._select_none_logs_btn.rect.width + gap
        self._refresh_btn.rect.topleft = (x, btn_y)
        x += self._refresh_btn.rect.width + gap
        self._browse_logs_btn.rect.topleft = (x, btn_y)
        self._load_btn.rect.topleft = (list_rect.right - self._load_btn.rect.width, btn_y - s(5))
        self._select_all_logs_btn.draw(surf)
        self._select_none_logs_btn.draw(surf)
        self._refresh_btn.draw(surf)
        self._browse_logs_btn.draw(surf)
        self._load_btn.draw(surf)

        status_y = btn_y + s(50)
        if self._status:
            st = font_sm.render(self._status, True, self._status_color)
            surf.blit(st, (rect.x + pad, status_y))

    def _draw_features_tab(self, surf, rect):
        cs = self._chrome_scale
        s = lambda px: round(px * cs)
        font = self.assets.font_scaled('ui_normal', cs)
        font_sm = self.assets.font_scaled('ui_small', cs)
        pad = s(20)
        header = font.render("Select which features feed the model:", True, WHITE)
        surf.blit(header, (rect.x + pad, rect.y + pad))

        self._select_all_feat_btn.rect.topleft = (rect.x + pad, rect.y + pad + s(36))
        self._select_none_feat_btn.rect.topleft = (
            rect.x + pad + self._select_all_feat_btn.rect.width + s(10),
            rect.y + pad + s(36))
        self._select_all_feat_btn.draw(surf)
        self._select_none_feat_btn.draw(surf)

        grid_top = rect.y + pad + s(84)
        col_w = (rect.width - 2 * pad) // 2
        for i, feat in enumerate(msomi_trainer.TRAINABLE_FEATURES):
            col = i // 7
            row = i % 7
            x = rect.x + pad + col * col_w
            y = grid_top + row * self.ROW_H
            btn = self._feature_btns.get(feat)
            if btn is None:
                btn = Button(pygame.Rect(0, 0, 1, 1), "", font_sm,
                            on_click=(lambda f=feat: self._toggle_feature(f)))
                self._feature_btns[feat] = btn
            else:
                btn.font = font_sm
            checked = self._feature_selected[feat]
            btn.rect = pygame.Rect(x, y, col_w - s(16), self.ROW_H - s(6))
            label = _FEATURE_LABELS.get(feat, feat)
            btn.text = f"{'[x]' if checked else '[ ]'}  {label}"
            btn.color = (55, 75, 55) if checked else (40, 40, 50)
            btn.hover_color = (70, 95, 70) if checked else (55, 55, 68)
            btn.draw(surf)

    def _draw_model_tab(self, surf, rect):
        cs = self._chrome_scale
        s = lambda px: round(px * cs)
        font = self.assets.font_scaled('ui_normal', cs)
        font_sm = self.assets.font_scaled('ui_small', cs)
        pad = s(20)
        header = font.render("Model type:", True, WHITE)
        surf.blit(header, (rect.x + pad, rect.y + pad))

        self._tier_light_btn.rect.topleft = (rect.x + pad, rect.y + pad + s(36))
        self._tier_heavy_btn.rect.topleft = (
            rect.x + pad + self._tier_light_btn.rect.width + s(20),
            rect.y + pad + s(36))
        for b, tier in ((self._tier_light_btn, 'light'), (self._tier_heavy_btn, 'heavy')):
            b.color = (90, 70, 140) if self._model_tier == tier else (45, 45, 60)
            b.hover_color = (115, 90, 170) if self._model_tier == tier else (65, 65, 85)
        self._tier_light_btn.draw(surf)
        self._tier_heavy_btn.draw(surf)
        note = font_sm.render("Heavy (tree ensemble) is reserved for a larger dataset — "
                              "not needed yet.", True, (*WHITE, 150))
        surf.blit(note, (rect.x + pad, rect.y + pad + s(100)))

        weight_y = rect.y + pad + s(150)
        self._draw_numberbox(surf, self._human_weight_box, rect.x + pad, weight_y)
        note2 = font_sm.render(
            "How much more a human decision counts than an AI one of the same shape — "
            "per MSOMI's \"learn from humans first\" priority.", True, (*WHITE, 150))
        surf.blit(note2, (rect.x + pad, weight_y + s(44)))

        iter_y = weight_y + s(90)
        self._draw_numberbox(surf, self._iterations_box, rect.x + pad, iter_y)

    def _draw_numberbox(self, surf, box: 'NumberBox', x, y):
        cs = self._chrome_scale
        s = lambda px: round(px * cs)
        box.rect = pygame.Rect(x, y, s(260), s(44))
        box.minus_rect = pygame.Rect(x + s(264), y, s(34), s(44))
        box.plus_rect = pygame.Rect(x + s(302), y, s(34), s(44))
        box.draw(surf, self.assets.font_scaled('ui_normal', cs), self.assets.font_scaled('ui_small', cs))

    def _draw_results_tab(self, surf, rect):
        cs = self._chrome_scale
        s = lambda px: round(px * cs)
        font = self.assets.font_scaled('ui_normal', cs)
        font_sm = self.assets.font_scaled('ui_small', cs)
        pad = s(20)

        self._train_btn.rect.topleft = (rect.x + pad, rect.y + pad)
        self._train_btn.draw(surf)

        if self._trained_model:
            self._save_btn.rect.topleft = (
                rect.x + pad + self._train_btn.rect.width + s(20),
                rect.y + pad + s(4))
            self._save_btn.draw(surf)

        status_y = rect.y + pad + s(66)
        if self._status:
            st = font_sm.render(self._status, True, self._status_color)
            surf.blit(st, (rect.x + pad, status_y))
        if self._saved_path:
            sp = font_sm.render(f"Saved to: {self._saved_path}", True, (140, 220, 140))
            surf.blit(sp, (rect.x + pad, status_y + s(22)))

        if not self._trained_model:
            hint = font_sm.render(
                "Train a model to see its learned weights here.", True, (*WHITE, 150))
            surf.blit(hint, (rect.x + pad, status_y + s(50)))
            return

        t = self._trained_model['training']
        lines = [
            f"Decisions used: {t['num_decisions']} "
            f"({t['num_human_decisions']} human, {t['num_ai_decisions']} AI)",
            f"Training-set agreement: {t['train_agreement']*100:.1f}%"
            + (f"  (human-only: {t['train_agreement_human_only']*100:.1f}%)"
               if t['train_agreement_human_only'] is not None else ""),
            "Learned weights (higher = more this feature pushes toward being chosen):",
        ]
        y = status_y + s(50)
        for line in lines:
            surf.blit(font_sm.render(line, True, WHITE), (rect.x + pad, y))
            y += s(22)

        list_rect = pygame.Rect(rect.x + pad, y + s(6), rect.width - 2 * pad,
                                self.ROW_H * self.LIST_VISIBLE_ROWS)
        pygame.draw.rect(surf, (20, 22, 28), list_rect, border_radius=6)
        clip = surf.get_clip()
        surf.set_clip(list_rect)
        items = sorted(self._trained_model['weights'].items(), key=lambda kv: -abs(kv[1]))
        for i, (feat, w) in enumerate(items):
            ry = list_rect.y + i * self.ROW_H - self._results_scroll
            if ry + self.ROW_H < list_rect.y or ry > list_rect.bottom:
                continue
            label = _FEATURE_LABELS.get(feat, feat)
            col = (140, 220, 140) if w >= 0 else (220, 140, 140)
            txt = font_sm.render(f"{label}: {w:+.3f}", True, col)
            surf.blit(txt, (list_rect.x + s(12), ry + s(10)))
        surf.set_clip(clip)

    def _toggle_log(self, path):
        if path in self._selected_logs:
            self._selected_logs.discard(path)
        else:
            self._selected_logs.add(path)

    def _toggle_feature(self, feat):
        self._feature_selected[feat] = not self._feature_selected[feat]


# ─── Multiplayer submenu ────────────────────────────────────────────────────

class MultiplayerMenuScene(Scene):
    """Reached from the main menu's single "Multiplayer" button. Splits
    into Local Multiplayer (same machine, pass-and-play hot-seat — see
    GameplayScene's hot-seat handling and PassAndPlayOverlay), LAN
    Multiplayer, and Internet Multiplayer (play with anyone, anywhere,
    through a shared server — see server/README.md)."""

    HELP_SECTIONS = [
        ("Which mode do I want?", [
            "Local Multiplayer — everyone takes turns on this ONE device, "
            "passing it around. A privacy screen hides each player's hand "
            "before it's shown, so nobody peeks at an opponent's cards "
            "while the device is being handed over.",
            "LAN Multiplayer — for players on the same Wi-Fi/network (e.g. "
            "everyone in one house or office). One person's machine hosts "
            "the game; everyone else joins it from their own device.",
            "Internet Multiplayer — for players anywhere, on separate "
            "networks, connecting through a shared server rather than "
            "directly to each other.",
        ]),
        ("Connecting to Internet Multiplayer", [
            "KADI's official server address is kadigame.ddns.net — enter "
            "just that under Server Address (no port needed) to play "
            "with anyone else using KADI's official server, no matter "
            "where they are.",
            "If a friend or community runs their OWN private server "
            "instead, use whatever address they give you there rather "
            "than the official one above.",
        ]),
    ]

    def on_enter(self, **kwargs):
        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        # Top 3 buttons get a wider box than the standard 260 — "Internet
        # Multiplayer" already overflowed a 260px box and needed Button's
        # shrink-to-fit even before this pass (pre-existing, at every
        # resolution); that shrink is what was producing the soft/blurry
        # look. 360 comfortably fits the longest label without shrinking.
        w52, h52 = round(360 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        g1, g2, g3 = round(65 * cs), round(130 * cs), round(215 * cs)
        # Pull the whole stack up if the preferred position would push
        # "Back" (or on a small enough screen, "Internet Multiplayer")
        # past the bottom edge — see fit_stack_start_y().
        y = fit_stack_start_y(sh // 2 - round(145 * cs), g3 + h48, sh)
        self._buttons = [
            Button(pygame.Rect(cx - w52 // 2, y, w52, h52), "Local Multiplayer", font_lg,
                   color=(60, 110, 60), hover_color=(80, 145, 80),
                   on_click=lambda: self.manager.switch('mode_select', vs_ai=False)),
            Button(pygame.Rect(cx - w52 // 2, y + g1, w52, h52), "LAN Multiplayer", font_lg,
                   color=(60, 90, 130), hover_color=(80, 120, 165),
                   on_click=lambda: self.manager.switch('lan_menu')),
            Button(pygame.Rect(cx - w52 // 2, y + g2, w52, h52), "Internet Multiplayer", font_lg,
                   color=(90, 70, 130), hover_color=(120, 95, 165),
                   on_click=lambda: self.manager.switch('internet_menu')),
            Button(pygame.Rect(cx - w48 // 2, y + g3, w48, h48), "Back", font_md,
                   color=(80, 60, 120), hover_color=(110, 85, 160),
                   on_click=lambda: self.manager.switch('main_menu')),
        ]

        font_help_title = self.assets.font_scaled('ui_large', cs)
        font_help_head = self.assets.font_scaled('ui_medium', cs)
        font_help_body = self.assets.font_scaled('ui_normal', cs)
        self._help = HelpOverlay("Multiplayer — Which mode?", self.HELP_SECTIONS,
                                 font_help_title, font_help_head, font_help_body)
        self._help_btn = make_help_button(pygame.Rect(0, 0, 1, 1),
                                          self.assets.font_scaled('ui_small', cs),
                                          on_click=self._help.open)

    def _layout_help_btn(self, sw: int, sh: int):
        # Anchored immediately left of the sfx toggle — same anchoring
        # trick AudioControls itself uses off WindowControls (see that
        # class's _layout()) — so this stays lined up with the shared
        # top-right icon cluster at every resolution without this scene
        # needing to duplicate that cluster's own scaling math.
        ac = getattr(self.manager, 'audio_controls', None)
        cs = get_chrome_scale(sw, sh)
        sz = round(32 * cs)
        if ac is not None and ac._btn_sfx.rect.width > 0:
            x = ac._btn_sfx.rect.left - round(6 * cs) - sz
            y = ac._btn_sfx.rect.top
        else:
            x, y = sw - round(10 * cs) - sz, round(10 * cs)
        self._help_btn.rect = pygame.Rect(x, y, sz, sz)

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        self._help.notice_activity()
        if self._help.handle_event(event, sw, sh):
            return
        self._help_btn.handle_event(event)
        for b in self._buttons:
            b.handle_event(event)

    def update(self, dt):
        sw, sh = self.gm.resolution
        self._layout_help_btn(sw, sh)
        self._help.update_idle_glow(dt)
        mp = pygame.mouse.get_pos()
        self._help_btn.update(dt, mp)
        for b in self._buttons:
            b.update(dt, mp)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        title = self.assets.font_scaled('ui_large', cs).render("Multiplayer", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, round(90 * cs) + self._ad_top_pad()))
        for b in self._buttons:
            b.draw(surf)
        self._help.draw_button_glow(surf, self._help_btn.rect)
        self._help_btn.draw(surf)
        self._help.draw(surf)


# ─── LAN Multiplayer ────────────────────────────────────────────────────────
# Server-authoritative LAN play: one machine (the host) runs a real
# GameManager + RuleEngine — the exact same classes single-player uses,
# completely unmodified — and every other player is a thin client whose
# moves are sent as "intentions" over TCP, validated, and applied by the
# host. See network/README.md for the full design writeup and known
# limitations (undo, pause, and drag-reordering are host/local-only).

class LANMenuScene(Scene):
    """Simple Host / Join / Back chooser — the entry point for LAN play."""
    def on_enter(self, **kwargs):
        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        w52, h52 = round(260 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        g1, g2 = round(65 * cs), round(150 * cs)
        # Pull the whole stack up if the preferred position would push
        # "Back" past the bottom edge — see fit_stack_start_y().
        y = fit_stack_start_y(sh // 2 - round(90 * cs), g2 + h48, sh)
        self._buttons = [
            Button(pygame.Rect(cx - w52 // 2, y, w52, h52), "Host a Game", font_lg,
                   color=(60, 90, 130), hover_color=(80, 120, 165),
                   on_click=lambda: self.manager.switch('lan_host_lobby')),
            Button(pygame.Rect(cx - w52 // 2, y + g1, w52, h52), "Join a Game", font_lg,
                   color=(60, 110, 60), hover_color=(80, 145, 80),
                   on_click=lambda: self.manager.switch('lan_join')),
            Button(pygame.Rect(cx - w48 // 2, y + g2, w48, h48), "Back", font_md,
                   color=(80, 60, 120), hover_color=(110, 85, 160),
                   on_click=lambda: self.manager.switch('multiplayer_menu')),
        ]

    def handle_event(self, event):
        for b in self._buttons:
            b.handle_event(event)

    def update(self, dt):
        mp = pygame.mouse.get_pos()
        for b in self._buttons:
            b.update(dt, mp)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        title = self.assets.font_scaled('ui_large', cs).render("LAN Multiplayer", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, round(90 * cs) + self._ad_top_pad()))
        sub = self.assets.font_scaled('ui_normal', cs).render(
            "Play with others on the same local network / WiFi", True, (*WHITE, 160))
        surf.blit(sub, (cx - sub.get_width() // 2, round(140 * cs) + self._ad_top_pad()))
        for b in self._buttons:
            b.draw(surf)


def _build_settings_summary(gm) -> List[Tuple[str, str]]:
    """Read-only summary of the host's current game settings, shown on
    both LANHostLobbyScene (so the host can double check) and
    LANJoinScene's waiting room (so joining players know what they're
    getting into before the game starts). Thin wrapper: the actual
    row-building logic now lives in network/settings_summary.py (no
    pygame dependency) so server/game_room.py can reuse the identical
    logic for Internet Multiplayer's lobby — this function's own
    behavior/output is unchanged, only its location moved."""
    return settings_summary.build_settings_summary(gm)


def _truncate_to_width(text: str, font, max_width: int) -> str:
    """Shortens `text` with a trailing '…' so it renders within
    max_width, leaving it untouched if it already fits. Used by
    _draw_settings_panel below so a long value (e.g. an MSOMI model's
    filename, which can run 30+ characters with its timestamp) can
    never visually collide with its row's label."""
    if font.size(text)[0] <= max_width:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.size(text[:mid] + ell)[0] <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo > 0 else ell


def _draw_settings_panel(surf, rect: pygame.Rect, rows: List[Tuple[str, str]],
                         font_title, font_row, scroll_offset: float,
                         title: str = "Game Settings") -> int:
    """Scrollable read-only settings list — shared by the host lobby and
    the join waiting-room so both render it identically. Returns the
    max scroll value (0 if everything already fits) so callers can
    clamp their own scroll_offset against it."""
    pygame.draw.rect(surf, (20, 34, 46), rect, border_radius=8)
    pygame.draw.rect(surf, (*WHITE, 60), rect, width=2, border_radius=8)

    title_surf = font_title.render(title, True, GOLD_LIGHT)
    surf.blit(title_surf, (rect.x + 16, rect.y + 12))

    # list_rect's top is derived from the title's own actual rendered
    # height rather than a fixed 46px — that fixed gap didn't account
    # for font_title coming in pre-scaled at higher resolutions (68px
    # tall at 3840x2160 vs the 46px gap reserved for it), so the title
    # was overlapping the first row of the list beneath it.
    list_top = rect.y + 12 + title_surf.get_height() + 8
    list_rect = pygame.Rect(rect.x + 10, list_top, rect.width - 20,
                            rect.bottom - list_top - 10)
    # Derived from font_row's own actual rendered height (whatever
    # scale the caller built it at) rather than a fixed 30px — that
    # fixed value was tuned for the original unscaled font; once
    # font_row started coming in pre-scaled via font_scaled() at
    # higher resolutions, its real height could exceed 30px, making
    # consecutive rows overlap each other (confirmed via a real
    # screenshot: every row in the Game Settings panel overlapping the
    # next at 3840x2160, all the way down the list).
    row_h = font_row.get_height() + 10
    content_h = len(rows) * row_h
    max_scroll = max(0, content_h - list_rect.height)

    prev_clip = surf.get_clip()
    surf.set_clip(list_rect)
    for i, (label, value) in enumerate(rows):
        ry = list_rect.y + i * row_h - int(scroll_offset)
        if ry + row_h < list_rect.y or ry > list_rect.bottom:
            continue
        lbl = font_row.render(_truncate_to_width(label, font_row, int(list_rect.width * 0.52)),
                              True, (*WHITE, 210))
        val = font_row.render(_truncate_to_width(value, font_row,
                                                  list_rect.width - int(list_rect.width * 0.52) - 16),
                              True, GOLD_LIGHT)
        surf.blit(lbl, (list_rect.x + 6, ry + 4))
        surf.blit(val, (list_rect.right - val.get_width() - 10, ry + 4))
    surf.set_clip(prev_clip)

    if max_scroll > 0:
        track = pygame.Rect(rect.right - 8, list_rect.y, 5, list_rect.height)
        pygame.draw.rect(surf, (*WHITE, 40), track, border_radius=3)
        thumb_h = max(24, int(list_rect.height * (list_rect.height / content_h)))
        thumb_y = track.y + int((list_rect.height - thumb_h) * (scroll_offset / max_scroll))
        pygame.draw.rect(surf, (*WHITE, 140),
                         pygame.Rect(track.x, thumb_y, track.width, thumb_h), border_radius=3)
    return max_scroll


class MSOMIPickerWidget:
    """Reusable "attach a trained MSOMI model" control: a toggle
    (on/off, only enabled once a model is attached) plus an attach
    button that opens a scrollable modal listing trained models and a
    Browse-for-file option. Mirrors ModeSelectScene's own MSOMI UI
    (same modal layout/colors, same core.msomi_trainer calls) so both
    screens behave identically — kept as its OWN self-contained widget
    rather than refactoring ModeSelectScene to share it, so this
    addition carries zero risk to the already-shipped, well-tested
    single-player MSOMI flow.
    """
    def __init__(self, toggle_rect: pygame.Rect, attach_rect: pygame.Rect):
        self.toggle_rect = toggle_rect
        self.attach_rect = attach_rect
        self.enabled = False
        self.model_name: Optional[str] = None
        self.picker_open = False
        self.available_models = msomi_trainer.list_models()
        self.modal_scroll = 0
        self.status = ""
        self.browse_rect = pygame.Rect(0, 0, 1, 1)
        self.cancel_rect = pygame.Rect(0, 0, 1, 1)

    def _modal_rect(self, sw: int, sh: int) -> pygame.Rect:
        w, h = 520, min(480, sh - 100)
        return pygame.Rect(sw // 2 - w // 2, sh // 2 - h // 2, w, h)

    def _modal_row_rect(self, i: int, sw: int, sh: int) -> pygame.Rect:
        modal = self._modal_rect(sw, sh)
        list_top = modal.y + 96
        return pygame.Rect(modal.x + 20, list_top + i * 38 - self.modal_scroll,
                           modal.width - 40, 34)

    def _modal_list_area(self, sw: int, sh: int) -> pygame.Rect:
        modal = self._modal_rect(sw, sh)
        list_top = modal.y + 96
        list_bottom = modal.bottom - 96
        return pygame.Rect(modal.x + 20, list_top, modal.width - 40, list_bottom - list_top)

    def browse_for_model(self):
        if not native_dialog.is_available():
            self.status = "File browsing isn't available on this system."
            return
        path = native_dialog.ask_open_file(
            title="Attach an MSOMI model",
            filetypes=[("MSOMI model", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            model = msomi_trainer.load_model(path)
            problem = msomi_trainer.validate_model(model)
        except Exception as e:
            self.status = f"Couldn't read that file: {e}"
            return
        if problem:
            self.status = problem
            return
        self.model_name = path
        self.enabled = True
        self.picker_open = False
        self.status = ""

    def pick_model(self, name: str):
        self.model_name = name
        self.enabled = True
        self.picker_open = False
        self.status = ""

    def handle_event(self, event, sw: int, sh: int, active: bool = True):
        """`active` gates the toggle/attach buttons only (e.g. the LAN
        lobby only wants this to matter while AI Players > 0) — the
        modal, once open, always stays fully interactive so a person
        can still close it even if `active` flips false underneath it."""
        if event.type == pygame.MOUSEWHEEL and self.picker_open:
            list_area = self._modal_list_area(sw, sh)
            max_scroll = max(0, len(self.available_models) * 38 - list_area.height)
            self.modal_scroll = max(0, min(max_scroll, self.modal_scroll - event.y * 38))
            return
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return
        if self.picker_open:
            if self.browse_rect.collidepoint(event.pos):
                self.browse_for_model()
                return
            if self.cancel_rect.collidepoint(event.pos):
                self.picker_open = False
                return
            list_area = self._modal_list_area(sw, sh)
            if list_area.collidepoint(event.pos):
                for i, name in enumerate(self.available_models):
                    row = self._modal_row_rect(i, sw, sh)
                    if row.collidepoint(event.pos):
                        self.pick_model(name)
                        return
                return
            if not self._modal_rect(sw, sh).collidepoint(event.pos):
                self.picker_open = False  # clicked outside the modal — dismiss
            return
        if not active:
            return
        if self.toggle_rect.collidepoint(event.pos):
            if self.model_name:
                self.enabled = not self.enabled
        if self.attach_rect.collidepoint(event.pos):
            self.available_models = msomi_trainer.list_models()
            self.modal_scroll = 0
            self.status = ""
            self.picker_open = True

    def draw_controls(self, surf, font_sm, active: bool = True):
        can_enable = self.model_name is not None and active
        on = self.enabled and can_enable
        t_col = (60, 140, 60) if on else ((60, 60, 80) if active else (35, 35, 45))
        pygame.draw.rect(surf, t_col, self.toggle_rect, border_radius=8)
        if on:
            pygame.draw.rect(surf, GOLD_LIGHT, self.toggle_rect, width=2, border_radius=8)
        ts_col = WHITE if active else (*WHITE, 90)
        ts = font_sm.render("ON" if on else "OFF", True, ts_col)
        surf.blit(ts, (self.toggle_rect.centerx - ts.get_width() // 2,
                       self.toggle_rect.centery - ts.get_height() // 2))

        a_col = (60, 60, 80) if active else (35, 35, 45)
        pygame.draw.rect(surf, a_col, self.attach_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 100 if active else 40), self.attach_rect,
                         width=2, border_radius=8)
        attach_label = (os.path.basename(self.model_name) if self.model_name
                        else "Attach model...")
        # Long model filenames used to render past both edges of the
        # button since the text was only centered, never clamped —
        # truncate with an ellipsis so it always stays inside.
        attach_label = _truncate_to_width(attach_label, font_sm, self.attach_rect.width - 16)
        as_ = font_sm.render(attach_label, True, WHITE if active else (*WHITE, 90))
        surf.blit(as_, (self.attach_rect.centerx - as_.get_width() // 2,
                       self.attach_rect.centery - as_.get_height() // 2))

    def draw_modal(self, surf, sw: int, sh: int, font_md, font_sm, font_tiny):
        """Drawn LAST by the caller, after everything else in the
        scene, so it's always visibly on top rather than hidden behind
        whatever gets drawn after it."""
        if not self.picker_open:
            return
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(dim, (0, 0))

        modal = self._modal_rect(sw, sh)
        Panel(modal, color=(32, 34, 46)).draw(surf)

        title = font_md.render("Attach MSOMI Model", True, GOLD_LIGHT)
        surf.blit(title, (modal.centerx - title.get_width() // 2, modal.y + 16))
        sub = font_sm.render("From this device's saved models, or browse anywhere:",
                             True, (*WHITE, 170))
        surf.blit(sub, (modal.x + 20, modal.y + 52))

        list_area = self._modal_list_area(sw, sh)
        pygame.draw.rect(surf, (20, 22, 30), list_area, border_radius=6)
        clip = surf.get_clip()
        surf.set_clip(list_area)
        if not self.available_models:
            es = font_sm.render("No saved models yet — train one in Chuo, or Browse below.",
                                True, (*WHITE, 160))
            surf.blit(es, (list_area.x + 12, list_area.y + 12))
        for i, name in enumerate(self.available_models):
            row = self._modal_row_rect(i, sw, sh)
            if row.bottom < list_area.y or row.y > list_area.bottom:
                continue
            hovered = row.collidepoint(pygame.mouse.get_pos())
            is_current = (name == self.model_name)
            color = (85, 65, 130) if is_current else ((60, 60, 80) if hovered else (45, 45, 60))
            pygame.draw.rect(surf, color, row, border_radius=6)
            ns = font_sm.render(name, True, WHITE)
            surf.blit(ns, (row.x + 10, row.centery - ns.get_height() // 2))
        surf.set_clip(clip)

        self.browse_rect = pygame.Rect(modal.x + 20, list_area.bottom + 14, 230, 40)
        self.cancel_rect = pygame.Rect(modal.right - 150, list_area.bottom + 14, 130, 40)
        pygame.draw.rect(surf, (50, 90, 130), self.browse_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 150), self.browse_rect, width=2, border_radius=8)
        bs = font_sm.render("Browse for file...", True, WHITE)
        surf.blit(bs, (self.browse_rect.centerx - bs.get_width() // 2,
                       self.browse_rect.centery - bs.get_height() // 2))

        pygame.draw.rect(surf, (70, 70, 80), self.cancel_rect, border_radius=8)
        pygame.draw.rect(surf, (*WHITE, 120), self.cancel_rect, width=2, border_radius=8)
        cs = font_sm.render("Cancel", True, WHITE)
        surf.blit(cs, (self.cancel_rect.centerx - cs.get_width() // 2,
                       self.cancel_rect.centery - cs.get_height() // 2))

        if self.status:
            st = font_tiny.render(self.status, True, (240, 140, 100))
            surf.blit(st, (modal.x + 20, self.browse_rect.bottom + 8))


def _draw_text_field(surf, font_label, font_value, label, rect, value, active, t,
                     placeholder: str = ""):
    """Small shared helper for the name/IP text fields below — copies
    the exact look-and-feel ModeSelectScene already established for its
    own "Your Name" field, so LAN screens don't introduce a visually
    different text-entry style. When `value` is empty and a
    `placeholder` is given, it's shown dimmed in its place (standard
    "greyed-out example text" pattern) instead of leaving the field
    looking blank/broken."""
    lbl = font_label.render(label, True, WHITE)
    # Offset derived from font_label's own actual height (whatever
    # scale the caller built it at) rather than a fixed 26px — that
    # fixed value was tuned for the ORIGINAL unscaled font size; once
    # font_label started coming in pre-scaled via font_scaled() at
    # higher resolutions, its rendered height could exceed 26px,
    # making the label's own top edge dip down INTO the box it's
    # labeling (confirmed via a real screenshot: "Player 2 Name:" /
    # "Player 3 Name:" / "Player 4 Name:" all overlapping their own
    # text fields at 3840x2160). This is a shared helper (LAN/Internet
    # lobbies and ModeSelectScene all use it), so every caller that
    # reserves vertical space above a field for its label already
    # budgets comfortably more than one label's height — this fix
    # fits well within that existing margin, not just at this field.
    surf.blit(lbl, (rect.x, rect.y - lbl.get_height() - 6))
    bc = GOLD_LIGHT if active else (*WHITE, 120)
    pygame.draw.rect(surf, (30, 60, 40), rect, border_radius=6)
    pygame.draw.rect(surf, bc, rect, width=2, border_radius=6)
    # Clipped to the field's own interior — neither a long placeholder
    # hint (e.g. "Type a name your friend gave you...") nor a long
    # typed value can spill past the box's own border into whatever
    # sits next to it (confirmed via a real screenshot: both this
    # field's placeholder and the "Game Name" field's placeholder
    # overflowing their boxes at every resolution checked, not just a
    # high-DPI case). Text that doesn't fit is invisibly clipped rather
    # than spilling out — same tradeoff any real text-input widget
    # makes long before it needs a scrolling caret.
    inner = rect.inflate(-16, -4)
    prev_clip = surf.get_clip()
    surf.set_clip(inner)
    if value:
        vs = font_value.render(value, True, WHITE)
        surf.blit(vs, (rect.x + 10, rect.y + 8))
        text_w = vs.get_width()
    elif placeholder:
        ps = font_value.render(placeholder, True, (*WHITE, 90))
        surf.blit(ps, (rect.x + 10, rect.y + 8))
        text_w = 0
    else:
        text_w = 0
    surf.set_clip(prev_clip)
    if active and int(t * 2) % 2 == 0:
        cxx = rect.x + 10 + text_w + 2
        pygame.draw.line(surf, WHITE, (cxx, rect.y + 8), (cxx, rect.y + rect.height - 7), 2)


class LANHostLobbyScene(Scene):
    AI_NAMES = ["Kadi-Bot", "Smart AI", "Trickster", "Blitz", "Shadow", "Rogue"]

    def on_enter(self, **kwargs):
        self._player_name = "Host"
        self._name_active = False
        self._elimination_mode = False
        self._t = 0.0
        self._error = ""
        self._host: Optional[HostGame] = None
        self._starting = False
        self._settings_scroll = 0.0
        # AI-fill is entirely optional and host-controlled: defaults to
        # 0 (off) — nothing is added unless the host explicitly asks for
        # it. Bounded live, every frame, by however many human seats are
        # currently taken, so total players never exceeds MAX_PLAYERS
        # (the same limit single-player uses) no matter when someone
        # else joins or leaves the lobby.
        self._ai_count = 0
        self._ai_difficulty = AIDifficulty.MEDIUM

        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        self._lobby_scale = cs
        # Every top-anchored Y position in this method adds ad_pad —
        # this scene is ad-eligible (see AD_ELIGIBLE_SCENES) and its
        # title (drawn at s(50) in draw()) didn't clear the ad banner's
        # reserved height at ANY resolution before this, not just at
        # scaled-up ones (confirmed: even 1024x640 needed 56px and
        # only had 50). Bottom-anchored elements (Start/Back, computed
        # from sh - ...) are untouched — the banner only ever affects
        # the top of the screen.
        ad_pad = self._ad_top_pad()
        self._name_rect = pygame.Rect(cx - s(150), s(130) + ad_pad, s(300), s(45))
        self._elim_toggle_rect = pygame.Rect(cx - s(150), s(210) + ad_pad, s(300), s(40))
        # The "AI Players to add: N" label is drawn 24px above this
        # stepper (see draw()) — it must start below the Elimination
        # Mode button's bottom edge (210+40=250) or the two overlap.
        # Shifted down (+28 vs the old 262) to clear that, and every
        # row below is shifted by the same amount to preserve spacing.
        # (All these offsets now scale together via s() — since every
        # one of them moves by the same factor, the relative gaps that
        # were hand-fixed here for 1024x640 stay exactly as fixed.)
        self._ai_minus_rect = pygame.Rect(cx - s(150), s(290) + ad_pad, s(40), s(40))
        self._ai_plus_rect = pygame.Rect(cx + s(110), s(290) + ad_pad, s(40), s(40))
        self._diff_buttons = []
        for i, (d, lbl) in enumerate([(AIDifficulty.EASY, "Easy"),
                                      (AIDifficulty.MEDIUM, "Medium"),
                                      (AIDifficulty.HARD, "Hard")]):
            r = pygame.Rect(cx - s(150) + i * s(102), s(342) + ad_pad, s(96), s(34))
            self._diff_buttons.append((d, lbl, r))
        # Attaching a trained MSOMI model to the AI-fill seats works the
        # same way ModeSelectScene already lets single-player do it —
        # same widget class, same core.msomi_trainer calls underneath.
        # Only meaningful while AI Players > 0 (see `active=` below).
        msomi_toggle_rect = pygame.Rect(cx - s(180), s(386) + ad_pad, s(170), s(38))
        msomi_attach_rect = pygame.Rect(cx - s(4), s(386) + ad_pad, s(184), s(38))
        self._msomi = MSOMIPickerWidget(msomi_toggle_rect, msomi_attach_rect)
        # Settings summary panel — placed to the side of the name/roster
        # column, and made scrollable rather than fixed-height, since the
        # number of rows can grow if more settings get surfaced here later.
        # Width is measured from the widest top-row control's actual right
        # edge — msomi_attach_rect, which reaches cx+180 (wider than the
        # difficulty buttons' cx+150 or Start/Back's cx+130) — not an
        # approximate "- 170" offset from center. That approximation left
        # an overlap with msomi_attach_rect at 1024x640 specifically (fine
        # at 1280+, where there's more slack).
        panel_w = min(s(340), sw - s(60) - (cx + s(180)) - s(20), sw // 3)
        self._settings_panel_rect = pygame.Rect(sw - panel_w - s(60), s(220) + ad_pad, panel_w,
                                                 sh - s(320) - ad_pad)

        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        w52, h52 = round(260 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        self._start_btn = Button(pygame.Rect(cx - w52 // 2, sh - round(140 * cs), w52, h52), "Start Game",
                                 font_lg, on_click=self._start_game)
        self._back_btn = Button(pygame.Rect(cx - w48 // 2, sh - round(76 * cs), w48, h48), "Back", font_md,
                                color=(80, 60, 120), hover_color=(110, 85, 160),
                                on_click=self._go_back)

        try:
            self._host = HostGame(gm=self.gm)
            self._host.start_listening(host_name=self._player_name)
        except OSError as e:
            self._error = f"Couldn't start hosting: {e}"

    def on_exit(self):
        # Only reached if the person navigates away without starting the
        # game (Back, or the window Close/ESC path) — once Start Game is
        # clicked, ownership of self._host moves to GameplayScene, whose
        # own on_exit() is what stops it from then on.
        if self._host is not None and not self._starting:
            self._host.stop()

    def _go_back(self):
        self.manager.switch('main_menu')

    def _max_ai_slots(self) -> int:
        n_humans = len(self._host.roster()) if self._host else 1
        return max(0, MAX_PLAYERS - n_humans)

    def _build_ai_configs(self) -> List[dict]:
        model_name = self._msomi.model_name if self._msomi.enabled else None
        return [{'name': self.AI_NAMES[i % len(self.AI_NAMES)], 'is_human': False,
                'difficulty': self._ai_difficulty, 'msomi_model_name': model_name}
               for i in range(self._ai_count)]

    def _start_game(self):
        if self._host is None or self._starting or self._error:
            return
        n_humans = len(self._host.roster())
        if n_humans + self._ai_count < MIN_PLAYERS:
            return
        self._starting = True
        self._host.start_game(elimination_mode=self._elimination_mode,
                              extra_ai_configs=self._build_ai_configs())
        self.manager.switch('gameplay', network_role='host', host_game=self._host)

    def handle_event(self, event):
        sw, sh = self.gm.resolution
        # The MSOMI picker's own modal (if open) takes priority over
        # everything else underneath it — same rule ModeSelectScene uses.
        self._msomi.handle_event(event, sw, sh, active=self._ai_count > 0)
        if self._msomi.picker_open:
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._name_active = self._name_rect.collidepoint(event.pos)
            if self._elim_toggle_rect.collidepoint(event.pos):
                self._elimination_mode = not self._elimination_mode
            if self._ai_minus_rect.collidepoint(event.pos):
                self._ai_count = max(0, self._ai_count - 1)
            if self._ai_plus_rect.collidepoint(event.pos):
                self._ai_count = min(self._max_ai_slots(), self._ai_count + 1)
            for d, lbl, r in self._diff_buttons:
                if r.collidepoint(event.pos):
                    self._ai_difficulty = d
        if event.type == pygame.KEYDOWN and self._name_active:
            if event.key == pygame.K_BACKSPACE:
                self._player_name = self._player_name[:-1]
            elif event.key == pygame.K_RETURN:
                self._name_active = False
            elif len(self._player_name) < 16 and event.unicode.isprintable():
                self._player_name += event.unicode
            if self._host is not None:
                # Host's own display name can change any time before Start
                # — directly updating the roster dict entry is enough,
                # since poll_lobby()/roster() just reads it back out.
                self._host.player_names[0] = self._player_name or "Host"
        if event.type == pygame.MOUSEWHEEL and self._settings_panel_rect.collidepoint(
                pygame.mouse.get_pos()):
            rows = self._settings_rows()
            max_scroll = max(0, len(rows) * 30 - (self._settings_panel_rect.height - 56))
            self._settings_scroll = max(0, min(max_scroll, self._settings_scroll - event.y * 30))
        self._start_btn.handle_event(event)
        self._back_btn.handle_event(event)

    def _settings_rows(self) -> List[Tuple[str, str]]:
        rows = _build_settings_summary(self.gm)
        rows.append(("AI Players", f"{self._ai_count} ({self._ai_difficulty.name.title()})"
                     if self._ai_count else "None"))
        if self._ai_count and self._msomi.enabled and self._msomi.model_name:
            rows.append(("  MSOMI Model", os.path.basename(self._msomi.model_name)))
        return rows

    def update(self, dt):
        self._t += dt
        if self._host is not None and not self._starting:
            self._host.poll_lobby()
            # Someone else joining after the host picked an AI count can
            # push total players over MAX_PLAYERS — clamp down live
            # rather than only checking at Start time, so the displayed
            # count is never a value Start would actually reject.
            self._ai_count = min(self._ai_count, self._max_ai_slots())
            # Broadcast the FULL settings summary (incl. AI seats +
            # MSOMI), not just Elimination Mode, so a joining player's
            # waiting-room screen shows exactly what this screen shows —
            # built from the one shared function so the two can't disagree.
            self._host.broadcast_lobby({'rows': self._settings_rows()})
        mp = pygame.mouse.get_pos()
        roster = self._host.roster() if self._host else []
        self._start_btn.enabled = (len(roster) + self._ai_count >= MIN_PLAYERS
                                   and not self._error)
        self._start_btn.update(dt, mp)
        self._back_btn.update(dt, mp)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)
        font_tiny = self.assets.font_scaled('ui_tiny', cs)

        title = font_lg.render("Host LAN Game", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, s(50) + self._ad_top_pad()))

        if self._error:
            err = font_md.render(self._error, True, (220, 80, 80))
            surf.blit(err, (cx - err.get_width() // 2, s(130) + self._ad_top_pad()))
            self._back_btn.draw(surf)
            return

        _draw_text_field(surf, font_sm, font_md, "Your Name:", self._name_rect,
                         self._player_name, self._name_active, self._t)

        ec = (60, 140, 60) if self._elimination_mode else (60, 60, 80)
        pygame.draw.rect(surf, ec, self._elim_toggle_rect, border_radius=8)
        elabel = "Elimination Mode: ON" if self._elimination_mode else "Elimination Mode: OFF"
        et = font_sm.render(elabel, True, WHITE)
        surf.blit(et, (self._elim_toggle_rect.centerx - et.get_width() // 2,
                       self._elim_toggle_rect.centery - et.get_height() // 2))

        # AI-fill stepper — entirely optional (0 by default): lets the
        # host add computer players to fill empty seats, e.g. to start
        # solo or with just one other friend instead of waiting for a
        # full table. Bounded live to MAX_PLAYERS total.
        max_ai = self._max_ai_slots()
        minus_on = self._ai_count > 0
        plus_on = self._ai_count < max_ai
        pygame.draw.rect(surf, (60, 60, 80) if minus_on else (35, 35, 45),
                         self._ai_minus_rect, border_radius=6)
        pygame.draw.rect(surf, (60, 60, 80) if plus_on else (35, 35, 45),
                         self._ai_plus_rect, border_radius=6)
        minus_t = font_md.render("-", True, WHITE if minus_on else (*WHITE, 90))
        plus_t = font_md.render("+", True, WHITE if plus_on else (*WHITE, 90))
        surf.blit(minus_t, (self._ai_minus_rect.centerx - minus_t.get_width() // 2,
                            self._ai_minus_rect.centery - minus_t.get_height() // 2))
        surf.blit(plus_t, (self._ai_plus_rect.centerx - plus_t.get_width() // 2,
                           self._ai_plus_rect.centery - plus_t.get_height() // 2))
        ai_label = font_sm.render(f"AI Players to add: {self._ai_count}", True, WHITE)
        surf.blit(ai_label, (cx - ai_label.get_width() // 2, self._ai_minus_rect.y - s(24)))

        for d, lbl, r in self._diff_buttons:
            active = (d == self._ai_difficulty)
            enabled = self._ai_count > 0
            col = (90, 70, 20) if active and enabled else ((45, 45, 55) if enabled else (30, 30, 36))
            pygame.draw.rect(surf, col, r, border_radius=6)
            if active and enabled:
                pygame.draw.rect(surf, GOLD_LIGHT, r, width=2, border_radius=6)
            txt_col = WHITE if enabled else (*WHITE, 90)
            t = font_sm.render(lbl, True, txt_col)
            surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))

        msomi_lbl = font_sm.render("MSOMI:", True, WHITE if self._ai_count else (*WHITE, 100))
        surf.blit(msomi_lbl, (self._msomi.toggle_rect.x, self._msomi.toggle_rect.y - s(22)))
        self._msomi.draw_controls(surf, font_sm, active=self._ai_count > 0)

        caption = font_tiny.render(
            "Optional — fills empty seats with AI so you can start solo or with a few friends",
            True, (*WHITE, 160))
        surf.blit(caption, (cx - caption.get_width() // 2, s(430) + self._ad_top_pad()))

        rows = self._settings_rows()
        max_scroll = _draw_settings_panel(surf, self._settings_panel_rect, rows,
                                          font_md, font_sm, self._settings_scroll)
        self._settings_scroll = max(0, min(max_scroll, self._settings_scroll))

        ip_str = f"{self._host.local_ip()}:{self._host.port}" if self._host else "?"
        ip_lbl = font_md.render("Others on your network join at:", True, WHITE)
        surf.blit(ip_lbl, (cx - ip_lbl.get_width() // 2, s(462) + self._ad_top_pad()))
        ip_val = font_lg.render(ip_str, True, GOLD_LIGHT)
        surf.blit(ip_val, (cx - ip_val.get_width() // 2, s(490) + self._ad_top_pad()))

        roster = self._host.roster() if self._host else []
        rl = font_sm.render(f"Players ({len(roster)}):", True, WHITE)
        surf.blit(rl, (cx - s(150), s(550) + self._ad_top_pad()))
        shown = roster[:4]
        for i, entry in enumerate(shown):
            tag = " (you, host)" if entry['player_id'] == 0 else ""
            row = font_sm.render(f"  \u2022 {entry['name']}{tag}", True, (*WHITE, 220))
            surf.blit(row, (cx - s(150), s(578) + self._ad_top_pad() + i * s(24)))
        if len(roster) > len(shown):
            more = font_sm.render(f"  ...and {len(roster) - len(shown)} more",
                                  True, (*WHITE, 160))
            surf.blit(more, (cx - s(150), s(578) + self._ad_top_pad() + len(shown) * s(24)))

        if len(roster) + self._ai_count < MIN_PLAYERS:
            hint = font_sm.render(
                "Need at least 2 players total — invite someone or add AI players above.",
                True, (200, 180, 80))
            surf.blit(hint, (cx - hint.get_width() // 2, sh - s(200)))

        self._start_btn.draw(surf)
        self._back_btn.draw(surf)

        # Drawn LAST so it's always visibly on top of everything above,
        # including the buttons — same rule ModeSelectScene follows.
        self._msomi.draw_modal(surf, sw, sh, font_md, font_sm, font_tiny)



class LANJoinScene(Scene):
    def on_enter(self, **kwargs):
        self._player_name = "Player"
        self._ip_text = ""
        self._name_active = False
        self._ip_active = True
        self._t = 0.0
        self._state = 'entry'   # entry -> connecting -> lobby -> starting
        self._error = ""
        self._client: Optional[LANClient] = None
        self._connect_error: Optional[str] = None
        self._lobby_roster: List[dict] = []
        self._settings_rows: List[Tuple[str, str]] = []
        self._settings_scroll = 0.0
        self._client_gm: Optional[ClientGameManager] = None
        self._reconnect_token: Optional[str] = None
        self._connect_ip: Optional[str] = None
        self._connect_port: Optional[int] = None
        self._connect_name: Optional[str] = None
        # Version-check notice (see network/host_game.py's 'welcome'
        # reply and constants.VERSION) — informational only, never
        # blocks anything. None means either no mismatch, or we haven't
        # heard back yet.
        self._version_notice: Optional[str] = None

        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        self._join_scale = cs
        # ad_pad: this scene is ad-eligible (see AD_ELIGIBLE_SCENES) and
        # every one of its top-anchored elements below didn't clear the
        # ad banner's reserved height at any resolution before this —
        # see Scene._ad_top_pad()'s own docstring for the full story.
        # The Back button is untouched since it's anchored to sh (the
        # bottom of the screen), which the banner never affects.
        ad_pad = self._ad_top_pad()
        self._name_rect = pygame.Rect(cx - s(150), s(130) + ad_pad, s(300), s(45))
        self._ip_rect   = pygame.Rect(cx - s(150), s(210) + ad_pad, s(300), s(45))
        # Width measured from the name/ip fields' actual right edge
        # (cx + 150 — wider than the Connect button's cx + 130), not an
        # approximate "- 170" offset from center — that approximation
        # overlapped those fields by 38px at 1024x640 specifically (fine
        # at 1280+, where there's more slack). (Scaled together via s()
        # now, so that fixed relationship holds at every resolution.)
        panel_w = min(s(340), sw - s(60) - (cx + s(150)) - s(20), sw // 3)
        self._settings_panel_rect = pygame.Rect(sw - panel_w - s(60), s(190) + ad_pad, panel_w,
                                                 sh - s(290) - ad_pad)

        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        w52, h52 = round(260 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        self._connect_btn = Button(pygame.Rect(cx - w52 // 2, s(296) + ad_pad, w52, h52), "Connect", font_lg,
                                   on_click=self._start_connect)
        self._back_btn = Button(pygame.Rect(cx - w48 // 2, sh - round(76 * cs), w48, h48), "Back", font_md,
                                color=(80, 60, 120), hover_color=(110, 85, 160),
                                on_click=self._go_back)

    def on_exit(self):
        if self._client is not None and self._state != 'starting':
            self._client.close()

    def _go_back(self):
        self.manager.switch('main_menu')

    def _start_connect(self):
        if self._state != 'entry' or not self._ip_text.strip():
            return
        self._state = 'connecting'
        self._error = ""
        self._connect_error = None
        self._client = LANClient()
        # Accept either a bare IP ("192.168.1.42") or the full
        # "IP:PORT" string the Host lobby screen itself displays
        # (LANHostLobbyScene shows "192.168.1.42:51999") — so a player
        # can just copy-paste exactly what the host reads out, without
        # needing to know to strip the port off first.
        raw = self._ip_text.strip()
        if ':' in raw:
            ip, _, port_str = raw.rpartition(':')
            try:
                port = int(port_str)
            except ValueError:
                ip, port = raw, DEFAULT_PORT
        else:
            ip, port = raw, DEFAULT_PORT
        name = self._player_name.strip() or "Player"
        self._connect_ip, self._connect_port, self._connect_name = ip, port, name

        def worker():
            try:
                self._client.connect(ip, port, name)
            except ConnectError as e:
                self._connect_error = str(e)
        # Run the (up-to-5s-timeout) blocking connect off the main
        # thread so a slow/unreachable host can't freeze the pygame
        # loop — see network/client.py's connect() docstring.
        threading.Thread(target=worker, daemon=True).start()

    def handle_event(self, event):
        if self._state != 'entry':
            if event.type == pygame.MOUSEWHEEL and self._settings_panel_rect.collidepoint(
                    pygame.mouse.get_pos()):
                max_scroll = max(0, len(self._settings_rows) * 30
                                 - (self._settings_panel_rect.height - 56))
                self._settings_scroll = max(0, min(max_scroll,
                                                   self._settings_scroll - event.y * 30))
            self._back_btn.handle_event(event)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._name_active = self._name_rect.collidepoint(event.pos)
            self._ip_active = self._ip_rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN:
            if self._name_active:
                if event.key == pygame.K_BACKSPACE:
                    self._player_name = self._player_name[:-1]
                elif event.key == pygame.K_RETURN:
                    self._name_active = False
                elif len(self._player_name) < 16 and event.unicode.isprintable():
                    self._player_name += event.unicode
            elif self._ip_active:
                if event.key == pygame.K_BACKSPACE:
                    self._ip_text = self._ip_text[:-1]
                elif event.key == pygame.K_RETURN:
                    self._start_connect()
                elif len(self._ip_text) < 45 and event.unicode.isprintable():
                    self._ip_text += event.unicode
        self._connect_btn.handle_event(event)
        self._back_btn.handle_event(event)

    def update(self, dt):
        self._t += dt
        mp = pygame.mouse.get_pos()
        self._connect_btn.enabled = (self._state == 'entry')
        self._connect_btn.update(dt, mp)
        self._back_btn.update(dt, mp)

        if self._state == 'connecting':
            if self._connect_error:
                self._error = self._connect_error
                self._connect_error = None
                self._state = 'entry'
                self._client = None
            elif self._client is not None and self._client.connected:
                self._state = 'lobby'
                self._lobby_roster = []

        elif self._state == 'lobby':
            for msg in self._client.poll():
                t = msg.get('type')
                if t == 'reject':
                    self._error = msg.get('reason', 'Connection rejected')
                    self._client.close()
                    self._client = None
                    self._state = 'entry'
                    return
                elif t == 'lobby_state':
                    self._lobby_roster = msg.get('players', [])
                    settings = msg.get('settings') or {}
                    rows = settings.get('rows')
                    if rows:
                        # Wire format turns each (label, value) tuple into
                        # a 2-item list — normalize back for _draw_settings_panel.
                        self._settings_rows = [tuple(r) for r in rows]
                elif t == 'welcome':
                    self._reconnect_token = msg.get('reconnect_token')
                    host_version = msg.get('host_version')
                    if host_version and host_version != VERSION:
                        self._version_notice = (
                            f"Note: the host is running v{host_version}, you're on "
                            f"v{VERSION} — this may cause issues, but play should still work.")
                elif t == '_disconnected':
                    self._error = "Disconnected from host"
                    self._client = None
                    self._state = 'entry'
                    return
                elif t == 'start_game':
                    self._state = 'starting'
                    reconnect_info = None
                    if self._reconnect_token and self._connect_ip:
                        reconnect_info = {'host': self._connect_ip, 'port': self._connect_port,
                                          'name': self._connect_name, 'token': self._reconnect_token,
                                          'game_id': None, 'mode': 'lan'}
                    self._client_gm = ClientGameManager(self._client,
                                                        resolution=self.gm.resolution,
                                                        reconnect_info=reconnect_info)

        elif self._state == 'starting':
            self._client_gm.update(0.0)
            if self._client_gm.players:
                # From here on GameplayScene owns this ClientGameManager
                # and the underlying LANClient (see its on_exit()) — swap
                # it in as the SceneManager's active gm right before the
                # switch so on_enter() sees a fully-populated mirror.
                self.manager.gm = self._client_gm
                self.manager.switch('gameplay', network_role='client',
                                    client_gm=self._client_gm)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        ad_pad = self._ad_top_pad()
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)

        title = font_lg.render("Join LAN Game", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, s(50) + ad_pad))

        if self._state == 'entry':
            _draw_text_field(surf, font_sm, font_md, "Your Name:", self._name_rect,
                             self._player_name, self._name_active, self._t)
            _draw_text_field(surf, font_sm, font_md, "Host Address (IP:Port):", self._ip_rect,
                             self._ip_text, self._ip_active, self._t,
                             placeholder="e.g. 192.168.1.42:51999")
            hint_font = self.assets.font_scaled('ui_tiny', cs)
            hint = hint_font.render(
                "Ask the host — it's shown on their screen under \"Host a Game\".",
                True, (*WHITE, 160))
            surf.blit(hint, (self._ip_rect.x, self._ip_rect.bottom + s(6)))
            if self._error:
                err = font_sm.render(self._error, True, (220, 80, 80))
                surf.blit(err, (cx - err.get_width() // 2, s(360) + ad_pad))
            self._connect_btn.draw(surf)

        elif self._state == 'connecting':
            msg = font_md.render(f"Connecting to {self._ip_text.strip()}...", True, WHITE)
            surf.blit(msg, (cx - msg.get_width() // 2, sh // 2 - s(20)))

        elif self._state in ('lobby', 'starting'):
            msg = font_md.render("Connected — waiting for the host to start...",
                                 True, GOLD_LIGHT)
            surf.blit(msg, (cx - msg.get_width() // 2, s(120) + ad_pad))
            rl = font_sm.render(f"Players ({len(self._lobby_roster)}):", True, WHITE)
            surf.blit(rl, (cx - s(150), s(200) + ad_pad))
            for i, entry in enumerate(self._lobby_roster):
                you = " (you)" if entry['player_id'] == self._client.player_id else ""
                row = font_sm.render(f"  \u2022 {entry['name']}{you}", True, (*WHITE, 220))
                surf.blit(row, (cx - s(150), s(230) + ad_pad + i * s(28)))

            if self._settings_rows:
                max_scroll = _draw_settings_panel(
                    surf, self._settings_panel_rect, self._settings_rows,
                    font_md, font_sm, self._settings_scroll, title="Host's Settings")
                self._settings_scroll = max(0, min(max_scroll, self._settings_scroll))

            if self._state == 'starting':
                starting = font_md.render("Starting game...", True, GOLD_LIGHT)
                surf.blit(starting, (cx - starting.get_width() // 2, sh - s(160)))

            if self._version_notice:
                note_font = self.assets.font_scaled('ui_tiny', cs)
                note_lines = wrap_text(note_font, self._version_notice, sw - s(120))
                ny = sh - s(40) - (len(note_lines) - 1) * s(18)
                for line in note_lines:
                    ns = note_font.render(line, True, (230, 200, 120))
                    surf.blit(ns, (cx - ns.get_width() // 2, ny))
                    ny += s(18)

        self._back_btn.draw(surf)


# ─── Internet Multiplayer ─────────────────────────────────────────────────────
# Server-authoritative play against a public matchmaking + game-authority
# server (server/kadi_server.py) instead of a LAN peer. Reuses the exact
# same wire protocol/client transport LAN multiplayer already uses
# (network/client.LANClient, network/client_state.ClientGameManager) —
# only the server on the other end, and the lobby-level messages
# exchanged before a match starts, differ. See server/README.md for the
# full design writeup and deployment instructions.
#
# The key architectural difference from LAN: here EVERY player,
# including whoever created the hosted game, is a thin client of the
# server's own GameManager (server/game_room.GameRoom) — there is no
# local-host special case. That's why this always hands off to
# GameplayScene with network_role='client', never 'host'.

class InternetMenuScene(Scene):
    """Entry point for Internet Multiplayer: enter the server's address
    (host:port) and your name, then connect. Once connected, hands off
    to InternetLobbyScene to browse/host/join an actual game."""
    def on_enter(self, **kwargs):
        self._player_name = "Player"
        self._addr_text = ""
        self._name_active = False
        self._addr_active = True
        self._t = 0.0
        self._state = 'entry'  # entry -> connecting
        self._error = ""
        self._client: Optional[LANClient] = None
        self._connect_error: Optional[str] = None

        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        self._imenu_scale = cs
        # name_rect's y is derived from the title+subtitle block's own
        # actual rendered height (matching what draw() renders) rather
        # than a fixed s(150) — that fixed value and the title/subtitle
        # text (which scales with cs independently via font_scaled())
        # weren't tied together, so the subtitle was overlapping "Your
        # Name:" at higher resolutions (confirmed via a real screenshot
        # at 3840x2160). See draw()'s own title/sub placement, which
        # this mirrors exactly.
        title_h = self.assets.font_scaled('ui_large', cs).get_height()
        sub_h = self.assets.font_scaled('ui_normal', cs).get_height()
        # +label_h+6 accounts for "Your Name:" itself, which
        # _draw_text_field draws ABOVE _name_rect (see that function) —
        # the previous version of this formula left a flat s(20) gap
        # that didn't include room for that label, so the label text
        # still overlapped the subtitle above it even after the
        # subtitle/field collision itself was fixed (confirmed via a
        # real screenshot at 3840x2160).
        label_h = self.assets.font_scaled('ui_normal', cs).get_height()
        ad_pad = self._ad_top_pad()
        content_top = s(60) + ad_pad + title_h + s(8) + sub_h + s(20) + label_h + 6
        self._name_rect = pygame.Rect(cx - s(150), content_top, s(300), s(45))
        self._addr_rect = pygame.Rect(cx - s(150), content_top + s(80), s(300), s(45))
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        w52, h52 = round(260 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        self._connect_btn = Button(pygame.Rect(cx - w52 // 2, self._addr_rect.bottom + s(36), w52, h52),
                                   "Connect", font_lg, on_click=self._start_connect)
        self._back_btn = Button(pygame.Rect(cx - w48 // 2, sh - round(76 * cs), w48, h48), "Back", font_md,
                                color=(80, 60, 120), hover_color=(110, 85, 160),
                                on_click=self._go_back)

    def on_exit(self):
        # Only reached if the person backs out mid-connect-attempt —
        # once actually connected, ownership of self._client moves to
        # internet_lobby, whose own on_exit() takes over from there.
        if self._client is not None and self._state == 'connecting':
            self._client.close()

    def _go_back(self):
        self.manager.switch('multiplayer_menu')

    def _start_connect(self):
        if self._state != 'entry' or not self._addr_text.strip():
            return
        self._state = 'connecting'
        self._error = ""
        self._connect_error = None
        self._client = LANClient()
        # Same "bare host or host:port" acceptance LANJoinScene uses.
        raw = self._addr_text.strip()
        if ':' in raw:
            ip, _, port_str = raw.rpartition(':')
            try:
                port = int(port_str)
            except ValueError:
                ip, port = raw, INTERNET_DEFAULT_PORT
        else:
            ip, port = raw, INTERNET_DEFAULT_PORT
        name = self._player_name.strip() or "Player"
        # Stashed directly on the client instance (arbitrary attrs are
        # fine on a plain Python object) so internet_lobby --
        # and eventually ClientGameManager's own background reconnect
        # loop -- can find our way back to this same server without
        # needing a separate parameter threaded through
        # manager.switch()'s **kwargs.
        self._client.connect_host = ip
        self._client.connect_port = port
        self._client.connect_name = name

        def worker():
            try:
                self._client.connect(ip, port, name)
            except ConnectError as e:
                self._connect_error = str(e)
        # Off the main thread so a slow/unreachable server can't
        # freeze the pygame loop — same rule LANJoinScene follows.
        threading.Thread(target=worker, daemon=True).start()

    def handle_event(self, event):
        if self._state != 'entry':
            self._back_btn.handle_event(event)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._name_active = self._name_rect.collidepoint(event.pos)
            self._addr_active = self._addr_rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN:
            if self._name_active:
                if event.key == pygame.K_BACKSPACE:
                    self._player_name = self._player_name[:-1]
                elif event.key == pygame.K_RETURN:
                    self._name_active = False
                elif len(self._player_name) < 16 and event.unicode.isprintable():
                    self._player_name += event.unicode
            elif self._addr_active:
                if event.key == pygame.K_BACKSPACE:
                    self._addr_text = self._addr_text[:-1]
                elif event.key == pygame.K_RETURN:
                    self._start_connect()
                elif len(self._addr_text) < 64 and event.unicode.isprintable():
                    self._addr_text += event.unicode
        self._connect_btn.handle_event(event)
        self._back_btn.handle_event(event)

    def update(self, dt):
        self._t += dt
        mp = pygame.mouse.get_pos()
        self._connect_btn.enabled = (self._state == 'entry')
        self._connect_btn.update(dt, mp)
        self._back_btn.update(dt, mp)

        if self._state == 'connecting':
            if self._connect_error:
                self._error = self._connect_error
                self._connect_error = None
                self._state = 'entry'
                self._client = None
            elif self._client is not None and self._client.connected:
                client = self._client
                self._client = None  # ownership moves to internet_lobby
                self.manager.switch('internet_lobby', client=client)

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        ad_pad = self._ad_top_pad()
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)

        title = font_lg.render("Internet Multiplayer", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, s(60) + ad_pad))
        sub = font_sm.render("Play with anyone, anywhere, through a shared server", True,
                             (*WHITE, 160))
        surf.blit(sub, (cx - sub.get_width() // 2, s(60) + ad_pad + title.get_height() + s(8)))

        if self._state == 'entry':
            _draw_text_field(surf, font_sm, font_md, "Your Name:", self._name_rect,
                             self._player_name, self._name_active, self._t)
            _draw_text_field(surf, font_sm, font_md, "Server Address:",
                             self._addr_rect, self._addr_text, self._addr_active, self._t,
                             placeholder="kadigame.ddns.net")
            hint_font = self.assets.font_scaled('ui_tiny', cs)
            hint_lines = wrap_text(hint_font,
                "To join KADI's official server, just type kadigame.ddns.net "
                "— no port needed. Running your own server? Ask whoever "
                "hosts it for their address instead.",
                sw - self._addr_rect.x - s(40))
            hy = self._addr_rect.bottom + s(6)
            for line in hint_lines:
                hs = hint_font.render(line, True, (*WHITE, 160))
                surf.blit(hs, (self._addr_rect.x, hy))
                hy += hint_font.get_height() + 2
            # Repositioned below the hint's ACTUAL rendered height (1
            # line at wide resolutions, 2 at narrow ones like 1024x640,
            # where the same hint wraps because there's less width to
            # work with) rather than a fixed offset from _addr_rect
            # alone — a fixed offset didn't account for the hint
            # sometimes needing a second line, so the button was
            # overlapping that second line at 1024x640 specifically
            # (confirmed via a real screenshot).
            self._connect_btn.rect.y = hy + s(10)
            self._connect_btn.draw(surf)
            if self._error:
                err = font_sm.render(self._error, True, (220, 80, 80))
                surf.blit(err, (cx - err.get_width() // 2, self._connect_btn.rect.bottom + s(16)))
        else:
            msg = font_md.render(f"Connecting to {self._addr_text.strip()}...", True, WHITE)
            surf.blit(msg, (cx - msg.get_width() // 2, sh // 2 - s(20)))

        self._back_btn.draw(surf)


class InternetLobbyScene(Scene):
    """Browse open hosted games on the connected server, host a new one
    (configuring its rules similarly to LANHostLobbyScene), or join one
    someone else is hosting — then wait for the host to start, similarly
    to LANJoinScene's waiting room. Whoever creates a game and whoever
    joins it are BOTH thin clients of the server's authoritative
    GameManager (server/game_room.GameRoom) — there is no local-host
    special case here, which is why this scene only ever hands off to
    GameplayScene with network_role='client'."""

    LIST_REFRESH_SECS = 1.5

    def on_enter(self, client: Optional[LANClient] = None, **kwargs):
        self._client = client
        self._state = 'browse'  # browse -> joining -> lobby -> starting
        self._t = 0.0
        self._list_timer = 0.0
        self._games: List[dict] = []
        self._error = ""
        self._elimination_mode = False
        self._ai_count = 0
        self._ai_difficulty = AIDifficulty.MEDIUM
        self._my_player_id: Optional[int] = None
        self._host_id: Optional[int] = None
        self._game_id: Optional[str] = None
        self._lobby_roster: List[dict] = []
        self._settings_rows: List[Tuple[str, str]] = []
        self._settings_scroll = 0.0
        self._client_gm: Optional[ClientGameManager] = None
        self._game_name_text = ""
        self._game_name_active = False
        self._search_text = ""
        self._search_active = False
        self._lobby_game_name: Optional[str] = None
        self._reconnect_token: Optional[str] = None
        # Version-check notice — informational only, see
        # constants.VERSION and LANJoinScene's identical field.
        self._version_notice: Optional[str] = None

        # ── Global Leaderboard (Part B) ──────────────────────────────
        # Lives here rather than on ProfileScene (which holds the LOCAL
        # leaderboard, Part A) because this scene already has a live,
        # connected LANClient to the Internet Multiplayer server -- the
        # Profile screen has no persisted server address to reach for
        # one of its own, and this feature is explicitly an extension
        # of the existing protocol/connection, not a reason to prompt
        # for a server address a second time. 'idle' -> 'loading' ->
        # 'ready' | 'unavailable' (see _open_leaderboard/update()).
        self._lb_status = 'idle'
        self._lb_entries: List[dict] = []
        self._lb_my_rank: Optional[int] = None
        self._lb_my_wins: int = 0
        self._lb_got_rank = False
        # Server unreachable / doesn't answer -> fail gracefully rather
        # than hang the UI thread, per the READ FIRST instructions (a
        # leaderboard fetch is inherently less critical than the game
        # connection itself). There's no ConnectError to catch here
        # the way InternetMenuScene's initial connect has (we're
        # already connected) -- an old/unresponsive server would just
        # never answer 'get_leaderboard', so a plain timeout is what
        # actually detects that.
        self._lb_timeout_secs = 5.0
        self._lb_timer = 0.0

        sw, sh = self.gm.resolution
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        self._ilobby_scale = cs
        # ad_pad: this scene is ad-eligible (see AD_ELIGIBLE_SCENES) —
        # every top-anchored element below gets it added; bottom-
        # anchored ones (Start/Back, computed from sh) are untouched,
        # since the banner never affects the bottom of the screen. See
        # Scene._ad_top_pad()'s own docstring for the full story.
        ad_pad = self._ad_top_pad()
        # Shifted down from y=150 (was only 8px below the "Host a New
        # Game" header at y=116 — with that header's own text height,
        # its bottom edge actually landed ON TOP OF this field's label,
        # which is drawn 26px above game_name_rect, i.e. at old y=124,
        # squarely inside the header's ~116-146 span). +34 clears the
        # header with room to spare; every row below shifts the same
        # amount to keep their existing spacing intact. (All scaled
        # together via s() now, so that fixed relationship holds at
        # every resolution, not just the 1280x800 baseline it was
        # originally tuned against.)
        self._game_name_rect = pygame.Rect(cx - s(340), s(184) + ad_pad, s(260), s(40))
        self._elim_toggle_rect = pygame.Rect(cx - s(340), s(250) + ad_pad, s(260), s(40))
        # Same fix as LANHostLobbyScene: the "AI Players: N" label sits
        # 22px above this stepper, which used to land inside the
        # Elimination Mode button (216+40=256 bottom) above it. Shifted
        # down (+24) to clear it; rows below shift by the same amount.
        self._ai_minus_rect = pygame.Rect(cx - s(340), s(326) + ad_pad, s(40), s(36))
        self._ai_plus_rect = pygame.Rect(cx - s(130), s(326) + ad_pad, s(40), s(36))
        self._diff_buttons = []
        for i, (d, lbl) in enumerate([(AIDifficulty.EASY, "Easy"),
                                      (AIDifficulty.MEDIUM, "Medium"),
                                      (AIDifficulty.HARD, "Hard")]):
            r = pygame.Rect(cx - s(340) + i * s(88), s(372) + ad_pad, s(82), s(32))
            self._diff_buttons.append((d, lbl, r))
        # Attaching a trained MSOMI model works the same way LAN's host
        # lobby offers it (same widget, same core.msomi_trainer calls
        # on THIS client to read the file) — the difference is only in
        # what gets sent onward: LAN's host is the live GameManager, so
        # a filename is enough; here the model's actual JSON content
        # gets embedded in create_game's settings payload instead,
        # since the server can't see this machine's files. See
        # _create_game() below and server/game_room.py.
        msomi_toggle_rect = pygame.Rect(cx - s(340), s(420) + ad_pad, s(160), s(38))
        msomi_attach_rect = pygame.Rect(cx - s(172), s(420) + ad_pad, s(172), s(38))
        self._msomi = MSOMIPickerWidget(msomi_toggle_rect, msomi_attach_rect)
        # Width is capped, not simply *cs: this button sits in the same
        # fixed 340px-wide left column as the MSOMI picker widget above
        # it, with the Open Games list starting right at cx+20 — an
        # uncapped width at high resolutions would run this button
        # straight into that list. Font scale is capped by the same
        # ratio the width is, so the label always fits without Button's
        # shrink-to-fit kicking in — letting the font outscale a capped
        # box was producing a blurry look at high resolutions. (The cap
        # itself — 330 — is intentionally NOT run through s(): it's
        # measuring against the ALREADY-scaled natural_w below, same
        # units, so scaling it again would double-count cs.)
        natural_w = round(260 * cs)
        create_w = min(natural_w, 330)
        create_font_scale = cs * (create_w / natural_w) if natural_w > 0 else cs
        create_h = round(46 * cs)
        self._create_btn = Button(pygame.Rect(cx - s(340), s(480) + ad_pad, create_w, create_h), "Host a New Game",
                                  self.assets.font_scaled('ui_medium', create_font_scale), on_click=self._create_game)

        # Stacked directly below the "Host a New Game" button, in the
        # SAME left column — this column's own content always ends
        # here regardless of resolution (create_btn is the last widget
        # in it), so there's no risk of colliding with the search box,
        # its label, or the "Open Games (N):" header the way a
        # right-column placement did in two earlier attempts (visually
        # confirmed via screenshot — see the note above create_btn).
        lb_w, lb_h = create_w, round(38 * cs)
        self._leaderboard_btn = Button(
            pygame.Rect(cx - s(340), self._create_btn.rect.bottom + s(20), lb_w, lb_h),
            "Global Leaderboard", self.assets.font_scaled('ui_small', cs),
            color=(90, 70, 20), hover_color=(120, 95, 30), on_click=self._open_leaderboard)
        _lbw48, _lbh48 = round(260 * cs), round(48 * cs)
        self._lb_back_btn = Button(pygame.Rect(cx - _lbw48 // 2, sh - round(92 * cs), _lbw48, _lbh48),
                                   "Back", self.assets.font_scaled('ui_medium', cs),
                                   color=(80, 60, 120), hover_color=(110, 85, 160),
                                   on_click=self._close_leaderboard)

        # Lets a friend say "look for 'Friday Night KADI'" instead of
        # "look for whatever game_37 happens to be" — purely a label,
        # doesn't affect gameplay at all. Empty by default; the browse
        # list and lobby waiting-room both fall back to "<host>'s game"
        # wherever a room was never given one (see
        # server/game_room.GameRoom.display_name()).
        self._search_rect = pygame.Rect(cx + s(20), s(150) + ad_pad, s(340), s(36))
        # The "Open Games (N):" label is drawn 32px above
        # _games_list_rect (see draw()) — that used to land at y=164,
        # which is INSIDE the search box above it (search_rect spans
        # 150-186), so the label text and the search field's own
        # border/placeholder text overlapped. list.y is pushed down
        # far enough that its label clears the search box with room to
        # spare; height is trimmed by the same amount so the list's
        # bottom edge (and the gap above Start/Back) doesn't move.
        self._games_list_rect = pygame.Rect(cx + s(20), s(234) + ad_pad, s(340), sh - s(364) - ad_pad)
        self._settings_panel_rect = pygame.Rect(sw - s(360), s(190) + ad_pad, s(300), sh - s(290) - ad_pad)

        # Raised off the very bottom edge a bit (previously sh-140/sh-76,
        # uncomfortably close to the window edge on shorter resolutions).
        w52, h52 = round(260 * cs), round(52 * cs)
        w48, h48 = round(260 * cs), round(48 * cs)
        self._start_btn = Button(pygame.Rect(cx - w52 // 2, sh - round(156 * cs), w52, h52), "Start Game",
                                 self.assets.font_scaled('ui_large', cs), on_click=self._request_start)
        self._back_btn = Button(pygame.Rect(cx - w48 // 2, sh - round(92 * cs), w48, h48), "Back",
                                self.assets.font_scaled('ui_medium', cs),
                                color=(80, 60, 120), hover_color=(110, 85, 160),
                                on_click=self._go_back)

        if self._client is not None:
            self._client.send({'type': 'list_games'})

    def on_exit(self):
        # Only reached if the person leaves before a match actually
        # starts (Back from browse, or Back/close while waiting in a
        # lobby) — once 'starting' begins, GameplayScene's own
        # on_exit() takes over the same LANClient this scene handed it.
        if self._client is not None and self._state != 'starting':
            self._client.close()

    def _go_back(self):
        self.manager.switch('multiplayer_menu')

    def _open_leaderboard(self):
        if self._state != 'browse' or self._client is None:
            return
        self._state = 'leaderboard'
        self._lb_status = 'loading'
        self._lb_entries = []
        self._lb_my_rank = None
        self._lb_my_wins = 0
        self._lb_got_rank = False
        self._lb_timer = self._lb_timeout_secs
        self._client.send({'type': 'get_leaderboard', 'n': 20})
        self._client.send({'type': 'get_my_rank'})

    def _close_leaderboard(self):
        if self._state == 'leaderboard':
            self._state = 'browse'

    def _max_ai_slots(self) -> int:
        n_humans = len(self._lobby_roster) if self._state == 'lobby' else 1
        return max(0, MAX_PLAYERS - n_humans)

    def _create_game(self):
        if self._state != 'browse' or self._client is None:
            return
        settings = {
            'elimination_mode': self._elimination_mode,
            'ai_count': self._ai_count,
            'ai_difficulty': self._ai_difficulty.name,
            # Optional friendly label so a friend can say "look for
            # 'Friday Night KADI'" instead of an opaque game id. Purely
            # cosmetic — falls back to "<host>'s game" server-side if
            # left blank. Capped defensively; the server also caps it
            # (see GameRoom.__init__) so a malicious/buggy client can't
            # send an oversized value regardless.
            'game_name': self._game_name_text.strip()[:40],
            # Carries the host's OWN locally-configured rules (turn
            # timer, hints, ace/pickup/jump toggles -- whatever their
            # Settings screen last saved) onto the server's GameManager
            # for this room, the same way they'd already be "baked in"
            # for free on a LAN host's own live GameManager. See
            # network/settings_summary.py.
            'rules': settings_summary.rule_settings_payload(self.gm),
        }
        if self._ai_count > 0 and self._msomi.enabled and self._msomi.model_name:
            # Send the model's actual JSON content, not a filename --
            # the server has no access to THIS machine's files. Reads
            # and validates locally first so a bad/corrupt file is
            # caught right here with a clear message, exactly like
            # LAN's own attach flow does, rather than surfacing as a
            # vague server-side rejection later.
            try:
                model = msomi_trainer.load_model(self._msomi.model_name)
                problem = msomi_trainer.validate_model(model)
            except Exception as e:
                problem = f"Couldn't read that model file: {e}"
                model = None
            if problem:
                self._error = problem
                return
            settings['ai_msomi_model'] = model
            settings['ai_msomi_model_label'] = os.path.basename(self._msomi.model_name)
        self._client.send({'type': 'create_game', 'settings': settings})
        self._state = 'joining'

    def _join_game(self, game_id: str):
        if self._state != 'browse' or self._client is None:
            return
        self._client.send({'type': 'join_game', 'game_id': game_id})
        self._state = 'joining'

    def _request_start(self):
        if self._state != 'lobby' or self._client is None:
            return
        if self._my_player_id != self._host_id:
            return
        self._client.send({'type': 'request_start_game'})

    def _game_row_rect(self, i: int) -> pygame.Rect:
        s = round(64 * self._ilobby_scale), round(56 * self._ilobby_scale)
        return pygame.Rect(self._games_list_rect.x, self._games_list_rect.y + i * s[0],
                           self._games_list_rect.width, s[1])

    def _join_btn_rect(self, row: pygame.Rect) -> pygame.Rect:
        cs = self._ilobby_scale
        w, h = round(80 * cs), round(36 * cs)
        return pygame.Rect(row.right - round(90 * cs), row.y + round(10 * cs), w, h)

    def _filtered_games(self) -> List[dict]:
        """self._games (refreshed every LIST_REFRESH_SECS from the
        server) filtered by whatever's typed in the search box —
        matched against both the game's own name and its host's name,
        case-insensitively, so "if there are many games and your friend
        tells you the name of the hosted game" you can just type it and
        find theirs instead of scanning a long list."""
        q = self._search_text.strip().lower()
        if not q:
            return self._games
        return [g for g in self._games
               if q in g.get('game_name', '').lower() or q in g.get('host_name', '').lower()]

    def handle_event(self, event):
        if self._state == 'browse':
            sw, sh = self.gm.resolution
            # The MSOMI picker's own modal (if open) takes priority
            # over everything else underneath it — same rule
            # LANHostLobbyScene/ModeSelectScene use.
            self._msomi.handle_event(event, sw, sh, active=self._ai_count > 0)
            if self._msomi.picker_open:
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._game_name_active = self._game_name_rect.collidepoint(event.pos)
                self._search_active = self._search_rect.collidepoint(event.pos)
                if self._elim_toggle_rect.collidepoint(event.pos):
                    self._elimination_mode = not self._elimination_mode
                if self._ai_minus_rect.collidepoint(event.pos):
                    self._ai_count = max(0, self._ai_count - 1)
                if self._ai_plus_rect.collidepoint(event.pos):
                    self._ai_count = min(self._max_ai_slots(), self._ai_count + 1)
                for d, lbl, r in self._diff_buttons:
                    if r.collidepoint(event.pos):
                        self._ai_difficulty = d
                for i, g in enumerate(self._filtered_games()):
                    row = self._game_row_rect(i)
                    if row.bottom < self._games_list_rect.y or row.y > self._games_list_rect.bottom:
                        continue
                    if self._join_btn_rect(row).collidepoint(event.pos):
                        self._join_game(g['game_id'])
            self._leaderboard_btn.handle_event(event)
            if event.type == pygame.KEYDOWN:
                if self._game_name_active:
                    if event.key == pygame.K_BACKSPACE:
                        self._game_name_text = self._game_name_text[:-1]
                    elif event.key == pygame.K_RETURN:
                        self._game_name_active = False
                    elif len(self._game_name_text) < 40 and event.unicode.isprintable():
                        self._game_name_text += event.unicode
                elif self._search_active:
                    if event.key == pygame.K_BACKSPACE:
                        self._search_text = self._search_text[:-1]
                    elif event.key == pygame.K_RETURN:
                        self._search_active = False
                    elif len(self._search_text) < 40 and event.unicode.isprintable():
                        self._search_text += event.unicode
            self._create_btn.handle_event(event)
        elif self._state == 'lobby':
            if event.type == pygame.MOUSEWHEEL and self._settings_panel_rect.collidepoint(
                    pygame.mouse.get_pos()):
                max_scroll = max(0, len(self._settings_rows) * 30
                                 - (self._settings_panel_rect.height - 56))
                self._settings_scroll = max(0, min(max_scroll,
                                                   self._settings_scroll - event.y * 30))
            if self._my_player_id == self._host_id:
                self._start_btn.handle_event(event)
        elif self._state == 'leaderboard':
            self._lb_back_btn.handle_event(event)
        if self._state != 'leaderboard':
            self._back_btn.handle_event(event)

    def update(self, dt):
        self._t += dt
        mp = pygame.mouse.get_pos()
        if self._state != 'leaderboard':
            self._back_btn.update(dt, mp)

        if self._client is None:
            return

        if self._state == 'browse':
            self._list_timer -= dt
            if self._list_timer <= 0:
                self._client.send({'type': 'list_games'})
                self._list_timer = self.LIST_REFRESH_SECS
            self._ai_count = min(self._ai_count, self._max_ai_slots())
            self._create_btn.update(dt, mp)
            self._leaderboard_btn.update(dt, mp)

        if self._state == 'leaderboard':
            self._lb_back_btn.update(dt, mp)
            if self._lb_status == 'loading':
                self._lb_timer -= dt
                if self._lb_timer <= 0:
                    self._lb_status = 'unavailable'

        if self._state != 'starting':
            # Once a ClientGameManager exists (state == 'starting'),
            # IT becomes the sole reader of this socket (via its own
            # update() below) -- draining generically here too would
            # race it and silently swallow 'state_sync' messages, since
            # _handle_message below has no case for that type. Same
            # state-scoped-poll rule LANJoinScene follows.
            for msg in self._client.poll():
                self._handle_message(msg)

        if self._state == 'lobby' and self._my_player_id == self._host_id:
            self._start_btn.enabled = (len(self._lobby_roster) + self._ai_count >= MIN_PLAYERS)
            self._start_btn.update(dt, mp)

        if self._state == 'starting' and self._client_gm is not None:
            self._client_gm.update(0.0)
            if self._client_gm.players:
                # From here on GameplayScene owns this ClientGameManager
                # and the underlying LANClient — exactly the same
                # ownership handoff LANJoinScene performs.
                self.manager.gm = self._client_gm
                self.manager.switch('gameplay', network_role='client',
                                    client_gm=self._client_gm, is_internet=True)

    def _handle_message(self, msg: dict):
        t = msg.get('type')
        if t == 'games_list':
            self._games = msg.get('games', [])
        elif t == 'welcome':
            self._my_player_id = msg.get('player_id')
            self._host_id = msg.get('host_id')
            self._game_id = msg.get('game_id')
            self._reconnect_token = msg.get('reconnect_token')
            self._state = 'lobby'
            server_version = msg.get('server_version')
            if server_version and server_version != VERSION:
                self._version_notice = (
                    f"Note: the server is running v{server_version}, you're on "
                    f"v{VERSION} — this may cause issues, but play should still work.")
        elif t == 'lobby_state':
            self._lobby_roster = msg.get('players', [])
            hid = msg.get('host_id')
            if hid is not None:
                self._host_id = hid
            gn = msg.get('game_name')
            if gn:
                self._lobby_game_name = gn
            settings = msg.get('settings') or {}
            rows = settings.get('rows')
            if rows:
                self._settings_rows = [tuple(r) for r in rows]
        elif t == 'leaderboard_result':
            self._lb_entries = msg.get('entries', [])
            self._lb_status = 'ready'
        elif t == 'my_rank_result':
            self._lb_my_rank = msg.get('rank')
            self._lb_my_wins = msg.get('wins', 0)
            self._lb_got_rank = True
        elif t == 'reject':
            self._error = msg.get('reason', 'Request rejected')
            self._state = 'browse'
        elif t == 'room_closed':
            self._error = msg.get('reason', 'The lobby was closed')
            self._state = 'browse'
            self._lobby_roster = []
            self._my_player_id = None
            self._host_id = None
        elif t == 'start_game':
            self._state = 'starting'
            reconnect_info = None
            host = getattr(self._client, 'connect_host', None)
            port = getattr(self._client, 'connect_port', None)
            name = getattr(self._client, 'connect_name', None)
            if self._reconnect_token and host and port:
                reconnect_info = {'host': host, 'port': port, 'name': name,
                                  'token': self._reconnect_token,
                                  'game_id': self._game_id, 'mode': 'internet'}
            self._client_gm = ClientGameManager(self._client, resolution=self.gm.resolution,
                                                reconnect_info=reconnect_info)
        elif t == '_disconnected':
            self._client = None
            self.manager.switch('internet_menu')

    def draw(self, surf):
        sw, sh = self.gm.resolution
        surf.fill((15, 24, 34))
        cx = sw // 2
        cs = get_chrome_scale(sw, sh)
        s = lambda px: round(px * cs)
        ad_pad = self._ad_top_pad()
        font_lg = self.assets.font_scaled('ui_large', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)
        font_tiny = self.assets.font_scaled('ui_tiny', cs)

        if self._state == 'browse':
            title = font_lg.render("Internet Multiplayer — Browse Games", True, GOLD_LIGHT)
            surf.blit(title, (cx - title.get_width() // 2, s(60) + ad_pad))

            hdr = font_md.render("Host a New Game", True, WHITE)
            surf.blit(hdr, (cx - s(340), s(116) + ad_pad))

            _draw_text_field(surf, font_sm, font_md, "Game Name (optional):",
                             self._game_name_rect, self._game_name_text,
                             self._game_name_active, self._t,
                             placeholder="e.g. Friday Night KADI")

            ec = (60, 140, 60) if self._elimination_mode else (60, 60, 80)
            pygame.draw.rect(surf, ec, self._elim_toggle_rect, border_radius=8)
            elabel = "Elimination Mode: ON" if self._elimination_mode else "Elimination Mode: OFF"
            et = font_sm.render(elabel, True, WHITE)
            surf.blit(et, (self._elim_toggle_rect.centerx - et.get_width() // 2,
                          self._elim_toggle_rect.centery - et.get_height() // 2))

            max_ai = self._max_ai_slots()
            minus_on = self._ai_count > 0
            plus_on = self._ai_count < max_ai
            pygame.draw.rect(surf, (60, 60, 80) if minus_on else (35, 35, 45),
                             self._ai_minus_rect, border_radius=6)
            pygame.draw.rect(surf, (60, 60, 80) if plus_on else (35, 35, 45),
                             self._ai_plus_rect, border_radius=6)
            minus_t = font_md.render("-", True, WHITE if minus_on else (*WHITE, 90))
            plus_t = font_md.render("+", True, WHITE if plus_on else (*WHITE, 90))
            surf.blit(minus_t, (self._ai_minus_rect.centerx - minus_t.get_width() // 2,
                                self._ai_minus_rect.centery - minus_t.get_height() // 2))
            surf.blit(plus_t, (self._ai_plus_rect.centerx - plus_t.get_width() // 2,
                               self._ai_plus_rect.centery - plus_t.get_height() // 2))
            ai_lbl = font_sm.render(f"AI Players: {self._ai_count}", True, WHITE)
            surf.blit(ai_lbl, (self._elim_toggle_rect.x, self._ai_minus_rect.y - s(22)))

            for d, lbl, r in self._diff_buttons:
                active = (d == self._ai_difficulty)
                enabled = self._ai_count > 0
                col = (90, 70, 20) if active and enabled else ((45, 45, 55) if enabled else (30, 30, 36))
                pygame.draw.rect(surf, col, r, border_radius=6)
                if active and enabled:
                    pygame.draw.rect(surf, GOLD_LIGHT, r, width=2, border_radius=6)
                txt_col = WHITE if enabled else (*WHITE, 90)
                t = font_sm.render(lbl, True, txt_col)
                surf.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))

            self._create_btn.draw(surf)
            self._leaderboard_btn.draw(surf)

            msomi_lbl = font_sm.render("MSOMI:", True, WHITE if self._ai_count else (*WHITE, 100))
            surf.blit(msomi_lbl, (self._msomi.toggle_rect.x, self._msomi.toggle_rect.y - s(22)))
            self._msomi.draw_controls(surf, font_sm, active=self._ai_count > 0)

            if self._ai_count > 0:
                msomi_caption = font_tiny.render(
                    "Optional — sent to the server just for this one game, not saved there.",
                    True, (*WHITE, 150))
                surf.blit(msomi_caption, (cx - s(340), self._msomi.toggle_rect.bottom + s(8)))

            _draw_text_field(surf, font_sm, font_md, "Search by game or host name:",
                             self._search_rect, self._search_text, self._search_active, self._t,
                             placeholder="Type a name your friend gave you...")

            filtered = self._filtered_games()
            lbl = font_md.render(f"Open Games ({len(filtered)}"
                                 + (f" of {len(self._games)}" if self._search_text.strip() else "")
                                 + "):", True, WHITE)
            surf.blit(lbl, (self._games_list_rect.x, self._games_list_rect.y - s(32)))
            if not self._games:
                empty = font_sm.render("No open games right now — host one!",
                                       True, (*WHITE, 160))
                surf.blit(empty, (self._games_list_rect.x, self._games_list_rect.y))
            elif not filtered:
                empty = font_sm.render(f"No open games matching \"{self._search_text.strip()}\".",
                                       True, (*WHITE, 160))
                surf.blit(empty, (self._games_list_rect.x, self._games_list_rect.y))
            clip = surf.get_clip()
            surf.set_clip(self._games_list_rect)
            for i, g in enumerate(filtered):
                row = self._game_row_rect(i)
                if row.bottom < self._games_list_rect.y or row.y > self._games_list_rect.bottom:
                    continue
                pygame.draw.rect(surf, (24, 38, 50), row, border_radius=8)
                pygame.draw.rect(surf, (*WHITE, 60), row, width=1, border_radius=8)
                # The host's chosen label takes top billing (what a
                # friend would actually recognize) — the host's own
                # name moves to a secondary line rather than being
                # mashed into one string, once a real game_name is set.
                display_name = g.get('game_name') or f"{g['host_name']}'s game"
                name = font_sm.render(
                    f"{display_name} ({g['player_count']}/{g['max_players']})",
                    True, WHITE)
                surf.blit(name, (row.x + s(12), row.y + s(8)))
                summary_parts = []
                if g.get('game_name'):
                    # Custom name is now the headline, so the host's own
                    # name would otherwise disappear from this row —
                    # keep it visible as context. Only 1 settings row
                    # alongside it (rather than 2) to keep the line from
                    # overflowing the card.
                    summary_parts.append(f"Hosted by {g['host_name']}")
                    summary_parts.extend(f"{k}: {v}" for k, v in g.get('rows', [])[:1])
                else:
                    summary_parts.extend(f"{k}: {v}" for k, v in g.get('rows', [])[:2])
                if summary_parts:
                    st = font_tiny.render(", ".join(summary_parts), True, (*WHITE, 150))
                    surf.blit(st, (row.x + s(12), row.y + s(30)))
                jr = self._join_btn_rect(row)
                pygame.draw.rect(surf, (60, 110, 60), jr, border_radius=6)
                jt = font_sm.render("Join", True, WHITE)
                surf.blit(jt, (jr.centerx - jt.get_width() // 2, jr.centery - jt.get_height() // 2))
            surf.set_clip(clip)

            if self._error:
                err = font_sm.render(self._error, True, (220, 80, 80))
                surf.blit(err, (cx - err.get_width() // 2, sh - s(172)))

        elif self._state == 'joining':
            title = font_lg.render("Internet Multiplayer", True, GOLD_LIGHT)
            surf.blit(title, (cx - title.get_width() // 2, s(60)))
            msg = font_md.render("Contacting server...", True, WHITE)
            surf.blit(msg, (cx - msg.get_width() // 2, sh // 2 - s(20)))

        elif self._state in ('lobby', 'starting'):
            title_txt = (f"Internet Multiplayer — {self._lobby_game_name}"
                        if self._lobby_game_name else "Internet Multiplayer — Lobby")
            title = font_lg.render(title_txt, True, GOLD_LIGHT)
            surf.blit(title, (cx - title.get_width() // 2, s(60) + ad_pad))
            you_are_host = (self._my_player_id == self._host_id)
            sub = font_sm.render(
                "You are hosting — start whenever you're ready."
                if you_are_host else "Connected — waiting for the host to start...",
                True, GOLD_LIGHT)
            surf.blit(sub, (cx - sub.get_width() // 2, s(110) + ad_pad))

            rl = font_sm.render(f"Players ({len(self._lobby_roster)}):", True, WHITE)
            surf.blit(rl, (cx - s(340), s(160) + ad_pad))
            for i, entry in enumerate(self._lobby_roster[:6]):
                tag = ""
                if entry['player_id'] == self._my_player_id:
                    tag = " (you)"
                if entry['player_id'] == self._host_id:
                    tag += " [host]"
                row = font_sm.render(f"  \u2022 {entry['name']}{tag}", True, (*WHITE, 220))
                surf.blit(row, (cx - s(340), s(188) + ad_pad + i * s(26)))

            if self._settings_rows:
                # Panel used to always stretch to the full fixed height
                # even for 1-2 rows, leaving a large empty box below the
                # content — size it to the content instead, capped at
                # the original max height so it still scrolls if needed.
                content_h = len(self._settings_rows) * s(30) + s(56)
                panel_h = min(self._settings_panel_rect.height, max(s(96), content_h))
                panel_rect = pygame.Rect(self._settings_panel_rect.x,
                                         self._settings_panel_rect.y,
                                         self._settings_panel_rect.width, panel_h)
                max_scroll = _draw_settings_panel(
                    surf, panel_rect, self._settings_rows,
                    font_md, font_sm, self._settings_scroll, title="Game Settings")
                self._settings_scroll = max(0, min(max_scroll, self._settings_scroll))

            if you_are_host:
                if len(self._lobby_roster) + self._ai_count < MIN_PLAYERS:
                    hint = font_sm.render(
                        "Need at least 2 players total to start.", True, (200, 180, 80))
                    surf.blit(hint, (cx - hint.get_width() // 2, sh - s(200)))
                self._start_btn.draw(surf)
            if self._state == 'starting':
                starting = font_md.render("Starting game...", True, GOLD_LIGHT)
                surf.blit(starting, (cx - starting.get_width() // 2, sh - s(160)))

            if self._version_notice:
                note_font = font_tiny
                note_lines = wrap_text(note_font, self._version_notice, sw - s(120))
                ny = sh - s(40) - (len(note_lines) - 1) * s(18)
                for line in note_lines:
                    ns = note_font.render(line, True, (230, 200, 120))
                    surf.blit(ns, (cx - ns.get_width() // 2, ny))
                    ny += s(18)

        elif self._state == 'leaderboard':
            self._draw_leaderboard(surf, cx, sw, sh, font_lg, font_md, font_sm, font_tiny)

        if self._state == 'leaderboard':
            self._lb_back_btn.draw(surf)
        else:
            self._back_btn.draw(surf)

        # Drawn LAST so it's always visibly on top of everything above
        # (including the Back button) — same rule LANHostLobbyScene follows.
        if self._state == 'browse':
            self._msomi.draw_modal(surf, sw, sh, font_md, font_sm, font_tiny)

    def _draw_leaderboard(self, surf, cx, sw, sh, font_lg, font_md, font_sm, font_tiny):
        cs = self._ilobby_scale
        s = lambda px: round(px * cs)
        ad_pad = self._ad_top_pad()
        title = font_lg.render("Global Leaderboard — Internet Multiplayer Wins", True, GOLD_LIGHT)
        surf.blit(title, (cx - title.get_width() // 2, s(60) + ad_pad))
        sub = font_sm.render(
            "Ranked by total wins in server-run Internet Multiplayer games only.",
            True, (*WHITE, 160))
        surf.blit(sub, (cx - sub.get_width() // 2, s(106) + ad_pad))

        list_rect = pygame.Rect(cx - s(260), s(150) + ad_pad, s(520), sh - s(300) - ad_pad)
        pygame.draw.rect(surf, (18, 28, 38), list_rect, border_radius=10)
        pygame.draw.rect(surf, (*WHITE, 40), list_rect, width=1, border_radius=10)

        if self._lb_status == 'loading':
            msg = font_md.render("Fetching leaderboard...", True, WHITE)
            surf.blit(msg, (list_rect.centerx - msg.get_width() // 2,
                            list_rect.centery - msg.get_height() // 2))
        elif self._lb_status == 'unavailable':
            msg = font_md.render("Leaderboard unavailable", True, (220, 120, 80))
            surf.blit(msg, (list_rect.centerx - msg.get_width() // 2, list_rect.y + s(30)))
            hint_y = list_rect.y + s(80)
            for wrapped in wrap_text(font_sm, "Couldn't reach the server for leaderboard data. "
                                     "Your game connection is unaffected.", list_rect.width - s(40)):
                t = font_sm.render(wrapped, True, (*WHITE, 170))
                surf.blit(t, (list_rect.x + s(20), hint_y))
                hint_y += t.get_height() + 2
        elif self._lb_status == 'ready':
            if not self._lb_entries:
                empty = font_sm.render("No Internet Multiplayer wins recorded yet.", True, (*WHITE, 170))
                surf.blit(empty, (list_rect.centerx - empty.get_width() // 2, list_rect.y + s(30)))
            else:
                row_h = s(34)
                ry = list_rect.y + s(16)
                for i, entry in enumerate(self._lb_entries, start=1):
                    name = str(entry.get('name', '?'))
                    wins = entry.get('wins', 0)
                    if ry + row_h > list_rect.bottom - s(10):
                        break
                    col = GOLD_LIGHT if i <= 3 else WHITE
                    rank_t = font_sm.render(f"{i}.", True, col)
                    surf.blit(rank_t, (list_rect.x + s(20), ry))
                    name_t = font_sm.render(name, True, col)
                    surf.blit(name_t, (list_rect.x + s(60), ry))
                    wins_t = font_sm.render(f"{wins} win{'s' if wins != 1 else ''}", True, (*WHITE, 200))
                    surf.blit(wins_t, (list_rect.right - s(20) - wins_t.get_width(), ry))
                    ry += row_h
            if self._lb_got_rank:
                if self._lb_my_rank is not None:
                    rank_line = (f"Your rank: #{self._lb_my_rank} "
                                f"({self._lb_my_wins} win{'s' if self._lb_my_wins != 1 else ''})")
                else:
                    rank_line = "Your rank: no Internet Multiplayer wins recorded yet."
                rt = font_sm.render(rank_line, True, GOLD_LIGHT)
                surf.blit(rt, (list_rect.centerx - rt.get_width() // 2, list_rect.bottom + s(14)))


class GameplayScene(Scene):
    # Chat quick-reactions: plain ASCII text (what's actually sent over
    # the wire and what a client with no icon set would still show
    # legibly) mapped to the vector icon (see rendering.widgets
    # .draw_icon) shown for it instead, both on its own button and
    # wherever that exact text turns up in the chat log — see
    # _build_buttons and _draw_chat. Kept as one shared table so the
    # button someone clicks and the bubble that appears (on every
    # participant's screen, not just the sender's) always agree.
    REACTION_ICONS = {
        "+1":   ('thumbs_up',  (230, 200, 80)),
        "Haha": ('face_laugh', (230, 200, 80)),
        "Wow":  ('face_wow',   (230, 200, 80)),
        "<3":   ('heart',      (220, 60, 80)),
        "Grr":  ('face_angry', (230, 120, 80)),
        "GG":   ('star',       (255, 215, 60)),
    }

    HELP_SECTIONS = [
        ("Playing your turn", [
            "Play a card that matches the SUIT or RANK of the top "
            "discard card, or click Draw Card if you can't or don't "
            "want to play. Click a card in your hand to select it "
            "(gold glow), then Play Card(s) — or just click Draw Card "
            "or the draw pile directly.",
            "Playable cards are highlighted; unplayable ones are dimmed "
            "so it's clear at a glance what your options are.",
        ]),
        ("Arranging multi-card plays", [
            "Drag and drop cards in your hand to reorder them — click "
            "and hold a card, then drag it left or right to a new "
            "position. This matters for multi-card plays (like a "
            "Question card plus its answer, or several Jacks/Kings "
            "played together): put the cards in the order you want "
            "them played, in a single line, before selecting and "
            "playing them together.",
            # Image spliced in at construction time — see _build_buttons,
            # which loads assets/help/help_drag_multicard.png and
            # inserts it right after this paragraph (can't load it here,
            # at class-body/import time, since pygame's display isn't
            # necessarily initialized yet).
        ]),
        ("Declaring KADI", [
            "Click Declare KADI! on your second-to-last card to warn "
            "everyone you're about to finish — forgetting to declare "
            "in time carries a penalty, so it's worth getting in the "
            "habit of clicking it as soon as you're down to 2 cards.",
        ]),
        ("Undo", [
            "A limited number of undo tokens let you take back your "
            "last move if you misclick. When available, an Undo button "
            "appears right after you play or draw, showing your "
            "current token count in its label — e.g. \"Undo (2)\".",
        ]),
    ]


    def on_enter(self, player_configs=None, elimination_mode=None,
                elimination_ai_only_continue=None, network_role=None,
                host_game=None, client_gm=None, is_internet=False, **kwargs):
        self.board = self.manager.board
        self.anim  = self.manager.anim
        # Distinguishes LAN from Internet play for profile stats (Part 1)
        # — network_role alone can't tell them apart, since Internet play
        # (see InternetLobbyScene's docstring) is network_role='client'
        # for BOTH the game's creator and joiners; only LANHostLobbyScene
        # ever uses network_role='host'. Callers set is_internet=True
        # explicitly from the Internet menu flow.
        self._is_internet = is_internet
        self._profile_stats_done = False

        # network_role is None for ordinary single-player/local-multiplayer
        # games. 'host' means self.gm is the SAME real GameManager the
        # host's own single-player code always uses — network/host_game.py
        # just also validates and applies OTHER players' moves against it.
        # 'client' means self.gm is a ClientGameManager (see
        # network/client_state.py): a thin mirror that sends intents and
        # never mutates game state locally. Either way, everything below
        # this point (buttons, rendering, event handling) is completely
        # unaware of the difference — that's the whole point.
        self._network_role = network_role
        self._host_game = host_game if network_role == 'host' else None
        self._client_gm = client_gm if network_role == 'client' else None
        self._reconnect_banner: Optional[MessageBanner] = None
        self._last_conn_status = 'ok'
        self._chat_open = False
        self._chat_input_text = ""
        self._chat_input_active = False
        self._chat_seen_count = 0  # len(chat_log) already shown on the toggle badge

        self._selected: set = set()
        self._hovered: Optional[int] = None
        self._playable: set = set()
        self._messages: List[MessageBanner] = []
        self._kadi_banner: Optional[KADIBanner] = None
        self._win_screen: Optional[WinScreen] = None
        self._exit_confirm_pending: bool = False

        # Drag-to-reorder state
        self._drag_idx: Optional[int] = None      # card index being dragged
        self._drag_pos: Optional[tuple] = None    # current mouse pos while dragging
        self._drag_target: Optional[int] = None   # current drop slot
        self._drag_start_pos: Optional[tuple] = None
        self._drag_threshold = 8  # pixels before drag starts

        # Local hot-seat "Pass and Play" state — see _visible_player's and
        # _my_player's docstrings. Irrelevant (never triggers) outside a
        # local (non-networked) game with 2+ human players.
        self._revealed_player = None          # human currently allowed to see their hand
        self._pending_reveal_target = None    # human waiting on the interstitial, or None
        self._hotseat_auto_paused = False     # did WE pause the game for the current handoff?
        sw0, sh0 = self.gm.resolution
        _pass_scale = get_chrome_scale(sw0, sh0)
        self._pass_overlay = PassAndPlayOverlay(
            sw0, sh0, self.assets.font_scaled('ui_large', _pass_scale),
            self.assets.font_scaled('ui_medium', _pass_scale),
            self.assets.font_scaled('ui_small', _pass_scale), scale=_pass_scale)

        sw, sh = self.gm.resolution
        self._suit_picker = SuitPicker(sw, sh,
                                       self.assets.font_scaled('ui_medium', get_chrome_scale(sw, sh)),
                                       on_pick=self._on_suit_picked,
                                       scale=get_chrome_scale(sw, sh))

        self.gm.subscribe(self._on_game_event)

        if player_configs:
            em = elimination_mode if elimination_mode is not None else self.gm.elimination_mode
            eac = (elimination_ai_only_continue if elimination_ai_only_continue is not None
                   else self.gm.elimination_ai_only_continue)
            self.gm.new_game(player_configs, elimination_mode=em,
                             elimination_ai_only_continue=eac)
            self.board.setup_layout(len(self.gm.players), sw, sh, top_margin=self._ad_top_pad())
        elif kwargs.get('resume'):
            # Game state was already rehydrated by save_manager.load_game()
            # before switching to this scene — just lay the board out for
            # however many players that save has.
            self.board.setup_layout(len(self.gm.players), sw, sh, top_margin=self._ad_top_pad())
        elif network_role:
            # Host: HostGame.start_game() already called gm.new_game() on
            # this same shared GameManager before switching here. Client:
            # LANJoinScene already waited for the first state_sync to
            # populate self.gm.players before switching here. Either way
            # there's nothing left to initialize — just lay the board out.
            self.board.setup_layout(len(self.gm.players), sw, sh, top_margin=self._ad_top_pad())

        self._build_buttons()
        self._refresh_playable()

    def on_exit(self):
        # Fires on EVERY switch away from this scene (Menu, Save & Exit,
        # Discard & Exit, the win screen's Menu button, ESC) — see
        # scenes.SceneManager.switch(). That makes this the one place
        # network teardown needs to live, rather than duplicating it at
        # every individual exit call site.
        if self._network_role == 'host' and self._host_game is not None:
            self._host_game.stop()
        elif self._network_role == 'client' and self._client_gm is not None:
            self._client_gm.client.close()
            # self.manager.gm was pointed at this ClientGameManager by
            # LANJoinScene for the duration of the match — restore the
            # SceneManager's real single-player GameManager so every
            # other scene (main menu, mode select, settings, ...) goes
            # back to reading/writing the one it always expects.
            self.manager.gm = self.manager.singleplayer_gm
        self._network_role = None
        self._host_game = None
        self._client_gm = None

    # ── Button layout ─────────────────────────────────────────────────────────

    def _build_buttons(self):
        sw, sh = self.gm.resolution
        chrome_scale = get_chrome_scale(sw, sh)
        font_lg = self.assets.font_scaled('ui_large', chrome_scale)
        font    = self.assets.font_scaled('ui_medium', chrome_scale)
        font_sm = self.assets.font_scaled('ui_normal', chrome_scale)
        # "Declare KADI!" already overflowed a 160px-wide box even before
        # this pass (pre-existing, at every resolution) — same
        # shrink-to-fit blur as MultiplayerMenuScene above. 190 fits it
        # (and every other label in this stack) without shrinking.
        bw, bh = round(190 * chrome_scale), round(46 * chrome_scale)

        # Right-side action panel — stack from bottom, leave more margin
        # than before: on some platforms, restoring the window after a
        # minimize (or un-maximizing) can leave SDL's scaled presentation
        # squeezed for a frame/session, cropping a strip off the bottom
        # of the table. A slimmer 10px margin put "Clear Selection" right
        # in that cropped strip; 40px keeps the whole stack clear of it.
        bx = sw - bw - 14
        b4 = sh - bh - 40        # bottom button
        b3 = b4 - bh - 8
        b2 = b3 - bh - 8
        b1 = b2 - bh - 8

        self._btn_kadi = Button(
            pygame.Rect(bx, b1, bw, bh), "Declare KADI!", font,
            color=(160,30,30), hover_color=(200,50,50),
            on_click=self._action_declare_kadi)

        self._btn_play = Button(
            pygame.Rect(bx, b2, bw, bh), "Play Card(s)", font,
            on_click=self._action_play)

        self._btn_draw = Button(
            pygame.Rect(bx, b3, bw, bh), "Draw Card", font,
            color=(60,100,60), hover_color=(80,140,80),
            on_click=self._action_draw)

        self._btn_clear = Button(
            pygame.Rect(bx, b4, bw, bh), "Clear Selection", font_sm,
            color=(60,60,80), hover_color=(85,85,110),
            on_click=self._action_clear)

        # Counter window buttons — centered as one group, sitting well
        # above the bottom edge for the same "squeezed after
        # minimize/restore" reason as the action panel above. Pass now
        # sits directly beside "Play J to Counter" (same row, same
        # height) instead of below it near the screen edge, where that
        # same squeeze could crop it out of reach entirely and leave a
        # pending counter with no visible way to decline it.
        counter_w, pass_w, gap, cbh = (round(310 * chrome_scale), round(140 * chrome_scale),
                                        round(14 * chrome_scale), round(50 * chrome_scale))
        group_w = counter_w + gap + pass_w
        gx = sw // 2 - group_w // 2
        cy = sh - round(120 * chrome_scale)
        self._btn_counter = Button(
            pygame.Rect(gx, cy, counter_w, cbh),
            "Play J to Counter", font,
            color=(160,80,0), hover_color=(210,110,0),
            on_click=self._action_counter)
        self._btn_pass_counter = Button(
            pygame.Rect(gx + counter_w + gap, cy, pass_w, cbh),
            "Pass", font_sm,
            color=(50,50,80), hover_color=(70,70,110),
            on_click=self._action_pass_counter)

        # Menu / Pause — the two "corner chrome" buttons for this scene,
        # top-left. Scaled by the same get_chrome_scale() factor as
        # WindowControls/AudioControls (top-right) and every other
        # fixed-pixel menu button, so this cluster grows consistently
        # with the rest of the chrome instead of staying pinned at its
        # 1280x800 size. AdBanner.draw() reads _btn_pause.rect.right
        # directly to place its own left-side clearance, so this is the
        # one spot in the file whose real rect another system depends on
        # at runtime — see AdBanner.draw().
        font_chrome = font_sm  # same font_scaled('ui_normal', chrome_scale) computed above
        menu_margin = round(14 * chrome_scale)
        menu_w, menu_h = round(100 * chrome_scale), round(34 * chrome_scale)
        pause_w = round(80 * chrome_scale)
        menu_pause_gap = round(6 * chrome_scale)

        self._btn_menu = Button(
            pygame.Rect(menu_margin, menu_margin, menu_w, menu_h), "Menu", font_chrome,
            color=(50,50,80), hover_color=(70,70,110),
            on_click=self._action_menu_clicked)

        self._btn_pause = Button(
            pygame.Rect(menu_margin + menu_w + menu_pause_gap, menu_margin, pause_w, menu_h),
            "Pause", font_chrome,
            color=(60, 80, 60), hover_color=(80, 110, 80),
            on_click=self._action_toggle_pause)

        # Plain in-match chat — LAN/Internet only (self._network_role is
        # None for single-player/local hot-seat, where there's nobody
        # else to talk to). Toggle button always built (harmless if
        # unused); drawn/clickable only when self._network_role is set
        # — see draw()/handle_event(). Own size intentionally left
        # fixed (out of scope for this pass — see the docs) but its X
        # position is anchored off the real (now-scaled) Pause button
        # rect rather than a hardcoded 210, so it can never end up
        # overlapping Menu/Pause at resolutions where those are bigger.
        # Original hardcoded position was x=210, i.e. a 10px gap after
        # Pause's right edge at 200 — a different (larger) gap than the
        # 6px between Menu and Pause themselves. Own scaled constant so
        # baseline output matches exactly, not menu_pause_gap's 6px.
        chat_gap = round(10 * chrome_scale)
        self._btn_chat_toggle = Button(
            pygame.Rect(self._btn_pause.rect.right + chat_gap, menu_margin, 90, 34), "Chat", font_sm,
            color=(70, 60, 100), hover_color=(95, 82, 130),
            on_click=self._action_toggle_chat)
        self._chat_scale = chrome_scale  # _draw_chat reads this to scale its own geometry to match
        cs = chrome_scale
        panel_w, panel_h = round(300 * cs), round(300 * cs)
        panel_x, panel_y = round(14 * cs), round(58 * cs)
        self._chat_panel_rect = pygame.Rect(panel_x, panel_y, panel_w, panel_h)
        self._chat_input_rect = pygame.Rect(round(24 * cs), panel_y + panel_h - round(78 * cs),
                                            round(190 * cs), round(34 * cs))
        self._chat_send_btn = Button(
            pygame.Rect(self._chat_input_rect.right + round(6 * cs), self._chat_input_rect.y,
                       round(70 * cs), round(34 * cs)), "Send", font_sm,
            color=(60, 100, 60), hover_color=(80, 130, 80),
            on_click=self._action_send_chat)
        # Six one-tap reactions -- covers "chat AND emojis" without a
        # full picker grid; anyone can still type any emoji their own
        # keyboard/IME supports directly into the text field above (it
        # may or may not render depending on what's actually in their
        # OS's own emoji font — see below). These are drawn as small
        # vector icons (rendering.widgets.draw_icon's 'thumbs_up',
        # 'face_laugh', 'face_wow', 'heart', 'face_angry', 'star'
        # kinds) rather than actual emoji characters, for the exact
        # same reason this file already draws suit symbols, the
        # kickback/jump icons, etc. as shapes instead of Unicode
        # glyphs: this project's body font (Poppins) has ZERO emoji
        # glyph coverage — pygame loads that exact .ttf file directly
        # with no OS emoji-font fallback the way a web browser would,
        # so an actual emoji character renders as an empty tofu box on
        # every platform, not just some. Each button's icon kind/color
        # and the reaction text it actually sends over chat are stored
        # on the Button itself (reaction_kind/reaction_color/reaction_text)
        # for _draw_chat to use — the button's own on-screen text stays
        # empty.
        self._chat_emoji_btns: List[Button] = []
        ex = round(24 * cs)
        ey = self._chat_panel_rect.bottom - round(36 * cs)
        for text, (kind, color) in self.REACTION_ICONS.items():
            btn = Button(pygame.Rect(ex, ey, round(40 * cs), round(32 * cs)), "", font_sm,
                        color=(50, 50, 70), hover_color=(70, 70, 95),
                        on_click=lambda text=text: self._action_send_chat_emoji(text))
            btn.reaction_kind = kind
            btn.reaction_color = color
            self._chat_emoji_btns.append(btn)
            ex += round(44 * cs)

        # Sound-effects / music toggles now live in the shared
        # AudioControls widget (drawn by SceneManager on every screen),
        # same as minimize/maximize/close live in WindowControls — so
        # nothing scene-local is needed here anymore.

        # KADI window — big centred buttons shown after each play
        kw_y = sh // 2 + 60
        kadi_w, kadi_h = round(190 * chrome_scale), round(58 * chrome_scale)
        kadi_gap = round(20 * chrome_scale)
        self._btn_kadi_yes = Button(
            pygame.Rect(sw // 2 - kadi_gap - kadi_w, kw_y, kadi_w, kadi_h), "Declare KADI!", font_lg,
            color=(160,20,20), hover_color=(210,40,40),
            on_click=self._action_kadi_yes)
        self._btn_kadi_no = Button(
            pygame.Rect(sw // 2 + kadi_gap, kw_y, kadi_w, kadi_h), "Skip", font_lg,
            color=(50,70,50), hover_color=(70,100,70),
            on_click=self._action_kadi_no)

        # Undo — lets the player back out of their just-played card or
        # voluntary draw (while the POST_PLAY/KADI-check window is still
        # open) and choose a different move instead. Only ever undoes the
        # single most recent action; not available after a forced pick-up
        # draw, since that's a mandatory penalty rather than a choice.
        self._btn_undo = Button(
            pygame.Rect(0, 0, round(192 * chrome_scale), round(36 * chrome_scale)), "Undo", font_sm,
            color=(80, 60, 20), hover_color=(110, 85, 30),
            on_click=self._action_undo)

        # Exit-confirmation dialog — shown when Menu/ESC is used mid-game
        # so a player can save progress before leaving instead of losing
        # it outright. Rects are positioned in draw() once sw/sh are on
        # hand; placeholders here so handle_event() has something to
        # check against even before the first draw() call.
        font_md = font  # font_scaled('ui_medium', chrome_scale), same as above
        self._btn_exit_save = Button(
            pygame.Rect(0, 0, round(220 * chrome_scale), round(46 * chrome_scale)), "Save & Exit", font_md,
            color=(40, 120, 60), hover_color=(60, 150, 80),
            on_click=self._action_exit_save)
        self._btn_exit_discard = Button(
            pygame.Rect(0, 0, round(220 * chrome_scale), round(46 * chrome_scale)), "Discard & Exit", font_md,
            color=(120, 40, 40), hover_color=(160, 60, 60),
            on_click=self._action_exit_discard)
        self._btn_exit_cancel = Button(
            pygame.Rect(0, 0, round(220 * chrome_scale), round(40 * chrome_scale)), "Cancel", font_sm,
            color=(60, 60, 70), hover_color=(85, 85, 100),
            on_click=self._action_exit_cancel)

        # AI Spectator Mode speed control — only shown/clickable once
        # gm.is_ai_spectator_mode is True (see draw()/handle_event()).
        # Rects are re-positioned each frame in draw() next to the
        # spectator banner, same pattern as the exit-confirm buttons.
        self._btn_spec_slower = Button(
            pygame.Rect(0, 0, 34, 30), "", font_sm,
            color=(50, 50, 80), hover_color=(75, 75, 115),
            on_click=lambda: self.gm.cycle_ai_spectator_speed(-1))
        self._btn_spec_faster = Button(
            pygame.Rect(0, 0, 34, 30), "", font_sm,
            color=(50, 50, 80), hover_color=(75, 75, 115),
            on_click=lambda: self.gm.cycle_ai_spectator_speed(1))

        # AI game-speed control — same idea and same speed ladder as the
        # spectator one above, but usable any time during ordinary play,
        # not just the end-of-round AI-only stretch (see gm.ai_game_speed).
        # Tucked into a bottom-left corner badge that expands into the
        # full [-] speed [+] row only on mouse hover (see
        # _game_speed_hover_rect / draw()) so it stays out of the way
        # the rest of the time instead of permanently occupying table
        # space the way the always-visible spectator banner does.
        self._btn_game_speed_slower = Button(
            pygame.Rect(0, 0, 30, 26), "", font_sm,
            color=(50, 50, 80), hover_color=(75, 75, 115),
            on_click=lambda: self.gm.cycle_ai_game_speed(-1))
        self._btn_game_speed_faster = Button(
            pygame.Rect(0, 0, 30, 26), "", font_sm,
            color=(50, 50, 80), hover_color=(75, 75, 115),
            on_click=lambda: self.gm.cycle_ai_game_speed(1))
        self._game_speed_hover_rect = pygame.Rect(0, 0, 0, 0)  # set each draw()
        self._game_speed_expanded = False

        font_help_title = font_lg
        font_help_head = font
        font_help_body = font_sm
        # Splice the drag-to-reorder illustration into the "Arranging
        # multi-card plays" section — built here rather than as a class-
        # level constant since loading a pygame.Surface needs the
        # display already initialized (see _load_help_image's docstring).
        help_sections = [(heading, list(paras)) for heading, paras in self.HELP_SECTIONS]
        drag_img = _load_help_image('help_drag_multicard.png')
        if drag_img is not None:
            for i, (heading, paras) in enumerate(help_sections):
                if heading == "Arranging multi-card plays":
                    paras.append(('image', drag_img,
                                  "Example: dragging a card to group it with same-rank cards "
                                  "already in hand, ready to play together."))
                    help_sections[i] = (heading, paras)
                    break
        self._help = HelpOverlay("Gameplay — Quick Guide", help_sections,
                                 font_help_title, font_help_head, font_help_body)
        self._help_btn = make_help_button(pygame.Rect(0, 0, 1, 1), font_sm,
                                          on_click=self._help.open)

    def _layout_help_btn(self, sw: int, sh: int):
        # Same anchoring as the other two help buttons — immediately
        # left of the shared sfx/music icon cluster, so it stays in a
        # consistent spot across every screen that has one.
        ac = getattr(self.manager, 'audio_controls', None)
        cs = get_chrome_scale(sw, sh)
        sz = round(32 * cs)
        if ac is not None and ac._btn_sfx.rect.width > 0:
            x = ac._btn_sfx.rect.left - round(6 * cs) - sz
            y = ac._btn_sfx.rect.top
        else:
            x, y = sw - round(10 * cs) - sz, round(10 * cs)
        self._help_btn.rect = pygame.Rect(x, y, sz, sz)

    # ── Playable refresh ──────────────────────────────────────────────────────

    def _refresh_playable(self):
        if not self.gm.current_player.is_human:
            self._playable = set()
            return
        playable_cards = self.gm.get_playable_cards()
        self._playable = {i for i,c in enumerate(self.gm.current_player.hand.cards)
                          if c in playable_cards}

    # ── Game events ───────────────────────────────────────────────────────────

    def _on_game_event(self, event: GameEvent):
        sw, sh = self.gm.resolution
        _chrome_scale = get_chrome_scale(sw, sh)
        font = self.assets.font_scaled('ui_medium', _chrome_scale)
        if event.kind == 'turn_start':
            self._selected.clear()
            self._hovered = None
            self._refresh_playable()
            self._rebuild_suit_picker()
        elif event.kind == 'kadi_declared':
            self._kadi_banner = KADIBanner(event.player.name, sw, sh,
                                            self.assets.font_scaled('kadi_banner', _chrome_scale), font)
            self.assets.play_sound('kadi_declare')
        elif event.kind == 'cards_played':
            if event.effect_text: self._add_message(event.effect_text, GOLD_LIGHT)
            self.assets.play_sound('play_card')
            self._refresh_playable()
        elif event.kind == 'card_drawn':
            self.assets.play_sound('draw_card')
            self._refresh_playable()
        elif event.kind == 'pickup_drawn':
            self._add_message(f"{event.player.name} picks up {event.count}!", (220,80,80))
            self.assets.play_sound('pickup')
            self._refresh_playable()
        elif event.kind == 'invalid_play':
            self._add_message(f"Invalid: {event.reason}", (220,80,80), duration=1.5)
            self.assets.play_sound('error')
        elif event.kind == 'invalid_kadi':
            msg = getattr(event, 'reason', None)
            self._add_message(f"Not KADI! {msg}" if msg else "Can't declare KADI yet!",
                              (220,80,80), duration=1.8)
            self.assets.play_sound('error')
        elif event.kind == 'kadi_penalty':
            self._add_message(f"{event.player.name} finished without KADI! +2 cards", (220,80,80))
        elif event.kind == 'suit_pick_required':
            # event.player (network-decoded via network/event_codec.py's
            # generic Player<->player_id mapping) is whoever must choose
            # — in a multi-human LAN/Internet game that's not necessarily
            # ME, and showing this modal on every connected screen at
            # once would let anyone try to pick the suit for someone
            # else's play. The server/host would silently ignore an
            # unauthorized intent_choose_suit anyway, but the modal
            # should never even appear on the wrong screen to begin with.
            if event.player is self._my_player():
                self._suit_picker.show()
        elif event.kind == 'kadi_blocked_by_cardless':
            names = ', '.join(p.name for p in event.blocked_by)
            self._add_message(f"KADI blocked — {names} is cardless!", (220, 140, 50), duration=3.0)
        elif event.kind == 'jump_counter_open':
            self._add_message(f"{event.counter_player.name} can counter the Jump with a J!",
                              (255,140,0))
        elif event.kind == 'jump_counter_next':
            self._add_message(f"{event.player.name} can counter the Jump with a J!",
                              (255,140,0))
        elif event.kind == 'jump_countered':
            self._add_message(f"{event.player.name} countered the Jump!", (255,140,0))
            self.assets.play_sound('counter')
        elif event.kind == 'jump_counter_voided_bundle':
            cards_str = " ".join(c.display_ascii for c in event.cards)
            self._add_message(f"Countered! {event.player.name} gets back: {cards_str}",
                              (255,140,0), duration=3.0)
        elif event.kind == 'player_finished':
            place = event.place
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(place, 'th')
            self._add_message(f"{event.player.name} finishes {place}{suffix}!",
                              GOLD_LIGHT, duration=3.0)
            self.assets.play_sound('win')
        elif event.kind == 'player_disconnected_removed':
            self._add_message(f"{event.player.name} was disconnected too long and left the match",
                              (220, 120, 80), duration=4.0)
        elif event.kind == 'game_over':
            self._show_win_screen(event.winner)
        elif event.kind == 'turn_skipped':
            self._add_message(f"{event.player.name}'s turn skipped!", LIGHT_GRAY, duration=1.2)
        elif event.kind == 'kadi_cancelled':
            self._add_message("KADI cancelled — play freely", (200, 140, 50), duration=2.0)
        elif event.kind == 'stall_resolved':
            self._add_message("Game stalled — resolved by finishing cards!", (220,140,40), duration=3.0)
        elif event.kind == 'game_paused':
            pass
        elif event.kind == 'game_resumed':
            pass
        elif event.kind == 'turn_timer_expired':
            self._add_message(f"{event.player.name}'s time ran out!", (200,100,50), duration=1.5)
        elif event.kind == 'post_play_open':
            pass  # mini strip drawn in draw()
        elif event.kind == 'post_play_expired':
            pass  # silently proceed
        elif event.kind == 'question_no_answer':
            self._add_message("Question unanswered — drew 1 card!", (220, 140, 50), duration=2.5)
        elif event.kind == 'player_cardless':
            self._add_message(f"{event.player.name} is cardless — draws next turn", (180, 180, 80), duration=2.5)
        elif event.kind == 'cardless_draw':
            card = event.card
            msg = f"Drew {card} — {'KADI eligible!' if card.is_finishing else 'play next turn'}"
            self._add_message(msg, GOLD_LIGHT if card.is_finishing else (*WHITE, 200), duration=2.5)
            self.assets.play_sound('draw_card')
            self._refresh_playable()

    def _rebuild_suit_picker(self):
        sw, sh = self.gm.resolution
        self._suit_picker = SuitPicker(sw, sh,
                                       self.assets.font_scaled('ui_medium', get_chrome_scale(sw, sh)),
                                       on_pick=self._on_suit_picked,
                                       scale=get_chrome_scale(sw, sh))

    def _add_message(self, text, color=GOLD_LIGHT, duration=2.0):
        sw, sh = self.gm.resolution
        _chrome_scale = get_chrome_scale(sw, sh)
        y = round(80 * _chrome_scale) + len(self._messages) * round(36 * _chrome_scale)
        # Cap to avoid going off screen
        y = min(y, sh - round(120 * _chrome_scale))
        banner = MessageBanner(text, color, duration,
                               self.assets.font_scaled('ui_medium', _chrome_scale), y=y)
        self._messages.append(banner)
        return banner

    # ── Chat (LAN / Internet only — see _build_buttons's chat widgets) ──────
    def _chat_log(self) -> list:
        if self._network_role == 'host' and self._host_game is not None:
            return self._host_game.chat_log
        if self._network_role == 'client' and self._client_gm is not None:
            return self._client_gm.chat_log
        return []

    def _action_toggle_chat(self):
        self._chat_open = not self._chat_open
        if self._chat_open:
            self._chat_seen_count = len(self._chat_log())
        else:
            self._chat_input_active = False

    def _dispatch_chat(self, text: str):
        text = text.strip()
        if not text:
            return
        if self._network_role == 'host' and self._host_game is not None:
            self._host_game.send_chat(text)
        elif self._network_role == 'client' and self._client_gm is not None:
            self._client_gm.send_chat(text)
        self._chat_seen_count = len(self._chat_log())

    def _action_send_chat(self):
        self._dispatch_chat(self._chat_input_text)
        self._chat_input_text = ""

    def _action_send_chat_emoji(self, emoji: str):
        self._dispatch_chat(emoji)

    def _draw_chat(self, surf: pygame.Surface):
        cs = self._chat_scale
        font_sm = self.assets.font_scaled('ui_normal', cs)
        font_tiny = self.assets.font_scaled('ui_tiny', cs)

        # Toggle button + an unread-count badge when new messages have
        # arrived while the panel was closed.
        self._btn_chat_toggle.draw(surf)
        unread = len(self._chat_log()) - self._chat_seen_count
        if not self._chat_open and unread > 0:
            bx = self._btn_chat_toggle.rect.right - round(10 * cs)
            by = self._btn_chat_toggle.rect.top - round(4 * cs)
            pygame.draw.circle(surf, (200, 50, 50), (bx, by), round(10 * cs))
            n = font_tiny.render(str(min(unread, 9)), True, WHITE)
            surf.blit(n, (bx - n.get_width() // 2, by - n.get_height() // 2))

        if not self._chat_open:
            return

        panel = self._chat_panel_rect
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, (15, 20, 30, 225), bg.get_rect(), border_radius=round(10 * cs))
        pygame.draw.rect(bg, (*GOLD_LIGHT, 160), bg.get_rect(), width=2, border_radius=round(10 * cs))
        surf.blit(bg, panel.topleft)

        # Messages — most recent at the bottom, directly above the
        # input row, same reading direction as any chat app. A message
        # whose text is exactly one of the quick-reactions (see
        # REACTION_ICONS) renders as that same icon here too, on every
        # participant's screen — not just plain "Grr" text — so a
        # reaction actually reads as a reaction wherever it shows up.
        log = self._chat_log()
        visible = log[-7:]
        y = panel.bottom - round(122 * cs)
        for entry in reversed(visible):
            prefix = f"{entry.get('from', '?')}: "
            text = entry.get('text', '')
            ps = font_sm.render(prefix, True, (225, 225, 230))
            surf.blit(ps, (panel.x + round(10 * cs), y))
            reaction = self.REACTION_ICONS.get(text)
            if reaction is not None:
                kind, color = reaction
                icon_rect = pygame.Rect(panel.x + round(10 * cs) + ps.get_width() + round(2 * cs),
                                        y - round(3 * cs), round(22 * cs), round(22 * cs))
                draw_icon(surf, icon_rect, kind, color=color, width=2)
            else:
                ts = font_sm.render(text[:50], True, (225, 225, 230))
                surf.blit(ts, (panel.x + round(10 * cs) + ps.get_width(), y))
            y -= round(24 * cs)
            if y < panel.y + round(8 * cs):
                break

        # Text input + Send
        bc = GOLD_LIGHT if self._chat_input_active else (*WHITE, 120)
        pygame.draw.rect(surf, (30, 40, 55), self._chat_input_rect, border_radius=round(6 * cs))
        pygame.draw.rect(surf, bc, self._chat_input_rect, width=2, border_radius=round(6 * cs))
        if self._chat_input_text:
            vs = font_sm.render(self._chat_input_text[-26:], True, WHITE)
            surf.blit(vs, (self._chat_input_rect.x + round(8 * cs), self._chat_input_rect.y + round(7 * cs)))
        elif not self._chat_input_active:
            ps = font_sm.render("Say something…", True, (*WHITE, 90))
            surf.blit(ps, (self._chat_input_rect.x + round(8 * cs), self._chat_input_rect.y + round(7 * cs)))
        self._chat_send_btn.draw(surf)

        for btn in self._chat_emoji_btns:
            btn.draw(surf)
            draw_icon(surf, btn.rect.inflate(-14, -10), btn.reaction_kind,
                     color=btn.reaction_color, width=2)

    def _record_profile_stats(self):
        """Update the attached profile's stats/badges exactly once for
        this game (guarded both here via _profile_stats_done and inside
        GameManager.finalize_profile_stats via game_id, belt-and-braces
        since a network client can receive the game_over event more than
        once across reconnects). Pops a MessageBanner toast (reusing the
        existing pattern — see _add_message) for each newly earned badge.

        BUGFIX (crash report): when self._network_role == 'client' (a
        LAN joiner, or ANY Internet Multiplayer participant — see the
        mode-detection just below for why those two differ), self.gm is
        a network.client_state.ClientGameManager, which has no .profile
        attribute AT ALL (not even None) — the old
        `if self.gm.profile is None: return` guard assumed the
        attribute always at least existed, and crashed with
        AttributeError instead of skipping gracefully. The real local
        profile in that case lives on self.manager.singleplayer_gm (the
        same stable reference on_exit() restores manager.gm from — see
        also the identical pattern in _ads_showing's own comment).
        Routes to profile_store.record_basic_network_result instead of
        the full finalize_profile_stats for clients — see that
        function's docstring for why full badge-checking isn't
        possible there."""
        if self._profile_stats_done:
            return
        self._profile_stats_done = True

        if self._network_role == 'client':
            local_gm = getattr(self.manager, 'singleplayer_gm', None)
            profile = getattr(local_gm, 'profile', None)
            if profile is None:
                return
            mode = 'internet' if self._is_internet else 'lan'
            my_player = self.gm.players[0] if self.gm.players else None
            won = bool(my_player is not None and self.gm.winner is my_player)
            profile_store.record_basic_network_result(profile, mode, won)
            return

        if self.gm.profile is None:
            return

        if self._network_role:
            # network_role == 'host': self.gm IS the real GameManager
            # (see on_enter's own comment on network_role) — full path.
            mode = 'internet' if self._is_internet else 'lan'
            my_player = self.gm.players[0] if self.gm.players else None
            difficulty = None
        else:
            human_players = self._human_players()
            my_player = human_players[0] if human_players else None
            if len(human_players) > 1:
                mode = 'hot_seat'
                difficulty = None
            else:
                mode = 'single_player_elimination' if self.gm.elimination_mode else 'single_player'
                ai_players = [p for p in self.gm.players if not p.is_human]
                difficulty = ai_players[0].difficulty.name if ai_players else 'MEDIUM'

        newly = self.gm.finalize_profile_stats(mode=mode, difficulty=difficulty, my_player=my_player)
        for badge_id in newly:
            name = profile_store.BADGE_DEFS.get(badge_id, {}).get('name', badge_id)
            self._add_message(f"Badge earned: {name}!", (255, 215, 60), duration=3.5)

    def _show_win_screen(self, winner):
        self._record_profile_stats()
        self.assets.play_sound('win')
        sw, sh = self.gm.resolution
        standings = []
        # Only single-player has one unambiguous "you" — local hot-seat
        # has several humans sharing this one screen (no single "you"
        # to point at), and LAN/Internet already show each connected
        # player their own name plainly, so this is scoped to exactly
        # the one case a screenshot flagged: a solo player's own
        # placement getting lost in a list of AI names they don't
        # otherwise call out.
        human_players = [p for p in self.gm.players if p.is_human]
        my_seat = human_players[0] if (not self._network_role and len(human_players) == 1) else None
        if self.gm.elimination_mode and self.gm.finish_order:
            for i, p in enumerate(self.gm.finish_order, start=1):
                tag = " (last)" if i == len(self.gm.finish_order) else ""
                if p is my_seat:
                    tag += "  (You)"
                standings.append(f"{i}. {p.name}{tag}")
        _ui_scale = get_ui_scale(sw, sh)
        self._win_screen = WinScreen(winner.name, sw, sh,
                                     self.assets.font_scaled('kadi_banner', _ui_scale['font_scale']),
                                     self.assets.font_scaled('ui_large', _ui_scale['font_scale']),
                                     self.assets.font_scaled('ui_medium', _ui_scale['font_scale']),
                                     standings=standings,
                                     scale=_ui_scale['button_scale'])
        self._win_screen.setup_buttons(
            self.assets.font_scaled('ui_medium', _ui_scale['font_scale']),
            on_play_again=self._play_again,
            on_menu=lambda: self.manager.switch('main_menu'),
            on_share=self._on_share_win)

    def _play_again(self):
        if self._network_role:
            # Renegotiating a fresh LAN lobby isn't in scope here — see
            # network/README.md. Route to the menu like any other exit
            # (on_exit() handles stopping the host/closing the client).
            self.manager.switch('main_menu')
            return
        configs = [{'name': p.name, 'is_human': p.is_human,
                    'difficulty': getattr(p,'difficulty', AIDifficulty.MEDIUM)}
                   for p in self.gm.players]
        self.on_enter(player_configs=configs, elimination_mode=self.gm.elimination_mode,
                      elimination_ai_only_continue=self.gm.elimination_ai_only_continue)

    def _share_mode_label(self) -> str:
        """Human-readable mode name for the win-share card's stat line
        — same mode taxonomy _record_profile_stats already uses, just
        formatted for display rather than as a profile_store key."""
        if self._network_role:
            return "Internet Multiplayer" if self._is_internet else "LAN Multiplayer"
        human_players = self._human_players()
        if len(human_players) > 1:
            return "Hot-seat"
        return "Elimination Mode" if self.gm.elimination_mode else "Single-Player"

    def _on_share_win(self, platform_key: str):
        """Part C: render + save a shareable PNG for the just-finished
        win, then open a pre-filled share-compose window on the chosen
        platform. See core/social_share.py and rendering/share_card.py."""
        if self._win_screen is None:
            return
        winner_name = self._win_screen.winner_name
        mode_label = self._share_mode_label()
        card = share_card.render_win_share_card(
            winner_name, mode_label,
            self.assets.font('kadi_banner'), self.assets.font('ui_large'),
            self.assets.font('ui_medium'), self.assets.font('ui_small'))
        status = _save_and_share_card(
            card, f"kadi_win_{_slugify(winner_name)}", platform_key,
            social_share.build_win_share_text(winner_name, mode_label))
        self._win_screen.share_status = status

    def _on_suit_picked(self, suit: Suit):
        self.gm.human_choose_suit(suit)
        self._refresh_playable()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_play(self):
        if self._pending_reveal_target is not None:
            return
        if not self._selected:
            self._add_message("Select card(s) first!", (*WHITE,200), duration=1.2)
            return
        if self.gm.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return
        if self.gm.current_player is not self._my_player():
            # Not actually my turn (a different human's, in a multi-
            # human LAN/Internet game) — the UI-level gating in draw()/
            # handle_event() already keeps this unreachable by click,
            # but guard here too rather than indexing self._selected
            # into a hand that isn't mine.
            return
        cards = [self.gm.current_player.hand.cards[i] for i in sorted(self._selected)]
        self.gm.human_play(cards)
        self._selected.clear()
        self._refresh_playable()

    def _action_draw(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm.state not in (GameState.PLAYING, GameState.KADI_DECLARED):
            return
        if self.gm.current_player is not self._my_player():
            return
        self.gm.human_draw()
        self._selected.clear()
        self._refresh_playable()

    def _action_declare_kadi(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm.current_player is not self._my_player():
            return
        self.gm.human_declare_kadi()

    def _action_clear(self):
        self._selected.clear()

    def _action_counter(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm.state != GameState.JUMP_COUNTER_WINDOW:
            return
        from constants import CardType
        cp = self.gm.players[self.gm.counter_player_idx]
        if not cp.is_human or cp is not self._my_player():
            return

        # Player must select a J card from their hand to counter
        if not self._selected:
            self._add_message("Select one or more J cards to counter!", (220,140,50), duration=1.8)
            return

        selected_cards = [cp.hand.cards[i] for i in sorted(self._selected)
                          if i < len(cp.hand.cards)]
        j_cards = [c for c in selected_cards if c.card_type == CardType.JUMP]

        if not j_cards:
            self._add_message("Only J cards can counter!", (220,80,80), duration=1.5)
            self._selected.clear()
            return

        success = self.gm.human_counter(j_cards)
        if success:
            self._selected.clear()
            self._refresh_playable()
        else:
            self._add_message("Cannot counter now", (220,80,80), duration=1.2)

    def _action_toggle_pause(self):
        self.gm.toggle_pause()
        self._btn_pause.text = "Resume" if self.gm.is_paused else "Pause"

    def _action_minimize(self):
        try:
            import pygame
            pygame.display.iconify()
        except Exception:
            pass

    def _action_kadi_yes(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm._post_play_player is not self._my_player():
            return
        self.gm.human_post_play_declare_kadi()

    def _action_kadi_no(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm._post_play_player is not self._my_player():
            return
        self.gm.human_post_play_proceed()

    def _action_undo(self):
        if self.gm.human_undo_last_action():
            self._selected = set()
            self._hovered = None
            self._refresh_playable()
            self._add_message("Move undone — choose again", (220, 180, 80), duration=1.8)

    def _action_menu_clicked(self):
        # Pressing Menu/ESC again while the dialog is already up cancels
        # it, rather than doing nothing or re-showing it.
        if self._exit_confirm_pending:
            self._action_exit_cancel()
            return
        # A LAN match isn't something save_manager's single-player save
        # slot can represent (no real Deck/game_id round-trips a network
        # client's mirror, and "resuming" a LAN game later makes no sense
        # once everyone's disconnected) — leave straight away; on_exit()
        # handles stopping the host / closing the client connection.
        if self._network_role:
            self.manager.switch('main_menu')
            return
        # Nothing meaningful to save once the round's over, or mid a
        # transient decision (suit pick / jump-counter window) that
        # save_manager deliberately won't serialize — just leave.
        if self._win_screen or not save_manager.can_save(self.gm):
            self.manager.switch('main_menu')
            return
        self._exit_confirm_pending = True
        # Freeze the game (timers, AI) behind the dialog by reusing the
        # existing pause mechanism — but only actually pause if it wasn't
        # already paused, and only resume it on Cancel if we're the ones
        # who paused it.
        self._exit_confirm_auto_paused = not self.gm.is_paused
        if self._exit_confirm_auto_paused:
            self.gm.toggle_pause()

    def _action_exit_save(self):
        save_manager.save_game(self.gm)
        self._exit_confirm_pending = False
        self.manager.switch('main_menu')

    def _action_exit_discard(self):
        save_manager.delete_save_file()
        self._exit_confirm_pending = False
        self.manager.switch('main_menu')

    def _action_exit_cancel(self):
        self._exit_confirm_pending = False
        if getattr(self, '_exit_confirm_auto_paused', False):
            self.gm.toggle_pause()
        self._exit_confirm_auto_paused = False

    def _action_pass_counter(self):
        if self._pending_reveal_target is not None:
            return
        if self.gm.state != GameState.JUMP_COUNTER_WINDOW:
            return
        cp = self.gm.players[self.gm.counter_player_idx]
        if cp is not self._my_player():
            return
        self.gm.human_pass_counter()

    # ── Events ────────────────────────────────────────────────────────────────

    def handle_event(self, event: pygame.event.Event):
        if self._pending_reveal_target is not None:
            # Local hot-seat handoff in progress — nothing else on this
            # scene (buttons, hand, menu) should be reachable until the
            # incoming player has explicitly confirmed the device was
            # passed to them. See PassAndPlayOverlay/_hotseat_reveal.
            self._pass_overlay.handle_event(event)
            return

        sw, sh = self.gm.resolution
        self._help.notice_activity()
        if self._help.handle_event(event, sw, sh):
            return
        self._help_btn.handle_event(event)

        if self.gm.is_ai_spectator_mode:
            if self._btn_spec_slower.handle_event(event):
                return
            if self._btn_spec_faster.handle_event(event):
                return

        # Only clickable while actually expanded (mouse hovering the
        # badge/panel area) — see draw(). While collapsed the buttons
        # sit at a zero-size rect from _build_buttons() and simply can't
        # be hit, but the explicit guard keeps that invariant obvious
        # here rather than relying on rect geometry alone.
        if self._game_speed_expanded:
            if self._btn_game_speed_slower.handle_event(event):
                return
            if self._btn_game_speed_faster.handle_event(event):
                return

        if self._win_screen:
            self._win_screen.handle_event(event)
            return
        if self._suit_picker.handle_event(event):
            return

        is_counter_window = (self.gm.state == GameState.JUMP_COUNTER_WINDOW)
        if is_counter_window:
            active_player = self.gm.players[self.gm.counter_player_idx]
        else:
            active_player = self.gm.current_player
        # NOT just "is a human deciding" — in a multi-human LAN/Internet
        # game that's true on EVERY connected player's screen at once
        # whenever ANY human's turn/counter window is active. This must
        # additionally be MY OWN decision (see _my_player's docstring)
        # for the corresponding buttons to actually respond to clicks.
        is_human = active_player.is_human and active_player is self._my_player()
        self._btn_menu.handle_event(event)
        self._btn_pause.handle_event(event)

        if self._network_role:
            self._btn_chat_toggle.handle_event(event)
            if self._chat_open:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._chat_input_active = self._chat_input_rect.collidepoint(event.pos)
                elif event.type == pygame.KEYDOWN and self._chat_input_active:
                    if event.key == pygame.K_RETURN:
                        self._action_send_chat()
                    elif event.key == pygame.K_BACKSPACE:
                        self._chat_input_text = self._chat_input_text[:-1]
                    elif len(self._chat_input_text) < 200 and event.unicode.isprintable():
                        self._chat_input_text += event.unicode
                self._chat_send_btn.handle_event(event)
                for btn in self._chat_emoji_btns:
                    btn.handle_event(event)
                # Swallow any click that lands inside the open panel so
                # it doesn't also select/deselect a card or hit whatever
                # sits behind it on the table.
                if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)
                        and self._chat_panel_rect.collidepoint(event.pos)):
                    return

        # ESC/P toggles pause during gameplay — but not while the chat
        # input has focus (typing a word with a "p" in it shouldn't
        # also pause the game out from under a multiplayer match).
        if (event.type == pygame.KEYDOWN and event.key == pygame.K_p
                and not self._chat_input_active):
            self._action_toggle_pause()

        # Exit-confirm dialog (Menu/ESC mid-game) — takes priority over
        # the generic pause-click handling below, since showing this
        # dialog auto-pauses the game.
        if self._exit_confirm_pending:
            self._btn_exit_save.handle_event(event)
            self._btn_exit_discard.handle_event(event)
            self._btn_exit_cancel.handle_event(event)
            return

        # If paused, only allow resume / minimize clicks
        if self.gm.is_paused:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if hasattr(self, '_pause_resume_rect') and \
                        self._pause_resume_rect.collidepoint(event.pos):
                    self._action_toggle_pause()
                elif hasattr(self, '_pause_minimize_rect') and \
                        self._pause_minimize_rect.collidepoint(event.pos):
                    self._action_minimize()
                elif getattr(self, '_pause_undo_refill_rect', None) and \
                        self._pause_undo_refill_rect.collidepoint(event.pos):
                    self._action_undo_refill()
            return

        # ── KADI window ───────────────────────────────────────────────────────
        if self.gm.state == GameState.POST_PLAY:
            if self.gm._post_play_player is not self._my_player():
                # Someone else's post-play decision (a different human,
                # in a multi-human LAN/Internet game, or an AI's) — don't
                # route clicks to these buttons at all, so they can't
                # visually respond or fire for the wrong viewer. The
                # turn-indicator banner (_draw_turn_indicator) already
                # tells every viewer whose decision this is.
                return
            self._btn_kadi_yes.handle_event(event)
            self._btn_kadi_no.handle_event(event)
            if self.gm.undo_available:
                self._btn_undo.handle_event(event)
            return

        # ── Counter window ────────────────────────────────────────────────────
        if is_counter_window:
            if not is_human:
                # Not my decision (either an AI's window, or another
                # human player's, in a multi-human LAN/Internet game) —
                # don't even route the click to these buttons, so they
                # can't visually "press" or fire for the wrong viewer.
                return
            self._btn_counter.handle_event(event)
            self._btn_pass_counter.handle_event(event)
            # fall through so the human can still click/select a J in hand

        if is_human and self.gm.state in (GameState.PLAYING, GameState.KADI_DECLARED):
            self._btn_play.handle_event(event)
            self._btn_draw.handle_event(event)
            self._btn_kadi.handle_event(event)
            self._btn_clear.handle_event(event)

        layout = self.board.get_layout()
        active_idx = (self.gm.counter_player_idx if is_counter_window
                     else self.gm.current_player_idx)
        human_slot = self._hotseat_layout_slot(active_idx)
        human_layout = (layout[human_slot] if layout and 0 <= human_slot < len(layout)
                       else None)

        # ── Mouse button down ─────────────────────────────────────────────────
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not is_counter_window and self.board.draw_pile_rect().collidepoint(event.pos):
                self._action_draw()
                return
            if human_layout and is_human:
                idx = self.board.get_human_card_at(
                    event.pos[0], event.pos[1],
                    active_player, human_layout)
                if idx is not None:
                    # Start tracking for potential drag or click
                    self._drag_start_pos  = event.pos
                    self._drag_pending_idx = idx
                    self.assets.play_sound('button_click')

        # ── Mouse move — drag in progress ─────────────────────────────────────
        elif event.type == pygame.MOUSEMOTION:
            if human_layout and is_human:
                # Update hover
                self._hovered = self.board.get_human_card_at(
                    event.pos[0], event.pos[1],
                    active_player, human_layout)

                # Check if drag should start
                if (self._drag_start_pos is not None
                        and self._drag_idx is None
                        and hasattr(self, '_drag_pending_idx')):
                    dx = event.pos[0] - self._drag_start_pos[0]
                    dy = event.pos[1] - self._drag_start_pos[1]
                    if abs(dx) > self._drag_threshold or abs(dy) > self._drag_threshold:
                        self._drag_idx    = self._drag_pending_idx
                        self._drag_pos    = event.pos
                        self._drag_target = self._drag_idx
                        # Remove from selection if dragged
                        self._selected.discard(self._drag_idx)

                # Update drag position and target slot
                if self._drag_idx is not None:
                    self._drag_pos    = event.pos
                    self._drag_target = self.board.get_human_drop_index(
                        event.pos[0], active_player, human_layout)

        # ── Mouse button up ───────────────────────────────────────────────────
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if self._drag_idx is not None and self._drag_target is not None:
                # Complete the reorder
                if self._drag_idx != self._drag_target:
                    self._reorder_hand(self._drag_idx, self._drag_target)
                    self._selected.clear()
                    self._refresh_playable()
                self._drag_idx    = None
                self._drag_pos    = None
                self._drag_target = None
                self._drag_start_pos = None
            elif (self._drag_start_pos is not None
                  and hasattr(self, '_drag_pending_idx')
                  and self._drag_pending_idx is not None):
                # It was a click not a drag — toggle selection
                idx = self._drag_pending_idx
                if idx in self._selected:
                    self._selected.discard(idx)
                else:
                    self._selected.add(idx)
                self._drag_start_pos = None
                self._drag_pending_idx = None
            else:
                self._drag_start_pos = None

    def _my_player(self):
        """The player object representing whoever currently owns the
        active decision on THIS screen, if that's a human — else None.

        For a LAN host's own live GameManager, the host is always seated
        at 0 (see network/host_game.HostGame.start_game); and
        network.client_state.ClientGameManager rotates its mirrored
        `players` list so the local connection is always at index 0
        regardless of its real server-assigned seat. So `players[0]`
        reliably means "me" in either of those network cases — this is
        what several action-gating checks below use to make sure a
        decision that belongs to a DIFFERENT human player (whose
        turn/counter/post-play choice it actually is, in a multi-human
        LAN/Internet game) doesn't render as an active, clickable prompt
        on every OTHER player's screen too. Before this, e.g. the
        POST_PLAY "Yes! KADI / Proceed" panel and the Jump counter
        buttons were gated only on the game's global state, which is
        shared/identical for every connected client — so they lit up
        for everyone simultaneously, not just whoever the decision
        actually belonged to.

        For a LOCAL (non-networked) game — single-player OR local
        hot-seat, sharing one device — there's no per-client isolation
        to worry about; "me" instead means whoever's turn/counter/
        post-play decision it currently is, if that seat is human.
        In single-player this is always the same seat-0 human whenever
        a human decision is pending, identical to the old hardcoded
        behavior. In local hot-seat with multiple humans sharing one
        device, this is what lets the Play/Draw/Counter/KADI buttons
        (and _visible_player's hand-hiding, below) respond to whichever
        human's decision it actually is, instead of being stuck on seat
        0 forever — which is the reason Local Multiplayer only ever
        worked for the first player before this."""
        if self._network_role:
            return self.gm.players[0] if self.gm.players else None
        if not self.gm.players:
            return None
        if self.gm.state == GameState.POST_PLAY:
            p = self.gm._post_play_player
        elif self.gm.state == GameState.JUMP_COUNTER_WINDOW:
            idx = self.gm.counter_player_idx
            p = self.gm.players[idx] if 0 <= idx < len(self.gm.players) else None
        elif self.gm.state in (GameState.PLAYING, GameState.KADI_DECLARED,
                               GameState.SUIT_PICK):
            p = self.gm.current_player
        else:
            # No live decision pending right now (menus, paused, game
            # over, ...) — nobody currently "owns" anything.
            return None
        return p if (p is not None and p.is_human) else None

    def _human_players(self):
        return [p for p in self.gm.players if p.is_human]

    def _is_local_hotseat(self) -> bool:
        """True for a same-device game with 2+ human players sharing one
        screen (Local Multiplayer) — as opposed to single-player (only
        one human, nothing to hide from) or LAN/Internet (network
        isolation already gives each human their own screen, so none of
        the Pass-and-Play machinery below applies)."""
        return not self._network_role and len(self._human_players()) >= 2

    def _visible_player(self):
        """Which player's hand (if any) should render face-up and
        interactive on THIS screen right now.

        Single-player and network games always show the same identity —
        seat 0 (see _my_player's docstring: single-player's own human, or
        the network client's locally-rotated seat) — regardless of whose
        turn it is; there's no privacy concern in showing your own hand
        while an AI (or, over the network, someone else entirely) is
        deciding something.

        Local hot-seat instead only shows whichever human has actually
        clicked through the Pass-and-Play interstitial for the CURRENT
        decision (self._revealed_player). The instant the decision moves
        to an AI or to a different human, this returns None until the
        new handoff is acknowledged — so a hand is never left visible
        once it's no longer that player's turn/decision, even if nobody
        else's decision is pending yet (e.g. an AI is still "thinking")."""
        if not self._is_local_hotseat():
            return self.gm.players[0] if self.gm.players else None
        target = self._my_player()
        if target is not None and target is self._revealed_player:
            return self._revealed_player
        return None

    def _hotseat_layout_slot(self, player_idx: int) -> int:
        """Screen layout slot (table position) to draw/hit-test the
        given player index's hand at.

        Outside local hot-seat this is always identity — single-player
        and network games already guarantee the human/local player sits
        at seat 0, matching the one screen position (layout[0]) that's
        drawn face-up-sized and that card-click hit-testing uses.

        In local hot-seat, whichever human is currently revealed
        (self._revealed_player) is rotated to that same seat-0 position
        regardless of which seat they actually occupy in the game, so
        their hand always renders — and is clickable — in the familiar
        bottom spot no matter whose turn it is; everyone else keeps
        their relative seating order around the table, just rotated to
        start after the revealed player."""
        n = len(self.gm.players)
        if n <= 0 or not self._is_local_hotseat() or self._revealed_player is None:
            return player_idx
        try:
            r = self.gm.players.index(self._revealed_player)
        except ValueError:
            return player_idx
        return (player_idx - r) % n

    def _hotseat_reveal(self):
        """Callback for the Pass-and-Play overlay's reveal button:
        confirms the pending handoff and un-pauses if we're the ones
        who paused for it."""
        if self._pending_reveal_target is None:
            return
        self._revealed_player = self._pending_reveal_target
        self._pending_reveal_target = None
        if self._hotseat_auto_paused:
            self.gm.toggle_pause()
            self._hotseat_auto_paused = False
        # A fresh reveal is a fresh hand — nothing selected/hovered/
        # mid-drag should carry over from whoever had the device before.
        self._selected = set()
        self._hovered = None
        self._drag_idx = None
        self._drag_pos = None
        self._drag_target = None
        self._drag_start_pos = None
        if hasattr(self, '_drag_pending_idx'):
            self._drag_pending_idx = None

    def _reorder_hand(self, from_idx: int, to_idx: int):
        """Move card at from_idx to to_idx in the active player's hand."""
        # Network games (network.client_state.ClientGameManager) only

        # ever render/drag OUR OWN hand, and — unlike local play —
        # get a full fresh hand pushed down from the host on every
        # single state_sync snapshot, which would otherwise stomp a
        # plain in-place list reorder before the next frame even
        # draws. ClientGameManager.reorder_hand() also remembers the
        # new order so it survives that next snapshot.
        if hasattr(self.gm, 'reorder_hand'):
            self.gm.reorder_hand(from_idx, to_idx)
            return
        active_player = (self.gm.players[self.gm.counter_player_idx]
                          if self.gm.state == GameState.JUMP_COUNTER_WINDOW
                          else self.gm.current_player)
        cards = active_player.hand._cards
        card = cards.pop(from_idx)
        cards.insert(to_idx, card)

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, dt: float):
        sw, sh = self.gm.resolution
        self._layout_help_btn(sw, sh)
        # Idle-glow should only count time where the player could
        # actually be doing something and isn't — not time spent
        # waiting on the AI, which is normal and not "stuck." See
        # HelpOverlay.notice_activity()'s docstring for the general
        # mechanism; this is GameplayScene's one deviation from the
        # "always call update_idle_glow every frame" pattern the other
        # help-enabled scenes use.
        if self.gm.current_player.is_human and not self.gm.is_paused:
            self._help.update_idle_glow(dt)
        else:
            self._help.notice_activity()
        self._help_btn.update(dt, pygame.mouse.get_pos())

        # Local hot-seat: detect a NEW human decision (a different human
        # than whoever's currently revealed) and freeze the game behind
        # the Pass-and-Play interstitial until it's acknowledged. Only
        # even looked at when nothing's already pending and the game
        # isn't already paused for some other reason (manual pause,
        # exit-confirm dialog) — in either of those cases current_player/
        # post_play/counter aren't meaningfully changing anyway.
        if (self._is_local_hotseat() and self._pending_reveal_target is None
                and not self.gm.is_paused):
            target = self._my_player()
            if target is not None and target is not self._revealed_player:
                self._pending_reveal_target = target
                self._hotseat_auto_paused = True
                self.gm.toggle_pause()
                self._selected = set()
                self._hovered = None
                self._drag_idx = None
                self._drag_pos = None
                self._drag_target = None
                self._drag_start_pos = None
                if hasattr(self, '_drag_pending_idx'):
                    self._drag_pending_idx = None
                self._pass_overlay.setup(target.name, self._hotseat_reveal)
        if self._pending_reveal_target is not None:
            self._pass_overlay.update(dt, pygame.mouse.get_pos())

        # AI Spectator Mode: nobody's left to control, so this stretch of
        # play is scaled by the person's chosen watch speed. Only the
        # actual game/animation simulation is scaled — UI chrome (message
        # fade timers, button hover, etc.) stays on real time below so
        # the controls themselves don't feel sluggish at 0.25x. Outside
        # spectator mode, ai_game_speed does the same job for ordinary
        # AI turns (their "thinking" pause and post-play delay) — its
        # own separate dial, same speed ladder.
        sim_dt = dt
        if self.gm.is_ai_spectator_mode:
            sim_dt = dt * self.gm.ai_spectator_speed
        elif not self.gm.current_player.is_human and self.gm.ai_game_speed != 1.0:
            sim_dt = dt * self.gm.ai_game_speed
        self.gm.update(sim_dt)
        if self._host_game is not None:
            # Drains queued client intents (validating and applying them
            # to this SAME self.gm the line above just ticked) and
            # broadcasts the resulting state to every connected client.
            # Does NOT call gm.update() again — see HostGame.network_tick's
            # docstring for why that would double-tick every timer.
            self._host_game.network_tick()
        if self._network_role == 'client' and self._client_gm is not None:
            # A dropped connection triggers ClientGameManager's own
            # background auto-reconnect (see network/client_state.py) —
            # this just surfaces that as an on-screen banner rather
            # than leaving the person staring at a frozen table with no
            # explanation. 'lost' means the background retries gave up
            # (grace window elapsed, or this client had no reconnect_info
            # to try with) — the seat's genuinely gone at that point, so
            # there's nothing left to do here but head back to the menu.
            status = self._client_gm.connection_status
            if status != getattr(self, '_last_conn_status', 'ok'):
                if status == 'reconnecting':
                    self._reconnect_banner = self._add_message(
                        "Connection lost — reconnecting…", (220, 160, 60), duration=999.0)
                elif status == 'ok' and getattr(self, '_reconnect_banner', None) is not None:
                    self._reconnect_banner.done = True
                    self._reconnect_banner = None
                    self._add_message("Reconnected!", (120, 200, 120), duration=2.5)
                elif status == 'lost':
                    if getattr(self, '_reconnect_banner', None) is not None:
                        self._reconnect_banner.done = True
                        self._reconnect_banner = None
                    self._client_gm.client.close()
                    self.manager.switch('main_menu')
                    return
                self._last_conn_status = status
        self.anim.update(sim_dt)

        self._messages = [m for m in self._messages if not m.done]
        for m in self._messages:
            m.update(dt)

        if self._kadi_banner:
            self._kadi_banner.update(dt)
            if self._kadi_banner.done:
                self._kadi_banner = None

        if self._win_screen:
            self._win_screen.update(dt, pygame.mouse.get_pos())

        mp = pygame.mouse.get_pos()
        for btn in [self._btn_play, self._btn_draw, self._btn_kadi,
                    self._btn_clear, self._btn_menu, self._btn_pause,
                    self._btn_counter, self._btn_pass_counter,
                    self._btn_kadi_yes, self._btn_kadi_no, self._btn_undo,
                    self._btn_exit_save, self._btn_exit_discard, self._btn_exit_cancel,
                    self._btn_spec_slower, self._btn_spec_faster,
                    self._btn_game_speed_slower, self._btn_game_speed_faster]:
            btn.update(dt, mp)

        # Expanded state persists as long as the mouse is anywhere over
        # the last-drawn hover zone (badge OR the expanded panel it
        # grows into) — computed fresh in draw() each frame from the
        # actual rects just drawn, so hovering the buttons themselves
        # never causes the panel to collapse out from under the cursor.
        self._game_speed_expanded = self._game_speed_hover_rect.collidepoint(mp)

    # ── Draw ──────────────────────────────────────────────────────────────────

    def draw(self, surf: pygame.Surface):
        sw, sh = self.gm.resolution

        if self._pending_reveal_target is not None:
            # Local hot-seat handoff in progress — draw ONLY the fully
            # opaque interstitial. Nothing else this frame: not the
            # table, not any hand, not even briefly during a transition
            # animation (see PassAndPlayOverlay's docstring).
            self._pass_overlay.draw(surf)
            return

        self.board.draw_table(surf, top_margin=self._ad_top_pad())
        self.board.draw_piles(surf,
            self.gm.deck.top_card if self.gm.deck else None,
            self.gm.deck.draw_count if self.gm.deck else 0,
            self.gm.rule_engine.current_suit)
        self.board.draw_direction_indicator(surf, self.gm.direction)

        # Player hands & info
        layout = self.board.get_layout()
        visible_player = self._visible_player()
        hint_idx = None
        hint_suggest_draw = False
        if self.gm.hint_should_show and visible_player is not None:
            hint_card = self.gm.get_hint_card()
            if hint_card is not None:
                human_hand = visible_player.hand.cards
                if hint_card in human_hand:
                    hint_idx = human_hand.index(hint_card)
            else:
                # Nothing playable right now — the "not very smart" hint
                # still has one useful thing to say: there's no legal
                # play, so drawing is the move. Highlighted on the Draw
                # Card button below instead of a card in hand.
                hint_suggest_draw = True
        spectator = self.gm.is_ai_spectator_mode
        hotseat = self._is_local_hotseat()
        for i, player in enumerate(self.gm.players):
            slot = self._hotseat_layout_slot(i)
            if slot >= len(layout): break
            lay = layout[slot]
            is_cur  = (i == self.gm.current_player_idx)
            is_kadi = player.has_declared_kadi
            is_me = (player is visible_player)
            sel  = self._selected if is_me else set()
            play = self._playable  if is_me and is_cur else set()
            hov  = self._hovered   if is_me else None
            # Drag params only for whoever's hand is actually visible
            di  = self._drag_idx    if is_me else None
            dp  = self._drag_pos    if is_me else None
            dt2 = self._drag_target if is_me else None
            hi  = hint_idx if is_me else None
            if spectator:
                rev_override = True
            elif hotseat:
                # Explicit True/False (not None) — in hot-seat this
                # overrides the seat-position-based "seat 0 is face up"
                # default, which would otherwise show/hide the wrong
                # player's cards whenever the revealed human isn't
                # literally sitting in seat 0.
                rev_override = is_me
            else:
                rev_override = None
            self.board.draw_hand(surf, player, lay, sel, play, hov, is_cur,
                                 drag_idx=di, drag_pos=dp, drag_target=dt2,
                                 hint_idx=hi,
                                 reveal_override=rev_override)
            self.board.draw_player_info(surf, player, lay, is_cur, is_kadi, player.score)

        # Drawn AFTER every hand/info panel (not before, as it used to
        # be) so the "Pick up: +N" badge always paints on top of any
        # seat's fanned-out cards instead of getting covered by them —
        # matches the "must pick N!" banner below, which was already
        # drawn post-hands for the same reason.
        self.board.draw_pickup_indicator(surf, self.gm.pickup_pending_display)

        # Animations
        for ac in self.anim.get_active_anims():
            cs = self.assets.get_card_surface(ac.card, ac.face_up)
            if ac.scale != 1.0:
                cs = pygame.transform.smoothscale(cs, (int(CARD_W*ac.scale), int(CARD_H*ac.scale)))
            cs = cs.copy(); cs.set_alpha(ac.alpha)
            surf.blit(cs, (int(ac.pos[0]), int(ac.pos[1])))

        my_player = self._my_player()
        # NOT just "a human's turn" — in a multi-human LAN/Internet game
        # that's true on every connected player's screen simultaneously
        # whenever ANY human is current. Must additionally be MY turn
        # (see _my_player's docstring) for these buttons to draw as
        # active/clickable here at all.
        is_human_turn = (self.gm.current_player is my_player and
                         self.gm.state in (GameState.PLAYING, GameState.KADI_DECLARED))
        is_counter    = (self.gm.state == GameState.JUMP_COUNTER_WINDOW)

        # Action buttons
        if is_human_turn and not self._win_screen:
            has_sel = bool(self._selected)
            sel_playable = bool(self._playable & self._selected)
            self._btn_play.enabled  = has_sel and sel_playable
            self._btn_kadi.enabled  = not self.gm.current_player.has_declared_kadi
            self._btn_clear.enabled = has_sel
            if hint_suggest_draw:
                self._draw_button_hint_glow(surf, self._btn_draw.rect)
            self._btn_play.draw(surf)
            self._btn_draw.draw(surf)
            self._btn_kadi.draw(surf)
            self._btn_clear.draw(surf)

            # Show selection summary
            if has_sel:
                self._draw_selection_summary(surf)

        if is_counter and not self._win_screen:
            cp = self.gm.players[self.gm.counter_player_idx]
            # Same "is this actually mine" restriction as everywhere
            # else — a DIFFERENT human's counter window (multi-human
            # LAN/Internet) must not draw as an active prompt here.
            if cp.is_human and cp is my_player:
                t_left  = self.gm.counter_window_secs - self.gm.counter_timer
                max_cw  = self.gm.counter_window_secs
                self._draw_timer_bar(surf, t_left, max_cw,
                                     self._btn_counter.rect.top - 40, (200,140,0),
                                     f"Counter window: {t_left:.1f}s")
                self._btn_counter.draw(surf)
                self._btn_pass_counter.draw(surf)

        self._btn_menu.draw(surf)
        self._btn_pause.draw(surf)
        # Sound-effects/music toggles are drawn on top of every scene by
        # the shared AudioControls widget (see SceneManager.draw()), same
        # as minimize/maximize/close via WindowControls — nothing to draw
        # here.

        if self._network_role:
            self._draw_chat(surf)

        # Turn timer bar
        if (is_human_turn and self.gm.timers_enabled
                and self.gm._turn_timer_active and not self._win_screen):
            max_t = self.gm.turn_timer_secs
            t = self.gm.turn_timer
            color = (200,50,50) if t < max_t*0.25 else (200,160,0) if t < max_t*0.5 else (50,180,80)
            label = f"Timer: {t:.1f}s"
            self._draw_timer_bar(surf, t, max_t, sh - 58, color, label)

        # Messages
        for msg in self._messages:
            msg.draw(surf)

        if self._kadi_banner:
            self._kadi_banner.draw(surf)
        self._suit_picker.draw(surf)

        # Non-intrusive KADI mini-checker (always visible beside hand)
        if not self._win_screen and not self.gm.is_paused:
            self._draw_kadi_mini(surf)

        if self._win_screen:
            self._win_screen.draw(surf)

        self._draw_turn_indicator(surf)

        if spectator:
            self._draw_spectator_banner(surf)
        else:
            self._draw_game_speed_badge(surf)

        if not self.gm.current_player.is_human:
            self._draw_thinking(surf)

        # Pause overlay — always on top
        if self.gm.is_paused:
            self._draw_pause_overlay(surf)
            # Sound-effects/music toggles don't need a redraw here — the
            # shared AudioControls widget is drawn by SceneManager after
            # this whole scene (pause overlay included), same as
            # WindowControls, so it's already always on top regardless of
            # pause state.

        if self._exit_confirm_pending:
            self._draw_exit_confirm(surf)

        self._help.draw_button_glow(surf, self._help_btn.rect)
        self._help_btn.draw(surf)
        self._help.draw(surf)

    def _draw_exit_confirm(self, surf: pygame.Surface):
        sw, sh = self.gm.resolution
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(overlay, (0, 0))

        chrome_scale = get_chrome_scale(sw, sh)
        pw, ph = round(420 * chrome_scale), round(300 * chrome_scale)
        panel = pygame.Rect(sw//2 - pw//2, sh//2 - ph//2, pw, ph)
        Panel(panel, color=(20, 42, 28)).draw(surf)

        font_md = self.assets.font_scaled('ui_medium', chrome_scale)
        font_sm = self.assets.font_scaled('ui_normal', chrome_scale)
        title = font_md.render("Leave the game?", True, GOLD_LIGHT)
        surf.blit(title, (panel.centerx - title.get_width()//2, panel.y + round(20 * chrome_scale)))
        msg_lines = ["Save your progress to continue later,",
                    "or discard it and return to the menu."]
        my = panel.y + round(20 * chrome_scale) + title.get_height() + round(10 * chrome_scale)
        for line in msg_lines:
            ls = font_sm.render(line, True, (215, 220, 210))
            surf.blit(ls, (panel.centerx - ls.get_width()//2, my))
            my += ls.get_height() + round(2 * chrome_scale)

        by = panel.y + round(130 * chrome_scale)
        row_gap = round(54 * chrome_scale)
        self._btn_exit_save.rect.topleft    = (panel.centerx - self._btn_exit_save.rect.width // 2, by)
        self._btn_exit_discard.rect.topleft = (panel.centerx - self._btn_exit_discard.rect.width // 2, by + row_gap)
        self._btn_exit_cancel.rect.topleft  = (panel.centerx - self._btn_exit_cancel.rect.width // 2, by + 2 * row_gap)
        self._btn_exit_save.draw(surf)
        self._btn_exit_discard.draw(surf)
        self._btn_exit_cancel.draw(surf)

    def _draw_button_hint_glow(self, surf: pygame.Surface, rect: pygame.Rect):
        """Same glow-and-blink treatment as the card hint highlight (see
        HandRenderer.render's hint_idx handling), sized for a button
        instead of a card. Used to point at Draw Card when nothing in
        hand is currently playable — the hint system's other useful
        suggestion besides 'play this card'."""
        phase = (pygame.time.get_ticks() % 1100) / 1100.0
        pulse = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
        hint_col = (255, 215, 40)

        for pad, base_a in ((14, 40), (9, 60), (5, 90)):
            glow_rect = pygame.Rect(rect.x - pad, rect.y - pad,
                                    rect.width + pad * 2, rect.height + pad * 2)
            glow_surf = pygame.Surface(glow_rect.size, pygame.SRCALPHA)
            a = int(base_a * (0.5 + 0.5 * pulse))
            pygame.draw.rect(glow_surf, (*hint_col, a), glow_surf.get_rect(),
                             border_radius=10 + pad)
            surf.blit(glow_surf, glow_rect.topleft)

        alpha = int(90 + 165 * pulse)
        ring_rect = rect.inflate(10, 10)
        ring_surf = pygame.Surface(ring_rect.size, pygame.SRCALPHA)
        pygame.draw.rect(ring_surf, (*hint_col, alpha), ring_surf.get_rect(),
                         width=4, border_radius=13)
        surf.blit(ring_surf, ring_rect.topleft)

    def _draw_selection_summary(self, surf: pygame.Surface):
        """Show which cards are currently selected above the action buttons."""
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        cards = [self.gm.current_player.hand.cards[i] for i in sorted(self._selected)]
        font  = self.assets.font_scaled('ui_small', cs)
        prefix = font.render("Selected: ", True, GOLD_LIGHT)
        cards_surf = render_cards_inline(font, cards, GOLD_LIGHT)

        total_h = max(prefix.get_height(), cards_surf.get_height())
        s = pygame.Surface((prefix.get_width() + cards_surf.get_width(), total_h), pygame.SRCALPHA)
        s.blit(prefix, (0, (total_h - prefix.get_height()) // 2))
        s.blit(cards_surf, (prefix.get_width(), (total_h - cards_surf.get_height()) // 2))

        bx = sw - s.get_width() - round(180 * cs)
        bg = pygame.Surface((s.get_width() + round(16 * cs), s.get_height() + round(6 * cs)), pygame.SRCALPHA)
        pygame.draw.rect(bg, (0, 0, 0, 160), bg.get_rect(), border_radius=round(6 * cs))
        bby = self._btn_kadi.rect.y - s.get_height() - round(14 * cs)
        surf.blit(bg, (bx - round(8 * cs), bby))
        surf.blit(s,  (bx, bby + round(3 * cs)))

    def _draw_kadi_mini(self, surf: pygame.Surface):
        """
        Post-play chess-clock panel next to human hand. Only draws
        when there's actually a post-play decision open — either mine
        (full panel: KADI/Proceed/Undo buttons) or someone else's
        ("Waiting on <name>..."). Draws nothing the rest of the time —
        it used to always render, showing a bare, button-less
        "Waiting..." box during ordinary play with nothing open for
        anyone, which conveyed nothing (see this method's own comment
        on the early-return for why).
        """
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        font_sm = self.assets.font_scaled('ui_normal', cs)
        font_xs = self.assets.font_scaled('ui_tiny', cs)

        layout = self.board.get_layout()
        if not layout:
            return

        hcx = layout[0]['hand_cx']
        hcy = layout[0]['hand_cy']

        pw, ph = round(210 * cs), round(148 * cs)
        show_undo = self.gm.undo_available
        row_h = round(44 * cs)
        if show_undo:
            ph += row_h
        px = min(int(hcx + 270 * cs), sw - pw - 10)
        py = int(hcy - ph // 2)
        py = max(sh - ph - 90, min(py, sh - ph - 10))

        # ACTIVE only when the current POST_PLAY decision is actually
        # MINE — not just "someone is in POST_PLAY somewhere," which in
        # a multi-human LAN/Internet game is true on every connected
        # player's screen simultaneously whenever ANY human just played.
        # See _my_player's docstring.
        human = self._visible_player()
        is_active = (self.gm.state == GameState.POST_PLAY
                    and self.gm._post_play_player is human)
        # Someone ELSE'S post-play window is open right now — worth a
        # word so this panel doesn't just look randomly inert; who it's
        # naming comes straight off the (network-synced) game state.
        waiting_on = (self.gm._post_play_player.name
                     if (self.gm.state == GameState.POST_PLAY and not is_active
                         and self.gm._post_play_player is not None)
                     else None)

        # Nothing to show — no post-play decision is mine to make, and
        # nobody else's is open either, so there's nothing this panel
        # could tell the player beyond an inert "Waiting..." with no
        # name and no button under it. Previously this still drew the
        # full translucent panel + that bare "Waiting..." label during
        # ordinary play (i.e. most of the time), which just sat there
        # doing nothing — see waitingBoxNotUseful.png. Skipping the
        # draw entirely here is the fix; "Waiting on <name>..." below
        # (an actually useful case) and the full active panel are both
        # unaffected.
        if not is_active and waiting_on is None:
            return

        # Always compute KADI eligibility
        if is_active:
            can_kadi = self.gm._post_play_can_kadi
        else:
            can_kadi = False

        # Panel background
        if is_active:
            bg_col = (15, 55, 20, 245)
            border = (*GOLD, 230)
        else:
            bg_col = (18, 28, 20, 100)
            border = (*LIGHT_GRAY, 35)

        panel = pygame.Surface((pw, ph), pygame.SRCALPHA)
        pygame.draw.rect(panel, bg_col, panel.get_rect(), border_radius=12)
        pygame.draw.rect(panel, border, panel.get_rect(), width=2, border_radius=12)
        surf.blit(panel, (px, py))

        # Title
        if is_active:
            title_col = GOLD_LIGHT if can_kadi else (*WHITE, 230)
            title_txt = "KADI eligible!" if can_kadi else "Next Player"
        elif waiting_on:
            title_col = (*LIGHT_GRAY, 110)
            title_txt = f"Waiting on {waiting_on}..."
        else:
            title_col = (*LIGHT_GRAY, 75)
            title_txt = "Waiting..."
        t = font_xs.render(title_txt, True, title_col)
        surf.blit(t, (px + pw//2 - t.get_width()//2, py + round(7 * cs)))

        # Timer bar when active
        bar_bottom = py + round(26 * cs)
        if is_active and self.gm.timers_enabled and self.gm.post_play_delay_secs > 0:
            max_t = self.gm.post_play_delay_secs
            rem   = max(0.0, self.gm.post_play_timer)
            ratio = rem / max_t
            bw    = pw - round(18 * cs)
            bx2   = px + round(9 * cs)
            by2   = py + round(26 * cs)
            bar_h = round(8 * cs)
            pygame.draw.rect(surf, (20,20,20), pygame.Rect(bx2, by2, bw, bar_h), border_radius=4)
            fc = (200,50,50) if ratio < 0.3 else (200,160,0) if ratio < 0.6 else (60,180,80)
            pygame.draw.rect(surf, fc, pygame.Rect(bx2, by2, int(bw*ratio), bar_h), border_radius=4)
            tl = font_xs.render(f"{rem:.1f}s", True, (*WHITE, 180))
            surf.blit(tl, (px + pw//2 - tl.get_width()//2, by2 + round(10 * cs)))
            bar_bottom = by2 + round(24 * cs)

        if not is_active:
            return

        # KADI button — ALWAYS shown in full active style (red), every play
        kadi_y = bar_bottom + round(4 * cs)
        kadi_r = pygame.Rect(px + round(9 * cs), kadi_y, pw - round(18 * cs), round(36 * cs))
        self._btn_kadi_yes.rect = kadi_r
        pygame.draw.rect(surf, (160, 20, 20), kadi_r, border_radius=7)
        pygame.draw.rect(surf, (*GOLD_LIGHT, 200), kadi_r, width=1, border_radius=7)
        ks = font_sm.render("Yes! KADI", True, WHITE)
        surf.blit(ks, (kadi_r.centerx - ks.get_width()//2,
                       kadi_r.centery - ks.get_height()//2))

        # Proceed button
        proc_y = kadi_y + row_h - round(2 * cs)
        proc_r = pygame.Rect(px + round(9 * cs), proc_y, pw - round(18 * cs), round(36 * cs))
        self._btn_kadi_no.rect = proc_r
        pygame.draw.rect(surf, (30, 70, 38), proc_r, border_radius=7)
        pygame.draw.rect(surf, (*WHITE, 80), proc_r, width=1, border_radius=7)
        ps = font_sm.render("Proceed", True, WHITE)
        surf.blit(ps, (proc_r.centerx - ps.get_width()//2,
                       proc_r.centery - ps.get_height()//2))

        # Undo button — only present when this exact play/draw can still
        # be reverted (see GameManager.undo_available).
        if show_undo:
            undo_y = proc_y + row_h - round(2 * cs)
            undo_r = pygame.Rect(px + round(9 * cs), undo_y, pw - round(18 * cs), round(36 * cs))
            self._btn_undo.rect = undo_r
            # Token-gated (Part 3): grey out rather than letting a click
            # fail silently or crash — human_undo_last_action() also
            # re-checks this itself, but the button should visually
            # reflect it before the click even happens.
            tokens_ok = self.gm.undo_tokens_available
            self._btn_undo.enabled = tokens_ok
            btn_col = (80, 60, 20) if tokens_ok else (55, 55, 55)
            border_col = (*GOLD_LIGHT, 140) if tokens_ok else (*WHITE, 40)
            text_col = WHITE if tokens_ok else (*LIGHT_GRAY, 130)
            pygame.draw.rect(surf, btn_col, undo_r, border_radius=7)
            pygame.draw.rect(surf, border_col, undo_r, width=1, border_radius=7)
            label = "Undo"
            if self.gm.profile is not None:
                label = f"Undo ({self.gm.profile.get('undo_tokens', 0)})"
            us = font_sm.render(label, True, text_col)
            surf.blit(us, (undo_r.centerx - us.get_width()//2,
                           undo_r.centery - us.get_height()//2))

    def _draw_pause_overlay(self, surf: pygame.Surface):
        """Full-screen pause overlay."""
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, OVERLAY_ALPHA))
        surf.blit(overlay, (0, 0))

        font_xl = self.assets.font_scaled('kadi_banner', cs)
        font_md = self.assets.font_scaled('ui_medium', cs)
        font_sm = self.assets.font_scaled('ui_normal', cs)

        pause_txt = font_xl.render("PAUSED", True, GOLD_LIGHT)
        surf.blit(pause_txt, (sw//2 - pause_txt.get_width()//2,
                               sh//2 - pause_txt.get_height()//2 - round(20 * cs)))

        hint = font_sm.render("Press P or click Resume to continue", True, (*WHITE, 200))
        surf.blit(hint, (sw//2 - hint.get_width()//2,
                          sh//2 + pause_txt.get_height()//2))

        # Draw resume button in pause overlay too
        rw, rh = round(200 * cs), round(50 * cs)
        rx, ry = sw//2 - rw//2, sh//2 + pause_txt.get_height()//2 + round(40 * cs)
        r_rect = pygame.Rect(rx, ry, rw, rh)
        pygame.draw.rect(surf, (50, 130, 60), r_rect, border_radius=round(10 * cs))
        pygame.draw.rect(surf, (*GOLD_LIGHT, 180), r_rect, width=2, border_radius=round(10 * cs))
        rs = font_md.render("Resume", True, WHITE)
        surf.blit(rs, (r_rect.centerx - rs.get_width()//2,
                        r_rect.centery - rs.get_height()//2))
        # Store for click detection
        self._pause_resume_rect = r_rect

        # Explicit Minimize button right in the pause panel — players
        # pausing specifically to step away no longer have to hunt for the
        # small top-right window icon under the dark overlay.
        mw, mh = round(200 * cs), round(44 * cs)
        mx, my = sw//2 - mw//2, r_rect.bottom + round(14 * cs)
        m_rect = pygame.Rect(mx, my, mw, mh)
        pygame.draw.rect(surf, (50, 50, 80), m_rect, border_radius=round(10 * cs))
        pygame.draw.rect(surf, (*WHITE, 100), m_rect, width=1, border_radius=round(10 * cs))
        icon_sz = round(22 * cs)
        icon_rect = pygame.Rect(0, 0, icon_sz, icon_sz)
        icon_rect.center = (m_rect.left + round(30 * cs), m_rect.centery)
        draw_icon(surf, icon_rect, 'minimize', WHITE)
        ms = font_sm.render("Minimize", True, WHITE)
        surf.blit(ms, (m_rect.centerx - ms.get_width()//2 + round(10 * cs), m_rect.centery - ms.get_height()//2))
        self._pause_minimize_rect = m_rect

        # Undo token balance + "Watch to Refill" (Part 3) — HIDDEN from
        # the pause menu for now (not removed). This was a rewarded-ad
        # placeholder (see _action_undo_refill's docstring: no real ad
        # network wired in, it just granted the token directly) — with
        # no real ads anywhere in the game right now (see the "hidden ad
        # features" note near the top of main.py), a button promising to
        # "Watch to Refill" would show nothing to watch, so it's hidden
        # rather than left up as a broken-looking dead end. The token
        # balance itself, the spend/grant logic, and the profile-stat
        # tracking are all untouched — see core/game_manager.py's
        # undo_tokens_available / human_undo_last_action and this
        # scene's own _action_undo_refill (still callable, just not
        # reachable from any visible button right now).
        # self._pause_undo_refill_rect is deliberately left None below
        # (rather than set to a real rect) so the existing click-
        # handling in handle_event() naturally no-ops — same pattern
        # used to hide the Advertising Settings card. Restoring this is
        # just un-hiding this block.
        self._pause_undo_refill_rect = None

    def _action_undo_refill(self):
        """Placeholder 'Watch to Refill' button (Part 3) — no real ad
        network wired in yet, same as the banner ad slot. Just grants
        the token directly for now, capped at UNDO_TOKENS_MAX so this
        can't be stacked infinitely. TODO: once ad-network integration
        exists, gate this behind an actual rewarded-ad completion
        callback instead of granting immediately on click.

        Currently UNREACHABLE from the UI — the pause-menu block that
        used to call this via self._pause_undo_refill_rect was hidden
        (see that block's comment, just above _draw_pause_overlay's end).
        Left fully intact/callable on purpose."""
        gm = self.gm
        if gm.profile is None:
            return
        from core.profile_store import UNDO_TOKENS_MAX, save_profile
        gm.profile['undo_tokens'] = min(UNDO_TOKENS_MAX, gm.profile.get('undo_tokens', 0) + 1)
        save_profile(gm.profile)

    def _draw_timer_bar(self, surf, t_left, max_t, y, color, label):
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        bar_w = min(round(500 * cs), sw - 40)
        bar_h = round(14 * cs)
        bx = sw//2 - bar_w//2
        pygame.draw.rect(surf, (40,40,40), pygame.Rect(bx, y, bar_w, bar_h), border_radius=round(7 * cs))
        fill = max(0, int(bar_w * t_left / max(max_t, 0.001)))
        pygame.draw.rect(surf, color, pygame.Rect(bx, y, fill, bar_h), border_radius=round(7 * cs))
        pygame.draw.rect(surf, (*WHITE,60), pygame.Rect(bx, y, bar_w, bar_h), width=1, border_radius=round(7 * cs))
        lbl = self.assets.font_scaled('ui_small', cs).render(label, True, WHITE)
        surf.blit(lbl, (sw//2 - lbl.get_width()//2, y - lbl.get_height() - 2))

    def _draw_turn_indicator(self, surf: pygame.Surface):
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        player = self.gm.current_player
        font   = self.assets.font_scaled('ui_normal', cs)
        font_xs = self.assets.font_scaled('ui_tiny', cs)

        # Main turn text
        if self.gm.state == GameState.JUMP_COUNTER_WINDOW:
            cp  = self.gm.players[self.gm.counter_player_idx]
            # The discard pile only ever shows the LAST card of a
            # combo, so a play like [J♦, J♣, 2♣] — two Jumps answered
            # by a pick-up card — leaves the pile showing "2♣" with no
            # visible trace of the Jumps that actually opened this
            # counter window. The effect-text banner for that play (if
            # any) is also long gone by the time someone's actually
            # looking at this decision, especially with long counter
            # timers. Spell out what was actually played, for as long
            # as the window itself is open, not just as a fading toast.
            if self.gm.last_played_cards:
                played = " ".join(c.display_ascii for c in self.gm.last_played_cards)
                txt = f"Select J(s) to counter — {cp.name}  (played: {played})"
            else:
                txt = f"Select J(s) to counter — {cp.name}"
            col = (255, 140, 0)
        elif player.has_declared_kadi:
            txt = f"{player.name} — KADI declared!"
            col = KADI_COLOR
        else:
            txt = f"{player.name}'s turn"
            col = GOLD_LIGHT

        pad = self._ad_top_pad()
        s  = font.render(txt, True, col)
        bx = sw//2 - s.get_width()//2 - round(10 * cs)
        bg = pygame.Surface((s.get_width()+round(20 * cs), s.get_height()+round(8 * cs)), pygame.SRCALPHA)
        pygame.draw.rect(bg, (0,0,0,160), bg.get_rect(), border_radius=round(8 * cs))
        surf.blit(bg, (bx, round(10 * cs)+pad))
        surf.blit(s,  (bx+round(10 * cs), round(14 * cs)+pad))

        # Direction indicator — bottom-left corner
        from constants import PlayDirection
        dir_sym  = "Clockwise" if self.gm.direction == PlayDirection.CLOCKWISE else "Anti-clockwise"
        dir_col  = (120, 200, 120)
        ds = font_xs.render(dir_sym, True, dir_col)
        dsbg = pygame.Surface((ds.get_width()+round(14 * cs), ds.get_height()+round(6 * cs)), pygame.SRCALPHA)
        pygame.draw.rect(dsbg, (0,0,0,120), dsbg.get_rect(), border_radius=round(6 * cs))
        surf.blit(dsbg, (round(10 * cs), sh - ds.get_height() - round(34 * cs)))
        surf.blit(ds,   (round(17 * cs), sh - ds.get_height() - round(31 * cs)))

        # Pickup target name — shown in the open felt to the right of the
        # piles, mirroring BoardRenderer._draw_suit_indicator's placement
        # on the left of the piles (see that method's own comment for why
        # it was moved off-centre in the first place). This used to sit
        # dead-centre at sh//2 + a fixed offset, which landed directly on
        # top of the bottom seat's name/card-count panel that renders
        # just below the pile — see Move_Player_Pick_Details.png. Sits
        # just below pile-centre so BoardRenderer.draw_pickup_indicator's
        # "Pick up: +N" badge (just above pile-centre) never overlaps it.
        if self.gm.pickup_pending_display > 0:
            # IMPORTANT: current_player_idx only moves forward when a turn
            # actually ends (_advance_turn). While we're still in POST_PLAY
            # for the player who just played the pick-up card, current_player_idx
            # is still THEM, so the player who must respond is the *next* seat.
            # But once the turn has actually advanced to that player (regular
            # PLAYING state), current_player_idx already IS that player — adding
            # another step here would wrongly point one seat further around the
            # table. This double-advance was the cause of the wrong name showing.
            if self.gm.state == GameState.POST_PLAY:
                # Skip already-finished players (Elimination Mode) the same
                # way turn advancement does — otherwise this can name a
                # player who already won and left the game.
                step = self.gm.direction.value
                idx = self.gm._next_active_idx(self.gm.current_player_idx, step)
                target = self.gm.players[idx]
            else:
                target = player
            # Bumped from font_xs (ui_tiny, 11px) -> ui_normal (18px) ->
            # ui_medium (22px, bold) — at ui_tiny the target's name was
            # hard to read against the "Pick up: +N" badge sitting right
            # above it. ptbg below auto-sizes off pt's rendered size, so
            # the bigger box just follows along; no separate tuning needed.
            font_pt = self.assets.font_scaled('ui_medium', cs)
            pt   = font_pt.render(f"{target.name} must pick {self.gm.pickup_pending_display}!", True, (220, 80, 80))
            ptbg = pygame.Surface((pt.get_width()+round(14 * cs), pt.get_height()+round(6 * cs)), pygame.SRCALPHA)
            pygame.draw.rect(ptbg, (60,10,10,180), ptbg.get_rect(), border_radius=round(6 * cs))
            pile_rect = self.board.draw_pile_rect()
            gap = round(34 * cs)
            mid_gap = round(4 * cs)
            bx = pile_rect.right + gap
            by = pile_rect.centery + mid_gap
            surf.blit(ptbg, (bx, by))
            surf.blit(pt,   (bx + round(7 * cs), by + round(3 * cs)))

    def _draw_game_speed_badge(self, surf: pygame.Surface):
        """Bottom-left corner control for gm.ai_game_speed — same speed
        ladder and same [-] speed [+] layout as the AI Spectator Mode
        banner's watch-speed control, but for ordinary play at any
        point in the game. Collapsed to a small unobtrusive badge most
        of the time; expands into the clickable control only while the
        mouse is hovering it (see update()'s _game_speed_expanded /
        _game_speed_hover_rect tracking), instead of permanently taking
        up table space the way the always-on spectator banner does."""
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        font_sm = self.assets.font_scaled('ui_small', cs)
        speed = self.gm.ai_game_speed
        margin_x = round(14 * cs)
        # Sits directly above the "Clockwise/Anti-clockwise" direction
        # label (which lives right at the bottom-left corner, ~34-50px
        # up from the edge) with a clear gap, and — like the action
        # panel's margin fix — well clear of the strip that can get
        # cropped after a minimize/restore on some platforms.
        bottom_offset = round(60 * cs)

        if not self._game_speed_expanded:
            label = f"AI speed {speed:g}x"
            txt = font_sm.render(label, True, (210, 210, 220))
            pad_x, pad_y = round(10 * cs), round(6 * cs)
            w, h = txt.get_width() + pad_x * 2, txt.get_height() + pad_y * 2
            rect = pygame.Rect(margin_x, sh - h - bottom_offset, w, h)

            bg = pygame.Surface(rect.size, pygame.SRCALPHA)
            pygame.draw.rect(bg, (0, 0, 0, 90), bg.get_rect(), border_radius=round(8 * cs))
            surf.blit(bg, rect.topleft)
            surf.blit(txt, (rect.x + pad_x, rect.y + pad_y))

            self._game_speed_hover_rect = rect
            # Parked at zero size while collapsed so a stray click can't
            # hit them even if handle_event's expanded-guard were ever
            # bypassed.
            self._btn_game_speed_slower.rect = pygame.Rect(0, 0, 0, 0)
            self._btn_game_speed_faster.rect = pygame.Rect(0, 0, 0, 0)
            return

        speed_str = f"{speed:g}x"
        sp_txt = font_sm.render(f"AI speed: {speed_str}", True, WHITE)
        btn_w, btn_h, gap = round(30 * cs), round(26 * cs), round(8 * cs)
        pad_x, pad_y = round(10 * cs), round(7 * cs)
        total_w = btn_w + gap + sp_txt.get_width() + gap + btn_w
        panel = pygame.Rect(margin_x, sh - (btn_h + pad_y * 2) - bottom_offset,
                            total_w + pad_x * 2, btn_h + pad_y * 2)

        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, (30, 30, 45, 215), bg.get_rect(), border_radius=round(8 * cs))
        pygame.draw.rect(bg, (120, 120, 160, 160), bg.get_rect(), width=1, border_radius=round(8 * cs))
        surf.blit(bg, panel.topleft)

        bx, by = panel.x + pad_x, panel.y + pad_y
        self._btn_game_speed_slower.rect = pygame.Rect(bx, by, btn_w, btn_h)
        self._btn_game_speed_slower.enabled = speed > self.gm.SPECTATOR_SPEEDS[0] + 1e-6
        self._btn_game_speed_slower.draw(surf)
        draw_icon(surf, self._btn_game_speed_slower.rect, 'minus', WHITE)

        surf.blit(sp_txt, (bx + btn_w + gap, by + btn_h // 2 - sp_txt.get_height() // 2))

        faster_x = bx + btn_w + gap + sp_txt.get_width() + gap
        self._btn_game_speed_faster.rect = pygame.Rect(faster_x, by, btn_w, btn_h)
        self._btn_game_speed_faster.enabled = speed < self.gm.SPECTATOR_SPEEDS[-1] - 1e-6
        self._btn_game_speed_faster.draw(surf)
        draw_icon(surf, self._btn_game_speed_faster.rect, 'plus', WHITE)

        # A little bigger than the panel itself so moving the mouse from
        # the original badge corner toward the buttons never briefly
        # falls outside the hover zone and collapses the panel mid-move.
        self._game_speed_hover_rect = panel.inflate(16, 16)

    def _draw_spectator_banner(self, surf: pygame.Surface):
        """AI Spectator Mode banner + watch-speed control, shown once
        every human has finished in Elimination Mode and only AIs are
        still playing the round out (see gm.is_ai_spectator_mode). Sits
        just below the normal turn indicator so both stay readable.
        Also doubles as good screen real-estate for a future ad slot —
        the longer someone stays to watch the AIs finish, the more of
        that space gets seen, without interrupting actual play."""
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        font    = self.assets.font_scaled('ui_normal', cs)
        font_sm = self.assets.font_scaled('ui_small', cs)

        label = "AI SPECTATOR MODE — all players are out, watching it play out"
        txt = font.render(label, True, (255, 210, 90))
        pad_x, pad_y = round(16 * cs), round(6 * cs)
        icon_w = round(26 * cs)
        panel_w = icon_w + round(8 * cs) + txt.get_width() + pad_x * 2
        panel_h = txt.get_height() + pad_y * 2
        px = sw // 2 - panel_w // 2
        py = round(48 * cs) + self._ad_top_pad()
        panel = pygame.Rect(px, py, panel_w, panel_h)

        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        pygame.draw.rect(bg, (70, 45, 0, 190), bg.get_rect(), border_radius=round(8 * cs))
        pygame.draw.rect(bg, (255, 210, 90, 140), bg.get_rect(), width=1, border_radius=round(8 * cs))
        surf.blit(bg, panel.topleft)

        icon_rect = pygame.Rect(px + pad_x, panel.centery - icon_w // 2, icon_w, icon_w)
        draw_icon(surf, icon_rect, 'double_arrow', (255, 210, 90))
        surf.blit(txt, (icon_rect.right + round(8 * cs), panel.centery - txt.get_height() // 2))

        # Watch-speed control, directly under the banner: [ - ]  1.0x  [ + ]
        speed = self.gm.ai_spectator_speed
        speed_str = f"{speed:g}x"
        sp_txt = font_sm.render(f"Watch speed: {speed_str}", True, WHITE)
        sp_y = panel.bottom + round(8 * cs)
        btn_w, btn_h = round(34 * cs), round(30 * cs)
        gap = round(8 * cs)
        total_w = btn_w + gap + sp_txt.get_width() + gap + btn_w
        sp_x = sw // 2 - total_w // 2

        sp_bg = pygame.Surface((total_w + round(20 * cs), btn_h + round(8 * cs)), pygame.SRCALPHA)
        pygame.draw.rect(sp_bg, (0, 0, 0, 150), sp_bg.get_rect(), border_radius=round(8 * cs))
        surf.blit(sp_bg, (sp_x - round(10 * cs), sp_y - round(4 * cs)))

        self._btn_spec_slower.rect = pygame.Rect(sp_x, sp_y, btn_w, btn_h)
        self._btn_spec_slower.enabled = speed > self.gm.SPECTATOR_SPEEDS[0] + 1e-6
        self._btn_spec_slower.draw(surf)
        draw_icon(surf, self._btn_spec_slower.rect, 'minus', WHITE)

        surf.blit(sp_txt, (sp_x + btn_w + gap, sp_y + btn_h // 2 - sp_txt.get_height() // 2))

        faster_x = sp_x + btn_w + gap + sp_txt.get_width() + gap
        self._btn_spec_faster.rect = pygame.Rect(faster_x, sp_y, btn_w, btn_h)
        self._btn_spec_faster.enabled = speed < self.gm.SPECTATOR_SPEEDS[-1] - 1e-6
        self._btn_spec_faster.draw(surf)
        draw_icon(surf, self._btn_spec_faster.rect, 'plus', WHITE)

    def _draw_thinking(self, surf: pygame.Surface):
        sw, sh = self.gm.resolution
        cs = get_chrome_scale(sw, sh)
        import time
        dots = "." * (int(time.time() * 2) % 4)
        s = self.assets.font_scaled('ui_small', cs).render(f"AI thinking{dots}", True, (*WHITE, 160))
        surf.blit(s, (sw - s.get_width() - round(14 * cs), sh - round(26 * cs)))
