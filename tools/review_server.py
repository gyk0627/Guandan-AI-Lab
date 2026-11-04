"""人类偏好标注工具（RLHF 成对偏好数据收集）。

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.review_server
    # 或者指定某一局 / 输出文件 / 端口
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.review_server ^
        --file replay/human_20261104_200237_705470.jsonl --port 8795

浏览器打开 http://127.0.0.1:8795/ 后，逐决策点比较：

* A：真人在实战里当时打出的动作；
* B：用 `game_engine` 在**同一个局面**重新生成的另一个合法动作。

选 A / B / 平局（S）后写进 `replay/preferences.jsonl`（可用 --out 改）。
同一局同一步重复标注会**覆盖**旧记录，不会追加重复行。

设计要点：

1. 真人对局记录只有 `seed`，没有完整局面。这里用 `GameState.new_game(seed, level)`
   重新发牌，再严格按记录里的真人动作重放；每步都会核对
   `current_player`、`hand_before`、`previous_play`，对不上就报错而不是猜。
2. 记录里没写级牌，所以默认依次尝试 2..A / 无级牌，取第一个能完整重放通的
   级牌；也可以用 --level 手动指定。
3. A、B 都直接来自 `GameState.get_legal_moves()`，B 会排除与 A 完全相同的
   牌组，优先选不同点数组成的动作；「过牌」在跟牌阶段也是合法动作。
4. 只读真实记录，不改已有代码；服务默认只监听 127.0.0.1。
"""

import argparse
import json
import os
import random
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent

if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from game_engine.game_state import GameState  # noqa: E402
from game_engine.patterns import analyze_cards, type_label  # noqa: E402
from game_engine.ranks import (  # noqa: E402
    SUITS,
    is_joker,
    natural_value,
    rank_of,
    suit_of,
)

DEFAULT_PORT = 8795
DEFAULT_OUT = REPO / "replay" / "preferences.jsonl"
DEFAULT_HTML = REPO / "interface" / "review.html"
MAX_BODY = 256 * 1024  # 一条偏好只有几百字节，留足余量

# 记录里没有级牌字段：按 UI 下拉框顺序依次试，第一个能完整重放的即为本局级牌。
LEVEL_ORDER = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", None)

PASS = "过牌"
UNKNOWN_TYPE = "未知牌型"
RECORD_FIELDS = ("game", "step", "chosen", "a", "b", "time")

_SUIT_ORDER = {suit: index for index, suit in enumerate(SUITS)}


class ReviewError(RuntimeError):
    """记录读不了 / 重放对不上时抛这个。"""


class ReviewBadRequest(ValueError):
    """客户端提交的内容不合法。"""


class ReviewNotFound(LookupError):
    """决策点在当前对局里不存在。"""


# ---------------------------------------------------------------------------
# 记录读取与重放


def _card(value):
    """记录里的牌：花色点数对会反序列化成 tuple，大小王是字符串。"""
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


def _cards(values):
    if values is None:
        return None
    return [_card(value) for value in values]


def _serialize_cards(cards):
    if cards is None:
        return None
    return [list(card) if isinstance(card, tuple) else card for card in cards]


def _signature(cards):
    """按牌面（花色+点数）去重用的签名；过牌返回 None。"""
    if not cards:
        return None
    return tuple(sorted(map(repr, cards)))


def _rank_signature(cards):
    """只看点数的签名，用来排除「同点数换花色」这种等价动作。"""
    if not cards:
        return None
    return tuple(sorted(rank_of(card) for card in cards))


def _hand_sort_key(card):
    return (
        natural_value(rank_of(card)),
        _SUIT_ORDER.get(suit_of(card), -1),
        repr(card),
    )


