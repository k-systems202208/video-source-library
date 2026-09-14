from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
TOOLS = ROOT / "tools"

assets = [
    "video-library.html",
    "manifest.webmanifest",
    "service-worker.js",
    "offline.html",
    "icon.svg",
]
datas = [(str(SRC / name), ".") for name in assets]
ffprobe = TOOLS / "ffprobe.exe"
if ffprobe.is_file():
    datas.append((str(ffprobe), "tools"))

a = Analysis(
    [str(SRC / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "tkinter.ttk", "sqlite3"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "build" / "runtime_no_console.py")],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoLibrary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="VideoLibrary",
)
