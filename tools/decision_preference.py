"""决策内偏好测试：价值网络能不能在**同一个局面里**分出好坏？

背景：E05/E11 发现"全局 AUC 越高，一步前瞻越差"。一个直接解释是：
AUC 衡量的是**跨对局**的排序（A 局 vs B 局），而前瞻需要的是
**同一局面下兄弟动作**的排序。这个工具就是来测后者的。

做法（不需要训练、不读历史数据文件，全部现算）：

1. 用启发式策略重新打 N 局，沿它的轨迹走；
2. 在每个采样到的决策点：
   - 候选 = 合法出牌 + 过牌
   - "老师的动作" = 启发式此刻的选择
   - 随机抽 K 个**其它**候选作为陪衬
   - 对每个动作真实模拟执行，用价值网络评估"走完这步后我方头游概率"
3. 统计：老师动作的价值排名第一的比例。

参考基线：
* 随机排序 → 1/(K+1)（K=4 时是 20%）
* 行为克隆在同一批决策上的"老师排名第一"比例应接近验证一致率（~0.75）

用法：
    & .\\.venv\\Scripts\\python.exe -X utf8 -m tools.decision_preference --games 40 --alternatives 4
"""

import argparse
import copy
import math
import random
import statistics
from pathlib import Path

import numpy as np
import torch

from game_engine.game_state import GameState
from players.heuristic import choose_move
from training.model import ValueNet
from training.state_encoder import encode_state

REPO = Path(__file__).resolve().parent.parent


def wilson(wins, total, z=1.96):
    if total == 0:
        return 0.0, 0.0

    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator

    return max(0.0, centre - margin), min(1.0, centre + margin)


def pick_device(requested="auto"):
    if requested != "auto":
        return torch.device(requested)

    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def load_value(path, device):
    blob = torch.load(Path(path), map_location=device, weights_only=False)

    from training.state_encoder import ENCODER_VERSION, STATE_DIM

    checkpoint_dim = (blob.get("config") or {}).get("state_dim")

    if checkpoint_dim is not None and checkpoint_dim != STATE_DIM:
        raise ValueError(
            f"价值网络 {Path(path).name} 用的是 {checkpoint_dim} 维状态"
            f"（旧编码器），当前编码器 v{ENCODER_VERSION} 是 {STATE_DIM} 维。"
            f"请用当前数据重新训练：python -m training.train_value"
        )

    model = ValueNet(**blob["config"]).to(device)
    model.load_state_dict(blob["model"])
    model.eval()

    return model, blob


@torch.no_grad()
def value_of_state(model, state, device):
    tensor = torch.from_numpy(np.asarray(state, dtype=np.float32)).unsqueeze(0)

    return float(torch.sigmoid(model(tensor.to(device))).item())


def our_win_probability(model, device, game, player, action):
    """模拟执行 action，返回「我方最终头游」的估计概率。"""
    sim = copy.deepcopy(game)

    if action is None:
        sim.pass_turn(player)
    else:
        sim.play(player, action)

    if sim.game_over:
        first_out = sim.finished_players[0]
        return 1.0 if first_out in (player, (player + 2) % 4) else 0.0

    next_player = sim.current_player
    probability = value_of_state(model, encode_state(sim, next_player), device)

    return probability if next_player == (player + 2) % 4 else 1.0 - probability


def signature(cards):
    return tuple(sorted(map(repr, cards))) if cards else None


