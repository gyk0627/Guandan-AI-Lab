"""GuanDan Benchmark：一台机器的综合性能测试，输出可用于选型的报告。

分模块测（可选跑哪几个）：

* ``cpu``       纯 CPU 模拟吞吐：启发式对局 局/秒、决策/秒（不碰 GPU）
* ``inference`` 神经网络推理：不同 batch 下的 推理次数/秒、显存、功耗、温度
                    以及"CPU 端数据准备"耗时（区分是推理慢还是喂数据慢）
* ``train``     训练吞吐：行为克隆与价值网络各跑 N 轮，报每轮耗时与样本/秒
* ``export``    数据导出：固定局数的导出速度（样本/秒）
* ``pipeline``  完整流水线：生成对局 → 导出 → 训练 1 轮，端到端耗时

用法：

    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.benchmark_suite
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.benchmark_suite --modules cpu,inference
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.benchmark_suite --compare evaluation\\benchmark_xxx.json

输出：终端表格 + ``evaluation/benchmark_<机器名>_<时间>.json``，
后者可以直接拿去和别的机器对比（``--compare``）。
"""

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np
import torch

from tools.gpu_metrics import EngineSampler

REPO = Path(__file__).resolve().parent.parent
TMP = REPO / ".test_tmp" / "benchmark"
SAMPLER = REPO / "tools" / "_sampler.ps1"
OUT_DIR = REPO / "evaluation"
DATA_DIR = REPO / "training" / "data"


# ---------------------------------------------------------------- 小工具
def display_width(text):
    return sum(2 if unicodedata.east_asian_width(char) in ("W", "F") else 1 for char in str(text))


def pad(text, width, align="left"):
    text = str(text)
    gap = max(0, width - display_width(text))

    return (" " * gap + text) if align == "right" else (text + " " * gap)


def human_time(seconds):
    if seconds is None:
        return "-"

    if seconds < 60:
        return f"{seconds:.1f} 秒"

    if seconds < 3600:
        return f"{seconds / 60:.1f} 分"

    return f"{seconds / 3600:.1f} 小时"


def latest_npz():
    files = sorted(DATA_DIR.glob("*.npz"), key=lambda path: path.stat().st_mtime)

    return files[-1] if files else None