def read_replay(path):
    """读一份 jsonl 记录，返回 (game_start, rows)。"""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReviewError(f"读不了记录文件 {path}：{exc}") from exc

    rows = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            raise ReviewError(f"{path.name} 第 {lineno} 行不是合法 JSON：{exc}") from exc

    if not rows:
        raise ReviewError(f"{path.name} 是空文件")

    start = rows[0]
    if not isinstance(start, dict) or start.get("event") != "game_start":
        raise ReviewError(f"{path.name} 第一行不是 game_start")

    seed = start.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ReviewError(
            f"{path.name} 没有可用的 seed（{seed!r}），无法按种子重放这局。"
            " 请换一份带 seed 的 human_*.jsonl。"
        )

    if not any(row.get("event") == "turn" for row in rows):
        raise ReviewError(f"{path.name} 里没有 turn 记录（可能只开了局就退出）")

    return start, rows


def _replay_at_level(start, rows, level):
    """按种子 + 级牌重放整局，每一步都校验记录与引擎状态一致。"""
    game = GameState.new_game(seed=start["seed"], level=level)
    snapshots = []

    for row in rows:
        if row.get("event") != "turn":
            continue

        turn = row.get("turn")
        player = row.get("player")
        if not isinstance(turn, int) or player not in (0, 1, 2, 3):
            raise ReviewError(f"第 {turn!r} 条 turn 记录字段不完整")

        if game.current_player != player:
            raise ReviewError(
                f"第 {turn} 步轮次对不上：记录是玩家 {player}，"
                f"按种子重放轮到玩家 {game.current_player}"
            )

        hand_before = _cards(row.get("hand_before"))
        if hand_before is None:
            raise ReviewError(f"第 {turn} 步缺少 hand_before")
        hand_before = sorted(hand_before, key=repr)
        if sorted(game.hands[player], key=repr) != hand_before:
            raise ReviewError(
                f"第 {turn} 步手牌对不上：记录与按种子重放的结果不一致。"
                " 这份记录可能不是用固定 seed 打的，或者引擎规则版本不同。"
            )

        previous_play = _cards(row.get("previous_play"))
        engine_previous = list(game.last_play) if game.last_play is not None else None
        if engine_previous != previous_play:
            raise ReviewError(
                f"第 {turn} 步桌面牌对不上：记录 {previous_play}，"
                f"重放得到 {engine_previous}"
            )

        legal = game.get_legal_moves(player)
        action = _cards(row.get("action"))
        action_type = row.get("action_type")

        snapshots.append({
            "turn": turn,
            "player": player,
            "team": row.get("team") or ("A" if player in (0, 2) else "B"),
            "hand_before": list(game.hands[player]),
            "previous_play": list(game.last_play) if game.last_play is not None else None,
            "previous_player": row.get("previous_player"),
            "finished_players": list(game.finished_players),
            "legal": legal,
            "action": action,
            "action_type": action_type,
            "level": level,
        })

        try:
            if action_type == "play":
                if not action:
                    raise ReviewError(f"第 {turn} 步 action_type=play 却没有 action")
                game.play(player, action)
            elif action_type == "pass":
                game.pass_turn(player)
            else:
                raise ReviewError(f"第 {turn} 步 action_type 未知：{action_type!r}")
        except ReviewError:
            raise
        except ValueError as exc:
            raise ReviewError(
                f"第 {turn} 步真人的动作按当前规则不合法（{exc}）。"
                f"当前尝试的级牌是 {level!r}，可以换 --level 再试。"
            ) from exc

    return snapshots


def load_decisions(start, rows, level=None):
    """重放整局，返回 (snapshots, 实际级牌)。

    level=None 时按 LEVEL_ORDER 依次尝试，取第一个能完整重放通的级牌。
    记录里不带级牌，所以这一步是必要的兜底。
    """
    if level is not None:
        return _replay_at_level(start, rows, level), level

    first_error = None
    for candidate in LEVEL_ORDER:
        try:
            return _replay_at_level(start, rows, candidate), candidate
        except ReviewError as exc:
            if first_error is None:
                first_error = str(exc)

    raise ReviewError(
        "按任何级牌都重放不通这份记录。"
        + (f" 默认级牌 2 的报错：{first_error}" if first_error else "")
    )


