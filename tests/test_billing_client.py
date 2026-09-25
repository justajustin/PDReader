from ppt_study.billing_client import _bases, redeem_remote, reset_directory_cache


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, dict):
            return self._payload
        raise ValueError("not json")


def test_post_skips_html_error_and_tries_local(appdata_tmp, monkeypatch):
    reset_directory_cache()
    monkeypatch.setenv("PPT_STUDY_BILLING_URL", "https://pdreader.invalid")
    seen = []

    def fake_post(url, **kwargs):
        seen.append((url, kwargs.get("trust_env")))
        if "pdreader.invalid" in url:
            return _Resp(502, "<html>bad gateway</html>")
        return _Resp(200, {"ok": True, "credited": "10", "balance": "11"})

    monkeypatch.setattr("ppt_study.billing_client.httpx.post", fake_post)
    monkeypatch.setattr("ppt_study.billing_client.device_id", lambda: "dev-1")
    out = redeem_remote("ABC123")
    assert out["ok"] is True
    assert out["credited"] == "10"
    assert seen[0][1] is False
    assert any("127.0.0.1:8765" in url for url, _trust in seen)


def test_bases_prefers_live_local_operator(appdata_tmp, monkeypatch):
    reset_directory_cache()
    monkeypatch.delenv("PPT_STUDY_BILLING_URL", raising=False)
    monkeypatch.setattr("ppt_study.billing_client._local_operator_up", lambda: True)
    monkeypatch.setattr("ppt_study.billing_client._directory_lookup", lambda: "")
    monkeypatch.setattr(
        "ppt_study.billing_client.load_settings",
        lambda: type("S", (), {"billing_url": ""})(),
    )
    monkeypatch.setattr(
        "ppt_study.billing_client.load_billing_endpoint",
        lambda: {"billing_url": "https://pdreader.fun", "lan_url": "", "directory_url": ""},
    )
    urls = _bases()
    assert urls[0] == "http://127.0.0.1:8765"
    assert "https://pdreader.fun" in urls

def test_platform_opt_out_skips_discovery_and_requests(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("Platform opt-out must not perform discovery or network requests")

    monkeypatch.setenv("PPT_STUDY_DISABLE_PLATFORM", "true")
    monkeypatch.setattr("ppt_study.billing_client._directory_lookup", unexpected)
    monkeypatch.setattr("ppt_study.billing_client._local_operator_up", unexpected)
    monkeypatch.setattr("ppt_study.billing_client.httpx.get", unexpected)
    monkeypatch.setattr("ppt_study.billing_client.httpx.post", unexpected)
    monkeypatch.setattr("ppt_study.billing_client.device_id", lambda: "test-device")
    assert _bases() == []
    assert redeem_remote("sample-code")["ok"] is False


def test_platform_opt_out_prevents_update_download(monkeypatch, tmp_path):
    from ppt_study.billing_client import download_update_file

    def unexpected(*args, **kwargs):
        raise AssertionError("Platform opt-out must not open an HTTP stream")

    monkeypatch.setenv("PPT_STUDY_DISABLE_PLATFORM", "1")
    monkeypatch.setattr("ppt_study.billing_client.httpx.stream", unexpected)
    target = tmp_path / "update.exe"
    assert download_update_file(target)["ok"] is False
    assert not target.exists()
