from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from ppt_study.models import AppSettings


class AIError(Exception):
    pass


AI_CONNECT_TIMEOUT = 8.0
AI_READ_TIMEOUT = 300.0
AI_WRITE_TIMEOUT = 60.0


def ai_http_timeout(web_search: bool = False) -> httpx.Timeout:
    """Long read window for vision scripts; fail fast if the operator is unreachable."""
    del web_search
    return httpx.Timeout(
        connect=AI_CONNECT_TIMEOUT,
        read=AI_READ_TIMEOUT,
        write=AI_WRITE_TIMEOUT,
        pool=AI_CONNECT_TIMEOUT,
    )


@dataclass
class ChatResult:
    text: str
    usage: dict | None = None


@dataclass
class StreamChunk:
    text: str = ""
    done: bool = False
    usage: dict | None = None


def _payload_error(data: dict) -> str | None:
    err = data.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()
    if isinstance(err, dict):
        msg = err.get("message") or err.get("msg") or err.get("code")
        if msg:
            return str(msg).strip()
    if str(data.get("type") or "") == "error":
        msg = data.get("message") or data.get("msg")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return None


def _first_choice(data: dict) -> dict | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    return first if isinstance(first, dict) else None


def _parts_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits: list[str] = []
        for item in content:
            if isinstance(item, str):
                bits.append(item)
            elif isinstance(item, dict):
                bits.append(str(item.get("text") or item.get("content") or ""))
        return "".join(bits)
    return ""


def _delta_text(choice: dict) -> str:
    delta = choice.get("delta") or {}
    if not isinstance(delta, dict):
        return ""
    return _parts_text(delta.get("content")) or _parts_text(delta.get("text"))


def _message_text(choice: dict) -> str:
    message = choice.get("message") or {}
    if isinstance(message, dict):
        text = _parts_text(message.get("content")) or _parts_text(message.get("text"))
        if text:
            return text
    return _parts_text(choice.get("text"))


def _http_error_message(status: int, raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    msg = f"接口错误 {status}"
    if not text:
        return msg
    try:
        body = json.loads(text)
    except json.JSONDecodeError:
        return f"{msg}：{text[:200]}"
    extra = _payload_error(body) if isinstance(body, dict) else None
    if extra:
        return f"{msg}：{extra}"
    return msg


def _image_url_from_part(part: dict) -> str:
    img = part.get("image_url")
    if isinstance(img, dict):
        return str(img.get("url") or "").strip()
    if isinstance(img, str) and img.strip():
        return img.strip()
    return str(part.get("url") or "").strip()


def _to_responses_content(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[dict] = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"type": "input_text", "text": item})
            continue
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        if kind in {"image_url", "input_image"}:
            url = _image_url_from_part(item)
            if url:
                parts.append({"type": "input_image", "image_url": url, "detail": "auto"})
            continue
        text = str(item.get("text") or item.get("content") or "")
        if text:
            parts.append({"type": "input_text", "text": text})
    return parts


def messages_to_responses_input(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "user").strip().lower() or "user"
        if role not in {"system", "user", "assistant", "developer"}:
            role = "user"
        content = _to_responses_content(item.get("content"))
        if content == "" or content == []:
            continue
        out.append({"role": role, "content": content})
    return out


def normalize_usage(raw) -> dict | None:
    if not isinstance(raw, dict) or not raw:
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
    try:
        if prompt is None:
            prompt = raw["input_tokens"]
        if completion is None:
            completion = raw["output_tokens"]
        prompt = int(prompt)
        completion = int(completion)
    except (TypeError, ValueError, KeyError):
        return None
    if prompt < 0 or completion < 0:
        return None
    total = raw.get("total_tokens")
    try:
        total = int(total) if total is not None else prompt + completion
    except (TypeError, ValueError):
        total = prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def should_fallback_to_chat(exc: AIError) -> bool:
    msg = str(exc)
    if any(token in msg for token in ("接口错误 401", "接口错误 403", "API Key")):
        return False
    if "接口错误 404" in msg or "接口错误 405" in msg:
        return True
    low = msg.lower()
    return any(
        marker in low
        for marker in (
            "/chat/completions",
            "v1/chat",
            "chat completions",
            "does not support the responses",
            "responses api is not",
            "unknown endpoint",
            "no such route",
            "invalid url",
        )
    )


