"""
KADI - Animation system
Lightweight tween engine + card motion animations.
"""
from __future__ import annotations
import math
from typing import List, Optional, Callable, Tuple


# ─── Easing functions ─────────────────────────────────────────────────────────

def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3

def ease_in_out_quad(t: float) -> float:
    if t < 0.5:
        return 2 * t * t
    return 1 - (-2 * t + 2) ** 2 / 2

def ease_out_bounce(t: float) -> float:
    n1, d1 = 7.5625, 2.75
    if t < 1/d1:
        return n1 * t * t
    elif t < 2/d1:
        t -= 1.5/d1
        return n1 * t * t + 0.75
    elif t < 2.5/d1:
        t -= 2.25/d1
        return n1 * t * t + 0.9375
    else:
        t -= 2.625/d1
        return n1 * t * t + 0.984375

def ease_out_elastic(t: float) -> float:
    if t == 0: return 0
    if t == 1: return 1
    c4 = (2 * math.pi) / 3
    return pow(2, -10 * t) * math.sin((t * 10 - 0.75) * c4) + 1

def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """Overshoots past 1.0 then settles back — the 'snap into place with a
    little bounce' feel, used for the scroll-limit bounce and other
    UI settle effects."""
    c1 = overshoot
    c3 = c1 + 1
    t -= 1
    return 1 + c3 * (t ** 3) + c1 * (t ** 2)


EASING = {
    'linear':       lambda t: t,
    'ease_out':     ease_out_cubic,
    'ease_in_out':  ease_in_out_quad,
    'bounce':       ease_out_bounce,
    'elastic':      ease_out_elastic,
    'ease_out_back': ease_out_back,
}


# ─── Tween ────────────────────────────────────────────────────────────────────

class Tween:
    def __init__(self, start, end, duration: float, easing: str = 'ease_out',
                 on_complete: Optional[Callable] = None):
        self.start = start
        self.end   = end
        self.duration = duration
        self.elapsed  = 0.0
        self._ease = EASING.get(easing, ease_out_cubic)
        self.on_complete = on_complete
        self.done = False

    def update(self, dt: float):
        if self.done:
            return
        self.elapsed = min(self.elapsed + dt, self.duration)
        if self.elapsed >= self.duration:
            self.done = True
            if self.on_complete:
                self.on_complete()

    @property
    def value(self):
        if self.duration == 0:
            return self.end
        t = self._ease(self.elapsed / self.duration)
        if isinstance(self.start, (list, tuple)):
            return tuple(self.start[i] + (self.end[i] - self.start[i]) * t
                         for i in range(len(self.start)))
        return self.start + (self.end - self.start) * t

    @property
    def progress(self) -> float:
        if self.duration == 0:
            return 1.0
        return min(self.elapsed / self.duration, 1.0)


# ─── Animated card ────────────────────────────────────────────────────────────

class AnimatedCard:
    """A card in motion - has position, scale, rotation, alpha tweens."""
    def __init__(self, card, start_pos: Tuple[float, float],
                 end_pos: Tuple[float, float], duration: float = 0.35,
                 face_up: bool = True, easing: str = 'ease_out',
                 on_complete: Optional[Callable] = None,
                 start_scale: float = 1.0, end_scale: float = 1.0,
                 start_alpha: int = 255, end_alpha: int = 255):
        self.card     = card
        self.face_up  = face_up
        self.done     = False

        self._pos_tween   = Tween(list(start_pos), list(end_pos), duration, easing,
                                  self._finish)
        self._scale_tween = Tween(start_scale, end_scale, duration, easing)
        self._alpha_tween = Tween(float(start_alpha), float(end_alpha), duration, easing)
        self._on_complete = on_complete

    def _finish(self):
        self.done = True
        if self._on_complete:
            self._on_complete(self)

    def update(self, dt: float):
        self._pos_tween.update(dt)
        self._scale_tween.update(dt)
        self._alpha_tween.update(dt)

    @property
    def pos(self) -> Tuple[float, float]:
        v = self._pos_tween.value
        return (v[0], v[1])

    @property
    def scale(self) -> float:
        return self._scale_tween.value

    @property
    def alpha(self) -> int:
        return int(self._alpha_tween.value)


# ─── Animation Manager ────────────────────────────────────────────────────────

class AnimationManager:
    def __init__(self):
        self._active: List[AnimatedCard] = []
        self._tweens: List[Tween] = []
        self._callbacks_pending: List[Callable] = []

    def update(self, dt: float):
        for a in self._active:
            a.update(dt)
        self._active = [a for a in self._active if not a.done]
        for t in self._tweens:
            t.update(dt)
        self._tweens = [t for t in self._tweens if not t.done]

    @property
    def is_busy(self) -> bool:
        return bool(self._active) or bool(self._tweens)

    def add_card_anim(self, anim: AnimatedCard):
        self._active.append(anim)

    def add_tween(self, tween: Tween):
        self._tweens.append(tween)

    def get_active_anims(self) -> List[AnimatedCard]:
        return list(self._active)

    def deal_card(self, card, deck_pos, dest_pos, face_up=False, delay=0.0,
                  on_complete=None):
        def _start():
            a = AnimatedCard(card, deck_pos, dest_pos, duration=0.32,
                             face_up=face_up, easing='ease_out_back',
                             start_scale=0.8, end_scale=1.0,
                             start_alpha=180, end_alpha=255,
                             on_complete=on_complete)
            self._active.append(a)

        if delay > 0:
            t = Tween(0, 1, delay, on_complete=_start)
            self._tweens.append(t)
        else:
            _start()

    def play_card(self, card, start_pos, discard_pos, face_up=True, on_complete=None):
        a = AnimatedCard(card, start_pos, discard_pos, duration=0.28,
                         face_up=face_up, easing='ease_out_back',
                         start_scale=1.1, end_scale=1.0,
                         on_complete=on_complete)
        self._active.append(a)

    def draw_card(self, card, deck_pos, hand_pos, face_up=True, on_complete=None):
        a = AnimatedCard(card, deck_pos, hand_pos, duration=0.28,
                         face_up=face_up, easing='ease_out',
                         start_scale=0.9, end_scale=1.0,
                         on_complete=on_complete)
        self._active.append(a)

    def clear(self):
        self._active.clear()
        self._tweens.clear()
