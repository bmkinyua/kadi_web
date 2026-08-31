"""
KADI - Internet multiplayer: server-side connection plumbing.

Same threading rule as network/host.py (read that module's docstring
first if you haven't): background threads (one accept thread + one
recv thread per connection) ONLY ever push (conn_id, message_dict)
tuples onto a queue.Queue. The main server loop (server/kadi_server.py)
is the only thread that reads that queue, mutates any Lobby/GameRoom/
GameManager state, or calls send_to()/broadcast().

Differs from network/host.py in exactly one structural way: LANHost is
scoped to ONE game (one accept loop feeding one shared match). This
server is scoped to MANY concurrent games multiplexed over a single
listening port, so the connection registry here is global (keyed by a
process-wide connection id) rather than assuming every connection
belongs to the same match. Which room (if any) a connection belongs to
is tracked as a mutable `room_id` attribute on its ServerConnection,
set by the Lobby once that connection creates/joins a game -- it isn't
known at accept time, since a connection sits in the matchmaking lobby
first.

TWO transports, ONE queue: the original TCP listener (wire framing
from network/protocol.py, newline-delimited JSON -- what the desktop
pygame client speaks) and a WebSocket listener (framing from
network/ws_protocol.py -- what a browser-based client on Discord/
Telegram/WeChat/the standalone web-pwa speaks, added for the web port)
run as two independent accept loops on two ports, but every connection
from either one is a plain ServerConnection pushing the exact same
(conn_id, message_dict) shape onto self.incoming. server/kadi_server.py,
server/lobby.py, and server/game_room.py were written against that
queue + send_to()/broadcast(), never against a socket directly, so
none of them needed to change for this -- they don't know or care
which transport a given conn_id arrived on.
"""
from __future__ import annotations
import itertools
import json
import queue
import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from network.protocol import FrameBuffer, encode_message, ProtocolError
from network import ws_protocol

DEFAULT_PORT = 52010
DEFAULT_WS_PORT = 53010


@dataclass
class ServerConnection:
    conn_id: int
    sock: socket.socket
    addr: tuple
    name: str = "Player"
    room_id: Optional[str] = None
    transport: str = "tcp"  # 'tcp' or 'ws' -- decides how send_to()/broadcast() encode outgoing frames
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    alive: bool = True


