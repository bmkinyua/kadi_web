# -*- mode: python ; coding: utf-8 -*-

import sys

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    # Bundled READ-ONLY resources — both loaded at runtime via
    # constants.resource_base_dir(), which resolves to PyInstaller's
    # sys._MEIPASS once frozen (see that function's own docstring for
    # the from-source vs frozen story). Format is (source, dest-in-bundle)
    # — dest matches the relative path resource_base_dir()-based code
    # actually joins onto, so this MUST stay named exactly 'assets' and
    # 'msomi_models' to line up with every asset_loader.py / scenes.py /
    # msomi_trainer.py call site that builds a path this way.
    datas=[
        ('assets', 'assets'),
        # The one shipped reference MSOMI model (see packaging decision:
        # ship exactly one, seeded into a fresh player's own per-user
        # models directory on first launch — see
        # core.msomi_trainer.seed_bundled_reference_model_if_empty).
        # NOT the same directory the game actually trains/saves into —
        # that one lives in the per-user app-data dir and is never part
        # of the bundle at all.
        ('msomi_models', 'msomi_models'),
    ],
    hiddenimports=['tkinter', 'tkinter.filedialog'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='KADI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows/Mac app icon (was unset — this is what fixed the default
    # Python icon showing everywhere: taskbar, pinned icon, File Explorer,
    # before the game is even running). PyInstaller wants .ico on Windows
    # and .icns on Mac from the SAME 'icon=' field — it picks the right
    # one per-platform automatically. This is a separate icon from the
    # in-app pygame.display.set_icon() call in main.py, which only
    # affects the running window's title bar/Alt-Tab, not the .exe itself.
    icon='assets/icon/kadi_icon.ico',
)

# macOS-only: wraps the raw executable above into a proper double-
# clickable KADI.app bundle (with its own Info.plist and Finder icon)
# instead of shipping a bare Unix binary. BUNDLE() is a no-op / not
# even importable-as-meaningful on Windows or Linux, so this is
# guarded to only run when actually building on a Mac (see
# .github/workflows/build.yml, which builds this same .spec file on
# three different hosted OSes — this is what makes the Mac run of that
# workflow come out as dist/KADI.app while Windows/Linux stay dist/
# KADI.exe and dist/KADI respectively).
#
# bundle_identifier is a placeholder (reverse-DNS style, matches no
# real registered domain) — fine for local/CI builds and itch.io
# distribution, but if this ever goes through Apple's notarization
# process, that's usually done under a real identifier tied to the
# Apple Developer account doing the signing; worth revisiting together
# at that point rather than guessing now.
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='KADI.app',
        icon='assets/icon/kadi_icon.icns',
        bundle_identifier='com.kadigame.kadi',
    )
