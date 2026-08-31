#!/bin/sh
# Installs a Start-Menu / app-launcher entry for KADI when it's been
# extracted from the raw .tar.gz rather than run as an AppImage (the
# AppImage handles this itself — this script is ONLY for that manual/
# tar.gz fallback path). Run this from the directory KADI was
# extracted into (it locates the KADI binary and icon relative to its
# own location, so it works no matter where that directory lives).
#
# What it does:
#   1. Makes sure the KADI binary is executable (tar preserves the bit
#      from packaging, but this is a harmless safety net if it was
#      lost some other way, e.g. re-zipping instead of re-tarring).
#   2. Copies the icon into the standard per-user icon theme location.
#   3. Fills in this directory's real, absolute path in the .desktop
#      template and installs it into the standard per-user applications
#      directory, so KADI shows up in the desktop environment's normal
#      app launcher/Start Menu like any other installed application.
#
# Safe to re-run any time (e.g. after moving the KADI folder) — it
# always overwrites with the current location.

set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/KADI"
ICON_SRC="$HERE/kadi_icon.png"
TEMPLATE="$HERE/kadi-manual-install.desktop.template"

if [ ! -f "$BIN" ]; then
    echo "KADI binary not found at $BIN — run this script from the" >&2
    echo "same directory you extracted the KADI archive into." >&2
    exit 1
fi
chmod +x "$BIN"

ICON_DEST_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DEST_DIR"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$ICON_DEST_DIR/kadi_icon.png"
    ICON_PATH="$ICON_DEST_DIR/kadi_icon.png"
else
    # Fall back to a bare name (relies on it being found some other
    # way) rather than failing the whole install over a missing icon.
    ICON_PATH="kadi_icon"
fi

APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"

if [ ! -f "$TEMPLATE" ]; then
    echo ".desktop template not found at $TEMPLATE — this script must" >&2
    echo "stay alongside the file it was shipped with." >&2
    exit 1
fi

sed -e "s|__KADI_EXEC_PATH__|$BIN|" \
    -e "s|__KADI_ICON_PATH__|$ICON_PATH|" \
    "$TEMPLATE" > "$APPS_DIR/kadi.desktop"

echo "Installed KADI to your application launcher/Start Menu."
echo "  Binary: $BIN"
echo "  Desktop entry: $APPS_DIR/kadi.desktop"
echo "If your desktop environment doesn't pick it up immediately, log"
echo "out and back in (or run: update-desktop-database \"$APPS_DIR\")."
