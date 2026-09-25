from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ppt_study.export_com as export_com
from ppt_study.export_com import ExportError, export_slides


@pytest.fixture(autouse=True)
def _clear_export_apps():
    export_com.release_export_apps()
    yield
    export_com.release_export_apps()


def _patch_apps(monkeypatch, dispatch_ex=None, dispatch=None):
    def default_missing(progid):
        raise OSError("missing")

    monkeypatch.setattr(export_com, "_dispatch_ex", dispatch_ex or default_missing)
    monkeypatch.setattr(export_com, "_dispatch", dispatch or default_missing)


def test_powerpoint_success(tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"x")
    out = tmp_path / "out"

    slide = MagicMock()
    slides = MagicMock()
    slides.__iter__.return_value = [slide]
    slides.__len__.return_value = 1

    presentation = MagicMock()
    presentation.Slides = slides
    app = MagicMock()
    app.Presentations.Open.return_value = presentation
    app.Presentations.Count = 0

    def fake_dispatch_ex(progid):
        if progid == "PowerPoint.Application":
            return app
        raise OSError("no")

    _patch_apps(monkeypatch, dispatch_ex=fake_dispatch_ex)

    def fake_export(slide_obj, dest, width, height):
        Path(dest).write_bytes(b"png")

    monkeypatch.setattr(export_com, "_slide_export", fake_export)

    paths = export_slides(ppt, out)
    assert len(paths) == 1
    assert paths[0].name == "slide_001.png"
    opened = app.Presentations.Open.call_args[0][0]
    assert Path(opened).parent == out
    assert Path(opened).name.startswith("_source")
    assert app.Presentations.Open.call_args[1].get("ReadOnly") is True
    assert app.Presentations.Open.call_args[1].get("WithWindow") is False
    presentation.Close.assert_called_once()
    app.Quit.assert_not_called()
    assert not any(
        getattr(c, "args", ())[:1] == ("Visible",) for c in app.mock_calls
    )


def test_falls_back_to_wps(tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"x")
    out = tmp_path / "out"
    wps_app = MagicMock()
    presentation = MagicMock()
    slides = MagicMock()
    slides.__iter__.return_value = [MagicMock()]
    presentation.Slides = slides
    wps_app.Presentations.Open.return_value = presentation
    wps_app.Presentations.Count = 0

    def fake_dispatch_ex(progid):
        if progid == "PowerPoint.Application":
            raise OSError("missing")
        if progid == "KWPP.Application":
            return wps_app
        raise OSError("missing")

    _patch_apps(monkeypatch, dispatch_ex=fake_dispatch_ex)
    monkeypatch.setattr(
        export_com,
        "_slide_export",
        lambda slide_obj, dest, width, height: Path(dest).write_bytes(b"png"),
    )
    paths = export_slides(ppt, out)
    assert paths[0].exists()


def test_both_fail_raises(tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"x")

    _patch_apps(monkeypatch)
    try:
        export_slides(ppt, tmp_path / "out")
        assert False, "should have raised"
    except ExportError as exc:
        assert "PowerPoint" in str(exc) or "WPS" in str(exc)


def test_one_slide_missing_keeps_others(tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"x")
    out = tmp_path / "out"

    slides = MagicMock()
    slides.__iter__.return_value = [MagicMock(), MagicMock()]
    presentation = MagicMock()
    presentation.Slides = slides
    app = MagicMock()
    app.Presentations.Open.return_value = presentation
    app.Presentations.Count = 0

    def fake_dispatch_ex(progid):
        if progid == "PowerPoint.Application":
            return app
        raise OSError("no")

    _patch_apps(monkeypatch, dispatch_ex=fake_dispatch_ex)

    def fake_export(slide_obj, dest, width, height):
        if dest.endswith("slide_001.png"):
            return
        Path(dest).write_bytes(b"png")

    monkeypatch.setattr(export_com, "_slide_export", fake_export)
    paths = export_slides(ppt, out)
    assert len(paths) == 2
    assert not paths[0].exists()
    assert paths[1].is_file()
    presentation.Close.assert_called_once()


def test_second_export_reuses_com_app(tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"x")
    starts = []

    slides = MagicMock()
    slides.__iter__.return_value = [MagicMock()]
    presentation = MagicMock()
    presentation.Slides = slides
    app = MagicMock()
    app.Presentations.Open.return_value = presentation
    app.Presentations.Count = 0

    def fake_dispatch_ex(progid):
        starts.append(progid)
        if progid == "PowerPoint.Application":
            return app
        raise OSError("no")

    _patch_apps(monkeypatch, dispatch_ex=fake_dispatch_ex)
    monkeypatch.setattr(
        export_com,
        "_slide_export",
        lambda slide_obj, dest, width, height: Path(dest).write_bytes(b"png"),
    )
    export_slides(ppt, tmp_path / "out1")
    export_slides(ppt, tmp_path / "out2")
    assert starts.count("PowerPoint.Application") == 1
    assert app.Quit.call_count == 0
    assert presentation.Close.call_count == 2
