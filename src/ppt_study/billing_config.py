from __future__ import annotations

import json
import os

from ppt_study.paths import packaged_billing_endpoint_file

# 用户端兜底地址。固定隧道请写到 billing_endpoint.json，不要依赖临时 trycloudflare 域名。
BUILTIN_BILLING_URL = "https://pdreader.fun"

LOCAL_OPERATOR_URL = "http://127.0.0.1:8765"

_LOCAL_DEFAULTS = frozenset(
    {
        "http://127.0.0.1:8765",
        "http://localhost:8765",
        "http://127.0.0.1:8765/",
        "http://localhost:8765/",
    }
)


def _norm(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _is_loopback(url: str) -> bool:
    raw = _norm(url)
    if raw in {_norm(item) for item in _LOCAL_DEFAULTS}:
        return True
    return raw.startswith("http://127.0.0.1:") or raw.startswith("http://localhost:")


def _read_packaged_endpoint() -> dict:
    path = packaged_billing_endpoint_file()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def packaged_billing_url() -> str:
    url = _norm(str(_read_packaged_endpoint().get("billing_url") or ""))
    if url.startswith("https://"):
        return url
    return ""


def packaged_directory_url() -> str:
    url = _norm(str(_read_packaged_endpoint().get("directory_url") or ""))
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return ""


def builtin_billing_url() -> str:
    return packaged_billing_url() or _norm(BUILTIN_BILLING_URL) or LOCAL_OPERATOR_URL


def resolve_billing_url(saved: str | None) -> str:
    env = _norm(os.environ.get("PPT_STUDY_BILLING_URL") or "")
    if env:
        return env
    builtin = builtin_billing_url()
    url = _norm(saved or "")
    if not url or url in _LOCAL_DEFAULTS:
        return builtin
    if "trycloudflare.com" in url.lower() and url != builtin:
        return builtin
    return url


def candidate_billing_urls(
    saved: str | None,
    learned: str | None = None,
    lan_url: str | None = None,
    packaged: str | None = None,
    discovered: str | None = None,
) -> list[str]:
    env = _norm(os.environ.get("PPT_STUDY_BILLING_URL") or "")
    primary = resolve_billing_url(saved)
    raw = _norm(saved or "")
    out: list[str] = []

    def add(url: str) -> None:
        item = _norm(url)
        if item and item not in out:
            out.append(item)

    if env:
        add(env)
        add(LOCAL_OPERATOR_URL)
        return out
    if _is_loopback(raw):
        add(raw)
    add(discovered or "")
    add(learned or "")
    add(packaged or packaged_billing_url())
    add(primary)
    add(lan_url or "")
    add(LOCAL_OPERATOR_URL)
    return out
