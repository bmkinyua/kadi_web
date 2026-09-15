/**
 * KADI web-client — GameConfigScene.
 *
 * The real per-game configuration screen this codebase's old
 * ModeSelectScene.ts deliberately skipped (see §9's "Mode Select"
 * row and layout/GameConfigLayout.ts's own header for the full
 * scope/discrepancy notes). One shared scene for both entry points,
 * parameterized by `vsAi`, matching scenes.ModeSelectScene(vs_ai:
 * bool) exactly:
 *   - Reached DIRECTLY from MainMenuScene's "Play vs AI" button, with
 *     vsAi=true.
 *   - Reached from MultiplayerMenuScene's "Local Multiplayer" button,
 *     with vsAi=false.
 *
 * BACK: always goes straight to MainMenuScene, in BOTH modes — this
 * is deliberate PC parity (`ModeSelectScene`'s own Back, scenes.py),
 * not a bug: Local Multiplayer's Back does NOT return to
 * MultiplayerMenuScene even though that's how this scene was reached.
 * See layout/GameConfigLayout.ts's/MultiplayerMenuLayout.ts's own
 * headers for the same note from the other side.
 *
 * PLAY VS AI — START GAME: fully wired. Builds a real
 * `CreateGameSettings` (opponent count → ai_count, difficulty,
 * elimination mode + AI-only-continue sub-toggle, embedded MSOMI
 * model) and the typed player name, then hands both to LobbyScene
 * (autoQuickPlay=true) — see that scene's own header for why it,
 * not this scene, owns the actual connect/hello/create_game/
 * request_start_game lifecycle (it already has the bugfixed
 * `quickPlayRequested` reset and reconnect-adjacent plumbing; no
 * reason to duplicate that here).
 *
 * LOCAL MULTIPLAYER — START GAME: deliberately NOT wired to start a
 * real match. Investigation (this task's own Part A) found that
 * server/game_room.py's whole roster model is ONE human seat per
 * server connection (`self.member_names`, keyed by conn_id) — there
 * is no existing path for a single browser tab/connection to own
 * several human seats the way PC's hot-seat pass-and-play does, and
 * bolting that on is a real server/reconnect-token design decision,
 * not a mechanical client-side fix. Per this task's own instruction
 * ("report it, don't patch around it silently"), this scene collects
 * every PC-parity input (names, opponent count, elimination mode)
 * and is otherwise fully usable/testable, but its Start Game button
 * shows `LOCAL_MULTIPLAYER_BLOCKED_MESSAGE` and does not attempt a
 * create_game — a player sees an honest, specific reason instead of
 * either a silent no-op or a broken/fake game.
 *
 * SCROLLING/INTERACTION: same wheel + touch-drag physics as
 * SettingsScene.ts/RulesScene.ts (layout/scrollPhysics.ts), same
 * destroy-and-rebuild-per-render() discipline, same choice-button/
 * toggle rendering conventions. Free-text fields ("Your Name",
 * hot-seat names) are new to this codebase — click-to-focus +
 * keyboard entry, direct analogue of SettingsScene.ts's NumberBox
 * state machine but for printable text instead of digits.
 */
import Phaser from 'phaser';
import type { MsomiStore, MsomiTrainedModel, PlatformAdapter } from '@kadi/adapter-interface';
import { validateModel } from './msomi/trainer.js';
import {
  computeGameConfigFlow,
  computeGameConfigTitleLayout,
  MAX_OPPONENTS,
  MIN_OPPONENTS,
  type AiDifficulty,
  type GameConfigFlow,
  type GameConfigRowLayout,
} from './layout/GameConfigLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';
import { HelpOverlay } from './HelpOverlay.js';
import { gameConfigHelp } from './layout/HELP_CONTENT.js';

const MAX_NAME_LENGTH = 16;
const LOCAL_MULTIPLAYER_BLOCKED_MESSAGE =
  'Local Multiplayer needs a server-side update (one connection can only hold one human seat today) — not available on web yet.';

