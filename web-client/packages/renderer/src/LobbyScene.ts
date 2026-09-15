/**
 * KADI - first renderer scene: prove the whole vertical slice works
 * (adapter -> WebSocket -> real server -> back), rendered entirely on
 * Phaser's canvas. Deliberately minimal -- this is NOT the game
 * table, it's the smallest useful thing that proves the pipe works:
 * connection status, this device's display name, and the live global
 * leaderboard pulled from the real server/leaderboard_store.py.
 *
 * RENDERING DISCIPLINE (plan §6): every element below is a Phaser
 * GameObject (Text, in this scene), never an HTML element. That's not
 * a style preference -- it's the one thing that has to be true from
 * the very first scene for a WeChat build to have any chance of
 * running this unmodified later (WeChat's sandbox has no DOM to put
 * an HTML element INTO).
 *
 * LAYOUT DISCIPLINE (KADI_web_port_implementation_plan.md's
 * "Continuous Layout & Scale System" section): every position and
 * font size below comes from computeLobbyLayout() in
 * layout/LobbyLayout.ts, recomputed from this.scale.width/height on
 * every genuine viewport change -- never a hard-coded x/y/fontSize
 * against a fixed 480x640 canvas. This is the mandatory pattern every
 * future scene copies; see that file and layout/scale.ts for the
 * underlying math and why it's shaped this way.
 *
 * PART E ADDITION -- the lobby -> game-table transition: a single
 * "Quick Play vs AI" button (layout.quickPlayButton, see
 * LobbyLayout.ts's own note on why this is the retrofit target its
 * touch-target docs predicted). Tapping it creates a room with one AI
 * opponent, immediately requests start, and -- once the server
 * confirms with 'start_game' -- hands the SAME already-open
 * KadiConnection to GameTableScene (see that file's own note on why a
 * second connection would NOT be a continuation of this one's room
 * membership). This is a deliberately narrow slice of "create/join a
 * game from the lobby": no lobby-browse/join-by-list UI is built here
 * (see packages/protocol/src/messages.ts's GameSummary docstring) --
 * Quick Play satisfies the literal transition the task brief asks for
 * (create a game, land in GameTableScene once it starts) without a
 * full room-browser this pass doesn't otherwise need.
 */
import Phaser from 'phaser';
import { KadiConnection } from '@kadi/client-core';
import type { ConnectionState } from '@kadi/client-core';
import type { CreateGameSettings, ServerMessage } from '@kadi/protocol';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import { computeLobbyLayout, type LobbyLayout } from './layout/LobbyLayout.js';

