from __future__ import annotations

import os
from pathlib import Path

APP_DISPLAY_NAME = "PDReader"
APP_DIR_NAME = "PPTStudyCompanion"
APP_VERSION = "0.2.14"


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def cache_dir() -> Path:
    path = app_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_dir() -> Path:
    path = app_data_dir() / "operator"
    path.mkdir(parents=True, exist_ok=True)
    return path


def operator_store_file() -> Path:
    return operator_dir() / "store.json"


def operator_public_url_file() -> Path:
    return operator_dir() / "public_url.txt"


def operator_tunnel_file() -> Path:
    return operator_dir() / "tunnel.json"


def billing_endpoint_file() -> Path:
    return app_data_dir() / "billing_endpoint.json"


def packaged_billing_endpoint_file() -> Path:
    return Path(__file__).with_name("billing_endpoint.json")


def read_operator_public_url() -> str:
    path = operator_public_url_file()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_version(text: str) -> tuple[int, int, int] | None:
    parts = str(text or "").strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def version_newer(remote: str, local: str) -> bool:
    left = parse_version(remote)
    right = parse_version(local)
    if left is None or right is None:
        return False
    return left > right


def suggest_next_version(current: str) -> str:
    parsed = parse_version(current)
    if parsed is None:
        return "0.0.1"
    major, minor, patch = parsed
    return f"{major}.{minor}.{patch + 1}"
