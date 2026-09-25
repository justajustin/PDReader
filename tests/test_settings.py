from ppt_study.models import AppSettings
from ppt_study.settings import load_settings, save_settings


def test_load_settings_returns_defaults_when_missing(appdata_tmp):
    from ppt_study.paths import settings_file

    s = load_settings()
    assert s.base_url == ""
    assert s.api_key == ""
    assert s.model == ""
    assert s.auth_mode == "bearer"
    assert s.theme == "light"
    assert not settings_file().exists()


def test_save_and_load_theme(appdata_tmp):
    original = AppSettings(
        base_url="https://www.dmxapi.cn/v1",
        api_key="sk-test-not-real",
        model="gpt-5.6-sol",
        auth_mode="bearer",
        theme="eye",
    )
    save_settings(original)
    loaded = load_settings()
    assert loaded.theme == "eye"


def test_invalid_theme_falls_back_to_light(appdata_tmp):
    from ppt_study.paths import settings_file

    settings_file().write_text(
        '{"base_url":"https://x","api_key":"","model":"m","auth_mode":"bearer","theme":"neon"}',
        encoding="utf-8",
    )
    assert load_settings().theme == "light"


def test_save_and_load_roundtrip(appdata_tmp):
    original = AppSettings(
        base_url="https://www.dmxapi.cn/v1",
        api_key="sk-test-not-real",
        model="gpt-5.6-sol",
        auth_mode="raw",
    )
    save_settings(original)
    loaded = load_settings()
    assert loaded == original
    text = (appdata_tmp / "PPTStudyCompanion" / "settings.json").read_text(encoding="utf-8")
    assert "sk-test-not-real" in text


def test_blank_settings_roundtrip(appdata_tmp):
    save_settings(
        AppSettings(base_url="", api_key="", model="", auth_mode="bearer", theme="dark")
    )
    loaded = load_settings()
    assert loaded.base_url == ""
    assert loaded.model == ""
    assert loaded.theme == "dark"