export class LobbyScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  private connection!: KadiConnection;

  private statusText!: Phaser.GameObjects.Text;
  private identityText!: Phaser.GameObjects.Text;
  private rankText!: Phaser.GameObjects.Text;
  private headerText!: Phaser.GameObjects.Text;
  private leaderboardLines: Phaser.GameObjects.Text[] = [];
  private quickPlayButton!: Phaser.GameObjects.Rectangle;
  private quickPlayLabel!: Phaser.GameObjects.Text;
  /** True once this scene has already asked the server to
   * create+start a Quick Play room -- guards against a double-tap
   * firing two create_game requests while the first is still in
   * flight. */
  private quickPlayRequested = false;
  /** Set when ModeSelectScene routes here after the player already
   * picked "Play vs AI" (see ModeSelectScene.ts) -- fires the same
   * request onQuickPlayTapped() would, the moment the connection
   * opens, so the player isn't asked to tap a second, redundant
   * "Quick Play vs AI" button after already choosing that mode one
   * screen back. */
  private autoQuickPlay = false;
  /** Real per-game settings from GameConfigScene(vsAi=true)'s "Start
   * Game" (opponent count/difficulty/elimination mode/MSOMI) --
   * falls back to the original fixed Quick Play settings
   * ({ai_count:1, ai_difficulty:'MEDIUM'}) when undefined, e.g. for
   * GameTableScene's own post-game "Play Again" route back here,
   * which never carried real config and shouldn't have to. */
  private gameSettings: CreateGameSettings | undefined;
  /** GameConfigScene's "Your Name" field, applied via
   * adapter.setDisplayName() before 'hello' goes out -- see that
   * scene's own onStartGame() for why this lives here rather than
   * GameConfigScene sending 'hello' itself (this scene already owns
   * the one connection's whole hello/create/start lifecycle, bugfixes
   * and all -- see this file's own header). */
  private playerName: string | undefined;
  private unsubscribers: (() => void)[] = [];

  /** Most recent leaderboard payload, kept around so a resize can
   * re-run renderLeaderboard() against the CURRENT viewport without
   * waiting for a new server message -- entries themselves don't
   * change on resize, only how many rows fit and where. */
  private lastEntries: { name: string; wins: number }[] = [];

  constructor() {
    super('LobbyScene');
  }

  /** Called once by an app entry point (e.g. apps/web-pwa/src/main.ts)
   * before the game boots -- see that file for why adapter selection
   * happens there, at build/entry time, rather than this scene
   * guessing which platform it's on. */
  init(data: {
    adapter: PlatformAdapter;
    autoQuickPlay?: boolean;
    gameSettings?: CreateGameSettings;
    playerName?: string;
  }): void {
    this.adapter = data.adapter;
    this.autoQuickPlay = data.autoQuickPlay ?? false;
    this.gameSettings = data.gameSettings;
    this.playerName = data.playerName;
    // BUGFIX (post-drag-to-reorder manual test): Phaser scenes are
    // singleton instances -- this.scene.start('LobbyScene', ...) from
    // GameTableScene's win screen (see that file's renderWinScreen())
    // re-invokes init()/create() on the SAME LobbyScene instance
    // rather than constructing a fresh one, so any field not reset
    // here carries over from the previous game. quickPlayRequested
    // was never reset: it stayed `true` from the game that just
    // ended, which made onQuickPlayTapped()'s own guard
    // (`|| this.quickPlayRequested`) permanently reject every tap and
    // kept onConnectionState() dimming the button at alpha 0.5
    // forever -- "Quick Play vs AI" looked and behaved as if it was
    // dead until a full page reload re-ran this scene's constructor.
    // Resetting every piece of prior-game state that init()/create()
    // don't already overwrite unconditionally below.
    this.quickPlayRequested = false;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    const layout = this.currentLayout();

    this.statusText = this.add.text(layout.status.x, layout.status.y, 'Connecting…', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.status.fontPx}px`,
      color: theme.text,
    });

    this.identityText = this.add.text(layout.identity.x, layout.identity.y, '', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.identity.fontPx}px`,
      color: theme.text,
    });

    this.rankText = this.add.text(layout.rank.x, layout.rank.y, '', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.rank.fontPx}px`,
      color: theme.accent,
    });

    this.headerText = this.add.text(
      layout.leaderboardHeader.x,
      layout.leaderboardHeader.y,
      'Global Leaderboard',
      {
        fontFamily: 'sans-serif',
        fontSize: `${layout.leaderboardHeader.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      },
    );

    this.quickPlayButton = this.add
      .rectangle(
        layout.quickPlayButton.x + layout.quickPlayButton.width / 2,
        layout.quickPlayButton.y + layout.quickPlayButton.height / 2,
        layout.quickPlayButton.width,
        layout.quickPlayButton.height,
        0x2a5a34,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setAlpha(0.5) // dimmed until the connection is actually open
      .setInteractive({ useHandCursor: true });
    this.quickPlayLabel = this.add
      .text(this.quickPlayButton.x, this.quickPlayButton.y, 'Quick Play vs AI', {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
    this.quickPlayButton.on('pointerdown', () => this.onQuickPlayTapped());

    this.connection = new KadiConnection(this.adapter.getWebSocketUrl());
    this.unsubscribers = [
      this.connection.onStateChange((state) => this.onConnectionState(state)),
      this.connection.onMessage((msg) => this.onServerMessage(msg)),
    ];

    this.adapter.onReady(() => this.connection.connect());

    // Part A/B: Phaser's own Scale Manager RESIZE event (see index.ts's
    // scale config) -- fires on browser window resize, mobile
    // orientation change, and a host platform (Discord/Telegram)
    // resizing the surrounding iframe/panel. This is the ONE place
    // resize is handled; nothing here polls or listens to raw DOM
    // resize events itself.
    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
      // Unsubscribe rather than closing the connection -- a
      // successful Quick Play deliberately KEEPS it open and hands it
      // to GameTableScene (see this file's Part E docstring); only
      // this scene's own reactions to it need to stop.
      for (const unsub of this.unsubscribers) unsub();
      this.unsubscribers = [];
    });
  }

  /** Reads the current Scale Manager dimensions + this platform's
   * safe-area insets and runs them through computeLobbyLayout(). The
   * one call site every other method in this scene goes through --
   * never compute a position any other way. */
  private currentLayout(): LobbyLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeLobbyLayout(viewport, insets, this.lastEntries.length);
  }

  private handleResize(): void {
    const layout = this.currentLayout();

    this.statusText.setPosition(layout.status.x, layout.status.y);
    this.statusText.setFontSize(layout.status.fontPx);

    this.identityText.setPosition(layout.identity.x, layout.identity.y);
    this.identityText.setFontSize(layout.identity.fontPx);

    this.rankText.setPosition(layout.rank.x, layout.rank.y);
    this.rankText.setFontSize(layout.rank.fontPx);

    this.headerText.setPosition(layout.leaderboardHeader.x, layout.leaderboardHeader.y);
    this.headerText.setFontSize(layout.leaderboardHeader.fontPx);

    this.quickPlayButton.setPosition(
      layout.quickPlayButton.x + layout.quickPlayButton.width / 2,
      layout.quickPlayButton.y + layout.quickPlayButton.height / 2,
    );
    this.quickPlayButton.setSize(layout.quickPlayButton.width, layout.quickPlayButton.height);
    if (this.quickPlayButton.input) {
      // Keep the tap hit-area in sync with the visible rect size --
      // setInteractive() captured the size once at creation time, so
      // a resize needs to update it explicitly or taps would land
      // against the OLD (pre-resize) rectangle bounds.
      this.quickPlayButton.input.hitArea.width = layout.quickPlayButton.width;
      this.quickPlayButton.input.hitArea.height = layout.quickPlayButton.height;
    }
    this.quickPlayLabel.setPosition(this.quickPlayButton.x, this.quickPlayButton.y);

    // Leaderboard rows: re-render against the new layout rather than
    // just repositioning the existing Text objects -- a resize can
    // change maxVisibleRows (more/less room), so the row COUNT itself
    // may need to change, not just each row's x/y/fontSize.
    this.renderLeaderboard(this.lastEntries);
  }

  private onConnectionState(state: ConnectionState): void {
    const labels: Record<ConnectionState, string> = {
      connecting: 'Connecting…',
      open: 'Connected',
      // Shows the ACTUAL url being attempted -- not just "stuck", so
      // a stale VITE_WS_URL (still pointing at localhost on a phone,
      // where "localhost" means the phone itself, not the dev
      // machine), a firewall block, and a server that simply isn't
      // running are distinguishable from each other by looking at
      // the phone's own screen, without needing devtools/console
      // access on a device most testers won't have plugged into a
      // debugger. See PHONE_TESTING.md's troubleshooting section.
      reconnecting: `Reconnecting… (${this.connection.getUrl()})`,
      closed: 'Disconnected',
    };
    this.statusText.setText(labels[state]);
    // Quick Play only makes sense once 'hello' has actually gone out
    // -- gate it on the same 'open' transition sendHelloAndRequestLeaderboard
    // reacts to, not just on the button existing.
    this.quickPlayButton.setAlpha(state === 'open' && !this.quickPlayRequested ? 1 : 0.5);

    if (state === 'open') {
      void this.sendHelloAndRequestLeaderboard();
      if (this.autoQuickPlay) this.onQuickPlayTapped();
    }
  }

  private onQuickPlayTapped(): void {
    if (this.connection.getState() !== 'open' || this.quickPlayRequested) return;
    this.quickPlayRequested = true;
    this.quickPlayButton.setAlpha(0.5);
    this.quickPlayLabel.setText('Starting…');
    this.connection.send({
      type: 'create_game',
      settings: this.gameSettings ?? { ai_count: 1, ai_difficulty: 'MEDIUM' },
    });
  }

  private async sendHelloAndRequestLeaderboard(): Promise<void> {
    if (this.playerName) {
      // GameConfigScene's "Your Name" field -- applied before reading
      // getDisplayName() back so 'hello' carries what the player just
      // typed, not last session's stored name.
      await this.adapter.setDisplayName(this.playerName);
    }
    const name = await this.adapter.getDisplayName();
    const identity = await this.adapter.getPlatformIdentity();
    this.identityText.setText(`Playing as ${name}`);

    this.connection.send(
      identity
        ? { type: 'hello', name, platform: identity.platform, external_id: identity.externalId }
        : { type: 'hello', name },
    );
    this.connection.send({ type: 'get_leaderboard', n: 10 });
    this.connection.send({ type: 'get_my_rank' });
  }

  private onServerMessage(msg: ServerMessage): void {
    if (msg.type === 'leaderboard_result') {
      this.renderLeaderboard(msg.entries);
    } else if (msg.type === 'my_rank_result') {
      this.rankText.setText(
        msg.rank === null ? 'No wins recorded yet' : `Your rank: #${msg.rank} (${msg.wins} wins)`,
      );
    } else if (msg.type === 'welcome' && this.quickPlayRequested) {
      // We're seated -- as the (sole human) creator we're also always
      // the host, so ask the server to start immediately rather than
      // waiting on a lobby-browse UI this pass doesn't build (see this
      // file's Part E docstring).
      this.connection.send({ type: 'request_start_game' });
    } else if (msg.type === 'start_game' && this.quickPlayRequested) {
      this.scene.start('GameTableScene', { adapter: this.adapter, connection: this.connection });
    } else if (msg.type === 'reject' && this.quickPlayRequested) {
      // Let the player try again rather than leaving the button stuck
      // showing "Starting..." forever.
      this.quickPlayRequested = false;
      this.quickPlayLabel.setText('Quick Play vs AI');
      this.quickPlayButton.setAlpha(1);
      this.statusText.setText(`Connected -- ${msg.reason}`);
    }
  }

  private renderLeaderboard(entries: { name: string; wins: number }[]): void {
    this.lastEntries = entries;

    for (const line of this.leaderboardLines) line.destroy();
    this.leaderboardLines = [];

    const theme = this.adapter.getTheme();
    const layout = this.currentLayout();

    if (entries.length === 0) {
      // computeLobbyLayout() with entryCount 0 produces no row slots,
      // so this one "be the first!" line uses the header's own slot
      // math directly rather than layout.rows[0], which won't exist.
      const emptyLayout = computeLobbyLayout(
        { width: this.scale.width, height: this.scale.height },
        this.adapter.getSafeAreaInsets(),
        1,
      );
      const row = emptyLayout.rows[0];
      if (row) {
        const line = this.add.text(row.x, row.y, 'No wins recorded yet — be the first!', {
          fontFamily: 'sans-serif',
          fontSize: `${row.fontPx}px`,
          color: theme.text,
        });
        this.leaderboardLines.push(line);
      }
      return;
    }

    entries.forEach((entry, i) => {
      const row = layout.rows[i];
      if (!row) return; // beyond maxVisibleRows at this viewport size -- see LobbyLayout.ts
      const line = this.add.text(row.x, row.y, `${i + 1}. ${entry.name} — ${entry.wins} wins`, {
        fontFamily: 'sans-serif',
        fontSize: `${row.fontPx}px`,
        color: theme.text,
      });
      this.leaderboardLines.push(line);
    });
  }
}
