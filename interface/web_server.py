"""本地人机对战界面（只依赖 Python 标准库）。

设计要点：

* 服务只监听 127.0.0.1，不对外网开放；
* 全部游戏状态在服务端，客户端只提交「我要出这几张牌」，
  合法性由 GameState.play 校验——界面无法作弊；
* 你坐 0 号位（A 队），其余三家由神经网络策略代打
  （找不到模型时自动退回启发式）；
* 不需要联网，也不需要额外装包。

启动：

    .\\.venv\\Scripts\\python.exe -m interface.web_server

或者直接双击 interface\\start_gui.bat。
"""

import argparse
import json
import random
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from game_engine.game_state import GameState
from game_engine.legal_moves import legal_moves
from game_engine.patterns import analyze_cards, type_label
from players.heuristic import choose_move
from replay.game_logger import GameLogger
from training.serialize import card_to_text, text_to_cards

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = Path(__file__).resolve().parent / "index.html"
MODEL_DIR = ROOT / "models"

MAX_AI_STEPS = 400
HUMAN_SEAT = 0
TEAM_OF = {0: "A", 1: "B", 2: "A", 3: "B"}


def teammate(player):
    return (player + 2) % 4


def latest_model():
    models = sorted(MODEL_DIR.glob("bc_*.pt"), key=lambda path: path.stat().st_mtime)

    return models[-1] if models else None


