"""把多份导出好的 npz 合并成一份数据集。

数据是分批采集的（不同种子区间），训练时合并成一份更省事。
合并时唯一容易出错的地方是 `cand_offsets`：它必须整体平移，
否则第二条数据集的候选会指到第一条的区间里去。

用法：

    .\\.venv\\Scripts\\python.exe -m training.merge_datasets
    .\\.venv\\Scripts\\python.exe -m training.merge_datasets --out training/data/merged.npz a.npz b.npz
"""

import argparse
import json
from pathlib import Path

import numpy as np

DATA_DIR = Path(__file__).resolve().parent / "data"

SCALAR_KEYS = (
    "y_index",
    "hand_ranks",
    "team_win",
    "level_up",
    "is_pass",
    "game_index",
)


def merge(paths, out_path=None):
    paths = [Path(path) for path in paths]

    if not paths:
        raise ValueError("至少要给一个 npz")

    arrays = [np.load(path) for path in paths]

    states = np.concatenate([a["states"] for a in arrays], axis=0)

    has_groups = all("cand_groups" in a.files for a in arrays)
    cand_flat = np.concatenate([a["cand_flat"] for a in arrays], axis=0)
    cand_groups = (
        np.concatenate([a["cand_groups"] for a in arrays], axis=0)
        if has_groups
        else None
    )

    offsets = [np.zeros(1, dtype=np.int64)]
    total = 0

    for array in arrays:
        local = array["cand_offsets"].astype(np.int64)

        # local[0] 恒为 0，不能重复计入；其余端点整体平移 total
        offsets.append(local[1:] + total)
        total += int(local[-1])

    cand_offsets = np.concatenate(offsets).astype(np.int32)

    if len(cand_offsets) - 1 != len(states):
        raise RuntimeError(
            f"合并后样本数 {len(states)} 与偏移数 {len(cand_offsets) - 1} 不一致"
        )

    if int(cand_offsets[-1]) != len(cand_flat):
        raise RuntimeError("合并后候选总数与偏移末尾不一致")

    merged = {"states": states, "cand_flat": cand_flat, "cand_offsets": cand_offsets}

    if cand_groups is not None:
        merged["cand_groups"] = cand_groups

    for key in SCALAR_KEYS:
        if not all(key in a.files for a in arrays):
            continue

        parts = []
        offset = 0

        for array in arrays:
            part = array[key]

            if key == "game_index":
                part = part + offset
                offset += int(part.max()) + 1

            parts.append(part)

        merged[key] = np.concatenate(parts, axis=0)

    out_path = Path(out_path) if out_path else DATA_DIR / "merged.npz"
    np.savez_compressed(out_path, **merged)

    meta = {
        "sources": [path.name for path in paths],
        "samples": int(len(states)),
        "candidates": int(len(cand_flat)),
        "games": int(merged["game_index"].max()) + 1 if "game_index" in merged else None,
        "avg_candidates": round(len(cand_flat) / max(len(states), 1), 2),
        "has_groups": bool(has_groups),
    }

    out_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 60)
    print("合并完成")
    print("=" * 60)
    print(f"来源：{[path.name for path in paths]}")
    print(f"样本 {meta['samples']}   局数 {meta['games']}   平均候选 {meta['avg_candidates']}")
    print(f"输出：{out_path}")

    return out_path, meta


def main(argv=None):
    parser = argparse.ArgumentParser(description="合并多份数据集 npz")
    parser.add_argument("paths", nargs="*", help="要合并的 npz；省略时取 data 下全部 games_*.npz")
    parser.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    paths = args.paths or sorted(DATA_DIR.glob("games_*.npz"))

    if not paths:
        raise FileNotFoundError(f"{DATA_DIR} 下没有可合并的 npz")

    merge(paths, out_path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
