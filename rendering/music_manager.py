"""
KADI - Music Manager

Background music + the Chuo drum easter egg, built on pygame.mixer
Channels (not pygame.mixer.music, which can only stream one file at a
time — we need up to three loops with independent, simultaneously
moving volumes: menu theme, gameplay ambient, and Chuo drums).

Split into two pieces on purpose:

  VolumeFader   - pure math, no pygame audio calls. Given a target
                  volume and a duration, interpolates update()-by-
                  update() and lands exactly on the target. Deterministic
                  and unit-testable without a sound device.

  MusicManager  - owns three VolumeFaders (menu / gameplay / chuo), the
                  three pygame.mixer.Channel objects they drive, and the
                  small state machine that decides what the *targets*
                  should be (which scene we're in, whether the Chuo
                  button is currently hovered, whether music is muted).

Every crossfade in the game — the ordinary menu<->gameplay scene
transition, the Chuo hover preview, and the Chuo scene's persistent
faint drum layer — goes through the same set_target()/update()
mechanism, per the "don't build the crossfade twice" instruction.
"""
from __future__ import annotations
import os
from typing import Optional, Dict


class VolumeFader:
    """Smoothly interpolates a single value toward a target over a
    fixed duration. update(dt) advances it; value always lands exactly
    on the target once the duration has elapsed (no float drift)."""

    def __init__(self, value: float = 0.0):
        self.value: float = value
        self._start: float = value
        self._target: float = value
        self._elapsed: float = 0.0
        self._duration: float = 0.0

    def set_target(self, target: float, duration: float) -> None:
        """Begin a new fade from the *current* value toward `target`.
        Called mid-fade, this naturally reverses/redirects the motion
        smoothly instead of snapping, since _start is always wherever
        the fader currently sits."""
        target = max(0.0, min(1.0, target))
        if duration <= 0:
            self.value = target
            self._start = target
            self._target = target
            self._elapsed = 0.0
            self._duration = 0.0
            return
        self._start = self.value
        self._target = target
        self._elapsed = 0.0
        self._duration = duration

    def update(self, dt: float) -> None:
        if self._elapsed >= self._duration:
            self.value = self._target
            return
        self._elapsed = min(self._duration, self._elapsed + dt)
        t = self._elapsed / self._duration
        self.value = self._start + (self._target - self._start) * t
        if self._elapsed >= self._duration:
            self.value = self._target  # land exactly, no float error

    @property
    def target(self) -> float:
        return self._target

    @property
    def done(self) -> bool:
        return self._elapsed >= self._duration


# ─── Tuning ─────────────────────────────────────────────────────────────────

SCENE_CROSSFADE_SECS = 1.5   # ordinary menu<->gameplay transition
HOVER_CROSSFADE_SECS = 1.5   # Chuo button hover preview (spec: ~1-2s)
CHUO_ENTER_SECS      = 1.5   # full drums -> faint, on actually entering Chuo
CHUO_EXIT_SECS       = 1.0   # drums out / menu theme back up, on leaving Chuo
CHUO_FAINT_LEVEL      = 0.065  # 6.5%, inside the requested 5-8% band

# Scenes that count as "menu-tier" for music purposes (menu theme plays).
# Everything not in GAMEPLAY_SCENES or CHUO_SCENES falls into this bucket,
# so newly-added menu-ish screens don't need to remember to opt in.
GAMEPLAY_SCENES = {'gameplay'}
CHUO_SCENES = {'chuo'}


