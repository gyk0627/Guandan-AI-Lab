"""自我对弈对局生成（阶段 6 第 1 步）。

目标不是"训练得更强"，而是先建立一条**稳定、可复现、可扩展**的自我对弈流水线：

* 四家可以由不同策略担任（当前模型 / 启发式 / 随机），方便做对手池；
* 采样带温度，避免四家永远走同一条线、产出大量重复对局；
* 产出与 training.collect_data 完全相同的 JSONL 格式，
  所以 training.export_dataset 可以直接吃、不需要改。

用法：

    # 四家都用当前模型，温度 1.0，跑 100 局
    & .\\.venv\\Scripts\\python.exe -m training.self_play --games 100 --seats neural

    # 2 个模型 vs 2 个启发式（A 队模型、B 队启发式）
    & .\\.venv\\Scripts\\python.exe -m training.self_play --games 100 --seats neural,heuristic,neural,heuristic

    # 指定模型与探索强度
    & .\\.venv\\Scripts\\python.exe -m training.self_play --games 100 --seats neural --temperature 0.8 --epsilon 0.05
"""

import argparse
import json
import random
from collections import Counter
from datetime import datetime
from pathlib import Path

from game_engine.ranks import NORMAL_RANKS
from training import collect_data
from players.sampling import HeuristicSeat, RandomSeat, SeatPolicies, SamplingPolicy

DATA_DIR = Path(__file__).resolve().parent / "data_selfplay"


def latest_model():
    models = sorted(
        (Path(__file__).resolve().parent.parent / "models").glob("bc_*.pt"),
        key=lambda path: path.stat().st_mtime,
    )

    return models[-1] if models else None


def build_neural_seat(checkpoint, seed, temperature, epsilon):
    from players.neural import NeuralPolicy

    base = NeuralPolicy(checkpoint, device="auto", seed=seed)

    if temperature <= 0 and epsilon <= 0:
        # 不探索时直接用贪心，省得套一层采样
        base.name = f"neural:{Path(checkpoint).stem}"
        return base

    return SamplingPolicy(
        base,
        temperature=temperature,
        epsilon=epsilon,
        seed=seed,
        name=f"neural:{Path(checkpoint).stem}(T={temperature:g},eps={epsilon:g})",
    )


def build_seat_policies(specs, seed, checkpoint, temperature, epsilon):
    """按座位构建策略。specs 形如 ["neural", "heuristic", "neural", "heuristic"]。"""
    per_seat = {}

    for seat, spec in enumerate(specs):
        seat_seed = seed * 100 + seat

        if spec == "neural":
            per_seat[seat] = build_neural_seat(
                checkpoint, seat_seed, temperature, epsilon
            )
        elif spec == "heuristic":
            per_seat[seat] = HeuristicSeat(seat_seed, name="heuristic")
        elif spec == "random":
            per_seat[seat] = RandomSeat(seat_seed, name="random")
        else:
            raise ValueError(f"未知策略：{spec}")

    return SeatPolicies(per_seat)


