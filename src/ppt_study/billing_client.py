from __future__ import annotations

import hashlib
import json
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ppt_study.ai_client import ai_http_timeout
from ppt_study.billing_config import (
    BUILTIN_BILLING_URL,
    LOCAL_OPERATOR_URL,
    candidate_billing_urls,
    packaged_directory_url,
    resolve_billing_url,
)
from ppt_study.models import AppSettings
from ppt_study.paths import app_data_dir, billing_endpoint_file
from ppt_study.settings import load_settings

DEFAULT_BILLING_URL = BUILTIN_BILLING_URL
_directory_checked = False
_directory_cache = ""


def reset_directory_cache() -> None:
    global _directory_checked, _directory_cache
    _directory_checked = False
    _directory_cache = ""


def load_billing_endpoint() -> dict:
    path = billing_endpoint_file()
    if not path.is_file():
        return {"billing_url": "", "lan_url": "", "directory_url": ""}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"billing_url": "", "lan_url": "", "directory_url": ""}
    if not isinstance(raw, dict):
        return {"billing_url": "", "lan_url": "", "directory_url": ""}
    return {
        "billing_url": str(raw.get("billing_url") or "").strip().rstrip("/"),
        "lan_url": str(raw.get("lan_url") or "").strip().rstrip("/"),
        "directory_url": str(raw.get("directory_url") or "").strip().rstrip("/"),
    }


def remember_billing_endpoint(
    billing_url: str = "",
    lan_url: str = "",
    directory_url: str = "",
) -> None:
    data = load_billing_endpoint()
    public = (billing_url or "").strip().rstrip("/")
    lan = (lan_url or "").strip().rstrip("/")
    directory = (directory_url or "").strip().rstrip("/")
    if public.startswith("https://") or public.startswith("http://"):
        if "127.0.0.1" not in public and "localhost" not in public:
            data["billing_url"] = public
        elif public.startswith("http://127.0.0.1:") or public.startswith("http://localhost:"):
            data["lan_url"] = public
    if lan.startswith("http://") or lan.startswith("https://"):
        data["lan_url"] = lan
    if directory.startswith("http://") or directory.startswith("https://"):
        data["directory_url"] = directory
    path = billing_endpoint_file()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _directory_lookup() -> str:
    global _directory_checked, _directory_cache
    if _directory_checked:
        return _directory_cache
    _directory_checked = True
    ep = load_billing_endpoint()
    url = (
        (os.environ.get("PPT_STUDY_DIRECTORY_URL") or "").strip().rstrip("/")
        or ep.get("directory_url")
        or packaged_directory_url()
    )
    if not url:
        _directory_cache = ""
        return ""
    target = url
    if not target.endswith("/v1/meta"):
        target = target.rstrip("/") + "/v1/meta"
    try:
        resp = httpx.get(target, timeout=6.0, follow_redirects=True, trust_env=False)
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        _directory_cache = ""
        return ""
    if not isinstance(data, dict):
        _directory_cache = ""
        return ""
    found = str(data.get("billing_url") or data.get("public_url") or "").strip().rstrip("/")
    if found.startswith("http://") or found.startswith("https://"):
        _directory_cache = found
        remember_billing_endpoint(found)
        return found
    _directory_cache = ""
    return ""


def device_file() -> Path:
    return app_data_dir() / "device.json"


def device_id() -> str:
    path = device_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ident = str((data or {}).get("id") or "").strip()
            if ident:
                return ident
        except (OSError, ValueError):
            pass
    ident = uuid.uuid4().hex
    path.write_text(json.dumps({"id": ident}, ensure_ascii=False), encoding="utf-8")
    return ident


def billing_url(settings: AppSettings | None = None) -> str:
    s = settings or load_settings()
    return resolve_billing_url(s.billing_url)


def _local_operator_up(timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=timeout):
            return True
    except OSError:
        return False


