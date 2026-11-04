"""人类偏好标注工具（tools/review_server.py）的测试。

覆盖：
* 记录解析：拒绝没有 seed / 没有 turn 的记录；
* 重放：自动识别级牌、级牌不对时明确报错；
* 决策点：A 是真人动作、B 是同一局面的合法动作、A/B 不重复、生成确定；
* 落盘：JSONL 字段格式、同一 (game, step) 覆盖而不是追加、坏行容忍；
* HTTP：首页 / API / 提交偏好 / 错误码。
"""

import json
import threading
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest

from tools.review_server import (
    PreferenceStore,
    ReviewBadRequest,
    ReviewError,
    ReviewNotFound,
    ReviewSession,
    build_decisions,
    default_record_file,
    make_server,
    read_replay,
)

REPO = Path(__file__).resolve().parent.parent
FAST_FILE = REPO / "replay" / "human_20261104_200237_705470.jsonl"
Q_FILE = REPO / "replay" / "human_20261102_235032_211876.jsonl"
HTML_FILE = REPO / "interface" / "review.html"


# ---------------------------------------------------------------------------
# 工具函数


def make_session(workdir, record=FAST_FILE, **kwargs):
    return ReviewSession(
        record,
        out_path=workdir / "preferences.jsonl",
        html_path=HTML_FILE,
        **kwargs,
    )


