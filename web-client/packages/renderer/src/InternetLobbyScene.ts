/**
 * KADI web-client — InternetLobbyScene.
 *
 * This is the "real join/browse flow" §9 row: a genuine client build
 * against the ALREADY-WORKING server lobby (server/lobby.py,
 * server/kadi_server.py's create_game/join_game/rejoin_game/
 * request_start_game handling) -- no server changes anywhere in this
 * file's story. Ported from scenes.InternetLobbyScene's own behavior
 * (browse open games, host with a name, join by list or by name
 * search, wait for the host to start), reshaped into this renderer's
 * single-vertical-column layout (see layout/InternetLobbyLayout.ts's
 * own docstring for why) and Phaser-canvas-only rendering (§6).
 *
 * Reached from ModeSelectScene's "Internet Multiplayer" button
 * (replacing the plain LobbyScene routing that used to land there --
 * LobbyScene itself is now reachable only... it isn't, from the menu;
 * it remains in the codebase as the Quick-Play-vs-AI scene, unchanged,
 * per this task's "don't touch GameTableScene's existing gameplay
 * beyond the minimum" instruction extended sensibly to LobbyScene's
 * own untouched Quick Play flow).
 *
 * STATE MACHINE:
 *   'browse' -- host form + search field + open-games list, polled
 *               every LIST_REFRESH_SECS (mirrors scenes.py's own
 *               constant) while this state is active.
 *   'lobby'  -- the waiting room: roster (mirrors the PC's roster
 *               display), Start button (host only, enabled once
 *               there are >= MIN_PLAYERS), Back leaves the room.
 * A successful 'start_game' hands the SAME already-open KadiConnection
 * to GameTableScene, exactly as LobbyScene's Quick Play already does
 * (see that file's Part E note on why a second connection would NOT
 * be a continuation of this one's room membership) -- plus this room's
 * gameId/reconnectToken, which GameTableScene now also accepts (Part
 * D: mid-game reconnect wiring, see that file's own note).
 *
 * PART D -- RECONNECT, AND ITS ACTUAL SERVER-SIDE LIMIT: rejoin_game
 * only works once server/game_room.py's GameRoom has actually
 * started (`GameRoom.reconnect()`: `if not self.started or ...:
 * return False`). A drop while 'browse' or 'lobby' (pre-start) is NOT
 * covered by any grace period at all -- server/kadi_server.py's
 * `_handle_disconnect()` removes a pre-start member from its room
 * IMMEDIATELY (closing the room outright if that member was host), no
 * waiting, no token. That's an existing, unmodified server behavior
 * (this task doesn't touch server/), not a gap this client can paper
 * over with a client-side retry -- attempting rejoin_game here would
 * just collect an honest 'reject' back. So: a transport drop during
 * 'browse' needs nothing special (the list simply resumes polling once
 * KadiConnection's own auto-reconnect reopens the socket -- see
 * connection.ts's scheduleReconnect()). A transport drop during
 * 'lobby' (waiting room, pre-start) is reported plainly and the scene
 * returns to 'browse' with a status line explaining why, rather than
 * silently trying and failing a rejoin_game the server was never going
 * to honor. The one place rejoin_game genuinely helps -- a drop
 * AFTER start_game, mid-match -- is handled in GameTableScene, which
 * this scene hands gameId/reconnectToken to precisely so it can.
 */
import Phaser from 'phaser';
import { KadiConnection } from '@kadi/client-core';
import type { ConnectionState } from '@kadi/client-core';
import type { GameSummary, ServerMessage } from '@kadi/protocol';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeInternetLobbyBrowseLayout,
  computeInternetLobbyRosterLayout,
  type InternetLobbyBrowseLayout,
  type InternetLobbyRosterLayout,
} from './layout/InternetLobbyLayout.js';
import { StatusTextGuard } from './statusText.js';

/** Mirrors scenes.InternetLobbyScene's own LIST_REFRESH_SECS exactly
 * (scenes.py), in milliseconds for Phaser's time.addEvent(). */
const LIST_REFRESH_MS = 1500;
const MAX_NAME_LEN = 40;

type UiState = 'browse' | 'lobby';

interface RosterPlayer {
  player_id: number;
  name: string;
}