def _bases(settings: AppSettings | None = None) -> list[str]:
    if os.environ.get("PPT_STUDY_DISABLE_PLATFORM", "").strip().lower() in {"1", "true", "yes"}:
        return []
    s = settings or load_settings()
    ep = load_billing_endpoint()
    urls = candidate_billing_urls(
        s.billing_url,
        learned=ep.get("billing_url"),
        lan_url=ep.get("lan_url"),
        discovered=_directory_lookup(),
    )
    local = LOCAL_OPERATOR_URL.rstrip("/")
    if _local_operator_up() and local in urls:
        return [local] + [item for item in urls if item != local]
    return urls


def _learn_payload(data: dict, used_base: str = "") -> dict:
    if used_base:
        remember_billing_endpoint(used_base)
    if isinstance(data, dict):
        remember_billing_endpoint(
            str(data.get("public_url") or data.get("billing_url") or ""),
            str(data.get("lan_url") or ""),
        )
    return data


def _decode(resp: httpx.Response) -> dict | None:
    try:
        data = resp.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if resp.status_code >= 400 and "error" not in data:
        data["ok"] = False
        data["error"] = data.get("error") or f"服务器错误 {resp.status_code}"
    return data


def _request_kwargs(timeout: float | httpx.Timeout) -> dict:
    return {"timeout": timeout, "follow_redirects": True, "trust_env": False}


def _post(path: str, payload: dict, timeout: float = 12.0) -> dict:
    timed_out = False
    invalid = False
    for base in _bases():
        url = base + path
        try:
            resp = httpx.post(url, json=payload, **_request_kwargs(timeout))
            data = _decode(resp)
            if data is None:
                invalid = True
                continue
            return _learn_payload(data, base)
        except httpx.TimeoutException:
            timed_out = True
        except httpx.RequestError:
            continue
    if timed_out:
        return {"ok": False, "error": "积分服务器超时"}
    if invalid:
        return {"ok": False, "error": "积分服务器响应无效"}
    return {"ok": False, "error": "连不上积分服务器，请检查地址或先启动后台"}


def _get(path: str, timeout: float = 12.0) -> dict:
    timed_out = False
    invalid = False
    for base in _bases():
        url = base + path
        try:
            resp = httpx.get(url, **_request_kwargs(timeout))
            data = _decode(resp)
            if data is None:
                invalid = True
                continue
            return _learn_payload(data, base)
        except httpx.TimeoutException:
            timed_out = True
        except httpx.RequestError:
            continue
    if timed_out:
        return {"ok": False, "error": "积分服务器超时"}
    if invalid:
        return {"ok": False, "error": "积分服务器响应无效"}
    return {"ok": False, "error": "连不上积分服务器，请检查地址或先启动后台"}


def fetch_wallet() -> dict:
    ident = device_id()
    out = _get(f"/v1/wallet?device_id={ident}")
    out.setdefault("platform_model", "gpt-5.6-sol")
    return out


def hello_remote() -> dict:
    ident = device_id()
    out = _post("/v1/hello", {"device_id": ident})
    if out.get("ok"):
        return out
    return _get(f"/v1/hello?device_id={ident}")


def redeem_remote(code: str) -> dict:
    return _post("/v1/redeem", {"device_id": device_id(), "code": code})


def create_invite_remote() -> dict:
    return _post("/v1/invite/create", {"device_id": device_id()})


def redeem_invite_remote(code: str) -> dict:
    return _post("/v1/invite/redeem", {"device_id": device_id(), "code": code})


def create_wechat_pay_remote(amount) -> dict:
    return _post("/v1/pay/wechat", {"device_id": device_id(), "amount": amount})


def query_wechat_pay_remote(order_id: str) -> dict:
    ident = quote(device_id(), safe="")
    token = quote(str(order_id or ""), safe="")
    return _get(f"/v1/pay/wechat?device_id={ident}&order_id={token}")