class MusicManager:
    """Owns the three looping audio layers and the crossfade state
    machine that drives their volumes. AssetLoader owns the Sound
    objects (or None, if a track file isn't present); this class only
    deals in Channels + VolumeFaders."""

    def __init__(self):
        self.menu_fader     = VolumeFader(1.0)   # menu theme starts "on"
        self.gameplay_fader = VolumeFader(0.0)
        self.chuo_fader     = VolumeFader(0.0)

        self.enabled: bool = True   # master music on/off (Settings toggle)
        self.volume: float = 0.7    # master music volume 0.0-1.0 (Settings slider)

        self._menu_channel: Optional["pygame.mixer.Channel"] = None
        self._gameplay_channel: Optional["pygame.mixer.Channel"] = None
        self._chuo_channel: Optional["pygame.mixer.Channel"] = None

        self._menu_sound = None
        self._gameplay_sound = None
        self._chuo_sound = None

        self._chuo_hovered = False
        self._current_scene = ""

    # ── Wiring (called once from AssetLoader after sounds are loaded) ──────

    def bind(self, menu_sound, gameplay_sound, chuo_sound):
        """Attach the loaded Sound objects (any may be None if the file
        wasn't found) and reserve+start their channels. Safe to call
        even with pygame.mixer running on the 'dummy' audio driver —
        .play() on a dummy device is a no-op but doesn't raise."""
        import pygame
        self._menu_sound = menu_sound
        self._gameplay_sound = gameplay_sound
        self._chuo_sound = chuo_sound
        try:
            pygame.mixer.set_reserved(3)
            self._menu_channel = pygame.mixer.Channel(0)
            self._gameplay_channel = pygame.mixer.Channel(1)
            self._chuo_channel = pygame.mixer.Channel(2)
            if menu_sound is not None:
                self._menu_channel.play(menu_sound, loops=-1)
                self._menu_channel.set_volume(self.menu_fader.value)
            if gameplay_sound is not None:
                self._gameplay_channel.play(gameplay_sound, loops=-1)
                self._gameplay_channel.set_volume(self.gameplay_fader.value)
            if chuo_sound is not None:
                self._chuo_channel.play(chuo_sound, loops=-1)
                self._chuo_channel.set_volume(self.chuo_fader.value)
        except Exception:
            # No audio device (or init failed) — the faders still track
            # state correctly, they just have nothing to apply volume to.
            pass

    # ── Scene-driven state ──────────────────────────────────────────────────

    def on_scene_changed(self, scene_name: str) -> None:
        """Called by SceneManager right after switch(). Sets the target
        volumes for the new scene; update() carries them there smoothly."""
        leaving_chuo = (self._current_scene in CHUO_SCENES) and (scene_name not in CHUO_SCENES)
        self._current_scene = scene_name
        self._chuo_hovered = False  # leaving main menu always cancels hover

        if scene_name in GAMEPLAY_SCENES:
            self.menu_fader.set_target(0.0, SCENE_CROSSFADE_SECS)
            self.gameplay_fader.set_target(1.0, SCENE_CROSSFADE_SECS)
            self.chuo_fader.set_target(0.0, SCENE_CROSSFADE_SECS)
        elif scene_name in CHUO_SCENES:
            # Full drums (from the hover preview) -> faint persistent layer.
            # Menu theme stays silent for the duration of the Chuo scene.
            self.menu_fader.set_target(0.0, CHUO_ENTER_SECS)
            self.gameplay_fader.set_target(0.0, CHUO_ENTER_SECS)
            self.chuo_fader.set_target(CHUO_FAINT_LEVEL, CHUO_ENTER_SECS)
        else:
            # Any other menu-tier screen (main menu, mode select, settings,
            # rules, multiplayer/LAN/internet menus and lobbies).
            dur = CHUO_EXIT_SECS if leaving_chuo else SCENE_CROSSFADE_SECS
            self.menu_fader.set_target(1.0, dur)
            self.gameplay_fader.set_target(0.0, dur)
            self.chuo_fader.set_target(0.0, dur)

    def set_chuo_hover(self, hovered: bool) -> None:
        """Called every frame from MainMenuScene.update() with whether the
        mouse is currently over the Chuo button. Only meaningful while on
        the main menu; a no-op transition if the state hasn't changed."""
        if hovered == self._chuo_hovered:
            return
        self._chuo_hovered = hovered
        if hovered:
            self.menu_fader.set_target(0.0, HOVER_CROSSFADE_SECS)
            self.chuo_fader.set_target(1.0, HOVER_CROSSFADE_SECS)
        else:
            # Reverses smoothly from wherever the crossfade currently is,
            # rather than snapping, since set_target starts from .value.
            self.menu_fader.set_target(1.0, HOVER_CROSSFADE_SECS)
            self.chuo_fader.set_target(0.0, HOVER_CROSSFADE_SECS)

    # ── Per-frame update ─────────────────────────────────────────────────────

    def update(self, dt: float) -> None:
        self.menu_fader.update(dt)
        self.gameplay_fader.update(dt)
        self.chuo_fader.update(dt)
        self._apply_volumes()

    def _apply_volumes(self) -> None:
        mute = 0.0 if not self.enabled else 1.0
        level = mute * max(0.0, min(1.0, self.volume))
        try:
            if self._menu_channel is not None:
                self._menu_channel.set_volume(self.menu_fader.value * level)
            if self._gameplay_channel is not None:
                self._gameplay_channel.set_volume(self.gameplay_fader.value * level)
            if self._chuo_channel is not None:
                self._chuo_channel.set_volume(self.chuo_fader.value * level)
        except Exception:
            pass

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self._apply_volumes()

    def set_volume(self, volume: float) -> None:
        self.volume = max(0.0, min(1.0, volume))
        self._apply_volumes()
