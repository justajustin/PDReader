from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path

from ppt_study.app_version import resolve_setup_version, save_installed_version
from ppt_study.paths import APP_DISPLAY_NAME, APP_VERSION

APP_NAME = APP_DISPLAY_NAME
PRODUCT_ID = "PDReader"
EXE_NAME = "PDReader.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PDReader"
LEGACY_APP_NAMES = ("PPT 学习伴侣", "PDF学习助手")


def payload_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "payload"
    return Path(__file__).resolve().parents[2] / "dist" / PRODUCT_ID


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local) / "Programs" / PRODUCT_ID


def normalize_install_dir(raw: str) -> Path:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("请填写安装目录")
    return Path(text).expanduser()


def suggest_install_dir_from_browse(chosen: str) -> Path:
    path = normalize_install_dir(chosen)
    if path.name.lower() != PRODUCT_ID.lower():
        path = path / PRODUCT_ID
    return path


def prepare_destination(dest: Path) -> Path:
    dest = Path(dest)
    if dest.exists() and dest.is_file():
        raise ValueError("安装路径不能是文件")
    if dest.exists() and dest.parent == dest:
        raise ValueError("请选择更具体的文件夹，不要安装到磁盘根目录")
    if dest.exists():
        has_files = any(dest.iterdir())
        if has_files and not (dest / EXE_NAME).is_file():
            raise ValueError(f"文件夹不是空的，也不是已安装的 {APP_NAME}")
    return dest


def desktop_dir() -> Path:
    return Path.home() / "Desktop"


def start_menu_dir() -> Path:
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def shortcut_path(folder: Path, name: str | None = None) -> Path:
    return folder / f"{name or APP_NAME}.lnk"


def remove_legacy_shortcuts() -> None:
    programs = start_menu_dir().parent
    for name in LEGACY_APP_NAMES:
        lnk = shortcut_path(desktop_dir(), name)
        if lnk.exists():
            lnk.unlink()
        folder = programs / name
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)


def log_path() -> Path:
    temp = os.environ.get("TEMP") or str(Path.home())
    return Path(temp) / "PDReader-setup.log"


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _taskkill_image(name: str) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/IM", name],
        capture_output=True,
        text=True,
        check=False,
    )


def _image_running(name: str) -> bool:
    completed = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    return name.lower() in out.lower()


def _kill_app_webview() -> None:
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" |"
        " Where-Object { $_.CommandLine -and"
        " ($_.CommandLine -match 'PPTStudyCompanion' -or $_.CommandLine -match 'PDReader') } |"
        " ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )


def stop_running_app(wait: float = 2.0) -> None:
    for name in (EXE_NAME, "PPTStudyCompanion.exe"):
        _taskkill_image(name)
    _kill_app_webview()
    deadline = time.time() + max(float(wait), 0.2)
    while time.time() < deadline:
        if not _image_running(EXE_NAME) and not _image_running("PPTStudyCompanion.exe"):
            time.sleep(0.4)
            return
        time.sleep(0.2)
    for name in (EXE_NAME, "PPTStudyCompanion.exe"):
        _taskkill_image(name)
    _kill_app_webview()
    time.sleep(0.5)


def _is_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in (5, 32, 33):
        return True
    errno = getattr(exc, "errno", None)
    return errno in (11, 13)


def is_existing_app_dir(dest: Path) -> bool:
    return Path(dest).is_dir() and (Path(dest) / EXE_NAME).is_file()


def is_in_app_update(argv: list[str] | None = None) -> bool:
    items = sys.argv[1:] if argv is None else argv
    return any(str(item).upper().lstrip("/-") == "FORCECLOSEAPPLICATIONS" for item in items)


def _retry_locked(action, tries: int = 20):
    last: OSError | None = None
    for attempt in range(tries):
        try:
            return action()
        except OSError as exc:
            last = exc
            if not _is_lock_error(exc) or attempt == tries - 1:
                raise
            stop_running_app(wait=0)
            time.sleep(0.35)
    if last is not None:
        raise last
    raise RuntimeError("retry failed")