def run_self_play(
    games=100,
    seats=("neural", "heuristic", "neural", "heuristic"),
    seed_start=70000,
    level_mode="cycle",
    temperature=1.0,
    epsilon=0.05,
    checkpoint=None,
    out_path=None,
    verbose=True,
    progress=None,
):
    checkpoint = checkpoint or latest_model()

    if checkpoint is None and "neural" in seats:
        raise FileNotFoundError("seats 里含 neural，但 models/ 下没有 .pt")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = DATA_DIR / f"selfplay_{stamp}.jsonl"
    else:
        out_path = Path(out_path)

    stats = {
        "games": 0,
        "decisions": 0,
        "pass": 0,
        "play": 0,
        "steps": 0,
        "first_out_team": Counter(),
        "by_seat_policy": Counter(),
    }

    seat_label = {0: "0", 1: "1", 2: "2", 3: "3"}

    with out_path.open("w", encoding="utf-8") as file:
        for index in range(games):
            seed = seed_start + index
            level = (
                None if level_mode == "none"
                else NORMAL_RANKS[index % len(NORMAL_RANKS)]
            )

            policies = build_seat_policies(
                seats, seed, checkpoint, temperature, epsilon
            )

            decisions, summary = collect_data.collect_one_game(
                seed=seed, level=level, policy=policies
            )

            for line in collect_data.dump_game(decisions, summary):
                file.write(line + "\n")

            stats["games"] += 1
            stats["decisions"] += len(decisions)
            stats["steps"] += summary["steps"]
            stats["first_out_team"][summary["first_out_team"]] += 1

            for record in decisions:
                stats[record["action_type"]] += 1

            winner = summary["first_out_team"]
            for seat in (0, 2) if winner == "A" else (1, 3):
                stats["by_seat_policy"][seats[seat]] += 1

            if verbose and ((index + 1) % 10 == 0 or index == games - 1):
                print(
                    f"第 {index + 1:04d}/{games} 局 | level={level or 'none'} | "
                    f"步数 {summary['steps']:3d} | 头游 {winner} 队 | "
                    f"累计样本 {stats['decisions']}"
                )

            if progress is not None:
                progress(index + 1, games, stats["decisions"])

    manifest = {
        "file": out_path.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "games": stats["games"],
        "decisions": stats["decisions"],
        "actions": {"pass": stats["pass"], "play": stats["play"]},
        "avg_steps": round(stats["steps"] / max(stats["games"], 1), 2),
        "seats": list(seats),
        "temperature": temperature,
        "epsilon": epsilon,
        "checkpoint": str(checkpoint) if checkpoint else None,
        "seed_start": seed_start,
        "level_mode": level_mode,
        "first_out_team": dict(stats["first_out_team"]),
        "wins_by_seat_policy": dict(stats["by_seat_policy"]),
    }

    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if verbose:
        print("\n" + "=" * 60)
        print("自我对弈完成")
        print("=" * 60)
        print(f"对局：{stats['games']}   决策：{stats['decisions']}")
        print(f"平均步数：{manifest['avg_steps']}")
        print(f"头游分布：{manifest['first_out_team']}")
        print(f"按座位策略的胜场：{manifest['wins_by_seat_policy']}")
        print(f"数据：{out_path}")

    return out_path, manifest


def _spawn_worker(args):
    """用独立子进程跑一段种子区间。

    为什么不用 multiprocessing.Pool：Windows 上 Pool 依赖命名管道，
    而受限环境（沙箱）会拒绝创建命名管道。用 subprocess + DEVNULL 完全不走管道，
    每个进程只往自己的分片文件里写。
    """
    import subprocess
    import sys

    take, seed_start, seats, level_mode, temperature, epsilon, checkpoint, part_path = args

    command = [
        sys.executable, "-X", "utf8", "-m", "training.self_play",
        "--games", str(take),
        "--seed-start", str(seed_start),
        "--seats", ",".join(seats),
        "--level-mode", level_mode,
        "--temperature", str(temperature),
        "--epsilon", str(epsilon),
        "--out", part_path,
    ]

    if checkpoint:
        command += ["--checkpoint", str(checkpoint)]

    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return process, part_path


