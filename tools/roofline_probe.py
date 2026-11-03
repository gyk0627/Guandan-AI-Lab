"""Roofline 分析：训练时 GPU 到底是"算力吃满"还是"显存带宽限制"。

思路（标准 roofline 方法）：

1. 用 ``torch.utils.flop_counter`` 精确数出一次训练步（前向+反向）的 **FLOPs**；
2. 估算这一步要搬多少**字节**（输入张量 + 权重 + 激活）；
3. 两者相除得到**算术强度**（FLOP/Byte）；
4. 与这台 GPU 的 **脊点**（峰值算力 / 峰值带宽）比较：
   * 算术强度 < 脊点 → 带宽受限（搬数据太慢）；
   * 算术强度 > 脊点 → 算力受限；
   * 若两者**都远低于峰值** → 两者都不是，是**规模太小、延迟/占用率受限**。
5. 同时实测本机大矩阵乘的 TFLOPS 与大块拷贝的 GB/s，作为"能到多高"的参照。

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.roofline_probe
"""

import argparse
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from training.dataset import candidate_lengths, collate, load_dataset, make_batches
from training.model import CandidateScorer

REPO = Path(__file__).resolve().parent.parent
DATA_DIR = REPO / "training" / "data"


def latest_npz():
    files = sorted(DATA_DIR.glob("*.npz"), key=lambda path: path.stat().st_mtime)

    return files[-1]


def peak_gemm_tflops(device, size=4096, seconds=1.5):
    """实测大矩阵乘能跑多少 TFLOPS（算力上限参照）。"""
    a = torch.randn(size, size, device=device)
    b = torch.randn(size, size, device=device)

    for _ in range(3):
        a @ b

    torch.cuda.synchronize()
    started = time.perf_counter()
    steps = 0

    while time.perf_counter() - started < seconds:
        a @ b
        steps += 1

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    flops = 2 * size ** 3 * steps

    return flops / elapsed / 1e12


def peak_bandwidth_gbps(device, size_mb=512, seconds=1.0):
    """实测显存拷贝带宽（带宽上限参照）。"""
    elements = size_mb * 1024 * 1024 // 4
    source = torch.empty(elements, device=device)
    target = torch.empty_like(source)

    target.copy_(source)
    torch.cuda.synchronize()
    started = time.perf_counter()
    steps = 0

    while time.perf_counter() - started < seconds:
        target.copy_(source)
        steps += 1

    torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    bytes_moved = elements * 4 * 2 * steps  # 读 + 写

    return bytes_moved / elapsed / 1e9


def make_batch(data, batch_size, device, seed=0):
    indices = np.arange(len(data["states"]))
    lengths = candidate_lengths(data["cand_offsets"])
    batches = make_batches(indices, lengths, batch_size=batch_size, shuffle=True, seed=seed)
    states, cands, mask, labels, values, groups = collate(batches[0], data)

    return (
        states.to(device), cands.to(device), mask.to(device),
        labels.to(device), values.to(device),
        (groups.to(device) if groups is not None else None),
    )


def measure_flops(model, batch, counter_mode):
    """在 FLOP 计数器下跑一次前向+反向，返回 FLOPs。"""
    states, cands, mask, labels, values, groups = batch

    with counter_mode:
        scores, value = model(states, cands, mask)
        loss = F.cross_entropy(scores, labels) + 0.5 * F.binary_cross_entropy_with_logits(
            value, values
        )
        loss.backward()

    return counter_mode.get_total_flops()


