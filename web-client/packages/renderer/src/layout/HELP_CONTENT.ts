/**
 * KADI web-client — Help Overlay content for all five screens that
 * have one on the PC side.
 *
 * This is the actual copy the player reads, ported VERBATIM from
 * scenes.py's five HELP_SECTIONS class constants (Main Menu ~846,
 * Chuo ~3613, MultiplayerMenuScene ~4310, GameplayScene ~6328) and
 * GameConfigScene's `_help_sections()` method (~1652, dynamic rather
 * than a static list -- it branches on `vs_ai`, so `gameConfigHelp()`
 * below is a function, not a constant, mirroring that). Nothing here
 * is paraphrased or rewritten -- if the wording looks slightly odd in
 * a spot, that's the PC original, not a porting mistake.
 *
 * ONE DELIBERATE EXCEPTION to verbatim-only: MULTIPLAYER_MENU_HELP's
 * LAN paragraph is PC's own real copy, but this web client's own
 * MultiplayerMenuScene.ts has no LAN button at all ("No LAN button,
 * ever" -- that file's own header). Rather than silently deleting or
 * rewriting PC's paragraph, a second, clearly-marked line was added
 * immediately after it (see that constant, below) noting LAN isn't
 * available on web and pointing to the desktop app -- a decision
 * made explicitly with the user, not assumed unilaterally.
 *
 * IMAGE SECTIONS -- NOT PORTED THIS PASS, flagged rather than dropped
 * silently (see layout/HelpOverlayLayout.ts's own header for the full
 * reasoning): two sections on the PC side splice in an illustration at
 * construction time, after the text below --
 *
 *   - Chuo's "Using a trained model in a game" section appends
 *     ('image', help_msomi_attach.png, "The MSOMI \"Attach Model...\"
 *     button, on the Play vs AI screen.") as its last item.
 *   - Gameplay's "Arranging multi-card plays" section appends
 *     ('image', help_drag_multicard.png, "Example: dragging a card to
 *     group it with same-rank cards already in hand, ready to play
 *     together.") as its last item.
 *
 * Reason: this web-client has NO image-asset loading pipeline
 * anywhere (no `load.image`/`preload` calls, no `public`/`static`
 * folder, no static-asset handling in vite.config.ts -- confirmed by
 * grep across the whole client before writing this file).
 * GameTableScene.ts's own header already states card art is drawn as
 * code specifically because no such pipeline exists. Adding one just
 * for these two illustrations is a real infrastructure addition, not
 * a mechanical part of porting the overlay widget -- so it's
 * deliberately left for a separately-scoped task. The exact
 * insertion point for each image is marked below with a comment where
 * it belongs, so wiring it in later is a content-only change, not
 * another pass through all five scenes.
 */
import type { HelpContent } from './HelpOverlayLayout.js';

export const MAIN_MENU_HELP: HelpContent = {
  title: 'KADI — Quick Guide',
  sections: [
    {
      heading: 'What each button does',
      paragraphs: [
        'Play vs AI — a single-player game against 1-5 computer opponents, with adjustable difficulty.',
        'Multiplayer — play with other people: on this device (hot-seat), over a local network (LAN), or with anyone online (Internet, via KADI\u2019s own server).',
        'How to Play — the full rules reference, built from the actual rules the game enforces.',
        'Settings — timers, jokers per deck, logging, hints, display resolution, and sound.',
        'Chuo (Swahili for "university") — train your own AI model (MSOMI) from your own logged games, then attach it to an AI opponent in Play vs AI.',
        'Profile — your badges, unlocked cosmetics (card backs and felt themes), and local/global leaderboards.',
      ],
    },
  ],
};

/**
 * Mirrors GameConfigScene._help_sections()'s `if self.vs_ai` branch --
 * the title itself also branches on the PC side ("Play vs AI — Quick
 * Guide" vs "Local Multiplayer — Quick Guide"), so this returns the
 * whole HelpContent (title + sections), not just the sections list.
 */
export function gameConfigHelp(vsAi: boolean): HelpContent {
  if (vsAi) {
    return {
      title: 'Play vs AI — Quick Guide',
      sections: [
        {
          heading: 'Setting up your game',
          paragraphs: [
            'Number of Opponents sets how many AI players you\u2019ll face. AI Difficulty applies to ALL of them at once — there\u2019s no per-opponent difficulty yet.',
            'MSOMI lets you attach a model you trained yourself in Chuo to make an AI opponent play more like a human. It\u2019s separate from difficulty, not a 4th tier — it layers on top of whichever difficulty is picked. See the ? on the Chuo screen for the full training guide.',
          ],
        },
        {
          heading: 'Elimination Mode',
          paragraphs: [
            'Off (default): the game ends the moment the first player finishes their cards — everyone else is ranked by cards remaining.',
            'On: finished players are set aside as they go, and play continues until only one player is left holding cards — that player loses. "Continue with AI" controls what happens if every human finishes before the AI players do.',
          ],
        },
      ],
    };
  }
  return {
    title: 'Local Multiplayer — Quick Guide',
    sections: [
      {
        heading: 'Setting up local multiplayer',
        paragraphs: [
          'Everyone plays on this ONE device, passing it around turn by turn. Give each player a name so it\u2019s clear whose turn it is.',
          'A privacy screen appears between turns so players can\u2019t see each other\u2019s hands while the device is being handed over — just tap through it once you\u2019ve got the device.',
        ],
      },
      {
        heading: 'Elimination Mode',
        paragraphs: [
          'Off (default): the game ends the moment the first player finishes their cards — everyone else is ranked by cards remaining.',
          'On: finished players are set aside as they go, and play continues until only one player is left holding cards — that player loses.',
        ],
      },
    ],
  };
}