def run_parallel_self_play(
    games=100,
    workers=4,
    seats=("neural", "heuristic", "neural", "heuristic"),
    seed_start=70000,
    level_mode="cycle",
    temperature=1.0,
    epsilon=0.05,
    checkpoint=None,
    out_path=None,
    verbose=True,
):
    """多进程并行自对弈：按种子区间切分，各进程写分片，最后合并。

    合并后的文件与单进程产出格式完全一致，导出器可以直接吃。
    """
    import shutil
    import time

    checkpoint = checkpoint or latest_model()

    if checkpoint is None and "neural" in seats:
        raise FileNotFoundError("seats 里含 neural，但 models/ 下没有 .pt")

    workers = max(1, int(workers))
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if out_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = DATA_DIR / f"selfplay_{stamp}.jsonl"
    else:
        out_path = Path(out_path)

    base = max(1, games // workers)
    chunks = []
    remaining = games
    seed = seed_start
    index = 0

    while remaining > 0:
        take = min(base if index < workers - 1 else remaining, remaining)

        chunks.append(
            (take, seed, seats, level_mode, temperature, epsilon, checkpoint,
             str(out_path.with_suffix(f".part{index}.jsonl")))
        )
        seed += take
        remaining -= take
        index += 1

    started = time.perf_counter()
    running = [_spawn_worker(chunk) for chunk in chunks]

    for process, part_path in running:
        process.wait()

        if process.returncode != 0:
            raise RuntimeError(
                f"子进程失败（退出码 {process.returncode}）：{part_path}"
            )

        if not Path(part_path).exists():
            raise RuntimeError(f"子进程没有产出分片：{part_path}")

    elapsed = time.perf_counter() - started

    merged_decisions = 0
    merged_first_out = Counter()
    merged_wins = Counter()
    total_games = 0

    with out_path.open("w", encoding="utf-8") as sink:
        for chunk in chunks:
            part = Path(chunk[7])

            with part.open("r", encoding="utf-8") as source:
                shutil.copyfileobj(source, sink)

            part.unlink(missing_ok=True)

            manifest_path = part.with_suffix(".manifest.json")

            if manifest_path.exists():
                part_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                merged_decisions += part_manifest["decisions"]
                total_games += part_manifest["games"]

                for key, value in part_manifest["first_out_team"].items():
                    merged_first_out[key] += value
                for key, value in part_manifest["wins_by_seat_policy"].items():
                    merged_wins[key] += value

                manifest_path.unlink(missing_ok=True)

    manifest = {
        "file": out_path.name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "games": total_games,
        "decisions": merged_decisions,
        "workers": workers,
        "elapsed_seconds": round(elapsed, 1),
        "games_per_second": round(total_games / elapsed, 2) if elapsed > 0 else None,
        "seats": list(seats),
        "temperature": temperature,
        "epsilon": epsilon,
        "checkpoint": str(checkpoint) if checkpoint else None,
        "seed_start": seed_start,
        "level_mode": level_mode,
        "first_out_team": dict(merged_first_out),
        "wins_by_seat_policy": dict(merged_wins),
    }

    out_path.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if verbose:
        print("\n" + "=" * 60)
        print("并行自我对弈完成")
        print("=" * 60)
        print(f"对局：{total_games}   决策：{merged_decisions}   进程：{workers}")
        print(f"耗时：{elapsed:.1f}s   吞吐：{total_games / elapsed:.2f} 局/秒")
        print(f"头游分布：{manifest['first_out_team']}")
        print(f"数据：{out_path}")

    return out_path, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="自我对弈对局生成")
    parser.add_argument("--games", type=int, default=100)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="并行进程数；>1 时按种子区间切分，各进程各写一个分片文件，最后合并",
    )
    parser.add_argument("--seed-start", type=int, default=70000)
    parser.add_argument(
        "--seats",
        default="neural,heuristic,neural,heuristic",
        help="四个座位依次用什么策略：neural / heuristic / random",
    )
    parser.add_argument(
        "--level-mode", choices=("cycle", "none"), default="cycle"
    )
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--epsilon", type=float, default=0.05)
    parser.add_argument("--checkpoint", default=None)
    parser.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    seats = tuple(part.strip() for part in args.seats.split(","))

    if len(seats) != 4:
        raise SystemExit("--seats 必须给 4 个，用逗号分隔")

    if args.workers > 1:
        run_parallel_self_play(
            games=args.games,
            workers=args.workers,
            seats=seats,
            seed_start=args.seed_start,
            level_mode=args.level_mode,
            temperature=args.temperature,
            epsilon=args.epsilon,
            checkpoint=args.checkpoint,
            out_path=args.out,
        )
    else:
        run_self_play(
            games=args.games,
            seats=seats,
            seed_start=args.seed_start,
            level_mode=args.level_mode,
            temperature=args.temperature,
            epsilon=args.epsilon,
            checkpoint=args.checkpoint,
            out_path=args.out,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
