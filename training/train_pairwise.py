"""成对比较训练（Preference / pairwise ranking）—— 通往 RLHF 的第一步。

与行为克隆的区别
----------------
* 行为克隆：对全部候选做 softmax 分类，目标是"提高老师动作的概率"。
* 本训练：只比较**两张牌**——老师选的（正样本）vs 一个陪衬（负样本），
  目标是"让老师的分数比陪衬高"。这正是 RLHF 里奖励模型的训练形式，
  只是这里用**启发式老师**代替人类偏好。

为什么用「难负样本」
--------------------
E13 发现价值网络在**同一个局面里**几乎没有分辨力（28.81%，随机 20%）。
随机负样本太容易，学不到精细差别；所以负样本优先从"同牌型、同张数、但不是老师那张"
的候选里挑（例如老师打的是对 9，负样本就挑另一对），逼模型学会看细微之处。

产出
----
保存成与 `players/neural.py` 完全兼容的 checkpoint（同样的 `CandidateScorer` 结构），
因此可以直接被评估工具、界面、自我对弈使用。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m training.train_pairwise --epochs 30 --batch-size 256
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from training.dataset import load_dataset, split_by_game
from training.model import CandidateScorer

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

PATTERN_SLICE = slice(54, 63)   # 动作向量里牌型 one-hot 的位置
COUNT_INDEX = 63                # 动作向量里张数的位置


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def choose_negative(cand_flat, offsets, index):
    """为一个样本挑负样本的全局下标（难负样本优先）。"""
    start, end = offsets[index], offsets[index + 1]
    y = start + int(np.argmax(np.zeros(1)))  # 占位，实际由调用方传入 y_index

    return start, end, y


def build_pairs(data, indices, seed=0, hard_ratio=0.75):
    """为每个样本选一个负样本，返回 (pos_global, neg_global) 数组。

    难负样本定义：同牌型 + 同张数 + 不是老师那张；找不到就退回随机负样本。
    """
    rng = np.random.default_rng(seed)

    cand_flat = data["cand_flat"]
    offsets = data["cand_offsets"]
    y_index = data["y_index"]

    pos = np.empty(len(indices), dtype=np.int64)
    neg = np.empty(len(indices), dtype=np.int64)

    for position, index in enumerate(indices):
        start = int(offsets[index])
        end = int(offsets[index + 1])
        y = int(y_index[index])

        pos[position] = start + y

        candidates = cand_flat[start:end]
        teacher = candidates[y]
        teacher_pattern = np.argmax(teacher[PATTERN_SLICE])
        teacher_count = teacher[COUNT_INDEX]

        others = np.arange(end - start)
        others = others[others != y]

        if len(others) == 0:
            neg[position] = start + y  # 该样本没有其它候选，稍后过滤
            continue

        if rng.random() < hard_ratio:
            same_pattern = others[
                np.argmax(candidates[others][:, PATTERN_SLICE], axis=1) == teacher_pattern
            ]
            same_count = same_pattern[
                np.isclose(candidates[same_pattern][:, COUNT_INDEX], teacher_count)
            ]

            pool = same_count if len(same_count) else same_pattern
            if len(pool) == 0:
                pool = others
        else:
            pool = others

        neg[position] = start + int(rng.choice(pool))

    return pos, neg


def within_decision_accuracy(model, data, indices, device, batch_size=64):
    """老师动作在**全部候选**里排第一的比例（E13 同款指标）。

    注意：必须传**全量 data** + 索引表。cand_flat 是全局扁平化存储的，
    如果传"子集后的 states"配"全量 offsets"，索引会错位（踩过这个坑）。
    """
    model.eval()

    states = data["states"]
    cand_flat = data["cand_flat"]
    offsets = data["cand_offsets"]
    y_index = data["y_index"]

    indices = np.asarray(indices)
    correct = 0
    total = 0

    with torch.no_grad():
        for start in range(0, len(indices), batch_size):
            chunk = indices[start:start + batch_size]
            starts = offsets[chunk]
            lengths = offsets[chunk + 1] - starts
            width = int(lengths.max())

            batch = len(chunk)
            cand_tensor = np.zeros((batch, width, cand_flat.shape[1]), dtype=np.float32)
            mask = np.zeros((batch, width), dtype=np.float32)

            for row in range(batch):
                begin = int(starts[row])
                length = int(lengths[row])
                cand_tensor[row, :length] = cand_flat[begin:begin + length]
                mask[row, :length] = 1.0

            scores, _ = model(
                torch.from_numpy(states[chunk].astype(np.float32)).to(device),
                torch.from_numpy(cand_tensor).to(device),
                torch.from_numpy(mask).to(device),
            )
            scores = scores.cpu().numpy()

            for row, index in enumerate(chunk):
                correct += int(int(np.argmax(scores[row])) == int(y_index[index]))
                total += 1

    return correct / max(total, 1), total


def train(data_path=None, epochs=30, batch_size=256, lr=1e-3, val_fraction=0.1,
          seed=0, device="auto", out_path=None, verbose=True, hard_ratio=0.75):
    if data_path is None:
        files = sorted(DATA_DIR.glob("games_*.npz"), key=lambda p: p.stat().st_mtime)
        data_path = files[-1]

    data_path = Path(data_path)
    data = load_dataset(data_path)

    train_idx, val_idx = split_by_game(data["game_index"], val_fraction=val_fraction, seed=seed)

    states = data["states"].astype(np.float32)
    cand_flat = data["cand_flat"].astype(np.float32)
    offsets = data["cand_offsets"].astype(np.int64)
    y_index = data["y_index"].astype(np.int64)

    device = pick_device(device)
    torch.manual_seed(seed)
    np.random.seed(seed)

    state_dim = int(states.shape[1])
    action_dim = int(cand_flat.shape[1])

    print("=" * 66)
    print("成对比较训练（Preference / pairwise）")
    print("=" * 66)
    print(f"数据：{data_path.name}   设备：{device}")
    print(f"训练 {len(train_idx)} 条   验证 {len(val_idx)} 条   难负样本比例 {hard_ratio}")

    train_pos, train_neg = build_pairs(data, train_idx, seed=seed, hard_ratio=hard_ratio)
    val_pos, val_neg = build_pairs(data, val_idx, seed=seed + 1, hard_ratio=hard_ratio)

    valid_train = train_pos != train_neg
    train_idx = train_idx[valid_train]
    train_pos, train_neg = train_pos[valid_train], train_neg[valid_train]

    model = CandidateScorer(state_dim, action_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    print(f"可用训练对 {len(train_idx)} 条")
    print("-" * 66)

    history = []
    best = None
    started = time.perf_counter()

    for epoch in range(1, epochs + 1):
        model.train()
        order = np.random.permutation(len(train_idx))
        total_loss = 0.0
        correct = 0
        count = 0

        for start in range(0, len(order), batch_size):
            batch = order[start:start + batch_size]

            state = torch.from_numpy(states[train_idx[batch]]).to(device)
            pos = torch.from_numpy(cand_flat[train_pos[batch]]).unsqueeze(1).to(device)
            neg = torch.from_numpy(cand_flat[train_neg[batch]]).unsqueeze(1).to(device)

            pairs = torch.cat([pos, neg], dim=1)                    # (B, 2, action_dim)
            mask = torch.ones((len(batch), 2), device=device)

            scores, _ = model(state, pairs, mask)                   # (B, 2)
            margin = scores[:, 0] - scores[:, 1]
            loss = F.binary_cross_entropy_with_logits(
                margin, torch.ones_like(margin)
            )

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

            total_loss += loss.item() * len(batch)
            correct += int((margin > 0).sum().item())
            count += len(batch)

        train_loss = total_loss / max(count, 1)
        train_acc = correct / max(count, 1)
        val_acc, val_n = within_decision_accuracy(model, data, val_idx, device)

        record = {
            "epoch": epoch,
            "train_loss": round(train_loss, 4),
            "pair_acc": round(train_acc, 4),
            "val_within_decision_acc": round(val_acc, 4),
            "seconds": round(time.perf_counter() - started, 1),
        }
        history.append(record)

        print(f"第 {epoch:02d} 轮 | 成对 loss {train_loss:.4f} 成对准确率 {train_acc:.3f} "
              f"| 验证·决策内排第一 {val_acc:.4f}（{val_n} 条）| {record['seconds']:.0f}s")

        if best is None or val_acc > best["acc"]:
            best = {
                "acc": val_acc,
                "epoch": epoch,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            }

    from training.state_encoder import ENCODER_VERSION

    out_path = Path(out_path) if out_path else MODEL_DIR / f"pairwise_{data_path.stem}.pt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = {
        "model": best["state"],
        "config": model.config(),
        "state_dim": state_dim,
        "action_dim": action_dim,
        "encoder_version": ENCODER_VERSION,
        "trained_on": data_path.name,
        "best_epoch": best["epoch"],
        "best_val_acc": best["acc"],
        "objective": "pairwise_preference",
        "hard_negative_ratio": hard_ratio,
        "history": history,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "seed": seed,
    }

    torch.save(checkpoint, out_path)
    out_path.with_suffix(".json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("-" * 66)
    print(f"最佳轮次：第 {best['epoch']} 轮，验证·决策内排第一 = {best['acc']:.4f}")
    print(f"（同口径参考：行为克隆在同一函数下为 0.8200，即「学比较」并未提高模仿率）")
    print(f"模型：{out_path}")

    return {
        "checkpoint": str(out_path),
        "best_epoch": best["epoch"],
        "best_within_decision_acc": best["acc"],
        "history": history,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="成对比较训练（RLHF 奖励模型的先导版）")
    parser.add_argument("--data", default=None)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--hard-ratio", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--out", default=None)

    args = parser.parse_args(argv)

    train(
        data_path=args.data,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        val_fraction=args.val_fraction,
        seed=args.seed,
        device=args.device,
        out_path=args.out,
        hard_ratio=args.hard_ratio,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
