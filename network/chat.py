"""
KADI - shared chat-message sanitization for LAN and Internet Multiplayer.

Deliberately tiny and dependency-free (no pygame) so both
network/host_game.py (LAN) and server/kadi_server.py (Internet, which
runs headless with no pygame at all) can import it unmodified.
"""
from __future__ import annotations

MAX_CHAT_LEN = 240


def sanitize_chat_text(raw) -> str:
    """Turns whatever a client sent as chat 'text' into a safe string
    to broadcast: coerces to str, strips control characters (a client
    could otherwise smuggle e.g. a literal newline — impossible to
    actually break the newline-delimited wire framing since
    network/protocol.py's encode_message re-serializes through
    json.dumps regardless, but still worth stripping so it can't mess
    with how the message renders in anyone's chat log), trims
    surrounding whitespace, and caps the length. Emoji and other
    printable Unicode (this project's text-input fields already accept
    arbitrary Unicode via pygame's event.unicode — see
    scenes._draw_text_field's callers) pass through untouched; only
    C0/C1 control characters are removed."""
    text = str(raw) if raw is not None else ""
    cleaned = "".join(ch for ch in text if ch == ' ' or (ch.isprintable() and ch not in "\r\n\t"))
    cleaned = cleaned.strip()
    return cleaned[:MAX_CHAT_LEN]
