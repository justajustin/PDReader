import json

import httpx
import pytest

from ppt_study.ai_client import AIClient, AIError
from ppt_study.models import AppSettings


def _settings(**kwargs):
    data = dict(
        base_url="https://example.test/v1",
        api_key="sk-aaa",
        model="gpt-5.6-sol",
        auth_mode="bearer",
    )
    data.update(kwargs)
    return AppSettings(**data)


def test_empty_key_raises_without_http():
    client = AIClient(_settings(api_key="  "))
    with pytest.raises(AIError, match="API Key"):
        client.chat([{"role": "user", "content": "hi"}])


def test_empty_base_url_raises_without_http():
    client = AIClient(_settings(base_url=""))
    with pytest.raises(AIError, match="Base URL"):
        client.chat([{"role": "user", "content": "hi"}])


def test_bearer_and_stream_deltas():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        assert request.headers["Authorization"] == "Bearer sk-aaa"
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-sol"
        assert body["stream"] is True
        assert body["store"] is False
        assert body["input"][0]["type"] == "message"
        assert body["input"][0]["role"] == "user"
        assert body["input"][0]["content"] == "hi"
        assert "instructions" not in body
        lines = (
            'data: {"type":"response.output_text.delta","delta":"你"}\n\n'
            'data: {"type":"response.output_text.delta","delta":"好"}\n\n'
            'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    client = AIClient(_settings(), transport=transport)
    assert client.chat([{"role": "user", "content": "hi"}]) == "你好"
    streamed = list(client.iter_chat([{"role": "user", "content": "hi"}]))
    assert streamed == ["你", "好"]


def test_complete_reads_usage_trailer():
    def handler(request: httpx.Request) -> httpx.Response:
        lines = (
            'data: {"type":"response.output_text.delta","delta":"好"}\n\n'
            'data: {"type":"response.completed","response":{"status":"completed","usage":{"input_tokens":12,"output_tokens":5,"total_tokens":17}}}\n\n'
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.text == "好"
    assert result.usage["prompt_tokens"] == 12
    assert result.usage["completion_tokens"] == 5


def test_raw_auth_and_json_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        assert request.headers["Authorization"] == "sk-bbb"
        return httpx.Response(
            200,
            json={"status": "completed", "output_text": "ok"},
        )

    client = AIClient(
        _settings(api_key="sk-bbb", auth_mode="raw"),
        transport=httpx.MockTransport(handler),
    )
    assert client.chat([{"role": "user", "content": "hi"}]) == "ok"


def test_401_becomes_aierror():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="401"):
        client.chat([{"role": "user", "content": "hi"}])


def test_ai_http_timeout_allows_long_script_reads():
    from ppt_study.ai_client import AI_READ_TIMEOUT, ai_http_timeout

    timeout = ai_http_timeout()
    assert timeout.connect <= 8.0
    assert timeout.read >= 300.0
    assert timeout.read == AI_READ_TIMEOUT


def test_timeout_becomes_aierror():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="超时") as info:
        client.chat([{"role": "user", "content": "hi"}])
    assert "sk-aaa" not in str(info.value)


def test_network_becomes_aierror():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="网络") as info:
        client.chat([{"role": "user", "content": "hi"}])
    assert "sk-aaa" not in str(info.value)


def test_stream_skips_empty_choices():
    def handler(request: httpx.Request) -> httpx.Response:
        lines = (
            'data: {"type":"response.created","response":{"id":"resp_1"}}\n\n'
            'data: {"type":"response.output_text.delta","delta":"讲"}\n\n'
            'data: {"type":"response.output_text.delta","delta":"稿"}\n\n'
            'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == "讲稿"


def test_json_empty_choices_uses_error_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "failed", "error": {"message": "模型暂时不可用"}},
        )

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="模型暂时不可用"):
        client.chat([{"role": "user", "content": "hi"}])


def test_http_error_includes_body_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "model not found"}})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="model not found"):
        client.chat([{"role": "user", "content": "hi"}])


