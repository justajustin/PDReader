# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

spec_root = Path(SPECPATH)
datas = [(str(spec_root / "web"), "web")]
datas += collect_data_files("ppt_study", includes=["billing_endpoint.json"])
binaries = []
hiddenimports = collect_submodules("ppt_study")
hiddenimports += [
    "win32timezone",
    "win32com",
    "win32com.client",
    "pythoncom",
    "pywintypes",
]
for pkg in ("webview", "pptx", "clr_loader", "pythonnet", "pypdfium2"):
    try:
        collected_datas, collected_binaries, collected_hidden = collect_all(pkg)
    except Exception:
        continue
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hidden

a = Analysis(
    [str(spec_root / "src" / "ppt_study" / "app.py")],
    pathex=[str(spec_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6", "PySide2"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PDReader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(spec_root / "web" / "app-icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PDReader",
)
