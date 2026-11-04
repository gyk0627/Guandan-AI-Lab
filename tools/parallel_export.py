"""并行导出：把 JSONL 按对局切分，多进程同时导出，再合并成一个 npz。

**为什么需要**：导出要逐局重放 + 重算候选（`training/export_dataset.py`），
实测单进程约 **427 样本/秒**（E17）。这是纯 CPU 工作，天然可以按对局并行。
沙箱不允许 multiprocessing 的命名管道，所以用**子进程扇出**（与
`training/self_play.py::run_parallel_self_play` 同一套路）。

**正确性**：按对局 id 排序后切成连续区间，保证同一局的全部记录落在同一分片；
分片按顺序合并后，行序与单进程 `export()` 完全一致（可逐位比对）。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.parallel_export --workers 4
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.parallel_export training/data/games_xxx.jsonl --workers 8
"""

import argparse
import json
import os
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"


def latest_jsonl():
    files = sorted(DATA_DIR.glob("games_*.jsonl"), key=lambda path: path.stat().st_mtime)

    if not files:
        raise FileNotFoundError("没有 games_*.jsonl，请先采集")

    return files[-1]


def group_by_game(path):
    """按对局分组记录，保持每局内部的原始顺序。"""
    games = OrderedDict()

    with Path(path).open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue

            record = json.loads(line)
            game = record.get("game")

            if game is None:
                raise ValueError("记录缺少 game 字段，无法按局切分")

            games.setdefault(game, []).append(line)

    return games


def split_sorted(games, workers):
    """按对局 id 排序后切成连续区间。

    这样「分片顺序合并」得到的行序与单进程 `export()`（按 game_id 排序）完全一致，
    既保证结果可逐位比对，也保证训练数据顺序确定。
    """
    ordered = sorted(games)
    total = len(ordered)
    size = (total + workers - 1) // workers
    buckets = []

    for index in range(workers):
        chunk = ordered[index * size:(index + 1) * size]
        buckets.append([(game, games[game]) for game in chunk])

    return buckets


def write_shards(buckets, shard_dir):
    shards = []

    for index, bucket in enumerate(buckets):
        if not bucket:
            continue

        path = shard_dir / f"shard_{index:02d}.jsonl"

        with path.open("w", encoding="utf-8") as handle:
            for _game, lines in bucket:
                handle.write("".join(lines))

        shards.append((path, len(bucket), sum(len(lines) for _g, lines in bucket)))

    return shards


def run_shards(shards, shard_dir, no_verify):
    """同时启动各分片子进程（每个进程内部是单线程 CPU 重放）。"""
    processes = []

    for path, _games, _lines in shards:
        out_path = shard_dir / (path.stem + ".npz")
        log_path = shard_dir / (path.stem + ".log")
        command = [
            sys.executable, "-X", "utf8", "-u",
            "-m", "training.export_dataset", str(path), "--out", str(out_path),
        ]

        if no_verify:
            command.append("--no-verify")

        log = log_path.open("w", encoding="utf-8", errors="replace")
        process = subprocess.Popen(
            command,
            cwd=str(REPO),
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        processes.append((process, out_path, log_path, log, path.stem))

    started = time.perf_counter()
    results = []

    for process, out_path, log_path, log, name in processes:
        returncode = process.wait()
        log.close()

        if returncode != 0:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            raise RuntimeError(
                f"分片 {name} 导出失败（退出码 {returncode}）：\n" + "\n".join(tail)
            )

        results.append(out_path)

    elapsed = time.perf_counter() - started

    return results, elapsed


def main(argv=None):
    parser = argparse.ArgumentParser(description="并行导出 JSONL -> npz")
    parser.add_argument("path", nargs="?", help="JSONL；省略时取 data 下最新")
    parser.add_argument("--out", default=None, help="输出 npz；默认 xxx.parallel.npz")
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--keep-shards", action="store_true", help="保留分片（调试用）")

    args = parser.parse_args(argv)

    path = Path(args.path) if args.path else latest_jsonl()
    out_path = Path(args.out) if args.out else path.with_suffix(".parallel.npz")

    print("=" * 78)
    print("并行导出：JSONL -> npz")
    print("=" * 78)
    print(f"输入：{path.name}   分片数：{args.workers}   校验：{'关' if args.no_verify else '开'}")

    started = time.perf_counter()
    games = group_by_game(path)
    buckets = split_sorted(games, args.workers)
    read_seconds = time.perf_counter() - started

    shard_dir = out_path.parent / f".export_shards_{os.getpid()}"
    shard_dir.mkdir(parents=True, exist_ok=True)

    try:
        shards = write_shards(buckets, shard_dir)
        print(f"对局 {len(games)} 个，切成 {len(shards)} 片（读入 {read_seconds:.1f}s）")
        print("-" * 78)
        print(f"{'分片':>8}{'对局':>7}{'记录行':>9}")

        for shard_path, games_count, lines in shards:
            print(f"{shard_path.stem:>8}{games_count:>7}{lines:>9}")

        results, elapsed = run_shards(shards, shard_dir, args.no_verify)

        from training.merge_datasets import merge

        merged_path, meta = merge(results, out_path)

        total_seconds = time.perf_counter() - started
        serial_seconds = elapsed * len(results)

        print("-" * 78)
        print(f"并行墙钟：{elapsed:.1f}s   串行估计：{serial_seconds:.1f}s"
              f"   加速比：{serial_seconds / max(elapsed, 1e-9):.2f}×")
        print(f"总墙钟（含读入+合并）：{total_seconds:.1f}s")
        print(f"样本：{meta['samples']:,}   局数：{meta['games']}   "
              f"平均候选：{meta['avg_candidates']}")
        print(f"输出：{merged_path}")
    finally:
        if not args.keep_shards:
            for item in shard_dir.glob("*"):
                try:
                    item.unlink()
                except OSError:
                    pass

            try:
                shard_dir.rmdir()
            except OSError:
                pass

    print("=" * 78)
    print("注意：并行导出省的是墙钟时间，总 CPU 时间与单进程相近（受核数限制）。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
