"""
KADI - WebSocket transport: handshake + frame codec (RFC 6455).

Sibling to network/protocol.py, not a replacement for it. protocol.py's
newline-delimited-JSON framing stays exactly as-is for the existing
LAN/Internet-multiplayer TCP path (desktop client <-> server). This
module exists ONLY so a browser-based client (Discord/Telegram/WeChat/
web-pwa — none of which can open a raw TCP socket) can reach the same
server over a WebSocket instead, carrying the *same* JSON message dicts
core.game_manager.GameManager already speaks.

Deliberately stdlib-only (socket, hashlib, base64, struct) rather than
pulling in the third-party `websockets` package: the rest of this
server (network/protocol.py, server/connection.py) is stdlib-only and
thread-based (one blocking-recv thread per connection feeding a shared
queue.Queue), specifically so it runs on a bare box with just python3
installed. Adding `websockets` would mean also adopting asyncio for
this one transport and bridging it back into the existing thread/queue
model — two concurrency models in one process. A ~150-line hand-rolled
RFC 6455 implementation, reusing the SAME thread-per-connection shape
the TCP path already uses, is less total complexity than that bridge,
even though "just pip install websockets" looks simpler in isolation.

This module only implements what a JSON-message game client needs:
- server-side handshake (this server only ever accepts, never
  initiates, WS connections)
- text frames only (our payloads are always JSON, never binary)
- client->server frames are masked per spec; this module unmasks them
- server->client frames are NOT masked (also per spec — masking is
  client-to-server only)
- close/ping/pong opcodes recognized enough to close cleanly; no
  fragmented-frame reassembly (a single JSON message from any real
  client is always sent as one complete frame in practice, and nothing
  here sends a payload large enough to need fragmenting)
"""
from __future__ import annotations
import base64
import hashlib
import socket
import struct
from typing import Optional


class WSProtocolError(Exception):
    pass


class WSClosed(Exception):
    """Raised by recv_frame() when the peer sent a Close frame or the
    socket hit EOF -- callers treat this exactly like protocol.py's
    recv_messages_blocking() returning None (a clean disconnect)."""
    pass


_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # fixed magic string, RFC 6455 §1.3


def _read_http_headers(sock: socket.socket) -> bytes:
    """Read raw bytes up to and including the blank line that ends an
    HTTP request (the WS handshake is one HTTP GET). Small, bounded
    read -- a handshake is a few hundred bytes at most; refuses to
    read past 8KB to avoid a slow/hostile peer holding this open."""
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(1024)
        if not chunk:
            raise WSProtocolError("Connection closed during handshake")
        buf.extend(chunk)
        if len(buf) > 8192:
            raise WSProtocolError("Handshake headers too large")
    return bytes(buf)


def perform_server_handshake(sock: socket.socket) -> None:
    """Block until a valid WS upgrade request arrives on `sock`, then
    reply with the 101 Switching Protocols response. Raises
    WSProtocolError on anything that isn't a well-formed WS handshake
    -- caller should treat that as "not actually a WS client" and
    close the connection, same as a malformed frame on the TCP path.
    """
    raw = _read_http_headers(sock)
    try:
        head = raw.decode("iso-8859-1")
    except UnicodeDecodeError as e:
        raise WSProtocolError(f"Non-ASCII handshake: {e}") from e

    lines = head.split("\r\n")
    if not lines or not lines[0].upper().startswith("GET "):
        raise WSProtocolError("Not an HTTP GET request")

    headers = {}
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        headers[k.strip().lower()] = v.strip()

    if headers.get("upgrade", "").lower() != "websocket":
        raise WSProtocolError("Missing/invalid Upgrade header")
    key = headers.get("sec-websocket-key")
    if not key:
        raise WSProtocolError("Missing Sec-WebSocket-Key")

    accept = base64.b64encode(
        hashlib.sha1(key.encode("ascii") + _GUID).digest()
    ).decode("ascii")

    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    )
    sock.sendall(response.encode("ascii"))


# ── frame codec ──────────────────────────────────────────────────────────

_OP_CONT = 0x0
_OP_TEXT = 0x1
_OP_BINARY = 0x2
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def encode_text_frame(payload: str) -> bytes:
    """One complete, unmasked (server->client) text frame carrying
    `payload`. Mirrors protocol.py's encode_message() role, but WS
    framing carries its own length prefix -- no trailing newline
    needed or wanted here."""
    data = payload.encode("utf-8")
    header = bytearray([0x80 | _OP_TEXT])  # FIN=1, opcode=text
    n = len(data)
    if n < 126:
        header.append(n)
    elif n < 65536:
        header.append(126)
        header += struct.pack(">H", n)
    else:
        header.append(127)
        header += struct.pack(">Q", n)
    return bytes(header) + data


def _encode_close_frame(code: int = 1000) -> bytes:
    payload = struct.pack(">H", code)
    return bytes([0x80 | _OP_CLOSE, len(payload)]) + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise WSClosed("Peer closed mid-frame")
        buf.extend(chunk)
    return bytes(buf)


def recv_frame(sock: socket.socket) -> Optional[str]:
    """Block for exactly one complete WS frame from `sock`, return its
    decoded text payload. Returns None for a PING (caller should reply
    with PONG and call again) or PONG (caller just calls again) --
    only a text frame or a Close raises/returns meaningfully.
    Raises WSClosed on a Close frame or EOF, WSProtocolError on
    anything malformed (binary frame, bad opcode, etc.) -- caller
    treats both exactly like protocol.py's ProtocolError/None: fatal
    for this connection.
    """
    first2 = _recv_exact(sock, 2)
    b0, b1 = first2[0], first2[1]
    fin = bool(b0 & 0x80)
    opcode = b0 & 0x0F
    masked = bool(b1 & 0x80)
    length = b1 & 0x7F

    if not masked:
        # Per RFC 6455 §5.1, a server MUST close the connection if a
        # client sends an unmasked frame -- this is a protocol
        # violation, not a "maybe some other client type" case.
        raise WSProtocolError("Client frame not masked")

    if length == 126:
        length = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(sock, 8))[0]

    mask_key = _recv_exact(sock, 4)
    payload = bytearray(_recv_exact(sock, length))
    for i in range(len(payload)):
        payload[i] ^= mask_key[i % 4]

    if opcode == _OP_CLOSE:
        raise WSClosed("Peer sent Close frame")
    if opcode == _OP_PING:
        # Caller (the recv loop) owns the socket write lock, so it
        # replies with PONG itself -- this function only decodes.
        return None
    if opcode == _OP_PONG:
        return None
    if opcode != _OP_TEXT:
        raise WSProtocolError(f"Unsupported opcode: {opcode}")
    if not fin:
        raise WSProtocolError("Fragmented frames not supported")

    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as e:
        raise WSProtocolError(f"Malformed UTF-8 text frame: {e}") from e


def close_gracefully(sock: socket.socket) -> None:
    try:
        sock.sendall(_encode_close_frame())
    except OSError:
        pass
