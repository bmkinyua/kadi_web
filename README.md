# KADI Card Game

A full-featured implementation of the KADI card game in Python/Pygame.

## Play
```
python main.py
```

## Controls
| Action | How |
|--------|-----|
| Select card | Click on it in your hand |
| Deselect | Click again |
| Play selected | Click **Play Card** or select + double-click |
| Draw | Click **Draw Card** or click the draw pile |
| Declare KADI | Click **Declare KADI!** before your second-to-last play |
| Choose suit (A card) | Click one of the four suit buttons |
| Counter finish | Click **Counter! (J/K)** during the 3-second window |
| Pass counter | Click **Pass** |
| Menu / Quit | ESC or click **Menu** |

## Rules Summary
- Match the top card by **suit** or **rank**
- Special cards:
  - **2 / 3 / Joker** — force next player to pick 2 / 3 / 5 cards
  - **A (10)** — change the active suit, or shield against pickups
  - **K** — reverse play direction
  - **J** — skip next player (in 2-player: play again)
  - **8 / Q** — question cards (thematic, no special effect)
- **Finishing cards**: 4, 5, 6, 7, 9
- Declare **KADI** on your second-to-last turn; win by playing your last finishing card(s)

## Modes
- **vs AI** — 1–5 AI opponents, Easy / Medium / Hard
- **Local Multiplayer** — hotseat for 2–6 players on one machine

## Settings
- Joker count: 2 or 4
- Allow counter finish (J/K to block a win, 3-second window)
- Suit change after shield

---

## Packaging for itch.io

### Desktop (recommended)
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "KADI" main.py
# Distributable is in dist/KADI (or dist/KADI.exe on Windows)
# Zip the dist/ folder and upload to itch.io
```

### Browser (experimental — requires pygbag)
```bash
pip install pygbag
pygbag main.py
# Generates web/ folder with index.html
# Upload web/ contents to itch.io as HTML5
```

> **Note**: Browser build requires replacing `asyncio`-incompatible blocking calls.
> Desktop distribution is the recommended path.

---

## Project Structure
```
kadi/
├── main.py              Entry point
├── constants.py         Colors, enums, game constants
├── core/
│   ├── game_manager.py  Game state machine
│   └── rule_engine.py   Card play validation
├── models/
│   ├── card.py          Card + Deck data models
│   └── player.py        Human + AI player logic
├── rendering/
│   ├── asset_loader.py  Procedural card rendering
│   ├── board_renderer.py Table + hand layout
│   └── widgets.py       Buttons, banners, pickers
├── animation/
│   └── animator.py      Tween engine + card animations
└── scenes.py            All game screens
```
