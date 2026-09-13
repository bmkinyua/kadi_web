/**
 * KADI web-client — ChuoScene ("Chuo" / MSOMI train-your-own-AI).
 * Ported from scenes.ChuoScene (scenes.py) — see that class's own
 * docstring: four tabs (Data, Features, Model, Train & Results),
 * everything local (no server, no live game state touched).
 *
 * WHAT'S GENUINELY NEW HERE VS. THE PC ORIGINAL (both deliberate, both
 * flagged in KADI_web_port_implementation_plan.md's §9 Chuo row too):
 *   - A "Saved models" list with per-model Load/Delete on the Train &
 *     Results tab. The PC ChuoScene has NO such list or delete
 *     anywhere — see MsomiStore.ts's own header. Added here because
 *     it's the natural, low-cost counterpart of local save/load, not
 *     because it was asked for as a straight port.
 *   - A small "Files"/"Browser storage" backend indicator near the
 *     Back button (see MsomiStore.ts's `backendKind`) — there is
 *     nothing to indicate on a single-platform desktop app; a web
 *     player benefits from knowing whether "Import from device" will
 *     open a real native picker or fall back to a plain one.
 *   - "Load" on a saved-model row: doesn't do anything gameplay-wise
 *     yet (attaching a model to an AI opponent is ModeSelectScene's/
 *     MSOMIPickerWidget's job on the PC side — explicitly out of scope
 *     for this delivery, see the handoff prompt's own "don't touch...
 *     anything already covered by prior deliveries" and MsomiStore.ts's
 *     header on why that flow lives elsewhere). It validates the file
 *     (validateModel()) and shows its weights, which is genuinely
 *     useful on its own for a player checking what they trained.
 *
 * WHAT'S DELIBERATELY NOT PORTED THIS PASS: the Help overlay — see
 * layout/ChuoLayout.ts's own header for why, and §9 for the tracked
 * follow-up. NumberBox click-to-focus + keyboard digit entry (from
 * SettingsScene.ts's own pattern) is also simplified to +/- steppers
 * only here — Chuo's two numeric fields (human weight 1-10, training
 * iterations 50-3000 step 50) are coarse enough that steppers alone
 * are a reasonable simplification, and it keeps this already-large
 * scene from needing its own copy of Settings' keyboard-focus state
 * machine for two fields.
 *
 * EVERYTHING ELSE follows SettingsScene.ts's own established
 * conventions exactly: destroy-and-rebuild dynamicObjects on every
 * render(), a Container + Graphics geometry mask for the scrollable
 * viewport band, wheel + touch-drag both feeding
 * layout/scrollPhysics.ts, hold-to-repeat steppers with the same
 * accelerating interval. See that file's own header for the reasoning
 * behind each of those, not repeated here.
 */
import Phaser from 'phaser';
import type { MsomiDecisionRecord, MsomiStore, MsomiTrainedModel, PlatformAdapter } from '@kadi/adapter-interface';
import {
  computeChuoFlow,
  computeChuoTitleLayout,
  type ChuoFlow,
  type ChuoPositionedRow,
  type ChuoRowInput,
  type ChuoTabId,
} from './layout/ChuoLayout.js';
import type { RectLayout } from './layout/InternetLobbyLayout.js';
import { scrollWheelDelta, settleScroll, type ScrollBounce } from './layout/scrollPhysics.js';
import {
  MsomiTrainingError,
  TRAINABLE_FEATURES,
  loadDecisionsFromText,
  scoreOption,
  trainConditionalLogit,
  validateModel,
  type TrainableFeature,
} from './msomi/trainer.js';

const FEATURE_LABELS: Record<TrainableFeature, string> = {
  cards_played: 'Cards played',
  cards_remaining: 'Cards remaining after',
  empties_hand: 'Empties hand',
  wastes_win: 'Wastes a winning play',
  leaves_kadi: 'Leaves KADI undeclared',
  unanswered_question: 'Unanswered Question',
  pickup_value_added: 'Pick-up value added',
  has_suit_change: 'Changes suit',
  has_skip: 'Includes a Skip (J)',
  has_kickback: 'Includes a Kickback (K)',
  has_question: 'Includes a Question (8/Q)',
  next_is_threat: 'Next player is a threat',
  stranded_cluster_cost: 'Strands a card cluster',
};

const HOLD_INITIAL_DELAY_MS = 450;
const HOLD_MIN_INTERVAL_MS = 35;
const HOLD_ACCELERATION = 0.8;

