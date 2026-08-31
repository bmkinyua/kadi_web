"""
KADI - LAN networking: client (joining player) side socket plumbing.

Same threading rule as network/host.py: a single background recv
thread only ever pushes decoded messages onto self.incoming (a
queue.Queue); it never touches game/UI state. The main thread is the
only thread that calls poll() or send().
"""
from __future__ import annotations
import queue
import socket
import threading
from typing import List, Optional

from network.protocol import FrameBuffer, encode_message, ProtocolError
from constants import VERSION


class ConnectError(Exception):
    pass


class LANClient:
    def __init__(self):
        self._sock: Optional[socket.socket] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._running = False
        self.connected = False
        self.player_id: Optional[int] = None
        self.incoming: "queue.Queue[dict]" = queue.Queue()

    def connect(self, host_ip: str, port: int, name: str, timeout: float = 5.0):
        """Blocking TCP connect + fire off the 'hello' handshake
        message. Raises ConnectError on failure. Does NOT wait for the
        host's 'welcome' reply — that arrives asynchronously like any
        other message and is read via poll(). Callers running this
        from the pygame main thread should do so from a short-lived
        background thread (see scenes.LANJoinScene) so a slow/failed
        connection attempt can't freeze the UI.
        """
        try:
            sock = socket.create_connection((host_ip, port), timeout=timeout)
        except (OSError, socket.timeout) as e:
            raise ConnectError(f"Could not connect to {host_ip}:{port} - {e}") from e
        sock.settimeout(None)
        self._sock = sock
        self._running = True
        self.connected = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()
        self.send({'type': 'hello', 'name': name, 'version': VERSION})

    def _recv_loop(self):
        buf = FrameBuffer()
        try:
            while self._running:
                data = self._sock.recv(4096)
                if not data:
                    break
                try:
                    msgs = buf.feed(data)
                except ProtocolError:
                    break
                for m in msgs:
                    if m.get('type') == 'welcome':
                        self.player_id = m.get('player_id')
                    self.incoming.put(m)
        except OSError:
            pass
        finally:
            self.connected = False
            self.incoming.put({'type': '_disconnected'})

    def send(self, msg: dict):
        if not self._sock:
            return
        try:
            with self._write_lock:
                self._sock.sendall(encode_message(msg))
        except OSError:
            self.connected = False

    def close(self):
        self._running = False
        self.connected = False
        if self._sock:
            # shutdown() BEFORE close() matters here: the background
            # recv thread is blocked inside sock.recv() on this same
            # fd. Just calling close() from this (different) thread
            # does not reliably wake that blocked recv() or deliver a
            # FIN to the peer — observed hanging indefinitely in
            # testing. shutdown(SHUT_RDWR) forces the blocked recv()
            # to return immediately with EOF and properly notifies the
            # peer, so the host's disconnect gets detected without a
            # multi-second stall.
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass

    def poll(self) -> List[dict]:
        """Drain all currently-queued incoming messages (non-blocking).
        Call once per frame from the main thread."""
        out = []
        while True:
            try:
                out.append(self.incoming.get_nowait())
            except queue.Empty:
                break
        return out
