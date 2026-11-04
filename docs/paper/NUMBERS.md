# 论文数字索引（NUMBERS）

> 配套文件：[draft.md](draft.md)。本文档把初稿中每个关键数字映射到「数值 → 口径/条件 → 来源 → 复现命令」。
> **原则**：不新造数字；找不到来源标「待补」；同一指标存在多套数字时并列并注明条件，不做平均。

---

## A. 约定

### A.1 来源编号

| 编号 | 含义 |
|---|---|
| `E01`–`E22` | [docs/EXPERIMENTS.md](../EXPERIMENTS.md) 对应实验小节（该节内附命令与原始 JSON 路径） |
| `O:§n` | [docs/PAPER_OUTLINE.md](../PAPER_OUTLINE.md) 第 n 节 |
| `W` | [docs/RELATED_WORK.md](../RELATED_WORK.md)（文献与 DOI，检索日期 2026-11-03） |
| `M` | [models/README.md](../../models/README.md)（模型清单与旧实验表） |
| `R` | [README.md](../../README.md)（项目总览与徽章表） |
| `X:日期` | 写作期间新跑的验证命令（命令见对应条目） |
| `JSON:<文件名>` | `evaluation/` 下的原始评测报告 |
| `本文计算` | 由已标注数字直接相减/相除得到，未引入新数据 |

### A.2 复现环境

