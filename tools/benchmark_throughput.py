"""吞吐量基准：回答"租服务器要租多久、租几核"。

测四件事：

A. 纯 CPU 的模拟吞吐      —— 每秒能跑多少局随机/启发式对局、多少次决策
B. GPU 的推理吞吐         —— 每秒能过多少个「候选打分」批次
C. 端到端自我对弈吞吐     —— 一局完整的「引擎 + 神经网络」需要多久
D. 数据产出速率           —— 每小时能生成多少条决策、多少 MB

再据此估算 100 万局 / 1000 万局需要多久。

用法：
    & .\\.venv\\Scripts\\python.exe -m tools.benchmark_throughput
    & .\\.venv\\Scripts\\python.exe -m tools.benchmark_throughput --games 30
"""

import argparse
import random
import statistics
import time
from pathlib import Path

from game_engine.game_state import GameState
from players.heuristic import choose_move

REPO = Path(__file__).resolve().parent.parent


def play_one_game(strategy, seed, level="2"):
    """跑一局，返回 (步数, 决策数)。strategy 为 "random" 或 "heuristic"。"""
    game = GameState.new_game(seed=seed, level=level)
    rng = random.Random(seed)
    steps = 0

    while not game.game_over:
        steps += 1
        player = game.current_player
        legal = game.get_legal_moves(player)

        if strategy == "random":
            selected = rng.choice(legal) if legal else None
        else:
            selected = choose_move(
                game.hands[player], legal, rng=rng,
                game_state=game, player=player,
            )

        if selected is None:
            game.pass_turn(player)
        else:
            game.play(player, selected)

    return steps, len(game.history)


def bench_cpu(strategy, games):
    durations = []
    steps_list = []

    for index in range(games):
        started = time.perf_counter()
        steps, _ = play_one_game(strategy, seed=100000 + index)
        durations.append(time.perf_counter() - started)
        steps_list.append(steps)

    total = sum(durations)

    return {
        "games": games,
        "total_seconds": total,
        "games_per_second": games / total,
        "seconds_per_game": statistics.median(durations),
        "decisions_per_second": sum(steps_list) / total,
        "avg_steps": statistics.mean(steps_list),
    }


def bench_gpu(game_batches=30, batch_sizes=(1, 64)):
    """测候选打分网络的前向吞吐（不含引擎）。"""
    import numpy as np
    import torch

    from training.state_encoder import ACTION_DIM, STATE_DIM
    from training.model import CandidateScorer

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = CandidateScorer(STATE_DIM, ACTION_DIM, hidden=256, cand_hidden=128).to(device)
    model.eval()

    results = {}

    for batch in batch_sizes:
        width = 30
        states = torch.randn(batch, STATE_DIM, device=device)
        cands = torch.randn(batch, width, ACTION_DIM, device=device)
        mask = torch.ones(batch, width, device=device)

        for _ in range(3):  # 预热
            model(states, cands, mask)

        if device.type == "cuda":
            torch.cuda.synchronize()

        started = time.perf_counter()

        for _ in range(game_batches):
            with torch.no_grad():
                model(states, cands, mask)

        if device.type == "cuda":
            torch.cuda.synchronize()

        elapsed = time.perf_counter() - started
        decisions = game_batches * batch

        results[batch] = {
            "decisions": decisions,
            "seconds": elapsed,
            "decisions_per_second": decisions / elapsed,
            "ms_per_batch": elapsed / game_batches * 1000,
        }

    return device.type, results


def bench_selfplay(games=5):
    """端到端：加载模型，跑自我对弈若干局。"""
    from players.neural import NeuralPolicy
    from players.sampling import SamplingPolicy
    from training.self_play import latest_model

    checkpoint = latest_model()

    if checkpoint is None:
        return None

    base = NeuralPolicy(checkpoint, device="auto", seed=0)
    sampler = SamplingPolicy(base, temperature=1.0, epsilon=0.05, seed=0)

    durations = []

    for index in range(games):
        seed = 500000 + index
        started = time.perf_counter()

        game = GameState.new_game(seed=seed, level="2")
        rng = random.Random(seed)
        steps = 0

        while not game.game_over:
            steps += 1
            player = game.current_player
            legal = game.get_legal_moves(player)
            selected = sampler.choose(game, player, legal)

            if selected is None:
                game.pass_turn(player)
            else:
                game.play(player, selected)

        durations.append(time.perf_counter() - started)

    total = sum(durations)

    return {
        "games": games,
        "seconds_per_game": statistics.median(durations),
        "games_per_second": games / total,
        "device": str(base.device),
        "checkpoint": checkpoint.name,
    }


