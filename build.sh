#!/usr/bin/env bash
# build.sh – erzeugt soundklaut-mac.zip zum Verschicken
# Voraussetzung: Python 3.9+ mit Tcl/Tk (z.B. von python.org oder Homebrew)
# Aufruf: bash build.sh
set -euo pipefail

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
PYTHON="${PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║         soundklaut · Distributionsbuild       ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# Python-Check
# ---------------------------------------------------------------------------
if ! command -v "$PYTHON" &>/dev/null; then
    echo "FEHLER: '$PYTHON' nicht gefunden."
    echo "Installiere Python 3.9+ von https://www.python.org/downloads/"
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python  : $("$PYTHON" --version)"

# Tkinter-Check (System-Python auf macOS hat kein Tk eingebaut)
if ! "$PYTHON" -c "import tkinter" 2>/dev/null; then
    echo ""
    echo "FEHLER: Dieses Python hat kein Tkinter."
    echo "Lösung: Installiere Python von https://www.python.org/downloads/"
    echo "        (Homebrew-Python: brew install python-tk@${PY_VERSION})"
    exit 1
fi
echo "Tkinter : OK"

# ---------------------------------------------------------------------------
# Abhängigkeiten installieren
# ---------------------------------------------------------------------------
echo ""
echo "▶  Abhängigkeiten installieren …"
"$PYTHON" -m pip install -q --upgrade pip
"$PYTHON" -m pip install -q \
    "yt-dlp>=2024.1.1" \
    "requests>=2.31.0" \
    "librespot>=0.0.1" \
    "sounddevice>=0.4.6" \
    "numpy>=1.24.0" \
    "mutagen>=1.47.0" \
    "rich>=13.7.0" \
    "pydub>=0.25.1" \
    "customtkinter>=5.2.0" \
    "spotdl>=4.2.0" \
    "imageio-ffmpeg>=0.4.9" \
    "pyinstaller>=6.0.0" \
    "pyinstaller-hooks-contrib>=2024.1"

echo "   Fertig."

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
echo ""
echo "▶  App bauen (das dauert 1–3 Minuten) …"
"$PYTHON" -m PyInstaller soundklaut.spec --clean --noconfirm 2>&1 | \
    grep -E '^[0-9]+ (WARNING|ERROR|CRITICAL)' | \
    grep -v 'PIL\|emscripten\|libc.so\|user32\|AppKit' | head -20 || true

if [ ! -d "dist/soundklaut.app" ]; then
    echo ""
    echo "FEHLER: Build fehlgeschlagen — dist/soundklaut.app nicht gefunden."
    exit 1
fi
echo "   Build OK."

# ---------------------------------------------------------------------------
# Ad-hoc-Signierung (kein Apple-Developer-Account nötig)
# Die App läuft danach nach einmaligem Rechtsklick → Öffnen.
# ---------------------------------------------------------------------------
echo ""
echo "▶  Ad-hoc-Signierung …"
codesign --deep --force --sign - "dist/soundklaut.app" 2>&1 || true
# Eigenen Quarantäne-Flag für lokale Tests entfernen
xattr -rd com.apple.quarantine "dist/soundklaut.app" 2>/dev/null || true
echo "   Fertig."

# ---------------------------------------------------------------------------
# ZIP erstellen
# ---------------------------------------------------------------------------
echo ""
echo "▶  soundklaut-mac.zip erstellen …"
rm -f soundklaut-mac.zip
ditto -c -k --keepParent "dist/soundklaut.app" soundklaut-mac.zip
ZIP_SIZE=$(du -sh soundklaut-mac.zip | cut -f1)
echo "   Fertig — soundklaut-mac.zip (${ZIP_SIZE})"

# ---------------------------------------------------------------------------
# Anleitung
# ---------------------------------------------------------------------------
echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║                  Fertig!                      ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "Datei zum Verschicken: soundklaut-mac.zip"
echo ""
echo "Anleitung für den Empfänger:"
echo "  1. soundklaut-mac.zip per Doppelklick entpacken"
echo "  2. soundklaut.app in den Programme-Ordner ziehen (optional)"
echo "  3. Beim ERSTEN Start:"
echo "       Rechtsklick auf soundklaut.app → Öffnen → Öffnen"
echo "       (nur einmal nötig — danach funktioniert normaler Doppelklick)"
echo ""
echo "Unterstützte URLs:"
echo "  • SoundCloud-Tracks und -Playlists"
echo "  • Spotify-Tracks, -Alben, -Playlists  (via YouTube Music)"
echo "  • Spotify-Podcasts / Episoden  (öffentliche Shows)"
echo ""
