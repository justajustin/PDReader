from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue

from ppt_study.ai_client import AIClient, AIError
from ppt_study.billing_client import (
    complete_remote,
    complete_remote_stream,
    create_invite_remote,
    create_wechat_pay_remote,
    download_update_file,
    fetch_update_info,
    fetch_wallet,
    hello_remote,
    query_wechat_pay_remote,
    redeem_invite_remote,
    redeem_remote,
    send_telemetry,
)
from ppt_study.billing_config import resolve_billing_url
from ppt_study.context import build_qa_messages, build_script_messages
from ppt_study.image_util import (
    data_url_to_api_data_url,
    file_to_display_data_url,
    image_to_api_data_url,
)
from ppt_study.ingest import IngestError, ingest_presentation
from ppt_study.models import AppSettings, DeckRecord
from ppt_study.app_version import current_app_version
from ppt_study.paths import version_newer
from ppt_study.settings import THEMES, load_settings, save_settings
from ppt_study.extract_media import extract_slide_links, publish_slide_media
from ppt_study.store import (
    add_qa_favorite,
    deck_cache_key,
    load_favorites,
    save_script,
    search_qa_favorites,
)
from ppt_study.store import remove_qa_favorite as delete_saved_qa
from ppt_study.store import toggle_favorite as persist_favorite

DECK_SUFFIXES = {".ppt", ".pptx", ".pdf"}
PPT_SUFFIXES = DECK_SUFFIXES
OPEN_FILE_TYPES = ("课件 (*.ppt;*.pptx;*.pdf)",)
SCRIPT_MODEL_RETRIES = 1
SCRIPT_RETRY_DELAY = 1.5
SCRIPT_OVERLOAD_RETRIES = 2
SCRIPT_OVERLOAD_DELAY = 4.0
SCRIPT_BATCH_WORKERS = 2


def _win_quote(value: str) -> str:
    text = str(value or "")
    if not text or any(ch in text for ch in ' \t&|^'):
        return '"' + text.replace('"', '""') + '"'
    return text


def current_install_dir() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return ""


def update_setup_command(setup: str, version: str = "") -> list[str]:
    args = [str(setup)]
    if os.name != "nt":
        return args
    if version:
        args.append("/APPVERSION=" + str(version))
    args.extend(["/FORCECLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS"])
    install_dir = current_install_dir()
    if install_dir:
        args.extend(["--dir", install_dir, "--silent"])
    inner = " ".join(_win_quote(item) for item in args)
    return ["cmd.exe", "/c", "ping 127.0.0.1 -n 4 >nul & " + inner]


def fatal_script_batch_error(error: str) -> bool:
    text = str(error or "")
    return any(
        token in text
        for token in ("积分不足", "未授权", "请求过大", "尚未打开", "平台模型尚未配置")
    )


def is_overload_script_error(error: str) -> bool:
    text = str(error or "").lower()
    compact = text.replace(" ", "")
    return any(
        token in text or token in compact
        for token in (
            "overloaded",
            "too many requests",
            "rate limit",
            "过载",
            "接口错误429",
            "接口错误502",
            "接口错误503",
            "接口错误504",
        )
    )


def retryable_script_error(error: str) -> bool:
    text = str(error or "")
    if any(token in text for token in ("积分不足", "未授权", "请求过大", "页码不存在", "尚未打开")):
        return False
    if is_overload_script_error(text):
        return True
    return any(token in text for token in ("超时", "网络错误", "平台模型调用失败"))


def script_retry_delay(error: str, slide_index: int = 0) -> float:
    if is_overload_script_error(error):
        return float(SCRIPT_OVERLOAD_DELAY)
    return float(SCRIPT_RETRY_DELAY)


def script_retry_limit(error: str) -> int:
    if is_overload_script_error(error):
        return max(0, int(SCRIPT_OVERLOAD_RETRIES))
    return max(0, int(SCRIPT_MODEL_RETRIES))


