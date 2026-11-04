"""对局记录自动回传。

每局打完，把 `replay/human_*.jsonl` 传到指定服务器；没网就排队，下次启动接着传。
服务器地址放在 exe 旁边的 `upload.json`：

    {
      "url": "https://example.com/upload",
      "token": "一串约定好的口令"
    }

没有这个文件、或者 url 为空，就什么都不做（完全离线）。
上传失败绝不打断游戏；所有状态记在 `upload_state.json` 里，可按 sha256 去重。
"""

import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

CONFIG_NAME = "upload.json"
STATE_NAME = "upload_state.json"
MAX_RETRY_SECONDS = 300.0
MIN_COMPLETE_LINES = 10


def load_config(path):
    """读配置；文件不存在或格式不对都当作「不上传」。"""
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    url = data.get("url") or ""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return {}
    return {
        "url": url,
        "token": str(data.get("token") or ""),
        "timeout": float(data.get("timeout") or 10.0),
    }


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class Uploader:
    """后台线程：把没传过的对局记录依次传上去。"""

    def __init__(
        self,
        log_dir,
        config_path=None,
        state_path=None,
        retry_seconds=20.0,
        verbose=True,
    ):
        self.log_dir = Path(log_dir)
        self.config_path = Path(config_path) if config_path else self.log_dir.parent / CONFIG_NAME
        self.state_path = Path(state_path) if state_path else self.log_dir.parent / STATE_NAME
        self.retry_seconds = max(1.0, float(retry_seconds))
        self.verbose = verbose

        self.config = load_config(self.config_path)
        self.enabled = bool(self.config)

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._state = self._load_state()
        if not self._state.get("device"):
            # 第一次运行：生成一个设备号并立刻落盘，否则每次重启都变一个
            self._state["device"] = uuid.uuid4().hex[:16]
            self._save_state()
        self._state.setdefault("uploaded", [])
        self._state.setdefault("pending", [])

    # ------------------------------------------------------------ 状态文件
    def _load_state(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save_state(self):
        payload = json.dumps(self._state, ensure_ascii=False, indent=1)
        temporary = self.state_path.with_suffix(".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            temporary.replace(self.state_path)
        except OSError:
            pass  # 磁盘满了也不该影响游戏

    # ------------------------------------------------------------ 排队
    def _uploaded_set(self):
        return set(self._state.get("uploaded", []))

    def enqueue(self, path):
        """登记一个要上传的文件；重复登记会被去重。"""
        if not self.enabled:
            return False
        path = Path(path)
        if not path.exists():
            return False
        try:
            digest = file_sha256(path)
        except OSError:
            return False
        with self._lock:
            if digest in self._uploaded_set():
                return False
            known = {item.get("sha") for item in self._state["pending"]}
            if digest in known:
                return False
            self._state["pending"].append({"path": str(path), "sha": digest})
            self._save_state()
        self._wake.set()
        return True

    def scan(self):
        """把目录里还没传过的历史对局也排上队（第一次运行、或者上次断网）。"""
        if not self.enabled or not self.log_dir.exists():
            return 0
        uploaded = self._uploaded_set()
        pending = {item.get("sha") for item in self._state["pending"]}
        added = 0
        for path in sorted(self.log_dir.glob("human_*.jsonl")):
            if not self._looks_complete(path):
                continue  # 空壳（刚起服务时就建了一个日志，一局没打）
            try:
                digest = file_sha256(path)
            except OSError:
                continue
            if digest in uploaded or digest in pending:
                continue
            with self._lock:
                self._state["pending"].append({"path": str(path), "sha": digest})
            pending.add(digest)
            added += 1
        if added:
            self._save_state()
            self._wake.set()
        return added

    @staticmethod
    def _looks_complete(path, min_lines=MIN_COMPLETE_LINES):
        """判断日志是不是「打过的」。空壳只有一两行，补传时别浪费流量。"""
        try:
            with open(path, encoding="utf-8") as handle:
                for index, _ in enumerate(handle, start=1):
                    if index >= min_lines:
                        return True
        except OSError:
            return False
        return False

    # ------------------------------------------------------------ 上传
    def _post(self, path, digest):
        body = {
            "device": self._state["device"],
            "name": path.name,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
        request = urllib.request.Request(
            self.config["url"],
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "GuandanAI/0.1",
            },
            method="POST",
        )
        if self.config.get("token"):
            request.add_header("X-Upload-Token", self.config["token"])
        with urllib.request.urlopen(
            request, timeout=self.config.get("timeout", 10.0)
        ) as response:  # noqa: S310 - 地址来自用户自己的配置
            return 200 <= response.status < 300

    def upload_once(self, path, digest):
        """传一个文件；成功返回 True，失败保持排队。"""
        path = Path(path)
        if not path.exists():
            return True  # 文件被删了就当作已处理
        try:
            return bool(self._post(path, digest))
        except (urllib.error.URLError, OSError, ValueError):
            return False

    # ------------------------------------------------------------ 线程
    def _loop(self):
        backoff = self.retry_seconds
        while not self._stop.is_set():
            with self._lock:
                pending = list(self._state["pending"])
            if not pending:
                self._wake.wait(timeout=self.retry_seconds)
                self._wake.clear()
                continue

            item = pending[0]
            ok = self.upload_once(item["path"], item["sha"])
            with self._lock:
                if ok:
                    self._state["uploaded"].append(item["sha"])
                    self._state["pending"] = [
                        entry for entry in self._state["pending"] if entry.get("sha") != item["sha"]
                    ]
                    self._save_state()
                    backoff = self.retry_seconds
                else:
                    backoff = min(MAX_RETRY_SECONDS, backoff * 2)
            if not ok:
                self._stop.wait(backoff)

    def start(self):
        if not self.enabled or self._thread is not None:
            return False
        self.scan()
        self._thread = threading.Thread(target=self._loop, name="uploader", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self._wake.set()

    @property
    def pending_count(self):
        with self._lock:
            return len(self._state["pending"])
