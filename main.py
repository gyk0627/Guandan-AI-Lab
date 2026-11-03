"""
GuanDan AI Lab - 命令行入口。

用法：
    python main.py play --seed 42
    python main.py bench --games 20
    python main.py evaluate --games 100 --opponent random
    python main.py collect
    python main.py test

各子命令都有自己的 --help 说明，
直接运行 `python main.py` 会打印总帮助。
"""

import argparse
import inspect
import os
import random
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

# 允许从任意工作目录运行，例如 python C:\...\GuanDan-AI-Lab\main.py
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# 单局最大行动次数，与评估器保持一致
MAX_STEPS = 2000


def cmd_play(args):
    """跑一局启发式自对弈，打印每一步与最终名次。"""

    from game_engine.game_state import GameState
    from players.heuristic import choose_move
    from replay.game_logger import GameLogger

    game = GameState.new_game(seed=args.seed, level=args.level)

    logger = None

    if not args.no_log:
        logger = GameLogger(seed=args.seed)

    rng = random.Random(args.seed + 1000)

    print("=" * 60)
    print("GuanDan AI Lab - 启发式 AI 自对弈")
    print("=" * 60)
    print(
        f"随机种子：{args.seed}    "
        f"级牌：{args.level if args.level else '无'}    "
        f"日志：{'关闭' if args.no_log else '开启'}"
    )
    print("-" * 60)

    step = 0

    while not game.game_over:

        step += 1

        if step > MAX_STEPS:
            print(
                f"[错误] 超过最大行动次数 {MAX_STEPS}，已中止",
                file=sys.stderr,
            )

            if logger is not None:
                logger.file.close()

            return 1

        player = game.current_player
        hand = game.hands[player]

        moves = game.get_legal_moves(player)

        hand_before = list(hand)

        previous_play = (
            list(game.last_play)
            if game.last_play is not None
            else None
        )
        previous_player = game.last_player
        legal_count = len(moves)

        selected = choose_move(
            hand,
            moves,
            rng=rng,
            game_state=game,
            player=player,
        )

        if selected is None:
            if game.last_play is None:
                print(
                    f"[错误] 玩家{player}在领出阶段没有出牌",
                    file=sys.stderr,
                )

                if logger is not None:
                    logger.file.close()

                return 1

            game.pass_turn(player)
            action_type = "pass"

            print(f"第{step:03d}步 | 玩家{player}过牌")

        else:
            game.play(player, selected)
            action_type = "play"

            print(
                f"第{step:03d}步 | 玩家{player}出牌 | "
                f"{selected} | 剩余{len(game.hands[player])}张"
            )

            if player in game.finished_players:
                print(f"玩家{player}已经出完！")

        if logger is not None:
            logger.record_turn(
                game=game,
                player=player,
                action=selected,
                action_type=action_type,
                hand_before=hand_before,
                previous_play=previous_play,
                previous_player=previous_player,
                legal_count=legal_count,
            )

    print("\n" + "=" * 60)
    print("对局结束！")
    print("=" * 60)

    for position, player in enumerate(
        game.finished_players,
        start=1,
    ):
        team = "A队" if player in (0, 2) else "B队"

        print(f"第{position}名：玩家{player}（{team}）")

    first_team = (
        "A队"
        if game.finished_players[0] in (0, 2)
        else "B队"
    )

    print("-" * 60)
    print(f"率先出完牌的队伍：{first_team}")
    print(f"总行动次数：{step}")
    print("=" * 60)

    if logger is not None:
        logger.finish(game)

    return 0


def cmd_bench(args):
    """调用 evaluation/benchmark.py 跑性能基准。"""

    from evaluation.benchmark import run_benchmark

    run_benchmark(
        num_games=args.games,
        seed_start=args.seed_start,
        strategy=args.strategy,
        first_player=args.first_player,
        level=args.level,
        max_steps=args.max_steps,
    )

    return 0


def cmd_evaluate(argv):
    """把剩余参数原样透传给 evaluation/head_to_head.py。"""

    from evaluation import head_to_head

    return head_to_head.main(argv)