def estimate_bytes(batch, model):
    """估算一步要搬的字节数：输入张量 + 参数 + 梯度（粗估）。"""
    states, cands, mask, labels, values, groups = batch

    input_bytes = (
        states.numel() * states.element_size()
        + cands.numel() * cands.element_size()
        + mask.numel() * mask.element_size()
        + labels.numel() * labels.element_size()
        + values.numel() * values.element_size()
    )

    parameter_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
    # 反向要读参数 + 写梯度，粗估为参数量的 3 倍
    total = input_bytes + parameter_bytes * 3

    return {
        "input_bytes": input_bytes,
        "parameter_bytes": parameter_bytes,
        "total_bytes": total,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Roofline 分析：算力 vs 带宽")
    parser.add_argument("--data", default=None)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="cuda")

    args = parser.parse_args(argv)

    if not torch.cuda.is_available():
        raise SystemExit("需要 CUDA")

    device = torch.device(args.device)
    data_path = Path(args.data) if args.data else latest_npz()
    data = load_dataset(data_path)

    model = CandidateScorer(int(data["states"].shape[1]), int(data["cand_flat"].shape[1])).to(device)
    model.train()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    print("=" * 72)
    print("Roofline 分析：训练时 GPU 是算力受限还是带宽受限？")
    print("=" * 72)
    print(f"GPU：{torch.cuda.get_device_name(0)}")
    print(f"数据：{data_path.name}   batch={args.batch_size}")
    print("-" * 72)

    # ---- 1. 机器上限 ----
    gemm = peak_gemm_tflops(device)
    bandwidth = peak_bandwidth_gbps(device)
    ridge = gemm * 1e12 / (bandwidth * 1e9)

    print("[1] 本机上限（实测）")
    print(f"    矩阵乘算力   {gemm:8.2f} TFLOPS")
    print(f"    显存带宽     {bandwidth:8.1f} GB/s")
    print(f"    脊点         {ridge:8.1f} FLOP/Byte"
          f"（算术强度小于它 → 带宽受限）")

    # ---- 2. 我们的训练步 ----
    from torch.utils.flop_counter import FlopCounterMode

    batch = make_batch(data, args.batch_size, device)

    # 预热
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        scores, value = model(batch[0], batch[1], batch[2])
        loss = F.cross_entropy(scores, batch[3]) + 0.5 * F.binary_cross_entropy_with_logits(
            value, batch[4]
        )
        loss.backward()

    torch.cuda.synchronize()

    flops = measure_flops(model, batch, FlopCounterMode(display=False))
    optimizer.zero_grad(set_to_none=True)

    torch.cuda.synchronize()
    started = time.perf_counter()
    steps = 0

    while time.perf_counter() - started < 2.0:
        optimizer.zero_grad(set_to_none=True)
        scores, value = model(batch[0], batch[1], batch[2])
        loss = F.cross_entropy(scores, batch[3]) + 0.5 * F.binary_cross_entropy_with_logits(
            value, batch[4]
        )
        loss.backward()
        steps += 1

    torch.cuda.synchronize()
    step_seconds = (time.perf_counter() - started) / steps

    achieved = flops / step_seconds
    sizes = estimate_bytes(batch, model)
    intensity = flops / sizes["total_bytes"]

    print("\n[2] 我们的训练步（前向+反向，实测）")
    print(f"    FLOPs/步        {flops / 1e9:8.2f} GFLOP")
    print(f"    字节/步         {sizes['total_bytes'] / 1e6:8.2f} MB"
          f"（输入 {sizes['input_bytes'] / 1e6:.2f} MB + 参数/梯度 "
          f"{sizes['parameter_bytes'] * 3 / 1e6:.2f} MB）")
    print(f"    步时            {step_seconds * 1000:8.2f} ms")
    print(f"    实际达到算力    {achieved / 1e12:8.3f} TFLOPS"
          f"（占峰值 {achieved / 1e12 / gemm * 100:.2f}%）")
    print(f"    实际带宽需求    {sizes['total_bytes'] / step_seconds / 1e9:8.2f} GB/s"
          f"（占峰值 {sizes['total_bytes'] / step_seconds / 1e9 / bandwidth * 100:.2f}%）")
    print(f"    算术强度        {intensity:8.1f} FLOP/Byte")

    print("\n[3] 结论")
    compute_ratio = achieved / 1e12 / gemm
    bandwidth_ratio = sizes["total_bytes"] / step_seconds / 1e9 / bandwidth

    if compute_ratio < 0.2 and bandwidth_ratio < 0.2:
        print("    **两者都没吃满**：算力和带宽都远低于上限。")
        print("    瓶颈是「GPU 工作规模太小」——kernel launch 开销、小矩阵效率低、占用率不足。")
        print("    对策：加大 batch / 合并候选计算 / 让每次 kernel 干更多活。")
    elif bandwidth_ratio > compute_ratio * 2:
        print("    **带宽受限**：搬数据的速度跟不上，算力单元在等数据。")
        print("    对策：减少张量搬运、用更小 dtype、把数据放在更近的存储。")
    elif compute_ratio > bandwidth_ratio * 2:
        print("    **算力受限**：计算单元是瓶颈，换更快的 GPU 直接有效。")
    else:
        print("    算力与带宽占用接近，接近脊点，属于均衡区。")

    # 更大的 batch 会不会更划算？（用**固定宽度**的合成张量，只变 batch）
    print("\n[4] batch 放大的效果（合成张量，候选宽度固定为 30，只变 batch）")

    state_dim = int(data["states"].shape[1])
    action_dim = int(data["cand_flat"].shape[1])
    width = 30

    for size in (64, 128, 256, 512, 1024):
        states = torch.randn(size, state_dim, device=device)
        cands = torch.randn(size, width, action_dim, device=device)
        mask = torch.ones(size, width, device=device)
        labels = torch.zeros(size, dtype=torch.long, device=device)
        values = torch.zeros(size, device=device)

        for _ in range(2):
            optimizer.zero_grad(set_to_none=True)
            scores, value = model(states, cands, mask)
            loss = F.cross_entropy(scores, labels) + 0.5 * F.binary_cross_entropy_with_logits(
                value, values
            )
            loss.backward()

        torch.cuda.synchronize()
        started = time.perf_counter()
        runs = 0

        while time.perf_counter() - started < 1.5:
            optimizer.zero_grad(set_to_none=True)
            scores, value = model(states, cands, mask)
            loss = F.cross_entropy(scores, labels) + 0.5 * F.binary_cross_entropy_with_logits(
                value, values
            )
            loss.backward()
            runs += 1

        torch.cuda.synchronize()
        per_step = (time.perf_counter() - started) / runs

        print(f"    batch {size:>4} | {per_step * 1000:7.2f} ms/步"
              f" | {size / per_step:10,.0f} 样本/秒")

    print("=" * 72)
    print("说明：字节数按「输入 + 参数×3」粗估，未计入全部中间激活，")
    print("      因此算术强度是**上界**；若上界都远低于脊点，结论只会更强。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
