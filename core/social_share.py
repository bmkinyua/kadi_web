"""
KADI - Social sharing (Profile Part C): saving a shareable PNG and
opening a pre-filled share-intent URL, for a choice of platforms, in
the person's own browser.

SAVE LOCATION: a shareable image is meant to be found and manually
attached to a post afterward, so this deliberately does NOT reuse
core.msomi_trainer.get_models_dir()'s location (KADI's own per-user
*application data* directory, alongside logs/ and settings.json) --
that's the right place for files the game itself reads back (trained
MSOMI models), but the wrong place for a human to go looking for a
picture to attach to a tweet. The OS-conventional Pictures folder is
what every other app that exports a shareable image uses, so a
"KADI Shares" subfolder there is what this saves into instead.

What IS reused from that same pattern (see core/game_logger.py's
_per_user_data_dir): resolve a real OS-conventional folder per
platform, and fall back to a location inside KADI's own app-data
directory (core.game_logger.base_dir()) if the conventional one can't
be created/written to for some reason -- same defensive shape, just
pointed at Pictures instead of AppData/Application Support/.local/share.

PLATFORM CHOICES -- why this list and not literally "every" social
network: the task is still deliberately scoped to NO OAuth / NO
developer account (same reasoning as the original ad-network
integration deferral), and this pass has no image hosting either (the
PNG only ever exists as a local file on the person's own machine). That
combination rules out any platform whose share dialog needs a URL it
can fetch OpenGraph data from -- Facebook's sharer.php and LinkedIn's
share-offsite endpoint both require a `u=` URL parameter and will show
a broken/empty preview without one; Instagram has no web share-intent
at all (posting is app-only, no URL scheme). What's left, and what's
below, are the share dialogs that work with plain pre-filled TEXT and
nothing else: X/Twitter, WhatsApp, Telegram, Reddit (a link post with
no `url=` still accepts a title), and plain email as a universal
fallback that always works. Every one of these opens in the person's
own already-logged-in browser tab/app -- KADI itself never touches
credentials for any of them.

DELIBERATELY LEFT OUT, and why (so this list doesn't quietly grow to
include a broken button next time someone reaches for "exhaustive"):
Facebook's sharer.php, LinkedIn's share-offsite, and Pinterest's
pin/create all REQUIRE a real, fetchable `u=`/media URL to scrape a
preview from -- pass them text with no URL and the dialog shows
broken/empty, not a working share. Skype and Tumblr's share endpoints
are undocumented/unstable enough (behavior has silently changed before)
that shipping them here risks a Share button that quietly does
nothing. SMS is a poor fit for a desktop app (sms: mostly only makes
sense on a phone). None of that is permanent -- if KADI ever hosts the
share image at a real URL, Facebook/LinkedIn/Pinterest become straight-
forward to add back in.
"""
from __future__ import annotations
import os
import sys
import webbrowser
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

SHARE_SUBDIR = "KADI Shares"

# ── Distribution link ───────────────────────────────────────────────
# The real, live itch.io page — replaces the earlier placeholder now
# that KADI is actually published there. This is the ONE place the
# link lives; every share-text builder below reads it from here.
GAME_URL = "https://bmkinyua.itch.io/"


# ── Share message text ──────────────────────────────────────────────
# Each share is triggered from a different moment in the game (a win,
# a badge unlock) and should say something specific to that moment
# rather than one generic caption reused everywhere — see the Part B
# "social share content" discussion. Centralized here (rather than
# inline at each scenes.py call site) so GAME_URL only has to be
# threaded through in one place.

def build_win_share_text(winner_name: str, mode_label: str) -> str:
    """Caption for the win-screen Share button. `mode_label` is the
    same human-readable mode name already shown on the win card itself
    (see GameplayScene._share_mode_label) — e.g. "Single-Player",
    "Hot-seat", "LAN Multiplayer", "Internet Multiplayer", "Elimination
    Mode" — folded in here so the message says what actually happened
    instead of a generic "I just won a game.\""""
    return f"{winner_name} just won a match of KADI ({mode_label})! {GAME_URL}"


def build_badge_share_text(badge_name: str) -> str:
    """Caption for a Profile-screen badge-card Share button."""
    return f"Just earned the \"{badge_name}\" badge in KADI! {GAME_URL}"


def _twitter_url(text: str) -> str:
    return f"https://twitter.com/intent/tweet?text={quote(text)}"


