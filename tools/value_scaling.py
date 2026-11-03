"""价值网络的数据量缩放曲线：AUC 随训练局数怎么变？

回答一个具体问题：E04 的 AUC 0.635 是"数据不够"还是"分布不对"？

做法：从同一份 5000 局数据里，按固定的随机种子抽取前 N 局（N = 300 / 1000 / 2000 / 5000），
每个规模单独训练一个价值网络，报告验证 AUC。因为数据来源完全相同，
唯一的变量就是**局数**——这是受控对比。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.value_scaling
"""

import argparse
import json
import tempfile
from pathlib import Path

import numpy as np

from training import train_value

REPO = Path(__file__).resolve().parent.parent


def subset_dataset(source, games, seed=0):
    """按局抽样，返回 (临时 npz 路径, 实际局数, 样本数)。

    npz 里候选是扁平化存储的（cand_flat + cand_offsets），
    所以不能简单按样本行掩码，必须按 offset 重建候选段。
    """
    data = np.load(source, allow_pickle=False)

    game_index = data["game_index"]
    unique = np.unique(game_index)
    rng = np.random.default_rng(seed)
    chosen = rng.permutation(unique)[: min(games, len(unique))]
    keep = np.isin(game_index, chosen)

    kept = np.flatnonzero(keep)

    offsets = data["cand_offsets"]
    starts = offsets[kept]
    ends = offsets[kept + 1]

    cand_flat = data["cand_flat"]
    cand_groups = data["cand_groups"]

    new_flat = np.concatenate([cand_flat[a:b] for a, b in zip(starts, ends)])
    new_groups = np.concatenate([cand_groups[a:b] for a, b in zip(starts, ends)])
    lengths = ends - starts
    new_offsets = np.concatenate([[0], np.cumsum(lengths)]).astype(np.int32)

    # 局编号重新映射成 0..G-1
    remap = {old: new for new, old in enumerate(np.unique(game_index[keep]))}

    subset = {
        "states": data["states"][keep],
        "cand_flat": new_flat,
        "cand_groups": new_groups,
        "cand_offsets": new_offsets,
        "y_index": data["y_index"][keep],
        "hand_ranks": data["hand_ranks"][keep],
        "team_win": data["team_win"][keep],
        "level_up": data["level_up"][keep],
        "is_pass": data["is_pass"][keep],
        "game_index": np.array(
            [remap[int(g)] for g in game_index[keep]], dtype=np.int32
        ),
    }

    handle = tempfile.NamedTemporaryFile(suffix=".npz", delete=False)
    handle.close()
    np.savez_compressed(handle.name, **subset)

    return Path(handle.name), len(remap), int(keep.sum())


def main(argv=None):
    parser = argparse.ArgumentParser(description="价值网络数据量缩放曲线")
    parser.add_argument("--data", default=None)
    parser.add_argument("--sizes", default="300,1000,2000,5000")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)

    args = parser.parse_args(argv)

    source = Path(args.data) if args.data else sorted(
        (REPO / "training" / "data").glob("games_*.npz"),
        key=lambda path: path.stat().st_mtime,
    )[-1]

    sizes = [int(part) for part in args.sizes.split(",")]

    print("=" * 66)
    print("价值网络 · 数据量缩放曲线")
    print("=" * 66)
    print(f"数据来源：{source.name}")
    print(f"规模点：{sizes}")
    print("-" * 66)

    rows = []

    for games in sizes:
        path, actual_games, samples = subset_dataset(source, games, seed=args.seed)

        try:
            result = train_value.train(
                data_path=path,
                epochs=args.epochs,
                batch_size=256,
                seed=args.seed,
                verbose=False,
                # 缩放曲线只需要 AUC，不要把 checkpoint 写进 models/
                out_path=path.with_suffix(".model.pt"),
            )
        finally:
            path.unlink(missing_ok=True)

        rows.append(
            {
                "games": actual_games,
                "samples": samples,
                "best_epoch": result["best_epoch"],
                "val_auc": round(result["best_val_auc"], 4),
            }
        )

        print(f"  {actual_games:5d} 局 / {samples:7d} 条 | "
              f"最佳第 {result['best_epoch']:2d} 轮 | 验证 AUC {result['best_val_auc']:.4f}")

    out = REPO / "evaluation" / "value_scaling.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print("-" * 66)
    print(f"结果：{out}")
    print("=" * 66)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