def run(games=40, alternatives=4, stride=1, seed_start=910000, level="2",
        value_path=None, device="auto", verbose=True, policy_path=None):
    device = pick_device(device)

    model, blob = load_value(value_path, device)

    policy = None

    if policy_path is not None:
        from players.neural import NeuralPolicy

        policy = NeuralPolicy(policy_path, device=str(device), seed=0)

    if verbose:
        print("=" * 66)
        print("决策内偏好测试")
        print("=" * 66)
        print(f"价值网络：{Path(value_path).name}（AUC {blob.get('best_val_auc', 0):.4f}）")
        if policy is not None:
            print(f"对照策略网络：{Path(policy_path).name}")
        print(f"设备：{device}   局数：{games}   陪衬候选：{alternatives}   采样步长：{stride}")
        print("-" * 66)

    rank1 = 0
    total = 0
    margins = []
    per_game = []

    policy_rank1 = 0
    policy_total = 0

    for game_index in range(games):
        seed = seed_start + game_index
        game = GameState.new_game(seed=seed, level=level)
        rng = random.Random(seed + 7)

        game_correct = 0
        game_total = 0
        step = 0

        while not game.game_over:
            step += 1
            player = game.current_player
            legal = game.get_legal_moves(player)

            candidates = list(legal)
            if game.last_play is not None:
                candidates.append(None)

            teacher = choose_move(
                game.hands[player], legal, rng=rng, game_state=game, player=player
            )

            # 采样：候选太少或没抽到就跳过统计，但仍要推进对局
            if (len(candidates) >= 2 and step % stride == 0 and teacher is not None):
                teacher_key = signature(teacher)
                others = [c for c in candidates if signature(c) != teacher_key]

                if others:
                    sample = rng.sample(others, min(alternatives, len(others)))

                    value_teacher = our_win_probability(model, device, game, player, teacher)
                    values_others = [
                        our_win_probability(model, device, game, player, action)
                        for action in sample
                    ]

                    if max(values_others) < value_teacher:
                        rank1 += 1
                        game_correct += 1

                    margins.append(value_teacher - statistics.mean(values_others))
                    total += 1
                    game_total += 1

                # 对照：策略网络在同一批决策上能不能把老师动作排第一
                if policy is not None:
                    import numpy as np

                    from training.state_encoder import encode_action

                    level_now = getattr(game, "level", None)
                    vectors = np.asarray(
                        [encode_action(c, level_now) for c in candidates],
                        dtype=np.float32,
                    )
                    with torch.no_grad():
                        state_t = torch.from_numpy(
                            np.asarray(encode_state(game, player), dtype=np.float32)
                        ).unsqueeze(0).to(device)
                        cand_t = torch.from_numpy(vectors).unsqueeze(0).to(device)
                        mask = torch.ones((1, len(candidates)), device=device)
                        scores, _ = policy.model(state_t, cand_t, mask)

                    scores = scores.squeeze(0).cpu().numpy()
                    best = int(np.argmax(scores))

                    if signature(candidates[best]) == teacher_key:
                        policy_rank1 += 1

                    policy_total += 1

            if teacher is None:
                game.pass_turn(player)
            else:
                game.play(player, teacher)

        per_game.append((game_total, game_correct))

        if verbose and ((game_index + 1) % 10 == 0 or game_index == games - 1):
            print(f"第 {game_index + 1:03d}/{games} 局 | 累计采样 {total} 次决策 "
                  f"| 老师排第一 {rank1}（{rank1 / max(total, 1) * 100:.1f}%）")

    low, high = wilson(rank1, total)
    baseline = 1.0 / (alternatives + 1)
    avg_margin = statistics.mean(margins) if margins else 0.0

    if verbose:
        print("\n" + "=" * 66)
        print("结果")
        print("=" * 66)
        print(f"采样决策数：{total}（来自 {games} 局）")
        print(f"老师动作被价值网络排第一：{rank1} / {total} = "
              f"{rank1 / max(total, 1) * 100:.2f}%")
        print(f"95% Wilson 置信区间：[{low * 100:.2f}%, {high * 100:.2f}%]")
        print(f"随机排序基线：{baseline * 100:.1f}%（1/{alternatives + 1}）")
        print(f"老师动作的价值优势（均值）：{avg_margin:+.4f}")

        if policy is not None and policy_total:
            print(f"\n对照 · 策略网络把老师动作排第一：{policy_rank1} / {policy_total} = "
                  f"{policy_rank1 / policy_total * 100:.2f}%")
            print("（这个数应接近策略网络的验证一致率，用来证明测试工具本身没坏）")

        print("=" * 66)

    return {
        "samples": total,
        "teacher_rank1": rank1,
        "rate": rank1 / max(total, 1),
        "ci": [low, high],
        "random_baseline": baseline,
        "avg_margin": avg_margin,
        "value_checkpoint": str(value_path),
        "value_auc": blob.get("best_val_auc"),
        "policy_rank1_rate": (policy_rank1 / policy_total) if policy_total else None,
        "policy_samples": policy_total,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="决策内偏好测试")
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--alternatives", type=int, default=4)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--seed-start", type=int, default=910000)
    parser.add_argument("--level", default="2")
    parser.add_argument("--value-checkpoint", default=None)
    parser.add_argument("--policy-checkpoint", default=None, help="对照用的策略网络")
    parser.add_argument("--device", default="auto")

    args = parser.parse_args(argv)

    value_path = args.value_checkpoint

    if value_path is None:
        values = sorted((REPO / "models").glob("value_*.pt"),
                        key=lambda path: path.stat().st_mtime)
        value_path = values[-1]

    result = run(
        games=args.games,
        alternatives=args.alternatives,
        stride=args.stride,
        seed_start=args.seed_start,
        level=args.level,
        value_path=value_path,
        device=args.device,
        policy_path=args.policy_checkpoint,
    )

    import json

    out = REPO / "evaluation" / "decision_preference.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果已保存：{out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