def test_web_search_uses_responses_and_citations():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-sol"
        assert body["tools"] == [{"type": "web_search"}]
        assert "stream" not in body
        assert body["input"][0]["type"] == "message"
        assert body["input"][0]["role"] == "user"
        assert body["input"][0]["content"][0]["type"] == "input_text"
        assert body["input"][0]["content"][1]["type"] == "input_image"
        assert body["input"][0]["content"][1]["image_url"] == "data:image/png;base64,xx"
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "web_search_call", "status": "completed"},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "北京今天偏热。",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "title": "天气",
                                        "url": "https://example.test/weather",
                                    }
                                ],
                            }
                        ],
                    },
                ],
                "usage": {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
            },
        )

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "今天北京热吗？"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,xx"}},
                ],
            }
        ],
        web_search=True,
    )
    assert "北京今天偏热。" in result.text
    assert "https://example.test/weather" in result.text
    assert result.usage["prompt_tokens"] == 20
    assert result.usage["completion_tokens"] == 8


def test_web_search_empty_key_raises_without_http():
    client = AIClient(_settings(api_key=""))
    with pytest.raises(AIError, match="API Key"):
        client.complete([{"role": "user", "content": "hi"}], web_search=True)


def test_falls_back_to_chat_when_responses_unsupported():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/responses"):
            return httpx.Response(
                404,
                json={"error": {"message": "no such route, use v1/chat/completions"}},
            )
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        assert body["model"] == "gpt-5.6-sol"
        assert body["stream"] is True
        assert body.get("stream_options") == {"include_usage": True}
        lines = (
            'data: {"choices":[{"delta":{"content":"讲"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"稿"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":9,"completion_tokens":2,"total_tokens":11}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.text == "讲稿"
    assert result.usage["prompt_tokens"] == 9
    assert result.usage["completion_tokens"] == 2
    assert seen[0].endswith("/responses")
    assert seen[-1].endswith("/chat/completions")


def test_401_does_not_fallback_to_chat():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="401"):
        client.chat([{"role": "user", "content": "hi"}])
    assert seen == ["/v1/responses"]


def test_responses_json_when_not_event_stream():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output_text": "已生成",
                "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
            },
        )

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.text == "已生成"
    assert result.usage["prompt_tokens"] == 4


def test_system_prompt_goes_to_instructions():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["instructions"] == "你是课件助教"
        assert [item["role"] for item in body["input"]] == ["user"]
        assert body["input"][0]["type"] == "message"
        return httpx.Response(
            200,
            json={"status": "completed", "output_text": "好"},
        )

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    assert (
        client.chat(
            [
                {"role": "system", "content": "你是课件助教"},
                {"role": "user", "content": "hi"},
            ]
        )
        == "好"
    )


def test_native_sse_event_lines_and_keepalive():
    def handler(request: httpx.Request) -> httpx.Response:
        lines = (
            "event: response.created\n"
            'data: {"type":"response.created","response":{"id":"resp_1","error":null}}\n\n'
            "data:\n\n"
            "event: response.output_text.delta\n"
            'data: {"type":"response.output_text.delta","item_id":"msg_1","delta":"讲"}\n\n'
            "event: response.output_text.delta\n"
            'data: {"type":"response.output_text.delta","delta":"稿"}\n\n'
            "event: response.completed\n"
            'data: {"type":"response.completed","response":{"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"讲稿"}]}],"usage":{"input_tokens":3,"output_tokens":2,"total_tokens":5}}}\n\n'
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    result = client.complete([{"role": "user", "content": "hi"}])
    assert result.text == "讲稿"
    assert result.usage["prompt_tokens"] == 3


def test_stream_network_error_retries_json():
    seen_stream = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_stream.append(bool(body.get("stream")))
        if body.get("stream"):
            raise httpx.ConnectError("connection reset")
        return httpx.Response(
            200,
            json={"status": "completed", "output_text": "非流式"},
        )

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == "非流式"
    assert seen_stream == [True, False]


def test_error_event_uses_message_field():
    def handler(request: httpx.Request) -> httpx.Response:
        lines = (
            "event: error\n"
            'data: {"type":"error","code":"server_error","message":"upstream failed"}\n\n'
        )
        return httpx.Response(200, text=lines, headers={"content-type": "text/event-stream"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(AIError, match="upstream failed"):
        client.chat([{"role": "user", "content": "hi"}])


def test_ai_client_ignores_socks_proxy_env(monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")
    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:1080")
    monkeypatch.setenv("HTTP_PROXY", "socks5://127.0.0.1:1080")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "completed", "output_text": "ok"})

    client = AIClient(_settings(), transport=httpx.MockTransport(handler))
    assert client.chat([{"role": "user", "content": "hi"}]) == "ok"
