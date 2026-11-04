"""对局记录自动回传的测试。

覆盖四件事：配置读不出来就当离线、同一个文件不重复排队、空壳日志不补传、
真的能 POST 到一个收集服务并清空队列。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from interface.uploader import Uploader, file_sha256, load_config


def make_log(directory: Path, name: str, lines: int = 20) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    rows = [json.dumps({"event": "turn", "turn": index}) for index in range(lines)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def write_config(base: Path, url: str, token: str = "t") -> Path:
    path = base / "upload.json"
    path.write_text(json.dumps({"url": url, "token": token}), encoding="utf-8")
    return path


class Receiver:
    """最小的收集服务，只记收到几次、内容对不对。"""

    def __init__(self, token="t"):
        self.token = token
        self.payloads = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if self.headers.get("X-Upload-Token") != outer.token:
                    self.send_response(403)
                    self.end_headers()
                    return
                outer.payloads.append(payload)
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/upload"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def test_missing_config_means_offline(workdir):
    uploader = Uploader(workdir / "replay", config_path=workdir / "upload.json")
    assert uploader.enabled is False
    assert uploader.start() is False


def test_config_requires_http_url(workdir):
    path = workdir / "upload.json"
    path.write_text(json.dumps({"url": "ftp://example.com"}), encoding="utf-8")
    assert load_config(path) == {}
    path.write_text(json.dumps({"url": "http://example.com/upload"}), encoding="utf-8")
    assert load_config(path)["url"] == "http://example.com/upload"


def test_enqueue_deduplicates(workdir):
    write_config(workdir, "http://127.0.0.1:1/upload")
    log_dir = workdir / "replay"
    log = make_log(log_dir, "human_1.jsonl")
    uploader = Uploader(log_dir, config_path=workdir / "upload.json")

    assert uploader.enqueue(log) is True
    assert uploader.enqueue(log) is False
    assert uploader.pending_count == 1


def test_scan_skips_empty_shell_logs(workdir):
    write_config(workdir, "http://127.0.0.1:1/upload")
    log_dir = workdir / "replay"
    make_log(log_dir, "human_shell.jsonl", lines=1)
    real = make_log(log_dir, "human_real.jsonl", lines=20)
    uploader = Uploader(log_dir, config_path=workdir / "upload.json")

    assert uploader.scan() == 1
    assert [item["path"] for item in uploader._state["pending"]] == [str(real)]


def test_upload_clears_queue_and_records_state(workdir):
    log_dir = workdir / "replay"
    log = make_log(log_dir, "human_ok.jsonl")
    with Receiver() as receiver:
        write_config(workdir, receiver.url)
        uploader = Uploader(log_dir, config_path=workdir / "upload.json", verbose=False)
        uploader.enqueue(log)
        assert uploader.upload_once(log, file_sha256(log)) is True
        assert uploader.config["url"] == receiver.url

        # 走完整的线程：队列清空、状态落盘
        uploader.start()
        try:
            for _ in range(100):
                if uploader.pending_count == 0:
                    break
                uploader._stop.wait(0.05)
        finally:
            uploader.stop()
        state = json.loads((workdir / "upload_state.json").read_text(encoding="utf-8"))
        assert state["pending"] == []
        assert file_sha256(log) in state["uploaded"]
        assert receiver.payloads and receiver.payloads[0]["sha256"] == file_sha256(log)


def test_upload_failure_keeps_file_pending(workdir):
    write_config(workdir, "http://127.0.0.1:1/upload")  # 端口 1 必然连不上
    log_dir = workdir / "replay"
    log = make_log(log_dir, "human_fail.jsonl")
    uploader = Uploader(log_dir, config_path=workdir / "upload.json", verbose=False)
    uploader.enqueue(log)
    assert uploader.upload_once(log, file_sha256(log)) is False
    assert uploader.pending_count == 1


def test_upload_missing_file_is_treated_as_done(workdir):
    write_config(workdir, "http://127.0.0.1:1/upload")
    uploader = Uploader(workdir / "replay", config_path=workdir / "upload.json")
    assert uploader.upload_once(workdir / "gone.jsonl", "0" * 64) is True


def test_device_id_is_stable(workdir):
    write_config(workdir, "http://127.0.0.1:1/upload")
    first = Uploader(workdir / "replay", config_path=workdir / "upload.json")
    second = Uploader(workdir / "replay", config_path=workdir / "upload.json")
    assert first._state["device"]
    assert first._state["device"] == second._state["device"]
