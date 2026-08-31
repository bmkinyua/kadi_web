"""
KADI - LAN networking: wire protocol.

FRAMING: newline-delimited JSON. Each message is a single JSON object
serialized with json.dumps(..., separators=(',', ':')) (so it can never
contain a literal embedded newline) followed by a single b'\\n' byte.
Reader side buffers bytes as they arrive and splits on b'\\n'.

Chosen over length-prefixing because it's trivially debuggable (you can
literally `nc` into the port and read/paste JSON lines by hand) and the
payloads here are small (a single game-state snapshot, not bulk data),
so the minor overhead of scanning for '\\n' vs. reading a fixed-size
length header is irrelevant.

This module has NO game-rule knowledge and NO pygame dependency — it
only knows how to turn a dict into a length-safe wire frame and back.
"""
from __future__ import annotations
import json
import socket
from typing import Optional


class ProtocolError(Exception):
    pass


def encode_message(msg: dict) -> bytes:
    """dict -> one wire frame (JSON + trailing newline)."""
    if not isinstance(msg, dict):
        raise ProtocolError(f"Message must be a dict, got {type(msg)}")
    try:
        payload = json.dumps(msg, separators=(',', ':'))
    except (TypeError, ValueError) as e:
        raise ProtocolError(f"Message not JSON-serializable: {e}") from e
    if '\n' in payload:
        # Should be impossible (json.dumps never emits a raw newline
        # inside a string without escaping it) but guard explicitly
        # since our framing depends on this invariant.
        raise ProtocolError("Encoded message unexpectedly contains a newline")
    return payload.encode('utf-8') + b'\n'


class FrameBuffer:
    """Incremental newline-delimited JSON decoder.

    Feed it raw bytes as they arrive from a socket (which may split or
    coalesce messages arbitrarily); it yields complete decoded dicts as
    soon as a full line is available. Keeps any partial trailing data
    across calls.
    """

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list:
        """Append raw bytes, return a list of newly-completed messages
        (dicts), in order. Malformed lines raise ProtocolError — the
        caller decides whether that's fatal for the connection."""
        if not data:
            return []
        self._buf.extend(data)
        messages = []
        while True:
            idx = self._buf.find(b'\n')
            if idx == -1:
                break
            line = bytes(self._buf[:idx])
            del self._buf[:idx + 1]
            if not line.strip():
                continue  # tolerate stray blank lines
            try:
                messages.append(json.loads(line.decode('utf-8')))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ProtocolError(f"Malformed frame: {e}") from e
        return messages


def send_message(sock: socket.socket, msg: dict, lock=None):
    """Send one message on `sock`. Thread-safe if `lock` (a
    threading.Lock) is provided — callers with multiple threads writing
    to the same socket (e.g. the main loop and a keepalive) must pass
    one; a single dedicated writer thread per socket doesn't need it."""
    frame = encode_message(msg)
    if lock is not None:
        with lock:
            sock.sendall(frame)
    else:
        sock.sendall(frame)


def recv_messages_blocking(sock: socket.socket, buf: FrameBuffer, chunk_size: int = 4096):
    """Block on one recv() call, feed it to `buf`, return the list of
    complete messages it produced (may be empty). Returns None if the
    peer closed the connection (recv returned zero bytes) — callers
    should treat that as a disconnect, not an empty message list."""
    data = sock.recv(chunk_size)
    if not data:
        return None
    return buf.feed(data)
