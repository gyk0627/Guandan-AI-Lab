"""人机对战界面的端到端测试。

不启动真实浏览器，也不依赖神经网络：用启发式策略在本地端口上跑完整流程。
服务端持有全部状态，所以这里测的是「HTTP 接口 + 规则校验」这条链。
"""

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

from interface.web_server import create_server


@contextmanager
def running_server(log_dir=None, **kwargs):
    """起一个真实的本地服务。

    默认把对局日志写到仓库内的临时目录并自动清理——
    否则每跑一次测试往 replay/ 里多一个 human_*.jsonl，很快就没法看了。
    """
    import shutil
    import uuid
    from pathlib import Path

    owned = log_dir is None

    if owned:
        log_dir = (
            Path(__file__).resolve().parent.parent
            / ".test_tmp"
            / f"srv_{uuid.uuid4().hex}"
        )
        log_dir.mkdir(parents=True, exist_ok=True)

    server = create_server(port=0, use_neural=False, log_dir=log_dir, **kwargs)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

        if owned:
            shutil.rmtree(log_dir, ignore_errors=True)


def get(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status, response.read().decode("utf-8")


def post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_index_page_is_served():
    with running_server(seed=1, level="2") as base:
        status, html = get(base + "/")

        assert status == 200
        assert "掼蛋" in html
        assert "api/play" in html
        assert "导出对局" in html, "界面要有「导出对局」按钮，不会配网络的人也能把记录发回来"
        assert "发送给作者" in html, "界面要有「发送给作者」按钮，点一下就能把记录发到作者邮箱"
        assert "发送这一局给作者" in html, "打完一局的全屏弹窗里要有醒目的大按钮"
        assert "对局结束" in html
        # 同点数的牌要叠着显示，不然 27 张铺开太占地方
        assert ".card.stack" in html
        assert 'classList.add("stack")' in html
        # 打完直接发、发完自动开下一局：结束弹窗里不再放「再来一局」按钮
        assert "不想发，直接开下一局" in html
        assert "againBtn" not in html


def test_export_returns_the_latest_record():
    """点「导出对局」拿到的是这一局的 jsonl，能直接发给别人。"""
    with running_server(seed=7, level="2") as base:
        _, state = get_json(base + "/api/state")
        post(base + "/api/play", {"cards": [state["hand"][0]]})

        request = urllib.request.Request(base + "/api/export")
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            disposition = response.headers.get("Content-Disposition", "")

    rows = [json.loads(line) for line in body.splitlines() if line.strip()]
    assert rows[0]["event"] == "game_start"
    assert any(row["event"] == "turn" for row in rows)
    assert "attachment" in disposition
    assert "human_" in disposition and ".jsonl" in disposition


def test_export_post_saves_the_file_and_reports_the_path():
    """窗口版没有下载框，所以由服务端直接存到「下载」并回报路径。"""
    import os

    from pathlib import Path

    target = Path(__file__).resolve().parent.parent / ".test_tmp" / "export_target"
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob("human_*.jsonl"):
        stale.unlink()

    previous = os.environ.get("GUANDAN_EXPORT_DIR")
    os.environ["GUANDAN_EXPORT_DIR"] = str(target)
    try:
        with running_server(seed=11, level="2") as base:
            _, state = get_json(base + "/api/state")
            post(base + "/api/play", {"cards": [state["hand"][0]]})
            status, result = post(base + "/api/export", {})
    finally:
        if previous is None:
            os.environ.pop("GUANDAN_EXPORT_DIR", None)
        else:
            os.environ["GUANDAN_EXPORT_DIR"] = previous

    assert status == 200
    saved = Path(result["saved"])
    assert saved.exists()
    assert saved.parent == target
    assert saved.name.startswith("human_") and saved.suffix == ".jsonl"
    assert result["bytes"] == saved.stat().st_size > 200


def test_send_without_mail_config_packs_a_zip_for_manual_delivery():
    """没配邮箱时不报错：打成一个 zip 存到「下载」，并把路径告诉玩家。"""
    import os

    from pathlib import Path

    target = Path(__file__).resolve().parent.parent / ".test_tmp" / "send_target"
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob("guandan_*.zip"):
        stale.unlink()

    previous = os.environ.get("GUANDAN_EXPORT_DIR")
    os.environ["GUANDAN_EXPORT_DIR"] = str(target)
    try:
        # home 指向一个没有 mail.json 的目录 = 离线版
        with running_server(seed=13, level="2", home=target) as base:
            _, state = get_json(base + "/api/state")
            post(base + "/api/play", {"cards": [state["hand"][0]]})
            status, result = post(base + "/api/send", {})
    finally:
        if previous is None:
            os.environ.pop("GUANDAN_EXPORT_DIR", None)
        else:
            os.environ["GUANDAN_EXPORT_DIR"] = previous

    assert status == 200
    assert result["sent"] is False
    assert "没有配置收件邮箱" in result["reason"]
    saved = Path(result["saved"])
    assert saved.exists() and saved.suffix == ".zip"
    assert saved.parent == target
    import zipfile

    with zipfile.ZipFile(saved) as archive:
        assert any(name.startswith("human_") for name in archive.namelist())


def test_initial_state():
    with running_server(seed=1, level="2") as base:
        _, state = get_json(base + "/api/state")

        assert state["your_seat"] == 0
        assert state["your_team"] == "A"
        assert len(state["hand"]) == 27
        assert state["hand_counts"][0] == 27
        assert state["level_text"] == "打 2"
        # 人先手，所以一开始就轮到人
        assert state["your_turn"] is True
        assert state["can_pass"] is False
        assert state["game_over"] is False


def get_json(url):
    status, body = get(url)
    return status, json.loads(body)


def test_illegal_play_is_rejected():
    with running_server(seed=1, level="2") as base:
        _, state = get_json(base + "/api/state")

        # 三张不同点数的牌不是合法牌型
        cards = [c for c in state["hand"][:3]]

        status, result = post(base + "/api/play", {"cards": cards})

        assert status == 400
        assert result["error"]
        assert len(result["hand"]) == 27, "非法出牌不能改变手牌"


def test_pass_while_leading_is_rejected():
    with running_server(seed=1, level="2") as base:
        status, result = post(base + "/api/pass", {})

        assert status == 400
        assert "领出" in result["error"]


def test_legal_single_is_accepted():
    with running_server(seed=1, level="2") as base:
        _, state = get_json(base + "/api/state")

        card = state["hand"][0]
        status, result = post(base + "/api/play", {"cards": [card]})

        assert status == 200
        assert card not in result["hand"]
        assert len(result["hand"]) == 26


def test_full_game_reaches_game_over():
    """一路打到结束：每步都选第一个提示的牌，或过牌。"""
    with running_server(seed=7, level="2") as base:
        _, state = get_json(base + "/api/state")
        rounds = 0

        while not state["game_over"]:
            rounds += 1
            assert rounds < 400, "对局没有正常结束"

            if not state["your_turn"]:
                status, state = get_json(base + "/api/state")
                continue

            if state["can_pass"]:
                status, state = post(base + "/api/pass", {})
            else:
                _, legal = get_json(base + "/api/legal")
                assert legal["plays"], "领出阶段必须有合法出牌"
                status, state = post(base + "/api/play", {"cards": legal["plays"][0]})

            assert status == 200, state.get("error")

        assert sorted(state["ranking"]) == [0, 1, 2, 3]
        assert len(state["finished"]) == 4


def test_new_game_resets():
    with running_server(seed=1, level="2") as base:
        _, state = get_json(base + "/api/state")
        post(base + "/api/play", {"cards": [state["hand"][0]]})

        status, fresh = post(base + "/api/new", {"level": "7"})

        assert status == 200
        assert fresh["level_text"] == "打 7"
        assert len(fresh["hand"]) == 27
        assert fresh["game_over"] is False


def test_legal_endpoint_returns_plays():
    with running_server(seed=3, level="2") as base:
        _, data = get_json(base + "/api/legal")

        assert data["plays"]
        assert all(isinstance(play, list) and play for play in data["plays"])


# ==================== 前端选牌的身份问题 ====================


def test_page_selects_cards_by_index_not_text():
    """两副牌里两张大王文本都是 BJ。

    如果前端用牌面文本记录选中状态，点一张大王会把两张一起选上——
    这是实际发生过的 bug，所以用静态断言把它钉死。
    """
    from pathlib import Path

    html = (
        Path(__file__).resolve().parent.parent / "interface" / "index.html"
    ).read_text(encoding="utf-8")

    assert "selected.has(index)" in html, "选中状态必须按手牌下标记录"
    assert "selected.has(text)" not in html, "不能按牌面文本记录选中状态"
    assert "let selected = new Set();" in html


def test_page_clears_selection_only_on_new_state():
    """本地点选只重绘，不能清空选择；只有收到新状态才清。"""
    from pathlib import Path

    html = (
        Path(__file__).resolve().parent.parent / "interface" / "index.html"
    ).read_text(encoding="utf-8")

    assert "function applyState(next, keepSelection)" in html
    assert "function render()" in html


def test_seat_names_follow_turn_order():
    """出牌顺序 0→1→2→3，所以 1 号是下家、3 号是上家，不能反。"""
    from pathlib import Path

    html = (
        Path(__file__).resolve().parent.parent / "interface" / "index.html"
    ).read_text(encoding="utf-8")

    assert '1: "下家"' in html
    assert '3: "上家"' in html
    assert '1: "上家"' not in html


def test_table_shows_who_played():
    """桌面上必须写清是谁出的牌，不能只有牌面。"""
    from pathlib import Path

    html = (
        Path(__file__).resolve().parent.parent / "interface" / "index.html"
    ).read_text(encoding="utf-8")

    assert "号位）</b> 打出" in html
    assert "刚出牌" in html


@pytest.fixture
def log_dir():
    """用仓库内的临时目录，不要用系统 TEMP（沙箱里不可写）。"""
    import shutil
    import uuid
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)

    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_every_game_is_logged(log_dir):
    """关掉窗口也要能复盘：每一手都必须落盘。"""
    with running_server(seed=5, level="2", log_dir=log_dir) as base:
        _, state = get_json(base + "/api/state")

        assert state["log_name"].startswith("human_")

        post(base + "/api/play", {"cards": [state["hand"][0]]})

        files = list(log_dir.glob("human_*.jsonl"))
        assert len(files) == 1

        records = [
            json.loads(line)
            for line in files[0].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    assert records[0]["event"] == "game_start"
    assert records[0]["level"] == "2", "开头必须记下打几，否则复盘只能靠猜"

    turns = [record for record in records if record["event"] == "turn"]

    assert turns, "至少要记录一手"
    assert all("hand_before" in turn and "action_type" in turn for turn in turns)
    assert any(turn["player"] == 0 for turn in turns), "人的动作也要记录"


def test_snapshot_marks_wildcard_and_partner_lead():
    """界面要能标出逢人配（红桃级牌），也要知道是不是队友领出。"""
    with running_server(seed=31, level="Q") as base:
        _, state = get_json(base + "/api/state")

    assert state["wildcard_text"] == "H:Q"
    assert state["partner_leads"] is False
    assert isinstance(state["partner_leads"], bool)


def test_no_wildcard_without_level():
    with running_server(seed=32, level=None) as base:
        _, state = get_json(base + "/api/state")

    assert state["wildcard_text"] is None


def test_new_game_really_replaces_the_session():
    """点「新的一局」之后，**后续请求**也必须看到新局。

    这是一次真实 bug：新对局只赋给了当前 handler 实例（self.session），
    而 http.server 每个请求都新建实例，于是后续请求读到的还是旧局，
    界面就永远停在上一局的结果上。
    """
    with running_server(seed=21, level="2") as base:
        _, first = get_json(base + "/api/state")
        post(base + "/api/play", {"cards": [first["hand"][0]]})

        _, fresh = post(base + "/api/new", {"level": "5"})

        assert fresh["level_text"] == "打 5"
        assert fresh["game_over"] is False
        assert len(fresh["hand"]) == 27
        assert fresh["seed"] != first["seed"]

        # 关键：换一个请求再看一次，必须还是新局
        _, after = get_json(base + "/api/state")

        assert after["seed"] == fresh["seed"]
        assert after["level_text"] == "打 5"
        assert after["game_over"] is False
        assert len(after["hand"]) == 27


def test_new_game_after_finishing_clears_overlay_state():
    """上一局已经结束的情况下开新局，状态里不能再是 game_over。"""
    with running_server(seed=22, level="2") as base:
        _, state = get_json(base + "/api/state")

        # 一直打到结束
        rounds = 0
        while not state["game_over"]:
            rounds += 1
            assert rounds < 400

            if not state["your_turn"]:
                _, state = get_json(base + "/api/state")
                continue

            if state["can_pass"]:
                _, state = post(base + "/api/pass", {})
            else:
                _, legal = get_json(base + "/api/legal")
                _, state = post(base + "/api/play", {"cards": legal["plays"][0]})

        assert state["game_over"] is True

        _, fresh = post(base + "/api/new", {"level": "2"})
        _, after = get_json(base + "/api/state")

    assert fresh["game_over"] is False
    assert after["game_over"] is False, "上一局的结果不能残留到新局"


def test_new_game_closes_previous_log(log_dir):
    with running_server(seed=6, level="2", log_dir=log_dir) as base:
        _, state = get_json(base + "/api/state")
        post(base + "/api/play", {"cards": [state["hand"][0]]})
        post(base + "/api/new", {"level": "3"})

        files = list(log_dir.glob("human_*.jsonl"))
        assert len(files) == 2, "开新局要另起一个日志文件"

        last_events = []

        for path in files:
            records = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            last_events.append(records[-1]["event"])

    # 旧的那一局必须被收尾；新开的那局还没打过牌，自然只有 game_start
    assert last_events.count("game_end") == 1
    assert "game_start" in last_events


def test_new_game_does_not_keep_an_empty_log(log_dir):
    """一手没打就点「新的一局」，不该在 replay/ 里留下空壳日志。

    服务端启动时会先建一个默认会话（也就是先落一个日志文件），
    用户一进来就点新局的话，这个文件只有 game_start/game_end 两行，
    堆久了 replay/ 里全是这种 200 字节的垃圾。
    """
    with running_server(seed=31, level="2", log_dir=log_dir) as base:
        # 只看状态、不出牌：默认会话一手都没动过
        _, state = get_json(base + "/api/state")
        assert state["history"] == []

        before = list(log_dir.glob("human_*.jsonl"))
        assert len(before) == 1

        _, fresh = post(base + "/api/new", {"level": "2"})
        after = list(log_dir.glob("human_*.jsonl"))

    assert fresh["game_over"] is False
    assert len(after) == 1, "空壳日志应该被删掉，只留下新开的那局"
    assert after[0].name not in {path.name for path in before}


def test_log_callback_fires_when_game_ends(log_dir):
    """每局打完通知一次（上传器就靠这个把记录排进队列）。"""
    seen = []

    with running_server(seed=41, level="2", log_dir=log_dir, on_log_ready=seen.append) as base:
        state = post(base + "/api/new", {"level": "2"})[1]
        steps = 0
        while not state["game_over"]:
            steps += 1
            assert steps < 400
            _, hint = get_json(base + "/api/legal")
            moves = hint.get("plays") or []
            if moves:
                _, state = post(base + "/api/play", {"cards": moves[0]})
            else:
                _, state = post(base + "/api/pass", {})

    assert len(seen) == 1
    path = Path(seen[0])
    assert path.exists()
    assert sum(1 for _ in path.open(encoding="utf-8")) > 10