def _whatsapp_url(text: str) -> str:
    # web.whatsapp.com if there's no phone paired, wa.me redirects to
    # the installed app first when there is one -- either way this is
    # the standard no-account-needed WhatsApp share link.
    return f"https://wa.me/?text={quote(text)}"


def _telegram_url(text: str) -> str:
    # Telegram's share dialog wants url= for the link and text= for the
    # caption -- with no hosted image URL to give it, put everything in
    # text= alone (url= left empty) rather than passing a fake/blank url.
    return f"https://t.me/share/url?url=&text={quote(text)}"


def _reddit_url(text: str) -> str:
    # A link submission needs a title regardless of whether a url= is
    # given; Reddit shows it as a text post when url= is omitted.
    return f"https://www.reddit.com/submit?title={quote(text)}"


def _line_url(text: str) -> str:
    # LINE's own documented "LINE it!" button endpoint -- text= is a
    # first-class supported param, no url= required.
    return f"https://social-plugins.line.me/lineit/share?text={quote(text)}"


def _vk_url(text: str) -> str:
    # VK's share.php accepts a title-only share with no url=.
    return f"https://vk.com/share.php?title={quote(text)}"


def _email_url(text: str) -> str:
    return f"mailto:?subject={quote('My KADI game')}&body={quote(text)}"


# Ordered so the UI can lay these out left-to-right / top-to-bottom
# consistently. label is what a Share-platform button shows.
SHARE_PLATFORMS: List[Tuple[str, str, Callable[[str], str]]] = [
    ("twitter", "X / Twitter", _twitter_url),
    ("whatsapp", "WhatsApp", _whatsapp_url),
    ("telegram", "Telegram", _telegram_url),
    ("reddit", "Reddit", _reddit_url),
    ("line", "LINE", _line_url),
    ("vk", "VK", _vk_url),
    ("email", "Email", _email_url),
]
_PLATFORM_BY_KEY: Dict[str, Tuple[str, Callable[[str], str]]] = {
    key: (label, fn) for key, label, fn in SHARE_PLATFORMS
}

# A "Copy Text" action alongside the network buttons -- not a network
# at all, but the one option every WordPress-style share widget always
# has regardless of how many networks it lists, and the one thing that
# always works with zero risk of a dead/unsupported endpoint. Handled
# separately from SHARE_PLATFORMS (see copy_text_to_clipboard below)
# since it copies to the clipboard rather than opening a URL.
COPY_ACTION_KEY = "copy"
COPY_ACTION_LABEL = "Copy Text"

# What the UI actually iterates over to build buttons -- every network
# button plus the Copy Text action, in one list so callers (WinScreen,
# ProfileScene) don't need to special-case appending it themselves.
SHARE_UI_OPTIONS: List[Tuple[str, str]] = (
    [(key, label) for key, label, _fn in SHARE_PLATFORMS] +
    [(COPY_ACTION_KEY, COPY_ACTION_LABEL)]
)



def _pictures_dir_candidate() -> str:
    """Best-guess OS-conventional Pictures folder. Not guaranteed to
    exist yet -- get_share_dir() creates it (or falls back) below."""
    plat = sys.platform
    home = os.path.expanduser("~")

    if plat.startswith("win"):
        userprofile = os.environ.get("USERPROFILE") or home
        return os.path.join(userprofile, "Pictures")

    if plat == "darwin":
        return os.path.join(home, "Pictures")

    if plat.startswith("linux"):
        # Honors XDG_PICTURES_DIR if the desktop environment set it
        # (same "check the env var first" style as game_logger's own
        # XDG_DATA_HOME lookup); ~/Pictures otherwise, which is what
        # xdg-user-dirs defaults to anyway on most distros.
        xdg = os.environ.get("XDG_PICTURES_DIR")
        if xdg:
            return xdg
        return os.path.join(home, "Pictures")

    # Unknown/unsupported OS -- same "don't guess further" stance
    # game_logger._per_user_data_dir takes; the get_share_dir()
    # fallback below covers this case.
    return os.path.join(home, "Pictures")