- 仓库根目录：`C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab`
- Windows 11；Python 3.13.17；PyTorch 2.11.0+cu128；RTX 5060 Laptop 8 GB；18 个逻辑核 [O:§12][E17]
- 解释器统一写作 `PY`，实际执行：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
$PY = ".\.venv\Scripts\python.exe"
& $PY -X utf8 <script>
```

- 系统 TEMP 不可写：脚本的临时输出请落在仓库内（如 `evaluation/`、`training/data/`）。
- **禁止**用 `Get-Content | Set-Content` 改写含中文的源文件（会把 UTF-8 变成乱码，E21 实际发生过）。

### A.3 关键 checkpoint（复现命令里用到）

| 用途 | 文件 | 说明 |
|---|---|---|
| BC 参考模型（v2 状态） | `models/bc_games_20261103_121919.pt` | 5000 局 40 轮，验证一致率 0.756（第 37 轮）[M] |
| BC v3 状态模型 | `models/bc_games_20261103_v3.pt` | 状态编码 v3（258 维） |
| 价值网络 v2 | `models/value_games_20261103_121919.pt` | AUC 0.6351 [E04] |
| 价值网络 v3 | `models/value_v3.pt` | AUC 0.6997 [E11] |
| 价值网络 v3 + 软标签 | `models/value_v3_soft.pt` | AUC 0.6954 [E15] |
| 价值网络（6000 局合并） | `models/value_merged_6000.pt` | AUC 0.6426 [E10] |
| 成对比较网络 | `models/pairwise_v3.pt` | 决策内 0.7462 [E14] |

> 注意：`players.neural.register()` / `evaluate_neural` 不传 checkpoint 时按修改时间取最新模型 [M]。**所有命令必须显式传 checkpoint**，否则复现结果会随目录里新生成的模型漂移。

---

## B. 规则引擎与数据审计

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 349 → 359 条测试 | 审计时点（E00 未在 EXPERIMENTS 单列，见大纲） | `O:§3` | `& $PY -X utf8 -m pytest tests -q` |
| **427 passed / 28.97 s** | 2026-11-04 写作期间实测 | `X:2026-11-04` | `& $PY -X utf8 -m pytest tests -q` |
| 300 局逐手重放零违规 | 全量重放，不一致即抛错 | `O:§3` | 见 EXPERIMENTS 的审计小节（`tools/verify_rules.py`、`tools/flow_audit.py`） |
| 比较关系 0 矛盾 | 牌型大小/炸弹压制自动检查 | `O:§3` | `& $PY -X utf8 tools/logic_audit.py` |
| 发牌卡方 p=0.84 | 54 种「牌→座位」分布 | `O:§3` | `& $PY -X utf8 tools/deal_randomness.py` |
| 300 局导出 62.6 s → 17.5 s（3.58×） | 1 进程 vs 4 分片 | `E21` | `& $PY -X utf8 tools/parallel_export.py <jsonl> --workers 4` |
| 5000 局导出 1,335.1 s → 215.4 s（6.20×） | 1 进程 vs 8 分片，478,895 样本 | `E21` | `& $PY -X utf8 tools/parallel_export.py <jsonl> --workers 8` |
| 逐位一致（10 个数组） | 并行 vs 单进程 npz 全等 | `E21` | 同上，脚本内置校验（勿加 `--no-verify`） |
| 新增 2 条回归测试 | `merge_datasets` 局号偏移翻倍 bug 修复后 | `E21` | `& $PY -X utf8 -m pytest tests -q` |

---

## C. 表示与网络结构

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 198 维 | v2 状态编码 | `O:§4` | `& $PY -X utf8 tools/verify_rules.py`（含维度自检）或读 `training/state_encoder.py` |
| 258 维 | v3 = v2 + 历史 24+24 + 进度 2 + 出完 2 + 炸弹 2 + 手牌结构 6 | `E11` | 同上 |
| 65 维 | 动作编码 = 牌面 54 + 牌型 9 + 张数 1 + 过牌 1 | `O:§4` | 读 `training/serialize.py` / `state_encoder.py` |
| hidden 256 / cand 128 / dropout 0.1 | `CandidateScorer` 默认结构 | `X:2026-11-04`（读 `training/model.py`） | `Get-Content training/model.py` |
| 最大候选 1536 | 5000 局数据统计 | `E02` | `& $PY -X utf8 tools/check_dataset.py <npz>` |
| 平均候选 23.53 | 同上 | `E02` | 同上 |
| 过牌比例 0.5759 | 过牌决策 / 全部决策 | `E02` | 同上 |

---

## D. 行为克隆基线

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 5000 局 / 478,895 决策 | 启发式老师对局 | `E02` | `& $PY -X utf8 training/collect_data.py`（重采） |
| 430,847 / 48,048 | 按局切分训练/验证 | `E02` | `& $PY -X utf8 tools/check_dataset.py <npz>` |
| 验证一致率 **0.7562** | 第 37 轮，40 轮 batch 64 | `E02` | `& $PY -X utf8 training/train_bc.py`（原始运行见 `models/bc_games_20261103_121919.json`） |
| 训练 / 验证 loss 0.8564 / 1.0143 | 同上 | `E02` | 同上（json 内有逐轮记录） |
| 对启发式 **48.50%**（v2，400 局） | 400 局配对（200 组），CI 43.64–53.39，分边 49.0% / 48.0%（百分比口径） | `E02` | `& $PY -X utf8 -m training.evaluate_neural --games 200 --opponent heuristic --level 2`（该脚本 `--games` 为组数，每组 2 局 = 400 局） |
| 对启发式 **51.50%**（v2，200 局复测） | 103/200，CI 44.61–58.33；与 48.50% 的差异属抽样波动（CI 重叠） | `E05` / `JSON:policies_neural_vs_heuristic_191528.json` | 同上 `--games 100`（100 组 = 200 局） |
| 对启发式 **53.00%**（v3，200 局，**当前主口径**） | 106/200（100 对），CI 46.09–59.80；JSON 记 `games: 200`、`a_wins: 106`、分边 0.49 / 0.57 | `E11` / `JSON:policies_neural_vs_heuristic_20261103_205210.json` | `& $PY -X utf8 tools\eval_policies.py --a neural --b heuristic --games 100 --seed-start 300 --checkpoint models\bc_games_20261103_v3.pt` |
| 分边 49.0% / 48.0% | 胜率百分比（**非局数**），无先手偏差；均值 48.5% 与 v2 400 局 48.50% 一致 | `O:§5` | 同上，输出按座位分列 |
| 对随机 **93.00%** | 400 局，CI 90.07–95.11，分边 92.5/93.5 | `R` / `JSON:policies_neural_vs_random_20261104_192931.json` | `... --a neural --b random --games 200 --checkpoint <最新v3模型>` |
| 启发式对随机 88.00% | 400 局 | `R` | `... --a heuristic --b random --games 200` |
| 成对局面 全胜 50 / 一胜一负 94 / 全负 56 | 400 局配对 | `E02` | `& $PY -X utf8 -m training.evaluate_neural --games 200 --opponent heuristic --level 2`（输出逐局明细） |
| 全胜 50 / 94 / 56 → 胜率 48.50% | (50 + 94/2)/200 | `本文计算` | — |

### D.1 分桶一致率（验证集 27,725 条，`M`）

| 候选数 | 5000 局 40 轮 | 2000 局 20 轮 |
|---|---:|---:|
| 2 | 0.990（5,383 条） | 0.910 |
| 3–5 | 0.815（5,949 条） | 0.747 |
| 6–20 | 0.697（8,530 条） | 0.553 |
| 21–100 | 0.560（5,263 条） | 0.356 |
| 101+ | 0.429（2,600 条） | 0.234 |

> 来源 `M`（models/README.md 的表）。复现：`& $PY -X utf8 training/evaluate_neural.py --checkpoint models\bc_games_20261103_121919.pt`（脚本会输出分桶统计）。
> 注意：README.md 给出的分桶为 0.993 / 0.844 / 0.708 / 0.544 / 0.385，与 `M` 不同（另一模型/另一验证集），见 §J。

### D.2 旧规则模型量表（`M`，仅作历史参考）

| 模型 | 一致率 | 对启发式胜率 |
|---|---:|---:|
| 300 局 12 轮 | 0.714* | 8.33%（120 局） |
| 2000 局 20 轮 | 0.594 | 25.75%（400 局） |
| 5000 局 20 轮 | 0.684 | 39.75%（400 局） |
| bc_v7 5000 局 40 轮 | 0.728 | 51.50%（400 局） |
| bc_v7 独立种子 | — | 52.00% |
| bc_v7 打 7（级牌=7） | — | 55.00% |

> 负结果（`M`）：2000 局上跑 40 轮过拟合，loss 1.82→2.09、胜率 25.75%→23.33%。
> 负结果（`M`）：花色等价损失显著更差——仅 CE 赢 77 局 vs 仅等价 51 局（McNemar p=0.027）；混合 λ=0.1/0.3/0.5 → 18.00/25.75/25.25%。

---

## E. 价值网络（硬目标）

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 478,895 样本 | v2，按局切分 430,847/48,048 | `E04` | `& $PY -X utf8 tools/check_dataset.py <npz>` |
| **AUC 0.6351**（第 3 轮） | v2 状态，`team_win` 标签 | `E04` / `JSON:value_v2` | `& $PY -X utf8 training/train_value.py --data <npz> --out models\value_games_20261103_121919.pt` |
| 第 4 轮起过拟合 | 验证 loss 0.72（第 3 轮）→ 1.31（第 20 轮），训练 AUC 0.966（第 20 轮） | `E04` | 同上（逐轮日志） |
| **AUC 0.6997**（v3） | 258 维状态，+0.065 | `E11` | `... --data training/data/games_20261103_v3.npz --out models\value_v3.pt` |
| AUC 0.6426（第 5 轮） | 580,805 样本 = 老师 5000 + 克隆 1000 局 | `E10` | 同上，换合并数据集 |
| AUC 0.5558（第 1 轮） | 101,910 样本，克隆策略自对弈 1000 局 | `E06` | 同上 |
| 0.5491 / 0.5234 / 0.6197 / 0.6351 | 300 / 1000 / 2000 / 5000 局（28,789 / 95,748 / 191,608 / 478,895 样本），最佳轮 3 / 20 / 16 / 3 | `E07` / `JSON:value_scaling.json` | `& $PY -X utf8 tools/value_scaling.py --sizes 300,1000,2000,5000 --epochs 20` |
| 0.6351（基线） | hidden 256、无正则 | `E09` | `... training/train_value.py`（默认无 wd） |
| 0.5347（第 16 轮） | weight decay 1e-2 | `E09` | 同上，`--weight-decay 1e-2`（具体参数见 EXPERIMENTS E09） |
| 0.5357（第 1 轮） | dropout 0.3 + wd 1e-2 + hidden 128 | `E09` | 同上组合参数 |
| 0.5000（塌缩） | dropout 0.5 + wd 5e-2 + hidden 64 | `E09` | 同上组合参数 |

> E07 的 1000 局点（0.5234）低于 300 局点，作者标注为噪声点；论文不得用它支持「更多数据更差」。

---

## F. 一步前瞻与决策质量（核心负结果）

### F.1 前瞻胜率（200 局配对 = `--games 100`，种子 300..399 换边）

| 策略 | 胜率 | CI | 触发率 | 来源 |
|---|---:|---|---:|---|
| BC 基线（v2） | 51.50%（103/200） | 44.61–58.33 | — | `E05` |
| `top_k=1` 对照 | 51.50%（103/200），逐局相同 | — | 86.7% | `E05` |
| `top_k=3` | 34.50%（69/200） | 28.26–41.32 | 89.5% | `E05` |
| `top_k=5` | **26.00%**（52/200） | 20.41–32.49 | 87.9% | `E05` |
| `top_k=5` + gap 0.15 | 42.00%（84/200） | 35.37–48.93 | 87.9% | `E05` |
| `top_k=5` vs BC 直接对打 | 24.50%（49/200） | 19.06–30.90 | 90.8% | `E05` |
| `top_k=5`（6000 局价值网，AUC 0.6426） | 31.50%（63/200） | 25.46–38.24 | 90.4% | `E05` / `E10` |
| `top_k=5`（v3 价值网，AUC 0.6997） | **16.50%** | 12.00–22.27 | — | `E11` |
| `top_k=3` + gap 0.1（v3） | 39.50% | 32.98–46.41 | — | `E11` |
| 前瞻价值差典型量级 0.01–0.05 | 相邻候选 | — | — | `E05` |
| 候选 >60 退回 BC | 编码 500 候选约 200 ms | — | — | `E05` |

复现命令（以 top5 + v2 价值网为例）：

```powershell
& $PY -X utf8 tools\eval_policies.py --a lookahead --b heuristic --games 100 --seed-start 300 `
  --checkpoint models\bc_games_20261103_121919.pt --value-checkpoint models\value_games_20261103_121919.pt `
  --top-k 5 --max-candidates 60 --out evaluation\policies_lookahead_vs_heuristic_<时间>.json