def build_decisions(snapshots, seed):
    """把重放结果变成「可标注的决策点」列表。

    只保留至少有一个「不同动作」可选的决策点；B 用固定种子生成，
    同一份记录每次打开得到的 A/B 都相同。
    """
    decisions = []

    for snapshot in snapshots:
        level = snapshot["level"]
        legal = snapshot["legal"]
        action = snapshot["action"]  # None 表示过牌
        action_sig = _signature(action)
        action_ranks = _rank_signature(action)

        # 候选：所有合法出牌里排除与 A 完全相同的牌组
        alternatives = [move for move in legal if _signature(move) != action_sig]

        # 优先排除「同点数换花色」的等价动作（对子 8♠8♥ vs 8♠8♦）
        if action_ranks is not None:
            different = [move for move in alternatives if _rank_signature(move) != action_ranks]
        else:
            different = alternatives

        choices = different or alternatives

        # 跟牌阶段「过牌」也是合法动作；领出阶段不能过
        if action is not None and snapshot["previous_play"] is not None:
            choices = list(choices) + [None]

        if not choices:
            continue

        rng = random.Random(f"{seed}:{snapshot['turn']}")
        chosen_b = rng.choice(choices)

        a_info = analyze_cards(action, level) if action else None
        b_info = analyze_cards(chosen_b, level) if chosen_b else None

        decisions.append({
            "index": len(decisions),
            "step": snapshot["turn"],
            "player": snapshot["player"],
            "team": snapshot["team"],
            "level": level,
            "hand": [
                _serialize_cards([card])[0]
                for card in sorted(snapshot["hand_before"], key=_hand_sort_key)
            ],
            "hand_count": len(snapshot["hand_before"]),
            "previous_play": _serialize_cards(snapshot["previous_play"]),
            "previous_player": snapshot["previous_player"],
            "finished_players": snapshot["finished_players"],
            "legal_play_count": len(legal),
            "a": _serialize_cards(action) or [],
            "b": _serialize_cards(chosen_b) or [],
            "a_label": type_label(a_info) if a_info else PASS,
            "b_label": type_label(b_info) if b_info else PASS,
            "a_is_pass": action is None,
            "b_is_pass": chosen_b is None,
        })

    return decisions


# ---------------------------------------------------------------------------
# 偏好落盘


class PreferenceStore:
    """把偏好记录按 (game, step) 存成 JSONL；重复标注覆盖旧行。"""

    def __init__(self, path):
        self.path = Path(path)
        self.load_errors = 0
        self._lock = threading.RLock()
        self._records = {}
        self._load()

    @staticmethod
    def _key(game, step):
        return (Path(str(game)).name, int(step))

    def _load(self):
        if not self.path.exists():
            return

        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ReviewError(f"读不了已有的偏好文件 {self.path}：{exc}") from exc

        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                key = self._key(record["game"], record["step"])
            except (ValueError, KeyError, TypeError):
                self.load_errors += 1
                continue
            self._records[key] = record

    def lookup(self, game, step):
        with self._lock:
            record = self._records.get(self._key(game, step))
            return dict(record) if record is not None else None

    def labels_for(self, game):
        """返回 {step: chosen}，给页面显示「已标注」。"""
        game = Path(str(game)).name
        with self._lock:
            return {
                key[1]: record.get("chosen")
                for key, record in self._records.items()
                if key[0] == game
            }

    def count(self):
        with self._lock:
            return len(self._records)

    def upsert(self, record):
        """写入一条记录；同一 (game, step) 覆盖，返回 (存储的记录, 是否覆盖)。"""
        missing = [field for field in RECORD_FIELDS if field not in record]
        if missing:
            raise ReviewBadRequest(f"记录缺少字段：{', '.join(missing)}")

        key = self._key(record["game"], record["step"])
        with self._lock:
            replaced = key in self._records
            self._records[key] = dict(record)
            self._flush()
        return dict(record), replaced

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        body = "".join(
            json.dumps(record, ensure_ascii=False) + "\n"
            for record in self._records.values()
        )
        tmp_path.write_text(body, encoding="utf-8")
        os.replace(tmp_path, self.path)


