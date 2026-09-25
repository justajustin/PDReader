from pathlib import Path

import pytest

from ppt_study.windows_installer import (
    APP_NAME,
    EXE_NAME,
    PRODUCT_ID,
    copy_payload,
    default_install_dir,
    install,
    normalize_install_dir,
    parse_args,
    payload_root,
    prepare_destination,
    suggest_install_dir_from_browse,
    write_uninstall_scripts,
)


def test_default_install_dir_is_per_user(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_install_dir() == tmp_path / "Programs" / PRODUCT_ID


def test_in_app_update_flag_and_overlay_copy(tmp_path):
    from ppt_study.windows_installer import copy_payload, is_existing_app_dir, is_in_app_update

    assert is_in_app_update(["/FORCECLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS"]) is True
    assert is_in_app_update(["--silent"]) is False
    src = tmp_path / "payload"
    src.mkdir()
    (src / EXE_NAME).write_bytes(b"new")
    dest = tmp_path / "install"
    dest.mkdir()
    (dest / EXE_NAME).write_bytes(b"old")
    leftover = dest / "keep-me.txt"
    leftover.write_text("stay", encoding="utf-8")
    assert is_existing_app_dir(dest) is True
    copy_payload(src, dest)
    assert (dest / EXE_NAME).read_bytes() == b"new"
    assert leftover.read_text(encoding="utf-8") == "stay"


def test_copy_payload_and_uninstall_script(tmp_path):
    src = tmp_path / "payload"
    src.mkdir()
    (src / EXE_NAME).write_bytes(b"fake")
    nested = src / "lib"
    nested.mkdir()
    (nested / "a.dll").write_bytes(b"dll")
    dest = tmp_path / "install"
    seen: list[tuple[int, int, str]] = []
    copy_payload(src, dest, on_progress=lambda done, total, name: seen.append((done, total, name)))
    assert (dest / EXE_NAME).is_file()
    assert (dest / "lib" / "a.dll").read_bytes() == b"dll"
    assert seen
    assert seen[-1][0] == seen[-1][1]
    write_uninstall_scripts(dest)
    cmd = (dest / "Uninstall.cmd").read_text(encoding="utf-8")
    ps1 = (dest / "Uninstall.ps1").read_text(encoding="utf-8")
    assert "Uninstall.ps1" in cmd
    assert PRODUCT_ID in ps1
    assert APP_NAME in ps1
    assert APP_NAME == "PDReader"


def test_parse_silent_flags():
    args = parse_args(["--silent", "--no-desktop", "--no-launch", "--dir", "D:\\Apps\\PPT"])
    assert args.silent
    assert args.no_desktop
    assert args.no_launch
    assert args.install_dir == r"D:\Apps\PPT"


def test_payload_root_in_source_tree():
    root = Path(__file__).resolve().parents[1]
    assert payload_root() == root / "dist" / PRODUCT_ID


def test_normalize_install_dir_strips_and_expands():
    path = normalize_install_dir(r"  D:\My Apps\PDReader  ")
    assert path == Path(r"D:\My Apps\PDReader")


def test_normalize_install_dir_rejects_empty():
    with pytest.raises(ValueError, match="安装目录"):
        normalize_install_dir("   ")


def test_browse_appends_product_folder_when_needed():
    assert suggest_install_dir_from_browse(r"D:\Apps") == Path(r"D:\Apps") / PRODUCT_ID
    assert suggest_install_dir_from_browse(r"D:\Apps\PDReader") == Path(r"D:\Apps\PDReader")


def test_prepare_destination_rejects_nonempty_unrelated_folder(tmp_path):
    dest = tmp_path / "Documents"
    dest.mkdir()
    (dest / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ValueError, match="不是空的"):
        prepare_destination(dest)


def test_prepare_destination_allows_empty_or_existing_app(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    prepare_destination(empty)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / EXE_NAME).write_bytes(b"old")
    prepare_destination(app_dir)


def test_installer_ui_allows_editing_install_dir():
    source = Path(__file__).resolve().parents[1] / "src" / "ppt_study" / "windows_installer.py"
    text = source.read_text(encoding="utf-8")
    assert 'state="readonly"' not in text
    assert "askdirectory" in text
    assert "浏览" in text
    assert "suggest_install_dir_from_browse" in text
    assert "threading" in text
    assert "Progressbar" in text
    assert "不要关闭窗口" in text
    assert "/T" in text
    assert "_retry_locked" in text
    assert "parse_known_args" in text
    assert "is_existing_app_dir" in text
    assert "is_in_app_update" in text
    assert "覆盖原安装目录" in text


def test_parse_ignores_inno_close_flags():
    args = parse_args(["/FORCECLOSEAPPLICATIONS", "/NORESTARTAPPLICATIONS", "--silent"])
    assert args.silent is True


def test_copy_payload_retries_locked_file(tmp_path, monkeypatch):
    src = tmp_path / "payload"
    src.mkdir()
    (src / EXE_NAME).write_bytes(b"fake")
    dest = tmp_path / "install"
    calls = {"n": 0}

    def flaky(source, target, follow_symlinks=True):
        calls["n"] += 1
        if calls["n"] == 1:
            err = PermissionError("busy")
            err.winerror = 32
            raise err
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_bytes(Path(source).read_bytes())

    monkeypatch.setattr("ppt_study.windows_installer.shutil.copy2", flaky)
    monkeypatch.setattr("ppt_study.windows_installer.stop_running_app", lambda wait=0.8: None)
    monkeypatch.setattr("ppt_study.windows_installer.time.sleep", lambda _s: None)
    copy_payload(src, dest)
    assert (dest / EXE_NAME).read_bytes() == b"fake"
    assert calls["n"] >= 2


def test_install_reports_status_without_blocking_helpers(appdata_tmp, tmp_path, monkeypatch):
    src = tmp_path / "payload"
    src.mkdir()
    (src / EXE_NAME).write_bytes(b"fake")
    dest = tmp_path / "app"
    notes: list[str] = []
    monkeypatch.setattr("ppt_study.windows_installer.stop_running_app", lambda wait=0.8: None)
    monkeypatch.setattr("ppt_study.windows_installer.create_shortcut", lambda *a, **k: None)
    monkeypatch.setattr("ppt_study.windows_installer.remove_legacy_shortcuts", lambda: None)
    monkeypatch.setattr("ppt_study.windows_installer.register_uninstall", lambda dest, version="": None)
    exe = install(
        dest,
        src=src,
        desktop=False,
        start_menu=False,
        register=False,
        version="0.3.1",
        on_status=notes.append,
    )
    assert exe == dest / EXE_NAME
    assert exe.is_file()
    assert any("复制" in msg for msg in notes)
    from ppt_study.app_version import current_app_version, read_installed_version

    assert read_installed_version() == "0.3.1"
    assert current_app_version() == "0.3.1"
    assert (dest / "app_version.json").read_text(encoding="utf-8").find("0.3.1") >= 0
