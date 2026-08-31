"""Manual repro for the 'Trickster must pick 2!' naming bug reported by the
user: seats 0 and 1 have already finished (won and left, Elimination Mode),
seat 2 plays a Pick-2 card. The banner must name the next still-active
seat (skipping 0 and 1), not blindly step by one seat."""
import os, sys
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from constants import AIDifficulty
from core.game_manager import GameManager

gm = GameManager()
gm.new_game([
    {'name': 'Blitz', 'is_human': False, 'difficulty': AIDifficulty.EASY},
    {'name': 'Shadow', 'is_human': False, 'difficulty': AIDifficulty.EASY},
    {'name': 'Player 1', 'is_human': True},
    {'name': 'Trickster', 'is_human': False, 'difficulty': AIDifficulty.EASY},
    {'name': 'Smart AI', 'is_human': False, 'difficulty': AIDifficulty.EASY},
], elimination_mode=True)

gm.players[0].finished = True   # Blitz OUT
gm.players[1].finished = True   # Shadow OUT
gm.current_player_idx = 2       # Player 1's turn

step = gm.direction.value
next_idx = gm._next_active_idx(gm.current_player_idx, step)
named = gm.players[next_idx]
assert named.name == 'Trickster', f"expected Trickster, got {named.name}"
print("OK:", named.name, "is correctly named as the next active player")