interface NumberFieldState {
  holdDir: number;
  holdElapsed: number;
  holdInterval: number;
}

const DEFAULT_HUMAN_WEIGHT = 2;
const DEFAULT_ITERATIONS = 300;

export class ChuoScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  private msomiStore!: MsomiStore;

  private titleText!: Phaser.GameObjects.Text;
  private content!: Phaser.GameObjects.Container;
  private clipMask!: Phaser.GameObjects.Graphics;
  private dynamicObjects: Phaser.GameObjects.GameObject[] = [];

  private activeTab: ChuoTabId = 'data';
  private scrollOffsetByTab: Record<ChuoTabId, number> = { data: 0, features: 0, model: 0, results: 0 };
  private scrollBounce: ScrollBounce | null = null;
  private currentFlow!: ChuoFlow;

  private dragging = false;
  private dragPointerId: number | null = null;
  private dragLastY = 0;

  // Data tab state
  private logFiles: { id: string; name: string; size: number; importedAt: number }[] = [];
  private selectedLogIds = new Set<string>();
  private loadedDecisions: MsomiDecisionRecord[] | null = null;
  private loadStatus = '';

  // Features tab state
  private featureSelected: Record<string, boolean> = Object.fromEntries(
    TRAINABLE_FEATURES.map((f) => [f, true]),
  );

  // Model tab state
  private humanWeight = DEFAULT_HUMAN_WEIGHT;
  private iterations = DEFAULT_ITERATIONS;
  private modelTier: 'light' | 'heavy' = 'light';
  private numberFieldState: Record<'human_weight' | 'iterations', NumberFieldState> = {
    human_weight: { holdDir: 0, holdElapsed: 0, holdInterval: 0 },
    iterations: { holdDir: 0, holdElapsed: 0, holdInterval: 0 },
  };

  // Train & Results tab state
  private trainedModel: MsomiTrainedModel | null = null;
  private trainStatus = '';
  private savedModels: string[] = [];
  private lastSavedFilename: string | null = null;
  private resultStatus = '';

  constructor() {
    super('ChuoScene');
  }

  init(data: { adapter: PlatformAdapter; msomiStore: MsomiStore }): void {
    this.adapter = data.adapter;
    this.msomiStore = data.msomiStore;
    // Fresh interaction state on every entry -- same reasoning as
    // every other scene here (this Scene instance is reused across
    // repeated scene.start() calls).
    this.activeTab = 'data';
    this.scrollOffsetByTab = { data: 0, features: 0, model: 0, results: 0 };
    this.scrollBounce = null;
    this.dragging = false;
    this.dragPointerId = null;
    this.logFiles = [];
    this.selectedLogIds = new Set();
    this.loadedDecisions = null;
    this.loadStatus = '';
    this.featureSelected = Object.fromEntries(TRAINABLE_FEATURES.map((f) => [f, true]));
    this.humanWeight = DEFAULT_HUMAN_WEIGHT;
    this.iterations = DEFAULT_ITERATIONS;
    this.modelTier = 'light';
    this.numberFieldState = {
      human_weight: { holdDir: 0, holdElapsed: 0, holdInterval: 0 },
      iterations: { holdDir: 0, holdElapsed: 0, holdInterval: 0 },
    };
    this.trainedModel = null;
    this.trainStatus = '';
    this.savedModels = [];
    this.lastSavedFilename = null;
    this.resultStatus = '';
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    const insets = this.adapter.getSafeAreaInsets();
    const titleLayout = computeChuoTitleLayout(this.viewport(), insets);
    this.titleText = this.add
      .text(titleLayout.x, titleLayout.y, 'Chuo — Train Your Own AI', {
        fontFamily: 'sans-serif',
        fontSize: `${titleLayout.fontPx}px`,
        color: theme.text,
        fontStyle: 'bold',
      })
      .setOrigin(0.5, 0);

    this.content = this.add.container(0, 0);
    this.clipMask = this.make.graphics(undefined, false);
    this.content.setMask(this.clipMask.createGeometryMask());

    this.render();
    void this.refreshLogFiles();
    void this.refreshSavedModels();

    this.input.on(Phaser.Input.Events.POINTER_WHEEL, this.handleWheel, this);
    this.input.on(Phaser.Input.Events.POINTER_DOWN, this.handleDragStart, this);
    this.input.on(Phaser.Input.Events.POINTER_MOVE, this.handlePointerMove, this);
    this.input.on(Phaser.Input.Events.POINTER_UP, this.handleDragEnd, this);
    this.input.on(Phaser.Input.Events.POINTER_UP_OUTSIDE, this.handleDragEnd, this);

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
  }

  update(_time: number, delta: number): void {
    let needsRender = false;

    const scrollOffset = this.scrollOffsetByTab[this.activeTab];
    const outOfRange = scrollOffset < 0 || scrollOffset > this.currentFlow.maxScroll;
    if (this.scrollBounce || outOfRange) {
      const result = settleScroll(scrollOffset, this.scrollBounce, delta, this.currentFlow.maxScroll);
      this.scrollOffsetByTab[this.activeTab] = result.value;
      this.scrollBounce = result.bounce;
      needsRender = true;
    }

    for (const key of Object.keys(this.numberFieldState) as (keyof typeof this.numberFieldState)[]) {
      const state = this.numberFieldState[key];
      if (state.holdDir === 0) continue;
      state.holdElapsed += delta;
      if (state.holdElapsed >= state.holdInterval) {
        state.holdElapsed = 0;
        state.holdInterval = Math.max(HOLD_MIN_INTERVAL_MS, state.holdInterval * HOLD_ACCELERATION);
        this.nudgeNumberField(key, state.holdDir);
        needsRender = true;
      }
    }

    if (needsRender) this.render();
  }

  private viewport(): { width: number; height: number } {
    return { width: this.scale.width, height: this.scale.height };
  }

  // ── Data loading (async, re-renders once settled) ─────────────────

  private async refreshLogFiles(): Promise<void> {
    this.logFiles = await this.msomiStore.listLogFiles();
    this.render();
  }

  private async refreshSavedModels(): Promise<void> {
    this.savedModels = await this.msomiStore.listModels();
    this.render();
  }

  // ── Scroll input (identical pattern to SettingsScene.ts) ──────────

  private handleWheel(pointer: Phaser.Input.Pointer, _over: unknown, _dx: number, dy: number): void {
    if (this.dragging || this.currentFlow == null) return;
    pointer.event?.preventDefault();
    this.scrollBounce = null;
    const offset = this.scrollOffsetByTab[this.activeTab];
    this.scrollOffsetByTab[this.activeTab] = scrollWheelDelta(offset, dy, this.currentFlow.maxScroll);
    this.render();
  }

  private isWithinViewportBand(pointer: Phaser.Input.Pointer): boolean {
    const flow = this.currentFlow;
    return pointer.y >= flow.viewportTop && pointer.y <= flow.viewportTop + flow.viewportHeight;
  }

  private handleDragStart(pointer: Phaser.Input.Pointer): void {
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
    const offset = this.scrollOffsetByTab[this.activeTab];
    this.scrollOffsetByTab[this.activeTab] = scrollWheelDelta(offset, delta, this.currentFlow.maxScroll);
    this.render();
  }

  private handleDragEnd(pointer: Phaser.Input.Pointer): void {
    if (pointer.id !== this.dragPointerId) return;
    this.dragging = false;
    this.dragPointerId = null;
  }

  private handleResize(): void {
    this.render();
  }

  private isOffscreen(rect: RectLayout, flow: ChuoFlow): boolean {
    return rect.y + rect.height < flow.viewportTop || rect.y > flow.viewportTop + flow.viewportHeight;
  }

  // ── Tab switching ───────────────────────────────────────────────

  private setTab(tab: ChuoTabId): void {
    this.activeTab = tab;
    this.scrollBounce = null;
    this.render();
  }

  // ── Data tab actions ────────────────────────────────────────────

  private toggleLogSelected(id: string): void {
    if (this.selectedLogIds.has(id)) this.selectedLogIds.delete(id);
    else this.selectedLogIds.add(id);
    this.render();
  }

  private selectAllLogs(): void {
    this.selectedLogIds = new Set(this.logFiles.map((f) => f.id));
    this.render();
  }

  private selectNoneLogs(): void {
    this.selectedLogIds = new Set();
    this.render();
  }

  private browseForLogs(): void {
    void this.msomiStore.importLogFiles().then((imported) => {
      if (imported.length === 0) return;
      for (const meta of imported) this.selectedLogIds.add(meta.id);
      return this.refreshLogFiles();
    });
  }

  private loadSelectedLogs(): void {
    if (this.selectedLogIds.size === 0) return;
    this.loadStatus = 'Loading…';
    this.render();
    const ids = [...this.selectedLogIds];
    void Promise.all(ids.map((id) => this.msomiStore.readLogFile(id))).then((contents) => {
      const { decisions, stats } = loadDecisionsFromText(contents);
      this.loadedDecisions = decisions;
      this.loadStatus =
        `Loaded ${stats.loaded} decisions (${stats.humanCount} human, ${stats.aiCount} AI) ` +
        `from ${ids.length} file(s).` +
        (stats.skippedSchemaMismatch
          ? ` Skipped ${stats.skippedSchemaMismatch} from a different log format.`
          : '') +
        (stats.skippedUnparseable ? ` Skipped ${stats.skippedUnparseable} unreadable line(s).` : '');
      this.render();
    });
  }

  // ── Features tab actions ───────────────────────────────────────

  private toggleFeature(feature: string): void {
    this.featureSelected = { ...this.featureSelected, [feature]: !this.featureSelected[feature] };
    this.render();
  }

  private selectAllFeatures(): void {
    this.featureSelected = Object.fromEntries(TRAINABLE_FEATURES.map((f) => [f, true]));
    this.render();
  }

  private selectNoneFeatures(): void {
    this.featureSelected = Object.fromEntries(TRAINABLE_FEATURES.map((f) => [f, false]));
    this.render();
  }

  // ── Model tab actions ───────────────────────────────────────────

  private nudgeNumberField(key: 'human_weight' | 'iterations', direction: number): void {
    if (key === 'human_weight') {
      this.humanWeight = Math.max(1, Math.min(10, this.humanWeight + direction * 1));
    } else {
      this.iterations = Math.max(50, Math.min(3000, this.iterations + direction * 50));
    }
  }

  private startHold(key: 'human_weight' | 'iterations', direction: number): void {
    this.nudgeNumberField(key, direction);
    const state = this.numberFieldState[key];
    state.holdDir = direction;
    state.holdElapsed = 0;
    state.holdInterval = HOLD_INITIAL_DELAY_MS;
    const stop = () => {
      if (this.numberFieldState[key].holdDir === direction) this.numberFieldState[key].holdDir = 0;
    };
    this.input.once(Phaser.Input.Events.POINTER_UP, stop);
    this.input.once(Phaser.Input.Events.POINTER_UP_OUTSIDE, stop);
    this.render();
  }

  // ── Train & Results tab actions ────────────────────────────────

  private doTrain(): void {
    const selectedFeatures = TRAINABLE_FEATURES.filter((f) => this.featureSelected[f]);
    if (!this.loadedDecisions || this.loadedDecisions.length === 0) {
      this.trainStatus = 'Load some decision logs on the Data tab first.';
      this.render();
      return;
    }
    try {
      this.trainedModel = trainConditionalLogit(this.loadedDecisions, selectedFeatures, {
        humanWeight: this.humanWeight,
        iterations: this.iterations,
      });
      const t = this.trainedModel.training;
      const humanAgreement =
        t.train_agreement_human_only !== null ? `${Math.round(t.train_agreement_human_only * 100)}%` : 'n/a';
      this.trainStatus =
        `Trained on ${t.num_decisions} decisions (${t.num_human_decisions} human, ` +
        `${t.num_ai_decisions} AI). Agreement: ${Math.round(t.train_agreement * 100)}% overall, ` +
        `${humanAgreement} on human-only decisions.`;
    } catch (err) {
      this.trainedModel = null;
      this.trainStatus = err instanceof MsomiTrainingError ? err.message : 'Training failed — please try again.';
    }
    this.render();
  }

  private doSave(): void {
    if (!this.trainedModel) return;
    const filename = `msomi_${Date.now()}`;
    void this.msomiStore.saveModel(filename, this.trainedModel).then(() => {
      this.lastSavedFilename = filename.endsWith('.json') ? filename : `${filename}.json`;
      this.resultStatus = `Saved to: ${this.lastSavedFilename}`;
      return this.refreshSavedModels();
    });
  }

  private loadSavedModel(filename: string): void {
    void this.msomiStore.loadModel(filename).then((model) => {
      const problem = validateModel(model);
      if (problem) {
        this.resultStatus = problem;
        this.render();
        return;
      }
      this.trainedModel = model;
      const weightsText = Object.entries(model.weights)
        .map(([f, w]) => `${FEATURE_LABELS[f as TrainableFeature] ?? f}: ${w.toFixed(3)}`)
        .join(', ');
      this.resultStatus = `Loaded "${filename}" — ${weightsText}`;
      this.render();
    });
  }

  private deleteSavedModel(filename: string): void {
    void this.msomiStore.deleteModel(filename).then(() => {
      this.resultStatus = `Deleted "${filename}".`;
      return this.refreshSavedModels();
    });
  }

  // ── Row-building per tab ───────────────────────────────────────

  private buildRows(): ChuoRowInput[] {
    switch (this.activeTab) {
      case 'data':
        return this.buildDataRows();
      case 'features':
        return this.buildFeatureRows();
      case 'model':
        return this.buildModelRows();
      case 'results':
        return this.buildResultsRows();
    }
  }

  private buildDataRows(): ChuoRowInput[] {
    const rows: ChuoRowInput[] = [
      { kind: 'button', key: 'select_all_logs', label: 'Select All', enabled: this.logFiles.length > 0 },
      {
        kind: 'button',
        key: 'select_none_logs',
        label: 'Select None',
        enabled: this.selectedLogIds.size > 0,
      },
      { kind: 'button', key: 'browse_logs', label: 'Import from device…', enabled: true, variant: 'default' },
    ];
    if (this.logFiles.length === 0) {
      rows.push({
        kind: 'text',
        key: 'no_logs',
        text:
          'No logged decisions found yet. Turn on Settings → Deck & Logging → Logging (HIGH), play a few ' +
          'games, then come back — or import a .jsonl log from elsewhere with the button above.',
      });
    }
    for (const file of this.logFiles) {
      rows.push({
        kind: 'checkbox',
        key: file.id,
        label: file.name,
        sublabel: `${(file.size / 1024).toFixed(1)} KB`,
        checked: this.selectedLogIds.has(file.id),
      });
    }
    rows.push({
      kind: 'button',
      key: 'load_selected_logs',
      label: `Load Selected Logs (${this.selectedLogIds.size})`,
      enabled: this.selectedLogIds.size > 0,
      variant: 'primary',
    });
    if (this.loadStatus) rows.push({ kind: 'text', key: 'load_status', text: this.loadStatus });
    return rows;
  }

  private buildFeatureRows(): ChuoRowInput[] {
    const rows: ChuoRowInput[] = [
      { kind: 'button', key: 'select_all_features', label: 'Select All', enabled: true },
      { kind: 'button', key: 'select_none_features', label: 'Select None', enabled: true },
    ];
    for (const feature of TRAINABLE_FEATURES) {
      rows.push({
        kind: 'checkbox',
        key: feature,
        label: FEATURE_LABELS[feature],
        checked: this.featureSelected[feature],
      });
    }
    return rows;
  }

  private buildModelRows(): ChuoRowInput[] {
    return [
      { kind: 'tier', key: 'light', label: 'Light (Re-weighted Scorer)', selected: this.modelTier === 'light', enabled: true },
      { kind: 'tier', key: 'heavy', label: 'Heavy (Tree Ensemble) — coming soon', selected: false, enabled: false },
      { kind: 'number', key: 'human_weight', label: 'Human decision weight', value: this.humanWeight, unit: 'x' },
      { kind: 'number', key: 'iterations', label: 'Training iterations', value: this.iterations, unit: '' },
    ];
  }

  private buildResultsRows(): ChuoRowInput[] {
    const selectedFeatureCount = TRAINABLE_FEATURES.filter((f) => this.featureSelected[f]).length;
    const rows: ChuoRowInput[] = [
      {
        kind: 'button',
        key: 'train',
        label: 'Train Model',
        enabled: !!this.loadedDecisions && this.loadedDecisions.length > 0 && selectedFeatureCount > 0,
        variant: 'danger',
      },
    ];
    if (this.trainStatus) rows.push({ kind: 'text', key: 'train_status', text: this.trainStatus });
    rows.push({
      kind: 'button',
      key: 'save',
      label: 'Save Model',
      enabled: this.trainedModel !== null,
      variant: 'primary',
    });
    if (this.resultStatus) rows.push({ kind: 'text', key: 'result_status', text: this.resultStatus });
    if (this.savedModels.length > 0) {
      rows.push({ kind: 'text', key: 'saved_models_header', text: 'Saved models:' });
      for (const filename of this.savedModels) {
        rows.push({ kind: 'model', key: filename, label: filename });
      }
    }
    return rows;
  }

  // ── Render ──────────────────────────────────────────────────────

  private render(): void {
    const insets = this.adapter.getSafeAreaInsets();
    const scrollOffset = this.scrollOffsetByTab[this.activeTab];
    const flow = computeChuoFlow(this.viewport(), insets, this.activeTab, this.buildRows(), scrollOffset);
    this.currentFlow = flow;

    this.clipMask.clear();
    this.clipMask.fillStyle(0xffffff);
    this.clipMask.fillRect(flow.contentRect.x, flow.viewportTop, flow.contentRect.width, flow.viewportHeight);

    for (const obj of this.dynamicObjects) obj.destroy();
    this.dynamicObjects = [];

    const theme = this.adapter.getTheme();

    for (const tab of flow.tabButtons) this.renderTabButton(tab, theme);

    for (const row of flow.rows) {
      if (this.isOffscreen(row.rowRect, flow)) continue;
      this.renderRow(row, theme);
    }

    this.renderBackButton(flow, theme);
    this.renderBackendLabel(flow);
  }

  private track<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.content.add(obj);
    this.dynamicObjects.push(obj);
    return obj;
  }

  /** For chrome that must NOT be clipped by the scroll viewport's
   * geometry mask -- the tab bar (above the scrollable band) and the
   * Back button / backend-storage label (below it). Bug found via a
   * live screenshot: everything routed through track() above ends up
   * inside `this.content`, which carries the SAME mask that clips the
   * scrollable row list to just the viewport band -- correct for rows,
   * but it was silently clipping these three fixed-position elements
   * into invisibility (they still existed, just outside the one
   * rectangle the mask allows through). Left in the scene's own root
   * display list instead (no reparenting into `this.content`), so no
   * mask applies, while still tracked here for the same destroy-and-
   * rebuild-every-render() cleanup every other dynamic object gets. */
  private trackUnmasked<T extends Phaser.GameObjects.GameObject>(obj: T): T {
    this.dynamicObjects.push(obj);
    return obj;
  }

  private renderTabButton(tab: ChuoFlow['tabButtons'][number], theme: ReturnType<PlatformAdapter['getTheme']>): void {
    const cx = tab.rect.x + tab.rect.width / 2;
    const cy = tab.rect.y + tab.rect.height / 2;
    const rect = this.trackUnmasked(
      this.add
        .rectangle(cx, cy, tab.rect.width, tab.rect.height, tab.active ? 0xd9a441 : 0x2a2a2a)
        .setStrokeStyle(1, 0xffffff, 0.3)
        .setInteractive({ useHandCursor: true }),
    );
    rect.on('pointerdown', () => this.setTab(tab.id));
    this.trackUnmasked(
      this.add
        .text(cx, cy, tab.label, {
          fontFamily: 'sans-serif',
          fontSize: '14px',
          color: tab.active ? '#1a1a1a' : theme.text,
          fontStyle: tab.active ? 'bold' : 'normal',
        })
        .setOrigin(0.5),
    );
  }

  private renderRow(row: ChuoPositionedRow, theme: ReturnType<PlatformAdapter['getTheme']>): void {
    switch (row.kind) {
      case 'checkbox':
        this.renderCheckboxRow(row, theme);
        break;
      case 'button':
        this.renderButtonRow(row, theme);
        break;
      case 'number':
        this.renderNumberRow(row, theme);
        break;
      case 'tier':
        this.renderTierRow(row);
        break;
      case 'text':
        this.renderTextRow(row);
        break;
      case 'model':
        this.renderModelRow(row, theme);
        break;
    }
  }

  private renderCheckboxRow(
    row: Extract<ChuoPositionedRow, { kind: 'checkbox' }>,
    theme: ReturnType<PlatformAdapter['getTheme']>,
  ): void {
    const { input } = row;
    const box = this.track(
      this.add
        .rectangle(
          row.checkboxRect.x + row.checkboxRect.width / 2,
          row.checkboxRect.y + row.checkboxRect.height / 2,
          row.checkboxRect.width,
          row.checkboxRect.height,
          input.checked ? 0x288c32 : 0x282828,
        )
        .setStrokeStyle(1, 0xffffff, 0.5)
        .setInteractive({ useHandCursor: true }),
    );
    box.on('pointerdown', () => this.onCheckboxToggled(input.key));
    this.track(
      this.add.text(row.labelPos.x, row.labelPos.y, input.label, {
        fontFamily: 'sans-serif',
        fontSize: `${row.labelPos.fontPx}px`,
        color: theme.text,
      }).setOrigin(0, 0.5),
    );
    if (row.sublabelPos && input.sublabel) {
      this.track(
        this.add.text(row.sublabelPos.x, row.sublabelPos.y, input.sublabel, {
          fontFamily: 'sans-serif',
          fontSize: `${row.sublabelPos.fontPx}px`,
          color: '#96a094',
        }).setOrigin(0, 0.5),
      );
    }
  }

  private onCheckboxToggled(key: string): void {
    if (this.activeTab === 'data') this.toggleLogSelected(key);
    else if (this.activeTab === 'features') this.toggleFeature(key);
  }

  private renderButtonRow(
    row: Extract<ChuoPositionedRow, { kind: 'button' }>,
    theme: ReturnType<PlatformAdapter['getTheme']>,
  ): void {
    const { input } = row;
    const color = !input.enabled ? 0x333333 : input.variant === 'danger' ? 0xa01e1e : input.variant === 'primary' ? 0x3c6e3c : 0x32506e;
    const rect = this.add
      .rectangle(
        row.rowRect.x + row.rowRect.width / 2,
        row.rowRect.y + row.rowRect.height / 2,
        row.rowRect.width,
        row.rowRect.height,
        color,
      )
      .setStrokeStyle(1, 0xffffff, 0.4);
    if (input.enabled) {
      rect.setInteractive({ useHandCursor: true });
      rect.on('pointerdown', () => this.onButtonClicked(input.key));
    }
    this.content.add(rect);
    this.dynamicObjects.push(rect);
    this.track(
      this.add
        .text(row.labelPos.x, row.labelPos.y, input.label, {
          fontFamily: 'sans-serif',
          fontSize: `${row.labelPos.fontPx}px`,
          color: input.enabled ? theme.text : '#777777',
        })
        .setOrigin(0.5),
    );
  }

  private onButtonClicked(key: string): void {
    switch (key) {
      case 'select_all_logs':
        return this.selectAllLogs();
      case 'select_none_logs':
        return this.selectNoneLogs();
      case 'browse_logs':
        return this.browseForLogs();
      case 'load_selected_logs':
        return this.loadSelectedLogs();
      case 'select_all_features':
        return this.selectAllFeatures();
      case 'select_none_features':
        return this.selectNoneFeatures();
      case 'train':
        return this.doTrain();
      case 'save':
        return this.doSave();
    }
  }

  private renderNumberRow(
    row: Extract<ChuoPositionedRow, { kind: 'number' }>,
    theme: ReturnType<PlatformAdapter['getTheme']>,
  ): void {
    const { input } = row;
    this.track(
      this.add.text(row.labelPos.x, row.labelPos.y, input.label, {
        fontFamily: 'sans-serif',
        fontSize: `${row.labelPos.fontPx}px`,
        color: theme.text,
      }),
    );
    this.track(
      this.add
        .text(row.valuePos.x, row.valuePos.y, `${input.value}${input.unit}`, {
          fontFamily: 'sans-serif',
          fontSize: `${row.labelPos.fontPx}px`,
          color: '#ffffff',
        })
        .setOrigin(1, 0.5),
    );
    const key = input.key as 'human_weight' | 'iterations';
    this.renderStepper(row.decrementRect, '-', () => this.startHold(key, -1));
    this.renderStepper(row.incrementRect, '+', () => this.startHold(key, 1));
  }

  private renderStepper(rect: RectLayout, symbol: string, onClick: () => void): void {
    const btn = this.track(
      this.add
        .rectangle(rect.x + rect.width / 2, rect.y + rect.height / 2, rect.width, rect.height, 0x284630)
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    btn.on('pointerdown', onClick);
    this.track(
      this.add
        .text(rect.x + rect.width / 2, rect.y + rect.height / 2, symbol, {
          fontFamily: 'sans-serif',
          fontSize: `${Math.round(rect.height * 0.5)}px`,
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderTierRow(row: Extract<ChuoPositionedRow, { kind: 'tier' }>): void {
    const { input } = row;
    const cx = row.rowRect.x + row.rowRect.width / 2;
    const cy = row.rowRect.y + row.rowRect.height / 2;
    const color = !input.enabled ? 0x2a2a2a : input.selected ? 0xd9a441 : 0x325a3c;
    const rect = this.add
      .rectangle(cx, cy, row.rowRect.width, row.rowRect.height, color)
      .setStrokeStyle(1, 0xffffff, 0.4);
    if (input.enabled) {
      rect.setInteractive({ useHandCursor: true });
      rect.on('pointerdown', () => {
        this.modelTier = input.key as 'light' | 'heavy';
        this.render();
      });
    }
    this.content.add(rect);
    this.dynamicObjects.push(rect);
    this.track(
      this.add
        .text(cx, cy, input.label, {
          fontFamily: 'sans-serif',
          fontSize: `${row.labelPos.fontPx}px`,
          color: input.enabled ? (input.selected ? '#1a1a1a' : '#ffffff') : '#777777',
        })
        .setOrigin(0.5),
    );
  }

  private renderTextRow(row: Extract<ChuoPositionedRow, { kind: 'text' }>): void {
    for (const line of row.lines) {
      this.track(
        this.add.text(line.x, line.y, line.text, {
          fontFamily: 'sans-serif',
          fontSize: `${line.fontPx}px`,
          color: '#a0a89e',
        }),
      );
    }
  }

  private renderModelRow(
    row: Extract<ChuoPositionedRow, { kind: 'model' }>,
    theme: ReturnType<PlatformAdapter['getTheme']>,
  ): void {
    const { input } = row;
    this.track(
      this.add.text(row.labelPos.x, row.labelPos.y, input.label, {
        fontFamily: 'sans-serif',
        fontSize: `${row.labelPos.fontPx}px`,
        color: theme.text,
      }).setOrigin(0, 0.5),
    );
    const loadBtn = this.track(
      this.add
        .rectangle(
          row.loadButton.x + row.loadButton.width / 2,
          row.loadButton.y + row.loadButton.height / 2,
          row.loadButton.width,
          row.loadButton.height,
          0x32506e,
        )
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    loadBtn.on('pointerdown', () => this.loadSavedModel(input.key));
    this.track(
      this.add
        .text(row.loadButton.x + row.loadButton.width / 2, row.loadButton.y + row.loadButton.height / 2, 'Load', {
          fontFamily: 'sans-serif',
          fontSize: '12px',
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
    const deleteBtn = this.track(
      this.add
        .rectangle(
          row.deleteButton.x + row.deleteButton.width / 2,
          row.deleteButton.y + row.deleteButton.height / 2,
          row.deleteButton.width,
          row.deleteButton.height,
          0x782828,
        )
        .setStrokeStyle(1, 0xffffff, 0.4)
        .setInteractive({ useHandCursor: true }),
    );
    deleteBtn.on('pointerdown', () => this.deleteSavedModel(input.key));
    this.track(
      this.add
        .text(row.deleteButton.x + row.deleteButton.width / 2, row.deleteButton.y + row.deleteButton.height / 2, 'Delete', {
          fontFamily: 'sans-serif',
          fontSize: '11px',
          color: '#ffffff',
        })
        .setOrigin(0.5),
    );
  }

  private renderBackButton(flow: ChuoFlow, theme: ReturnType<PlatformAdapter['getTheme']>): void {
    const cx = flow.backButton.x + flow.backButton.width / 2;
    const cy = flow.backButton.y + flow.backButton.height / 2;
    const rect = this.trackUnmasked(
      this.add
        .rectangle(cx, cy, flow.backButton.width, flow.backButton.height, 0x3c2864)
        .setStrokeStyle(1, 0xffffff, 0.6)
        .setInteractive({ useHandCursor: true }),
    );
    rect.on('pointerdown', () => {
      this.scene.start('MainMenuScene', { adapter: this.adapter, msomiStore: this.msomiStore });
    });
    this.trackUnmasked(
      this.add
        .text(cx, cy, 'Back', { fontFamily: 'sans-serif', fontSize: '16px', color: theme.text })
        .setOrigin(0.5),
    );
  }

  private renderBackendLabel(flow: ChuoFlow): void {
    const text =
      this.msomiStore.backendKind === 'file-system-access' ? 'Storage: Files' : 'Storage: Browser storage';
    this.trackUnmasked(
      this.add
        .text(flow.backendLabelPos.x, flow.backendLabelPos.y, text, {
          fontFamily: 'sans-serif',
          fontSize: `${flow.backendLabelPos.fontPx}px`,
          color: '#777777',
        })
        .setOrigin(1, 0.5),
    );
  }

  /** Exposed for a future MSOMI-attach flow (out of scope this pass,
   * see this file's header) that wants to score an option against
   * whatever model Chuo currently has loaded/trained without
   * re-importing trainer.ts itself. Unused internally beyond that. */
  scoreWithCurrentModel(optionFeatures: Record<string, unknown>): number | null {
    return this.trainedModel ? scoreOption(this.trainedModel, optionFeatures) : null;
  }
}