def copy_with_level(workdir, record, level):
    """复制一份记录，并在 game_start 里补上级牌（模拟新版 exe 写出的日志）。"""
    rows = [
        json.loads(line)
        for line in Path(record).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows[0]["level"] = level
    path = workdir / f"with_level_{level}.jsonl"
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def as_tuples(cards):
    """JSON 里的牌（list / str）转回引擎用的 tuple / str。"""
    return [tuple(card) if isinstance(card, list) else card for card in cards]


def card_key(cards):
    return tuple(sorted(map(repr, as_tuples(cards))))


def write_jsonl(path, rows):
    body = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(body, encoding="utf-8")


def http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def http_post(url, payload):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# 记录解析


def test_read_replay_rejects_unusable_records(workdir):
    no_seed = workdir / "human_none.jsonl"
    write_jsonl(no_seed, [
        {"event": "game_start", "seed": None, "time": "2026-11-04T20:00:00"},
        {"event": "game_end"},
    ])
    with pytest.raises(ReviewError, match="seed"):
        read_replay(no_seed)

    no_turn = workdir / "human_empty.jsonl"
    write_jsonl(no_turn, [
        {"event": "game_start", "seed": 123, "time": "2026-11-04T20:00:00"},
        {"event": "game_end"},
    ])
    with pytest.raises(ReviewError, match="turn"):
        read_replay(no_turn)

    empty = workdir / "human_blank.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ReviewError, match="空文件"):
        read_replay(empty)

    with pytest.raises(ReviewError):
        read_replay(workdir / "missing.jsonl")


def test_read_replay_returns_start_and_rows():
    start, rows = read_replay(FAST_FILE)
    assert start["event"] == "game_start"
    assert isinstance(start["seed"], int)
    turns = [row for row in rows if row.get("event") == "turn"]
    assert len(turns) > 50


# ---------------------------------------------------------------------------
# 重放与级牌


def test_auto_level_detection_and_forced_wrong_level(workdir):
    session = make_session(workdir, Q_FILE)
    assert session.level == "Q"
    assert session.stats()["total"] > 0

    # 这份记录在级牌 2 下第 16 步就不合法；强制错级牌必须报错而不是硬编。
    with pytest.raises(ReviewError, match="级牌"):
        make_session(workdir, Q_FILE, level="2")


def test_auto_level_is_two_for_fast_file(workdir):
    session = make_session(workdir)
    assert session.level == "2"
    assert session.turn_count > 0
    assert session.stats()["level"] == "2"


def test_recorded_level_is_used_directly(workdir):
    """新记录在 game_start 里写了级牌，就不该再靠「逐个试」去猜。"""
    record = copy_with_level(workdir, Q_FILE, "Q")
    session = make_session(workdir, record)
    assert session.level == "Q"
    assert session.stats()["total"] > 0


def test_recorded_level_that_conflicts_is_still_rejected(workdir):
    """记录里写错了级牌就明确报错，不许静默按错的级牌重放。"""
    record = copy_with_level(workdir, Q_FILE, "2")
    with pytest.raises(ReviewError, match="级牌"):
        make_session(workdir, record)


# ---------------------------------------------------------------------------
# 决策点


def test_decisions_a_is_human_action_b_is_legal_and_distinct(workdir):
    session = make_session(workdir)
    items = session.items
    assert items, "这份记录应该有可标注的决策点"
    assert len(items) == session.stats()["total"]

    snapshots = {snapshot["turn"]: snapshot for snapshot in session.snapshots}
    assert len({item["step"] for item in items}) == len(items)

    for item in items:
        snapshot = snapshots[item["step"]]
        legal_keys = {card_key(move) for move in snapshot["legal"]}

        # A 必须精确等于真人的动作（过牌 → []）
        if snapshot["action"] is None:
            assert item["a"] == []
            assert item["a_is_pass"] is True
            assert item["a_label"] == "过牌"
        else:
            assert as_tuples(item["a"]) == list(snapshot["action"])
            assert item["a_is_pass"] is False

        # B 必须是引擎在同一局面给出的合法动作，且不能和 A 一样
        assert item["b_is_pass"] is (item["b"] == [])
        if item["b_is_pass"]:
            assert snapshot["previous_play"] is not None
        else:
            assert card_key(item["b"]) in legal_keys
        assert card_key(item["a"]) != card_key(item["b"])
        assert item["a_label"] and item["b_label"]

        # 手牌张数与快照一致
        assert item["hand_count"] == len(snapshot["hand_before"])
        assert len(item["hand"]) == len(snapshot["hand_before"])


def test_decisions_are_deterministic(workdir):
    session = make_session(workdir)
    again = build_decisions(session.snapshots, session.start["seed"])
    assert [item["b"] for item in again] == [item["b"] for item in session.items]
    assert [item["step"] for item in again] == [item["step"] for item in session.items]


def test_decisions_skip_steps_without_alternatives(workdir):
    """每一步都至少有一个和 A 不同的合法动作，否则就不该出现在列表里。"""
    session = make_session(workdir)
    for item in session.items:
        snapshot = {snap["turn"]: snap for snap in session.snapshots}[item["step"]]
        alternatives = [
            move for move in snapshot["legal"]
            if card_key(move) != card_key(item["a"])
        ]
        assert alternatives or (item["a"] != [] and snapshot["previous_play"] is not None)


def test_api_payload_is_json_serializable(workdir):
    session = make_session(workdir)
    payload = session.api_payload()
    text = json.dumps(payload, ensure_ascii=False)
    assert json.loads(text)["total"] == len(session.items)
    assert all("label" in item for item in payload["items"])


# ---------------------------------------------------------------------------
# 偏好文件


def test_store_upsert_overwrites_same_step(workdir):
    path = workdir / "preferences.jsonl"
    store = PreferenceStore(path)

    first = {"game": "human_a.jsonl", "step": 3, "chosen": "A",
             "a": [["S", "8"]], "b": [["H", "9"]], "time": "2026-11-04T20:00:00+08:00"}
    store.upsert(first)
    second = dict(first, chosen="tie")
    stored, replaced = store.upsert(second)
    assert replaced is True
    assert stored["chosen"] == "tie"

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert set(record) == {"game", "step", "chosen", "a", "b", "time"}
    assert record["chosen"] == "tie"

    # 重新加载：覆盖后的内容应当被读到
    reloaded = PreferenceStore(path)
    assert reloaded.lookup("human_a.jsonl", 3)["chosen"] == "tie"
    assert reloaded.labels_for("human_a.jsonl") == {3: "tie"}


def test_store_keeps_games_separate(workdir):
    path = workdir / "preferences.jsonl"
    store = PreferenceStore(path)
    base = {"step": 1, "chosen": "A", "a": [], "b": [["C", "3"]], "time": "t"}
    store.upsert(dict(base, game="human_a.jsonl"))
    store.upsert(dict(base, game="human_b.jsonl"))
    store.upsert(dict(base, game="human_a.jsonl", chosen="tie"))

    assert store.count() == 2
    assert store.labels_for("human_a.jsonl") == {1: "tie"}
    assert store.labels_for("human_b.jsonl") == {1: "A"}


def test_store_tolerates_corrupt_lines(workdir):
    path = workdir / "preferences.jsonl"
    good = {"game": "human_a.jsonl", "step": 2, "chosen": "B",
            "a": [], "b": [["D", "K"]], "time": "2026-11-04T20:00:00+08:00"}
    write_jsonl(path, [good])
    with path.open("a", encoding="utf-8") as handle:
        handle.write("这不是 JSON\n")
        handle.write('{"game": "human_a.jsonl"}\n')

    store = PreferenceStore(path)
    assert store.load_errors == 2
    assert store.lookup("human_a.jsonl", 2)["chosen"] == "B"


# ---------------------------------------------------------------------------
# 会话写入校验


def test_record_preference_validates_and_overwrites(workdir):
    session = make_session(workdir)
    item = session.items[0]
    valid = {
        "game": session.game,
        "step": item["step"],
        "chosen": "A",
        "a": item["a"],
        "b": item["b"],
    }

    with pytest.raises(ReviewBadRequest):
        session.record_preference(dict(valid, chosen="X"))
    with pytest.raises(ReviewBadRequest):
        session.record_preference(dict(valid, game="other.jsonl"))
    with pytest.raises(ReviewBadRequest):
        session.record_preference(dict(valid, a=[] if item["a"] else [["S", "3"]]))
    with pytest.raises(ReviewNotFound):
        session.record_preference(dict(valid, step=99999))

    result = session.record_preference(valid)
    assert result["ok"] is True
    assert result["replaced"] is False
    assert result["labeled"] == 1
    assert result["total"] == len(session.items)

    record = json.loads((workdir / "preferences.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record["game"] == session.game
    assert record["step"] == item["step"]
    assert record["chosen"] == "A"
    assert record["a"] == item["a"]
    assert record["b"] == item["b"]
    datetime.fromisoformat(record["time"])

    again = session.record_preference(dict(valid, chosen="tie"))
    assert again["replaced"] is True
    assert again["labeled"] == 1
    lines = [
        line for line in (workdir / "preferences.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert json.loads(lines[0])["chosen"] == "tie"

    payload = session.api_payload()
    labels = {row["step"]: row["label"] for row in payload["items"]}
    assert labels[item["step"]] == "tie"
    assert payload["labeled"] == 1


def test_record_preference_requires_chosen_field(workdir):
    session = make_session(workdir)
    item = session.items[0]
    with pytest.raises(ReviewBadRequest):
        session.record_preference({"game": session.game, "step": item["step"]})
    with pytest.raises(ReviewBadRequest):
        session.record_preference("not a dict")


# ---------------------------------------------------------------------------
# HTTP


def test_http_page_api_and_submit(workdir):
    out_path = workdir / "preferences.jsonl"
    server = make_server(FAST_FILE, out_path=out_path, port=0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        status, body = http_get(base + "/")
        assert status == 200
        html = body.decode("utf-8")
        assert "人类偏好标注" in html
        assert "/api/items" in html
        assert "/api/preference" in html

        status, body = http_get(base + "/api/items")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["game"] == FAST_FILE.name
        assert data["total"] == len(data["items"]) > 0
        assert data["labeled"] == 0
        assert all(item["label"] is None for item in data["items"])
        first = data["items"][0]
        assert first["a_label"] and first["b_label"]

        status, body = http_get(base + "/api/stats")
        assert status == 200
        assert json.loads(body.decode("utf-8"))["total"] == data["total"]

        status, body = http_get(base + "/healthz")
        assert status == 200 and json.loads(body.decode("utf-8"))["ok"] is True

        payload = {
            "game": data["game"],
            "step": first["step"],
            "chosen": "B",
            "a": first["a"],
            "b": first["b"],
            "time": "2026-11-04T20:00:00+08:00",
        }
        status, result = http_post(base + "/api/preference", payload)
        assert status == 200
        assert result["ok"] is True
        assert result["chosen"] == "B"
        assert result["replaced"] is False
        assert result["labeled"] == 1

        # 同一决策点再提交：覆盖，文件仍然只有一行
        status, result = http_post(base + "/api/preference", dict(payload, chosen="tie"))
        assert status == 200
        assert result["replaced"] is True
        lines = [line for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 1
        stored = json.loads(lines[0])
        assert stored["chosen"] == "tie"
        assert stored["game"] == data["game"]

        # 非法选择 → 400；未知路径 → 404
        status, error = http_post(base + "/api/preference", dict(payload, chosen="maybe"))
        assert status == 400 and "chosen" in error["error"]

        status, error = http_get(base + "/nope")
        assert status == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_http_submit_without_body_is_400(workdir):
    server = make_server(FAST_FILE, out_path=workdir / "preferences.jsonl", port=0, host="127.0.0.1")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        request = urllib.request.Request(base + "/api/preference", data=b"", method="POST")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=15)
        assert excinfo.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


# ---------------------------------------------------------------------------
# 静态资源与默认值


def test_html_has_required_controls():
    html = HTML_FILE.read_text(encoding="utf-8")
    for token in (
        'id="chooseA"', 'id="chooseB"', 'id="chooseTie"',
        "/api/items", "/api/preference",
        "该玩家当时的手牌", "平局", "ArrowLeft", "ArrowRight",
    ):
        assert token in html


def test_default_record_file_is_a_real_replay():
    path = default_record_file()
    assert path.exists()
    assert path.parent == REPO / "replay"
    assert path.stat().st_size > 1000