# ---------------------------------------------------------------------------
# 会话（解析 + 校验 + 产 API 数据）


class ReviewSession:
    """一局记录对应的标注会话，供 HTTP handler 与测试共用。"""

    def __init__(self, record_path, out_path=None, level=None, html_path=None):
        self.record_path = Path(record_path)
        self.start, self.rows = read_replay(self.record_path)
        # 新记录在 game_start 里写了级牌，直接用；老记录没写才靠重放去猜
        recorded = self.start.get("level") if isinstance(self.start, dict) else None
        if level is None and isinstance(recorded, str) and recorded in LEVEL_ORDER:
            level = recorded
        self.snapshots, self.level = load_decisions(self.start, self.rows, level=level)
        self.items = build_decisions(self.snapshots, self.start["seed"])
        self._items_by_step = {item["step"]: item for item in self.items}
        self.game = self.record_path.name

        self.store = PreferenceStore(out_path if out_path is not None else DEFAULT_OUT)
        self.html_path = Path(html_path) if html_path is not None else DEFAULT_HTML
        self.turn_count = sum(1 for row in self.rows if row.get("event") == "turn")

    # ---- 只读信息 ----

    def labels(self):
        return self.store.labels_for(self.game)

    def labeled_count(self):
        labels = self.labels()
        return sum(1 for item in self.items if item["step"] in labels)

    def stats(self):
        return {
            "game": self.game,
            "game_path": str(self.record_path),
            "level": self.level,
            "turn_count": self.turn_count,
            "total": len(self.items),
            "labeled": self.labeled_count(),
            "out": str(self.store.path),
            "html": str(self.html_path),
        }

    def api_payload(self):
        labels = self.labels()
        payload = self.stats()
        payload["items"] = [
            {**item, "label": labels.get(item["step"])}
            for item in self.items
        ]
        return payload

    # ---- 写入 ----

    def record_preference(self, payload):
        if not isinstance(payload, dict):
            raise ReviewBadRequest("提交内容不是 JSON 对象")

        game = Path(str(payload.get("game") or "")).name
        if game != self.game:
            raise ReviewBadRequest(f"game 对不上：当前记录是 {self.game}")

        try:
            step = int(payload.get("step"))
        except (TypeError, ValueError):
            raise ReviewBadRequest("step 必须是整数") from None

        chosen = payload.get("chosen")
        if chosen not in ("A", "B", "tie"):
            raise ReviewBadRequest("chosen 只能是 A / B / tie")

        item = self._items_by_step.get(step)
        if item is None:
            raise ReviewNotFound(f"第 {step} 步不在可标注的决策点里")

        # 前端回传的 a/b 只用来防页面过期：和服务器上的标准候选比对，不一致就拒。
        for field in ("a", "b"):
            if field in payload and payload[field] is not None:
                submitted = _cards(payload[field]) or []
                expected = _cards(item[field]) or []
                if sorted(map(repr, submitted)) != sorted(map(repr, expected)):
                    raise ReviewBadRequest(
                        f"{field} 与服务器上的决策点不一致（页面可能过期了，刷新重试）"
                    )

        record = {
            "game": self.game,
            "step": step,
            "chosen": chosen,
            "a": item["a"],
            "b": item["b"],
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        stored, replaced = self.store.upsert(record)

        return {
            "ok": True,
            "game": self.game,
            "step": step,
            "chosen": stored["chosen"],
            "replaced": replaced,
            "labeled": self.labeled_count(),
            "total": len(self.items),
            "out": str(self.store.path),
        }


# ---------------------------------------------------------------------------
# HTTP


class ReviewHandler(BaseHTTPRequestHandler):
    session = None  # 由 make_server 设置
    server_version = "GuandanReview/0.1"

    def log_message(self, fmt, *args):  # 标注工具不需要每个请求都刷屏
        pass

    # ---- 响应工具 ----

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status, message):
        self._json(status, {"ok": False, "error": message})

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(400, "Content-Length 不合法")
            return None

        if length <= 0:
            self._error(400, "请求体是空的")
            return None
        if length > MAX_BODY:
            self._error(413, "请求体太大")
            return None

        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._error(400, "不是合法 JSON")
            return None

    # ---- 路由 ----

    def do_GET(self):
        path = urlsplit(self.path).path

        if path in ("/", "/index.html", "/review.html"):
            try:
                body = self.session.html_path.read_bytes()
            except OSError as exc:
                self._error(500, f"读不了页面文件 {self.session.html_path}：{exc}")
                return
            self._send(200, body, "text/html; charset=utf-8")
            return

        if path == "/api/items":
            self._json(200, self.session.api_payload())
            return

        if path == "/api/stats":
            self._json(200, self.session.stats())
            return

        if path == "/healthz":
            self._json(200, {"ok": True})
            return

        self._error(404, "not found")

    def do_POST(self):
        path = urlsplit(self.path).path

        if path != "/api/preference":
            self._error(404, "not found")
            return

        payload = self._read_json()
        if payload is None:
            return

        try:
            result = self.session.record_preference(payload)
        except ReviewNotFound as exc:
            self._error(404, str(exc))
        except ReviewBadRequest as exc:
            self._error(400, str(exc))
        except OSError as exc:
            self._error(500, f"写入失败：{exc}")
        else:
            self._json(200, result)


