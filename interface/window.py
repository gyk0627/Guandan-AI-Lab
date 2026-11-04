"""把游戏装进一个「应用窗口」。

打包成 exe 后不弹浏览器标签页，而是用系统自带的 Edge 内核开一个**没有地址栏、
没有标签页**的独立窗口（应用模式）。它和浏览器共用渲染引擎，但用户看到的只是一个
窗口，像普通软件一样双击就有、关掉就退。

找不到 Edge 就退回默认浏览器，保证在任何 Windows 上都能玩。
"""

import os
import subprocess
import sys
from pathlib import Path

EDGE_NAMES = ("msedge.exe", "msedge.exe")

# Edge 的常见安装位置（注册表里也能查到，但直接找更省事）
EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


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


def open_window(url, profile_dir, width=1280, height=900):
    """开一个应用窗口，返回进程对象；找不到 Edge 返回 None。"""
    edge = find_edge()
    if edge is None:
        return None
    profile = Path(profile_dir)
    profile.mkdir(parents=True, exist_ok=True)
    arguments = window_args(edge, url, profile, width=width, height=height)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(  # noqa: S603 - 路径来自本机已知位置
        arguments,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
