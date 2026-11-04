"""把游戏装进一个**真正的窗口**。

两条路，按优先级：

1. **内嵌窗口（首选）**：`interface/window_host/GuandanWindow.exe`，一个几十 KB 的
   C# 外壳，里面是 Windows 自带的 WebView2 控件。页面渲染在进程内，不经过浏览器的
   启动策略——所以「以管理员权限运行」也不会白屏，也没有地址栏和标签页。
2. **Edge 应用模式（兜底）**：万一 WebView2 运行时不在了，用系统 Edge 的 `--app`
   模式开一个无地址栏窗口；再不行就交给默认浏览器。

WebView2 运行时：Win11 自带；Win10 大多随 Edge 装上。真没有时，外壳会弹一个提示
并退出，`app.py` 会自动退回第 2 条路。
"""

import os
import subprocess
import sys
from pathlib import Path

EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

HOST_NAME = "GuandanWindow.exe"


def base_dir():
    """exe 里是解包目录，源码里是仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def find_host():
    """返回内嵌窗口外壳的路径；没有返回 None。"""
    candidate = base_dir() / "interface" / "window_host" / HOST_NAME
    return candidate if candidate.exists() else None


def find_edge():
    """返回 msedge.exe 的路径；找不到返回 None。"""
    for candidate in EDGE_PATHS:
        if Path(candidate).exists():
            return candidate

    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        candidate = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if candidate.exists():
            return str(candidate)

    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "msedge.exe"
        if candidate.exists():
            return str(candidate)

    return None


def window_args(edge, url, profile_dir, width=1280, height=900):
    """应用模式窗口的启动参数（单独的用户目录，避免和用户平时的 Edge 打架）。"""
    return [
        edge,
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        f"--window-size={width},{height}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2,msEdgeCollections",
    ]


def _spawn(arguments, cwd=None):
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(  # noqa: S603 - 路径来自本机已知位置
        arguments,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )


def open_window(url, profile_dir, width=1280, height=900):
    """开窗口，返回 (进程对象, 用的哪种方式)；都不可用返回 (None, None)。"""
    host = find_host()
    if host is not None:
        profile = Path(profile_dir)
        profile.mkdir(parents=True, exist_ok=True)
        process = _spawn([str(host), url, str(profile), "0"], cwd=str(host.parent))
        return process, "host"

    edge = find_edge()
    if edge is None:
        return None, None
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    arguments = window_args(edge, url, profile, width=width, height=height)
    return _spawn(arguments), "edge"
