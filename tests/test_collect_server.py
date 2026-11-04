"""收集服务（tools/collect_server.py）的测试：收、去重、挡坏请求。"""

import base64
import json

import pytest

from tools.collect_server import Collector, make_server


def payload_for(content: bytes, name="human_1.jsonl", token=None, sha=None):
    body = {
        "device": "dev-1",
        "name": name,
        "sha256": sha if sha is not None else __import__("hashlib").sha256(content).hexdigest(),
        "bytes": len(content),
        "content": base64.b64encode(content).decode("ascii"),
    }
    if token is not None:
        body["token"] = token
    return body


def test_accept_stores_file_and_index(workdir):
    collector = Collector(workdir)
    status, message = collector.accept(payload_for(b'{"event":"turn"}\n'))
    assert (status, message) == (200, "ok")
    assert collector.received == 1
    files = [path for path in workdir.iterdir() if path.suffix == ".jsonl" and path.name != "index.jsonl"]
    assert len(files) == 1
    record = json.loads((workdir / "index.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["stored"] == files[0].name
    assert record["device"] == "dev-1"


def test_duplicate_is_not_stored_twice(workdir):
    collector = Collector(workdir)
    body = payload_for(b"same content\n")
    assert collector.accept(body)[0] == 200
    assert collector.accept(body) == (200, "duplicate")
    assert collector.duplicates == 1
    names = [path.name for path in workdir.iterdir() if path.name != "index.jsonl"]
    assert len(names) == 1


def test_wrong_token_is_rejected(workdir):
    collector = Collector(workdir, token="right")
    assert collector.accept(payload_for(b"x", token="wrong"))[0] == 403
    assert collector.accept(payload_for(b"x", token="right"))[0] == 200


def test_sha_mismatch_is_rejected(workdir):
    collector = Collector(workdir)
    status, message = collector.accept(payload_for(b"abc", sha="0" * 64))
    assert status == 400 and "sha256" in message


def test_bad_base64_and_extension_are_rejected(workdir):
    collector = Collector(workdir)
    body = payload_for(b"abc")
    body["content"] = "不是 base64"
    assert collector.accept(body)[0] == 400
    assert collector.accept(payload_for(b"abc", name="game.txt"))[0] == 400
    assert collector.accept("not a dict")[0] == 400


def test_path_traversal_is_neutralized(workdir):
    collector = Collector(workdir)
    status, _ = collector.accept(payload_for(b"abc", name="../../evil.jsonl"))
    assert status == 200
    stored = [path for path in workdir.iterdir() if path.name != "index.jsonl"]
    assert stored[0].parent == workdir
    assert ".." not in stored[0].name


def test_http_endpoints(workdir):
    import threading
    import urllib.request

    server = make_server(workdir, port=0, host="127.0.0.1", token="tok")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"
        body = payload_for(b'{"event":"game_start"}\n', token="tok")
        request = urllib.request.Request(
            f"{base}/upload",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Upload-Token": "tok"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            assert response.status == 200
        with urllib.request.urlopen(f"{base}/api/stats", timeout=5) as response:  # noqa: S310
            stats = json.loads(response.read().decode("utf-8"))
        assert stats["received"] == 1
        with urllib.request.urlopen(f"{base}/", timeout=5) as response:  # noqa: S310
            assert "掼蛋对局收集服务" in response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
