/**
 * KADI - the game-table scene: seats, hands, piles, turn flow, the
 * POST_PLAY "Yes! KADI / Proceed" panel, the pick-up-N badge and
 * "must pick" banner, the Jump counter window, suit picking, pause,
 * and the win screen.
 *
 * RENDERING DISCIPLINE (plan §6): every element is a Phaser
 * GameObject drawn on the canvas -- Rectangle/Text/Graphics, never an
 * HTML element -- same rule LobbyScene follows, for the same reason
 * (a WeChat build has no DOM to put an HTML element into). Cards are
 * drawn as code (rounded rect + rank/suit text), not image sprites --
 * there is no card-art asset pipeline in this web client yet (see
 * this file's own note below), and canvas-drawn text scales exactly
 * like every other UI element here rather than needing a separate
 * image-scaling story.
 *
 * LAYOUT DISCIPLINE: every position/size comes from
 * layout/GameTableLayout.ts's computeGameTableLayout() /
 * computeLocalHandSlots(), recomputed on every genuine viewport
 * change AND on every new state_sync (hand size changes every
 * draw/play) -- see currentLayout()/render() below. This is the same
 * "call the pure function, apply the numbers" shape LobbyScene
 * established; see GameTableLayout.ts's own docstring for what it
 * ports from the Python client and what it deliberately doesn't.
 *
 * CONNECTION OWNERSHIP: this scene does NOT open its own
 * KadiConnection. It's handed the SAME connection LobbyScene already
 * authenticated ('hello' already sent) and used to create/join this
 * room -- the server's room membership is keyed by conn_id
 * (server/game_room.py), so opening a second WebSocket here would be
 * a brand-new, room-less connection, not a continuation of the one
 * that's actually seated at this table. See LobbyScene.ts's Quick
 * Play wiring (Part E) for how this scene gets started with that
 * connection already open and the room already created.
 *
 * SCOPE CUTS, STATED PLAINLY (see also GameTableLayout.ts's own
 * scope-cut note and packages/protocol/src/messages.ts's file-level
 * note):
 * - No card-art image assets -- cards are drawn as rounded rects with
 *   rank/suit text, using the same suit colors/symbols
 *   constants.py's SUIT_COLOR/SUIT_SYMBOL define.
 * - Drag-to-reorder (own hand only, purely local/cosmetic -- see
 *   handOrder.ts's file-level docstring for why no server round-trip
 *   is needed) ported from scenes.py's _reorder_hand /
 *   rendering/board_renderer.py's HandRenderer drag rendering; tap
 *   still selects any number of cards with one explicit "Play" tap to
 *   commit (see Part D's touch-target notes below for why an explicit
 *   confirm step is used here instead of committing on first tap the
 *   way a mouse click-to-play could) -- a press-and-hold-then-move
 *   past a small threshold reorders instead of selecting, same
 *   threshold-based disambiguation scenes.py's mouse handler uses.
 * - Multi-card sequence legality (question chains, K/J bundles, ACE
 *   suit-shield mixing) is NOT mirrored client-side -- the server is
 *   the sole legality authority for anything beyond a single card
 *   (see core/rule_engine.py's is_valid_sequence and friends). The
 *   playable-highlight on each card only reflects the SINGLE-card
 *   is_playable()/_can_counter_pickup() rules ported in
 *   cardPlayability.ts. Selecting and "Play"-ing an illegal multi-card
 *   combo is simply a no-op server-side (handle_intent returns
 *   without acting) -- same silent-reject behavior every other
 *   invalid intent already gets.
 * - No pre-declared KADI at play time (IntentPlayMsg.declare_kadi is
 *   never set true here) -- the POST_PLAY "Yes! KADI" button covers
 *   the primary declare-on-your-last-card flow, which is the only one
 *   this scene implements.
 * - Reconnect (rejoin_game) IS wired in now (Part D of the Internet-
 *   multiplayer-flow task): if gameId/reconnectToken are provided at
 *   init() (see InternetLobbyScene.ts, which hands them over on
 *   start_game), a transport drop that later reopens (KadiConnection's
 *   own auto-reconnect, see connection.ts's scheduleReconnect())
 *   triggers a fresh 'hello' + 'rejoin_game' automatically -- see
 *   onConnectionState()/onServerMessage()'s 'rejoined' handling below.
 *   This only works because server/game_room.py's reconnect() only
 *   requires the room to have STARTED, which is exactly this scene's
 *   whole lifetime -- unlike the pre-start browse/waiting-room case
 *   (see InternetLobbyScene.ts's own header note on why rejoin_game
 *   canNOT help there). A Quick-Play-vs-AI game (no gameId/token
 *   passed) simply never attempts this -- same "Reconnecting..."-only
 *   behavior as before for that path.
 * - No chat UI, no invite/share flow, no elimination-mode spectator
 *   view, no MSOMI model attachment -- none of these are asked for by
 *   the task brief's Parts A-E and are left for a later pass.
 */
import Phaser from 'phaser';
import type { KadiConnection } from '@kadi/client-core';
import type { ConnectionState } from '@kadi/client-core';
import type {
  CardDict,
  ChatBroadcastMsg,
  GameSummaryMsg,
  RoomClosedMsg,
  ServerMessage,
  StateSyncMsg,
  SuitName,
} from '@kadi/protocol';
import type { PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeGameTableLayout,
  computeLocalHandSlots,
  getDropIndex,
  type CardSlot,
  type GameTableLayout,
} from './layout/GameTableLayout.js';
import { isCardPlayable } from './cardPlayability.js';
import { moveCard, reconcileHandOrder } from './handOrder.js';
import { StatusTextGuard } from './statusText.js';
import { HelpOverlay } from './HelpOverlay.js';
import { GAMEPLAY_HELP } from './layout/HELP_CONTENT.js';
import {
  applyGameSummary,
  BADGE_DEFS,
  defaultProfile,
  mergeProfile,
  resolveTableCosmetics,
  type ProfileData,
  type TableCosmetics,
} from './profileData.js';

