from __future__ import annotations

import json

from ppt_study.models import AppSettings, AuthMode, ThemeMode
from ppt_study.paths import settings_file

DEFAULT_BASE_URL = ""
DEFAULT_MODEL = ""
DEFAULT_BILLING_URL = "http://127.0.0.1:8765"
THEMES: tuple[ThemeMode, ...] = ("light", "dark", "system", "eye")


def _theme(value: object) -> ThemeMode:
    text = str(value or "").strip()
    if text in THEMES:
        return text  # type: ignore[return-value]
    return "light"


def load_settings() -> AppSettings:
    path = settings_file()
    if not path.exists():
        return AppSettings(
            base_url=DEFAULT_BASE_URL,
            api_key="",
            model=DEFAULT_MODEL,
            auth_mode="bearer",
            theme="light",
            billing_url=DEFAULT_BILLING_URL,
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    mode: AuthMode = data.get("auth_mode", "bearer")
    if mode not in ("bearer", "raw"):
        mode = "bearer"
    return AppSettings(
        base_url=str(data.get("base_url") or "").strip(),
        api_key=str(data.get("api_key") or ""),
        model=str(data.get("model") or "").strip(),
        auth_mode=mode,
        theme=_theme(data.get("theme")),
        billing_url=str(data.get("billing_url") or DEFAULT_BILLING_URL).strip()
        or DEFAULT_BILLING_URL,
    )


def save_settings(settings: AppSettings) -> None:
    path = settings_file()
    payload = {
        "base_url": settings.base_url,
        "api_key": settings.api_key,
        "model": settings.model,
        "auth_mode": settings.auth_mode,
        "theme": _theme(settings.theme),
        "billing_url": (settings.billing_url or DEFAULT_BILLING_URL).strip()
        or DEFAULT_BILLING_URL,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
