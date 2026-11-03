"""训练价值网络：给局面打分（当前玩家所在队能否头游）。

为什么单独训这个：

* 行为克隆只会「模仿老师」，它不知道一个局面好不好；
* 有了价值网络，就能做「一步前瞻」——把候选动作都模拟一遍，看哪个走向的胜率更高；
* 这也是后面 SDMC（Monte Carlo 回报）的地基：回报最终就是喂给价值网络。

数据直接复用 training.export_dataset 产出的 npz（里面已经有 team_win 标签）。
按「局」切分训练/验证，避免同一局同时出现在两边。

用法：
    & .\\.venv\\Scripts\\python.exe -m training.train_value
    & .\\.venv\\Scripts\\python.exe -m training.train_value --epochs 30 --batch-size 256
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from training.dataset import load_dataset, split_by_game
from training.model import ValueNet

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_targets(data, target="win"):
    """构造价值训练目标。

    * ``win``  ：硬标签（本队头游 = 1，否则 0），DMC 论文的常规做法；
    * ``soft`` ：软标签 = 0.5 * 胜负 + 0.5 * (升级数 / 3)。

    为什么要软：掼蛋里"赢了但只升 1 级"和"赢 3 级"的局势质量差别很大，
    硬标签把这些信息全抹掉，只会说"赢"。
    这也是 Soft-DMC 的第一层含义——**先把回报软化，再谈软采样**。
    """
    wins = data["team_win"].astype(np.float32)

    if target == "win":
        return wins

    if target == "soft":
        upgrades = data["level_up"].astype(np.float32) / 3.0

        return 0.5 * wins + 0.5 * upgrades

    raise ValueError(f"未知目标类型：{target}")


def auc_score(labels, scores):
    """AUC（无 sklearn）：用秩和公式，处理并列用平均秩。"""
    labels = np.asarray(labels)
    scores = np.asarray(scores)

    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    ranks[order] = np.arange(1, len(scores) + 1)

    # 并列分数取平均秩
    sorted_scores = scores[order]
    start = 0

    for index in range(1, len(sorted_scores) + 1):
        if index == len(sorted_scores) or sorted_scores[index] != sorted_scores[start]:
            if index - start > 1:
                average = (start + 1 + index) / 2.0
                ranks[order[start:index]] = average
            start = index

    positives = labels == 1
    n_pos = positives.sum()
    n_neg = len(labels) - n_pos

    if n_pos == 0 or n_neg == 0:
        return 0.5

    rank_sum = ranks[positives].sum()

    return float((rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def run_epoch(model, states, labels, device, optimizer=None, batch_size=256,
              auc_labels=None):
    """跑一轮。loss 用 labels（可以是软标签），AUC 用 auc_labels（默认与 labels 相同）。

    软标签训练时仍用硬胜负来算 AUC，保证与硬标签实验可比。
    """
    training = optimizer is not None
    model.train(training)

    count = len(states)
    order = np.random.permutation(count) if training else np.arange(count)

    total_loss = 0.0
    total_correct = 0
    all_scores = []
    all_labels = []

    for start in range(0, count, batch_size):
        index = order[start:start + batch_size]

        x = torch.from_numpy(states[index]).to(device)
        y = torch.from_numpy(labels[index].astype(np.float32)).to(device)

        logits = model(x)
        loss = F.binary_cross_entropy_with_logits(logits, y)

        if training:
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

        with torch.no_grad():
            probabilities = torch.sigmoid(logits)
            hard = (
                torch.from_numpy(auc_labels[index].astype(np.float32)).to(device)
                if auc_labels is not None
                else y
            )
            total_correct += int(((probabilities > 0.5) == (hard > 0.5)).sum().item())
            all_scores.append(probabilities.detach().cpu().numpy())
            all_labels.append(hard.detach().cpu().numpy())

        total_loss += loss.item() * len(index)

    scores = np.concatenate(all_scores)
    label_array = np.concatenate(all_labels)

    return {
        "loss": total_loss / count,
        "accuracy": total_correct / count,
        "auc": auc_score(label_array, scores),
        "samples": count,
    }


def train(
    data_path=None,
    epochs=20,
    batch_size=256,
    lr=1e-3,
    val_fraction=0.1,
    seed=0,
    device="auto",
    out_path=None,
    verbose=True,
    weight_decay=0.0,
    dropout=None,
    hidden=None,
    target="win",
):
    if data_path is None:
        files = sorted(DATA_DIR.glob("games_*.npz"), key=lambda p: p.stat().st_mtime)

        if not files:
            raise FileNotFoundError(f"{DATA_DIR} 下没有 npz")

        data_path = files[-1]

    data_path = Path(data_path)
    data = load_dataset(data_path)

    train_idx, val_idx = split_by_game(
        data["game_index"], val_fraction=val_fraction, seed=seed
    )

    states = data["states"]
    hard_labels = data["team_win"].astype(np.int8)
    labels = build_targets(data, target).astype(np.float32)

    dev = pick_device(device)
    torch.manual_seed(seed)
    np.random.seed(seed)

    state_dim = int(states.shape[1])
    model_kwargs = {}

    if dropout is not None:
        model_kwargs["dropout"] = dropout
    if hidden is not None:
        model_kwargs["hidden"] = hidden

    model = ValueNet(state_dim, **model_kwargs).to(dev)
    optimizer = torch.optim.Adam(
        model.parameters(), lr=lr, weight_decay=weight_decay
    )

    if verbose:
        print("=" * 66)
        print("GuanDan AI Lab - 价值网络训练")
        print("=" * 66)
        print(f"数据：{data_path.name}")
        print(f"设备：{dev}   状态维度：{state_dim}")
        print(f"训练 {len(train_idx)} 条   验证 {len(val_idx)} 条   目标：{target}")
        print(f"目标均值（训练）：{float(labels[train_idx].mean()):.4f}"
              f"   硬胜负均值：{float(hard_labels[train_idx].mean()):.4f}")
        print("-" * 66)

    history = []
    best = None
    started = time.perf_counter()

    for epoch in range(1, epochs + 1):
        train_stats = run_epoch(
            model, states[train_idx], labels[train_idx], dev, optimizer, batch_size,
            auc_labels=hard_labels[train_idx],
        )
        val_stats = run_epoch(
            model, states[val_idx], labels[val_idx], dev, None, batch_size,
            auc_labels=hard_labels[val_idx],
        )

        record = {
            "epoch": epoch,
            "train_loss": round(train_stats["loss"], 4),
            "train_auc": round(train_stats["auc"], 4),
            "val_loss": round(val_stats["loss"], 4),
            "val_acc": round(val_stats["accuracy"], 4),
            "val_auc": round(val_stats["auc"], 4),
            "seconds": round(time.perf_counter() - started, 1),
        }
        history.append(record)

        if verbose:
            print(
                f"第 {epoch:02d} 轮 | 训练 loss {record['train_loss']:.4f} "
                f"auc {record['train_auc']:.3f} | 验证 loss {record['val_loss']:.4f} "
                f"acc {record['val_acc']:.3f} auc {record['val_auc']:.3f} "
                f"| {record['seconds']:.0f}s"
            )

        if best is None or val_stats["auc"] > best["auc"]:
            best = {
                "auc": val_stats["auc"],
                "epoch": epoch,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            }

    out_path = (
        Path(out_path)
        if out_path
        else MODEL_DIR / f"value_{data_path.stem}.pt"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = {
        "model": best["state"],
        "config": model.config(),
        "trained_on": data_path.name,
        "best_epoch": best["epoch"],
        "best_val_auc": best["auc"],
        "history": history,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "seed": seed,
    }

    torch.save(checkpoint, out_path)

    if verbose:
        print("-" * 66)
        print(f"最佳轮次：第 {best['epoch']} 轮，验证 AUC = {best['auc']:.4f}")
        print(f"模型：{out_path}")

    return {
        "checkpoint": str(out_path),
        "best_epoch": best["epoch"],
        "best_val_auc": best["auc"],
        "history": history,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="训练价值网络")
    parser.add_argument("--data", default=None)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--out", default=None)
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--dropout", type=float, default=None)
    parser.add_argument("--hidden", type=int, default=None)
    parser.add_argument("--target", default="win", choices=("win", "soft"),
                        help="win=硬胜负标签；soft=0.5*胜负+0.5*升级数/3")

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
        weight_decay=args.weight_decay,
        dropout=args.dropout,
        hidden=args.hidden,
        target=args.target,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