def settle_remote(usage: dict | None, feature: str = "qa") -> dict:
    return _post(
        "/v1/settle",
        {"device_id": device_id(), "usage": usage or {}, "feature": feature},
    )


def _ai_payload(messages: list[dict], feature: str, web_search: bool) -> dict:
    feat = feature if feature in ("qa", "script") else "qa"
    payload = {
        "device_id": device_id(),
        "messages": messages,
        "feature": feat,
    }
    if web_search:
        payload["web_search"] = True
    return payload


def complete_remote(messages: list[dict], feature: str = "qa", web_search: bool = False) -> dict:
    out = _post(
        "/v1/ai",
        _ai_payload(messages, feature, web_search),
        timeout=ai_http_timeout(web_search),
    )
    err = str(out.get("error") or "")
    if not out.get("ok") and (err == "不存在" or "404" in err):
        out["error"] = "积分后台版本过旧，请重启本机积分后台后再试"
    return out


def complete_remote_stream(
    messages: list[dict],
    feature: str = "qa",
    web_search: bool = False,
    on_delta=None,
) -> dict:
    payload = _ai_payload(messages, feature, web_search)
    timeout = ai_http_timeout(web_search)
    timed_out = False
    for base in _bases():
        url = base + "/v1/ai/stream"
        try:
            with httpx.stream("POST", url, json=payload, **_request_kwargs(timeout)) as resp:
                if resp.status_code == 404:
                    break
                ctype = str(resp.headers.get("content-type") or "")
                if "event-stream" not in ctype:
                    raw = resp.read()
                    try:
                        data = json.loads(raw.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                        data = None
                    if not isinstance(data, dict):
                        continue
                    if resp.status_code >= 400 and "error" not in data:
                        data = {"ok": False, "error": data.get("error") or f"服务器错误 {resp.status_code}"}
                    if str(data.get("error") or "") == "不存在":
                        break
                    if data.get("ok") and on_delta and data.get("text"):
                        on_delta(str(data.get("text")))
                    return _learn_payload(data, base)
                last = {"ok": False, "error": "模型没有返回内容"}
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(data, dict):
                        continue
                    if data.get("text") and on_delta:
                        on_delta(str(data.get("text")))
                    if data.get("done") or data.get("error"):
                        last = data
                return _learn_payload(last, base)
        except httpx.TimeoutException:
            timed_out = True
        except httpx.RequestError:
            continue
    if timed_out:
        fallback = {"ok": False, "error": "积分服务器超时"}
    else:
        fallback = complete_remote(messages, feature, web_search)
    if fallback.get("ok") and on_delta and fallback.get("text"):
        on_delta(str(fallback.get("text")))
    return fallback


def send_telemetry(events: list[dict]) -> dict:
    return _post("/v1/telemetry", {"device_id": device_id(), "events": events})


def fetch_update_info() -> dict:
    return _get("/v1/update")


def download_update_file(dest: Path, expected_sha256: str = "") -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    timed_out = False
    wrote = False
    for base in _bases():
        url = base + "/v1/update/download"
        try:
            with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as resp:
                if resp.status_code >= 400:
                    return {"ok": False, "error": f"下载失败 {resp.status_code}"}
                with dest.open("wb") as handle:
                    for chunk in resp.iter_bytes():
                        handle.write(chunk)
            wrote = True
            remember_billing_endpoint(base)
            break
        except httpx.TimeoutException:
            timed_out = True
        except httpx.RequestError:
            continue
    if not wrote:
        if timed_out:
            return {"ok": False, "error": "下载超时"}
        return {"ok": False, "error": "连不上积分服务器，无法下载更新"}
    if not dest.is_file() or dest.stat().st_size <= 0:
        return {"ok": False, "error": "下载的安装包无效"}
    if expected_sha256:
        digest = hashlib.sha256()
        with dest.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            dest.unlink(missing_ok=True)
            return {"ok": False, "error": "安装包校验失败，请重试"}
    return {"ok": True, "path": str(dest), "error": ""}
