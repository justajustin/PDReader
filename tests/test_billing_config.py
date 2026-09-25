from ppt_study.billing_config import candidate_billing_urls, resolve_billing_url


def _no_packaged(monkeypatch):
    monkeypatch.delenv("PPT_STUDY_BILLING_URL", raising=False)
    monkeypatch.setattr("ppt_study.billing_config.packaged_billing_url", lambda: "")
    monkeypatch.setattr("ppt_study.billing_config.BUILTIN_BILLING_URL", "https://fixed.trycloudflare.com")


def test_resolve_uses_builtin_for_local_default(monkeypatch):
    _no_packaged(monkeypatch)
    assert resolve_billing_url("http://127.0.0.1:8765") == "https://fixed.trycloudflare.com"
    assert resolve_billing_url("") == "https://fixed.trycloudflare.com"
    assert resolve_billing_url(None) == "https://fixed.trycloudflare.com"


def test_resolve_keeps_explicit_local_test_server(monkeypatch):
    _no_packaged(monkeypatch)
    assert resolve_billing_url("http://127.0.0.1:54321") == "http://127.0.0.1:54321"


def test_resolve_replaces_stale_trycloudflare(monkeypatch):
    _no_packaged(monkeypatch)
    assert resolve_billing_url("https://old-name.trycloudflare.com") == "https://fixed.trycloudflare.com"
    assert resolve_billing_url("https://fixed.trycloudflare.com") == "https://fixed.trycloudflare.com"


def test_candidates_prefer_saved_loopback(monkeypatch):
    _no_packaged(monkeypatch)
    urls = candidate_billing_urls("http://127.0.0.1:8765")
    assert urls[0] == "http://127.0.0.1:8765"
    assert "https://fixed.trycloudflare.com" in urls


def test_candidates_public_first_when_unset(monkeypatch):
    monkeypatch.delenv("PPT_STUDY_BILLING_URL", raising=False)
    monkeypatch.setattr(
        "ppt_study.billing_config.BUILTIN_BILLING_URL",
        "https://fixed.trycloudflare.com",
    )
    monkeypatch.setattr("ppt_study.billing_config.packaged_billing_url", lambda: "")
    urls = candidate_billing_urls("")
    assert urls[0] == "https://fixed.trycloudflare.com"
    assert urls[-1] == "http://127.0.0.1:8765"


def test_candidates_put_learned_before_builtin(monkeypatch):
    monkeypatch.delenv("PPT_STUDY_BILLING_URL", raising=False)
    monkeypatch.setattr(
        "ppt_study.billing_config.BUILTIN_BILLING_URL",
        "https://fixed.trycloudflare.com",
    )
    monkeypatch.setattr("ppt_study.billing_config.packaged_billing_url", lambda: "")
    urls = candidate_billing_urls("", learned="https://new-name.trycloudflare.com")
    assert urls[0] == "https://new-name.trycloudflare.com"
    assert "https://fixed.trycloudflare.com" in urls


def test_remember_billing_endpoint_keeps_https(appdata_tmp):
    from ppt_study.billing_client import load_billing_endpoint, remember_billing_endpoint

    remember_billing_endpoint(
        "https://synced.trycloudflare.com",
        "http://10.1.2.3:8765",
    )
    data = load_billing_endpoint()
    assert data["billing_url"] == "https://synced.trycloudflare.com"
    assert data["lan_url"] == "http://10.1.2.3:8765"
