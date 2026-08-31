"""
KADI - LAN networking: host (server) side socket plumbing.

THREADING MODEL (read this before touching anything below):
  - One background "accept" thread blocks on listener.accept() and
    spins up a new per-client "recv" thread for each connection.
  - Each per-client recv thread does nothing but block on sock.recv(),
    feed bytes into a FrameBuffer, and push (player_id, message_dict)
    tuples onto self.incoming, a thread-safe queue.Queue. It NEVER
    touches GameManager, pygame, or any other shared game state
    directly — that would race against the main thread.
  - The main (pygame) thread is the ONLY thread that ever calls
    poll()/reads self.incoming, mutates GameManager, or calls
    send_to()/broadcast(). This single-consumer, single-mutator
    design is what makes this safe without a lock around game state:
    the only genuinely shared mutable structure between threads is
    the queue itself (internally locked) and self._clients (guarded
    by self._lock below, touched by both the accept thread and the
    main thread when it calls broadcast()/send_to()).
  - Each ClientConnection carries its own write_lock purely so a
    socket is never sendall()'d from two threads at once; in the
    current design only the main thread ever writes, so in practice
    this lock is never contended, but it costs nothing and removes an
    assumption that could silently break if that ever changes.
"""
from __future__ import annotations
import queue
import socket
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from constants import MAX_PLAYERS
from network.protocol import FrameBuffer, encode_message, ProtocolError

DEFAULT_PORT = 51999


@dataclass
class ClientConnection:
    player_id: int
    name: str
    sock: socket.socket
    addr: tuple
    write_lock: threading.Lock = field(default_factory=threading.Lock)
    alive: bool = True


class LANHost:
    def __init__(self, port: int = DEFAULT_PORT, max_players: int = MAX_PLAYERS):
        self.port = port
        self.max_players = max_players
        self._listener: Optional[socket.socket] = None
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()          # guards _clients / _next_player_id
        self._clients: Dict[int, ClientConnection] = {}
        self._next_player_id = 1               # host itself is always player_id 0
        self.incoming: "queue.Queue[tuple]" = queue.Queue()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def start(self):
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(('0.0.0.0', self.port))
        self._listener.listen(8)
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
            conns = list(self._clients.values())
        for c in conns:
            self._close_client(c)

    @staticmethod
    def local_ip() -> str:
        """Best-effort LAN-facing IP address to show the host, so they
        can tell other players what to type in. Doesn't actually send
        any traffic anywhere — connecting a UDP socket (even to an
        address never reached) is the standard trick to ask the OS
        routing table which local interface/IP it would use, without
        requiring that address to actually be reachable."""
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
        except OSError:
            return '127.0.0.1'
        finally:
            s.close()

    # ── accept loop (background thread) ─────────────────────────────────────
    def _accept_loop(self):
        while self._running:
            try:
                sock, addr = self._listener.accept()
            except OSError:
                break  # listener closed -> stop() was called
            with self._lock:
                full = len(self._clients) >= (self.max_players - 1)
                pid = self._next_player_id
            if full:
                try:
                    sock.sendall(encode_message({'type': 'reject', 'reason': 'Game is full'}))
                    sock.close()
                except OSError:
                    pass
                continue
            conn = ClientConnection(player_id=pid, name=f"Player{pid + 1}", sock=sock, addr=addr)
            with self._lock:
                self._clients[pid] = conn
                self._next_player_id += 1
            t = threading.Thread(target=self._recv_loop, args=(conn,), daemon=True)
            t.start()
            self.incoming.put((pid, {'type': '_connected', 'addr': addr}))

    # ── per-client recv loop (background thread) ─────────────────────────────
    def _recv_loop(self, conn: ClientConnection):
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
                    self.incoming.put((conn.player_id, m))
        except OSError:
            pass
        finally:
            self._close_client(conn)
            self.incoming.put((conn.player_id, {'type': '_disconnected'}))

    def _close_client(self, conn: ClientConnection):
        conn.alive = False
        # shutdown() before close() — see the identical comment in
        # network/client.py's close(): needed to reliably wake a
        # thread that may be blocked in recv() on this same fd and to
        # promptly deliver a FIN to that client, rather than leaving
        # the socket to close only once garbage collected.
        try:
            conn.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.sock.close()
        except OSError:
            pass
        with self._lock:
            self._clients.pop(conn.player_id, None)

    # ── outgoing — MAIN THREAD ONLY ───────────────────────────────────────────
    def send_to(self, player_id: int, msg: dict):
        with self._lock:
            conn = self._clients.get(player_id)
        if conn is None:
            return
        try:
            with conn.write_lock:
                conn.sock.sendall(encode_message(msg))
        except OSError:
            self._close_client(conn)

    def broadcast(self, msg: dict, exclude: Optional[int] = None):
        with self._lock:
            conns = list(self._clients.values())
        frame = encode_message(msg)
        for conn in conns:
            if exclude is not None and conn.player_id == exclude:
                continue
            try:
                with conn.write_lock:
                    conn.sock.sendall(frame)
            except OSError:
                self._close_client(conn)

    # ── bookkeeping ────────────────────────────────────────────────────────
    def player_ids(self) -> List[int]:
        with self._lock:
            return list(self._clients.keys())

    def set_name(self, player_id: int, name: str):
        with self._lock:
            conn = self._clients.get(player_id)
            if conn:
                conn.name = name

    def get_name(self, player_id: int) -> Optional[str]:
        with self._lock:
            conn = self._clients.get(player_id)
            return conn.name if conn else None

    def poll(self) -> List[tuple]:
        """Drain all currently-queued (player_id, message) pairs
        (non-blocking). Call once per frame from the main thread."""
        out = []
        while True:
            try:
                out.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return out