def _cast_argument(parameter, payload):
    """按目标函数参数的类型注解 / 默认值做简单类型转换。"""

    if isinstance(payload, bool):
        return payload

    default = parameter.default

    if isinstance(default, bool):
        lowered = str(payload).lower()

        if lowered in ("1", "true", "yes", "on"):
            return True

        if lowered in ("0", "false", "no", "off"):
            return False

        return True

    if isinstance(default, int):
        try:
            return int(payload)
        except (TypeError, ValueError):
            return payload

    if isinstance(default, float):
        try:
            return float(payload)
        except (TypeError, ValueError):
            return payload

    return str(payload)


def _collect_kwargs(function, tokens):
    """
    按目标函数签名，把剩余参数转成关键字参数。

    这样 training/collect_data.py 被重写后，
    只要函数参数名还在，main.py collect 不需要跟着改。
    """

    parameters = inspect.signature(function).parameters

    # 目标函数自己接收 argv 列表
    if "argv" in parameters:
        return {"argv": list(tokens)}

    kwargs = {}
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if not token.startswith("--"):
            print(f"[提示] 忽略无法识别的参数：{token}")
            index += 1
            continue

        name, _, inline_value = token[2:].partition("=")
        key = name.replace("-", "_")

        if key not in parameters:
            print(f"[提示] 目标函数不接受参数 --{name}，已忽略")
            index += 1
            continue

        if inline_value:
            payload = inline_value
            index += 1

        elif (
            index + 1 < len(tokens)
            and not tokens[index + 1].startswith("--")
        ):
            payload = tokens[index + 1]
            index += 2

        else:
            # 只有开关、没有取值
            payload = True
            index += 1

        kwargs[key] = _cast_argument(parameters[key], payload)

    return kwargs


def cmd_collect(argv):
    """
    调用 training/collect_data.py 的 main。

    该模块正在被重写，所以这里不写死参数：
    先尝试 main，再退回 collect_dataset，
    都不可用就友好提示并返回非零退出码。
    """

    from importlib import import_module

    parser = argparse.ArgumentParser(
        prog="main.py collect",
        description="采集训练数据（调用 training/collect_data.py）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "剩余参数会按 training.collect_data 目标函数的签名透传，例如：\n"
            "  python main.py collect --num-games 20 --start-seed 1000\n"
            "\n"
            "注意：training/collect_data.py 由其他人负责重写，"
            "目标函数写好后本命令自动生效，不需要修改 main.py。\n"
        ),
    )

    _, extra = parser.parse_known_args(argv)

    try:
        module = import_module("training.collect_data")

    except Exception as error:  # noqa: BLE001 - 重写期间任何导入错误都要友好提示
        print("[提示] 训练数据采集模块当前不可用。")
        print(f"       导入 training.collect_data 失败：{error}")
        print("       等它重写完成后重试，或直接运行：")
        print("       python -m training.collect_data")
        return 1

    function = getattr(module, "main", None)

    if not callable(function):
        function = getattr(module, "collect_dataset", None)

    if not callable(function):
        print("[提示] training.collect_data 里没有可调用的 main 或 collect_dataset。")
        print("       等它重写完成后再试，或直接运行：")
        print("       python -m training.collect_data")
        return 1

    kwargs = _collect_kwargs(function, extra)

    print(
        f"[提示] 调用 training.collect_data.{function.__name__}"
        f"({', '.join(f'{key}={value}' for key, value in kwargs.items())})"
    )

    result = function(**kwargs)

    if isinstance(result, int):
        return result

    return 0


def cmd_test(args):
    """等价于 python -m pytest tests -q。"""

    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests",
        "-q",
    ]

    print("执行命令：", " ".join(command))
    print(f"工作目录：{ROOT}")

    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"

    return subprocess.call(
        command,
        cwd=str(ROOT),
        env=environment,
    )