class GameSession:
    """一局人机对战。"""

    def __init__(
        self,
        level="2",
        seed=None,
        model_path=None,
        use_neural=True,
        log_dir=None,
        on_log_ready=None,
    ):
        self.level = level
        # 没指定种子就随机生成一个：写进日志文件名，这一局以后可以精确重放
        self.seed = seed if seed is not None else random.randrange(1, 1_000_000)
        self.message = ""

        self.game = GameState.new_game(seed=self.seed, level=level)
        self.rng = random.Random(self.seed + 1000)

        self.policy = None
        self.policy_name = "启发式"

        if use_neural:
            path = Path(model_path) if model_path else latest_model()

            if path and path.exists():
                try:
                    from players.neural import NeuralPolicy

                    self.policy = NeuralPolicy(path, device="auto", seed=self.seed)
                    self.policy_name = f"神经网络（{path.stem}）"
                except Exception as error:  # noqa: BLE001 - 模型坏了也要能玩
                    self.message = f"神经网络加载失败，已退回启发式：{error}"

        # 每一手都写进 replay/，否则关掉窗口这一局就彻底没了
        self.logger = GameLogger(
            seed=self.seed,
            output_dir=log_dir,
            prefix="human",
        )
        self.log_path = str(self.logger.file_path)
        # 本局到底动过几手：用来判断开新局时这局是不是空壳（空壳不留日志文件）
        self.moves = 0
        # 一局打完时回调（app.py 用它把记录传回去）；传出错也不影响游戏
        self.on_log_ready = on_log_ready

        self.advance_ai()

    # ---------------------------------------------------------------- 内部
    def _act(self, player, selected, legal):
        """执行并记录一手；出牌与过牌都走这里，保证日志完整。"""
        hand_before = list(self.game.hands[player])
        previous_play = (
            list(self.game.last_play)
            if self.game.last_play is not None
            else None
        )
        previous_player = self.game.last_player

        if selected is None:
            self.game.pass_turn(player)
            action_type = "pass"
        else:
            self.game.play(player, selected)
            action_type = "play"

        self.logger.record_turn(
            game=self.game,
            player=player,
            action=selected,
            action_type=action_type,
            hand_before=hand_before,
            previous_play=previous_play,
            previous_player=previous_player,
            legal_count=len(legal),
        )
        self.moves += 1

        if self.game.game_over:
            self.logger.finish(self.game)
            self._notify_log_ready()

    def _notify_log_ready(self):
        """一局结束，通知外部「这条记录可以拿走用/传走了」。"""
        callback = self.on_log_ready
        if callback is None:
            return
        try:
            callback(self.log_path)
        except Exception:  # noqa: BLE001 - 上传失败、磁盘只读都不该影响对局
            pass

    def ai_action(self, player, legal):
        if self.policy is not None:
            return self.policy.choose(self.game, player, legal)

        return choose_move(
            self.game.hands[player],
            legal,
            rng=self.rng,
            game_state=self.game,
            player=player,
        )

    def advance_ai(self):
        """让 AI 一直行动，直到轮到人或者对局结束。"""
        steps = 0

        while not self.game.game_over and self.game.current_player != HUMAN_SEAT:
            steps += 1

            if steps > MAX_AI_STEPS:
                self.message = "AI 行动次数异常，已中止本局"
                break

            player = self.game.current_player
            legal = self.game.get_legal_moves(player)
            selected = self.ai_action(player, legal)

            if selected is None and self.game.last_play is None:
                # 领出阶段不允许过牌，强行打第一手合法牌
                selected = legal[0]

            self._act(player, selected, legal)

    def human_acts(self):
        return (
            not self.game.game_over
            and self.game.current_player == HUMAN_SEAT
        )

    # ---------------------------------------------------------------- 动作
    def play(self, cards):
        if self.game.game_over:
            return False, "对局已经结束"

        if not self.human_acts():
            return False, "现在还没轮到你"

        try:
            parsed = text_to_cards(cards)
        except ValueError as error:
            return False, f"无法识别的牌：{error}"

        if not parsed:
            return False, "请先选择要出的牌"

        try:
            self._act(HUMAN_SEAT, parsed, self.game.get_legal_moves(HUMAN_SEAT))
        except ValueError as error:
            return False, str(error)

        self.message = ""
        self.advance_ai()
        return True, ""

    def pass_turn(self):
        if self.game.game_over:
            return False, "对局已经结束"

        if not self.human_acts():
            return False, "现在还没轮到你"

        try:
            self._act(HUMAN_SEAT, None, self.game.get_legal_moves(HUMAN_SEAT))
        except ValueError as error:
            return False, str(error)

        self.message = ""
        self.advance_ai()
        return True, ""

    # ---------------------------------------------------------------- 视图
    def snapshot(self):
        game = self.game

        last_play = (
            [card_to_text(card) for card in game.last_play]
            if game.last_play is not None
            else None
        )

        last_info = analyze_cards(game.last_play, self.level) if last_play else None

        # 队友刚出过牌时，你一手都不能出，只能过（规则：不能压队友）
        partner_leads = (
            not game.game_over
            and game.last_player is not None
            and teammate(HUMAN_SEAT) == game.last_player
        )

        # 出牌流水：界面要能按顺序看到每个人出了什么、谁过了
        history = []

        for entry in game.history[-60:]:
            cards = entry["cards"]
            info = analyze_cards(cards, self.level) if cards else None

            history.append({
                "player": entry["player"],
                "team": TEAM_OF[entry["player"]],
                "action_type": entry["action"],
                "cards": [card_to_text(card) for card in cards],
                "pattern": type_label(info) if info else None,
            })

        return {
            "level": self.level,
            "level_text": f"打 {self.level}" if self.level else "无级牌",
            "seed": self.seed,
            "log_name": Path(self.log_path).name,
            # 红桃级牌就是逢人配，界面要把它标出来，否则「9 J Q K Q」看起来像乱牌
            "wildcard_text": f"H:{self.level}" if self.level else None,
            "partner_leads": partner_leads,
            "history": history,
            "your_seat": HUMAN_SEAT,
            "your_team": TEAM_OF[HUMAN_SEAT],
            "your_partner": teammate(HUMAN_SEAT),
            "policy": self.policy_name,
            "hand": [card_to_text(card) for card in game.hands[HUMAN_SEAT]],
            "hand_counts": [len(hand) for hand in game.hands],
            "teams": [TEAM_OF[player] for player in range(4)],
            "current_player": game.current_player,
            "your_turn": self.human_acts(),
            "last_play": last_play,
            "last_play_text": type_label(last_info),
            "last_player": game.last_player,
            "finished": list(game.finished_players),
            "ranking": list(game.finished_players),
            "game_over": game.game_over,
            "can_pass": game.last_play is not None,
            "message": self.message,
        }

    def legal_plays(self, limit=8):
        """给「提示」按钮用：返回若干可行的出牌。"""
        moves = self.game.get_legal_moves(HUMAN_SEAT)

        if self.game.last_play is None:
            moves = sorted(moves, key=len, reverse=True)

        return [
            [card_to_text(card) for card in move]
            for move in moves[:limit]
        ]