// constants.py's SUIT_SYMBOL / SUIT_COLOR, ported for card-text
// rendering -- see this file's own scope-cut note on why there's no
// image art to draw instead.
const SUIT_SYMBOL: Record<SuitName, string> = {
  SPADES: '♠',
  LOVE: '♥',
  DICE: '♦',
  FLOWERS: '♣',
};
const SUIT_COLOR: Record<SuitName, string> = {
  SPADES: '#2a2a3a',
  LOVE: '#d84a4a',
  DICE: '#d99a34',
  FLOWERS: '#3fae5a',
};
// constants.py's RANK_DISPLAY -- only 'ACE' differs from its own name.
function rankDisplay(rank: string): string {
  return rank === 'ACE' ? 'A' : rank === 'JOKER' ? 'JKR' : rank;
}

function cardLabel(card: CardDict): string {
  if (card.rank === 'JOKER') return 'JKR';
  return `${rankDisplay(card.rank)}${card.suit ? SUIT_SYMBOL[card.suit] : ''}`;
}

function cardColor(card: CardDict): string {
  if (card.rank === 'JOKER') return card.is_red_joker ? '#d84a4a' : '#2a2a3a';
  return card.suit ? SUIT_COLOR[card.suit] : '#2a2a3a';
}

/** Mirrors GameManager._next_active_idx's role closely enough for
 * display purposes: walks the seat list in `step` direction, skipping
 * finished players, without mutating any server state -- this is only
 * used to name who the "must pick N!" banner is currently pointing at
 * during the one-tick POST_PLAY window before current_player_idx
 * itself has advanced (see _draw_turn_indicator's own comment on the
 * same double-advance pitfall this mirrors). */
function nextActiveSeat(players: StateSyncMsg['players'], fromIdx: number, step: number): number {
  const n = players.length;
  if (n === 0) return fromIdx;
  let idx = fromIdx;
  for (let i = 0; i < n; i++) {
    idx = ((idx + step) % n + n) % n;
    if (!players[idx].finished) return idx;
  }
  return fromIdx;
}