def build_parser():
    """构造总命令行解析器。"""

    parser = argparse.ArgumentParser(
        prog="main.py",
        description="GuanDan AI Lab - 命令行入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py play --seed 42\n"
            "  python main.py play --seed 7 --no-log\n"
            "  python main.py bench --games 20\n"
            "  python main.py evaluate --games 100 --opponent random\n"
            "  python main.py collect --num-games 20\n"
            "  python main.py test\n"
        ),
    )

    subparsers = parser.add_subparsers(
        dest="command",
        metavar="子命令",
        title="子命令",
    )

    # play：跑一局自对弈
    play_parser = subparsers.add_parser(
        "play",
        help="跑一局启发式 AI 自对弈，打印每步与最终名次",
        description="跑一局启发式 AI 自对弈，打印每步与最终名次",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py play --seed 1\n"
            "  python main.py play --seed 7 --no-log\n"
        ),
    )

    play_parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="随机种子（默认 42）",
    )
    play_parser.add_argument(
        "--level",
        default=None,
        help="级牌（2~A），默认 None 表示无级牌模式",
    )
    play_parser.add_argument(
        "--no-log",
        action="store_true",
        help="不写 replay/ 下的 jsonl 对局日志",
    )

    # bench：性能基准
    bench_parser = subparsers.add_parser(
        "bench",
        help="固定种子跑性能基准（ms/局、平均步数）",
        description="固定种子跑性能基准（ms/局、平均步数）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py bench\n"
            "  python main.py bench --games 50 --seed-start 100\n"
        ),
    )

    bench_parser.add_argument(
        "--games",
        type=int,
        default=20,
        help="基准局数（默认 20）",
    )
    bench_parser.add_argument(
        "--seed-start",
        type=int,
        default=42,
        help="起始随机种子（默认 42）",
    )
    bench_parser.add_argument(
        "--strategy",
        default="heuristic",
        choices=["heuristic", "random"],
        help="自对弈使用的策略（默认 heuristic）",
    )
    bench_parser.add_argument(
        "--first-player",
        type=int,
        default=0,
        choices=[0, 1, 2, 3],
        help="每局首位出牌玩家（默认 0）",
    )
    bench_parser.add_argument(
        "--level",
        default=None,
        help="级牌（2~A），默认 None",
    )
    bench_parser.add_argument(
        "--max-steps",
        type=int,
        default=MAX_STEPS,
        help=f"单局最大行动次数（默认 {MAX_STEPS}）",
    )

    # evaluate：参数全部透传给 evaluation/head_to_head.py
    subparsers.add_parser(
        "evaluate",
        help="成对同种子对战评估（参数透传给 evaluation/head_to_head.py）",
        description=(
            "成对同种子 + 换座位的对战评估。\n"
            "所有参数原样透传给 evaluation/head_to_head.py，"
            "例如 --games、--seed-start、--opponent、--json。\n"
            "查看完整参数请运行：python main.py evaluate --help"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py evaluate --games 100 --opponent random\n"
            "  python main.py evaluate --games 20 --json\n"
        ),
    )

    # collect：训练数据采集
    subparsers.add_parser(
        "collect",
        help="采集训练数据（调用 training/collect_data.py）",
        description=(
            "采集训练数据。剩余参数会按 training/collect_data.py "
            "目标函数的签名透传，不写死任何参数名。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python main.py collect\n"
            "  python main.py collect --num-games 20 --start-seed 1000\n"
        ),
    )

    # test：全量测试
    subparsers.add_parser(
        "test",
        help="等价于 python -m pytest tests -q",
        description="等价于 python -m pytest tests -q",
    )

    return parser


def _dispatch_evaluate(raw_argv):
    """evaluate 子命令的参数全部交给 head_to_head 解析。"""

    if raw_argv and raw_argv[0] == "evaluate":
        return cmd_evaluate(raw_argv[1:])

    return None


def _dispatch_collect(raw_argv):
    """collect 子命令的参数全部交给 training.collect_data 解析。

    必须在顶层 parse_args 之前拦截：顶层解析器不认识 --games 之类的参数，
    否则 `main.py collect --games 20` 会直接 exit 2。
    """

    if raw_argv and raw_argv[0] == "collect":
        return cmd_collect(raw_argv[1:])

    return None


def main(argv=None):
    """程序入口，返回退出码。"""

    raw_argv = list(sys.argv[1:] if argv is None else argv)

    # 先处理 evaluate / collect：这两个子命令的参数由下游模块自己解析
    for dispatch in (_dispatch_evaluate, _dispatch_collect):
        result = dispatch(raw_argv)

        if result is not None:
            return result

    parser = build_parser()

    if not raw_argv:
        parser.print_help()
        return 0

    args = parser.parse_args(raw_argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "play":
        return cmd_play(args)

    if args.command == "bench":
        return cmd_bench(args)

    if args.command == "collect":
        return cmd_collect(raw_argv[1:])

    if args.command == "test":
        return cmd_test(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