```

对照：`--top-k 1`（应逐局与 BC 相同）、`--top-k 5 --min-value-gap 0.15`（应得 42.00%）、`--b neural --b-checkpoint models\bc_games_20261103_121919.pt`（前瞻 vs BC 直接对打）。

### F.2 决策内偏好（E13）

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 40 局 / 1590 次采样决策 | stride 1 | `E13` / `JSON:decision_preference.json` | `& $PY -X utf8 tools\decision_preference.py --games 40 --alternatives 4 --value-checkpoint models\value_v3.pt --policy-checkpoint models\bc_games_20261103_v3.pt` |
| 价值网络 K=4 排第一 **28.81%** | 458/1590，CI 26.63–31.08，随机 20%，avg_margin 0.0190 | `E13` | 同上 |
| 价值网络 K=1 二选一 55.14% | 869/1576，CI 52.67–57.58，随机 50% | `E13` | 同上 `--alternatives 1` |
| 策略网络 K=4 **59.06%** | 939/1590（对照） | `E13` | 同上（`--policy-checkpoint` 提供对照） |

### F.3 成对奖励（E14）

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 决策内排第一 0.8200 vs 0.7462 | 48,048 条验证集；BC vs pairwise | `E14` / `JSON:decision_preference_pairwise*.json` | `& $PY -X utf8 tools\decision_preference.py --games 40 --alternatives 4 --policy-checkpoint models\bc_games_20261103_v3.pt`；pairwise 版本换 `models\pairwise_v3.pt` |
| 成对训练准确率 0.904 | 单负样本二分类 | `E14` | `& $PY -X utf8 training\train_pairwise.py --data <npz> --out models\pairwise_v3.pt` |
| 对启发式 53.00% vs **29.00%** | 200 局，pairwise CI 23.15–35.64 | `E14` | `... --a neural --b heuristic --games 100 --checkpoint models\pairwise_v3.pt` |
| pairwise vs BC **20.50%** | 200 局，CI 15.49–26.63 | `E14` | `... --a neural --b neural --checkpoint models\pairwise_v3.pt --b-checkpoint models\bc_games_20261103_v3.pt --games 100` |

### F.4 软标签（E15）

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 标签 = 0.5×胜负 + 0.5×升级数/3 | 只改标签 | `E15` | 见 EXPERIMENTS E15 的 `train_value.py` 参数 |
| AUC 0.6954 | 硬标签 0.6997 | `E15` | `& $PY -X utf8 training\train_value.py --data <npz> --soft-label --out models\value_v3_soft.pt` |
| 决策内偏好 **29.18%** | CI 27.00–31.46，硬标签 28.81% | `E15` | `... decision_preference.py --value-checkpoint models\value_v3_soft.pt` |
| 老师动作价值优势 +0.0157 | 硬标签 +0.0190 | `E15` | 同上 |

---

## G. 自我对弈与数据

| 数值 | 口径/条件 | 来源 | 复现命令 |
|---|---|---|---|
| 混合座位 400 局 / 40,156 决策 / 平均候选 22.48 | 启发式 478 : 模型 322（60:40） | `E03` | `& $PY -X utf8 training\self_play.py --games 400 --mixed-seats` |
| 纯模型 100 局 / 10,637 决策 / 21.34 候选 | A 队 42 : B 队 58 | `E03` | `... --games 100 --model-only` |
| 0.68 秒/局 | 自我对弈 | `E03` | 同上（日志） |
| 克隆策略自对弈 1000 局 / 101,910 决策 | 用于 E06 | `E06` | `... --games 1000` |
| v3 自我对弈 10,000 局 / 1,073,073 决策 | 1,032.6 s、9.68 局/秒（4 进程）、头游 A 5078 : B 4922、615 MB jsonl | `E12` | `... --games 10000 --seed-start 700000 --state-v3`（数据在 `training/data_selfplay/v3_selfplay_10k.jsonl`） |
| 状态：已产出、**未训练** | 结论栏待补 | `E12` | — |

---

## H. 系统与性能

### H.1 吞吐（E01）

| 数值 | 口径 | 来源 |
|---|---:|---|
| 10.0 局/秒/核（1,232 决策/秒） | CPU 随机策略 | `E01` |
| 5.2 局/秒（511 决策/秒） | CPU 启发式 | `E01` |
| 2.88 局/秒（325 ms/局） | 端到端含神经推理 | `E01` |
| GPU 2,628 决策/秒 | batch = 1 | `E01` |
| GPU 156,937 决策/秒 | batch = 64 | `E01` |
| 单核 1000 万局 ≈ 964 h | 端到端；随机 278 h、启发式 531 h | `E01` |

> 复现：`& $PY -X utf8 tools\speed_test.py`、`tools\benchmark_throughput.py`、`tools\train_speed.py`（具体入口见 E01）。

### H.2 并行（E08/E16）

| 数值 | 口径 | 来源 |
|---|---:|---|
| 200 局 66.3 s → 3.02 局/秒 | 1 进程 | `E08` |
| 200 局 21.8 s → 9.17 局/秒 | 4 进程，加速 3.04×，效率 76% | `E08` |
| 0.75 局/秒/核 → 1000 万局 ≈ 3700 核时 | 推算 | `E08` |
| 32 核 ≈ 115 h / 64 核 ≈ 58 h | 1000 万局 | `E08` |
| 1M 局 32 核 ≈ 11.5 h | — | `E08` |
| 2.18 / 3.35 / 4.47 / 4.46 / 3.78 / 2.64 局/秒 | 全神经网 1/2/4/8/12/16 进程，加速 1.00/1.54/2.05/2.05/1.73/1.21 | `E16` |
| 4.60 / 7.04 / 9.33 / 10.67 / 8.60 / 6.94 局/秒 | 纯 CPU 同上，峰值 2.32× | `E16` |
| 4→4.60、8→4.60、12→4.04、16→2.42 | 限单线程 | `E16` |
| 并行上限 2.0–2.3×（4–8 进程） | 瓶颈为功耗/散热 + 超线程 | `E16` |

复现：`& $PY -X utf8 tools\scaling_test.py --configs 1,2,4,8,12,16 --games 24`。

### H.3 GuanDan Benchmark（E17 v1 / E22 quick）

| 指标 | v1（`E17`） | quick（`E22`） | 备注 |
|---|---:|---:|---|
| CPU 对局吞吐 | 4.73 局/秒（458.8 决策/秒） | 5.72 局/秒（554.5 决策/秒） | 20 局、3.5 s |
| GPU batch=1 | 1,897.7 次/秒 | 2,607.1 次/秒 | |
| GPU batch=8 | 17,905 | 20,905.6 | |
| GPU batch=16 | 41,472 | 44,514.8 | |
| GPU batch=32 | 72,623 | 85,503.9 | |
| GPU batch=64 | 162,733 | 166,121.0 | |
| GPU batch=128 | 293,645 | 337,120.3 | |
| 状态编码 / 候选编码 | 0.038 ms / 0.006 ms | 0.031 ms / 0.005 ms | 每决策准备 0.17 → 0.14 ms |
| BC / value 每轮 | 31.3 s / 7.29 s | — | |
| 导出 | 426.8 样本/秒、4.40 局/秒 | — | |
| 端到端 | 0.59 s/局 | — | |
| CPU 占用 | 20.5% | 23.9% | |
| 显存峰值 | 4,300 MB（整机 nvidia-smi） | 1,451 MB（采样器） | **口径不同** |
| 功耗 / 温度 | 24.9 W / 52 ℃ | 23.1 W / 54 ℃ | |
| GPU 峰值 | 56% | 3D 引擎峰值 91.5%、均值 35.6% | 口径不同 |

E17 训练画像补充（`E17`）：每轮 19.4 s（均值 20.5 s，最长 28.5 s）；PyTorch 显存峰值 0.34 GB；nvidia-smi 整机 4,336 MB；时间分配 数据 15% / GPU 85%；CPU 20.7%（仅 1/18 核）；任务管理器口径 GPU 峰值 96% / p95 96% / 均值 78%，nvidia-smi 口径峰值 45% / 均值 26%；频率峰值 2,955 MHz、功耗均值 28.4 W、53 ℃。

复现：`& $PY -X utf8 tools\benchmark.py run --preset quick`（约 20 s）；对比 `& $PY -X utf8 tools\benchmark.py compare <新报告> evaluation\bench_quick_20261104_200736.json`。
判定阈值（`E22`）：吞吐比 ≥1.10 记「更快」，≤0.90 记「更慢」，±10% 内记「持平」；schema `gandan-benchmark/2`。

### H.4 Roofline 与训练效率（E19）

| 数值 | 口径 | 来源 |
|---|---:|---|
| 9.49 TFLOPS / 284.6 GB/s | 矩阵乘实测 | `E19` |
| 脊点 33.3 FLOP/Byte | 9.49e12 / 284.6e9 | `E19` |
| 0.29 GFLOP / 2.26 MB / 1.93 ms | batch=64 单训练步 | `E19` |
| 0.148 TFLOPS（1.55%）/ 1.17 GB/s（0.40%）/ 算术强度 126.5 | 同上 | `E19` |
| 2.12 / 2.07 / 2.08 / 2.03 / 2.92 ms/步 | batch 64/128/256/512/1024 | `E19` |
| 30,216 / 61,771 / 123,221 / 251,780 / 351,018 样本/秒 | 同上 | `E19` |
| batch 512 样本吞吐 8.3× | 合成基准 | `E19` |

复现：`& $PY -X utf8 tools\roofline_probe.py --batch-size 64`。

### H.5 真实数据 batch 消融（E20）

数据：`training/data/games_20261103_v3.npz`（311,662 训练 / 34,591 验证），3 轮 seed 0，lr 1e-3。

| batch | 总时长 | 每轮 | 样本/秒 | 验证准确率 |
|---:|---:|---:|---:|---:|
| 64 | 68.8 s | 22.9 s | 13,592 | 0.6226 |
| 128 | 42.9 s | 14.3 s | 21,777 | 0.6159 |
| 256 | 29.3 s | 9.8 s | 31,944 | 0.6104 |
| 512 | 23.1 s | 7.7 s | 40,412（2.97×） | 0.6061 |
| 512（线性 lr） | — | — | 38,948 | 0.6047 |

结论数字：组批 Amdahl 上限 44%；batch 512 长程可省约 70% 墙钟（`E20`）。
复现：`& $PY -X utf8 tools\batch_ablation.py --batch-sizes 64,128,256,512 --epochs 3`（线性缩放加 `--lr-scale linear`）。

### H.6 数据加载（E18）

| 预取线程 | 0 | 1 | 2 | 4 |
|---|---:|---:|---:|---:|
| 步/秒 | 279.0 | 300.8 | 306.5 | 302.3 |

2 线程仅 +9.9%；等待数据占 7%（`E18`）。复现：`& $PY -X utf8 tools\dataloading_test.py --prefetch 0,1,2,4 --seconds 4`。

---

## I. 仓库内文档口径冲突（写作时必须选一套并注明）

| 指标 | 数值 A | 数值 B | 数值 C | 处理 |
|---|---|---|---|---|
| BC 对启发式 | **53.00%**（v3，200 局/100 对，CI 46.09–59.80）`E11` / `JSON`（当前主口径） | 48.50%（v2，400 局，CI 43.64–53.39）`E02` | 51.50%（v2，200 局复测，抽样波动）`E05` / `JSON` | 正文以 v3 200 局为主口径；v2 两值只作历史/对照，逐处标模型版本与局数 |
| E02 摘要口径 | E02 正文：48.50%（400 局，CI 43.64–53.39） | EXPERIMENTS 末尾「大纲对照表」记 E02 为 51.50%（CI 44.61–58.33） | — | 51.50% 实为 v2 的 200 局复测（E05 基线），**非 E02 的 400 局批次**；以 E02 正文为准 |
| 测试数 | 349 `E02` 时点 | 359 `O:§3` | 370 `SESSION_2026-11-04`；423 `R`；**427 实测** `X:2026-11-04` | **正文只写 427**；349/359/370/423 仅在本文件保留为历史时点 |
| BC 验证一致率 | 0.7562（v2，第 37 轮）`E02` | 0.7500（v3，当前模型）`R` / `E11` | 0.728（bc_v7）`M` | 正文当前主口径用 v3 0.7500，v2 0.7562 作历史对照 |
| 价值 AUC | 0.6351 `E04` | 0.6997 `E11` | 0.6426 `E10` | 全部列出，标明状态版本/数据 |
| 分桶一致率 | `M`：0.990/0.815/0.697/0.560/0.429 | `R`：0.993/0.844/0.708/0.544/0.385 | — | 正文用 `M` 并注明验证集 27,725 条 |
| CPU 吞吐 | 4.73 局/秒 `E17` | 5.72 局/秒 `E22` | 5.2 局/秒（启发式）`E01` | 按实验分开引用，不合并 |
| GPU 吞吐 | 156,937 决策/秒（batch64，`E01`，另一机型/口径） | 162,733（`E17`） | 166,121（`E22`） | 正文用 E17/E22 并说明同日对比只算「未退化」 |
| 显存峰值 | 4,300 MB（整机 nvidia-smi）`E17` | 0.34 GB（PyTorch）`E17` | 1,451 MB（quick 采样器）`E22` | 必须标口径，不能混用 |
| 端到端 | 2.88 局/秒 `E01` | 0.59 s/局 `E17` | — | 两套不同实现/管线，分别引用 |
| 分边胜率 | 49.0% / 48.0%（`O:§5`，对应 v2 400 局 48.50% 评估） | v3 200 局评估分边 0.49 / 0.57（`JSON:policies_neural_vs_heuristic_20261103_205210.json`） | — | **百分比口径（不是局数）**：均值 48.5% 与 48.50% 一致，不存在算术矛盾 |

---

## J. 「待补」清单（写论文时无法从现有资料确认）

1. **E12（1 万局自我对弈数据）的训练结论**：EXPERIMENTS 明确标注「已产出、未训练」，训练后的 AUC / 胜率待补。
2. **E00 的独立实验编号**：审计内容只出现在 PAPER_OUTLINE §3（349→359、300 局重放、p=0.84），EXPERIMENTS 未单列 E00；若定稿要引 E00，需在 EXPERIMENTS 补一节或在正文改写为 `O:§3`。
3. **README 的测试徽章 404**：徽章链接不可达，实际测试数只能取上述时点值。
4. **人类偏好数据**：尚未采集，§9 的协议指标（偏好一致率、KL、胜率保持度）全部待补。
5. **多种子重复**：E07/E09 为单种子扫描，未做重复实验；论文若要加强 AUC 结论需补跑（命令已具备，`--seed` 可控）。
6. **图**：初稿未插图。建议定稿补三张：①AUC 随数据量曲线（E07）；②前瞻胜率 vs 价值 AUC（E05/E11）；③决策内偏好对比（E13/E14/E15）。

---

## K. 一句话复现清单

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
$PY = ".\.venv\Scripts\python.exe"

# 1) 规则与测试
& $PY -X utf8 -m pytest tests -q

# 2) 综合性能（约 20 s）
& $PY -X utf8 tools\benchmark.py run --preset quick

# 3) BC vs 启发式（200 局；v3 当前模型 = 53.00%；v2 参考模型换 --checkpoint models\bc_games_20261103_121919.pt，即 400 局的 48.50%）
& $PY -X utf8 tools\eval_policies.py --a neural --b heuristic --games 100 --seed-start 300 --checkpoint models\bc_games_20261103_v3.pt

# 4) 一步前瞻（核心负结果，top5 / v2 价值网）
& $PY -X utf8 tools\eval_policies.py --a lookahead --b heuristic --games 100 --seed-start 300 --top-k 5 --checkpoint models\bc_games_20261103_121919.pt --value-checkpoint models\value_games_20261103_121919.pt

# 5) 决策内偏好（1590 次采样）
& $PY -X utf8 tools\decision_preference.py --games 40 --alternatives 4 --value-checkpoint models\value_v3.pt --policy-checkpoint models\bc_games_20261103_v3.pt
```
