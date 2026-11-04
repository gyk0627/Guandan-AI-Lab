"""接收别人传回来的对局记录。

exe 版自带一个上传器（`interface/uploader.py`）：每局打完把 `replay/human_*.jsonl`
POST 到这里，按 sha256 去重后存盘，并追加一行索引。

在自己电脑或一台便宜的云主机上跑：

    python -m tools.collect_server --dir collected --port 8790 --token 换成一串口令

然后把 exe 旁边的 `upload.json` 写成：

    {"url": "http://这台机器的地址:8790/upload", "token": "同一串口令"}

注意：公网部署时**一定要设 token**（或者放 Nginx 后面加 HTTPS），否则谁都能往里塞文件。
"""

import argparse
import base64
import binascii
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MAX_BODY = 8 * 1024 * 1024  # 一局记录约 100KB，留足余量
DEFAULT_PORT = 8790


def _safe_name(name: str) -> str:
    """只保留文件名本身，防目录穿越。"""
    return Path(str(name)).name or "game.jsonl"


class Collector:
    """把收到的对局落到目录里，按 sha256 去重。"""

    def __init__(self, directory, token=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index_path = self.directory / "index.jsonl"
        self.token = token or None
        self.received = 0
        self.duplicates = 0
        self._known = self._load_known()

    def _load_known(self):
        known = set()
        if not self.index_path.exists():
            return known
        try:
            for line in self.index_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    known.add(json.loads(line)["sha256"])
        except (OSError, ValueError, KeyError):
            pass
        return known

    def accept(self, payload):
        """校验并落盘，返回 (HTTP 状态码, 说明)。"""
        if not isinstance(payload, dict):
            return 400, "payload 不是 JSON 对象"

        if self.token and str(payload.get("token") or "") != self.token:
            # token 也允许放在请求头里，由 handler 传进来
            return 403, "口令不对"

        name = _safe_name(payload.get("name") or "game.jsonl")
        if not name.endswith(".jsonl"):
            return 400, "只接收 .jsonl 文件"

        encoded = payload.get("content")
        if not isinstance(encoded, str):
            return 400, "缺少 content"
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            return 400, "content 不是合法 base64"

        digest = hashlib.sha256(raw).hexdigest()
        claimed = str(payload.get("sha256") or "").lower()
        if claimed and claimed != digest:
            return 400, "sha256 校验失败"

        if digest in self._known:
            self.duplicates += 1
            return 200, "duplicate"

        target = self.directory / f"{digest[:16]}_{name}"
        target.write_bytes(raw)

        record = {
            "sha256": digest,
            "stored": target.name,
            "name": name,
            "bytes": len(raw),
            "device": str(payload.get("device") or "")[:64],
            "received": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with self.index_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._known.add(digest)
        self.received += 1
        return 200, "ok"


class CollectorHandler(BaseHTTPRequestHandler):
    collector = None  # 由 make_server 设置
    server_version = "GuandanCollector/0.1"

    def log_message(self, fmt, *args):  # 别把每个请求都打到控制台
        pass

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            stats = {
                "received": self.collector.received,
                "duplicates": self.collector.duplicates,
                "directory": str(self.collector.directory),
            }
            body = (
                "<!doctype html><meta charset='utf-8'>"
                "<title>对局收集</title>"
                "<body style='font-family:system-ui;background:#0d2b22;color:#eee;padding:40px'>"
                "<h1>掼蛋对局收集服务</h1>"
                f"<p>已收 {stats['received']} 局，重复 {stats['duplicates']} 局。</p>"
                f"<p>存盘目录：<code>{stats['directory']}</code></p>"
                "</body>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/stats":
            self._json(
                200,
                {
                    "received": self.collector.received,
                    "duplicates": self.collector.duplicates,
                    "total_files": len(self.collector._known),
                },
            )
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/upload":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._json(413, {"error": "请求体大小不对"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._json(400, {"error": "不是合法 JSON"})
            return

        if self.collector.token:
            header_token = self.headers.get("X-Upload-Token")
            if header_token and not payload.get("token"):
                payload["token"] = header_token

        status, message = self.collector.accept(payload)
        self._json(status, {"status": message})


def make_server(directory, port=DEFAULT_PORT, host="0.0.0.0", token=None):
    collector = Collector(directory, token=token)

    class Handler(CollectorHandler):
        pass

    Handler.collector = collector
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.collector = collector
    return server


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="接收对局记录的服务器")
    parser.add_argument("--dir", default="collected", help="记录存到哪个目录")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--token", default=None, help="上传口令；公网部署务必设置")
    args = parser.parse_args(argv)

    server = make_server(args.dir, port=args.port, host=args.host, token=args.token)
    print(f"监听 http://{args.host}:{args.port}/upload")
    print(f"记录存到：{Path(args.dir).resolve()}")
    if not args.token:
        print("提醒：没设 --token，任何人都能往这里传文件。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
