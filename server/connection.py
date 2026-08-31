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

Wire framing and message encoding are reused EXACTLY from
network/protocol.py -- nothing about the newline-delimited JSON
framing is reinvented here.
"""
from __future__ import annotations
import itertools
import queue
import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from network.protocol import FrameBuffer, encode_message, ProtocolError

DEFAULT_PORT = 52010


@dataclass
class ServerConnection:
    conn_id: int
    sock: socket.socket
    addr: tuple
    name: str = "Player"
    room_id: Optional[str] = None
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    alive: bool = True


class ConnectionManager:
    """Accepts inbound TCP connections and multiplexes messages from
    all of them onto one queue -- the same job network.host.LANHost
    does for a single game, just without the per-game scoping (many
    rooms can share this one listener)."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._listener: Optional[socket.socket] = None
        self._listener_thread: Optional[threading.Thread] = None
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

    def stop(self):
        self._running = False
        try:
            if self._listener:
                self._listener.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._conns.values())
        for c in conns:
            self._close_conn(c)

    # ── accept loop (background thread) ─────────────────────────────────────
    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except OSError:
                break  # listener closed -> stop() was called
            conn = ServerConnection(conn_id=next(self._id_counter), sock=sock, addr=addr)
            with self._lock:
                self._conns[conn.conn_id] = conn
            t = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
            t.start()
            self.incoming.put((conn.conn_id, {'type': '_connected', 'addr': addr}))

    # ── per-connection recv loop (background thread) ─────────────────────────
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
    def send_to(self, conn_id: int, msg: dict):
        with self._lock:
            conn = self._conns.get(conn_id)
        if conn is None:
            return
        try:
            with conn.write_lock:
                conn.sock.sendall(encode_message(msg))
        except OSError:
            self._close_conn(conn)

    def broadcast(self, conn_ids: List[int], msg: dict, exclude: Optional[int] = None):
        frame = encode_message(msg)
        with self._lock:
            targets = [self._conns[c] for c in conn_ids if c in self._conns]
        for conn in targets:
            if exclude is not None and conn.conn_id == exclude:
                continue
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