def copy_payload(src: Path, dest: Path, on_progress=None) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"安装数据不存在: {src}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    overlay = is_existing_app_dir(dest)
    if dest.exists() and not overlay:
        if on_progress:
            on_progress(0, 1, "正在关闭旧程序并清理安装目录…")
        _retry_locked(lambda: shutil.rmtree(dest) if dest.exists() else None)
    dest.mkdir(parents=True, exist_ok=True)
    files = [path for path in src.rglob("*") if path.is_file()]
    total = len(files) or 1
    for index, path in enumerate(files, 1):
        target = dest / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        _retry_locked(lambda p=path, t=target: shutil.copy2(p, t))
        if on_progress and (index == 1 or index == total or index % 8 == 0):
            on_progress(index, total, path.name)


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_shortcut(path: Path, target: Path, workdir: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ws = New-Object -ComObject WScript.Shell\n"
        f"$s = $ws.CreateShortcut({_ps_quote(str(path))})\n"
        f"$s.TargetPath = {_ps_quote(str(target))}\n"
        f"$s.WorkingDirectory = {_ps_quote(str(workdir))}\n"
        f"$s.IconLocation = {_ps_quote(str(target))}\n"
        "$s.Save()\n"
    )
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "创建快捷方式失败")


def write_uninstall_scripts(install_dir: Path) -> None:
    ps1 = install_dir / "Uninstall.ps1"
    cmd = install_dir / "Uninstall.cmd"
    desktop = shortcut_path(desktop_dir())
    start = start_menu_dir()
    ps1.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = 'SilentlyContinue'",
                f"Stop-Process -Name '{PRODUCT_ID}' -Force",
                f"Remove-Item -LiteralPath {_ps_quote(str(desktop))} -Force",
                f"Remove-Item -LiteralPath {_ps_quote(str(start))} -Recurse -Force",
                f"Remove-Item -Path 'HKCU:\\{UNINSTALL_KEY}' -Recurse -Force",
                f"$app = {_ps_quote(str(install_dir))}",
                'Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "ping 127.0.0.1 -n 2 >nul & rmdir /s /q `"$app`"") -WindowStyle Hidden',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    cmd.write_text(
        "@echo off\r\n"
        'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall.ps1"\r\n',
        encoding="utf-8",
    )


def folder_size_kb(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return max(1, total // 1024)


def register_uninstall(install_dir: Path, version: str = "") -> None:
    exe = install_dir / EXE_NAME
    uninstall = install_dir / "Uninstall.cmd"
    display = str(version or APP_VERSION)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, display)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, str(uninstall))
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, str(uninstall))
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "EstimatedSize", 0, winreg.REG_DWORD, folder_size_kb(install_dir))


def remove_install_dir(install_dir: Path) -> None:
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)