export class GameConfigScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  private msomiStore: MsomiStore | undefined;
  private vsAi = true;

  private titleText!: Phaser.GameObjects.Text;
  private content!: Phaser.GameObjects.Container;
  private clipMask!: Phaser.GameObjects.Graphics;
  private dynamicObjects: Phaser.GameObjects.GameObject[] = [];
  private statusText!: Phaser.GameObjects.Text;

  // ── setup state ────────────────────────────────────────────────
  private playerName = 'Player 1';
  private localNames: string[] = Array.from({ length: MAX_OPPONENTS }, (_, i) => `Player ${i + 2}`);
  private opponentCount = 3;
  private difficulty: AiDifficulty = 'MEDIUM';
  private eliminationMode = false;
  private eliminationAiOnlyContinue = true;
  private msomiEnabled = false;
  private msomiModelName: string | null = null;
  private msomiModel: MsomiTrainedModel | null = null;

  private focusedFieldId: string | null = null;
  private statusMessage = '';

  // MSOMI picker modal
  private msomiPickerOpen = false;
  private msomiAvailableModels: string[] = [];

  private scrollOffset = 0;
  private scrollBounce: ScrollBounce | null = null;
  private currentFlow!: GameConfigFlow;

  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  private startInFlight = false;
  private helpOverlay!: HelpOverlay;

  constructor() {
    super('GameConfigScene');
  }

  init(data: { adapter: PlatformAdapter; vsAi: boolean; msomiStore?: MsomiStore }): void {
    this.adapter = data.adapter;
    this.vsAi = data.vsAi;
    this.msomiStore = data.msomiStore;

    // Fresh setup state every entry -- same reasoning as every other
    // reused-Scene-instance reset in this codebase (SettingsScene.ts/
    // RulesScene.ts's own init()).
    this.playerName = 'Player 1';
    this.localNames = Array.from({ length: MAX_OPPONENTS }, (_, i) => `Player ${i + 2}`);
    this.opponentCount = 3;
    this.difficulty = 'MEDIUM';
    this.eliminationMode = false;
    this.eliminationAiOnlyContinue = true;
    this.msomiEnabled = false;
    this.msomiModelName = null;
    this.msomiModel = null;
    this.focusedFieldId = null;
    this.statusMessage = '';
    this.msomiPickerOpen = false;
    this.msomiAvailableModels = [];
    this.scrollOffset = 0;
    this.scrollBounce = null;
    this.dragging = false;
    this.dragPointerId = null;
    this.startInFlight = false;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    void this.adapter.getDisplayName().then((name) => {
      if (name) this.playerName = name;
      this.render();
    });

    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeGameConfigTitleLayout(this.viewport(), insets);
    this.titleText = this.add
      .text(titleLayout.x, titleLayout.y, this.vsAi ? 'Play vs AI' : 'Local Multiplayer', {
        fontFamily: 'sans-serif',
        fontSize: `${titleLayout.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5, 0);

    this.statusText = this.add
      .text(titleLayout.x, titleLayout.y + titleLayout.fontPx + 6, '', {
        fontFamily: 'sans-serif',
        fontSize: '12px',
        color: '#f0a860',
        align: 'center',
        wordWrap: { width: Math.min(360, this.scale.width - 32) },
      })
      .setOrigin(0.5, 0);

    this.content = this.add.container(0, 0);
    this.clipMask = this.make.graphics(undefined, false);
    this.content.setMask(this.clipMask.createGeometryMask());

    // Help Overlay -- ported from scenes.ModeSelectScene
    // ._help_sections(), which branches on vs_ai for both title and
    // content (see HELP_CONTENT.ts's gameConfigHelp()). Suppressed
    // entirely while the MSOMI picker modal is open -- see render()'s
    // helpOverlay.setEnabled() call and this file's own header note
    // on why two floating modals at once would conflict, matching
    // scenes.py's own _layout_help_btn/draw not running while that
    // picker is up.
    this.helpOverlay = new HelpOverlay(this, this.adapter, gameConfigHelp(this.vsAi));
    this.helpOverlay.create();

    this.render();

    this.input.on(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
    this.input.on(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.input.on(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.on(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.input.keyboard?.on(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);

    this.scale.on(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, this.handleShutdown, this);
  }

  private handleShutdown(): void {
    this.scale.off(Phaser.Scale.Events.RESIZE, this.handleResize, this);
    this.input.off(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
    this.input.off(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.input.off(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.off(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.off(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);
    this.input.keyboard?.off(Phaser.Input.Keyboard.Events.KEY_DOWN, this.handleKeyDown, this);
    this.helpOverlay.destroy();
  }

  update(_time: number, delta: number): void {
    this.helpOverlay.update(delta);
    const outOfRange = this.scrollOffset < 0 || this.scrollOffset > this.currentFlow.maxScroll;
    if (this.scrollBounce || outOfRange) {
      const result = settleScroll(this.scrollOffset, this.scrollBounce, delta, this.currentFlow.maxScroll);
      this.scrollOffset = result.value;
      this.scrollBounce = result.bounce;
      this.render();
    }
  }

  private viewport(): { width: number; height: number } {
    return { width: this.scale.width, height: this.scale.height };
  }

  private flowOptions() {
    return { vsAi: this.vsAi, opponentCount: this.opponentCount, eliminationMode: this.eliminationMode };
  }

  // ── Scroll input (identical pattern to SettingsScene.ts) ─────────

  private handleWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (this.dragging || this.msomiPickerOpen || this.helpOverlay.isOpen || this.currentFlow == null) return;
    pointer.event?.preventDefault();
    this.scrollBounce = null;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, dy, this.currentFlow.maxScroll);
    this.render();
  }

  private isWithinViewportBand(pointer: Phaser.Input.Pointer): boolean {
    const flow = this.currentFlow;
    return pointer.y >= flow.viewportTop && pointer.y <= flow.viewportTop + flow.viewportHeight;
  }

  private handleDragStart(pointer: Phaser.Input.Pointer): void {
    if (this.msomiPickerOpen || this.helpOverlay.isOpen) return;
    if (this.dragPointerId !== null) return;
    if (!this.isWithinViewportBand(pointer)) return;
    this.dragging = true;
    this.dragPointerId = pointer.id;
    this.dragLastY = pointer.y;
    this.scrollBounce = null;
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    if (!this.dragging || pointer.id !== this.dragPointerId) return;
    const delta = this.dragLastY - pointer.y;
    this.dragLastY = pointer.y;
    this.scrollOffset = scrollWheelDelta(this.scrollOffset, delta, this.currentFlow.maxScroll);
    this.render();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
  }

  // ── Text field editing (click-to-focus + keyboard entry) ────────

  private fieldValue(id: string): string {
    if (id === 'playerName') return this.playerName;
    const idx = Number(id.split(':')[1]);
    return this.localNames[idx] ?? '';
  }

  private setFieldValue(id: string, value: string): void {
    if (id === 'playerName') {
      this.playerName = value;
      return;
    }
    const idx = Number(id.split(':')[1]);
    this.localNames[idx] = value;
  }

  private focusField(id: string): void {
    this.focusedFieldId = id;
    this.render();
  }

  private handleKeyDown(event: KeyboardEvent): void {
    if (this.helpOverlay.isOpen) return; // let the overlay's own Escape-to-close handle this
    const id = this.focusedFieldId;
    if (!id) return;
    if (event.key === 'Enter' || event.key === 'Escape' || event.key === 'Tab') {
      this.focusedFieldId = null;
      this.render();
      return;
    }
    if (event.key === 'Backspace') {
      this.setFieldValue(id, this.fieldValue(id).slice(0, -1));
      this.render();
      return;
    }
    // Mirrors ModeSelectScene's own `event.unicode.isprintable()` gate
    // (scenes.py) -- printable single characters only, length-capped.
    if (event.key.length === 1 && this.fieldValue(id).length < MAX_NAME_LENGTH) {
      this.setFieldValue(id, this.fieldValue(id) + event.key);
      this.render();
    }
  }

  // ── MSOMI attach ──────────────────────────────────────────────────

  private openMsomiPicker(): void {
    if (!this.msomiStore) {
      this.statusMessage = 'No local model storage available on this device.';
      this.render();
      return;
    }
    void this.msomiStore.listModels().then((models) => {
      this.msomiAvailableModels = models;
      this.msomiPickerOpen = true;
      this.render();
    });
  }

  private pickMsomiModel(name: string): void {
    if (!this.msomiStore) return;
    void this.msomiStore.loadModel(name).then((model) => {
      const problem = validateModel(model);
      if (problem) {
        this.statusMessage = problem;
        this.render();
        return;
      }
      this.msomiModelName = name;
      this.msomiModel = model;
      this.msomiEnabled = true;
      this.msomiPickerOpen = false;
      this.statusMessage = '';
      this.render();
    });
  }

  // ── Start / Back ───────────────────────────────────────────────

  private onStartGame(): void {
    if (this.startInFlight) return;
    const name = this.playerName.trim() || 'Player 1';

    if (!this.vsAi) {
      // See this file's own header -- genuine server-side gap, not
      // silently patched around.
      this.statusMessage = LOCAL_MULTIPLAYER_BLOCKED_MESSAGE;
      this.render();
      return;
    }

    this.startInFlight = true;
    const model = this.msomiEnabled && this.msomiModel ? this.msomiModel : undefined;
    this.scene.start('LobbyScene', {
      adapter: this.adapter,
      autoQuickPlay: true,
      playerName: name,
      gameSettings: {
        ai_count: this.opponentCount,
        ai_difficulty: this.difficulty,
        elimination_mode: this.eliminationMode,
        elimination_ai_only_continue: this.eliminationAiOnlyContinue,
        ai_msomi_model: model as unknown as Record<string, unknown> | undefined,
        ai_msomi_model_label: model ? (this.msomiModelName ?? undefined) : undefined,
      },
    });
  }

  private onBack(): void {
    // Always Main Menu, in both modes -- see this file's own header.
    this.scene.start('MainMenuScene', { adapter: this.adapter, msomiStore: this.msomiStore });
  }

  // ── Resize ─────────────────────────────────────────────────────

  private handleResize(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeGameConfigTitleLayout(this.viewport(), insets);
    this.titleText.setPosition(titleLayout.x, titleLayout.y);
    this.titleText.setFontSize(titleLayout.fontPx);
    this.statusText.setPosition(titleLayout.x, titleLayout.y + titleLayout.fontPx + 6);
    this.helpOverlay.layout();
    this.render();
  }

  private isOffscreen(rect: RectLayout, flow: GameConfigFlow): boolean {
    return rect.y + rect.height < flow.viewportTop || rect.y > flow.viewportTop + flow.viewportHeight;
  }

  // ── Render ─────────────────────────────────────────────────────

  private render(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const flow = computeGameConfigFlow(this.viewport(), insets, this.scrollOffset, this.flowOptions());
    this.currentFlow = flow;

    this.clipMask.clear();
    this.clipMask.fillStyle(0xffffff);
    this.clipMask.fillRect(flow.contentRect.x, flow.viewportTop, flow.contentRect.width, flow.viewportHeight);

    for (const obj of this.dynamicObjects) obj.destroy();
    this.dynamicObjects = [];

    this.statusText.setText(this.statusMessage);

    for (const row of flow.rows) {
      if (this.isOffscreen(this.rowBounds(row), flow)) continue;
      this.renderRow(row);
    }

    this.renderButton(flow.startButton, 'Start Game', 0x2a5a34, () => this.onStartGame());
    this.renderButton(flow.backButton, 'Back', 0x503268, () => this.onBack());

    if (this.msomiPickerOpen) this.renderMsomiModal();

    this.helpOverlay.setEnabled(!this.msomiPickerOpen);
  }

  private rowBounds(row: GameConfigRowLayout): RectLayout {
    switch (row.kind) {
      case 'textfield':
        return row.box;
      case 'opponentCount':
      case 'difficulty': {
        const rects = row.buttons.map((b) => b.rect);
        const y = Math.min(...rects.map((r) => r.y));
        const height = Math.max(...rects.map((r) => r.y + r.height)) - y;
        return { x: rects[0].x, y, width: 0, height };
      }
      case 'msomi':
        return { x: row.toggle.x, y: row.toggle.y, width: 0, height: row.toggle.height };
      case 'toggle':
        return row.button;
      case 'note':
        return { x: row.lines[0]?.x ?? 0, y: row.lines[0]?.y ?? 0, width: 0, height: 20 };
    }
  }

  private track<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.content.add(obj);
    this.dynamicObjects.push(obj);
    return obj;
  }

  private renderRow(row: GameConfigRowLayout): void {
    switch (row.kind) {
      case 'textfield':
        this.renderTextField(row.id, row.label, row.box);
        break;
      case 'opponentCount':
        this.track(
          this.add.text(row.label.x, row.label.y, row.label.value, {
            fontFamily: 'sans-serif',
            fontSize: `${row.label.fontPx}px`,
            color: '#dce0d8',
          }),
        );
        for (const b of row.buttons) {
          this.renderChoiceButton(b.rect, String(b.n), b.n === this.opponentCount, () => this.setOpponentCount(b.n));
        }
        break;
      case 'difficulty':
        this.track(
          this.add.text(row.label.x, row.label.y, row.label.value, {
            fontFamily: 'sans-serif',
            fontSize: `${row.label.fontPx}px`,
            color: '#dce0d8',
          }),
        );
        for (const b of row.buttons) {
          this.renderChoiceButton(b.rect, titleCase(b.value), b.value === this.difficulty, () => {
            this.difficulty = b.value;
            this.render();
          });
        }
        break;
      case 'msomi':
        this.renderMsomiRow(row.label, row.toggle, row.attach);
        break;
      case 'toggle':
        this.renderToggleRow(row.id, row.label, row.button);
        break;
      case 'note':
        for (const line of row.lines) {
          this.track(
            this.add
              .text(line.x, line.y, line.text, { fontFamily: 'sans-serif', fontSize: `${line.fontPx}px`, color: '#a0a89e' })
              .setOrigin(0.5, 0),
          );
        }
        break;
    }
  }

  private setOpponentCount(n: number): void {
    this.opponentCount = Math.max(MIN_OPPONENTS, Math.min(MAX_OPPONENTS, n));
    this.render();
  }

  private renderTextField(id: string, label: { x: number; y: number; fontPx: number; value: string }, box: RectLayout): void {
    this.track(
      this.add.text(label.x, label.y, label.value, { fontFamily: 'sans-serif', fontSize: `${label.fontPx}px`, color: '#dce0d8' }),
    );
    const focused = this.focusedFieldId === id;
    const rect = this.track(
      this.add
        .rectangle(box.x + box.width / 2, box.y + box.height / 2, box.width, box.height, 0x182e20)
        .setStrokeStyle(2, focused ? 0xf0d878 : 0x82a087)
        .setInteractive({ useHandCursor: true }),
    );
    rect.on('pointerdown', () => this.focusField(id));
    const value = this.fieldValue(id);
    this.track(
      this.add
        .text(box.x + 10, box.y + box.height / 2, value + (focused ? '|' : ''), {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(box.height * 0.4)}px`,
          color: '#ffffff',
        })
        .setOrigin(0, 0.5),
    );
  }

  private renderChoiceButton(rect: RectLayout, label: string, selected: boolean, onClick: () => void): void {
    const btn = this.track(
      this.add
        .rectangle(rect.x + rect.width / 2, rect.y + rect.height / 2, rect.width, rect.height, selected ? 0xd9a441 : 0x325a3c)
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', onClick);
    this.track(
      this.add
        .text(rect.x + rect.width / 2, rect.y + rect.height / 2, label, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(rect.height * 0.42)}px`,
          color: selected ? '#1a1a1a' : '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderToggleRow(
    id: 'eliminationMode' | 'eliminationAiOnlyContinue',
    label: { x: number; y: number; fontPx: number; value: string },
    button: RectLayout,
  ): void {
    this.track(
      this.add
        .text(label.x, label.y, label.value, { fontFamily: 'sans-serif', fontSize: `${label.fontPx}px`, color: '#dce0d8' })
        .setOrigin(0.5, 0),
    );
    const state = id === 'eliminationMode' ? this.eliminationMode : this.eliminationAiOnlyContinue;
    const onLabel = id === 'eliminationAiOnlyContinue' ? 'Continue with AI' : 'ON';
    const offLabel = id === 'eliminationAiOnlyContinue' ? 'End the game' : 'OFF';
    const btn = this.track(
      this.add
        .rectangle(
          button.x + button.width / 2,
          button.y + button.height / 2,
          button.width,
          button.height,
          state ? 0x288c32 : 0x642828,
        )
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', () => {
      if (id === 'eliminationMode') this.eliminationMode = !this.eliminationMode;
      else this.eliminationAiOnlyContinue = !this.eliminationAiOnlyContinue;
      this.render();
    });
    this.track(
      this.add
        .text(button.x + button.width / 2, button.y + button.height / 2, state ? onLabel : offLabel, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(button.height * 0.32)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderMsomiRow(label: { x: number; y: number; fontPx: number; value: string }, toggle: RectLayout, attach: RectLayout): void {
    this.track(
      this.add.text(label.x, label.y, label.value, { fontFamily: 'sans-serif', fontSize: `${label.fontPx}px`, color: '#dce0d8' }),
    );
    const canEnable = this.msomiModelName !== null;
    const on = this.msomiEnabled && canEnable;
    const toggleColor = !canEnable ? 0x64501e : on ? 0xb48c1e : 0x464650;
    const toggleBtn = this.track(
      this.add
        .rectangle(toggle.x + toggle.width / 2, toggle.y + toggle.height / 2, toggle.width, toggle.height, toggleColor)
        .setStrokeStyle(2, 0xffffff, canEnable ? 0.8 : 0.3)
        .setInteractive({ useHandCursor: true }),
    );
    toggleBtn.on('pointerdown', () => {
      if (this.msomiModelName) this.msomiEnabled = !this.msomiEnabled;
      this.render();
    });
    this.track(
      this.add
        .text(toggle.x + toggle.width / 2, toggle.y + toggle.height / 2, on ? 'ON' : 'OFF', {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(toggle.height * 0.38)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );

    const attachBtn = this.track(
      this.add
        .rectangle(attach.x + attach.width / 2, attach.y + attach.height / 2, attach.width, attach.height, 0x3c3c50)
        .setStrokeStyle(1, 0xffffff, 0.5)
        .setInteractive({ useHandCursor: true }),
    );
    attachBtn.on('pointerdown', () => this.openMsomiPicker());
    const attachLabel = this.msomiModelName ?? 'Attach Model...';
    this.track(
      this.add
        .text(attach.x + attach.width / 2, attach.y + attach.height / 2, attachLabel, {
          fontFamily: 'sans-serif',
          fontSize: '11px',
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderButton(rect: RectLayout, label: string, color: number, onClick: () => void): void {
    const cx = rect.x + rect.width / 2;
    const cy = rect.y + rect.height / 2;
    const btn = this.add.rectangle(cx, cy, rect.width, rect.height, color).setStrokeStyle(1, 0xffffff, 0.6);
    const text = this.add.text(cx, cy, label, { fontFamily: 'sans-serif', fontSize: '16px', color: '#ffffff' }).setOrigin(0.5);
    if (!this.isOffscreen(rect, this.currentFlow)) {
      btn.setInteractive({ useHandCursor: true });
      btn.on('pointerdown', onClick);
    }
    this.content.add([btn, text]);
    this.dynamicObjects.push(btn, text);
  }

  private renderMsomiModal(): void {
    const { width, height } = this.viewport();
    const dim = this.add.rectangle(width / 2, height / 2, width, height, 0x000000, 0.6).setInteractive();
    dim.on('pointerdown', () => {
      this.msomiPickerOpen = false;
      this.render();
    });
    this.dynamicObjects.push(dim);
    this.content.add(dim);

    const modalW = Math.min(360, width - 40);
    const modalH = Math.min(320, height - 80);
    const modal = this.add.rectangle(width / 2, height / 2, modalW, modalH, 0x20222e).setStrokeStyle(1, 0xffffff, 0.3);
    this.dynamicObjects.push(modal);
    this.content.add(modal);

    const title = this.add
      .text(width / 2, height / 2 - modalH / 2 + 16, 'Attach MSOMI Model', { fontFamily: 'sans-serif', fontSize: '16px', color: '#f0d878' })
      .setOrigin(0.5);
    this.dynamicObjects.push(title);
    this.content.add(title);

    if (this.msomiAvailableModels.length === 0) {
      const empty = this.add
        .text(width / 2, height / 2, 'No saved models yet — train one in Chuo.', {
          fontFamily: 'sans-serif',
          fontSize: '12px',
          color: '#a0a89e',
          align: 'center',
          wordWrap: { width: modalW - 32 },
        })
        .setOrigin(0.5);
      this.dynamicObjects.push(empty);
      this.content.add(empty);
    } else {
      this.msomiAvailableModels.forEach((name, i) => {
        const rowY = height / 2 - modalH / 2 + 56 + i * 34;
        if (rowY > height / 2 + modalH / 2 - 40) return;
        const isCurrent = name === this.msomiModelName;
        const row = this.add
          .rectangle(width / 2, rowY, modalW - 32, 30, isCurrent ? 0x554182 : 0x38384a)
          .setInteractive({ useHandCursor: true });
        row.on('pointerdown', () => this.pickMsomiModel(name));
        const label = this.add
          .text(width / 2 - modalW / 2 + 24, rowY, name, { fontFamily: 'sans-serif', fontSize: '12px', color: '#ffffff' })
          .setOrigin(0, 0.5);
        this.dynamicObjects.push(row, label);
        this.content.add([row, label]);
      });
    }

    const cancelY = height / 2 + modalH / 2 - 28;
    const cancel = this.add
      .rectangle(width / 2, cancelY, 120, 36, 0x503232)
      .setStrokeStyle(1, 0xffffff, 0.5)
      .setInteractive({ useHandCursor: true });
    cancel.on('pointerdown', () => {
      this.msomiPickerOpen = false;
      this.render();
    });
    const cancelLabel = this.add.text(width / 2, cancelY, 'Cancel', { fontFamily: 'sans-serif', fontSize: '13px', color: '#ffffff' }).setOrigin(0.5);
    this.dynamicObjects.push(cancel, cancelLabel);
    this.content.add([cancel, cancelLabel]);
  }
}

function titleCase(value: string): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}
