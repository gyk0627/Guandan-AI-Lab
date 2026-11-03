"""行为克隆（Behavior Cloning）训练脚本。

用启发式 AI 自对弈采出来的数据训练「候选打分」网络：
让人类（这里是启发式）当时选的那一手，在当时的合法动作里得分最高。

注意这不是强化学习，也没有 Monte Carlo 回报：
它只是在模仿启发式，理论上限就是启发式本身。它的作用是
**把表示、模型、训练、评估这条链路跑通**，之后的自我对弈与 SDMC 才在这个骨架上加。

用法：

    .\\.venv\\Scripts\\python.exe -m training.train_bc
    .\\.venv\\Scripts\\python.exe -m training.train_bc --epochs 12 --batch-size 64
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from training.dataset import (
    batch_stats,
    candidate_lengths,
    collate,
    filter_trivial,
    load_dataset,
    make_batches,
    split_by_game,
)
from training.model import CandidateScorer

DATA_DIR = Path(__file__).resolve().parent / "data"
MODEL_DIR = Path(__file__).resolve().parent.parent / "models"

# 按候选数量分桶统计一致率：候选越多，越接近真实决策难度
BUCKETS = ((1, 1), (2, 2), (3, 5), (6, 20), (21, 100), (101, 10 ** 9))


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


def accuracy(scores, labels):
    return (scores.argmax(dim=1) == labels).float().mean().item()


def accuracy_by_bucket(model, data, indices, device):
    """按候选数量分桶统计一致率。

    整体一致率会被「只有唯一选择」的样本抬高（它们恒为 100%），
    分桶看才能知道模型在真正的决策上有多强。
    """
    lengths = candidate_lengths(data["cand_offsets"])
    was_training = model.training
    model.eval()

    stats = {bucket: [0, 0] for bucket in BUCKETS}
    indices = np.asarray(indices)

    with torch.no_grad():
        for start in range(0, len(indices), 256):
            chunk = indices[start:start + 256]
            states, cands, mask, labels, _, _ = collate(chunk, data)
            scores, _ = model(
                states.to(device), cands.to(device), mask.to(device)
            )
            predicted = scores.argmax(dim=1).cpu()

            for row, index in enumerate(chunk):
                length = int(lengths[index])

                for bucket in BUCKETS:
                    if bucket[0] <= length <= bucket[1]:
                        stats[bucket][1] += 1
                        stats[bucket][0] += int(predicted[row] == labels[row])
                        break

    model.train(was_training)

    return stats


def group_policy_loss(scores, labels, groups, mask):
    """置换等价损失：把「同一手牌不同花色排列」的候选当成同一个答案。

    做法是把等价类**边际化**：损失 = -log(这一组所有候选的概率之和)。
    模型只需要把概率质量放进这一组，落在组里哪一张都一样对，
    不必去猜老师当时随机留下的那张花色。

    返回 (loss, member_mask)。
    """
    if groups is None:
        predicted = scores.argmax(dim=1, keepdim=True)
        return F.cross_entropy(scores, labels), predicted == labels.unsqueeze(1)

    label_group = groups.gather(1, labels.unsqueeze(1))     # (B, 1)
    member = (groups == label_group) & (mask > 0)

    log_prob = F.log_softmax(scores, dim=1)
    member_log_prob = log_prob.masked_fill(~member, float("-inf"))

    loss = -torch.logsumexp(member_log_prob, dim=1).mean()

    return loss, member


def policy_loss(scores, labels, groups, mask, mode="ce", group_weight=0.2):
    """策略损失。

    ce    ：普通交叉熵（基准，实测最好）
    group ：置换等价损失（实验：400 局配对检验显著更差）
    mixed ：ce + group_weight × group（想保留花色信号，同时降低对具体花色的惩罚）
    """
    exact_loss = F.cross_entropy(scores, labels)
    group_loss, member = group_policy_loss(scores, labels, groups, mask)

    if mode == "group":
        return group_loss, member

    if mode == "mixed":
        return exact_loss + group_weight * group_loss, member

    return exact_loss, member


def run_epoch(
    model,
    batches,
    data,
    device,
    optimizer=None,
    value_weight=0.5,
    loss_mode="ce",
    group_weight=0.2,
):
    training = optimizer is not None
    model.train(training)

    total_loss = 0.0
    total_acc = 0.0
    total_group_acc = 0.0
    total = 0
    prep_seconds = 0.0
    compute_seconds = 0.0

    for batch in batches:
        prep_started = time.perf_counter()

        states, cands, mask, labels, values, groups = collate(batch, data)
        states = states.to(device)
        cands = cands.to(device)
        mask = mask.to(device)
        labels = labels.to(device)
        values = values.to(device)

        if groups is not None:
            groups = groups.to(device)

        prep_seconds += time.perf_counter() - prep_started

        compute_started = time.perf_counter()

        scores, value = model(states, cands, mask)

        if loss_mode == "group":
            loss_policy, member = group_policy_loss(scores, labels, groups, mask)
        else:
            loss_policy, member = policy_loss(
                scores, labels, groups, mask, loss_mode, group_weight
            )

        loss_value = F.binary_cross_entropy_with_logits(value, values)
        loss = loss_policy + value_weight * loss_value

        if training:
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()

        with torch.no_grad():
            predicted = scores.argmax(dim=1, keepdim=True)
            exact = (predicted.squeeze(1) == labels).float().mean().item()
            in_group = member.gather(1, predicted).float().mean().item()

        compute_seconds += time.perf_counter() - compute_started

        size = len(batch)
        total += size
        total_loss += loss.item() * size
        total_acc += exact * size
        total_group_acc += in_group * size

    return {
        "loss": total_loss / max(total, 1),
        "acc": total_acc / max(total, 1),
        "group_acc": total_group_acc / max(total, 1),
        "samples": total,
        # 数据准备（collate + 搬上 GPU）与计算分开计时，便于判断瓶颈在哪
        "prep_seconds": round(prep_seconds, 2),
        "compute_seconds": round(compute_seconds, 2),
    }


def train(
    data_path=None,
    epochs=8,
    batch_size=64,
    lr=1e-3,
    val_fraction=0.1,
    seed=0,
    device="auto",
    out_path=None,
    value_weight=0.5,
    min_candidates=2,
    loss_mode="ce",
    group_weight=0.2,
    verbose=True,
):
    if data_path is None:
        files = sorted(DATA_DIR.glob("games_*.npz"), key=lambda p: p.stat().st_mtime)

        if not files:
            raise FileNotFoundError(f"{DATA_DIR} 下没有 .npz，请先跑 training.export_dataset")

        data_path = files[-1]

    data_path = Path(data_path)
    data = load_dataset(data_path)

    if "game_index" not in data:
        raise ValueError(
            "数据集缺少 game_index，无法按局切分。请重跑 training.export_dataset。"
        )

    train_idx, val_idx = split_by_game(
        data["game_index"], val_fraction=val_fraction, seed=seed
    )

    lengths = candidate_lengths(data["cand_offsets"])

    raw_train, raw_val = len(train_idx), len(val_idx)
    train_idx = filter_trivial(train_idx, lengths, min_candidates)
    val_idx = filter_trivial(val_idx, lengths, min_candidates)

    if len(train_idx) == 0 or len(val_idx) == 0:
        raise RuntimeError(
            "过滤后训练集或验证集为空，请调小 --min-candidates"
        )

    train_batches = make_batches(train_idx, lengths, batch_size, shuffle=True, seed=seed)
    val_batches = make_batches(val_idx, lengths, batch_size, shuffle=False)

    torch.manual_seed(seed)
    np.random.seed(seed)

    dev = pick_device(device)

    state_dim = int(data["states"].shape[1])
    action_dim = int(data["cand_flat"].shape[1])

    # 记录训练时用的编码器版本，推理端据此做兼容性校验
    from training.state_encoder import ENCODER_VERSION

    encoder_version = ENCODER_VERSION

    model = CandidateScorer(state_dim, action_dim).to(dev)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    if verbose:
        print("=" * 66)
        print("GuanDan AI Lab - 行为克隆训练")
        print("=" * 66)
        print(f"数据文件：{data_path.name}")
        print(f"设备：{dev}   状态维度 {state_dim}   动作维度 {action_dim}")
        print(f"损失模式：{loss_mode}（group = 同手牌不同花色视为同一答案）")
        print(f"训练样本 {len(train_idx)}（{len(train_batches)} 批）"
              f"   验证样本 {len(val_idx)}（{len(val_batches)} 批）")
        if min_candidates > 1:
            print(
                f"已剔除候选数 < {min_candidates} 的样本："
                f"训练 {raw_train} -> {len(train_idx)}，"
                f"验证 {raw_val} -> {len(val_idx)}"
            )
        print(f"训练集候选：{batch_stats(data, train_idx)}")
        print(f"验证集候选：{batch_stats(data, val_idx)}")
        print("-" * 66)

    history = []
    best = None
    started = time.perf_counter()

    for epoch in range(1, epochs + 1):
        if dev.type == "cuda":
            torch.cuda.reset_peak_memory_stats()

        train_stats = run_epoch(
            model, train_batches, data, dev, optimizer, value_weight, loss_mode, group_weight
        )
        val_stats = run_epoch(
            model, val_batches, data, dev, None, value_weight, loss_mode, group_weight
        )

        elapsed = time.perf_counter() - started

        record = {
            "epoch": epoch,
            "train_loss": round(train_stats["loss"], 4),
            "train_acc": round(train_stats["acc"], 4),
            "train_group_acc": round(train_stats["group_acc"], 4),
            "val_loss": round(val_stats["loss"], 4),
            "val_acc": round(val_stats["acc"], 4),
            "val_group_acc": round(val_stats["group_acc"], 4),
            "seconds": round(elapsed, 1),
            # 数据准备（collate + 搬上 GPU）与计算分开计时，两者相加约等于本轮耗时
            "prep_seconds": round(
                train_stats["prep_seconds"] + val_stats["prep_seconds"], 2
            ),
            "compute_seconds": round(
                train_stats["compute_seconds"] + val_stats["compute_seconds"], 2
            ),
            # PyTorch 实际分配的显存峰值（不含 CUDA 上下文，约 0.3~0.5 GB）
            "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)
            if dev.type == "cuda"
            else None,
        }
        history.append(record)

        if verbose:
            vram_text = (
                f" 显存 {record['peak_vram_gb']:.2f}GB"
                if record["peak_vram_gb"]
                else ""
            )

            print(
                f"第 {epoch:02d} 轮 | 训练 loss {record['train_loss']:.4f} "
                f"acc {record['train_acc']:.3f} | 验证 loss {record['val_loss']:.4f} "
                f"acc {record['val_acc']:.3f} 组内 {record['val_group_acc']:.3f} "
                f"| 数据 {record['prep_seconds']:.1f}s 计算 {record['compute_seconds']:.1f}s"
                f"{vram_text} | {elapsed:.0f}s"
            )

        if best is None or val_stats["acc"] > best["val_acc"]:
            best = {
                "val_acc": val_stats["acc"],
                "epoch": epoch,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
            }

    if out_path is None:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        out_path = MODEL_DIR / f"bc_{data_path.stem}.pt"

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint = {
        "model": best["state"],
        "config": model.config(),
        "state_dim": state_dim,
        "action_dim": action_dim,
        "encoder_version": encoder_version,
        "trained_on": data_path.name,
        "best_epoch": best["epoch"],
        "best_val_acc": best["val_acc"],
        "history": history,
        "seed": seed,
        "epochs": epochs,
        "batch_size": batch_size,
        "lr": lr,
        "value_weight": value_weight,
        "loss_mode": loss_mode,
        "group_weight": group_weight,
        "min_candidates": min_candidates,
    }

    torch.save(checkpoint, out_path)

    meta_path = out_path.with_suffix(".json")
    meta_path.write_text(
        json.dumps(checkpoint["history"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    model.load_state_dict(best["state"])
    buckets = accuracy_by_bucket(model, data, val_idx, dev)

    if verbose:
        print("-" * 66)
        print(f"最佳轮次：第 {best['epoch']} 轮，验证集动作一致率 {best['val_acc']:.4f}")

        print("\n按候选数量的验证集一致率（候选越多越难）：")
        for bucket in BUCKETS:
            correct, total = buckets[bucket]
            if total:
                upper = "+" if bucket[1] >= 10 ** 9 else f"-{bucket[1]}"
                print(f"  {bucket[0]}{upper:<5} {total:>6} 条   一致率 {correct / total:.3f}")

        print(f"\n模型：{out_path}")
        print(f"训练曲线：{meta_path}")

    return {
        "checkpoint": str(out_path),
        "best_epoch": best["epoch"],
        "best_val_acc": best["val_acc"],
        "history": history,
        "buckets": {
            f"{bucket[0]}-{bucket[1] if bucket[1] < 10 ** 9 else 'inf'}": {
                "total": buckets[bucket][1],
                "accuracy": round(buckets[bucket][0] / max(buckets[bucket][1], 1), 4),
            }
            for bucket in BUCKETS
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="行为克隆训练（候选打分网络）")
    parser.add_argument("--data", default=None, help="npz 路径；省略时取 data 下最新")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", default="auto", help="auto / cpu / cuda")
    parser.add_argument("--out", default=None, help="模型输出路径")
    parser.add_argument("--value-weight", type=float, default=0.5)
    parser.add_argument(
        "--min-candidates",
        type=int,
        default=2,
        help="剔除候选数少于此值的样本（1 = 不剔除）；小于 2 的样本只有唯一选择，学不到东西",
    )
    parser.add_argument(
        "--loss",
        choices=("ce", "group", "mixed"),
        default="ce",
        help=(
            "ce = 普通交叉熵（默认，实测最好）；"
            "group = 置换等价损失（400 局配对 p=0.027 显著更差）；"
            "mixed = ce + group_weight × group（保留花色信号）"
        ),
    )
    parser.add_argument(
        "--group-weight",
        type=float,
        default=0.2,
        help="mixed 模式下等价项的权重",
    )

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
        value_weight=args.value_weight,
        min_candidates=args.min_candidates,
        loss_mode=args.loss,
        group_weight=args.group_weight,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