def estimate(games_per_second, decisions_per_game=100, bytes_per_decision=700):
    if games_per_second <= 0:
        return {}

    rows = {}

    for target in (1_000_000, 10_000_000):
        seconds = target / games_per_second
        rows[target] = {
            "hours": seconds / 3600,
            "decisions": target * decisions_per_game,
            "gigabytes": target * decisions_per_game * bytes_per_decision / 1e9,
        }

    return rows


def main(argv=None):
    print("[已合并] 这个脚本现在归到统一入口：python -m tools.benchmark run --preset standard")
    print("          （旧命令仍可用；新报告格式见 tools/benchmark.py 顶部说明）")
    print()
    parser = argparse.ArgumentParser(description="吞吐量基准")
    parser.add_argument("--games", type=int, default=10, help="每个 CPU 基准跑几局")
    parser.add_argument("--selfplay-games", type=int, default=5)
    parser.add_argument("--skip-gpu", action="store_true")

    args = parser.parse_args(argv)

    print("=" * 68)
    print("GuanDan AI Lab —— 吞吐量基准")
    print("=" * 68)

    # ---- A. CPU ----
    cpu = {}

    for strategy in ("random", "heuristic"):
        result = bench_cpu(strategy, args.games)
        cpu[strategy] = result
        print(f"\n[A] CPU · {strategy} 策略")
        print(f"    每秒 {result['games_per_second']:.1f} 局"
              f"（{result['seconds_per_game']*1000:.0f} ms/局，平均 {result['avg_steps']:.1f} 步）")
        print(f"    每秒 {result['decisions_per_second']:.0f} 次决策")

    # ---- B. GPU ----
    gpu = {}

    if not args.skip_gpu:
        try:
            device, gpu = bench_gpu()
            print(f"\n[B] {device.upper()} · 候选打分前向")
            for batch, row in gpu.items():
                print(f"    batch={batch:3d}：{row['decisions_per_second']:,.0f} 次/秒"
                      f"（{row['ms_per_batch']:.1f} ms/批）")
        except Exception as error:  # noqa: BLE001 - 没装 torch 也要能跑完
            print(f"\n[B] 跳过 GPU 基准：{error}")

    # ---- C. 端到端 ----
    selfplay = bench_selfplay(args.selfplay_games)

    if selfplay:
        print(f"\n[C] 端到端自我对弈（{selfplay['device']}，{selfplay['checkpoint']}）")
        print(f"    {selfplay['seconds_per_game']*1000:.0f} ms/局，"
              f"每秒 {selfplay['games_per_second']:.2f} 局")

    # ---- D. 估算 ----
    print("\n[D] 规模估算（按不同策略）")
    print(f"    {'策略':<12}{'每秒局数':>10}{'100 万局':>12}{'1000 万局':>13}{'1000 万局数据':>15}")

    candidates = {
        "随机(单核)": cpu["random"]["games_per_second"],
        "启发式(单核)": cpu["heuristic"]["games_per_second"],
    }

    if selfplay:
        candidates["端到端(模型)"] = selfplay["games_per_second"]

    estimates = {}

    for label, rate in candidates.items():
        row = estimate(rate)
        estimates[label] = row
        m1 = row[1_000_000]
        m10 = row[10_000_000]
        print(f"    {label:<12}{rate:>10.1f}{m1['hours']:>11.1f}h{m10['hours']:>12.1f}h"
              f"{m10['gigabytes']:>14.0f}GB")

    print("\n说明：")
    print("  · 「单核」= 一个 Python 进程跑一局；多核并行按核数近似线性放大。")
    print("  · 数据量按每条决策约 700 字节估算（实际 JSONL 平均更大，含手牌与候选数）。")
    print("=" * 68)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
