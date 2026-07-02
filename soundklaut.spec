# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for soundklaut.app
# Build with:  python -m PyInstaller soundklaut.spec --clean --noconfirm

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Resolve imageio-ffmpeg binary path at spec-eval time so we can include it
# as an executable in the bundle (PyInstaller needs the source path).
import imageio_ffmpeg as _iio_ffmpeg
_ffmpeg_src = _iio_ffmpeg.get_ffmpeg_exe()

# yt-dlp embeds all extractors; collect them so nothing is missing at runtime.
ytdlp_hidden = collect_submodules('yt_dlp.extractor')

# spotdl submodules (search, download, types, utils, …)
spotdl_hidden = collect_submodules('spotdl')

a = Analysis(
    ['soundklaut_gui.py'],
    pathex=['.'],
    # Include the static ffmpeg binary from imageio-ffmpeg at the bundle root.
    # _ffmpeg_exe() checks for sys._MEIPASS/ffmpeg when frozen.
    binaries=[(_ffmpeg_src, '.')],
    datas=[
        # customtkinter needs its theme JSON and font files.
        *collect_data_files('customtkinter'),
        # yt-dlp ships some supporting data (e.g. extractor helper files).
        *collect_data_files('yt_dlp'),
        # spotdl ships locale / config data.
        *collect_data_files('spotdl'),
    ],
    hiddenimports=[
        *ytdlp_hidden,
        *spotdl_hidden,
        # mutagen tag formats used at runtime
        'mutagen',
        'mutagen.id3',
        'mutagen.mp3',
        'mutagen._util',
        # pydub
        'pydub',
        'pydub.silence',
        'pydub.effects',
        # imageio-ffmpeg
        'imageio_ffmpeg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='soundklaut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,      # No terminal window on macOS
    windowed=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='soundklaut',
)

app = BUNDLE(
    coll,
    name='soundklaut.app',
    bundle_identifier='com.soundklaut.app',
    version='1.0.0',
    info_plist={
        'CFBundleName': 'soundklaut',
        'CFBundleDisplayName': 'soundklaut',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        # Allow both light and dark mode
        'NSRequiresAquaSystemAppearance': False,
        # Not a background-only app
        'LSUIElement': False,
    },
)
