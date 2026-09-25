from __future__ import annotations

import json
import sys
from pathlib import Path

from ppt_study.paths import APP_VERSION, app_data_dir, parse_version

VERSION_STAMP_MARK = b"###PDREADER_VERSION###"


def installed_version_file() -> Path:
    return app_data_dir() / "installed_version.json"


def install_dir_version_file(install_dir: Path) -> Path:
    return Path(install_dir) / "app_version.json"


def sidecar_version_file(installer: Path) -> Path:
    return Path(str(installer) + ".version")


def stamp_installer_version(path: Path, version: str) -> None:
    ver = str(version or "").strip()
    if parse_version(ver) is None:
        raise ValueError("版本号无效")
    target = Path(path)
    raw = target.read_bytes()
    idx = raw.find(VERSION_STAMP_MARK)
    if idx != -1:
        raw = raw[:idx].rstrip(b"\r\n")
    target.write_bytes(raw + b"\n" + VERSION_STAMP_MARK + ver.encode("ascii") + b"\n")
    sidecar_version_file(target).write_text(ver + "\n", encoding="utf-8")


def read_stamped_installer_version(path: Path) -> str:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    idx = raw.rfind(VERSION_STAMP_MARK)
    if idx < 0:
        return ""
    tail = raw[idx + len(VERSION_STAMP_MARK) :].decode("ascii", "ignore").strip()
    ver = tail.splitlines()[0].strip() if tail else ""
    return ver if parse_version(ver) else ""


def version_from_argv(argv: list[str] | None) -> str:
    for item in argv or []:
        text = str(item or "")
        prefix = ""
        if text.startswith("/APPVERSION="):
            prefix = "/APPVERSION="
        elif text.startswith("--app-version="):
            prefix = "--app-version="
        if not prefix:
            continue
        ver = text[len(prefix) :].strip()
        if parse_version(ver):
            return ver
    return ""


def resolve_setup_version(argv: list[str] | None = None, installer_path: Path | None = None) -> str:
    items = list(sys.argv[1:] if argv is None else argv)
    ver = version_from_argv(items)
    if ver:
        return ver
    path = Path(installer_path or (sys.executable if getattr(sys, "frozen", False) else sys.argv[0]))
    sidecar = sidecar_version_file(path)
    if sidecar.is_file():
        try:
            text = sidecar.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except OSError:
            text = ""
        if parse_version(text):
            return text
    stamped = read_stamped_installer_version(path)
    if stamped:
        return stamped
    return APP_VERSION


def save_installed_version(version: str, install_dir: Path | None = None) -> str:
    ver = str(version or "").strip()
    if parse_version(ver) is None:
        ver = APP_VERSION
    payload = json.dumps({"version": ver}, ensure_ascii=False)
    path = installed_version_file()
    path.write_text(payload, encoding="utf-8")
    if install_dir is not None:
        dest = install_dir_version_file(install_dir)
        try:
            dest.write_text(payload, encoding="utf-8")
        except OSError:
            pass
    return ver


def _read_version_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return ""
    if isinstance(data, dict):
        ver = str(data.get("version") or "").strip()
    else:
        ver = str(data or "").strip()
    return ver if parse_version(ver) else ""


def read_installed_version() -> str:
    ver = _read_version_file(installed_version_file())
    if ver:
        return ver
    if getattr(sys, "frozen", False):
        return _read_version_file(Path(sys.executable).with_name("app_version.json"))
    return ""


def current_app_version() -> str:
    installed = read_installed_version()
    if installed:
        return installed
    return APP_VERSION
