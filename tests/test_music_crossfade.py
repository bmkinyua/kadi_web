"""
KADI - Music crossfade unit tests.

Covers the parts of the new music system that don't need real audio
hardware: VolumeFader's interpolation math, and MusicManager's scene/
hover-driven target-setting state machine. Run headless:

    SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy python -m tests.test_music_crossfade
"""
from __future__ import annotations
import os
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rendering.music_manager import (
    VolumeFader, MusicManager,
    SCENE_CROSSFADE_SECS, HOVER_CROSSFADE_SECS, CHUO_ENTER_SECS,
    CHUO_EXIT_SECS, CHUO_FAINT_LEVEL,
)

_fails = []


def check(label, cond):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}")
    if not cond:
        _fails.append(label)


def test_fader_basic_interpolation():
    print("\n== VolumeFader: basic interpolation ==")
    f = VolumeFader(0.0)
    f.set_target(1.0, 2.0)
    check("initial value unchanged until first update", f.value == 0.0)

    prev = f.value
    monotonic = True
    ticks = 0
    # Simulate ~60fps ticks for slightly longer than the duration.
    while not f.done and ticks < 1000:
        f.update(1 / 60)
        if f.value < prev - 1e-9:
            monotonic = False
        prev = f.value
        ticks += 1
    check("moved monotonically toward target", monotonic)
    check("landed exactly on target (1.0)", f.value == 1.0)
    check("done flag set once elapsed >= duration", f.done)
    check(f"converged in a bounded number of ticks (got {ticks})", ticks < 200)


def test_fader_reverse_mid_flight():
    print("\n== VolumeFader: reversing mid-fade ==")
    f = VolumeFader(0.0)
    f.set_target(1.0, 1.5)
    for _ in range(45):  # ~0.75s at 60fps — halfway through the fade
        f.update(1 / 60)
    mid_value = f.value
    check("partway through fade, value is between start and target",
          0.0 < mid_value < 1.0)

    # Reverse direction from wherever we currently are.
    f.set_target(0.0, 1.5)
    check("reversing starts from current value, not from old target",
          f.value == mid_value)

    prev = f.value
    monotonic_down = True
    ticks = 0
    while not f.done and ticks < 1000:
        f.update(1 / 60)
        if f.value > prev + 1e-9:
            monotonic_down = False
        prev = f.value
        ticks += 1
    check("reversed fade moved monotonically back down", monotonic_down)
    check("landed exactly on the new target (0.0)", f.value == 0.0)


def test_fader_zero_duration_snaps():
    print("\n== VolumeFader: zero-duration snap ==")
    f = VolumeFader(0.3)
    f.set_target(0.9, 0.0)
    check("zero duration applies target immediately", f.value == 0.9)
    check("zero duration reports done immediately", f.done)


def test_fader_clamps_target():
    print("\n== VolumeFader: target clamping ==")
    f = VolumeFader(0.0)
    f.set_target(5.0, 1.0)
    f.update(10.0)
    check("target above 1.0 clamps to 1.0", f.value == 1.0)
    f2 = VolumeFader(1.0)
    f2.set_target(-3.0, 1.0)
    f2.update(10.0)
    check("target below 0.0 clamps to 0.0", f2.value == 0.0)


def _settle(mgr: MusicManager, seconds: float, step: float = 1 / 60):
    ticks = int(seconds / step) + 2
    for _ in range(ticks):
        mgr.menu_fader.update(step)
        mgr.gameplay_fader.update(step)
        mgr.chuo_fader.update(step)


def test_scene_transitions():
    print("\n== MusicManager: scene transitions ==")
    m = MusicManager()
    check("starts on menu theme", m.menu_fader.value == 1.0 and m.gameplay_fader.value == 0.0)

    m.on_scene_changed('gameplay')
    _settle(m, SCENE_CROSSFADE_SECS)
    check("gameplay scene -> gameplay ambient full, menu silent",
          m.gameplay_fader.value == 1.0 and m.menu_fader.value == 0.0)

    m.on_scene_changed('settings')
    _settle(m, SCENE_CROSSFADE_SECS)
    check("returning to a menu-tier scene -> menu theme full again",
          m.menu_fader.value == 1.0 and m.gameplay_fader.value == 0.0)


def test_chuo_hover_and_enter_exit():
    print("\n== MusicManager: Chuo hover + scene enter/exit ==")
    m = MusicManager()
    m.on_scene_changed('main_menu')
    _settle(m, SCENE_CROSSFADE_SECS)

    m.set_chuo_hover(True)
    _settle(m, HOVER_CROSSFADE_SECS)
    check("hovering Chuo button fades menu theme fully out",
          m.menu_fader.value == 0.0)
    check("hovering Chuo button fades drums fully in",
          m.chuo_fader.value == 1.0)

    # Mouse leaves before entering the scene -> should reverse smoothly.
    m.set_chuo_hover(False)
    _settle(m, HOVER_CROSSFADE_SECS)
    check("leaving hover restores full menu theme", m.menu_fader.value == 1.0)
    check("leaving hover fades drums back to silent", m.chuo_fader.value == 0.0)

    # Now actually hover + click through to the Chuo scene.
    m.set_chuo_hover(True)
    _settle(m, HOVER_CROSSFADE_SECS)
    m.on_scene_changed('chuo')
    _settle(m, CHUO_ENTER_SECS)
    check("entering Chuo scene drops drums to the faint background level",
          abs(m.chuo_fader.value - CHUO_FAINT_LEVEL) < 1e-9)
    check("menu theme stays silent while in the Chuo scene",
          m.menu_fader.value == 0.0)
    check("faint level is within the requested 5-8% band",
          0.05 <= CHUO_FAINT_LEVEL <= 0.08)

    m.on_scene_changed('main_menu')
    _settle(m, CHUO_EXIT_SECS)
    check("leaving Chuo fades drums back out", m.chuo_fader.value == 0.0)
    check("leaving Chuo fades menu theme back up", m.menu_fader.value == 1.0)


def test_music_toggle_silences_everything():
    print("\n== MusicManager: master enable/disable ==")
    m = MusicManager()
    m.on_scene_changed('main_menu')
    _settle(m, SCENE_CROSSFADE_SECS)
    check("menu theme fader at full before mute", m.menu_fader.value == 1.0)
    m.enabled = False
    m._apply_volumes()  # no real channels bound in this test -> just must not raise
    check("disabling music doesn't crash without bound channels", True)
    # Fader math itself is untouched by mute — mute only affects the
    # applied channel volume, per the "state tracking unaffected" design
    # so re-enabling doesn't require re-deriving targets.
    check("fader value still reflects scene state (mute is a playback-only mask)",
          m.menu_fader.value == 1.0)


if __name__ == '__main__':
    print("=" * 70)
    print("KADI Music Crossfade Unit Tests")
    print("=" * 70)

    test_fader_basic_interpolation()
    test_fader_reverse_mid_flight()
    test_fader_zero_duration_snaps()
    test_fader_clamps_target()
    test_scene_transitions()
    test_chuo_hover_and_enter_exit()
    test_music_toggle_silences_everything()

    print("\n" + "=" * 70)
    if _fails:
        print(f"RESULT: {len(_fails)} check(s) FAILED:")
        for f in _fails:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: all checks passed")
        sys.exit(0)
