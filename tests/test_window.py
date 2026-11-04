"""应用窗口（interface/window.py）的测试：只验证路径查找与参数组装，不真的弹窗。"""

import sys
from pathlib import Path

import interface.window as window


def test_window_args_look_like_an_app_window():
    args = window.window_args("msedge.exe", "http://127.0.0.1:8765/", Path("C:/tmp/profile"))
    assert args[0] == "msedge.exe"
    assert "--app=http://127.0.0.1:8765/" in args
    assert any(arg.startswith("--user-data-dir=") for arg in args)
    assert "--window-size=1280,900" in args
    assert "--no-first-run" in args


def test_window_args_respects_size():
    args = window.window_args("msedge.exe", "http://x/", "C:/tmp/p", width=900, height=700)
    assert "--window-size=900,700" in args


def test_find_edge_returns_existing_path_or_none():
    edge = window.find_edge()
    if sys.platform == "win32":
        assert edge is None or Path(edge).exists()
        if edge is not None:
            assert edge.lower().endswith("msedge.exe")
    else:
        assert edge is None


def test_host_shell_is_shipped_with_the_three_dlls():
    """内嵌窗口依赖这四件套；少一件就只能退回 Edge 应用模式。"""
    host = window.find_host()
    assert host is not None, "没有 interface/window_host/GuandanWindow.exe"
    for name in (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
        "WebView2Loader.dll",
    ):
        assert (host.parent / name).exists(), f"缺少 {name}"


def test_open_window_prefers_the_host_shell(monkeypatch, workdir):
    calls = []

    class FakeProcess:
        pass

    monkeypatch.setattr(window, "find_host", lambda: Path("host/GuandanWindow.exe"))
    monkeypatch.setattr(window, "find_edge", lambda: "msedge.exe")
    monkeypatch.setattr(window, "_spawn", lambda argv, cwd=None: calls.append((argv, cwd)) or FakeProcess())

    process, kind = window.open_window("http://127.0.0.1:8765/", workdir / "profile")

    assert kind == "host"
    assert isinstance(process, FakeProcess)
    argv, cwd = calls[0]
    assert argv[0] == str(Path("host/GuandanWindow.exe"))
    assert argv[1] == "http://127.0.0.1:8765/"
    assert argv[3] == "0"  # 默认不开调试端口
    assert cwd == str(Path("host"))


def test_open_window_falls_back_to_edge(monkeypatch, workdir):
    monkeypatch.setattr(window, "find_host", lambda: None)
    monkeypatch.setattr(window, "find_edge", lambda: "msedge.exe")
    monkeypatch.setattr(window, "_spawn", lambda argv, cwd=None: object())

    process, kind = window.open_window("http://127.0.0.1:8765/", workdir / "profile")

    assert kind == "edge"
    assert process is not None


def test_open_window_reports_nothing_available(monkeypatch, workdir):
    monkeypatch.setattr(window, "find_host", lambda: None)
    monkeypatch.setattr(window, "find_edge", lambda: None)

    process, kind = window.open_window("http://127.0.0.1:8765/", workdir / "profile")

    assert process is None
    assert kind is None