def should_retry_responses_without_stream(exc: AIError) -> bool:
    msg = str(exc)
    if any(token in msg for token in ("接口错误 401", "接口错误 403", "API Key")):
        return False
    if "接口错误 404" in msg or "接口错误 405" in msg:
        return False
    if "网络错误" in msg or "响应无效" in msg:
        return True
    low = msg.lower()
    return "stream" in low and any(
        token in low for token in ("unsupported", "unknown", "invalid", "not allowed")
    )


def _looks_like_sse(text: str) -> bool:
    stripped = text.lstrip("\ufeff \t\r\n")
    return stripped.startswith("event:") or stripped.startswith("data:")


def parse_responses_result(data: dict) -> ChatResult:
    err = _payload_error(data)
    status = str(data.get("status") or "")
    if status == "failed":
        raise AIError(err or "联网搜索失败")
    texts: list[str] = []
    citations: list[tuple[str, str]] = []
    seen: set[str] = set()
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"}:
                    text = str(part.get("text") or "")
                    if text:
                        texts.append(text)
                for ann in part.get("annotations") or []:
                    if not isinstance(ann, dict) or ann.get("type") != "url_citation":
                        continue
                    url = str(ann.get("url") or "").strip()
                    title = str(ann.get("title") or "").strip()
                    if url and url not in seen:
                        seen.add(url)
                        citations.append((title, url))
    if not texts:
        fallback = data.get("output_text")
        if isinstance(fallback, str) and fallback.strip():
            texts.append(fallback.strip())
    text = "\n".join(texts).strip()
    if not text:
        raise AIError(err or "模型没有返回内容")
    if citations:
        lines = ["", "来源："]
        for title, url in citations:
            lines.append(f"- {title} {url}".strip() if title else f"- {url}")
        text = text + "\n" + "\n".join(lines)
    return ChatResult(text=text, usage=normalize_usage(data.get("usage")))


