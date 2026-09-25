from pathlib import Path

from ppt_study.app import web_dir
from ppt_study.paths import APP_DISPLAY_NAME, version_newer


def test_web_dir_points_to_index():
    assert (web_dir() / "index.html").exists()


def test_display_name_is_pdreader():
    assert APP_DISPLAY_NAME == "PDReader"


def test_version_newer_compares_semver():
    assert version_newer("0.2.1", "0.2.0") is True
    assert version_newer("0.2.0", "0.2.0") is False
    assert version_newer("0.1.9", "0.2.0") is False
    assert version_newer("bad", "0.2.0") is False
    from ppt_study.paths import suggest_next_version

    assert suggest_next_version("0.2.0") == "0.2.1"
    assert suggest_next_version("1.0.9") == "1.0.10"


def test_installed_version_comes_from_saved_file(appdata_tmp):
    from ppt_study.app_version import current_app_version, save_installed_version
    from ppt_study.paths import APP_VERSION

    assert current_app_version() == APP_VERSION
    save_installed_version("4.5.6")
    assert current_app_version() == "4.5.6"


def test_stamp_installer_version_roundtrip(tmp_path):
    from ppt_study.app_version import (
        read_stamped_installer_version,
        resolve_setup_version,
        sidecar_version_file,
        stamp_installer_version,
    )

    setup = tmp_path / "PDReaderSetup.exe"
    setup.write_bytes(b"MZ-fake-installer")
    stamp_installer_version(setup, "0.4.1")
    assert read_stamped_installer_version(setup) == "0.4.1"
    assert sidecar_version_file(setup).read_text(encoding="utf-8").strip() == "0.4.1"
    assert resolve_setup_version(["/APPVERSION=0.4.2"], setup) == "0.4.2"
    assert resolve_setup_version([], setup) == "0.4.1"