def host_info():
    gpu_name = None

    try:
        output = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            text=True, timeout=20,
        ).strip()
        gpu_name = output.splitlines()[0] if output else None
    except Exception:  # noqa: BLE001 - 拿不到就留空
        pass

    return {
        "host": platform.node(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "gpu": gpu_name,
    }


class Sampler:
    """在测量期间采样整机 CPU/GPU 指标。"""

    def __init__(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.csv = TMP / f"samples_{int(time.time() * 1000)}.csv"
        self.process = None

    def __enter__(self):
        self.process = subprocess.Popen(
            [sys.executable, "-X", "utf8", "-m", "tools.resource_sampler",
             "--out", str(self.csv), "--seconds", "3600", "--interval-ms", "200"],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        return self

    def __exit__(self, *exc):
        if self.process:
            self.process.terminate()

            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()

        self.summary = self._summarize()

        return False

    def _summarize(self):
        if not self.csv.exists():
            return {}

        columns = {name: [] for name in
                   ("cpu", "free", "gpu", "gpu_mem", "power", "temp", "clock", "per_core")}
        keys = ("cpu", "free", "gpu", "gpu_mem", "power", "temp", "clock")

        for line in self.csv.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split(",")

            if len(parts) < 8:
                continue

            for key, raw in zip(keys, parts[1:8]):
                try:
                    columns[key].append(float(raw))
                except ValueError:
                    pass

            if len(parts) >= 9 and parts[8].strip():
                cores = []

                for raw in parts[8].split("|"):
                    try:
                        cores.append(float(raw))
                    except ValueError:
                        pass

                if cores:
                    columns["per_core"].append(cores)

        def avg(values, digits=1):
            return round(sum(values) / len(values), digits) if values else None

        per_core_avg = None
        busy_cores = None

        if columns["per_core"]:
            count = min(len(row) for row in columns["per_core"])
            means = [
                sum(row[index] for row in columns["per_core"]) / len(columns["per_core"])
                for index in range(count)
            ]
            per_core_avg = [round(value, 1) for value in means]
            busy_cores = sum(1 for value in means if value >= 50)

        return {
            "cpu_avg": avg(columns["cpu"]),
            "free_mem_mb": avg(columns["free"]),
            "gpu_avg": avg(columns["gpu"], 0),
            "gpu_peak": round(max(columns["gpu"]), 0) if columns["gpu"] else None,
            "gpu_mem_peak_mb": round(max(columns["gpu_mem"]), 0) if columns["gpu_mem"] else None,
            "power_avg_w": avg(columns["power"]),
            "power_peak_w": round(max(columns["power"]), 1) if columns["power"] else None,
            "temp_peak_c": round(max(columns["temp"]), 0) if columns["temp"] else None,
            "gpu_clock_avg_mhz": avg(columns["clock"], 0),
            "gpu_clock_peak_mhz": round(max(columns["clock"]), 0) if columns["clock"] else None,
            "per_core_avg": per_core_avg,
            "cores_busy_over_50pct": busy_cores,
            "samples": len(columns["cpu"]),
        }


# ---------------------------------------------------------------- 各模块
def module_cpu(games=40):
    """纯 CPU：启发式对局吞吐（不加载神经网络）。"""
    from game_engine.game_state import GameState
    from players.heuristic import choose_move
    import random

    decisions = 0
    started = time.perf_counter()

    for index in range(games):
        game = GameState.new_game(seed=1_000_000 + index, level="2")
        rng = random.Random(index)

        while not game.game_over:
            player = game.current_player
            legal = game.get_legal_moves(player)
            action = choose_move(game.hands[player], legal, rng=rng,
                                 game_state=game, player=player)
            decisions += 1

            if action is None:
                game.pass_turn(player)
            else:
                game.play(player, action)

    elapsed = time.perf_counter() - started

    return {
        "games": games,
        "decisions": decisions,
        "seconds": round(elapsed, 2),
        "games_per_second": round(games / elapsed, 2),
        "decisions_per_second": round(decisions / elapsed, 1),
    }


def module_inference(batch_sizes=(1, 8, 16, 32, 64, 128), min_seconds=1.0, width=30):
    """GPU 推理独立测试：不跑对局，只压网络。

    每个 batch 至少跑 ``min_seconds`` 秒（而不是固定次数），
    否则测得太快，资源采样器只来得及采一两个点，GPU 利用率会失真。
    """
    from training.model import CandidateScorer
    from training.state_encoder import ACTION_DIM, STATE_DIM, encode_action, encode_state
    from game_engine.game_state import GameState

    if not torch.cuda.is_available():
        return {"error": "CUDA 不可用"}

    device = torch.device("cuda")
    model = CandidateScorer(STATE_DIM, ACTION_DIM).to(device)
    model.eval()

    rows = []

    for batch_size in batch_sizes:
        states = torch.randn(batch_size, STATE_DIM, device=device)
        candidates = torch.randn(batch_size, width, ACTION_DIM, device=device)
        mask = torch.ones(batch_size, width, device=device)

        for _ in range(20):  # 预热
            with torch.no_grad():
                model(states, candidates, mask)

        torch.cuda.synchronize()
        started = time.perf_counter()
        steps = 0

        while True:
            with torch.no_grad():
                model(states, candidates, mask)

            steps += 1

            if steps % 10 == 0:
                torch.cuda.synchronize()

                if time.perf_counter() - started >= min_seconds:
                    break

        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        inferences = steps * batch_size

        rows.append({
            "batch_size": batch_size,
            "inferences": inferences,
            "seconds": round(elapsed, 3),
            "inferences_per_second": round(inferences / elapsed, 1),
            "ms_per_batch": round(elapsed / steps * 1000, 2),
        })

    # CPU 端数据准备也要单独计时：否则分不清是推理慢还是喂数据慢
    game = GameState.new_game(seed=555, level="2")
    encode_started = time.perf_counter()

    for _ in range(200):
        encode_state(game, 0)

    state_ms = (time.perf_counter() - encode_started) / 200 * 1000

    sample_cards = [("S", "3"), ("H", "4"), ("C", "5")]
    action_started = time.perf_counter()

    for _ in range(200 * width):
        encode_action(sample_cards, "2")

    action_ms = (time.perf_counter() - action_started) / (200 * width) * 1000

    return {
        "rows": rows,
        "encode_state_ms": round(state_ms, 3),
        "encode_action_ms": round(action_ms, 3),
        "per_decision_prepare_ms": round(state_ms + action_ms * 20, 2),
    }


def module_train(epochs=1, data_path=None):
    """训练吞吐：行为克隆 + 价值网络，各跑 epochs 轮（真跑）。"""
    from training import train_bc, train_value

    data_path = data_path or latest_npz()

    if data_path is None:
        return {"error": "没有 npz 数据"}

    TMP.mkdir(parents=True, exist_ok=True)

    bc_out = TMP / "bench_bc.pt"
    started = time.perf_counter()
    bc = train_bc.train(data_path=data_path, epochs=epochs, batch_size=64,
                        out_path=bc_out, verbose=False)
    bc_seconds = time.perf_counter() - started

    value_out = TMP / "bench_value.pt"
    started = time.perf_counter()
    value = train_value.train(data_path=data_path, epochs=epochs, batch_size=256,
                              out_path=value_out, verbose=False)
    value_seconds = time.perf_counter() - started

    for path in (bc_out, value_out):
        path.unlink(missing_ok=True)

    return {
        "epochs": epochs,
        "bc_seconds_per_epoch": round(bc_seconds / epochs, 2),
        "bc_best_val_acc": round(bc["best_val_acc"], 4),
        "value_seconds_per_epoch": round(value_seconds / epochs, 2),
        "value_best_val_auc": round(value["best_val_auc"], 4),
    }


def module_export(games=40):
    """导出吞吐：先生成若干局，再导出，报样本/秒。"""
    from training.export_dataset import export
    from training.self_play import run_self_play

    TMP.mkdir(parents=True, exist_ok=True)
    source = TMP / "bench_export.jsonl"

    run_self_play(
        games=games,
        seats=("heuristic", "heuristic", "heuristic", "heuristic"),
        seed_start=1_100_000,
        out_path=source,
        verbose=False,
    )

    started = time.perf_counter()
    _, meta = export(source, out_path=TMP / "bench_export.npz")
    elapsed = time.perf_counter() - started

    for path in (source, TMP / "bench_export.npz"):
        path.unlink(missing_ok=True)

    samples = int(meta["samples"])

    return {
        "games": games,
        "samples": samples,
        "seconds": round(elapsed, 2),
        "samples_per_second": round(samples / elapsed, 1),
        "games_per_second": round(games / elapsed, 2),
    }


def module_pipeline(games=12):
    """完整流水线：自我对弈 → 导出 → 训练 1 轮。"""
    from training.export_dataset import export
    from training.self_play import run_self_play
    from training import train_bc

    TMP.mkdir(parents=True, exist_ok=True)
    source = TMP / "bench_pipe.jsonl"
    npz = TMP / "bench_pipe.npz"

    started = time.perf_counter()
    run_self_play(
        games=games,
        seed_start=1_200_000,
        temperature=1.0,
        epsilon=0.05,
        out_path=source,
        verbose=False,
    )
    gen_seconds = time.perf_counter() - started

    started = time.perf_counter()
    _, meta = export(source, out_path=npz)
    export_seconds = time.perf_counter() - started

    started = time.perf_counter()
    train_bc.train(data_path=npz, epochs=1, batch_size=64,
                   out_path=TMP / "bench_pipe.pt", verbose=False)
    train_seconds = time.perf_counter() - started

    total = gen_seconds + export_seconds + train_seconds

    for path in (source, npz, TMP / "bench_pipe.pt", TMP / "bench_pipe.json"):
        path.unlink(missing_ok=True)

    return {
        "games": games,
        "samples": int(meta["samples"]),
        "generate_seconds": round(gen_seconds, 2),
        "export_seconds": round(export_seconds, 2),
        "train_seconds": round(train_seconds, 2),
        "total_seconds": round(total, 2),
        "seconds_per_game_end_to_end": round(total / games, 2),
    }


# ---------------------------------------------------------------- 报告
def print_report(result):
    info = result["host"]
    print("\n" + "=" * 78)
    print("GuanDan Benchmark 报告")
    print("=" * 78)
    print(f"机器：{info['host']}  ({info['platform']})")
    print(f"CPU ：{info['processor']}  {info['cpu_count']} 逻辑核")
    print(f"GPU ：{info['gpu']}   CUDA={info['cuda_available']}")
    print(f"环境：Python {info['python']} / torch {info['torch']}")
    print("-" * 78)

    modules = result["modules"]

    if "cpu" in modules:
        row = modules["cpu"]
        print(f"CPU 模拟      {row['games_per_second']:>8.2f} 局/秒"
              f"   {row['decisions_per_second']:>8.1f} 决策/秒")

    if "inference" in modules and "rows" in modules["inference"]:
        row = modules["inference"]
        print("GPU 推理：")
        print(f"  {'batch':>6}{'推理/秒':>12}{'每批耗时ms':>14}")

        for item in row["rows"]:
            print(f"  {item['batch_size']:>6}{item['inferences_per_second']:>12.1f}"
                  f"{item['ms_per_batch']:>14.2f}")

        print(f"  数据准备：状态 {row['encode_state_ms']:.3f} ms + "
              f"每候选 {row['encode_action_ms']:.3f} ms")

    if "train" in modules and "error" not in modules["train"]:
        row = modules["train"]
        print(f"训练          BC {row['bc_seconds_per_epoch']:>6.2f} 秒/轮"
              f"   value {row['value_seconds_per_epoch']:>6.2f} 秒/轮")

    if "export" in modules:
        row = modules["export"]
        print(f"数据导出      {row['samples_per_second']:>8.1f} 样本/秒"
              f"   {row['games_per_second']:>6.2f} 局/秒")

    if "pipeline" in modules:
        row = modules["pipeline"]
        print(f"完整流水线    端到端 {row['seconds_per_game_end_to_end']:>6.2f} 秒/局"
              f"（生成 {row['generate_seconds']}s + 导出 {row['export_seconds']}s"
              f" + 训练 {row['train_seconds']}s）")

    resources = result.get("resources", {})

    if resources:
        print("-" * 78)
        print(f"资源：CPU {resources.get('cpu_avg', '-')}%  "
              f"GPU 峰值 {resources.get('gpu_peak', '-')}%（均值 {resources.get('gpu_avg', '-')}%）  "
              f"显存峰值 {resources.get('gpu_mem_peak_mb', '-')} MB  "
              f"功耗均值 {resources.get('power_avg_w', '-')} W  "
              f"温度峰值 {resources.get('temp_peak_c', '-')} ℃  "
              f"GPU 频率均值 {resources.get('gpu_clock_avg_mhz', '-')} MHz")

        if resources.get("cores_busy_over_50pct") is not None:
            print(f"      忙核数（>50%）：{resources['cores_busy_over_50pct']} / "
                  f"{len(resources.get('per_core_avg') or [])}")

        engine = (resources.get("engine") or {}).get("3d")

        if engine:
            print(f"GPU 占用(3D 引擎，任务管理器口径)："
                  f"峰值 {engine['max']:.0f}%  p95 {engine['p95']:.0f}%  "
                  f"均值 {engine['mean']:.0f}%   "
                  f"（≥80% 的采样占 {engine['over_80_pct']:.0f}%）")
            print("      注：nvidia-smi 的 utilization 在 Windows 上会低估，"
                  "判断\"显卡是否打满\"请看这一行")

    print("=" * 78)


def compare_with(baseline_path, result):
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    print("\n" + "=" * 78)
    print(f"与基线对比：{Path(baseline_path).name}")
    print("=" * 78)
    print(f"基线机器：{baseline['host']['host']} / {baseline['host']['gpu']}")
    print(f"当前机器：{result['host']['host']} / {result['host']['gpu']}")
    print("-" * 78)

    for key, label in (
        ("cpu", "局/秒"), ("export", "样本/秒"),
    ):
        old = baseline["modules"].get(key, {}).get(
            "games_per_second" if key == "cpu" else "samples_per_second"
        )
        new = result["modules"].get(key, {}).get(
            "games_per_second" if key == "cpu" else "samples_per_second"
        )

        if old and new:
            print(f"{key:<10}{label:<8} 基线 {old:>10.2f}   当前 {new:>10.2f}   "
                  f"倍数 {new / old:>6.2f}x")

    old_pipe = baseline["modules"].get("pipeline", {}).get("seconds_per_game_end_to_end")
    new_pipe = result["modules"].get("pipeline", {}).get("seconds_per_game_end_to_end")

    if old_pipe and new_pipe:
        print(f"{'pipeline':<10}{'秒/局':<8} 基线 {old_pipe:>10.2f}   当前 {new_pipe:>10.2f}   "
              f"倍数 {old_pipe / new_pipe:>6.2f}x")

    print("=" * 78)


def main(argv=None):
    parser = argparse.ArgumentParser(description="GuanDan Benchmark：机器性能测试")
    parser.add_argument("--modules", default="cpu,inference,train,export,pipeline")
    parser.add_argument("--games", type=int, default=40, help="cpu/export 模块的对局数")
    parser.add_argument("--pipe-games", type=int, default=12)
    parser.add_argument("--train-epochs", type=int, default=1)
    parser.add_argument("--compare", default=None)
    parser.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    modules = [part.strip() for part in args.modules.split(",") if part.strip()]
    data_path = latest_npz()

    result = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host": host_info(),
        "modules": {},
    }

    print("=" * 78)
    print("GuanDan Benchmark 开始")
    print("=" * 78)
    print(f"模块：{modules}")

    with Sampler() as sampler, EngineSampler(TMP / "engine.csv") as engine_sampler:
        for name in modules:
            print(f"  [{name}] 运行中…", end="", flush=True)
            started = time.perf_counter()

            try:
                if name == "cpu":
                    data = module_cpu(games=args.games)
                elif name == "inference":
                    data = module_inference()
                elif name == "train":
                    data = module_train(epochs=args.train_epochs, data_path=data_path)
                elif name == "export":
                    data = module_export(games=args.games)
                elif name == "pipeline":
                    data = module_pipeline(games=args.pipe_games)
                else:
                    data = {"error": f"未知模块 {name}"}
            except Exception as exception:  # noqa: BLE001 - 单模块失败不影响整体
                data = {"error": f"{type(exception).__name__}: {exception}"}

            data["module_seconds"] = round(time.perf_counter() - started, 2)
            result["modules"][name] = data
            print(f"\r  [{name}] 完成（{data['module_seconds']} 秒）")

    result["resources"] = getattr(sampler, "summary", {})
    result["resources"]["engine"] = getattr(engine_sampler, "summary", {})

    print_report(result)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else OUT_DIR / f"benchmark_{stamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{out_path}")

    if args.compare:
        compare_with(args.compare, result)

    shutil.rmtree(TMP, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