class AIClient:
    def __init__(
        self,
        settings: AppSettings,
        transport: httpx.BaseTransport | None = None,
        timeout: float | httpx.Timeout | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._timeout = ai_http_timeout() if timeout is None else timeout

    def _http_client(self) -> httpx.Client:
        return httpx.Client(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=True,
            trust_env=False,
        )

    def _headers(self) -> dict[str, str]:
        key = self.settings.api_key.strip()
        if self.settings.auth_mode == "raw":
            auth = key
        else:
            auth = f"Bearer {key}"
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _base(self) -> str:
        base = self.settings.base_url.strip()
        if not base:
            raise AIError("请先在设置中填写 Base URL")
        if not self.settings.model.strip():
            raise AIError("请先在设置中填写模型")
        return base.rstrip("/")

    def _url(self) -> str:
        return self._base() + "/chat/completions"

    def _responses_url(self) -> str:
        return self._base() + "/responses"

    def _responses_payload(
        self,
        messages: list[dict],
        web_search: bool = False,
        stream: bool = False,
    ) -> dict:
        converted = messages_to_responses_input(messages)
        if not converted:
            raise AIError("请求无效")
        instructions: list[str] = []
        items: list[dict] = []
        for item in converted:
            role = str(item.get("role") or "user")
            content = item.get("content")
            if role in {"system", "developer"}:
                text = content if isinstance(content, str) else _parts_text(content)
                if str(text).strip():
                    instructions.append(str(text).strip())
                continue
            items.append({"type": "message", "role": role, "content": content})
        if not items:
            raise AIError("请求无效")
        payload = {
            "model": self.settings.model,
            "input": items,
            "store": False,
        }
        if instructions:
            payload["instructions"] = "\n\n".join(instructions)
        if web_search:
            payload["tools"] = [{"type": "web_search"}]
        elif stream:
            payload["stream"] = True
        return payload

    def iter_complete(self, messages: list[dict], web_search: bool = False) -> Iterator[StreamChunk]:
        if not self.settings.api_key.strip():
            raise AIError("请先在设置中填写 API Key")
        if web_search:
            result = self._complete_with_search(messages)
            if result.text:
                yield StreamChunk(text=result.text)
            yield StreamChunk(done=True, usage=result.usage)
            return
        yielded = False
        try:
            for chunk in self._iter_responses(messages):
                yielded = True
                yield chunk
            return
        except AIError as exc:
            if yielded or not should_fallback_to_chat(exc):
                raise
        yield from self._iter_chat_completions(messages)

    def _iter_chat_completions(self, messages: list[dict]) -> Iterator[StreamChunk]:
        payload = {
            "model": self.settings.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        yield from self._stream_request(self._url(), payload, "chat")

    def _iter_responses(self, messages: list[dict]) -> Iterator[StreamChunk]:
        url = self._responses_url()
        try:
            yield from self._stream_request(
                url, self._responses_payload(messages, stream=True), "responses"
            )
            return
        except AIError as exc:
            if not should_retry_responses_without_stream(exc):
                raise
        yield from self._stream_request(
            url, self._responses_payload(messages, stream=False), "responses"
        )

    def _stream_request(self, url: str, payload: dict, mode: str) -> Iterator[StreamChunk]:
        try:
            with self._http_client() as client:
                with client.stream(
                    "POST", url, headers=self._headers(), json=payload
                ) as resp:
                    if resp.status_code >= 400:
                        raw = resp.read()
                        raise AIError(_http_error_message(resp.status_code, raw))
                    ctype = (resp.headers.get("content-type") or "").lower()
                    if "text/event-stream" in ctype or "octet-stream" in ctype:
                        if mode == "responses":
                            yield from self._parse_responses_sse(resp)
                        else:
                            yield from self._parse_chat_sse(resp)
                        return
                    raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            if _looks_like_sse(text):
                if mode == "responses":
                    yield from self._consume_responses_sse(text.splitlines())
                else:
                    yield from self._consume_chat_sse(text.splitlines())
                return
            data = json.loads(text)
        except AIError:
            raise
        except ImportError as exc:
            raise AIError("网络错误") from exc
        except httpx.TimeoutException as exc:
            raise AIError("请求超时") from exc
        except httpx.RequestError as exc:
            raise AIError("网络错误") from exc
        except json.JSONDecodeError as exc:
            raise AIError("响应无效") from exc
        except (IndexError, TypeError, KeyError) as exc:
            raise AIError("响应无效") from exc
        if not isinstance(data, dict):
            raise AIError("响应无效")
        if mode == "responses":
            result = parse_responses_result(data)
            yield StreamChunk(text=result.text)
            yield StreamChunk(done=True, usage=result.usage)
            return
        err = _payload_error(data)
        choice = _first_choice(data)
        if not choice:
            raise AIError(err or "模型没有返回内容")
        content = _message_text(choice)
        if not content:
            raise AIError(err or "模型没有返回内容")
        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) and raw_usage else None
        yield StreamChunk(text=content)
        yield StreamChunk(done=True, usage=usage)

    def _parse_chat_sse(self, resp: httpx.Response) -> Iterator[StreamChunk]:
        yield from self._consume_chat_sse(resp.iter_lines())

    def _consume_chat_sse(self, lines) -> Iterator[StreamChunk]:
        last_error = None
        usage: dict | None = None
        any_text = False
        truncated = False
        try:
            for line in lines:
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                err = _payload_error(chunk)
                if err:
                    last_error = err
                raw_usage = chunk.get("usage")
                if isinstance(raw_usage, dict) and raw_usage:
                    usage = raw_usage
                choice = _first_choice(chunk)
                if not choice:
                    continue
                delta = _delta_text(choice)
                if delta:
                    any_text = True
                    yield StreamChunk(text=delta)
        except (httpx.RequestError, UnicodeDecodeError):
            truncated = True
        if not any_text:
            if truncated:
                raise AIError("网络错误")
            raise AIError(last_error or "模型没有返回内容")
        yield StreamChunk(done=True, usage=usage)

    def _parse_responses_sse(self, resp: httpx.Response) -> Iterator[StreamChunk]:
        yield from self._consume_responses_sse(resp.iter_lines())

    def _consume_responses_sse(self, lines) -> Iterator[StreamChunk]:
        last_error = None
        usage: dict | None = None
        any_text = False
        truncated = False
        try:
            for line in lines:
                if not line or line.startswith("event:") or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if not isinstance(chunk, dict):
                    continue
                kind = str(chunk.get("type") or "")
                err = _payload_error(chunk)
                if err:
                    last_error = err
                if kind == "error":
                    raise AIError(err or last_error or "模型没有返回内容")
                if kind in {"response.output_text.delta", "response.text.delta"}:
                    delta = chunk.get("delta")
                    text = delta if isinstance(delta, str) else _parts_text(delta)
                    if text:
                        any_text = True
                        yield StreamChunk(text=text)
                    continue
                if kind in {"response.output_text.done", "response.text.done"} and not any_text:
                    text = chunk.get("text")
                    if isinstance(text, str) and text:
                        any_text = True
                        yield StreamChunk(text=text)
                    continue
                if kind == "response.failed":
                    body = chunk.get("response") if isinstance(chunk.get("response"), dict) else chunk
                    extra = _payload_error(body) if isinstance(body, dict) else None
                    raise AIError(extra or last_error or "模型没有返回内容")
                if kind == "response.output_item.done" and not any_text:
                    item = chunk.get("item")
                    if isinstance(item, dict):
                        try:
                            result = parse_responses_result({"output": [item], "status": "completed"})
                        except AIError:
                            result = None
                        if result and result.text:
                            any_text = True
                            usage = result.usage or usage
                            yield StreamChunk(text=result.text)
                    continue
                if kind in {"response.completed", "response.incomplete"}:
                    body = chunk.get("response") if isinstance(chunk.get("response"), dict) else chunk
                    if isinstance(body, dict):
                        usage = normalize_usage(body.get("usage")) or usage
                        if not any_text:
                            try:
                                result = parse_responses_result(body)
                            except AIError:
                                result = None
                            if result and result.text:
                                any_text = True
                                usage = result.usage or usage
                                yield StreamChunk(text=result.text)
        except AIError:
            raise
        except (httpx.RequestError, UnicodeDecodeError):
            truncated = True
        if not any_text:
            if truncated:
                raise AIError("网络错误")
            raise AIError(last_error or "模型没有返回内容")
        yield StreamChunk(done=True, usage=usage)

    def complete(self, messages: list[dict], web_search: bool = False) -> ChatResult:
        parts: list[str] = []
        usage: dict | None = None
        for chunk in self.iter_complete(messages, web_search=web_search):
            if chunk.text:
                parts.append(chunk.text)
            if chunk.done:
                usage = chunk.usage
        text = "".join(parts)
        if not text:
            raise AIError("模型没有返回内容")
        return ChatResult(text=text, usage=usage)

    def _complete_with_search(self, messages: list[dict]) -> ChatResult:
        payload = self._responses_payload(messages, web_search=True)
        try:
            with self._http_client() as client:
                resp = client.post(
                    self._responses_url(),
                    headers=self._headers(),
                    json=payload,
                )
                raw = resp.content
                if resp.status_code >= 400:
                    raise AIError(_http_error_message(resp.status_code, raw))
                data = json.loads(raw.decode("utf-8"))
        except AIError:
            raise
        except ImportError as exc:
            raise AIError("网络错误") from exc
        except httpx.TimeoutException as exc:
            raise AIError("请求超时") from exc
        except httpx.RequestError as exc:
            raise AIError("网络错误") from exc
        except json.JSONDecodeError as exc:
            raise AIError("响应无效") from exc
        if not isinstance(data, dict):
            raise AIError("响应无效")
        return parse_responses_result(data)

    def iter_chat(self, messages: list[dict]) -> Iterator[str]:
        for chunk in self.iter_complete(messages):
            if chunk.text:
                yield chunk.text

    def chat(self, messages: list[dict]) -> str:
        return self.complete(messages).text
