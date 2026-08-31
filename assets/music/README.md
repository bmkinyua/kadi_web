# Music assets

Drop the three loop files here (OGG Vorbis, not MP3 — MP3 encoders
commonly add silent padding that causes an audible tick/gap on loop):

| File                  | Slot              | Suggested track (CC0)                                             |
|-----------------------|-------------------|---------------------------------------------------------------------|
| `menu_theme.ogg`      | Menu Theme        | "Jazzy blues" by LushoGames — https://opengameart.org/content/jazzy-blues |
| `gameplay_ambient.ogg`| Gameplay Ambient  | "Heavenly Loop" by isaiah658 — https://opengameart.org/content/heavenly-loop |
| `chuo_drums.ogg`      | Chuo Drums        | "Djembe Loop 08 - 120 BPM" by Ancient.Sounds — https://freesound.org/people/Ancient.Sounds/sounds/485474/ |

See the chat response for full licensing notes and caveats on each pick.
Any slot left empty simply stays silent — the game runs fine without it.

The Credits panel in Settings reads from `MUSIC_CREDITS` in
`rendering/asset_loader.py` — update that list if you swap any track.
