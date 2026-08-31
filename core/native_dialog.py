"""
KADI - native OS file dialog wrapper.

Used by Chuo's log-file picker and the MSOMI "attach a model" picker to
let the person browse anywhere on their computer, not just the game's
own logs/ and msomi_models/ folders — needed for e.g. sharing log files
or trained models between people.

Wraps tkinter's filedialog (part of the Python standard library on a
normal install) behind a try/except so a machine without a working
Tk/tkinter installation gets a clear "not available" result instead of
a crash — this is a convenience on top of the built-in folder pickers,
never a requirement to use Chuo or MSOMI at all.
"""
from __future__ import annotations
from typing import List, Optional, Tuple


def _hidden_root():
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    return root


def ask_open_file(title: str, filetypes: List[Tuple[str, str]]) -> Optional[str]:
    """Native "open file" dialog for a single file. Returns the chosen
    absolute path, or None if cancelled or unavailable."""
    try:
        from tkinter import filedialog
        root = _hidden_root()
        try:
            path = filedialog.askopenfilename(title=title, filetypes=filetypes)
        finally:
            root.destroy()
        return path or None
    except Exception:
        return None


def ask_open_files_multi(title: str, filetypes: List[Tuple[str, str]]) -> List[str]:
    """Native "open file" dialog allowing multiple selection — no limit
    on how many, matching Chuo's own log-picker spec. Returns a list of
    absolute paths (empty if cancelled or unavailable)."""
    try:
        from tkinter import filedialog
        root = _hidden_root()
        try:
            paths = filedialog.askopenfilenames(title=title, filetypes=filetypes)
        finally:
            root.destroy()
        return list(paths)
    except Exception:
        return []


def is_available() -> bool:
    """Whether a native file dialog can actually be shown on this
    machine — checked once up front so the UI can show a clear message
    ("browsing isn't available here, but you can still use the
    built-in folder") instead of a silent no-op on click."""
    try:
        import tkinter  # noqa: F401
        return True
    except Exception:
        return False
