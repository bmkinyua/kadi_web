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
 */
import Phaser from 'phaser';
import { KadiConnection } from '@kadi/client-core';
import type { ConnectionState } from '@kadi/client-core';
import type { ServerMessage } from '@kadi/protocol';
import type { PlatformAdapter } from '@kadi/adapter-interface';

export class LobbyScene extends Phaser.Scene {
  private adapter!: PlatformAdapter;
  private connection!: KadiConnection;

  private statusText!: Phaser.GameObjects.Text;
  private identityText!: Phaser.GameObjects.Text;
  private rankText!: Phaser.GameObjects.Text;
  private leaderboardLines: Phaser.GameObjects.Text[] = [];

  constructor() {
    super('LobbyScene');
  }

  /** Called once by an app entry point (e.g. apps/web-pwa/src/main.ts)
   * before the game boots -- see that file for why adapter selection
   * happens there, at build/entry time, rather than this scene
   * guessing which platform it's on. */
  init(data: { adapter: PlatformAdapter }): void {
    this.adapter = data.adapter;
  }

  create(): void {
    const theme = this.adapter.getTheme();
    this.cameras.main.setBackgroundColor(theme.background);

    this.statusText = this.add.text(24, 24, 'Connecting…', {
      fontFamily: 'sans-serif',
      fontSize: '20px',
      color: theme.text,
    });

    this.identityText = this.add.text(24, 56, '', {
      fontFamily: 'sans-serif',
      fontSize: '16px',
      color: theme.text,
    });

    this.rankText = this.add.text(24, 84, '', {
      fontFamily: 'sans-serif',
      fontSize: '16px',
      color: theme.accent,
    });

    this.add.text(24, 128, 'Global Leaderboard', {
      fontFamily: 'sans-serif',
      fontSize: '18px',
      color: theme.text,
      fontStyle: 'bold',
    });

    this.connection = new KadiConnection(this.adapter.getWebSocketUrl());
    this.connection.onStateChange((state) => this.onConnectionState(state));
    this.connection.onMessage((msg) => this.onServerMessage(msg));

    this.adapter.onReady(() => this.connection.connect());
  }

  private onConnectionState(state: ConnectionState): void {
    const labels: Record<ConnectionState, string> = {
      connecting: 'Connecting…',
      open: 'Connected',
      reconnecting: 'Reconnecting…',
      closed: 'Disconnected',
    };
    this.statusText.setText(labels[state]);

    if (state === 'open') {
      void this.sendHelloAndRequestLeaderboard();
    }
  }

  private async sendHelloAndRequestLeaderboard(): Promise<void> {
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
    }
  }

  private renderLeaderboard(entries: { name: string; wins: number }[]): void {
    for (const line of this.leaderboardLines) line.destroy();
    this.leaderboardLines = [];

    const theme = this.adapter.getTheme();
    entries.forEach((entry, i) => {
      const line = this.add.text(24, 160 + i * 22, `${i + 1}. ${entry.name} — ${entry.wins} wins`, {
        fontFamily: 'sans-serif',
        fontSize: '15px',
        color: theme.text,
      });
      this.leaderboardLines.push(line);
    });

    if (entries.length === 0) {
      const line = this.add.text(24, 160, 'No wins recorded yet — be the first!', {
        fontFamily: 'sans-serif',
        fontSize: '15px',
        color: theme.text,
      });
      this.leaderboardLines.push(line);
    }
  }
}