export const CHUO_HELP: HelpContent = {
  title: 'Chuo — Training Guide',
  sections: [
    {
      heading: 'Before you start: turn on logging',
      paragraphs: [
        'Chuo trains a model from LOGGED decisions — human and AI moves recorded during real games. If logging is off, there\u2019s nothing here to train from.',
        'Go to Settings -> Deck & Logging -> Logging (for bug reports) and set it to HIGH, then go play a few games (any mode). Each finished game adds a new .jsonl file under the logs folder — that\u2019s what shows up in the Data tab below.',
      ],
    },
    {
      heading: 'The 4 tabs, in order',
      paragraphs: [
        'Data — pick which logged .jsonl files to train from (no limit on how many). Select All / Select None help with a long list; Browse for files... lets you pick logs from somewhere else on disk. Click Load Selected Logs once you\u2019ve picked which ones to use.',
        'Features — choose which signals the model is allowed to learn from (what cards are in play, hand size, current suit, and so on). Leaving everything selected is a reasonable default; deselecting some is for experimenting.',
        'Model — set the human decision weight (how much more a human\u2019s move counts vs. an AI\u2019s, since human play is usually the more useful signal) and training iterations (higher = slower but usually better).',
        'Train & Results — click Train Model, then Save Model once you\u2019re happy with the results shown. Training runs locally and doesn\u2019t touch a game in progress.',
      ],
    },
    {
      heading: 'Using a trained model in a game',
      paragraphs: [
        'A saved model does nothing by itself — it has to be attached to an AI opponent. Go to Play vs AI, pick a difficulty (Easy/Medium/Hard), then use the MSOMI toggle next to the difficulty buttons to attach the model you just trained to that AI opponent.',
        'MSOMI is separate from difficulty, not a 4th tier — it layers on top of whichever difficulty is picked.',
        // PC: help_msomi_attach.png + caption goes here as this
        // section's 3rd item — not ported this pass, see file header.
      ],
    },
  ],
};

export const MULTIPLAYER_MENU_HELP: HelpContent = {
  title: 'Multiplayer — Which mode?',
  sections: [
    {
      heading: 'Which mode do I want?',
      paragraphs: [
        'Local Multiplayer — everyone takes turns on this ONE device, passing it around. A privacy screen hides each player\u2019s hand before it\u2019s shown, so nobody peeks at an opponent\u2019s cards while the device is being handed over.',
        'LAN Multiplayer — for players on the same Wi-Fi/network (e.g. everyone in one house or office). One person\u2019s machine hosts the game; everyone else joins it from their own device.',
        // NOT part of the verbatim PC port -- a web-client-specific
        // addition (per this session's own follow-up decision) since
        // this screen's real MultiplayerMenuScene.ts has no LAN
        // button at all (see that file's header: "No LAN button,
        // ever"). Rather than deleting PC's own LAN paragraph above
        // (the task's own instruction was to port real HELP_SECTIONS
        // copy verbatim, not edit it), this note resolves the
        // resulting mismatch honestly and doubles as a cross-sell to
        // the desktop app, which does have it.
        'LAN Multiplayer isn\u2019t available in this web version — grab the KADI desktop app if you want to host or join a game over a local network.',
        'Internet Multiplayer — for players anywhere, on separate networks, connecting through a shared server rather than directly to each other.',
      ],
    },
    {
      heading: 'Connecting to Internet Multiplayer',
      paragraphs: [
        'KADI\u2019s official server address is kadigame.ddns.net — enter just that under Server Address (no port needed) to play with anyone else using KADI\u2019s official server, no matter where they are.',
        'If a friend or community runs their OWN private server instead, use whatever address they give you there rather than the official one above.',
      ],
    },
  ],
};

export const GAMEPLAY_HELP: HelpContent = {
  title: 'Gameplay — Quick Guide',
  sections: [
    {
      heading: 'Playing your turn',
      paragraphs: [
        'Play a card that matches the SUIT or RANK of the top discard card, or click Draw Card if you can\u2019t or don\u2019t want to play. Click a card in your hand to select it (gold glow), then Play Card(s) — or just click Draw Card or the draw pile directly.',
        'Playable cards are highlighted; unplayable ones are dimmed so it\u2019s clear at a glance what your options are.',
      ],
    },
    {
      heading: 'Arranging multi-card plays',
      paragraphs: [
        'Drag and drop cards in your hand to reorder them — click and hold a card, then drag it left or right to a new position. This matters for multi-card plays (like a Question card plus its answer, or several Jacks/Kings played together): put the cards in the order you want them played, in a single line, before selecting and playing them together.',
        // PC: help_drag_multicard.png + caption goes here as this
        // section's 2nd item — not ported this pass, see file header.
      ],
    },
    {
      heading: 'Declaring KADI',
      paragraphs: [
        'Click Declare KADI! on your second-to-last card to warn everyone you\u2019re about to finish — forgetting to declare in time carries a penalty, so it\u2019s worth getting in the habit of clicking it as soon as you\u2019re down to 2 cards.',
      ],
    },
    {
      heading: 'Undo',
      paragraphs: [
        'A limited number of undo tokens let you take back your last move if you misclick. When available, an Undo button appears right after you play or draw, showing your current token count in its label — e.g. "Undo (2)".',
      ],
    },
  ],
};