export class GameTableScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  // Part D (cosmetics equip actually affecting the table): resolved
  // once in create() from the SAME persisted profile ProfileScene.ts
  // reads/writes (WebAdapter's `kadi.web.profile` key, via
  // adapter.getProfile()), through the same pure
  // resolveTableCosmetics() ProfileScene.ts's equip flow is verified
  // against in __tests__/tableCosmetics.test.ts. Starts at the
  // 'default' resolution (defaultProfile()'s own cosmetics) so the
  // very first render() (before the async getProfile() resolves) has
  // a real value rather than needing a null-check at every call site;
  // re-resolved and re-render()'d once the fetch actually returns.
  // Loaded once per seating at the table, not live-reloaded while
  // playing -- equipping a new cosmetic requires leaving to
  // ProfileScene first, same as PC's own self.assets/table cosmetics
  // being fixed for the duration of a running game.
  private tableCosmetics: TableCosmetics = resolveTableCosmetics(defaultProfile());
  private connection!: KadiConnection;

  // Part D -- reconnect (rejoin_game). Only ever set when this scene
  // was reached via InternetLobbyScene's start_game handoff (see that
  // file); a Quick-Play-vs-AI game leaves both null, and the reconnect
  // logic below is simply never triggered for it. `awaitingRejoin`
  // becomes true the moment the connection actually drops (not on the
  // scene's own initial 'open' check in create() -- see
  // onConnectionState()) and stays true until a 'rejoined'/'reject'
  // reply resolves it.
  private gameId: string | null = null;
  private reconnectToken: string | null = null;
  private awaitingRejoin = false;

  private lastSync: StateSyncMsg | null = null;
  private helpOverlay!: HelpOverlay;
  private selected = new Set<number>();
  private dynamic: Phaser.GameObjects.GameObject[] = [];
  private statusText!: Phaser.GameObjects.Text;
  // Part A -- minimum-display-duration guard around statusText.setText()
  // (see statusText.ts's own docstring for the bug this fixes: a fast
  // reconnect cycle setting 'Reconnecting…' and clearing it again
  // before a frame ever paints it). Every write to statusText goes
  // through this from create() onward -- see onConnectionState() /
  // onServerMessage() below -- except the terminal "Could not
  // reconnect" case, which deliberately bypasses it via showImmediate().
  private statusTextGuard!: StatusTextGuard;
  private unsubscribers: (() => void)[] = [];

  // Locally-remembered display order for MY OWN hand only -- see
  // handOrder.ts's file-level docstring for why this exists (the
  // server has no notion of hand order at all) and reconcileHandOrder's
  // docstring for how it survives the next state_sync. Populated by
  // reconciling against `sync.players[...].hand` on every state_sync,
  // NOT read directly off the sync elsewhere -- renderLocalHand/
  // renderPlayButton/renderCounterPanel all index into THIS, so
  // `this.selected`'s indices stay meaningful across a drag.
  private myHandOrder: CardDict[] = [];

  // Drag-to-reorder state (Prompt 1, §9) -- direct port of scenes.py's
  // _drag_idx/_drag_pos/_drag_target/_drag_start_pos/_drag_pending_idx
  // and its _drag_threshold. dragPendingIdx/dragStartPos track a
  // pointer-down that HASN'T yet moved past the threshold (so it's
  // still ambiguous between "tap to select" and "drag to reorder");
  // dragIdx/dragPos/dragTarget are only set once the threshold is
  // crossed. See handlePointerMove/handlePointerUp below.
  private dragIdx: number | null = null;
  private dragPos: { x: number; y: number } | null = null;
  private dragTarget: number | null = null;
  private dragStartPos: { x: number; y: number } | null = null;
  private dragPendingIdx: number | null = null;
  private readonly dragThreshold = 8;
  private newlyEarnedBadgeIds: string[] = [];
  private gameSummaryApplied = false;

  constructor() {
    super('GameTableScene');
  }

  init(data: {
    adapter: PlatformAdapter;
    connection: KadiConnection;
    gameId?: string;
    reconnectToken?: string;
  }): void {
    this.adapter = data.adapter;
    this.connection = data.connection;
    this.gameId = data.gameId ?? null;
    this.reconnectToken = data.reconnectToken ?? null;
    this.awaitingRejoin = false;
    this.lastSync = null;
    this.selected = new Set();
    this.dynamic = [];
    this.unsubscribers = [];
    this.myHandOrder = [];
    this.clearDragState();
    this.newlyEarnedBadgeIds = [];
    this.gameSummaryApplied = false;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    this.tableCosmetics = resolveTableCosmetics(defaultProfile());
    void this.adapter.getProfile().then((stored) => {
      const profile: ProfileData = mergeProfile(stored as Partial<ProfileData> | null);
      this.tableCosmetics = resolveTableCosmetics(profile);
      this.render();
    });

    this.statusText = this.add.text(8, 8, '', {
      fontFamily: 'sans-serif',
      fontSize: '12px',
      color: '#ff8080',
    });
    this.statusText.setDepth(100);
    // Fresh guard every create() -- this scene instance can be reused
    // across scene.start() transitions (see this file's other reset-
    // on-init() precedent), so a leftover lastShownAtMs from a
    // previous seating at this table must not suppress this game's
    // very first status message.
    this.statusTextGuard = new StatusTextGuard(
      (text) => this.statusText.setText(text),
      () => this.time.now,
    );

    this.unsubscribers.push(
      this.connection.onMessage((msg) => this.onServerMessage(msg)),
      this.connection.onStateChange((state) => this.onConnectionState(state)),
    );
    this.onConnectionState(this.connection.getState());

    // Help Overlay -- ported from scenes.GameplayScene.HELP_SECTIONS,
    // see HELP_CONTENT.ts. Its idle-glow accrual is turn-gated (see
    // update() below) -- one deviation from every other help-enabled
    // screen, matching GameplayScene.update()'s own one deviation.
    this.helpOverlay = new HelpOverlay(this, this.adapter, GAMEPLAY_HELP);
    this.helpOverlay.create();

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    // Scene-wide (not per-card-rect) pointer tracking for drag-to-reorder:
    // once a card's own 'pointerdown' arms dragStartPos/dragPendingIdx (see
    // renderLocalHand below), the drag itself needs to keep tracking the
    // pointer even after it moves off that specific card's rect -- Phaser
    // unifies mouse and touch into these same Pointer events, so this one
    // pair of listeners drives both input types without special-casing.
    this.input.on(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.on(Phaser.Input.Events.POINTER_UP, this.handlePointerUp, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
      this.input.off(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
      this.input.off(Phaser.Input.Events.POINTER_UP, this.handlePointerUp, this);
      this.helpOverlay.destroy();
      for (const unsub of this.unsubscribers) unsub();
      this.unsubscribers = [];
    });
  }

  private onConnectionState(state: ConnectionState): void {
    const labels: Record<ConnectionState, string> = {
      connecting: '',
      open: '',
      reconnecting: 'Reconnecting…',
      closed: 'Disconnected',
    };
    this.statusTextGuard.show(labels[state]);

    if (state === 'reconnecting' && this.gameId && this.reconnectToken) {
      // The transport just dropped -- remember that the NEXT 'open' is
      // a genuine post-drop reconnect (needing rejoin_game), not this
      // scene's own initial create()-time state check below.
      this.awaitingRejoin = true;
    } else if (state === 'open' && this.awaitingRejoin && this.gameId && this.reconnectToken) {
      void this.attemptRejoin(this.gameId, this.reconnectToken);
    }
  }

  /** A fresh WebSocket (new conn_id server-side -- the old one is
   * gone) presenting our saved token, trying to resume the SAME seat
   * before server/game_room.py's reconnect() grace period lapses. See
   * this file's own header note on why this only works post-start. */
  private async attemptRejoin(gameId: string, token: string): Promise<void> {
    const name = await this.adapter.getDisplayName();
    const identity = await this.adapter.getPlatformIdentity();
    this.connection.send(
      identity
        ? { type: 'hello', name, platform: identity.platform, external_id: identity.externalId }
        : { type: 'hello', name },
    );
    this.connection.send({ type: 'rejoin_game', game_id: gameId, token });
  }

  private onServerMessage(msg: ServerMessage): void {
    if (msg.type === 'state_sync') {
      this.lastSync = msg;
      // Reconcile OUR OWN locally-dragged display order against
      // whatever set of cards the server just sent (see handOrder.ts) --
      // must happen before the selected-index cleanup below, since
      // `this.selected`'s indices are indices into `myHandOrder`, not
      // into the server's own hand order.
      const previousHandLen = this.myHandOrder.length;
      const me = msg.players.find((p) => p.player_id === msg.you);
      this.myHandOrder = reconcileHandOrder(this.myHandOrder, me?.hand ?? []);
      // Drop any selected index that no longer exists in the new hand
      // (its size can shrink on a play or grow on a draw between two
      // renders) -- defensive, since the server is what actually
      // moves cards, not anything this scene predicts locally.
      const myHandLen = this.myHandOrder.length;
      for (const idx of [...this.selected]) {
        if (idx >= myHandLen) this.selected.delete(idx);
      }
      // Only cancel an in-progress press/drag if the hand's actual
      // CONTENTS changed under it (a play or draw genuinely completed).
      // server/kadi_server.py's tick() re-broadcasts state_sync on
      // EVERY server tick (TICK_HZ = 20, i.e. every ~50ms) regardless
      // of whether anything actually changed -- so unconditionally
      // clearing drag state here on every state_sync (as an earlier
      // version of this handler did) wipes dragStartPos/dragPendingIdx
      // within milliseconds of a pointerdown, before the user's
      // pointerup can ever arrive, silently breaking BOTH drag-to-
      // reorder AND plain tap-to-select. Comparing hand length before/
      // after reconciliation catches the one case that actually needs
      // this (indices shifting out from under an in-progress drag)
      // without firing on every redundant no-op heartbeat tick.
      if (myHandLen !== previousHandLen) {
        this.clearDragState();
      }
      this.render();
    } else if (msg.type === 'chat') {
      this.onChat(msg);
    } else if (msg.type === 'room_closed') {
      this.onRoomClosed(msg);
    } else if (msg.type === 'game_summary') {
      this.onGameSummary(msg);
    } else if (msg.type === 'rejoined') {
      // Successfully resumed the same seat after a drop -- clear the
      // "Reconnecting..." status text; the next state_sync (already on
      // its way, server/kadi_server.py's tick() broadcasts on every
      // tick) repaints the table itself. reconnect_token is re-sent
      // unchanged by the server (see RejoinedMsg's own docstring) but
      // stored again anyway in case that ever changes.
      this.awaitingRejoin = false;
      this.reconnectToken = msg.reconnect_token ?? this.reconnectToken;
      this.statusTextGuard.show('');
    } else if (msg.type === 'reject' && this.awaitingRejoin) {
      // Our rejoin_game attempt was refused -- per this file's header
      // note, this means the grace period lapsed or the room is gone;
      // there is no seat left to return to. Report it plainly and
      // leave the table rather than sitting on a dead connection.
      // showImmediate(), not show(): this terminal message must win
      // unconditionally and instantly -- it already held correctly
      // for its own explicit 2s before this file's Part A bug was
      // ever found, and that exact behavior must not change now.
      this.awaitingRejoin = false;
      this.statusTextGuard.showImmediate(`Could not reconnect — ${msg.reason}`);
      this.connection.close();
      this.time.delayedCall(2000, () => {
        this.scene.start('ModeSelectScene', { adapter: this.adapter });
      });
    }
    // games_list/leaderboard_result/welcome/etc: not meaningful once
    // seated at a table -- ignored here, same as LobbyScene ignoring
    // anything outside its own scope.
  }

  private onChat(_msg: ChatBroadcastMsg): void {
    // No chat UI in this pass (see file-level scope-cut note) --
    // messages are received and simply not displayed rather than
    // left unhandled/erroring.
  }

  private onRoomClosed(_msg: RoomClosedMsg): void {
    // Mid-game this shouldn't normally fire (server/kadi_server.py
    // only sends it for a PRE-start lobby closing) -- handled
    // defensively anyway by returning to the lobby with a fresh
    // connection rather than sitting on a dead room.
    this.connection.close();
    this.scene.start('LobbyScene', { adapter: this.adapter });
  }

  /** Profile Part 5 disclosure (§9) -- server/kadi_server.py sends
   * this exactly once, right at the GAME_OVER transition (see
   * GameSummaryMsg's own doc comment in @kadi/protocol). Re-fetches
   * the profile fresh here rather than reusing create()'s own
   * getProfile() snapshot from scene start -- a game can run long
   * enough that ProfileScene.ts's cosmetic-equip flow, or a badge
   * from a DIFFERENT already-finished game in another tab, could have
   * written to the same adapter storage since then; read-modify-write
   * against the current value avoids clobbering that. */
  private onGameSummary(msg: GameSummaryMsg): void {
    // The server only ever sends this once per room (see
    // server/kadi_server.py's tick()) -- guarded here too, belt and
    // braces against ever double-crediting the local profile if this
    // handler were somehow invoked twice (e.g. a future reconnect-
    // replay path).
    if (this.gameSummaryApplied) return;
    this.gameSummaryApplied = true;
    void this.adapter.getProfile().then((stored) => {
      const profile: ProfileData = mergeProfile(stored as Partial<ProfileData> | null);
      this.newlyEarnedBadgeIds = applyGameSummary(profile, msg);
      this.tableCosmetics = resolveTableCosmetics(profile);
      void this.adapter.saveProfile({ ...profile });
      this.render();
    });
  }

  private myHandLength(sync: StateSyncMsg): number {
    const me = sync.players.find((p) => p.player_id === sync.you);
    return me?.hand?.length ?? 0;
  }

  private handleResize(): void {
    this.helpOverlay.layout();
    this.render();
  }

  /** Whether idle time should accrue right now -- mirrors
   * GameplayScene.update()'s own `self.gm.current_player.is_human and
   * not self.gm.is_paused` check (scenes.py ~7880): waiting on the AI,
   * or a paused game, isn't "stuck," so the nudge shouldn't count that
   * time. Same condition renderLocalHand() already computes locally as
   * `myTurnToAct`, duplicated here since that one's scoped to a single
   * render() call and this needs to run every frame regardless of
   * whether a render happened. */
  private isMyActionableTurn(): boolean {
    const sync = this.lastSync;
    if (!sync || sync.state === 'PAUSED') return false;
    return (
      (sync.state === 'PLAYING' && sync.current_player_idx === sync.you) ||
      (sync.state === 'JUMP_COUNTER_WINDOW' && sync.counter_player_idx === sync.you)
    );
  }

  update(_time: number, delta: number): void {
    this.helpOverlay.update(delta, this.isMyActionableTurn());
  }

  private currentLayout(): GameTableLayout | null {
    if (!this.lastSync) return null;
    const viewport = { width: this.scale.width, height: this.scale.height };
    const insets = this.adapter.getSafeAreaInsets();
    return computeGameTableLayout(viewport, insets, {
      numPlayers: this.lastSync.players.length,
      localHandCount: this.myHandLength(this.lastSync),
    });
  }

  private clearDynamic(): void {
    for (const obj of this.dynamic) obj.destroy();
    this.dynamic = [];
  }

  private track<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.dynamic.push(obj);
    return obj;
  }

  // ── the one render pass every state_sync/resize runs ─────────────
  private render(): void {
    const sync = this.lastSync;
    const layout = this.currentLayout();
    this.clearDynamic();
    if (!sync || !layout) return;

    const theme = this.adapter.getTheme();
    // Own hand renders/hit-tests against the locally-reconciled display
    // order (myHandOrder), not the raw sync -- see the state_sync
    // handler above and handOrder.ts's docstring for why.
    const myHand = this.myHandOrder;

    this.renderTable(layout);
    this.renderSeats(sync, layout);
    this.renderPiles(sync, layout);
    this.renderBanners(sync, layout);
    this.renderLocalHand(sync, myHand, layout);

    if (sync.state === 'POST_PLAY' && sync.post_play) {
      this.renderActionPanel(sync, layout);
    } else if (sync.state === 'SUIT_PICK') {
      this.renderSuitPick(sync, layout);
    } else if (sync.state === 'JUMP_COUNTER_WINDOW') {
      this.renderCounterPanel(sync, layout);
      this.renderPlayButton(sync, myHand, layout); // countering is "Play" with J(s) selected
    } else if (sync.state === 'PLAYING' || sync.state === 'KADI_DECLARED') {
      this.renderPlayButton(sync, myHand, layout);
      this.renderDrawButton(sync, layout);
    } else if (sync.state === 'PAUSED') {
      this.renderPauseOverlay(layout);
    }

    if (sync.state === 'GAME_OVER') {
      this.renderWinScreen(sync, layout, theme.text);
    }
  }

  // ── table felt + piles ────────────────────────────────────────────
  private renderTable(layout: GameTableLayout): void {
    // Part D: felt fill/edge come from the equipped felt theme
    // (this.tableCosmetics, resolved in create() -- see that field's
    // own comment), not a fixed color -- the one place equipping a
    // theme in ProfileScene actually changes what this scene draws.
    const g = this.track(this.add.graphics());
    g.fillStyle(this.tableCosmetics.feltFill, 1);
    g.fillEllipse(layout.tableCenter.x, layout.tableCenter.y, layout.tableRadiusX * 2, layout.tableRadiusY * 2);
    g.lineStyle(3, this.tableCosmetics.feltEdge, 1);
    g.strokeEllipse(layout.tableCenter.x, layout.tableCenter.y, layout.tableRadiusX * 2, layout.tableRadiusY * 2);
  }

  private renderPiles(sync: StateSyncMsg, layout: GameTableLayout): void {
    // Part D: the draw pile's back uses the equipped card back's
    // primary color (this.tableCosmetics.cardBackA) -- see
    // renderSeats() below for the same applied to opponents' hidden
    // cards, and this file's `tableCosmetics` field for where it's
    // resolved from.
    const back = (box: { x: number; y: number; width: number; height: number }, alpha = 1) =>
      this.track(
        this.add
          .rectangle(box.x + box.width / 2, box.y + box.height / 2, box.width, box.height, this.tableCosmetics.cardBackA, alpha)
          .setStrokeStyle(2, 0xffffff, 0.5),
      );

    back(layout.drawPile);
    this.track(
      this.add.text(layout.drawPileLabel.x, layout.drawPileLabel.y, `Draw (${sync.deck.draw_count})`, {
        fontFamily: 'sans-serif',
        fontSize: `${layout.drawPileLabel.fontPx}px`,
        color: '#ffffff',
      }).setOrigin(0.5, 0),
    );

    const top = sync.rule_engine.top_card;
    if (top) {
      const rect = back(layout.discardPile);
      rect.setFillStyle(0xffffff, 1).setStrokeStyle(2, 0xd9a441, 1);
      this.track(
        this.add
          .text(layout.discardPile.x + layout.discardPile.width / 2, layout.discardPile.y + layout.discardPile.height / 2, cardLabel(top), {
            fontFamily: 'sans-serif',
            fontSize: `${Math.round(layout.cardWidth * 0.32)}px`,
            color: cardColor(top),
            fontStyle: 'bold',
          })
          .setOrigin(0.5),
      );
    } else {
      back(layout.discardPile, 0.3);
    }
    this.track(
      this.add.text(layout.discardPileLabel.x, layout.discardPileLabel.y, 'Discard', {
        fontFamily: 'sans-serif',
        fontSize: `${layout.discardPileLabel.fontPx}px`,
        color: '#ffffff',
      }).setOrigin(0.5, 0),
    );

    if (sync.rule_engine.current_suit) {
      const suit = sync.rule_engine.current_suit;
      this.track(
        this.add
          .text(layout.suitIndicator.x, layout.suitIndicator.y, `${SUIT_SYMBOL[suit]}\nsuit`, {
            fontFamily: 'sans-serif',
            fontSize: `${layout.suitIndicator.fontPx}px`,
            color: SUIT_COLOR[suit],
            align: 'center',
          })
          .setOrigin(1, 0.5),
      );
    }

    if (sync.pickup_pending_display > 0) {
      this.track(
        this.add
          .text(layout.pickupBadge.x, layout.pickupBadge.y, `Pick up: +${sync.pickup_pending_display}`, {
            fontFamily: 'sans-serif',
            fontSize: `${layout.pickupBadge.fontPx}px`,
            color: '#dc5050',
            backgroundColor: '#501414',
            padding: { x: 8, y: 4 },
          })
          .setOrigin(0, 0.5),
      );

      let targetIdx = sync.current_player_idx;
      if (sync.state === 'POST_PLAY') {
        targetIdx = nextActiveSeat(sync.players, sync.current_player_idx, sync.direction === 'CLOCKWISE' ? 1 : -1);
      }
      const target = sync.players[targetIdx];
      if (target) {
        this.track(
          this.add
            .text(
              layout.mustPickBanner.x,
              layout.mustPickBanner.y,
              `${target.name} must pick ${sync.pickup_pending_display}!`,
              {
                fontFamily: 'sans-serif',
                fontSize: `${layout.mustPickBanner.fontPx}px`,
                color: '#dc5050',
                backgroundColor: '#3c0a0a',
                padding: { x: 8, y: 4 },
              },
            )
            .setOrigin(0, 0.5),
        );
      }
    }
  }

  private renderBanners(sync: StateSyncMsg, layout: GameTableLayout): void {
    let text: string;
    let color: string;
    if (sync.state === 'JUMP_COUNTER_WINDOW') {
      const cp = sync.players[sync.counter_player_idx];
      const played = sync.last_played_cards.map(cardLabel).join(' ');
      text = played ? `Counter with a J — ${cp?.name ?? '?'} (played: ${played})` : `Counter with a J — ${cp?.name ?? '?'}`;
      color = '#ff8c00';
    } else {
      const current = sync.players[sync.current_player_idx];
      if (current?.has_declared_kadi) {
        text = `${current.name} — KADI declared!`;
        color = '#dc3232';
      } else {
        text = `${current?.name ?? '?'}'s turn`;
        color = '#f0d060';
      }
    }
    this.track(
      this.add
        .text(layout.turnBanner.x, layout.turnBanner.y, text, {
          fontFamily: 'sans-serif',
          fontSize: `${layout.turnBanner.fontPx}px`,
          color,
          backgroundColor: '#000000',
          padding: { x: 10, y: 4 },
        })
        .setOrigin(0.5, 0)
        .setAlpha(0.9),
    );

    this.track(
      this.add
        .text(
          layout.directionBadge.x,
          layout.directionBadge.y,
          sync.direction === 'CLOCKWISE' ? 'Clockwise' : 'Anti-clockwise',
          {
            fontFamily: 'sans-serif',
            fontSize: `${layout.directionBadge.fontPx}px`,
            color: '#78c878',
            backgroundColor: '#000000',
            padding: { x: 6, y: 3 },
          },
        )
        .setOrigin(0, 1)
        .setAlpha(0.8),
    );
  }

  private renderSeats(sync: StateSyncMsg, layout: GameTableLayout): void {
    for (const seat of layout.seats) {
      const player = sync.players[seat.seatOffset === 0 ? sync.you : this.seatOffsetToPlayerIdx(sync, seat.seatOffset)];
      if (!player) continue;
      if (!seat.isLocal) {
        // Opponent: a compact face-down stack, not a full fan (Part
        // B's opponent-hand-indicator geometry) -- just enough
        // back-card art to read as "a hand", sized off the shared
        // card size so it scales identically to the local fan. Part D:
        // colored with the equipped card back's primary color, same
        // as the draw pile (renderPiles() above).
        this.track(
          this.add
            .rectangle(seat.handCenter.x, seat.handCenter.y, layout.cardWidth * 0.9, layout.cardHeight * 0.9, this.tableCosmetics.cardBackA)
            .setStrokeStyle(2, this.tableCosmetics.cardBackB, 0.6),
        );
      }
      const isCurrent = sync.current_player_idx === player.player_id && sync.state !== 'GAME_OVER';
      this.track(
        this.add
          .text(
            seat.badge.x,
            seat.badge.y,
            `${player.name}${seat.isLocal ? '' : ` (${player.hand_count})`}${player.finished ? ' ✓' : ''}`,
            {
              fontFamily: 'sans-serif',
              fontSize: `${seat.badge.fontPx}px`,
              color: isCurrent ? '#f0d060' : '#ffffff',
              backgroundColor: '#000000',
              padding: { x: 6, y: 2 },
            },
          )
          .setOrigin(0.5, seat.isLocal ? 1 : 0)
          .setAlpha(0.85),
      );
    }
  }

  /** layout.seats indexes opponents by seatOffset (distance from the
   * local player around the table), but sync.players indexes by real
   * server seat (player_id) -- this walks from `you` outward by
   * offset to find which real player_id a given seatOffset names.
   * Turn order in the real game follows direction/jump/kickback logic
   * this scene doesn't reimplement, so this deliberately uses a
   * fixed, simple seat-id ordering (seat (you+offset) mod n) for
   * WHERE to draw someone, independent of whose turn it currently is
   * -- exactly like the Python client's own table seating, which
   * never rearranges seats mid-game just because the direction or
   * current player changed. */
  private seatOffsetToPlayerIdx(sync: StateSyncMsg, offset: number): number {
    const n = sync.players.length;
    return (sync.you + offset) % n;
  }

  private renderLocalHand(sync: StateSyncMsg, hand: CardDict[], layout: GameTableLayout): void {
    const slots = computeLocalHandSlots(layout, hand.length);
    const pickupPending = sync.rule_engine.pickup_pending > 0;
    const myTurnToAct =
      (sync.state === 'PLAYING' && sync.current_player_idx === sync.you) ||
      (sync.state === 'JUMP_COUNTER_WINDOW' && sync.counter_player_idx === sync.you);

    slots.forEach((slot: CardSlot, idx: number) => {
      const card = hand[idx];
      if (!card) return;
      // The card being dragged is drawn separately as a floating card,
      // on top of everything else, below -- direct port of
      // HandRenderer.render's "continue" over drag_idx (board_renderer.py).
      if (idx === this.dragIdx && this.dragPos !== null) return;

      const isSelected = this.selected.has(idx);
      const playable = myTurnToAct
        ? isCardPlayable(card, sync.rule_engine, pickupPending)
        : false;
      const lift = isSelected ? slot.height * 0.18 : 0;

      // Shift cards to show an insertion gap while a drag is in
      // progress -- direct port of HandRenderer.render's identical
      // gap-shift math (board_renderer.py), just in the opposite
      // (center-point) coordinate convention this module already uses.
      let x = slot.x;
      if (this.dragIdx !== null && this.dragTarget !== null) {
        if (this.dragIdx < this.dragTarget) {
          if (this.dragIdx < idx && idx <= this.dragTarget) x -= slot.width / 2;
        } else if (this.dragIdx > this.dragTarget) {
          if (this.dragTarget <= idx && idx < this.dragIdx) x += slot.width / 2;
        }
      }

      const rect = this.track(
        this.add
          .rectangle(x, slot.y - lift, slot.width, slot.height, 0xffffff)
          .setStrokeStyle(isSelected ? 3 : playable ? 2 : 1, isSelected ? 0xd9a441 : playable ? 0x60c060 : 0x888888),
      );
      this.track(
        this.add
          .text(x, slot.y - lift, cardLabel(card), {
            fontFamily: 'sans-serif',
            fontSize: `${Math.round(slot.width * 0.32)}px`,
            color: cardColor(card),
            fontStyle: 'bold',
          })
          .setOrigin(0.5),
      );

      if (myTurnToAct) {
        rect.setInteractive({ useHandCursor: true });
        // Defer the tap-vs-drag decision to pointerup (handlePointerUp)
        // -- pointerdown here only ARMS tracking, same as scenes.py's
        // MOUSEBUTTONDOWN handler setting _drag_start_pos/
        // _drag_pending_idx and waiting for either a threshold-crossing
        // move (-> drag) or a button-up with no such move (-> a plain
        // select tap). This scene-wide pointermove/pointerup pair (see
        // create()) is what lets the drag keep tracking once the
        // pointer moves off this specific card's rect.
        rect.on('pointerdown', (pointer: Phaser.Input.Pointer) => {
          this.dragStartPos = { x: pointer.x, y: pointer.y };
          this.dragPendingIdx = idx;
        });
      }
    });

    // Draw the floating dragged card on top of everything above --
    // direct port of HandRenderer.render's identical floating-card pass
    // (board_renderer.py), using the ORIGINAL (undragged) card width/
    // height for the floating card's own size, same as that version.
    if (this.dragIdx !== null && this.dragPos !== null && this.dragIdx < hand.length) {
      const card = hand[this.dragIdx];
      const cw = layout.cardWidth;
      const ch = layout.cardHeight;
      const fx = this.dragPos.x;
      const fy = this.dragPos.y - 10 * layout.scale;
      this.track(
        this.add
          .rectangle(fx, fy, cw, ch, 0xffffff)
          .setStrokeStyle(3, 0xd9a441),
      );
      this.track(
        this.add
          .text(fx, fy, cardLabel(card), {
            fontFamily: 'sans-serif',
            fontSize: `${Math.round(cw * 0.32)}px`,
            color: cardColor(card),
            fontStyle: 'bold',
          })
          .setOrigin(0.5),
      );
    }
  }

  // ── drag-to-reorder: scene-wide pointer tracking (Prompt 1, §9) ───
  // Direct port of scenes.py's MOUSEMOTION/MOUSEBUTTONUP handling for
  // the human hand -- see this file's own scope-cut note (now updated)
  // and handOrder.ts's docstring for the local-only reordering model.
  private clearDragState(): void {
    this.dragIdx = null;
    this.dragPos = null;
    this.dragTarget = null;
    this.dragStartPos = null;
    this.dragPendingIdx = null;
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    if (this.dragStartPos === null) return;
    if (this.dragIdx === null) {
      // Not yet past the drag threshold -- check whether this move
      // crosses it (scenes.py's _drag_threshold check).
      const dx = pointer.x - this.dragStartPos.x;
      const dy = pointer.y - this.dragStartPos.y;
      if (Math.abs(dx) <= this.dragThreshold && Math.abs(dy) <= this.dragThreshold) return;
      this.dragIdx = this.dragPendingIdx;
      if (this.dragIdx !== null) this.selected.delete(this.dragIdx);
    }
    this.dragPos = { x: pointer.x, y: pointer.y };
    const layout = this.currentLayout();
    if (layout) {
      const slots = computeLocalHandSlots(layout, this.myHandOrder.length);
      this.dragTarget = getDropIndex(slots, pointer.x);
    }
    this.render();
  }

  private handlePointerUp(): void {
    if (this.dragIdx !== null && this.dragTarget !== null) {
      // Complete the reorder (scenes.py's MOUSEBUTTONUP handling).
      if (this.dragIdx !== this.dragTarget) {
        this.myHandOrder = moveCard(this.myHandOrder, this.dragIdx, this.dragTarget);
        this.selected.clear();
      }
      this.clearDragState();
      this.render();
    } else if (this.dragStartPos !== null && this.dragPendingIdx !== null) {
      // Never crossed the drag threshold -- it was a plain select tap.
      const idx = this.dragPendingIdx;
      if (this.selected.has(idx)) this.selected.delete(idx);
      else this.selected.add(idx);
      this.dragStartPos = null;
      this.dragPendingIdx = null;
      this.render();
    } else {
      this.dragStartPos = null;
    }
  }

  // ── explicit action buttons (Part D: touch-only input) ────────────
  private drawButton(box: { x: number; y: number; width: number; height: number; label: string }, onTap: () => void, fillColor = 0x2a5a34): void {
    const rect = this.track(
      this.add.rectangle(box.x + box.width / 2, box.y + box.height / 2, box.width, box.height, fillColor).setStrokeStyle(1, 0xffffff, 0.6),
    );
    this.track(
      this.add.text(box.x + box.width / 2, box.y + box.height / 2, box.label, {
        fontFamily: 'sans-serif',
        fontSize: '14px',
        color: '#ffffff',
      }).setOrigin(0.5),
    );
    rect.setInteractive({ useHandCursor: true });
    rect.on('pointerdown', onTap);
  }

  private renderDrawButton(sync: StateSyncMsg, layout: GameTableLayout): void {
    if (sync.current_player_idx !== sync.you) return;
    this.drawButton(layout.drawButton, () => {
      this.connection.send({ type: 'intent_draw' });
    });
  }

  private renderPlayButton(sync: StateSyncMsg, hand: CardDict[], layout: GameTableLayout): void {
    if (this.selected.size === 0) return;
    const isCounter = sync.state === 'JUMP_COUNTER_WINDOW';
    const cards = [...this.selected].sort((a, b) => a - b).map((i) => hand[i]);
    const label = isCounter ? 'Counter' : 'Play';
    this.drawButton({ ...layout.playButton, label }, () => {
      if (isCounter) {
        this.connection.send({ type: 'intent_counter', cards });
      } else {
        this.connection.send({ type: 'intent_play', cards });
      }
      this.selected.clear();
    });
  }

  private renderActionPanel(sync: StateSyncMsg, layout: GameTableLayout): void {
    const postPlay = sync.post_play!;
    const isActive = postPlay.player_id === sync.you;
    const panel = layout.actionPanel;
    const bg = this.track(
      this.add
        .rectangle(panel.x + panel.width / 2, panel.y + panel.height / 2, panel.width, panel.height, isActive ? 0x0f3714 : 0x121c14, isActive ? 0.95 : 0.5)
        .setStrokeStyle(2, isActive ? 0xd9a441 : 0xaaaaaa, isActive ? 0.9 : 0.3),
    );
    void bg;

    if (isActive) {
      this.track(
        this.add
          .text(panel.x + panel.width / 2, panel.y + 6, postPlay.can_kadi ? 'KADI eligible!' : 'Next player', {
            fontFamily: 'sans-serif',
            fontSize: '12px',
            color: postPlay.can_kadi ? '#f0d060' : '#ffffff',
          })
          .setOrigin(0.5, 0),
      );
      this.drawButton(panel.kadiButton, () => {
        this.connection.send({ type: 'intent_post_play_declare_kadi' });
      }, 0xa01414);
      this.drawButton(panel.proceedButton, () => {
        this.connection.send({ type: 'intent_post_play_proceed' });
      }, 0x1e4626);
    } else {
      const waitingOn = sync.players.find((p) => p.player_id === postPlay.player_id)?.name ?? '…';
      this.track(
        this.add
          .text(panel.x + panel.width / 2, panel.y + panel.height / 2, `Waiting on ${waitingOn}…`, {
            fontFamily: 'sans-serif',
            fontSize: '12px',
            color: '#cccccc',
          })
          .setOrigin(0.5),
      );
    }
  }

  private renderSuitPick(sync: StateSyncMsg, layout: GameTableLayout): void {
    const panel = layout.suitPick;
    const isMine = sync.current_player_idx === sync.you;
    this.track(
      this.add
        .rectangle(panel.x + panel.width / 2, panel.y + panel.height / 2, panel.width, panel.height, 0x101010, 0.9)
        .setStrokeStyle(2, 0xd9a441, 0.9),
    );
    this.track(
      this.add
        .text(panel.x + panel.width / 2, panel.y + 8, isMine ? 'Choose the new suit' : `Waiting for ${sync.players[sync.current_player_idx]?.name ?? '…'}…`, {
          fontFamily: 'sans-serif',
          fontSize: '13px',
          color: '#ffffff',
        })
        .setOrigin(0.5, 0),
    );
    if (!isMine) return;
    for (const btn of panel.buttons) {
      this.drawButton(
        { x: btn.x, y: btn.y, width: btn.width, height: btn.height, label: `${SUIT_SYMBOL[btn.suit]}` },
        () => {
          this.connection.send({ type: 'intent_choose_suit', suit: btn.suit });
        },
        0x1a1a1a,
      );
    }
  }

  private renderCounterPanel(sync: StateSyncMsg, layout: GameTableLayout): void {
    if (sync.counter_player_idx !== sync.you) return;
    const panel = layout.counterPanel;
    this.track(
      this.add
        .rectangle(panel.x + panel.width / 2, panel.y + panel.height / 2, panel.width, panel.height, 0x3a2400, 0.9)
        .setStrokeStyle(2, 0xff8c00, 0.8),
    );
    this.drawButton(panel.passButton, () => {
      this.connection.send({ type: 'intent_pass_counter' });
      this.selected.clear();
    }, 0x5a3a10);
  }

  private renderPauseOverlay(layout: GameTableLayout): void {
    this.track(
      this.add
        .rectangle(layout.tableCenter.x, layout.tableCenter.y, layout.contentRect.width, layout.contentRect.height, 0x000000, 0.6)
        .setOrigin(0.5),
    );
    this.track(
      this.add
        .text(layout.tableCenter.x, layout.tableCenter.y - 30, 'PAUSED', {
          fontFamily: 'sans-serif',
          fontSize: '28px',
          color: '#f0d060',
        })
        .setOrigin(0.5),
    );
    this.drawButton(
      { x: layout.tableCenter.x - 80, y: layout.tableCenter.y + 10, width: 160, height: 44, label: 'Resume' },
      () => this.connection.send({ type: 'intent_toggle_pause' }),
    );
  }

  private renderWinScreen(sync: StateSyncMsg, layout: GameTableLayout, textColor: string): void {
    this.track(
      this.add
        .rectangle(layout.tableCenter.x, layout.tableCenter.y, layout.contentRect.width, layout.contentRect.height, 0x000000, 0.75)
        .setOrigin(0.5),
    );
    const winner = sync.players.find((p) => p.player_id === sync.winner_id);
    this.track(
      this.add
        .text(layout.winScreen.title.x, layout.winScreen.title.y, winner ? `${winner.name} wins!` : 'Game Over', {
          fontFamily: 'sans-serif',
          fontSize: `${layout.winScreen.title.fontPx}px`,
          color: '#f0d060',
          fontStyle: 'bold',
        })
        .setOrigin(0.5),
    );
    const order = sync.finish_order_ids
      .map((id, i) => `${i + 1}. ${sync.players.find((p) => p.player_id === id)?.name ?? '?'}`)
      .join('   ');
    this.track(
      this.add
        .text(layout.winScreen.subtitle.x, layout.winScreen.subtitle.y, order, {
          fontFamily: 'sans-serif',
          fontSize: `${layout.winScreen.subtitle.fontPx}px`,
          color: textColor,
        })
        .setOrigin(0.5),
    );
    if (this.newlyEarnedBadgeIds.length > 0) {
      // No dedicated layout slot for this (GameTableLayout.ts's
      // winScreen only defines title/subtitle/playAgainButton, and
      // extending that layout module -- with its own snapshot tests --
      // is out of scope for this delivery) -- positioned as a fixed
      // offset below the subtitle instead, same font size as the
      // subtitle it sits under.
      const names = this.newlyEarnedBadgeIds
        .map((id) => BADGE_DEFS[id]?.name ?? id)
        .join('   ');
      this.track(
        this.add
          .text(
            layout.winScreen.subtitle.x,
            layout.winScreen.subtitle.y + layout.winScreen.subtitle.fontPx * 2,
            `New badge: ${names}`,
            {
              fontFamily: 'sans-serif',
              fontSize: `${layout.winScreen.subtitle.fontPx}px`,
              color: '#f0d060',
            },
          )
          .setOrigin(0.5),
      );
    }
    this.drawButton(layout.winScreen.playAgainButton, () => {
      this.connection.close();
      this.scene.start('LobbyScene', { adapter: this.adapter });
    });
  }
}