def ppt_path_from_drop_event(event) -> str:
    if not isinstance(event, dict):
        return ""
    files = (event.get("dataTransfer") or {}).get("files") or []
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("pywebviewFullPath") or "").strip()
        if Path(path).suffix.lower() in DECK_SUFFIXES:
            return path
    return ""


def _slide_public(slide, include_display: bool = False, include_thumb: bool = False) -> dict:
    data = {
        "index": slide.index,
        "title": slide.title,
        "script": slide.script,
        "has_script": bool(slide.script),
        "thumb_url": "",
        "display_url": "",
    }
    if include_thumb and slide.thumb_path and Path(slide.thumb_path).exists():
        data["thumb_url"] = file_to_display_data_url(Path(slide.thumb_path))
    if include_display and slide.image_path and Path(slide.image_path).exists():
        data["display_url"] = file_to_display_data_url(Path(slide.image_path))
    return data


def _deck_public(deck: DeckRecord) -> dict:
    starred = set(load_favorites(deck.source_path))
    slides = []
    for slide in deck.slides:
        row = _slide_public(slide)
        row["starred"] = slide.index in starred
        slides.append(row)
    return {
        "source_path": deck.source_path,
        "file_name": Path(deck.source_path).name,
        "slide_count": len(slides),
        "slides": slides,
    }


