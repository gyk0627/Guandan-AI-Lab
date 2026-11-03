"""训练用数据集：加载导出的 npz，按「局」切分，按批次补边。

为什么要按局切分：同一局的相邻决策高度相关，如果按样本随机切分，
验证集里会出现训练集同一局的局面，指标会虚高。这里按 game_index 整局切。

为什么要按批次补边：领出时候选动作最多可达 1600+ 个（含逢人配），
如果全局按最大宽度补边，300 局数据就要 10GB 以上。
这里按「批次内实际最大宽度」补边，并把候选数量接近的样本排到一起，进一步省内存。
"""

from pathlib import Path

import numpy as np
import torch

DEFAULT_BATCH_SIZE = 64


def load_dataset(path):
    """读取 export_dataset 产出的 .npz。"""
    data = np.load(Path(path))

    return {name: data[name] for name in data.files}


def candidate_lengths(cand_offsets):
    """每条样本的候选动作数量。"""
    return np.diff(cand_offsets)


def split_by_game(game_index, val_fraction=0.1, seed=0):
    """按局切分训练集 / 验证集，返回下标数组。"""
    games = np.unique(game_index)
    rng = np.random.default_rng(seed)

    shuffled = games.copy()
    rng.shuffle(shuffled)

    n_val = max(1, int(round(len(shuffled) * val_fraction)))
    n_val = min(n_val, max(1, len(shuffled) - 1))

    val_games = np.zeros(int(games.max()) + 1, dtype=bool)
    val_games[shuffled[:n_val]] = True

    is_val = val_games[game_index]

    return np.flatnonzero(~is_val), np.flatnonzero(is_val)


def make_batches(indices, lengths, batch_size=DEFAULT_BATCH_SIZE, shuffle=True, seed=0):
    """把下标切成批次；候选数量接近的排在一起，减少补边浪费。"""
    indices = np.asarray(indices)

    if len(indices) == 0:
        return []

    order = indices[np.argsort(lengths[indices], kind="stable")]
    batches = [
        order[start:start + batch_size]
        for start in range(0, len(order), batch_size)
    ]

    if shuffle:
        rng = np.random.default_rng(seed)
        rng.shuffle(batches)

    return batches


def collate(batch_indices, data, pad_to=None):
    """把一批样本补边成张量。

    返回：
        states (B, STATE_DIM)
        cands  (B, W, ACTION_DIM)   W = 本批最大候选数
        mask   (B, W)               1 表示真实候选
        labels (B,)                 正确动作下标
        values (B,)                 队伍是否头游（0/1）
        groups (B, W) 或 None       候选的策略等价组号，补边处为 -1
    """
    offsets = data["cand_offsets"]
    flat = data["cand_flat"]

    batch_indices = np.asarray(batch_indices)
    starts = offsets[batch_indices]
    lengths = offsets[batch_indices + 1] - starts

    width = int(lengths.max()) if pad_to is None else int(pad_to)

    count = len(batch_indices)
    dim = flat.shape[1]

    cands = np.zeros((count, width, dim), dtype=np.float32)
    mask = np.zeros((count, width), dtype=np.float32)

    groups_array = data.get("cand_groups")
    groups = None

    if groups_array is not None:
        groups = np.full((count, width), -1, dtype=np.int64)

    for row in range(count):
        start = int(starts[row])
        length = int(lengths[row])
        cands[row, :length] = flat[start:start + length]
        mask[row, :length] = 1.0

        if groups is not None:
            groups[row, :length] = groups_array[start:start + length]

    return (
        torch.from_numpy(data["states"][batch_indices].copy()),
        torch.from_numpy(cands),
        torch.from_numpy(mask),
        torch.from_numpy(data["y_index"][batch_indices].astype(np.int64)),
        torch.from_numpy(data["team_win"][batch_indices].astype(np.float32)),
        None if groups is None else torch.from_numpy(groups),
    )


def filter_trivial(indices, lengths, min_candidates=2):
    """去掉「只有唯一选择」的样本。

    这类样本（约 39%）的答案唯一，任何模型的准确率都是 100%，
    它们既不能提供学习信号，又会在损失里占掉近四成的权重，
    把真实决策上的差距掩盖掉。默认从训练/评估里剔除。
    """
    indices = np.asarray(indices)

    if min_candidates <= 1:
        return indices

    return indices[lengths[indices] >= min_candidates]


def batch_stats(data, indices=None):
    """数据集的候选规模统计，用于决定训练时的内存策略。"""
    offsets = data["cand_offsets"]

    if indices is None:
        lengths = candidate_lengths(offsets)
    else:
        indices = np.asarray(indices)
        lengths = offsets[indices + 1] - offsets[indices]

    return {
        "samples": int(len(lengths)),
        "avg": float(lengths.mean()),
        "max": int(lengths.max()),
        "p50": int(np.percentile(lengths, 50)),
        "p95": int(np.percentile(lengths, 95)),
    }
