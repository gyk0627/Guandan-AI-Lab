"""训练进度网页：把 `training/progress.py` 写的快照显示成实时页面。

两个程序分工：
- 训练进程（`training.train_bc --monitor 路径`）每 0.5 秒往文件里写一次进度；
- 这个程序起一个本地网页，每 0.8 秒读一次那个文件并刷新页面。

为什么用文件而不是进程间通信：训练和网页是两个独立进程，
文件最不容易出问题——网页晚点启动、刷新、关掉重开都不影响训练。

用法：
    # 一边看一边训（推荐，单进程，自动开浏览器）
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_with_monitor --epochs 40

    # 只看（训练在别的窗口跑）
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.train_monitor --open
"""

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from training.progress import DEFAULT_PATH, read_progress

REPO = Path(__file__).resolve().parent.parent
PAGE = REPO / "interface" / "train_monitor.html"


class MonitorHandler(BaseHTTPRequestHandler):
    """只提供两个地址：`/`（页面）和 `/api/progress`（进度 JSON）。"""

    progress_path = DEFAULT_PATH
    page_path = PAGE

    def log_message(self, format, *args):  # noqa: A002 - 标准库签名
        # 默认实现会往控制台刷每一条请求，训练日志会被淹没
        pass

    def _send(self, status, body, content_type):
        payload = body.encode("utf-8") if isinstance(body, str) else body

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html", "/monitor.html"):
            try:
                self._send(200, self.page_path.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            except OSError:
                self._send(500, "页面文件丢失：" + str(self.page_path), "text/plain; charset=utf-8")
            return

        if path == "/api/progress":
            snapshot = read_progress(self.progress_path)

            if snapshot is None:
                self._send(404, json.dumps({"status": "waiting"}, ensure_ascii=False),
                           "application/json; charset=utf-8")
                return

            self._send(200, json.dumps(snapshot, ensure_ascii=False),
                       "application/json; charset=utf-8")
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return

        self._send(404, "没有这个地址", "text/plain; charset=utf-8")


def make_server(progress_path=None, port=8766, host="127.0.0.1"):
    """建好但还没启动的服务器；port=0 时由系统分配（测试用）。"""
    handler = type(
        "BoundMonitorHandler",
        (MonitorHandler,),
        {"progress_path": Path(progress_path) if progress_path else DEFAULT_PATH},
    )

    return ThreadingHTTPServer((host, port), handler)


def start_in_background(progress_path=None, port=8766, host="127.0.0.1"):
    """起一个后台线程跑网页服务，返回 (server, url)。"""
    server = make_server(progress_path, port, host)
    thread = threading.Thread(target=server.serve_forever, name="train-monitor", daemon=True)
    thread.start()

    actual_port = server.server_address[1]

    return server, f"http://{host}:{actual_port}/"


def main(argv=None):
    parser = argparse.ArgumentParser(description="训练进度网页")
    parser.add_argument("--progress", default=None, help="进度快照文件（默认 .test_tmp/train_progress.json）")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")

    args = parser.parse_args(argv)

    try:
        server, url = start_in_background(args.progress, args.port, args.host)
    except OSError as exc:
        print(f"端口 {args.port} 起不来（可能已经开着一个了）：{exc}")
        print("换一个端口：--port 8767")
        return 2

    print("=" * 60)
    print("训练进度网页已启动")
    print("=" * 60)
    print(f"地址：{url}")
    print(f"进度文件：{args.progress or DEFAULT_PATH}")
    print("按 Ctrl+C 关闭。")
    print()

    if not args.no_open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已关闭网页服务。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
