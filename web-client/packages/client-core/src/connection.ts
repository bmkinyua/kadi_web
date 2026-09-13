/**
 * KADI - platform-agnostic WebSocket connection wrapper.
 *
 * This is intentionally NOT where game rules or state authority live
 * -- see KADI_web_port_implementation_plan.md §0: the Python server
 * (server/kadi_server.py, core/game_manager.py) stays the sole
 * authority, completely unmodified in that role. This class only
 * owns: opening the socket, encoding outgoing messages as JSON text
 * frames (server/ws_protocol.py decodes them server-side), decoding
 * incoming ones, and a typed pub/sub so packages/renderer can react
 * to server messages without importing anything platform-specific.
 *
 * Runs identically under every adapter (Discord/Telegram/WeChat/
 * web-pwa) -- none of them change how a WebSocket behaves, only WHERE
 * the URL points and how identity gets attached to the 'hello' sent
 * right after connecting (see PlatformAdapter.getPlayerId() and
 * KadiConnection.sendHello() below).
 */
import type { ClientMessage, ServerMessage } from '@kadi/protocol';

export type ConnectionState = 'connecting' | 'open' | 'closed' | 'reconnecting';

type Listener<T> = (payload: T) => void;

export class KadiConnection {
  private ws: WebSocket | null = null;
  private readonly url: string;
  private state: ConnectionState = 'closed';
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manuallyClosed = false;

  private readonly messageListeners = new Set<Listener<ServerMessage>>();
  private readonly stateListeners = new Set<Listener<ConnectionState>>();

  constructor(url: string) {
    this.url = url;
  }

  connect(): void {
    this.manuallyClosed = false;
    this.setState(this.reconnectAttempt > 0 ? 'reconnecting' : 'connecting');
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.setState('open');
    };

    ws.onmessage = (event: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(String(event.data));
      } catch {
        return; // malformed frame -- same "just drop it" stance protocol.py takes server-side
      }
      if (parsed && typeof parsed === 'object' && 'type' in parsed) {
        for (const listener of this.messageListeners) listener(parsed as ServerMessage);
      }
    };

    ws.onclose = () => {
      this.ws = null;
      if (this.manuallyClosed) {
        this.setState('closed');
        return;
      }
      this.setState('reconnecting');
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose always follows onerror for a WebSocket -- reconnect
      // logic lives there, not duplicated here.
    };
  }

  private scheduleReconnect(): void {
    // Exponential backoff, capped at 10s, so a client sitting in a
    // Discord/Telegram tab that's lost its connection doesn't hammer
    // the server -- 1s, 2s, 4s, 8s, 10s, 10s, ...
    const delayMs = Math.min(10_000, 1000 * 2 ** this.reconnectAttempt);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delayMs);
  }

  close(): void {
    this.manuallyClosed = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  send(msg: ClientMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
    // Silently dropped if not open yet -- callers that need
    // guaranteed delivery should wait for an 'open' state event
    // first; nothing in the current lobby-level message set (§ scope
    // note in packages/protocol) needs stronger guarantees than that.
  }

  onMessage(listener: Listener<ServerMessage>): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  onStateChange(listener: Listener<ConnectionState>): () => void {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  getState(): ConnectionState {
    return this.state;
  }

  /** Exposed for diagnostics only (see LobbyScene.ts's status text) --
   * a plain "Reconnecting..." with no indication of WHAT it's trying
   * to reach is nearly undebuggable for a non-technical tester (e.g.
   * a stale VITE_WS_URL still pointing at localhost on a phone, which
   * looks IDENTICAL to a firewall block or a server that isn't
   * running -- all three show as "stuck reconnecting forever" with no
   * further detail otherwise). */
  getUrl(): string {
    return this.url;
  }

  private setState(next: ConnectionState): void {
    this.state = next;
    for (const listener of this.stateListeners) listener(next);
  }
}
