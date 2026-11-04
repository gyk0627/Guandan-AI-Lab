"""应用窗口（interface/window.py）的测试：只验证参数组装和 Edge 查找，不真的弹窗。"""

import sys
from pathlib import Path

from interface.window import find_edge, window_args


def test_window_args_look_like_an_app_window():
    args = window_args("msedge.exe", "http://127.0.0.1:8765/", Path("C:/tmp/profile"))
    assert args[0] == "msedge.exe"
    assert "--app=http://127.0.0.1:8765/" in args
    assert any(arg.startswith("--user-data-dir=") for arg in args)
    assert "--window-size=1280,900" in args
    assert "--no-first-run" in args


def test_window_args_respects_size():
    args = window_args("msedge.exe", "http://x/", "C:/tmp/p", width=900, height=700)
    assert "--window-size=900,700" in args


def test_find_edge_returns_existing_path_or_none():
    edge = find_edge()
    if sys.platform == "win32":
        # 这台机器装了 Edge；即使没有，也必须是 None 而不是乱码路径
        assert edge is None or Path(edge).exists()
        if edge is not None:
            assert edge.lower().endswith("msedge.exe")
    else:
        assert edge is None