def make_server(record_path, out_path=None, port=DEFAULT_PORT, host="127.0.0.1",
                html_path=None, level=None):
    """创建（未启动的）标注服务；port=0 时由系统挑空闲端口。"""
    session = ReviewSession(
        record_path,
        out_path=out_path,
        level=level,
        html_path=html_path,
    )

    class Handler(ReviewHandler):
        pass

    Handler.session = session
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.session = session
    return server


def default_record_file():
    """默认挑 replay 下最大的一份真人对局（决策点最多）。"""
    replay_dir = REPO / "replay"
    candidates = [
        path for path in replay_dir.glob("human_*.jsonl")
        if path.stat().st_size > 1000
    ]
    if not candidates:
        raise ReviewError(f"{replay_dir} 下没有可用的 human_*.jsonl 记录")
    return max(candidates, key=lambda path: path.stat().st_size)


def main(argv=None):
    parser = argparse.ArgumentParser(description="人类偏好标注工具（掼蛋）")
    parser.add_argument(
        "--file", default=None,
        help="要标注的真人对局记录（默认：replay 下最大的 human_*.jsonl）",
    )
    parser.add_argument(
        "--out", default=None,
        help=f"偏好写入文件（默认：{DEFAULT_OUT}）",
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--level", default=None,
        help="本局级牌（2..A）；不填则自动尝试，通常不需要手动指定",
    )
    parser.add_argument(
        "--html", default=None,
        help=f"页面文件（默认：{DEFAULT_HTML}）",
    )
    args = parser.parse_args(argv)

    record_path = Path(args.file) if args.file else default_record_file()

    try:
        server = make_server(
            record_path,
            out_path=args.out,
            port=args.port,
            host=args.host,
            html_path=args.html,
            level=args.level,
        )
    except ReviewError as exc:
        print(f"加载记录失败：{exc}", file=sys.stderr)
        return 1

    session = server.session
    stats = session.stats()
    url = f"http://{args.host}:{server.server_address[1]}/"

    print("=" * 68)
    print("掼蛋 · 人类偏好标注")
    print("=" * 68)
    print(f"页面：{url}")
    print(f"对局：{stats['game_path']}（级牌 {session.level or '无'}）")
    print(f"决策点：{stats['total']} 个可选（共 {stats['turn_count']} 步）")
    print(f"偏好写入：{stats['out']}")
    print(f"已标注：{stats['labeled']} / {stats['total']}")
    if session.store.load_errors:
        print(f"提醒：偏好文件里有 {session.store.load_errors} 行读不懂，已跳过。")
    print("浏览器里用 A / B / S 快捷键标注；Ctrl+C 停止。")
    print("=" * 68)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
