import ctypes
import shutil
import sys
from pathlib import Path

import webview

from ppt_study.api import BridgeApi, ppt_path_from_drop_event
from ppt_study.paths import APP_DISPLAY_NAME, app_data_dir

APP_USER_MODEL_ID = "PDReader.App"


def web_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "web"
    return Path(__file__).resolve().parents[2] / "web"


def app_icon_path() -> Path:
    return web_dir() / "app-icon.ico"


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def prepare_runtime_ui() -> Path:
    src = web_dir()
    dest = app_data_dir() / "ui"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "index.html",
        "styles.css",
        "app.js",
        "viz3d.js",
        "wechat-qr.jpg",
        "app-icon.png",
        "app-icon.ico",
    ):
        src_file = src / name
        if src_file.exists():
            shutil.copy2(src_file, dest / name)
    vendor_src = src / "vendor"
    if vendor_src.exists():
        vendor_dest = dest / "vendor"
        if vendor_dest.exists():
            shutil.rmtree(vendor_dest)
        shutil.copytree(vendor_src, vendor_dest)
    return dest


def bind_file_drop(window, api: BridgeApi) -> None:
    from webview.dom import DOMEventHandler

    def on_loaded() -> None:
        el = window.dom.get_element("#stage")
        if el is None:
            return

        def on_drop(event) -> None:
            path = ppt_path_from_drop_event(event)
            if path:
                api.open_from_path(path)

        el.on("dragover", DOMEventHandler(lambda e: None, prevent_default=True))
        el.on("drop", DOMEventHandler(on_drop, prevent_default=True))

    window.events.loaded += on_loaded


def main() -> None:
    _set_windows_app_id()
    api = BridgeApi()
    ui = prepare_runtime_ui()
    icon = app_icon_path()
    window = webview.create_window(
        APP_DISPLAY_NAME,
        str(ui / "index.html"),
        js_api=api,
        width=1400,
        height=900,
        min_size=(1100, 700),
    )
    api._window = window
    bind_file_drop(window, api)
    start_kw: dict = {"storage_path": str(app_data_dir() / "webview")}
    if icon.is_file():
        import inspect

        if "icon" in inspect.signature(webview.start).parameters:
            start_kw["icon"] = str(icon)
    webview.start(**start_kw)


if __name__ == "__main__":
    main()
