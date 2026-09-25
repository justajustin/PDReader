from __future__ import annotations

import shutil
import threading
from pathlib import Path

PROG_POWERPOINT = "PowerPoint.Application"
PROG_WPS = "KWPP.Application"
EXPORT_WIDTH = 1920
EXPORT_HEIGHT = 1080

_APPS: dict[str, tuple[object, bool]] = {}
_APPS_LOCK = threading.Lock()
_EXPORT_LOCK = threading.Lock()


class ExportError(Exception):
    pass


def _dispatch(progid: str):
    import win32com.client

    return win32com.client.Dispatch(progid)


def _dispatch_ex(progid: str):
    import win32com.client

    return win32com.client.DispatchEx(progid)


def _slide_export(slide_obj, dest: str, width: int, height: int) -> None:
    slide_obj.Export(dest, "PNG", width, height)


def _quit_app(app) -> None:
    try:
        app.Quit()
    except Exception:
        pass


def release_export_apps() -> None:
    with _APPS_LOCK:
        held = list(_APPS.items())
        _APPS.clear()
    for _progid, (app, created_by_us) in held:
        if created_by_us:
            _quit_app(app)


def _app_alive(app) -> bool:
    try:
        int(app.Presentations.Count)
        return True
    except Exception:
        return False


def _acquire_app(progid: str):
    try:
        return _dispatch_ex(progid), True
    except Exception:
        return _dispatch(progid), False


def _get_app(progid: str):
    with _APPS_LOCK:
        held = _APPS.get(progid)
        if held is not None:
            app, created_by_us = held
            if _app_alive(app):
                return app, created_by_us
            _APPS.pop(progid, None)
            if created_by_us:
                _quit_app(app)
        app, created_by_us = _acquire_app(progid)
        _APPS[progid] = (app, created_by_us)
        return app, created_by_us


def _working_copy(ppt_path: Path, out_dir: Path) -> Path:
    dest = out_dir / f"_source{ppt_path.suffix.lower() or '.pptx'}"
    try:
        shutil.copy2(ppt_path, dest)
        return dest
    except OSError:
        return ppt_path


def _export_with_app(app, ppt_path: Path, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    work_copy = _working_copy(ppt_path, out_dir)
    presentation = None
    try:
        presentation = app.Presentations.Open(
            str(work_copy.resolve()),
            ReadOnly=True,
            Untitled=False,
            WithWindow=False,
        )
        paths: list[Path] = []
        for i, slide in enumerate(presentation.Slides, start=1):
            dest = out_dir / f"slide_{i:03d}.png"
            try:
                _slide_export(slide, str(dest), EXPORT_WIDTH, EXPORT_HEIGHT)
            except Exception:
                pass
            paths.append(dest)
        if not any(p.is_file() for p in paths):
            raise ExportError("全部页面导出失败")
        return paths
    finally:
        if presentation is not None:
            try:
                presentation.Close()
            except Exception:
                pass


def export_slides(ppt_path: Path, out_dir: Path) -> list[Path]:
    errors: list[str] = []
    with _EXPORT_LOCK:
        for progid in (PROG_POWERPOINT, PROG_WPS):
            try:
                app, _created = _get_app(progid)
                return _export_with_app(app, ppt_path, out_dir)
            except ExportError:
                raise
            except Exception as exc:
                with _APPS_LOCK:
                    held = _APPS.pop(progid, None)
                if held and held[1]:
                    _quit_app(held[0])
                errors.append(f"{progid}: {exc}")
        raise ExportError(
            "无法导出幻灯片，需要可用的 Microsoft PowerPoint 或 WPS。"
            + " ".join(errors)
        )