class GameHTTPServer(ThreadingHTTPServer):
    """默认的 HTTPServer 会开 allow_reuse_address，在 Windows 上表现为
    **两个进程可以同时绑定同一个端口**，然后各自接走一部分请求——
    用户会看到界面时好时坏、状态互相覆盖。

    这里显式关掉它：端口被占用时第二个实例直接报错退出，问题立刻暴露。
    """

    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    session: GameSession = None
    log_dir = None
    on_log_ready = None
    lock = threading.Lock()

    server_version = "GuanDanGUI/1.0"

    def log_message(self, fmt, *args):
        pass  # 控制台保持干净

    # ---------------------------------------------------------------- 工具
    def _send(self, status, payload, content_type="application/json"):
        body = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)

        if not length:
            return {}

        return json.loads(self.rfile.read(length).decode("utf-8"))

    # ---------------------------------------------------------------- 路由
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                html = INDEX_PATH.read_text(encoding="utf-8")
            except OSError:
                self._send(500, {"error": "index.html 缺失"}, "application/json")
                return

            self._send(200, html, "text/html; charset=utf-8")
            return

        if self.path == "/favicon.ico":
            # 浏览器会自动来要图标，回 204 免得控制台一直报 404
            self.send_response(204)
            self.end_headers()
            return

        if self.path == "/api/state":
            with self.lock:
                self._send(200, self.session.snapshot())
            return

        if self.path == "/api/legal":
            with self.lock:
                self._send(200, {"plays": self.session.legal_plays()})
            return

        self._send(404, {"error": "未知路径"})

    def do_POST(self):
        try:
            payload = self._read_json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "请求体不是合法 JSON"})
            return

        with self.lock:
            if self.path == "/api/new":
                level = payload.get("level", "2")
                seed = payload.get("seed")
                model = payload.get("model")

                # 旧的一局如果没打完，先收尾，避免日志文件悬着没关；
                # 如果这局一手都没动过（比如刚开服务器就点「新的一局」），
                # 顺手把空日志删掉，别在 replay/ 里越堆越多。
                old = self.session
                try:
                    old_path = old.logger.finish(old.game)
                except Exception:  # noqa: BLE001 - 收尾失败不该挡住开新局
                    old_path = None
                if old_path and not getattr(old, "moves", 0):
                    try:
                        Path(old_path).unlink()
                    except OSError:
                        pass
                elif old_path and getattr(old, "on_log_ready", None):
                    # 打到一半点「新的一局」：这局的记录也算数
                    try:
                        old.on_log_ready(old_path)
                    except Exception:  # noqa: BLE001
                        pass

                # 必须写到「类」上：http.server 每个请求都新建一个 handler 实例，
                # 写 self.session 只影响当次请求，后续请求读到的还是旧对局。
                type(self).session = GameSession(
                    level=level or None,
                    seed=seed,
                    model_path=model,
                    use_neural=payload.get("use_neural", True),
                    log_dir=self.log_dir,
                    on_log_ready=self.on_log_ready,
                )

                self._send(200, self.session.snapshot())
                return

            if self.path == "/api/play":
                ok, error = self.session.play(payload.get("cards") or [])
                state = self.session.snapshot()
                state["error"] = error
                self._send(200 if ok else 400, state)
                return

            if self.path == "/api/pass":
                ok, error = self.session.pass_turn()
                state = self.session.snapshot()
                state["error"] = error
                self._send(200 if ok else 400, state)
                return

        self._send(404, {"error": "未知路径"})


def create_server(
    port=8765,
    level="2",
    seed=None,
    use_neural=True,
    model_path=None,
    log_dir=None,
    on_log_ready=None,
):
    handler = type(
        "BoundHandler",
        (Handler,),
        {
            "session": GameSession(
                level=level,
                seed=seed,
                model_path=model_path,
                use_neural=use_neural,
                log_dir=log_dir,
                on_log_ready=on_log_ready,
            ),
            "log_dir": log_dir,
            "on_log_ready": on_log_ready,
        },
    )

    server = GameHTTPServer(("127.0.0.1", port), handler)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="掼蛋人机对战（本地网页版）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--level", default="2", help="打几，例如 2 / 7 / A")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-neural", action="store_true", help="强制用启发式")
    parser.add_argument("--model", default=None, help="指定模型；省略取 models 下最新")

    args = parser.parse_args(argv)

    try:
        server = create_server(
            port=args.port,
            level=args.level,
            seed=args.seed,
            use_neural=not args.no_neural,
            model_path=args.model,
        )
    except OSError as error:
        print(f"无法监听端口 {args.port}：{error}")
        print("通常是因为已经有一个界面在跑。")
        print(f"要么关掉它，要么换个端口：--port {args.port + 1}")
        return 1

    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 58)
    print("掼蛋人机对战")
    print("=" * 58)
    print(f"地址：{url}")
    print(f"你是 0 号位（A 队），队友 2 号位；对手 1、3 号位")
    print(f"级牌：{args.level}    策略：{'神经网络' if not args.no_neural else '启发式'}")
    print("关闭本窗口即结束。按 Ctrl+C 也可以。")
    print("=" * 58)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出。")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