interface RowObjects {
  text: Phaser.GameObjects.Text;
  joinRect: Phaser.GameObjects.Rectangle;
  joinLabel: Phaser.GameObjects.Text;
}

export class InternetLobbyScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  private connection!: KadiConnection;
  private unsubscribers: (() => void)[] = [];

  private uiState: UiState = 'browse';

  // ── browse-state data ──
  private games: GameSummary[] = [];
  private gameNameInput = '';
  private searchInput = '';
  private activeField: 'name' | 'search' | null = null;
  private joinRequested = false;
  private hostRequested = false;
  private listTimer: Phaser.Time.TimerEvent | null = null;

  // ── lobby (waiting-room) state data ──
  private gameId: string | null = null;
  private reconnectToken: string | null = null;
  private myPlayerId: number | null = null;
  private hostId: number | null = null;
  private roomGameName = '';
  private players: RosterPlayer[] = [];
  private startRequested = false;

  private statusMessage = '';

  // ── browse GameObjects ──
  private browseTitle!: Phaser.GameObjects.Text;
  private hostLabel!: Phaser.GameObjects.Text;
  private gameNameRect!: Phaser.GameObjects.Rectangle;
  private gameNameText!: Phaser.GameObjects.Text;
  private hostButtonRect!: Phaser.GameObjects.Rectangle;
  private hostButtonLabel!: Phaser.GameObjects.Text;
  private searchRect!: Phaser.GameObjects.Rectangle;
  private searchText!: Phaser.GameObjects.Text;
  private listHeaderText!: Phaser.GameObjects.Text;
  private rowObjects: RowObjects[] = [];
  private browseBackRect!: Phaser.GameObjects.Rectangle;
  private browseBackLabel!: Phaser.GameObjects.Text;
  private browseStatusText!: Phaser.GameObjects.Text;
  // Part A -- same minimum-display-duration guard as GameTableScene's
  // statusTextGuard (see statusText.ts's docstring). Every write to
  // browseStatusText goes through this from create() onward; there is
  // no terminal/bypass case here (unlike GameTableScene's "Could not
  // reconnect"), so every call site below uses .show().
  private browseStatusTextGuard!: StatusTextGuard;

  // ── lobby (roster) GameObjects ──
  private lobbyTitle!: Phaser.GameObjects.Text;
  private lobbySubtitle!: Phaser.GameObjects.Text;
  private rosterHeaderText!: Phaser.GameObjects.Text;
  private rosterLines: Phaser.GameObjects.Text[] = [];
  private startRect!: Phaser.GameObjects.Rectangle;
  private startLabel!: Phaser.GameObjects.Text;
  private lobbyBackRect!: Phaser.GameObjects.Rectangle;
  private lobbyBackLabel!: Phaser.GameObjects.Text;

  constructor() {
    super('InternetLobbyScene');
  }

  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
    // Same singleton-Scene-instance caveat LobbyScene.ts's init()
    // documents: this.scene.start('InternetLobbyScene', ...) re-runs
    // init()/create() on the SAME instance, so every piece of prior-
    // session state needs an explicit reset here.
    this.uiState = 'browse';
    this.games = [];
    this.gameNameInput = '';
    this.searchInput = '';
    this.activeField = null;
    this.joinRequested = false;
    this.hostRequested = false;
    this.gameId = null;
    this.reconnectToken = null;
    this.myPlayerId = null;
    this.hostId = null;
    this.roomGameName = '';
    this.players = [];
    this.startRequested = false;
    this.statusMessage = '';
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    // Connection MUST exist before any UI is built: buildBrowseUi()'s
    // internal renderGameRows() -> applyUiState() -> startListPolling()
    // chain reads this.connection.getState() synchronously during
    // create() itself (to decide whether to fire an immediate
    // list_games), not just later from user interaction. Building the
    // UI first (as an earlier fix here did, to solve a DIFFERENT
    // ordering bug -- see the lobby-before-browse note below) left
    // this one connection-vs-UI ordering bug exposed the moment that
    // first bug was fixed. Same root cause both times: this scene has
    // three things with real cross-dependencies at construction time
    // (connection, lobby UI, browse UI) and only one of the three
    // possible orderings has no forward reference. This is that one:
    // connection, then lobby UI, then browse UI.
    this.connection = new KadiConnection(this.adapter.getWebSocketUrl());
    this.unsubscribers = [
      this.connection.onStateChange((state) => this.onConnectionState(state)),
      this.connection.onMessage((msg) => this.onServerMessage(msg)),
    ];
    this.adapter.onReady(() => this.connection.connect());

    // buildBrowseUi() ends by calling renderGameRows(), which calls
    // applyUiState() -- and applyUiState() toggles visibility on BOTH
    // the browse AND lobby (waiting-room) GameObjects, since it's the
    // single function that switches between them. So the lobby UI
    // must exist FIRST, or applyUiState() throws reading .setVisible()
    // on lobby fields that are still undefined (this crashed every
    // real browser load -- headless layout/protocol tests never
    // exercise this create() path, which is how it got through).
    this.buildLobbyUi();
    this.buildBrowseUi();
    // Fresh guard every create() -- browseStatusText itself is a brand
    // new GameObject each time create() runs (buildBrowseUi() above),
    // so any leftover lastShownAtMs from a previous visit to this
    // scene instance must not suppress this visit's first message.
    this.browseStatusTextGuard = new StatusTextGuard(
      (text) => this.browseStatusText.setText(text),
      () => this.time.now,
    );
    this.applyUiState();

    const kb = this.input.keyboard;
    if (kb) kb.on('keydown', this.onKeyDown, this);

    // A tap anywhere that ISN'T one of the two text fields blurs
    // whichever field is currently active -- mirrors a normal mobile
    // text-field UX (tap elsewhere to dismiss focus) without needing
    // a real DOM input element (§6 rendering discipline).
    this.input.on('pointerdown', (_p: unknown, currentlyOver: Phaser.GameObjects.GameObject[]) => {
      if (currentlyOver.length === 0) this.activeField = null;
    });

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
      if (kb) kb.off('keydown', this.onKeyDown, this);
      this.stopListPolling();
      for (const unsub of this.unsubscribers) unsub();
      this.unsubscribers = [];
    });
  }

  // ── layout plumbing ──────────────────────────────────────────────

  private currentBrowseLayout(): InternetLobbyBrowseLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeInternetLobbyBrowseLayout(viewport, insets, this.filteredGames().length);
  }

  private currentRosterLayout(): InternetLobbyRosterLayout {
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeInternetLobbyRosterLayout(viewport, insets, this.players.length);
  }

  /** Ported verbatim from scenes.InternetLobbyScene._filtered_games():
   * case-insensitive substring match against BOTH the game's own name
   * and its host's name, so typing a friend's name finds their hosted
   * game exactly as fast as typing the game's own name would. Empty
   * query returns every open game unfiltered (browse-by-list path). */
  private filteredGames(): GameSummary[] {
    const q = this.searchInput.trim().toLowerCase();
    if (!q) return this.games;
    return this.games.filter(
      (g) => g.game_name.toLowerCase().includes(q) || g.host_name.toLowerCase().includes(q),
    );
  }

  // ── UI construction ──────────────────────────────────────────────

  private buildBrowseUi(): void {
    const theme = this.adapter.getTheme();
    const layout = this.currentBrowseLayout();

    this.browseTitle = this.add
      .text(layout.title.x, layout.title.y, 'Internet Multiplayer', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.title.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5, 0);

    this.hostLabel = this.add.text(layout.hostLabel.x, layout.hostLabel.y, 'Host a game:', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.hostLabel.fontPx}px`,
      color: theme.text,
    });

    this.gameNameRect = this.add
      .rectangle(
        layout.gameNameField.x + layout.gameNameField.width / 2,
        layout.gameNameField.y + layout.gameNameField.height / 2,
        layout.gameNameField.width,
        layout.gameNameField.height,
        0x1c1c1c,
      )
      .setStrokeStyle(1, 0xffffff, 0.5)
      .setInteractive({ useHandCursor: true });
    this.gameNameText = this.add
      .text(this.gameNameRect.x, this.gameNameRect.y, this.gameNamePlaceholder(), {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#aaaaaa',
      })
      .setOrigin(0.5);
    this.gameNameRect.on('pointerdown', () => {
      this.activeField = 'name';
    });

    this.hostButtonRect = this.add
      .rectangle(
        layout.hostButton.x + layout.hostButton.width / 2,
        layout.hostButton.y + layout.hostButton.height / 2,
        layout.hostButton.width,
        layout.hostButton.height,
        0x2a5a34,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setAlpha(0.5)
      .setInteractive({ useHandCursor: true });
    this.hostButtonLabel = this.add
      .text(this.hostButtonRect.x, this.hostButtonRect.y, layout.hostButton.label, {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
    this.hostButtonRect.on('pointerdown', () => this.onHostTapped());

    this.searchRect = this.add
      .rectangle(
        layout.searchField.x + layout.searchField.width / 2,
        layout.searchField.y + layout.searchField.height / 2,
        layout.searchField.width,
        layout.searchField.height,
        0x1c1c1c,
      )
      .setStrokeStyle(1, 0xffffff, 0.5)
      .setInteractive({ useHandCursor: true });
    this.searchText = this.add
      .text(this.searchRect.x, this.searchRect.y, 'Search by game or host name…', {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#aaaaaa',
      })
      .setOrigin(0.5);
    this.searchRect.on('pointerdown', () => {
      this.activeField = 'search';
    });

    this.listHeaderText = this.add.text(layout.listHeader.x, layout.listHeader.y, 'Open games (0):', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.listHeader.fontPx}px`,
      color: theme.text,
      fontStyle: 'bold',
    });

    this.browseBackRect = this.add
      .rectangle(
        layout.backButton.x + layout.backButton.width / 2,
        layout.backButton.y + layout.backButton.height / 2,
        layout.backButton.width,
        layout.backButton.height,
        0x505050,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setInteractive({ useHandCursor: true });
    this.browseBackLabel = this.add
      .text(this.browseBackRect.x, this.browseBackRect.y, 'Back', {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
    this.browseBackRect.on('pointerdown', () => this.onBackTapped());

    this.browseStatusText = this.add.text(layout.backButton.x, layout.backButton.y - 22, '', {
      fontFamily: 'sans-serif',
      fontSize: '11px',
      color: '#ff8080',
    });

    this.renderGameRows();
  }

  private buildLobbyUi(): void {
    const theme = this.adapter.getTheme();
    const layout = this.currentRosterLayout();

    this.lobbyTitle = this.add
      .text(layout.title.x, layout.title.y, 'Waiting Room', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.title.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5, 0);

    this.lobbySubtitle = this.add
      .text(layout.subtitle.x, layout.subtitle.y, '', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.subtitle.fontPx}px`,
        color: theme.accent,
      })
      .setOrigin(0.5, 0);

    this.rosterHeaderText = this.add.text(layout.rosterHeader.x, layout.rosterHeader.y, 'Players (0):', {
      fontFamily: 'sans-serif',
      fontSize: `${layout.rosterHeader.fontPx}px`,
      color: theme.text,
      fontStyle: 'bold',
    });

    this.startRect = this.add
      .rectangle(
        layout.startButton.x + layout.startButton.width / 2,
        layout.startButton.y + layout.startButton.height / 2,
        layout.startButton.width,
        layout.startButton.height,
        0x2a5a34,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setAlpha(0.5)
      .setInteractive({ useHandCursor: true });
    this.startLabel = this.add
      .text(this.startRect.x, this.startRect.y, 'Start Game', {
        fontFamily: 'sans-serif',
        fontSize: '14px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
    this.startRect.on('pointerdown', () => this.onStartTapped());

    this.lobbyBackRect = this.add
      .rectangle(
        layout.backButton.x + layout.backButton.width / 2,
        layout.backButton.y + layout.backButton.height / 2,
        layout.backButton.width,
        layout.backButton.height,
        0x505050,
      )
      .setStrokeStyle(1, 0xffffff, 0.6)
      .setInteractive({ useHandCursor: true });
    this.lobbyBackLabel = this.add
      .text(this.lobbyBackRect.x, this.lobbyBackRect.y, 'Leave', {
        fontFamily: 'sans-serif',
        fontSize: '13px',
        color: '#ffffff',
      })
      .setOrigin(0.5);
    this.lobbyBackRect.on('pointerdown', () => this.onBackTapped());
  }

  private gameNamePlaceholder(): string {
    return this.gameNameInput || 'Your game name (optional)';
  }

  /** Toggles which button/panel group is visible for the current
   * uiState -- both groups' GameObjects exist the whole time (simpler
   * than tearing down/rebuilding on every transition); only their
   * visibility and the list-poll timer are switched. */
  private applyUiState(): void {
    const browseVisible = this.uiState === 'browse';
    const browseObjects: Phaser.GameObjects.GameObject[] = [
      this.browseTitle,
      this.hostLabel,
      this.gameNameRect,
      this.gameNameText,
      this.hostButtonRect,
      this.hostButtonLabel,
      this.searchRect,
      this.searchText,
      this.listHeaderText,
      this.browseBackRect,
      this.browseBackLabel,
      this.browseStatusText,
      ...this.rowObjects.flatMap((r) => [r.text, r.joinRect, r.joinLabel]),
    ];
    for (const obj of browseObjects) (obj as Phaser.GameObjects.Text | undefined)?.setVisible(browseVisible);

    const lobbyObjects: Phaser.GameObjects.GameObject[] = [
      this.lobbyTitle,
      this.lobbySubtitle,
      this.rosterHeaderText,
      this.startRect,
      this.startLabel,
      this.lobbyBackRect,
      this.lobbyBackLabel,
      ...this.rosterLines,
    ];
    // Both `?.` guards here are a deliberate safety net, not just
    // style: this function is reached mid-create() (via
    // buildBrowseUi() -> renderGameRows()) before both UI groups are
    // guaranteed to exist yet -- an earlier build order bug called
    // this with the lobby group still undefined and crashed the whole
    // scene with an uncaught TypeError (only ever hit in a real
    // browser; the headless layout/protocol tests never exercise
    // create()). Guarding here means a future reordering mistake
    // degrades to "a button doesn't toggle visibility yet" instead of
    // taking the whole scene down.
    for (const obj of lobbyObjects) (obj as Phaser.GameObjects.Text | undefined)?.setVisible(!browseVisible);

    if (browseVisible) {
      this.startListPolling();
    } else {
      this.stopListPolling();
    }
  }

  // ── list polling (Part B) ───────────────────────────────────────

  private startListPolling(): void {
    if (this.listTimer) return;
    // Guards against being reached before this.connection exists --
    // this function is called synchronously from within create()'s
    // own UI-build chain (buildBrowseUi() -> renderGameRows() ->
    // applyUiState()), so a future reordering mistake here should
    // degrade to "polling starts once the connection shows up" rather
    // than crash the scene the way an unguarded read already has
    // twice during this feature's real-browser testing.
    if (!this.connection) return;
    if (this.connection.getState() === 'open') this.connection.send({ type: 'list_games' });
    this.listTimer = this.time.addEvent({
      delay: LIST_REFRESH_MS,
      loop: true,
      callback: () => {
        if (this.connection.getState() === 'open') this.connection.send({ type: 'list_games' });
      },
    });
  }

  private stopListPolling(): void {
    this.listTimer?.remove();
    this.listTimer = null;
  }

  // ── connection lifecycle ────────────────────────────────────────

  private onConnectionState(state: ConnectionState): void {
    if (state === 'open') {
      void this.sendHello();
      if (this.uiState === 'browse' && this.listTimer) {
        this.connection.send({ type: 'list_games' });
      } else if (this.uiState === 'lobby') {
        // A drop happened while waiting in a not-yet-started room --
        // see this file's own header docstring on why rejoin_game
        // cannot resume a pre-start room (server/game_room.py's
        // reconnect() requires `self.started`, and the pre-start
        // disconnect path removes the member immediately with no
        // grace period). The honest move is to say so and go back to
        // browsing, not to fire a rejoin_game the server was always
        // going to reject.
        this.uiState = 'browse';
        this.statusMessage = 'Connection dropped while waiting -- you were removed from that room. Reconnected to Browse.';
        this.browseStatusTextGuard.show(this.statusMessage);
        this.applyUiState();
      }
    } else if (state === 'reconnecting' && this.uiState === 'browse') {
      this.browseStatusTextGuard.show('Reconnecting…');
    }
  }

  private async sendHello(): Promise<void> {
    const name = await this.adapter.getDisplayName();
    const identity = await this.adapter.getPlatformIdentity();
    this.connection.send(
      identity
        ? { type: 'hello', name, platform: identity.platform, external_id: identity.externalId }
        : { type: 'hello', name },
    );
  }

  private onServerMessage(msg: ServerMessage): void {
    if (msg.type === 'games_list') {
      this.games = msg.games;
      this.renderGameRows();
      return;
    }
    if (msg.type === 'welcome') {
      // Fired by either create_game (we're the host) or join_game (we
      // joined someone else's room) -- server/kadi_server.py builds
      // this identically for both, see WelcomeMsg's own docstring.
      this.gameId = msg.game_id;
      this.hostId = msg.host_id;
      this.myPlayerId = msg.player_id;
      this.reconnectToken = msg.reconnect_token;
      this.hostRequested = false;
      this.joinRequested = false;
      this.uiState = 'lobby';
      this.statusMessage = '';
      this.applyUiState();
      this.renderRoster();
      return;
    }
    if (msg.type === 'lobby_state') {
      this.players = msg.players;
      this.roomGameName = msg.game_name;
      this.hostId = msg.host_id;
      this.renderRoster();
      return;
    }
    if (msg.type === 'room_closed' && this.uiState === 'lobby') {
      this.uiState = 'browse';
      this.gameId = null;
      this.reconnectToken = null;
      this.statusMessage = msg.reason;
      this.browseStatusTextGuard.show(this.statusMessage);
      this.applyUiState();
      return;
    }
    if (msg.type === 'start_game') {
      this.scene.start('GameTableScene', {
        adapter: this.adapter,
        connection: this.connection,
        gameId: this.gameId ?? undefined,
        reconnectToken: this.reconnectToken ?? undefined,
      });
      return;
    }
    if (msg.type === 'reject') {
      this.hostRequested = false;
      this.joinRequested = false;
      this.startRequested = false;
      this.statusMessage = msg.reason;
      if (this.uiState === 'browse') {
        this.browseStatusTextGuard.show(this.statusMessage);
        this.hostButtonLabel.setText('Host a New Game');
      } else {
        // A reject while in 'lobby' is only ever the host's own
        // request_start_game being refused (e.g. not enough players)
        // -- surface it on the subtitle line, which is otherwise just
        // "Waiting for host..."/"You are the host".
        this.lobbySubtitle.setText(this.statusMessage);
        this.startLabel.setText('Start Game');
      }
      this.applyUiState();
      return;
    }
  }

  // ── actions ──────────────────────────────────────────────────────

  private onHostTapped(): void {
    if (this.connection.getState() !== 'open' || this.hostRequested) return;
    this.hostRequested = true;
    this.hostButtonLabel.setText('Hosting…');
    const settings = this.gameNameInput.trim() ? { game_name: this.gameNameInput.trim() } : {};
    this.connection.send({ type: 'create_game', settings });
  }

  private onJoinTapped(gameId: string): void {
    if (this.connection.getState() !== 'open' || this.joinRequested) return;
    this.joinRequested = true;
    this.browseStatusTextGuard.show('Joining…');
    this.connection.send({ type: 'join_game', game_id: gameId });
  }

  private onStartTapped(): void {
    if (this.uiState !== 'lobby' || this.startRequested) return;
    if (this.myPlayerId !== this.hostId) return; // not the host -- button is disabled anyway
    if (this.players.length < 2) return; // MIN_PLAYERS, mirrors server/game_room.py
    this.startRequested = true;
    this.startLabel.setText('Starting…');
    this.connection.send({ type: 'request_start_game' });
  }

  private onBackTapped(): void {
    if (this.uiState === 'lobby') {
      // No explicit "leave_game" message exists on the wire (see
      // messages.ts) -- closing this connection is exactly how
      // scenes.InternetLobbyScene's own Back/Cancel behaves too
      // (a plain disconnect), which server/kadi_server.py's
      // _handle_disconnect() already handles correctly pre-start.
      this.connection.close();
      this.scene.start('ModeSelectScene', { adapter: this.adapter });
    } else {
      this.connection.close();
      this.scene.start('ModeSelectScene', { adapter: this.adapter });
    }
  }

  // ── keyboard text-field handling ────────────────────────────────

  private onKeyDown(event: KeyboardEvent): void {
    if (!this.activeField) return;
    const isName = this.activeField === 'name';
    let current = isName ? this.gameNameInput : this.searchInput;

    if (event.key === 'Enter' || event.key === 'Escape') {
      this.activeField = null;
    } else if (event.key === 'Backspace') {
      current = current.slice(0, -1);
    } else if (event.key.length === 1 && current.length < MAX_NAME_LEN) {
      current += event.key;
    } else {
      return;
    }

    if (isName) {
      this.gameNameInput = current;
      this.gameNameText.setText(this.gameNamePlaceholder());
      this.gameNameText.setColor(current ? '#ffffff' : '#aaaaaa');
    } else {
      this.searchInput = current;
      this.searchText.setText(current || 'Search by game or host name…');
      this.searchText.setColor(current ? '#ffffff' : '#aaaaaa');
      this.renderGameRows();
    }
  }

  // ── rendering ────────────────────────────────────────────────────

  private renderGameRows(): void {
    for (const row of this.rowObjects) {
      row.text.destroy();
      row.joinRect.destroy();
      row.joinLabel.destroy();
    }
    this.rowObjects = [];

    const theme = this.adapter.getTheme();
    const layout = this.currentBrowseLayout();
    const filtered = this.filteredGames();

    this.listHeaderText.setText(
      `Open games (${filtered.length}${this.searchInput.trim() ? ` of ${this.games.length}` : ''}):`,
    );

    if (filtered.length === 0) {
      // computeInternetLobbyBrowseLayout() with gameCount 0 (this
      // scene's own currentBrowseLayout() passes filteredGames().length)
      // produces zero row slots -- same "recompute with count 1 just
      // for this one placeholder line" workaround LobbyScene.ts's
      // renderLeaderboard() uses for its own empty state.
      const emptyLayout = computeInternetLobbyBrowseLayout(
        { width: this.scale.width, height: this.scale.height },
        this.adapter.getSafeAreaInsets(),
        1,
      );
      const emptyRow = emptyLayout.rows[0];
      if (emptyRow) {
        const msg = this.searchInput.trim()
          ? `No open games matching "${this.searchInput.trim()}".`
          : 'No open games right now -- host one above!';
        const text = this.add.text(emptyRow.x, emptyRow.y, msg, {
          fontFamily: 'sans-serif',
          fontSize: `${emptyRow.fontPx}px`,
          color: theme.text,
        });
        // Placeholder-only row -- no Join button for it, but it still
        // needs to participate in visibility toggling/cleanup like
        // every other row object, so it's tracked the same way with
        // zero-size, non-interactive stand-ins for the other two.
        const stub1 = this.add.rectangle(-1000, -1000, 1, 1).setVisible(false);
        const stub2 = this.add.text(-1000, -1000, '').setVisible(false);
        this.rowObjects.push({ text, joinRect: stub1, joinLabel: stub2 });
      }
      this.applyUiState();
      return;
    }

    filtered.forEach((game, i) => {
      const row = layout.rows[i];
      if (!row) return; // beyond maxVisibleRows at this viewport -- see InternetLobbyLayout.ts
      const displayName = game.game_name || `${game.host_name}'s game`;
      const text = this.add.text(
        row.x,
        row.y,
        `${displayName} — ${game.host_name} (${game.player_count}/${game.max_players})`,
        { fontFamily: 'sans-serif', fontSize: `${row.fontPx}px`, color: theme.text },
      );
      const joinRect = this.add
        .rectangle(
          row.joinButton.x + row.joinButton.width / 2,
          row.joinButton.y + row.joinButton.height / 2,
          row.joinButton.width,
          row.joinButton.height,
          0x2a5a34,
        )
        .setStrokeStyle(1, 0xffffff, 0.6)
        .setInteractive({ useHandCursor: true });
      const joinLabel = this.add
        .text(joinRect.x, joinRect.y, 'Join', {
          fontFamily: 'sans-serif',
          fontSize: '12px',
          color: '#ffffff',
        })
        .setOrigin(0.5);
      joinRect.on('pointerdown', () => this.onJoinTapped(game.game_id));
      this.rowObjects.push({ text, joinRect, joinLabel });
    });

    this.applyUiState();
  }

  private renderRoster(): void {
    for (const line of this.rosterLines) line.destroy();
    this.rosterLines = [];

    const theme = this.adapter.getTheme();
    const layout = this.currentRosterLayout();

    this.lobbyTitle.setText(this.roomGameName || 'Waiting Room');
    const iAmHost = this.myPlayerId !== null && this.myPlayerId === this.hostId;
    this.lobbySubtitle.setText(iAmHost ? 'You are the host' : 'Waiting for the host to start…');
    this.rosterHeaderText.setText(`Players (${this.players.length}):`);

    this.players.forEach((p, i) => {
      const row = layout.rows[i];
      if (!row) return;
      const tags: string[] = [];
      if (p.player_id === this.hostId) tags.push('host');
      if (p.player_id === this.myPlayerId) tags.push('you');
      const suffix = tags.length ? ` (${tags.join(', ')})` : '';
      const line = this.add.text(row.x, row.y, `${i + 1}. ${p.name}${suffix}`, {
        fontFamily: 'sans-serif',
        fontSize: `${row.fontPx}px`,
        color: theme.text,
      });
      this.rosterLines.push(line);
    });

    const canStart = iAmHost && this.players.length >= 2 && !this.startRequested;
    this.startRect.setAlpha(canStart ? 1 : 0.5);
    this.startRect.disableInteractive();
    if (canStart) this.startRect.setInteractive({ useHandCursor: true });
    if (!iAmHost) this.startLabel.setText('Waiting for host…');
    else if (!this.startRequested) this.startLabel.setText('Start Game');

    this.applyUiState();
  }

  // ── resize ───────────────────────────────────────────────────────

  private handleResize(): void {
    if (this.uiState === 'browse') {
      const layout = this.currentBrowseLayout();
      this.browseTitle.setPosition(layout.title.x, layout.title.y);
      this.browseTitle.setFontSize(layout.title.fontPx);
      this.hostLabel.setPosition(layout.hostLabel.x, layout.hostLabel.y);
      this.hostLabel.setFontSize(layout.hostLabel.fontPx);
      this.repositionRect(this.gameNameRect, layout.gameNameField);
      this.gameNameText.setPosition(this.gameNameRect.x, this.gameNameRect.y);
      this.repositionRect(this.hostButtonRect, layout.hostButton);
      this.hostButtonLabel.setPosition(this.hostButtonRect.x, this.hostButtonRect.y);
      this.repositionRect(this.searchRect, layout.searchField);
      this.searchText.setPosition(this.searchRect.x, this.searchRect.y);
      this.listHeaderText.setPosition(layout.listHeader.x, layout.listHeader.y);
      this.listHeaderText.setFontSize(layout.listHeader.fontPx);
      this.repositionRect(this.browseBackRect, layout.backButton);
      this.browseBackLabel.setPosition(this.browseBackRect.x, this.browseBackRect.y);
      this.browseStatusText.setPosition(layout.backButton.x, layout.backButton.y - 22);
      this.renderGameRows();
    } else {
      const layout = this.currentRosterLayout();
      this.lobbyTitle.setPosition(layout.title.x, layout.title.y);
      this.lobbyTitle.setFontSize(layout.title.fontPx);
      this.lobbySubtitle.setPosition(layout.subtitle.x, layout.subtitle.y);
      this.lobbySubtitle.setFontSize(layout.subtitle.fontPx);
      this.rosterHeaderText.setPosition(layout.rosterHeader.x, layout.rosterHeader.y);
      this.rosterHeaderText.setFontSize(layout.rosterHeader.fontPx);
      this.repositionRect(this.startRect, layout.startButton);
      this.startLabel.setPosition(this.startRect.x, this.startRect.y);
      this.repositionRect(this.lobbyBackRect, layout.backButton);
      this.lobbyBackLabel.setPosition(this.lobbyBackRect.x, this.lobbyBackRect.y);
      this.renderRoster();
    }
  }

  private repositionRect(
    rect: Phaser.GameObjects.Rectangle,
    box: { x: number; y: number; width: number; height: number },
  ): void {
    rect.setPosition(box.x + box.width / 2, box.y + box.height / 2);
    rect.setSize(box.width, box.height);
    if (rect.input) {
      rect.input.hitArea.width = box.width;
      rect.input.hitArea.height = box.height;
    }
  }
}