def get_share_dir() -> str:
    """Directory shareable images are saved into -- OS Pictures folder
    / "KADI Shares", created if needed. Falls back to a "shares"
    folder inside KADI's own app-data directory (same one logs/ and
    profile.json live in) if the Pictures location can't be created or
    written to (e.g. a locked-down or unusual environment), so saving
    a share image never simply fails outright."""
    primary = os.path.join(_pictures_dir_candidate(), SHARE_SUBDIR)
    try:
        os.makedirs(primary, exist_ok=True)
        probe = os.path.join(primary, ".kadi_write_test")
        with open(probe, "w") as f:
            f.write("")
        os.remove(probe)
        return primary
    except OSError:
        from core.game_logger import base_dir
        fallback = os.path.join(base_dir(), "shares")
        os.makedirs(fallback, exist_ok=True)
        return fallback


def save_share_image(surface, filename: str) -> str:
    """Save a pygame.Surface as a PNG into get_share_dir(). Returns the
    full path written. `filename` should already end in .png (caller's
    responsibility -- kept simple since both call sites in scenes.py
    control their own filenames)."""
    import pygame
    path = os.path.join(get_share_dir(), filename)
    pygame.image.save(surface, path)
    return path


def reveal_in_file_manager(path: str) -> bool:
    """Best-effort: opens the OS's file manager with the saved share
    image's folder showing (and, on Windows/Mac, the file itself
    pre-selected/highlighted) — called right after a successful save,
    so the image is one drag away from being manually attached to
    whatever share window just opened, instead of something the person
    has to go hunting for themselves.

    This does NOT and cannot attach the file automatically to a post/
    tweet/email — no browser-based share dialog can reach into the
    local filesystem to do that from a plain URL, on ANY platform
    (X/Twitter intents, Reddit's submit page, mailto: links -- this is
    a real, universal security boundary of how the web works, not a
    KADI-specific gap or something a different technical approach here
    could route around). This function is the actual, honest ceiling
    of how much friction can be removed: get the file's location
    in front of the person immediately, rather than a fully-automatic
    attach that isn't technically possible from a desktop app with no
    OAuth/API integration for any of these platforms (see this module's
    own docstring for why that's deliberately out of scope).

    Returns True if a reveal command was launched (not a guarantee it
    visually succeeded — e.g. a headless/SSH session has no desktop to
    show a file manager in at all). Never raises; a failure here should
    never take down the save+share flow that already succeeded."""
    try:
        if sys.platform == 'win32':
            import subprocess
            subprocess.Popen(['explorer', '/select,', path])
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', '-R', path])
        else:
            # Linux: no universal "select this exact file" command
            # across desktop environments (GNOME/KDE/XFCE/etc. each
            # have their own, inconsistent tool for that) -- opening
            # the containing FOLDER via xdg-open is the one thing
            # that's broadly supported, even though it can't highlight
            # the specific file the way Explorer/Finder can above.
            import subprocess
            subprocess.Popen(['xdg-open', os.path.dirname(path)])
        return True
    except Exception:
        return False


def platform_label(platform_key: str) -> str:
    if platform_key == COPY_ACTION_KEY:
        return COPY_ACTION_LABEL
    entry = _PLATFORM_BY_KEY.get(platform_key)
    return entry[0] if entry else platform_key


def copy_text_to_clipboard(text: str) -> bool:
    """Best-effort copy via pygame's own SDL clipboard binding
    (pygame.scrap) -- no new dependency, same best-effort/never-raise
    shape as open_share_intent below. Requires a video mode to already
    be set, which is always true by the time any Share button exists
    (see rendering/widgets.py) -- pygame.scrap.init() fails cleanly
    otherwise rather than crashing."""
    try:
        import pygame
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode('utf-8'))
        return True
    except Exception:
        return False


def share_intent_url(platform_key: str, text: str) -> str:
    """A pre-filled compose/share URL for `text` on the given platform
    -- text only, per the task spec (none of these can attach an image
    over a plain URL). Falls back to the X/Twitter builder for an
    unrecognized key rather than raising, since this is only ever
    called from a button the UI itself generated from SHARE_PLATFORMS."""
    entry = _PLATFORM_BY_KEY.get(platform_key)
    fn = entry[1] if entry else _twitter_url
    return fn(text)


def open_share_intent(platform_key: str, text: str) -> bool:
    """Open the person's default browser to a pre-filled share-compose
    window for `text` on `platform_key`, via the stdlib webbrowser
    module (no new dependency). Returns webbrowser.open()'s own success
    flag -- best-effort only; a False/exception here should never be
    treated as fatal by the caller (see scenes.py's Share button
    handlers), since failing to open a browser tab doesn't undo the
    image that was already saved to disk."""
    try:
        return bool(webbrowser.open(share_intent_url(platform_key, text)))
    except Exception:
        return False