class BridgeApi:
    def __init__(self) -> None:
        # Must stay private: pywebview walks public attributes when injecting JS.
        # A public `window` would recurse into WinForms and freeze the UI thread.
        self._window = None
        self.deck: DeckRecord | None = None
        self.current_index = 1
        self.history: list[dict] = []
        self._open_lock = threading.Lock()
        self._deck_gen = 0
        self._open_ident = ""
        self._open_started = 0.0
        self._script_gen = 0
        self._script_batch_gen = 0
        self._qa_gen = 0

    def _client(self) -> AIClient:
        return AIClient(load_settings())

    def _require_key(self) -> dict | None:
        if not load_settings().api_key.strip():
            return {"ok": False, "error": "请先在设置中填写 API Key"}
        return None

    def _route_name(self, route) -> str:
        text = str(route or "").strip().lower()
        if text in ("platform", "byok"):
            return text
        return "byok"

    def _web_search(self, value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _run_model(self, messages: list[dict], route, fail_label: str, web_search=False, on_delta=None) -> dict:
        use_platform = self._route_name(route) == "platform"
        want_search = self._web_search(web_search) and "回答" in fail_label
        if use_platform:
            feature = "qa" if "回答" in fail_label else "script"
            if on_delta:
                out = complete_remote_stream(messages, feature, want_search, on_delta)
            else:
                out = complete_remote(messages, feature, want_search)
            if not out.get("ok"):
                return {"ok": False, "error": out.get("error") or fail_label}
            return {
                "ok": True,
                "text": out.get("text") or "",
                "billed": bool(out.get("billed")),
                "fee": out.get("fee") or "",
                "balance": out.get("balance") or "",
                "notice": out.get("notice") or "",
                "prompt_tokens": out.get("prompt_tokens"),
                "completion_tokens": out.get("completion_tokens"),
                "error": "",
            }
        blocked = self._require_key()
        if blocked:
            return blocked
        try:
            if want_search:
                result = self._client().complete(messages, web_search=True)
                if on_delta and result.text:
                    on_delta(result.text)
                return {"ok": True, "text": result.text, "billed": False, "error": ""}
            if on_delta:
                parts: list[str] = []
                for chunk in self._client().iter_complete(messages):
                    if chunk.text:
                        parts.append(chunk.text)
                        on_delta("".join(parts))
                text = "".join(parts)
                if not text:
                    return {"ok": False, "error": fail_label}
                return {"ok": True, "text": text, "billed": False, "error": ""}
            text = self._client().chat(messages)
        except AIError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": fail_label}
        return {"ok": True, "text": text, "billed": False, "error": ""}

    def choose_and_open(self) -> dict:
        if self._window is None:
            return {"ok": False, "error": "窗口未就绪"}
        import webview

        chosen = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            file_types=OPEN_FILE_TYPES,
        )
        if not chosen:
            return {"ok": False, "pending": False, "error": "已取消"}
        return self._start_open_worker(str(chosen[0]))

    def open_from_path(self, path: str) -> dict:
        raw = str(path or "").strip()
        if not raw:
            return {"ok": False, "pending": False, "error": "没有可打开的课件"}
        p = Path(raw)
        if p.suffix.lower() not in DECK_SUFFIXES:
            return {"ok": False, "pending": False, "error": "请拖入 PPT、PPTX 或 PDF 课件"}
        if not p.is_file():
            return {"ok": False, "pending": False, "error": "找不到课件文件"}
        return self._start_open_worker(str(p))

    def open_url(self, url: str) -> dict:
        import webbrowser

        text = str(url or "").strip()
        low = text.lower()
        if not (low.startswith("http://") or low.startswith("https://")):
            return {"ok": False, "error": "只能打开网页链接"}
        if any(ch in text for ch in ("\n", "\r", "\x00")):
            return {"ok": False, "error": "只能打开网页链接"}
        webbrowser.open(text)
        return {"ok": True, "error": ""}

    def _start_open_worker(self, path: str) -> dict:
        now = time.monotonic()
        ident = str(path)
        if ident == self._open_ident and now - self._open_started < 1.5:
            return {"ok": True, "pending": True, "error": ""}
        self._open_ident = ident
        self._open_started = now
        worker = threading.Thread(
            target=self._open_deck_worker,
            args=(path,),
            daemon=True,
        )
        worker.start()
        return {"ok": True, "pending": True, "error": ""}

    def _emit_js(self, func: str, payload) -> None:
        if self._window is None:
            return
        blob = json.dumps(payload, ensure_ascii=False)
        try:
            self._window.evaluate_js(f"window.{func} && window.{func}({blob})")
        except Exception:
            pass

    def _open_deck_worker(self, path: str) -> None:
        initialized = False
        try:
            import pythoncom

            pythoncom.CoInitialize()
            initialized = True
        except Exception:
            pass
        try:
            with self._open_lock:
                result = self.open_deck(path)
                if result.get("ok"):
                    self._emit_js("onDeckReady", result)
                    self._emit_thumbs()
                else:
                    self._emit_js("onIngestFailed", result.get("error") or "打开失败")
        except Exception as exc:
            self._emit_js("onIngestFailed", f"打开失败：{exc}")
        finally:
            if initialized:
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def open_deck(self, path: str) -> dict:
        try:
            deck = ingest_presentation(
                Path(path),
                on_progress=self._on_progress,
            )
        except IngestError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"打开失败：{exc}"}
        self.deck = deck
        self.current_index = 1
        self.history = []
        self._deck_gen += 1
        return {"ok": True, "error": "", "deck": _deck_public(deck)}

    def get_thumb(self, index: int) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件", "thumb_url": ""}
        try:
            slide = self.deck.slide_by_index(int(index))
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "页码不存在", "thumb_url": ""}
        data = _slide_public(slide, include_thumb=True)
        return {"ok": True, "index": slide.index, "thumb_url": data["thumb_url"]}

    def _emit_thumbs(self) -> None:
        if self.deck is None:
            return
        gen = self._deck_gen
        for slide in self.deck.slides:
            if gen != self._deck_gen:
                return
            data = _slide_public(slide, include_thumb=True)
            if data["thumb_url"]:
                self._emit_js(
                    "onThumbReady",
                    {"index": slide.index, "thumb_url": data["thumb_url"]},
                )

    def _on_progress(self, done: int, total: int) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onIngestProgress && window.onIngestProgress({done}, {total})"
            )
        except Exception:
            pass

    def select_slide(self, index: int) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        try:
            slide = self.deck.slide_by_index(int(index))
        except KeyError:
            return {"ok": False, "error": "页码不存在"}
        self.current_index = slide.index
        data = _slide_public(slide, include_display=True)
        try:
            key = deck_cache_key(self.deck.source_path, self.deck.mtime)
            data["media"] = publish_slide_media(
                Path(self.deck.source_path), slide.index, key
            )
        except Exception:
            data["media"] = []
        try:
            data["links"] = extract_slide_links(
                Path(self.deck.source_path), slide.index
            )
        except Exception:
            data["links"] = []
        return {"ok": True, "slide": data}

    def toggle_favorite(self, index) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        try:
            idx = int(index)
            self.deck.slide_by_index(idx)
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "页码不存在"}
        starred = persist_favorite(self.deck.source_path, idx)
        return {"ok": True, "index": idx, "starred": starred, "error": ""}

    def save_qa_favorite(self, payload) -> dict:
        data = payload
        if isinstance(payload, str):
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                return {"ok": False, "error": "收藏格式无效"}
        if isinstance(data, list) and data and isinstance(data[0], dict):
            data = data[0]
        if not isinstance(data, dict):
            return {"ok": False, "error": "收藏格式无效"}
        question = str(data.get("question") or "").strip()
        answer = str(data.get("answer") or "").strip()
        if not question and not answer:
            return {"ok": False, "error": "没有可收藏的内容"}
        record = {
            "question": question,
            "answer": answer,
            "file_name": str(data.get("file_name") or "").strip(),
            "source_path": str(data.get("source_path") or "").strip(),
            "slide_index": data.get("slide_index") or 0,
        }
        if self.deck:
            record["file_name"] = record["file_name"] or Path(self.deck.source_path).name
            record["source_path"] = record["source_path"] or self.deck.source_path
            record["slide_index"] = record["slide_index"] or self.current_index
        try:
            item = add_qa_favorite(record)
        except ValueError:
            return {"ok": False, "error": "没有可收藏的内容"}
        return {"ok": True, "item": item, "error": ""}

    def remove_qa_favorite(self, fav_id) -> dict:
        ok = delete_saved_qa(str(fav_id or ""))
        return {"ok": ok, "error": "" if ok else "收藏不存在"}

    def list_qa_favorites(self, query="") -> dict:
        return {"ok": True, "items": search_qa_favorites(str(query or "")), "error": ""}

    def generate_script(self, route="") -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        if self._window is None:
            return self._generate_script_now(route, self.current_index)
        self._script_batch_gen += 1
        self._script_gen += 1
        gen = self._script_gen
        slide_index = self.current_index
        threading.Thread(
            target=self._generate_script_worker,
            args=(route, gen, slide_index),
            daemon=True,
        ).start()
        return {"ok": True, "pending": True, "error": "", "slide_index": slide_index}

    def _generate_script_worker(self, route, gen: int, slide_index: int) -> None:
        def on_delta(text: str) -> None:
            if gen != self._script_gen:
                return
            self._emit_js("onScriptChunk", {"text": text, "slide_index": slide_index})

        try:
            out = self._generate_script_now(route, slide_index, on_delta)
        except Exception:
            out = {"ok": False, "error": "生成失败", "slide_index": slide_index}
        if gen != self._script_gen:
            return
        self._emit_js("onScriptDone", out)

    def _generate_script_now(self, route, slide_index: int, on_delta=None, on_retry=None) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        try:
            slide = self.deck.slide_by_index(int(slide_index))
        except (KeyError, TypeError, ValueError):
            return {"ok": False, "error": "页码不存在"}
        image_url = None
        if slide.image_path and Path(slide.image_path).exists():
            image_url = image_to_api_data_url(Path(slide.image_path))
        messages = build_script_messages(self.deck, slide.index, image_url)
        ran: dict = {}
        attempt = 0
        while True:
            if attempt:
                err = str(ran.get("error") or "")
                if on_retry:
                    on_retry(err)
                time.sleep(script_retry_delay(err, slide.index))
            ran = self._run_model(messages, route, "生成失败", on_delta=on_delta)
            if ran.get("ok"):
                break
            err = str(ran.get("error") or "")
            if not retryable_script_error(err):
                break
            attempt += 1
            if attempt > script_retry_limit(err):
                break
        if not ran.get("ok"):
            return {"ok": False, "error": ran.get("error") or "生成失败", "slide_index": slide.index}
        script = ran.get("text") or ""
        slide.script = script
        save_script(self.deck.source_path, self.deck.mtime, slide.index, script)
        out = {"ok": True, "script": script, "error": "", "slide_index": slide.index}
        for key in ("billed", "fee", "balance", "notice", "prompt_tokens", "completion_tokens"):
            if key in ran:
                out[key] = ran[key]
        return out

    def generate_all_scripts(self, route="") -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        indexes = [slide.index for slide in self.deck.slides]
        if not indexes:
            return {"ok": False, "error": "课件没有页面"}
        if self._window is None:
            return self._generate_all_scripts_now(route, indexes)
        self._script_gen += 1
        self._script_batch_gen += 1
        gen = self._script_batch_gen
        threading.Thread(
            target=self._generate_all_scripts_worker,
            args=(route, gen, indexes),
            daemon=True,
        ).start()
        return {"ok": True, "pending": True, "total": len(indexes), "error": ""}

    def _generate_all_scripts_worker(self, route, gen: int, indexes: list[int]) -> None:
        def on_progress(payload: dict) -> None:
            if gen != self._script_batch_gen:
                return
            self._emit_js("onScriptBatchProgress", payload)

        try:
            out = self._generate_all_scripts_now(route, indexes, on_progress, gen)
        except Exception:
            out = {
                "ok": False,
                "error": "生成失败",
                "generated": 0,
                "skipped": 0,
                "failed": 0,
                "total": len(indexes),
            }
        if gen != self._script_batch_gen:
            return
        self._emit_js("onScriptBatchDone", out)

    def _generate_all_scripts_now(
        self,
        route,
        indexes: list[int],
        on_progress=None,
        gen: int | None = None,
    ) -> dict:
        generated = 0
        skipped = 0
        failed = 0
        error = ""
        total = len(indexes)
        last_out: dict = {}
        done = 0
        active: set[int] = set()
        state_lock = threading.Lock()
        stop = threading.Event()

        def cancelled() -> bool:
            if gen is not None and gen != self._script_batch_gen:
                stop.set()
                return True
            return stop.is_set()

        def progress_payload(slide_index, status: str, extra=None) -> dict:
            payload = {
                "current": max(1, done),
                "done": done,
                "total": total,
                "slide_index": slide_index,
                "status": status,
                "active": sorted(active),
            }
            if extra:
                payload.update(extra)
            return payload

        pending: list[int] = []
        for idx in indexes:
            if cancelled():
                error = error or "已取消"
                break
            try:
                slide = self.deck.slide_by_index(int(idx))
            except (KeyError, TypeError, ValueError):
                error = "页码不存在"
                if on_progress:
                    on_progress(progress_payload(idx, "error", {"error": error}))
                break
            if str(slide.script or "").strip():
                skipped += 1
                done += 1
                if on_progress:
                    on_progress(progress_payload(slide.index, "skipped"))
                continue
            pending.append(slide.index)

        def run_one(idx: int) -> dict:
            if cancelled():
                return {"ok": False, "error": "已取消", "slide_index": idx, "_skip": True}
            with state_lock:
                active.add(idx)
                if on_progress:
                    on_progress(progress_payload(idx, "running"))
            on_delta = None
            if self._window is not None:
                def on_delta(text: str, slide_index=idx) -> None:
                    if cancelled():
                        return
                    if slide_index != self.current_index:
                        return
                    self._emit_js("onScriptChunk", {"text": text, "slide_index": slide_index})

            def on_retry(err: str, page=idx) -> None:
                if not on_progress:
                    return
                with state_lock:
                    on_progress(progress_payload(page, "retrying", {"error": err}))

            return self._generate_script_now(route, idx, on_delta, on_retry)

        def worker_loop(queue: Queue) -> None:
            nonlocal generated, failed, error, last_out, done
            while not cancelled():
                try:
                    idx = queue.get_nowait()
                except Empty:
                    return
                try:
                    out = run_one(idx)
                    with state_lock:
                        active.discard(idx)
                        done += 1
                        if out.get("_skip"):
                            continue
                        last_out = out
                        if not out.get("ok"):
                            error = str(out.get("error") or "生成失败")
                            if on_progress:
                                on_progress(progress_payload(idx, "error", {"error": error}))
                            if fatal_script_batch_error(error):
                                stop.set()
                                return
                            failed += 1
                            continue
                        generated += 1
                        if on_progress:
                            on_progress(
                                progress_payload(idx, "ok", {"script": out.get("script") or ""})
                            )
                finally:
                    queue.task_done()

        if not error and pending:
            workers = max(1, min(int(SCRIPT_BATCH_WORKERS), len(pending)))
            queue: Queue = Queue()
            for idx in pending:
                queue.put(idx)
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="script-batch") as pool:
                futures = [pool.submit(worker_loop, queue) for _ in range(workers)]
                for future in futures:
                    future.result()

        if cancelled() and not error:
            error = "已取消"
        result = {
            "ok": not error,
            "generated": generated,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "error": error,
        }
        for key in ("billed", "fee", "balance", "notice"):
            if key in last_out:
                result[key] = last_out[key]
        return result

    def ask_question(self, question: str, attachments=None, route="", web_search=False) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        question = (question or "").strip()
        shots = self._prepare_attachments(attachments)
        if not question and not shots:
            return {"ok": False, "error": "请输入问题或附上截图"}
        if self._window is None:
            return self._ask_question_now(question, shots, route, web_search)
        self._qa_gen += 1
        gen = self._qa_gen
        threading.Thread(
            target=self._ask_question_worker,
            args=(question, shots, route, web_search, gen),
            daemon=True,
        ).start()
        return {"ok": True, "pending": True, "error": ""}

    def _ask_question_worker(self, question, shots, route, web_search, gen: int) -> None:
        def on_delta(text: str) -> None:
            if gen != self._qa_gen:
                return
            self._emit_js("onQaChunk", {"text": text})

        try:
            out = self._ask_question_now(question, shots, route, web_search, on_delta)
        except Exception:
            out = {"ok": False, "error": "回答失败"}
        if gen != self._qa_gen:
            return
        self._emit_js("onQaDone", out)

    def _ask_question_now(
        self,
        question: str,
        shots: list,
        route,
        web_search=False,
        on_delta=None,
    ) -> dict:
        slide = self.deck.slide_by_index(self.current_index)
        image_url = None
        if slide.image_path and Path(slide.image_path).exists():
            image_url = image_to_api_data_url(Path(slide.image_path))
        messages = build_qa_messages(
            self.deck,
            self.current_index,
            image_url,
            self.history,
            question,
            shots,
        )
        ran = self._run_model(messages, route, "回答失败", web_search, on_delta=on_delta)
        if not ran.get("ok"):
            return {"ok": False, "error": ran.get("error") or "回答失败"}
        answer = ran.get("text") or ""
        stored = question or "【截图】"
        if shots:
            stored = stored + " 【附截图】"
        self.history.append(
            {
                "role": "user",
                "content": stored,
                "question": question,
                "attachments": shots,
            }
        )
        self.history.append({"role": "assistant", "content": answer})
        out = {"ok": True, "answer": answer, "error": "", "slide_index": slide.index}
        for key in ("billed", "fee", "balance", "notice", "prompt_tokens", "completion_tokens"):
            if key in ran:
                out[key] = ran[key]
        return out

    def clear_chat(self) -> dict:
        self.history = []
        return {"ok": True, "error": ""}

    def delete_turn(self, turn_index) -> dict:
        span = self._turn_span(turn_index)
        if span is None:
            return {"ok": False, "error": "没有这段问答"}
        start, end = span
        del self.history[start:end]
        return {"ok": True, "error": ""}

    def retry_turn(self, turn_index, route="", web_search=False) -> dict:
        if self.deck is None:
            return {"ok": False, "error": "尚未打开课件"}
        if self._window is None:
            return self._retry_turn_now(turn_index, route, web_search)
        self._qa_gen += 1
        gen = self._qa_gen
        threading.Thread(
            target=self._retry_turn_worker,
            args=(turn_index, route, web_search, gen),
            daemon=True,
        ).start()
        return {"ok": True, "pending": True, "error": ""}

    def _retry_turn_worker(self, turn_index, route, web_search, gen: int) -> None:
        def on_delta(text: str) -> None:
            if gen != self._qa_gen:
                return
            self._emit_js("onQaChunk", {"text": text})

        try:
            out = self._retry_turn_now(turn_index, route, web_search, on_delta)
        except Exception:
            out = {"ok": False, "error": "回答失败"}
        if gen != self._qa_gen:
            return
        self._emit_js("onQaDone", out)

    def _retry_turn_now(self, turn_index, route="", web_search=False, on_delta=None) -> dict:
        span = self._turn_span(turn_index)
        if span is None:
            return {"ok": False, "error": "没有这段问答"}
        start, _end = span
        user = self.history[start]
        question = str(user.get("question") or "").strip()
        shots = user.get("attachments") or []
        if not isinstance(shots, list):
            shots = self._prepare_attachments(shots)
        if not question:
            question = str(user.get("content") or "").replace(" 【附截图】", "").strip()
            if question == "【截图】":
                question = ""
        if not question and not shots:
            return {"ok": False, "error": "请输入问题或附上截图"}
        slide = self.deck.slide_by_index(self.current_index)
        image_url = None
        if slide.image_path and Path(slide.image_path).exists():
            image_url = image_to_api_data_url(Path(slide.image_path))
        prior = [
            {"role": item["role"], "content": item["content"]}
            for item in self.history[:start]
            if item.get("role") in ("user", "assistant")
        ]
        messages = build_qa_messages(
            self.deck,
            self.current_index,
            image_url,
            prior,
            question,
            shots,
        )
        ran = self._run_model(messages, route, "回答失败", web_search, on_delta=on_delta)
        if not ran.get("ok"):
            return {"ok": False, "error": ran.get("error") or "回答失败"}
        answer = ran.get("text") or ""
        self.history[start + 1] = {"role": "assistant", "content": answer}
        out = {"ok": True, "answer": answer, "error": "", "slide_index": slide.index}
        for key in ("billed", "fee", "balance", "notice", "prompt_tokens", "completion_tokens"):
            if key in ran:
                out[key] = ran[key]
        return out

    def _turn_span(self, turn_index) -> tuple[int, int] | None:
        try:
            idx = int(turn_index)
        except (TypeError, ValueError):
            return None
        start = idx * 2
        end = start + 2
        if idx < 0 or end > len(self.history):
            return None
        if self.history[start].get("role") != "user":
            return None
        if self.history[start + 1].get("role") != "assistant":
            return None
        return start, end

    def _prepare_attachments(self, attachments) -> list[str]:
        if attachments is None or attachments == "":
            return []
        if isinstance(attachments, str):
            try:
                parsed = json.loads(attachments)
            except json.JSONDecodeError:
                parsed = [attachments]
            attachments = parsed
        if not isinstance(attachments, list):
            return []
        out: list[str] = []
        for item in attachments[:3]:
            if not isinstance(item, str) or not item.startswith("data:"):
                continue
            try:
                out.append(data_url_to_api_data_url(item))
            except Exception:
                continue
        return out

    def get_settings(self) -> dict:
        s = load_settings()
        return {
            "ok": True,
            "base_url": s.base_url,
            "model": s.model,
            "auth_mode": s.auth_mode,
            "theme": s.theme,
            "billing_url": resolve_billing_url(s.billing_url),
            "api_key_set": bool(s.api_key.strip()),
        }

    def save_settings(self, payload: dict | str) -> dict:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return {"ok": False, "error": "设置格式无效"}
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            payload = payload[0]
        if not isinstance(payload, dict):
            return {"ok": False, "error": "设置格式无效"}
        current = load_settings()
        key = payload.get("api_key", "")
        if not str(key).strip():
            key = current.api_key
        mode = payload.get("auth_mode", current.auth_mode)
        if mode not in ("bearer", "raw"):
            mode = "bearer"
        theme = payload.get("theme", current.theme)
        if theme not in THEMES:
            theme = current.theme
        if "base_url" in payload:
            base_url = str(payload.get("base_url") or "").strip()
        else:
            base_url = current.base_url
        if "model" in payload:
            model = str(payload.get("model") or "").strip()
        else:
            model = current.model
        updated = AppSettings(
            base_url=base_url,
            api_key=str(key),
            model=model,
            auth_mode=mode,
            theme=theme,
            billing_url=str(payload.get("billing_url", current.billing_url) or "").strip()
            or current.billing_url,
        )
        save_settings(updated)
        return {"ok": True}

    def test_connection(self) -> dict:
        blocked = self._require_key()
        if blocked:
            return blocked
        try:
            text = self._client().chat([{"role": "user", "content": "回复pong"}])
        except AIError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception:
            return {"ok": False, "error": "连接失败"}
        return {"ok": True, "reply": text}

    def get_wallet(self) -> dict:
        data = fetch_wallet()
        data["has_key"] = bool(load_settings().api_key.strip())
        return data

    def hello_server(self) -> dict:
        return hello_remote()

    def redeem_credit_code(self, code: str) -> dict:
        return redeem_remote(code)

    def create_invite_code(self) -> dict:
        return create_invite_remote()

    def redeem_invite_code(self, code: str) -> dict:
        return redeem_invite_remote(code)

    def create_wechat_pay(self, amount) -> dict:
        return create_wechat_pay_remote(amount)

    def query_wechat_pay(self, order_id: str) -> dict:
        return query_wechat_pay_remote(order_id)

    def report_telemetry(self, events) -> dict:
        if isinstance(events, str):
            try:
                events = json.loads(events)
            except json.JSONDecodeError:
                return {"ok": False, "error": "事件无效"}
        if not isinstance(events, list):
            return {"ok": False, "error": "事件无效"}
        return send_telemetry(events)

    def app_version(self) -> dict:
        version = current_app_version()
        return {"ok": True, "version": version}

    def check_app_update(self) -> dict:
        current = current_app_version()
        remote = fetch_update_info()
        if not remote.get("ok"):
            return {
                "ok": False,
                "newer": False,
                "available": False,
                "version": "",
                "current": current,
                "size": 0,
                "sha256": "",
                "error": str(remote.get("error") or "无法检查更新"),
            }
        version = str(remote.get("version") or "")
        newer = bool(remote.get("available")) and version_newer(version, current)
        return {
            "ok": True,
            "newer": newer,
            "available": bool(remote.get("available")),
            "version": version,
            "current": current,
            "size": int(remote.get("size") or 0),
            "sha256": str(remote.get("sha256") or ""),
            "error": "",
        }

    def apply_app_update(self) -> dict:
        info = self.check_app_update()
        if not info.get("ok"):
            return info
        if not info.get("newer"):
            return {"ok": False, "error": "已经是最新版本"}
        dest = Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".") / "PDReaderSetup.exe"
        out = download_update_file(dest, str(info.get("sha256") or ""))
        if not out.get("ok"):
            return out
        path = str(out.get("path") or dest)
        version = str(info.get("version") or "")
        cmd = update_setup_command(path, version)
        try:
            kwargs: dict = {}
            if os.name == "nt":
                kwargs["creationflags"] = (
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                    | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
                )
            subprocess.Popen(cmd, close_fds=False, **kwargs)
        except OSError as exc:
            return {"ok": False, "error": f"无法打开安装包：{exc}"}
        return {"ok": True, "path": path, "version": version, "quit": True, "error": ""}

    def quit_app(self) -> dict:
        def destroy_window() -> None:
            try:
                if self._window is not None:
                    self._window.destroy()
                    return
            except Exception:
                pass
            os._exit(0)

        def force_exit() -> None:
            os._exit(0)

        if not os.environ.get("PYTEST_CURRENT_TEST"):
            threading.Timer(0.2, destroy_window).start()
            threading.Timer(1.2, force_exit).start()
        return {"ok": True, "quit": True, "error": ""}
