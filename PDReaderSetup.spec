# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

spec_root = Path(SPECPATH)
payload = spec_root / "build" / "installer-payload"
if not payload.is_dir():
    raise SystemExit(f"Missing installer payload: {payload}")

a = Analysis(
    [str(spec_root / "src" / "ppt_study" / "windows_installer.py")],
    pathex=[str(spec_root / "src")],
    binaries=[],
    datas=[(str(payload), "payload")],
    hiddenimports=["tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "PySide2", "webview", "pptx"],
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
    name="PDReaderSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(spec_root / "web" / "app-icon.ico"),
)