def uninstall(install_dir: Path | None = None) -> None:
    dest = (install_dir or default_install_dir()).resolve()
    stop_running_app()
    shortcut = shortcut_path(desktop_dir())
    if shortcut.exists():
        shortcut.unlink()
    start = start_menu_dir()
    if start.exists():
        shutil.rmtree(start, ignore_errors=True)
    _delete_reg_tree(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    remove_install_dir(dest)


def _delete_reg_tree(root, subkey: str) -> None:
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                _delete_reg_tree(root, subkey + "\\" + child)
        winreg.DeleteKey(root, subkey)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def install(
    dest: Path,
    *,
    desktop: bool = True,
    start_menu: bool = True,
    register: bool = True,
    src: Path | None = None,
    on_status=None,
    on_progress=None,
    version: str = "",
) -> Path:
    def say(message: str) -> None:
        if on_status:
            on_status(message)

    payload = src or payload_root()
    dest = prepare_destination(Path(dest))
    installed = str(version or "").strip() or resolve_setup_version()
    log(f"install from {payload} to {dest} version {installed}")
    say("正在关闭已打开的 PDReader…")
    stop_running_app(wait=2.5)
    if is_existing_app_dir(dest):
        say("正在覆盖原安装目录，请稍候，不要关闭窗口…")
    else:
        say("正在复制文件，请稍候，不要关闭窗口…")
    copy_payload(payload, dest, on_progress=on_progress)
    write_uninstall_scripts(dest)
    target = dest / EXE_NAME
    if not target.is_file():
        raise FileNotFoundError(f"安装后未找到 {EXE_NAME}")
    say("正在创建快捷方式…")
    remove_legacy_shortcuts()
    if start_menu:
        create_shortcut(shortcut_path(start_menu_dir()), target, dest)
    if desktop:
        create_shortcut(shortcut_path(desktop_dir()), target, dest)
    if register:
        say("正在写入卸载信息…")
        register_uninstall(dest, version=installed)
    save_installed_version(installed, dest)
    say("安装完成")
    log("install finished")
    return target


def launch_app(exe: Path) -> None:
    subprocess.Popen([str(exe)], cwd=str(exe.parent), close_fds=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} 安装程序")
    parser.add_argument("--dir", dest="install_dir", help="安装目录")
    parser.add_argument("--silent", action="store_true", help="静默安装，不显示窗口")
    parser.add_argument("--uninstall", action="store_true", help="卸载")
    parser.add_argument("--no-desktop", action="store_true", help="不创建桌面快捷方式")
    parser.add_argument("--no-start-menu", action="store_true", help="不创建开始菜单快捷方式")
    parser.add_argument("--no-register", action="store_true", help="不写入卸载注册表")
    parser.add_argument("--no-launch", action="store_true", help="安装后不打开软件")
    return parser.parse_known_args(argv)[0]


def run_gui(args: argparse.Namespace, version: str = "", *, auto_install: bool = False) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    dest = normalize_install_dir(args.install_dir) if args.install_dir else default_install_dir()
    root = tk.Tk()
    root.title(f"安装 {APP_NAME}")
    root.minsize(520, 280)
    try:
        root.iconbitmap(default=str(payload_root() / EXE_NAME))
    except Exception:
        pass

    frame = ttk.Frame(root, padding=20)
    frame.grid(sticky="nsew")
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text=APP_NAME, font=("Microsoft YaHei UI", 16, "bold")).grid(
        row=0, column=0, sticky="w"
    )
    ttk.Label(
        frame,
        text="安装后可从开始菜单或桌面打开，不需要再安装 Python。\n使用前请确认本机已安装 Microsoft PowerPoint 或 WPS。",
        justify="left",
    ).grid(row=1, column=0, sticky="w", pady=(8, 12))
    ttk.Label(frame, text="安装位置（可修改或浏览选择）").grid(row=2, column=0, sticky="w")
    path_var = tk.StringVar(value=str(dest))
    path_row = ttk.Frame(frame)
    path_row.grid(row=3, column=0, sticky="ew", pady=(0, 10))
    path_row.columnconfigure(0, weight=1)
    entry = ttk.Entry(path_row, textvariable=path_var)
    entry.grid(row=0, column=0, sticky="ew")

    def browse() -> None:
        current = path_var.get().strip()
        initial = ""
        if current:
            current_path = Path(current)
            initial = str(current_path if current_path.exists() else current_path.parent)
        chosen = filedialog.askdirectory(
            parent=root,
            title="选择安装目录",
            initialdir=initial or str(default_install_dir().parent),
        )
        if chosen:
            path_var.set(str(suggest_install_dir_from_browse(chosen)))

    desktop_var = tk.BooleanVar(value=not args.no_desktop)
    launch_var = tk.BooleanVar(value=not args.no_launch)
    ttk.Checkbutton(frame, text="创建桌面快捷方式", variable=desktop_var).grid(
        row=4, column=0, sticky="w"
    )
    ttk.Checkbutton(frame, text="安装完成后打开软件", variable=launch_var).grid(
        row=5, column=0, sticky="w", pady=(0, 12)
    )
    status = tk.StringVar(
        value=(
            "正在覆盖原安装目录，请稍候，不要关闭窗口。"
            if auto_install
            else "复制文件可能需要一两分钟，窗口会显示进度，请不要强制结束。"
        )
    )
    ttk.Label(frame, textvariable=status, wraplength=460).grid(row=6, column=0, sticky="w")
    bar = ttk.Progressbar(frame, mode="indeterminate", maximum=100)
    bar.grid(row=7, column=0, sticky="ew", pady=(8, 0))

    events: queue.Queue = queue.Queue()
    busy = {"on": False}

    def set_busy(on: bool) -> None:
        busy["on"] = on
        state = ["disabled"] if on else ["!disabled"]
        install_btn.state(state)
        cancel_btn.state(state)
        browse_btn.state(state)
        entry.configure(state="disabled" if on else "normal")
        root.configure(cursor="wait" if on else "")
        if on:
            bar.configure(mode="indeterminate")
            bar.start(12)
        else:
            bar.stop()
            bar.configure(mode="determinate", value=0)

    def finish_ok(exe: Path, chosen: Path) -> None:
        set_busy(False)
        status.set("安装完成")
        bar.configure(mode="determinate", value=100)
        if launch_var.get():
            launch_app(exe)
        messagebox.showinfo(APP_NAME, f"安装完成。\n{chosen}")
        root.destroy()

    def finish_err(exc: BaseException) -> None:
        set_busy(False)
        log(f"install failed: {exc}")
        messagebox.showerror(APP_NAME, f"安装失败：{exc}")
        status.set("安装失败，可修改路径后重试。")

    def pump() -> None:
        try:
            while True:
                item = events.get_nowait()
                kind = item[0]
                if kind == "status":
                    status.set(item[1])
                elif kind == "progress":
                    done, total, name = item[1], item[2], item[3]
                    bar.stop()
                    bar.configure(mode="determinate", maximum=max(int(total), 1), value=int(done))
                    status.set(f"正在复制文件 {done}/{total}  {name}")
                elif kind == "done":
                    finish_ok(item[1], item[2])
                    return
                elif kind == "error":
                    finish_err(item[1])
                    return
        except queue.Empty:
            pass
        if busy["on"]:
            root.after(80, pump)

    def do_install() -> None:
        if busy["on"]:
            return
        try:
            chosen = prepare_destination(normalize_install_dir(path_var.get()))
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))
            return
        path_var.set(str(chosen))
        set_busy(True)
        status.set("正在安装，请稍候，不要关闭窗口…")
        root.after(80, pump)

        def work() -> None:
            try:
                exe = install(
                    chosen,
                    desktop=desktop_var.get(),
                    version=version or resolve_setup_version(),
                    on_status=lambda message: events.put(("status", message)),
                    on_progress=lambda done, total, name: events.put(("progress", done, total, name)),
                )
                events.put(("done", exe, chosen))
            except Exception as exc:
                events.put(("error", exc))

        threading.Thread(target=work, daemon=True).start()

    def on_close() -> None:
        if busy["on"]:
            return
        root.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=8, column=0, sticky="e", pady=(12, 0))
    cancel_btn = ttk.Button(buttons, text="取消", command=on_close)
    cancel_btn.grid(row=0, column=0, padx=(0, 8))
    install_btn = ttk.Button(buttons, text="安装", command=do_install)
    install_btn.grid(row=0, column=1)
    browse_btn = ttk.Button(path_row, text="浏览…", command=browse)
    browse_btn.grid(row=0, column=1, padx=(8, 0))
    root.protocol("WM_DELETE_WINDOW", on_close)
    if auto_install:
        stop_running_app(wait=1.2)
        root.after(300, do_install)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    args = parse_args(raw)
    setup_ver = resolve_setup_version(raw)
    dest = normalize_install_dir(args.install_dir) if args.install_dir else default_install_dir()
    try:
        if args.uninstall:
            uninstall(dest)
            return 0
        if args.silent:
            exe = install(
                dest,
                desktop=not args.no_desktop,
                start_menu=not args.no_start_menu,
                register=not args.no_register,
                version=setup_ver,
            )
            if not args.no_launch:
                launch_app(exe)
            return 0
        return run_gui(args, setup_ver, auto_install=is_in_app_update(raw))
    except Exception as exc:
        log(f"setup failed: {exc}")
        if args.silent or args.uninstall:
            print(f"安装失败：{exc}", file=sys.stderr)
            return 1
        try:
            import tkinter as tk
            from tkinter import messagebox

            tk.Tk().withdraw()
            messagebox.showerror(APP_NAME, f"安装失败：{exc}")
        except Exception:
            print(f"安装失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
