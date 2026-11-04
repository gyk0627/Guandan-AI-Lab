"""打包相关的测试：图标、入口文件、端口回退、发布包说明。

这些测试不真的跑 PyInstaller（太慢），只保证打包脚本的输入都在位、
端口回退逻辑正确、说明文件没被写空。
"""

from pathlib import Path

import pytest

from interface import app as app_module
from tools import build_exe, package_exe

REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeServer:
    def __init__(self, port):
        self.port = port


def make_fake_module(busy_ports):
    """create_server：前几个端口抛 OSError（模拟被占用），之后成功。"""
    calls = []

    def create_server(port, level, use_neural, log_dir, on_log_ready=None):
        calls.append(
            {
                "port": port,
                "level": level,
                "use_neural": use_neural,
                "log_dir": log_dir,
                "on_log_ready": on_log_ready,
            }
        )
        if port in busy_ports:
            raise OSError(f"端口 {port} 被占用")
        return FakeServer(port)

    return type("FakeWebServer", (), {"create_server": staticmethod(create_server)}), calls


def test_entry_and_web_page_exist():
    assert build_exe.ENTRY.exists(), f"缺少入口：{build_exe.ENTRY}"
    assert build_exe.DATA_FILE.exists(), f"缺少网页：{build_exe.DATA_FILE}"


def test_icon_is_a_real_ico():
    assert build_exe.ICON_FILE.exists(), "缺少图标"
    header = build_exe.ICON_FILE.read_bytes()[:4]
    assert header == b"\x00\x00\x01\x00", "不是合法的 ico 文件头"


def test_big_frameworks_are_excluded():
    # 打包版用启发式，不需要 torch / numpy；排除它们体积才压得住
    for module in ("torch", "numpy", "pandas"):
        assert module in build_exe.EXCLUDES


def test_application_dir_points_at_repo_root_when_running_from_source():
    assert app_module.application_dir() == REPO_ROOT


def test_pick_port_skips_busy_ports():
    fake, calls = make_fake_module(busy_ports={8765, 8766})
    server, port = app_module.pick_port(fake, 8765, "7", Path(".test_tmp"))
    assert port == 8767
    assert server.port == 8767
    assert [call["port"] for call in calls] == [8765, 8766, 8767]
    assert all(call["use_neural"] is False for call in calls)
    assert all(call["level"] == "7" for call in calls)


def test_pick_port_gives_up_with_readable_error():
    fake, _ = make_fake_module(busy_ports=set(range(8765, 8790)))
    with pytest.raises(SystemExit) as error:
        app_module.pick_port(fake, 8765, "2", Path(".test_tmp"))
    assert "端口" in str(error.value)


def test_release_readme_mentions_how_to_start():
    text = package_exe.README
    for keyword in ("解压", "双击", "GuandanAI.exe", "浏览器"):
        assert keyword in text


def test_wait_until_ready_detects_a_live_server():
    """服务能应答时立刻返回 True（避免 Edge 开白页）。"""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - 标准库要求这个名字
            body = b'{"level": "2"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        assert app_module.wait_until_ready(url, timeout=3.0) is True
    finally:
        server.shutdown()
        server.server_close()


def test_wait_until_ready_gives_up_quickly_on_a_dead_port():
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    # 端口已经释放，没有服务在听
    assert app_module.wait_until_ready(f"http://127.0.0.1:{free_port}/", timeout=0.3) is False