class ConnectionManager:
    """Accepts inbound TCP AND WebSocket connections and multiplexes
    messages from all of them onto one queue -- the same job
    network.host.LANHost does for a single game, just without the
    per-game scoping (many rooms can share this one listener), and now
    across two transports instead of one."""

    def __init__(self, port: int = DEFAULT_PORT, ws_port: Optional[int] = DEFAULT_WS_PORT):
        self.port = port
        self.ws_port = ws_port  # None disables the WS listener entirely (e.g. LAN-only deployments)
        self._listener: Optional[socket.socket] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._ws_listener: Optional[socket.socket] = None
        self._ws_listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()          # guards _conns
        self._conns: Dict[int, ServerConnection] = {}
        self._id_counter = itertools.count(1)
        self.incoming: "queue.Queue[tuple]" = queue.Queue()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(('0.0.0.0', self.port))
        self._listener.listen(64)
        self._running = True
        self._listener_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._listener_thread.start()

        if self.ws_port is not None:
            self._ws_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._ws_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._ws_listener.bind(('0.0.0.0', self.ws_port))
            self._ws_listener.listen(64)
            self._ws_listener_thread = threading.Thread(target=self._ws_accept_loop, daemon=True)
            self._ws_listener_thread.start()

    def stop(self):
        self._running = False
        for listener in (self._listener, self._ws_listener):
            try:
                if listener:
                    listener.close()
            except OSError:
                pass
        with self._lock:
            conns = list(self._conns.values())
        for c in conns:
            self._close_conn(c)

    # ── TCP accept loop (background thread) ─────────────────────────────────
    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except OSError:
                break  # listener closed -> stop() was called
            conn = ServerConnection(conn_id=next(self._id_counter), sock=sock, addr=addr, transport='tcp')
            with self._lock:
                self._conns[conn.conn_id] = conn
            t = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
            t.start()
            self.incoming.put((conn.conn_id, {'type': '_connected', 'addr': addr}))

    # ── TCP per-connection recv loop (background thread) ────────────────────
    def _recv_loop(self, conn: ServerConnection):
        buf = FrameBuffer()
        sock = conn.sock
        try:
            while self._running and conn.alive:
                data = sock.recv(4096)
                if not data:
                    break
                try:
                    msgs = buf.feed(data)
                except ProtocolError:
                    break
                for m in msgs:
                    self.incoming.put((conn.conn_id, m))
        except OSError:
            pass
        finally:
            self._close_conn(conn)
            self.incoming.put((conn.conn_id, {'type': '_disconnected'}))

    # ── WS accept loop (background thread) ──────────────────────────────────
    def _ws_accept_loop(self):
        while self._running:
            try:
                sock, addr = self._ws_listener.accept()
            except OSError:
                break  # listener closed -> stop() was called
            # Handshake happens on its own thread too (not inline here)
            # so one slow/hostile client doing the HTTP handshake can't
            # stall accept() for everyone else -- same reasoning as why
            # the TCP path hands each connection to its own thread
            # immediately rather than reading anything before spawning it.
            t = threading.Thread(target=self._ws_handshake_and_serve, args=(sock, addr), daemon=True)
            t.start()

    # ── WS handshake + per-connection recv loop (background thread) ─────────
    def _ws_handshake_and_serve(self, sock: socket.socket, addr: tuple):
        try:
            ws_protocol.perform_server_handshake(sock)
        except (ws_protocol.WSProtocolError, OSError):
            try:
                sock.close()
            except OSError:
                pass
            return  # not a valid WS client -- silently drop, same as a
                     # garbage first line would on the raw-TCP listener

        conn = ServerConnection(conn_id=next(self._id_counter), sock=sock, addr=addr, transport='ws')
        with self._lock:
            self._conns[conn.conn_id] = conn
        self.incoming.put((conn.conn_id, {'type': '_connected', 'addr': addr}))

        try:
            while self._running and conn.alive:
                try:
                    text = ws_protocol.recv_frame(sock)
                except ws_protocol.WSClosed:
                    break
                except ws_protocol.WSProtocolError:
                    break
                if text is None:
                    continue  # was a PING/PONG -- recv_frame already handled it
                try:
                    msg = json.loads(text)
                except (TypeError, ValueError):
                    break  # malformed JSON payload -- same fate as a ProtocolError on the TCP path
                if not isinstance(msg, dict):
                    break  # every real message here is a dict, same invariant protocol.py enforces
                self.incoming.put((conn.conn_id, msg))
        except OSError:
            pass
        finally:
            self._close_conn(conn)
            self.incoming.put((conn.conn_id, {'type': '_disconnected'}))

    def _close_conn(self, conn: ServerConnection):
        conn.alive = False
        # shutdown() before close() -- see the identical comment in
        # network/client.py's close() / network/host.py's
        # _close_client(): needed to reliably wake a thread that may
        # be blocked in recv() on this same fd and to promptly deliver
        # a FIN to the peer.
        try:
            conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.sock.close()
        except OSError:
            pass
        with self._lock:
            self._conns.pop(conn.conn_id, None)

    # ── outgoing — MAIN THREAD ONLY ───────────────────────────────────────────
    def _encode_for(self, conn: ServerConnection, msg: dict) -> bytes:
        """Pick wire framing by transport -- everything upstream of
        this (kadi_server.py, game_room.py, lobby.py) just calls
        send_to()/broadcast() with a plain dict and never needs to
        know or care which transport conn_id arrived on."""
        if conn.transport == 'ws':
            return ws_protocol.encode_text_frame(json.dumps(msg, separators=(',', ':')))
        return encode_message(msg)

    def send_to(self, conn_id: int, msg: dict):
        with self._lock:
            conn = self._conns.get(conn_id)
        if conn is None:
            return
        try:
            with conn.write_lock:
                conn.sock.sendall(self._encode_for(conn, msg))
        except OSError:
            self._close_conn(conn)

    def broadcast(self, conn_ids: List[int], msg: dict, exclude: Optional[int] = None):
        # Pre-encode once per transport (not once per connection) --
        # every 'tcp' target shares the identical newline-JSON frame,
        # every 'ws' target shares the identical WS frame; only the
        # per-connection write itself needs to happen individually.
        tcp_frame = encode_message(msg)
        ws_frame = ws_protocol.encode_text_frame(json.dumps(msg, separators=(',', ':')))
        with self._lock:
            targets = [self._conns[c] for c in conn_ids if c in self._conns]
        for conn in targets:
            if exclude is not None and conn.conn_id == exclude:
                continue
            frame = ws_frame if conn.transport == 'ws' else tcp_frame
            try:
                with conn.write_lock:
                    conn.sock.sendall(frame)
            except OSError:
                self._close_conn(conn)

    # ── bookkeeping ────────────────────────────────────────────────────────
    def set_name(self, conn_id: int, name: str):
        with self._lock:
            conn = self._conns.get(conn_id)
            if conn:
                conn.name = name

    def get_conn(self, conn_id: int) -> Optional[ServerConnection]:
        with self._lock:
            return self._conns.get(conn_id)

    def set_room(self, conn_id: int, room_id: Optional[str]):
        with self._lock:
            conn = self._conns.get(conn_id)
            if conn:
                conn.room_id = room_id

    def poll(self) -> List[tuple]:
        """Drain all currently-queued (conn_id, message) pairs
        (non-blocking). Call once per server tick from the main thread."""
        out = []
        while True:
            try:
                out.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return out
