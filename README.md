# GuanDan AI Lab

**掼蛋（Guandan）博弈 AI 研究平台**

> 本文件以**代码与测试**为唯一依据重写于 2026-11-02。
> 上一版 README 已被证实有多处与代码不符（清单见 [CHANGELOG.md](CHANGELOG.md) 末尾），请不要再引用旧版内容。
> 规则细节看 [docs/RULES.md](docs/RULES.md)｜完成度与缺陷看 [docs/STATUS.md](docs/STATUS.md)｜改动历史看 [CHANGELOG.md](CHANGELOG.md)。
>
> ⚠️ **新会话请先读最近一份交接文档**：
> [docs/SESSION_2026-11-04.md](docs/SESSION_2026-11-04.md)（性能测量与硬件选型，最新）
> ｜ [docs/SESSION_2026-11-03.md](docs/SESSION_2026-11-03.md)（规则/引擎/界面）
> 按文档里的「接手清单」走，5 分钟就能进入状态。
>
> 📊 **写论文 / 复现实验请读 [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md)**：
> E01–E19 的编号、命令、参数、实测数字与结论（含负结果），文末有「论文素材清单」。
>
> 🧮 **测速与选型**：[docs/HARDWARE.md](docs/HARDWARE.md)（配置评估）、
> [docs/RENT_PLAN.md](docs/RENT_PLAN.md)（云服务器租用方案）。
>
> 🔗 **代码仓库**：https://github.com/gyk0627/Guandan-AI-Lab （私有）

---

## 一、这个项目是什么

一个**掼蛋研究平台**，不是「一个能打牌的小程序」。目标顺序是：

1. 先把**规则**做到可验证（能证明它按确认表出牌）；
2. 再把**基线策略**做到可比较（随机 vs 启发式）；
3. 再把**数据**做成可复现、可校验；
4. 最后才谈神经网络、自我对弈、SDMC 强化学习、界面。

**当前进度：第 1～3 阶段基本完成（规则引擎、策略基线、300/2000/3000/合并 5000 局数据集都已交付）；
第 5 阶段基本完成——行为克隆**追平**了启发式老师（对老师 51.50%、对随机 91.25%）；
第 4 阶段缺人类数据，第 6 阶段（自我对弈 / SDMC）尚未开始，但入口条件已满足。**
（三分清单见第二节，路线状态见第九节。）

> 一句话说清现状：**能正确地打牌、能产出数据、能训练一个追平启发式的网络并评估它；
> 但它只是在模仿老师，不是强化学习产物——要「比老师更强」，必须进入阶段 6。**

### 研究参考

论文原件就在仓库根目录：`issn1000-1239.202220697.pdf`

- 《基于深度强化学习的掼蛋扑克博弈求解》
- 《计算机研究与发展》第 61 卷第 1 期，2024 年，145–155 页
- DOI：10.7544/issn1000-1239.202220697
- 作者：葛振兴、向帅、田品卓、高阳
- 方法：**SDMC**（Soft Deep Monte Carlo），含 Soft Warm Start、Soft Action Sampling

⚠️ **本项目没有复现该论文，也没有实现 SDMC。** 论文只是研究参考与路线依据。
任何「已复现论文」「达到论文水平」的说法都是虚假陈述。

---

## 二、当前真实完成度（已实现 / 进行中 / 未实现）

### ✅ 已实现（有测试或实测支撑）

| 能力 | 证据 |
|---|---|
| 两副牌 108 张、四人各 27 张、同种子发出同样的牌 | `game_engine/cards.py`；`tests/test_game_state.py` |
| 牌力体系（**2 最小**、级牌 15、小王 16、大王 17），全项目唯一来源 | `game_engine/ranks.py`；`tests/test_ranks.py` |
| 9 种牌型识别：单张 / 对子 / 三张 / 三带二 / 顺子 / 同花顺 / 连对 / 连续飞机 / 炸弹 | `game_engine/patterns.py`；`tests/test_patterns.py`（49 条） |
| 牌型比较与炸弹阶梯（4炸 < 同花顺 < 5炸 < … < 8炸） | `game_engine/compare.py`；`tests/test_compare.py` |
| 合法动作生成 + 按上一手过滤 | `game_engine/legal_moves.py`；`tests/test_legal_moves.py` |
| 完整对局：回合、过牌、牌权、名次、结束判定、牌数守恒 | `game_engine/game_state.py`；`tests/test_game_state.py`（44 条） |
| 级牌点数上浮（`level` 参数贯穿识别/比较/生成/对局，启发式也已接入） | `ranks.py::rank_value`、`game_state.py::GameState(level=...)`、`players/heuristic.py::choose_move(level=...)` |
| 随机策略、启发式策略 | `evaluation/head_to_head.py::RandomPolicy`、`players/heuristic.py` |
| 成对同种子 + 换座位的对抗评估（含 95% Wilson 区间） | `evaluation/head_to_head.py` |
| 固定种子性能基准 | `evaluation/benchmark.py` |
| 统一命令行入口 | `main.py`（`play`/`bench`/`evaluate`/`collect`/`test`） |
| 对局 JSONL 日志与复盘分析 | `replay/game_logger.py`、`replay/analyze_game.py` |
| 状态/动作编码 v2（**198 维 / 65 维**） | `training/state_encoder.py`；`tests/test_encoder.py`（37 条） |
| 数据采集 v2（可复现自检通过）+ 结构校验 + npz 导出（重放校验） | `training/collect_data.py`、`training/check_dataset.py`、`training/export_dataset.py` |
| **300 局数据集**（27,794 条决策样本，级牌 2..A 全覆盖） | `training/data/games_20261102_212830.*`（jsonl / manifest / npz / meta） |
| **2000 局数据集**（184,567 条决策样本，用于训练） | `training/data/games_20261102_214537.*`（jsonl 78.1 MB / npz 30.89 MB） |
| **训练用 Dataset / Model**：按局切分、按批次补边、候选打分网络 + value head | `training/dataset.py`、`training/model.py`；`tests/test_training.py`（20 条） |
| **数据集合并工具**（合并多份 npz，`cand_offsets` 整体平移） | `training/merge_datasets.py` |
| **行为克隆基线（追平老师）**：参考模型 v7 —— 验证一致率 0.728、对启发式 **51.50%**、对随机 **91.25%** | `training/train_bc.py`、`models/bc_v7_5000_40ep.pt` |
| **神经网络策略接入评估器**（成对换座位、CUDA 推理） | `players/neural.py`、`training/evaluate_neural.py` |
| pytest 测试网（**370 个用例，全绿**） | `tests/`、`pytest.ini` |

### 🟠 进行中 / 待追认（代码能跑，但还没定死或还没达标）

| 项 | 现状 |
|---|---|
| **神经网络（阶段 5）** | 行为克隆**已追平**启发式老师：v7 对启发式 **51.50%**（400 局，CI 46.61–56.36）、对随机 **91.25%**。<br>⚠️ 这是「追平」不是「超过」——BC 的上限就是老师，继续堆数据会向 50% 收敛。**要变强必须离开 BC**（阶段 6）。**没有任何自我对弈 / 强化学习。** |
| 红桃级牌「逢人配」（万能牌） | `game_engine/wildcards.py` + `patterns.py` / `legal_moves.py`；`tests/test_wildcards.py`（52 条）。<br>⚠️ 测试证明的是「代码按自己的解释自洽」，**不是**「符合规则」——细则仍待负责人确认（RULES.md Q3 的 10 条 + Q13） |
| 编码器 v2 的边界 | 已落地（198/65），但「只编码观测者视角、无历史序列」等限制仍在，见 `docs/STATUS.md` 4.4 |
| 候选动作的规模 | 平均 23、**最大 1635**（300 局）/ **1601**（2000 局）。已按批次补边，但「候选空间太大」仍是最大短板，见 `docs/STATUS.md` 4.11 / 5.4 |

> 其余「采集器 v2 / 结构校验 v2 / npz 导出 / 评估器 / CLI」都已跑通并进入上面的 ✅ 表。

### ❌ 未实现（严禁写成已完成）

| 项 | 说明 |
|---|---|
| **自我对弈训练** | 未开始。现在的「自对弈」只是**采集数据**，不更新参数 |
| **SDMC / 强化学习** | 未开始，论文方法一行未写（阶段 6） |
| **人类高手数据（阶段 4）** | 未开始，没有人类对局 |
| **进贡 / 抗贡** | 未实现 |
| **完整升级赛（升级、打到 A）** | 未实现，只有单局名次 |
| **模型管理与联赛 / 对局回放界面** | 未实现：没有模型版本对比与联赛机制，也没有复盘回放页面（人机对战界面本身已可用，见 6.8） |

---

## 三、已确认的规则表（唯一依据）

以下是项目负责人 **2026-11-02 确认**的原文，**照抄不改**。代码必须服从这张表，而不是服从「常见掼蛋规则」。

| # | 规则 |
|---|---|
| 1 | 两副牌 108 张，四人，每人 27 张，0/2 为 A 队、1/3 为 B 队，出牌顺序 0→1→2→3。 |
| 2 | 牌力：2 < 3 < 4 < … < 10 < J < Q < K < A < 级牌 < 小王 < 大王。**2 是最小的**。 |
| 3 | 顺子：恰好 5 张连续；可含 2（2 只能当最小，如 2-3-4-5-6）；不含大小王；A2345 不算；合法顺子共 9 种。 |
| 4 | 连对：≥2 对连续；可含 2、不含王；按最大对子比大小；张数必须相同才能互压。 |
| 5 | 连续飞机：≥2 组连续三张；不允许带对子（33344455、3334445566 均非法）。 |
| 6 | 三带二：单组三张 + 一对（33322 合法，3332、33345 非法）。 |
| 7 | 同花顺：5 张同花色顺子。 |
| 8 | 炸弹：4~8 张同点数；4炸 < 同花顺 < 5炸 < 6炸 < 7炸 < 8炸；同张数比点数；八张炸弹最大。 |
| 9 | 四王炸不存在（SJ SJ BJ BJ 非法）。 |
| 10 | 不接风：出完牌后牌权按顺序给下一家。 |
| 11 | 级牌：本局打几，该点数牌力上浮到 A 与小王之间；红桃级牌为「逢人配」（万能牌，可代替除大小王外的任意牌）。 |
| 12 | 进贡/抗贡、升级赛、接风细节：尚未实现，标记待确认。 |
| 13 | （同上，第 12 条为状态说明） |

**9 种合法顺子**（穷举，没有第 10 种）：
`2-3-4-5-6`、`3-4-5-6-7`、`4-5-6-7-8`、`5-6-7-8-9`、`6-7-8-9-10`、`7-8-9-10-J`、`8-9-10-J-Q`、`9-10-J-Q-K`、`10-J-Q-K-A`。

逐条的依据、实现位置、对应测试、以及 **13 条待确认清单**都在 [docs/RULES.md](docs/RULES.md)。

> ⚠️ 特别注意三条容易搞错的地方：
> 1. **2 是最小的牌**，不是最大的。
> 2. **A2345 不是顺子**，2 只能当最小。
> 3. **`33344455` 不合法**（飞机不许带对子），但 **`33322` 合法**（三带二）。

---

## 四、目录结构与每个文件的职责

以 2026-11-02 的实际文件为准，逐个核对存在性。

```text
GuanDan-AI-Lab/
├─ README.md                     ← 本文件：总入口
├─ CHANGELOG.md                  ← 变更日志（每次改动追加）
├─ docs/
│  ├─ RULES.md                   ← 规则表 + 每条依据 + 待确认清单
│  ├─ STATUS.md                  ← 完成度看板 + 测试数 + 缺陷 + 实测数字
│  ├─ ARCHITECTURE.md            ← 模块职责、调用关系、数据流
│  ├─ DATA_FORMAT.md             ← JSONL / npz / manifest 字段说明
│  ├─ TESTING.md                 ← 测试组织方式与新增测试的写法
│  └─ GLOSSARY.md                ← 术语表（牌型 / 符号 / 缩写）
├─ main.py                       ← 统一 CLI：play / bench / evaluate / collect / test
├─ auto_game.py                  ← 历史脚本：随机策略自动对局（只打印）
├─ auto_game_heuristic.py        ← 历史脚本：启发式自动对局 + 写 replay 日志
├─ pytest.ini                    ← pytest 配置（testpaths=tests，禁用 cache）
├─ requirements.txt              ← 依赖清单：numpy + pytest（⚠️ torch 尚未写入，见 5.2）
├─ issn1000-1239.202220697.pdf   ← 参考论文原件
├─ 规则.jpg                       ← 纸质规则照片（参考材料，未经代码验证）
├─ 新建 文本文档.txt               ← 负责人手写的 8 阶段路线原文
│
├─ game_engine/                  ← 规则引擎（核心）
│  ├─ __init__.py                ← 空
│  ├─ cards.py                   ← 建两副牌 108 张、洗牌、发牌（每人 27 张）、按点数统计
│  ├─ ranks.py                   ← ★ 牌点/牌力/顺子窗口的唯一真理源（2 最小、级牌 15、小王 16、大王 17）
│  ├─ patterns.py                ← 9 种牌型识别 analyze_cards / is_valid_play / is_bomb_like（已接逢人配）
│  ├─ compare.py                 ← 牌型比较 compare_cards / can_beat + 炸弹强度表 bomb_power
│  ├─ legal_moves.py             ← 合法动作生成 generate_candidates / legal_moves（已接逢人配）
│  ├─ wildcards.py               ← 🟠 逢人配（红桃级牌万能牌）纯函数工具：识别、拆分、缺口枚举
│  └─ game_state.py              ← 对局状态 GameState：回合、过牌、牌权、名次、level
│
├─ players/
│  ├─ heuristic.py               ← 启发式策略：hand_cost / move_cost / evaluate_move / choose_move
│  └─ neural.py                  ← ★ 神经网络策略 NeuralPolicy（argmax 选候选，注册进评估器）
│
├─ training/                     ← 数据、编码与训练
│  ├─ state_encoder.py           ← 状态/动作编码 v2（198 维 / 65 维）
│  ├─ serialize.py               ← 牌 → "S3"/"S10"/"SJ" 紧凑文本
│  ├─ collect_data.py            ← 采集器 v2（CLI，支持 --level-mode / --policy / --check）
│  ├─ export_dataset.py          ← 重放整局、重算候选、导出 .npz（带逐条一致性校验）
│  ├─ check_dataset.py           ← 结构校验 v2（字段/名次/索引/过牌自洽，不跑引擎）
│  ├─ dataset.py                 ← ★ 训练用 Dataset：按局切分、按批次补边、剔除无选择样本
│  ├─ model.py                   ← ★ 候选打分网络 CandidateScorer（state MLP + candidate MLP + score head + value head）
│  ├─ train_bc.py                ← ★ 行为克隆训练脚本（CLI：--epochs / --batch-size / --min-candidates）
│  ├─ evaluate_neural.py         ← ★ 神经网络策略的成对换座位评估（默认对手=启发式，默认 --level 2）
│  ├─ data/                      ← ★ 数据集：300 局（212830）+ 2000 局（214537），各含 jsonl/manifest/npz/meta
│  └─ training_data_20261102_012541.jsonl  ← ⚠️ 旧数据（19 MB，v1 编码，已作废，勿引用）
│
├─ evaluation/                    ← 评估
│  ├─ head_to_head.py            ← ★ 成对同种子 + 换座位 + Wilson 区间 + 策略注册表（含 CLI）
│  ├─ benchmark.py               ← ★ 固定种子性能基准（ms/局、min/median/max）
│  ├─ evaluate.py                ← 历史脚本：随机策略 100 局 → results.csv
│  ├─ compare_strategies.py      ← 历史脚本：启发式 vs 随机 → strategy_comparison_v2.csv
│  ├─ analyze_v2.py              ← 历史脚本：读上面的 CSV 做稳定性分析
│  ├─ results.csv                ← ⚠️ 旧规则时期的结果（非当前基线）
│  ├─ strategy_comparison.csv    ← ⚠️ 同上
│  └─ strategy_comparison_v2.csv ← ⚠️ 同上
│
├─ replay/                       ← 对局日志与复盘
│  ├─ game_logger.py             ← 写 JSONL 日志（每步：出牌/过牌、前后手牌、候选数）
│  ├─ inspect_log.py             ← 打印最新日志前 10 步
│  ├─ analyze_game.py            ← 复盘统计（出牌/过牌比例、可疑决策、关键行动）
│  └─ game_20261102_012035_42.jsonl  ← ⚠️ 旧规则时期的对局日志
│
├─ tests/                        ← 测试网（370 个用例；未装 torch 时会跳过需要 torch 的用例）
│  ├─ __init__.py
│  ├─ test_ranks.py              ← 牌力、级牌、顺子窗口（15）
│  ├─ test_patterns.py           ← 9 种牌型 + 非法边界（49）
│  ├─ test_compare.py            ← 炸弹阶梯、2 最小、同型同张数（18）
│  ├─ test_legal_moves.py        ← 候选完备性、候选数量上界（18）
│  ├─ test_game_state.py         ← 回合/过牌/牌权/名次/牌数守恒（44）
│  ├─ test_encoder.py            ← v2 编码器维度、归一化、确定性、无信息泄漏（37）
│  ├─ test_wildcards.py          ← 逢人配（红桃级牌万能牌）行为（52）
│  ├─ test_level.py              ← 级牌在各牌型/比较中的表现（19）
│  ├─ test_data_pipeline.py      ← 采集/导出/校验管线（19）
│  ├─ test_training.py           ← Dataset/合并/等价组损失/模型前向/训练加载（20，需 torch）
│  ├─ test_web.py                ← 人机对战 HTTP 服务端到端（8，不需浏览器/不需 torch）
│  └─ test_cli.py                ← CLI 冒烟 + 评估统计函数（25）
│
├─ models/                       ← ★ 训练产物（9 个 .pt + 同名指标 JSON + README）
│  ├─ bc_games_20261102_212830.pt ← v1：300 局 / 12 轮（0.714*，被无选择样本抬高）
│  ├─ bc_games_20261102_214537.pt ← v2：2000 局 / 20 轮（0.594，对启发式 25.75%）
│  ├─ bc_v3_40ep.pt              ← 负结果：2000 局 40 轮（过拟合，23.33%）
│  ├─ bc_v4_group.pt             ← 负结果：置换等价损失（19.25%，p=0.027 显著更差）
│  ├─ bc_v5_mixed_0.1/0.3/0.5.pt ← 负结果：混合损失（18.00% / 25.75% / 25.25%）
│  ├─ bc_v6_5000.pt              ← 5000 局 / 20 轮（0.684，对启发式 39.75%）
│  ├─ **bc_v7_5000_40ep.pt**     ← ★ **参考模型**：5000 局 / 40 轮（0.728，对启发式 **51.50%**）
│  └─ README.md                  ← 完整实验记录（含负结果，负责人撰写，勿改）
│
├─ interface/                    ← 🟠 人机对战界面（本地网页版，只用标准库）
│  ├─ web_server.py              ← 本地 HTTP 服务（http.server，只听 127.0.0.1:8765）
│  ├─ index.html                 ← 单文件前端（原生 JS，无框架、无 CDN）
│  ├─ app.py                     ← exe 启动器（挑端口 / 开浏览器 / 关窗退出）
│  ├─ guandan.ico                ← exe 图标（tools/make_icon.py 现画）
│  ├─ train_monitor.html         ← 训练进度网页
│  ├─ start_gui.bat              ← 双击启动并自动开浏览器
│  └─ README.md                  ← 界面用法与设计约束（负责人撰写，勿改）
└─ .venv/                        ← Python 虚拟环境（3.13.17 + torch 2.11.0+cu128）
```

**读代码的推荐顺序**（2 小时能摸清）：
`ranks.py` → `patterns.py` → `compare.py` → `legal_moves.py` → `game_state.py`
→ 对应测试 → `players/heuristic.py` → `main.py` → `state_encoder.py` → `collect_data.py`。

---

## 五、环境搭建（numpy + pytest + **torch（CUDA 版）**）

当前 `.venv` 里的实际情况（实测）：

| 项 | 版本 / 状态 |
|---|---|
| Python | 3.13.17（64 位） |
| numpy | 2.5.4 |
| pytest | 9.2.0 |
| **torch** | **2.11.0+cu128**（已安装，`torch.cuda.is_available() == True`） |
| GPU | NVIDIA RTX 5060 Laptop（走 CUDA 12.8 轮子） |
| 系统 | Windows 11（10.0.26200） |

### 5.1 如果 `.venv` 已经能用（当前情况）

不用安装任何东西，先验证三件套都在：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
& .\.venv\Scripts\python.exe -c "import numpy, pytest, torch; print(numpy.__version__, pytest.__version__, torch.__version__, torch.cuda.is_available())"
```

预期输出：`2.5.4 9.2.0 2.11.0+cu128 True`

### 5.2 如果要从零重建 `.venv`

`requirements.txt` 现在包含 `numpy==2.5.4`、`pytest==9.2.0`、`torch==2.11.0`，
并在注释里写明了 CUDA 版的安装命令（**RTX 5060 是 Blackwell，必须 cu128 及以上**）：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

# 先装 numpy + pytest
& .\.venv\Scripts\python.exe -m pip install numpy==2.5.4 pytest==9.2.0

# torch 建议用官方 cu128 索引装（照抄 requirements.txt 注释里的命令）
& .\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch

& .\.venv\Scripts\python.exe -c "import numpy, pytest, torch; print('ok', torch.__version__, torch.cuda.is_available())"
```

> `pip install -r requirements.txt` 也能装 `torch==2.11.0`，但它会拉 PyPI 的默认轮子
> （可能是 CPU 版）。**要 GPU 就用上面的 cu128 索引命令先装 torch**，
> 或者装完再确认 `torch.cuda.is_available()` 是 `True`。

- 只跑规则引擎 / 采集 / 评估（随机、启发式）**不需要 torch**。
- 只有 `training/train_bc.py`、`training/evaluate_neural.py`、`players/neural.py`
  和 `tests/test_training.py` 需要 torch。
- **没装 torch 的机器上，`pytest` 会自动跳过 `tests/test_training.py` 的 20 条**
  （用 `pytest.importorskip("torch")`），所以需要 torch 的用例会被跳过，实际数字以输出为准。这是预期行为，不是故障。

### 5.3 重要约定

- **一律用 `.\.venv\Scripts\python.exe`，不要用 PATH 里的 `python`**。
  PATH 里的 `python` 可能是另一个 Python，装了不同的包，会让你「明明装了却 import 不到」。
- **不要 `Activate.ps1` 也可以**：上面的写法不依赖激活虚拟环境，更不容易出错。
  如果你想激活，遇到「禁止运行脚本」就临时执行
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`。
- **训练用 GPU**：脚本默认 `--device auto`（有 CUDA 就用 CUDA）。
  CPU 也能跑，但 20 轮会慢一个数量级。
- 跑推理与对局**不需要联网**；只有首次装 torch 需要联网下载轮子。

---

## 六、怎么用（命令都可以直接复制）

先进入仓库目录，并让中文正常显示：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
$env:PYTHONIOENCODING='utf-8'
```

> `$env:PYTHONIOENCODING='utf-8'` 每开一个新的 PowerShell 窗口都要重新执行一次。
> 不加它，中文和 `SJ` 之外的字符可能显示成乱码，但**不影响对局结果**。

### 6.1 跑测试（最常用）

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -q
```

预期输出类似：`370 passed in 20s`
（如果数字和这里不同，以你跑出来的为准，并去看 `docs/STATUS.md` 第 4 节的已知缺陷。
没装 torch 的机器上会跳过 20 条、显示 `304 passed`，属预期。）

只跑某个文件：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_patterns.py -q
```

只跑某一条：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_compare.py::test_bomb_ladder -q
```

失败时看详细原因（去掉 `-q`，加 `-x` 遇到第一个失败就停）：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests -x
```

等价写法：`& .\.venv\Scripts\python.exe main.py test`

### 6.2 跑一局

```powershell
& .\.venv\Scripts\python.exe main.py play --seed 42 --no-log
```

- `--seed 42`：随机种子。**换成同一个种子，牌和过程完全一样**，方便复盘。
- `--no-log`：不写日志文件。去掉它会在 `replay/` 下生成 `game_*.jsonl`。
- 想看中文正确显示，先设 `$env:PYTHONIOENCODING='utf-8'`。

历史脚本（仍然可用，但功能不如 `main.py play`，且不支持级牌）：

```powershell
& .\.venv\Scripts\python.exe auto_game.py              # 随机策略，只打印结果
& .\.venv\Scripts\python.exe auto_game_heuristic.py    # 启发式，并写 replay 日志
```

### 6.3 采集数据

**可复现性自检（不写任何文件，最安全，建议先跑）**：

```powershell
& .\.venv\Scripts\python.exe -m training.collect_data --check
```

预期输出：`可复现性自检通过。`

**真正采集**（会在 `training/data/` 下生成 `games_*.jsonl` 和 `.manifest.json`）：

```powershell
& .\.venv\Scripts\python.exe -m training.collect_data --games 20
```

常用参数：

| 参数 | 作用 | 示例 |
|---|---|---|
| `--games N` | 采集多少局 | `--games 100` |
| `--seed-start N` | 起始种子 | `--seed-start 1000` |
| `--level-mode cycle/fixed/none` | 级牌模式：按 2..A 轮转 / 固定 / 无级牌 | `--level-mode fixed --level 2` |
| `--policy heuristic/random` | 用哪个策略打 | `--policy heuristic` |
| `--out 路径` | 指定输出文件 | `--out D:\gd\games.jsonl` |

`main.py collect` 也可以用了（2026-11-02 修复，参数会原样透传给采集器）：

```powershell
& .\.venv\Scripts\python.exe main.py collect --games 20
```

预期第一行会打印 `[提示] 调用 training.collect_data.main(argv=['--games', '20'])`，
然后正常输出进度并生成 jsonl + manifest。两种写法等价，习惯哪个用哪个。

**结构校验**（不调用引擎，跑得很快，采完立刻扫一遍；默认取 `training/data/` 下最新文件）：

```powershell
& .\.venv\Scripts\python.exe -m training.check_dataset
```

也可以指定文件：

```powershell
& .\.venv\Scripts\python.exe -m training.check_dataset training\data\games_20261102_212830.jsonl
```

它检查的是**文件本身没坏**：字段齐全、同一局内 `seed/level/policy` 一致、
名次是 `0..3` 的排列、`team_rank` 与实际名次一致、`selected_index` 不越界、
`pass/play` 与 `action` 自洽、四家手牌总数 ≤ 108、`hand` 长度与 `hand_counts` 一致。
预期输出最后一行：`结构校验通过。`

**导出成训练用的 `.npz`**（会按 seed 重放整局、重算候选、逐条校验语义）：

```powershell
& .\.venv\Scripts\python.exe -m training.export_dataset
```

> 分工要记住：`check_dataset.py` 只管「文件结构没坏」，
> `export_dataset.py` 才管「语义没坏」（重放整局 + 候选重算 + 标签对齐）。
> 正式数据两个都要跑。

**导出太慢就用并行版**（同样会重放校验，结果与单进程**逐位一致**）：

```powershell
# 默认 8 个分片（按 CPU 核数），输出 xxx.parallel.npz
& .\.venv\Scripts\python.exe -X utf8 -m tools.parallel_export --workers 8

# 指定文件与输出
& .\.venv\Scripts\python.exe -X utf8 -m tools.parallel_export training\data\games_xxx.jsonl --workers 4
```

> 原理：导出是纯 CPU 工作，按**对局 id 排序后切连续区间**，各分片同时重放，
> 最后按分片顺序合并——所以合并后的行序与单进程完全一样，可以逐位比对。
> 实测 5000 局：单进程约 18 分钟，8 分片约 3.6 分钟（详见 `docs/EXPERIMENTS.md` E21）。

**已经采好的数据集**（2026-11-02，可直接用，不必重采）：

| 数据集 | 局数 / 决策样本 | 平均候选 / 最大候选 | 用途 |
|---|---|---|---|
| `games_20261102_212830` | 300 / 27,794 | 23.21 / 1635 | 冒烟、对照（v1） |
| `games_20261102_214537` | 2000 / 184,567 | 23.09 / 1601 | v2 训练集 |
| `games_20261102_222451` | 3000 / 275,328 | 23.24 / 2014 | 合并用（seed 20000 起） |
| **`merged_5000`** | **5000 / 459,895** | **23.18 / 2014** | **v6 / v7 参考模型训练集** |

- 合并后的 `merged_5000` 是 2000 局 + 3000 局两份 npz 合成的
  （`training/merge_datasets.py`，唯一容易错的地方是 `cand_offsets` 要整体平移）。
- 采集 / 导出耗时：300 局约 51.5 s / 58.4 s；2000 局约 11 min / 6.0 min；3000 局约 **17 min / 9 min**。
- 无选择样本（只有 1 个候选）占比：300 局 39.3%、2000 局 40.2%、合并 5000 局 **40.1%**。
- 详细字段见 `docs/DATA_FORMAT.md`；每份数据的 `manifest.json` / `meta.json` 里都有完整统计。

⚠️ **规模提醒（已处理，但仍要注意）**：最大候选数已涨到 **2014**（领出时手里含逢人配会生成大量序列候选）。
**不能**按全局最大宽度补边（46 万样本会是几十 GB），必须按 batch 内实际最大宽度补边或按候选数分桶。
`training/dataset.py::collate` 已按「批内最大宽度」补边，`export_dataset.py::pad_candidates` 也支持传入 `max_width`。

### 6.4 做评估

**对抗评估（成对同种子 + 换座位，最推荐）**：

```powershell
& .\.venv\Scripts\python.exe main.py evaluate --games 100 --opponent random
```

- `--games 100` 表示 **100 组 = 200 局**（同一副牌打两局，策略 A 分别坐 A 队和 B 队）。
- `--games 100` 大约 20 秒。
- 会在 `evaluation/` 下生成 `head_to_head_<时间戳>.csv`。
- 只想拿数字给程序用（不打印逐局、输出 JSON）：

```powershell
& .\.venv\Scripts\python.exe main.py evaluate --games 20 --json
```

- 开级牌评估：

```powershell
& .\.venv\Scripts\python.exe main.py evaluate --games 20 --level 2
```

**性能基准（防止以后改慢没人发现）**：

```powershell
& .\.venv\Scripts\python.exe main.py bench --games 20
& .\.venv\Scripts\python.exe main.py bench --games 20 --strategy random
```

**历史脚本**（能跑，但写死文件名、不支持级牌）：

```powershell
& .\.venv\Scripts\python.exe -m evaluation.evaluate                  # → evaluation/results.csv
& .\.venv\Scripts\python.exe -m evaluation.compare_strategies        # → strategy_comparison_v2.csv
& .\.venv\Scripts\python.exe -m evaluation.analyze_v2                # 读上面那个 CSV 做分析
```

### 6.5 复盘一局

`auto_game_heuristic.py` 或 `main.py play`（不加 `--no-log`）会写 `replay/game_*.jsonl`：

```powershell
& .\.venv\Scripts\python.exe -m replay.inspect_log     # 看最新一局前 10 步
& .\.venv\Scripts\python.exe -m replay.analyze_game    # 出牌/过牌比例、可疑决策、最终名次
```

### 6.6 常用实测数字（当前基线，条件见 STATUS）

> 全部为 2026-11-02 重测结果。**步数是确定性的**（同种子必然一样）；
> **耗时随机器负载波动**（同一条命令复跑，平均耗时会在 ±10% 内浮动）。

**正式数据集（300 局，四名启发式，level 2..A 轮转）**

| 指标 | 数值 |
|---|---|
| 对局 / 决策样本 | **300 局 / 27,794 条** |
| 平均候选 / 最大候选 | **23.21 / 1635** |
| 平均步数 / 过牌率 | **92.65** / **57.5%** |

（完整字段表、文件位置见 6.3 节。）

**策略基线（启发式 vs 随机，成对同种子 + 换座位，200 局）**

| 指标 | 数值 |
|---|---|
| 胜率 | **176 / 200 = 88.00%**，95% Wilson 区间 **[82.77%, 91.80%]** |
| 策略坐 A 队 / B 队 | **90 / 100**（90.0%）/ **86 / 100**（86.0%） |
| 成对结果 | 全胜 78 组 / 一胜一负 20 组 / 全负 2 组 |
| 平均行动次数 | **116.96** 步 |
| 200 局总耗时 | **17.67 s**（88.4 ms/局） |
| 逐局明细 | `evaluation/head_to_head_20261102_2131.csv`（另有 2125、2128 两次冒烟/中间结果） |

**性能基准（bench，20 局，seed 42 起）**

| 指标 | 数值 |
|---|---|
| 启发式自对弈平均步数 | **96.95** 步 |
| 启发式自对弈每局耗时 | **109.2 ms**（min 77.0 / median 102.2 / max 148.1） |
| 随机自对弈平均步数 / 耗时 | **127.85** 步 / **70.1 ms** |
| 27 张手牌候选数（seed=42、玩家 0，无级牌模式） | **301** 个 |

> 口径提醒：这里的「胜率」= **率先出完牌（头游）的队伍获胜**，
> **不是**完整升级赛胜负（没有进贡、没有升级、没有过 A）；
> 对手是**随机策略**，不是人类高手。
> 所以这组数字只能用来比较「策略改动前后有没有变强」，**不能**用来宣称「达到论文水平」。

> 数字与旧版本的关系：旧 README 里的 94.5% / 83% / 随机 50:50 是**三套不同旧规则**下跑出来的，
> 与当前代码不可比；上面这组是当前引擎（规则表 v2 + 级牌 + 逢人配）下唯一有效的基线。

### 6.7 训练与评估神经网络（阶段 5 的第一个基线：行为克隆）

> ⚠️ 先说清性质：这是**行为克隆（模仿启发式）**，**不是强化学习**。
> 它的理论上限就是启发式本身。**参考模型 v7 对启发式 51.50%，含义是「追平老师」，不是「超过老师」。**
> 继续加数据只会向 50% 收敛并封顶——要真正变强，**必须离开行为克隆**（自我对弈 / 搜索 / SDMC）。
> 不许写成「AI 已经学会打掼蛋」。

**训练**（推荐直接用合并好的 5000 局；默认剔除「只有 1 个候选」的样本）：

```powershell
& .\.venv\Scripts\python.exe -m training.train_bc --data training\data\merged_5000.npz --epochs 40 --batch-size 64 --min-candidates 2
```

- 产物：`models/bc_<数据名>.pt`（权重 + 配置 + 元信息）和同名 `.json`（每轮 loss/acc/耗时/`group_acc`）。
- 参考模型 v7 训练成本：**GPU 上 40 轮约 591 秒（≈10 分钟）**。
- `--device auto` 会自动用 CUDA；`--min-candidates 1` 可关掉剔除（不建议，见下面的教训）。
- 损失函数默认 `--loss ce`（交叉熵）。`--loss group|mixed` 是**已验证失败的对照**，见下。

**看实时训练进度（网页）**

```powershell
# 一边训一边看：自动开浏览器，训练参数与 train_bc 一致
& .\.venv\Scripts\python.exe -X utf8 -m tools.train_with_monitor --epochs 40

# 训练在别的窗口跑，只想看进度
& .\.venv\Scripts\python.exe -X utf8 -m tools.train_monitor --open
```

也可以直接双击 `run_train_gui.bat`。

页面上有：总进度条、第几轮 / 共几轮、已用时间与**预计剩余**、训练与验证的 loss/准确率曲线、
每轮明细表、显存占用；训练中途报错会在页面上标红并显示原因（不会假装还在跑）。

原理一句话：训练进程每 0.5 秒把进度写进 `.test_tmp/train_progress.json`，
网页每 0.8 秒读一次。**两个程序用文件通信**，所以网页晚开、刷新、关掉重开都不影响训练。

- 单独用：`train_bc` 也支持 `--monitor <路径>`，不想要网页就不加这个参数。
- 端口默认 `8766`；被占用时加 `--port 8767`。
- 进度文件是普通 JSON，可以自己打开看，也可以给别的程序读。

**评估**（成对同种子 + 换座位；默认对手是启发式；默认 `--level 2`）：

```powershell
# 对启发式（200 组 = 400 局）
& .\.venv\Scripts\python.exe -m training.evaluate_neural --checkpoint models\bc_v7_5000_40ep.pt --games 200 --opponent heuristic --level 2

# 对随机（400 局）
& .\.venv\Scripts\python.exe -m training.evaluate_neural --checkpoint models\bc_v7_5000_40ep.pt --games 200 --opponent random --level 2
```

- `--games 200` = 200 组 = **400 局**；评估速度约 **242 ms/局**。
- ⚠️ **务必显式写 `--checkpoint`**：不带时按修改时间取最新，目录里既有好模型也有对照用的差模型。
- ⚠️ **务必写 `--level 2`（或别的具体级牌）**：数据集是按 level 轮转采的，
  `level=None`（无级牌）是**训练分布外**的输入，用它评估没有意义。

**模型对比（数据量曲线 + 参考模型）**

| 模型 | 局数 | 轮数 | 验证一致率 | 对启发式 | 对随机 |
|---|---:|---:|---:|---|---|
| v1 | 300 | 12 | 0.714\* | 8.33%（120 局） | — |
| v2 | 2000 | 20 | 0.594 | 25.75%（400 局） | 76.67%（120 局） |
| v6 | 5000 | 20 | 0.684 | 39.75%（400 局） | 85.00%（400 局） |
| **v7（参考模型）** | **5000** | **40** | **0.728** | **51.50%**（400 局，95% CI 46.61–56.36）<br>52.00%（独立种子 400 局）<br>55.00%（打 7，200 局） | **91.25%**（400 局，CI 88.07–93.64） |

\* v1 的 0.714 被「只有唯一选择的样本」抬高（这类样本恒为 100%），**不可与后面几行比较**。

- 对照：启发式对随机是 **88.00%**（200 局）。也就是说 v7 对随机（91.25%）已经略高于老师。
- **数据量是主要杠杆**：300 → 2000 → 5000 局（同为 20 轮），对启发式 8.3% → 25.8% → 39.8%；
  5000 局上再训到 40 轮，到 51.5%。

**分桶一致率（参考模型 v7，验证集 27,725 条）**

| 候选数量 | 样本数 | v7 一致率 | 2000 局模型（对照） |
|---|---:|---:|---:|
| 2 | 5,383 | **0.990** | 0.910 |
| 3–5 | 5,949 | 0.815 | 0.747 |
| 6–20 | 8,530 | 0.697 | 0.553 |
| 21–100 | 5,263 | 0.560 | 0.356 |
| 101+ | 2,600 | **0.429** | 0.234 |

结论：**候选越多（通常是领出）仍然越难，但每加一次数据，最难的那一桶涨得最多**
（101+ 从 0.234 → 0.429）。所以「候选空间太大」依然是短板，只是它**可以被数据和表示改善**，
不像之前判断的那样只能靠裁候选。

**两条方法论结论（2026-11-02 修正，旧结论已作废）**

1. **整体一致率会被「无选择样本」抬高。**
   300 局数据集里 39.3%、2000 局里 40.2%、合并 5000 局里 40.1% 的样本只有 1 个候选（恒为 100%）。
   默认 `--min-candidates 2` 剔除（2000 局：训练集 166,055 → 99,194）。
   **报一致率必须说明有没有剔除**，否则数字是虚的。
2. **「加轮数」和「加数据」是耦合的，不能单独说轮数有用/没用。**
   - 2000 局：40 轮 vs 20 轮 → 25.75% → 23.33%（**过拟合**，验证 loss 1.82 → 2.09）。
   - 5000 局：同样 40 轮 → 39.75% → **51.50%**（**有效**，验证 loss 仍在下降）。
   - 结论：**轮数能不能加，取决于数据量**。旧文档写的「训练轮数不是瓶颈」是错的，已更正。
3. **把「花色排列」当等价答案是错的（负结果，已留档）。**
   领出时候选常达上千个，其中很多只是同一手牌换了花色、老师随机挑一个。看起来像标签噪声，
   于是试了置换等价损失（`-log Σp`）和混合损失：
   - 纯等价损失：配对 400 局 **19.25%**，McNemar 精确双尾 **p = 0.027**，显著更差；
   - 混合 `ce + λ·group`：λ=0.1 → 18.00%、λ=0.3 → 25.75%、λ=0.5 → 25.25%，**全部不优于纯交叉熵**。
   - 原因：**花色不是噪声**——留哪张花色会影响后续的逢人配与同花顺，合并掉等于丢信息。
   - 实现保留在 `--loss group|mixed` 下做对照，**默认仍是 `ce`**。

**结论（阶段 5）**

- 行为克隆**追平**了启发式老师（51.50%，CI 46.61–56.36；换独立种子 52.00%；打 7 时 55.00%），
  对随机 **91.25%**。
- 但这**不是「超过老师」**：BC 的天花板就是老师。继续堆数据/轮数只会向 50% 收敛。
- 因此**阶段 6 的入口条件已经满足**：可以从「模仿」转向「自我对弈 / 搜索 / SDMC」了。
  在那之前唯一还值得做的工程项是候选裁剪（RULES.md Q13），因为它直接决定自我对弈的采样成本。

**评估口径（三条，必须一起说）**

1. 胜率口径仍是「**头游所在队获胜**」，不是完整升级赛。
2. 神经网络是**确定性策略**（argmax）；启发式带随机性。两者不是同一种「随机性条件」。
3. 神经网络评估用 `--level 2`，而数据集是 level 轮转采的；**不要用 `level=None` 评估**（分布外）。

### 6.8 人机对战界面（本地网页版，已可用）

**启动**（三种任选）：

```powershell
# 1) 默认打 2，端口 8765
& .\.venv\Scripts\python.exe -m interface.web_server

# 2) 换级牌与端口（打 7、端口 8899）
& .\.venv\Scripts\python.exe -m interface.web_server --level 7 --port 8899

# 3) 强制用启发式（不加载神经网络）
& .\.venv\Scripts\python.exe -m interface.web_server --no-neural
```

也可以直接双击 `interface\start_gui.bat`（会启动服务并自动打开浏览器），
然后访问 <http://127.0.0.1:8765/>。

**设计要点（这也是它的安全边界）**

- 玩家固定 **0 号位（A 队）**，队友 2 号，对手 1 / 3 号。
- **全部状态在服务端**：浏览器只提交「我要出这几张牌」，由 `GameState.play()` 校验合法性。
  改前端、或者直接用 HTTP 发请求，**都绕不过规则**。
- AI 默认用 `models/` 下**最新**的模型（当前 `bc_games_20261103_v3.pt`，验证一致率 0.7500、对启发式 53% 那个）；
  加载失败会自动退回启发式。想指定模型用 `--model models\bc_games_20261103_v3.pt`。
- **只用标准库 `http.server`**，前端是单文件原生 JS：**不联网、不需要 Flask / Node**，离线可用。
- 测试：`tests/test_web.py` 有 8 条端到端测试（其中一条通过真实 HTTP 把一整局打完）。

**已知限制（别当成品）**

- **单用户**：多个标签页会共用同一局，不是多人房间。
- 没有动画、音效、发牌提示，也没有对局回放界面。
- AI 强度取决于加载的模型；`models/` 里有 `bc_v3/v4/v5` 这些**故意做差的对照模型**，
  如果看到 AI 很弱，先确认它加载的是不是 v7。

```powershell
# 只跑界面测试（8 条，约 6 秒）
& .\.venv\Scripts\python.exe -m pytest tests/test_web.py -q
```

### 6.9 双击即玩的 exe 包（不用装 Python）

给别人玩、或者自己懒得开命令行时用这个。仓库根目录双击 **`build_exe.bat`**，
等一两分钟，得到：

```
dist\GuandanAI\GuandanAI.exe      ← 双击就能玩（旁边那一堆文件要一起保留）
dist\GuandanAI\使用说明.txt
dist\GuandanAI-win64.zip          ← 8.9 MB，可以直接发给别人
```

命令行等价写法：

```powershell
& .\.venv\Scripts\python.exe -m tools.package_exe           # 打包 + 写说明 + 压 zip
& .\.venv\Scripts\python.exe -m tools.build_exe --onedir    # 只出文件夹
& .\.venv\Scripts\python.exe -m tools.build_exe             # 只出单文件 exe
```

**做了什么**：`interface\app.py` 是 exe 的启动器（自动挑空闲端口、自动开浏览器、
关窗口即退出），PyInstaller 把 `interface\index.html` 一起塞进包里；
图标由 `tools\make_icon.py` 现画（`interface\guandan.ico`，Pillow 生成，多尺寸）。

**诚实说明**

- 打包版用**启发式策略**：会算最快出完、会抢先手、会给队友让路，但不记牌、不猜牌。
  它和神经网络版在实验室里打成 **53 : 47** 左右，属于同一档次；
  想用神经网络就在仓库里跑网页版（要 PyTorch，2 GB 以上，不进 exe）。
- 发布包用的是**文件夹形态**（onedir）而不是单文件：单文件版启动时要把运行库解压到
  系统临时目录，本机沙箱禁止这个写操作、无法验证，所以交付的是实测过的那份。
  你自己电脑上想要单文件，跑 `tools.build_exe` 就行。
- 实测（`tools\exe_smoke.py`，从解压出来的 zip 里跑）：起进程 → 打完一整局
  （25 步、出牌 8 次、过牌 17 次、排名 4 人）→ 对局记录 100 行 / 59.6 KB。
  复现：`& .\.venv\Scripts\python.exe -m tools.exe_smoke --exe dist\GuandanAI\GuandanAI.exe`

---

## 七、性能测试与硬件选型（2026-11-04 更新：统一入口）

### 7.1 一条命令跑基准

日常**只需要记一个入口**：`tools/benchmark.py`，用法统一成 `python -m tools.benchmark <子命令>`。

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab

# quick：约 20 秒，确认机器活着、GPU 能用（只跑 CPU 模拟 + 推理，不碰训练）
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset quick

# standard：约 3 分钟，日常基准（CPU / 推理 / 训练 / 导出 / 端到端 五项全跑）
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset standard

# full：约 10 分钟，样本更大，给买机器 / 租机器做选型用
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset full
```

| 预设 | 跑哪些模块 | 对局数 | pipe 局数 | 训练轮数 | 推理每档时长 | 量级 |
|---|---|---|---:|---:|---:|---|
| `quick` | `cpu`、`inference` | 20 | — | — | 0.4 秒 | 约 20 秒 |
| `standard` | 五项全跑 | 40 | 12 | 1 | 1.0 秒 | 约 3 分钟 |
| `full` | 五项全跑 | 100 | 30 | 2 | 2.0 秒 | 约 10 分钟 |

要自己配：`--preset custom --modules cpu,inference`（`custom` 必须给 `--modules`），
再按需加 `--games`、`--pipe-games`、`--train-epochs`、`--out`、`--warmup-seconds`。
`python -m tools.benchmark list` 能看到全部预设和子命令。

**报告**默认写到 `evaluation/bench_<预设>_<时间>.json`
（例：`evaluation/bench_quick_20261104_200736.json`），schema 固定 `gandan-benchmark/2`。
顶层字段：`schema / kind / preset / created / duration_seconds / warmup / host / config / modules / resources`
（`compare` 也认 v1 老格式，以及可选的 `metrics`）。
`warmup` 是统一预热：先把 CUDA 上下文、cublas 句柄热起来再计时，所以换机器、隔天重跑还能放一张表里比。

### 7.2 跟历史基线对比

```powershell
# 自动找仓库里的 v1 基线（evaluation/benchmark_v1_baseline.json）
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset quick --compare auto

# 指定任意一份基线报告
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset standard --compare evaluation\bench_quick_20261104_200736.json

# 两份已经跑完的报告，单独再比一次
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark compare evaluation\bench_quick_20261104_200736.json evaluation\benchmark_v1_baseline.json
```

对比规则（写在代码里，不是拍脑袋）：

- 只比两份报告**都有**的数字，缺的项直接跳过；
- 吞吐类：当前 / 基线 **≥ 1.10 判「更快」**、**≤ 0.90 判「变慢」**，中间算「持平」；延迟类反过来（越小越好）；
- `module_seconds`、`seconds`、`samples`、`games`、`decisions` 这类"测了多久 / 测了多少"的字段**不参与对比**；
- **±10% 以内不当结论**：温度、后台程序、跑的顺序都能带来这么大波动。

### 7.3 旧的测速脚本还能用

`tools/speed_test.py`、`tools/benchmark_throughput.py` 开头已加「[已合并]」提示，实现保留，旧命令照常能跑；
`benchmark_suite.py`、`scaling_test.py`、`roofline_probe.py`、`dataloading_test.py` 也都还在。
日常不用挨个记，统一走主入口的委托子命令（转调旧脚本）：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark scaling      # 多进程扩展性：1/2/4/8/16 进程
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark roofline     # 算力 / 带宽上限
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark dataloading  # 组批并行收益
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark batch        # batch 大小消融
```

仓库根目录的 `run_speed_test.bat`、`run_train_speed.bat`、`run_benchmark.bat` 也还能双击。

### 7.4 已得到的硬件结论

- 本机并行上限 **2.0–2.3×**（4~8 进程见顶），瓶颈是平台不是 GPU；
- 训练步只用到峰值算力 **1.55%**、带宽 **0.40%**，瓶颈是**每步固定开销（kernel launch）**；
- 因此"先加 batch / 上 CUDA Graphs"比"买更快的卡"更划算；
- 训练显存实测 **0.34 GB**，**4090 24GB 足够**（当前模型用不满，多进程推理也够）。

> ⚠️ GPU 占用率要用**任务管理器口径**（Windows GPU Engine 计数器）；
> `nvidia-smi` 的 `utilization.gpu` 在 Windows/WDDM 上会低估（实测同一段训练：45% vs 96%）。

2026-11-04 20:07 的 quick 实测（本机 RTX 5060 Laptop）：CPU 模拟 **5.72 局/秒**（554.5 决策/秒）、
推理 batch 128 到 **337,120 次/秒**、显存峰值 **1,451 MB**、功耗均值 23.1 W、54℃；
对比 v1 基线：CPU **1.21×**、batch 1 **1.37×**、batch 128 **1.15×**。
完整数字和局限见 [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md) E22。

## 八、如何复现「今天这套实验」

按顺序复制即可（Windows PowerShell，约 2.5 分钟跑完，含 300 局采集 + 导出）：

```powershell
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab
$env:PYTHONIOENCODING='utf-8'

# 1) 全量测试
& .\.venv\Scripts\python.exe -m pytest tests -q

# 2) 采集 300 局（约 52 秒）
& .\.venv\Scripts\python.exe -m training.collect_data --games 300

# 3) 结构校验（秒级）
& .\.venv\Scripts\python.exe -m training.check_dataset

# 4) 导出 npz（重放整局 + 逐条校验，约 58 秒）
& .\.venv\Scripts\python.exe -m training.export_dataset

# 5) 对抗评估：启发式 vs 随机，100 组 = 200 局（约 18 秒）
& .\.venv\Scripts\python.exe main.py evaluate --games 100 --opponent random

# 6) 性能基准：20 局（约 2 秒）
& .\.venv\Scripts\python.exe main.py bench --games 20

# 6b) 只跑人机对战界面的端到端测试（8 条，约 6 秒）
& .\.venv\Scripts\python.exe -m pytest tests/test_web.py -q
```

**如果要把神经网络基线也复现一遍**（需要 GPU；采集 3000 局约 17 分钟、导出约 9 分钟、训练 40 轮约 10 分钟，合计约 40 分钟）：

```powershell
# 7) 采集 3000 局（seed 20000 起，约 17 分钟）
& .\.venv\Scripts\python.exe -m training.collect_data --games 3000 --seed-start 20000

# 8) 结构校验 + 导出（校验秒级；导出约 9 分钟，会重放整局并逐条校验）
& .\.venv\Scripts\python.exe -m training.check_dataset
& .\.venv\Scripts\python.exe -m training.export_dataset

# 9) 合并成 5000 局（已有的 2000 局 npz + 刚导出的 3000 局 npz）
& .\.venv\Scripts\python.exe -m training.merge_datasets training\data\games_20261102_214537.npz training\data\games_20261102_222451.npz --out training\data\merged_5000.npz

# 10) 行为克隆训练（40 轮 / batch 64 / 剔除无选择样本；GPU 约 10 分钟）
& .\.venv\Scripts\python.exe -m training.train_bc --data training\data\merged_5000.npz --epochs 40 --batch-size 64 --min-candidates 2

# 11) 评估参考模型（务必显式 --checkpoint 与 --level）
& .\.venv\Scripts\python.exe -m training.evaluate_neural --checkpoint models\bc_v7_5000_40ep.pt --games 200 --opponent heuristic --level 2
& .\.venv\Scripts\python.exe -m training.evaluate_neural --checkpoint models\bc_v7_5000_40ep.pt --games 200 --opponent random --level 2
```

每一步该看到的关键行（数值以你机器为准，**步数是确定性的，耗时会有波动**）：

| 步骤 | 预期关键输出 |
|---|---|
| 1 | `370 passed in X.XXs`（没装 torch 时会跳过需要 torch 的用例，数字更小） |
| 2 | `对局数：300`、`决策样本：27794`、`出牌/过牌：11800 / 15994`、`平均步数：92.65` |
| 3 | `对局：300   决策：27794`、`结构校验通过。` |
| 4 | `样本数：27794（300 局）`、`平均候选：23.21   最大候选：1635`、`过牌比例：0.5754` |
| 5 | `策略 A 胜场：176 / 200    胜率：88.00%`、`95% Wilson 置信区间：[82.77%, 91.80%]`、`平均行动次数：116.96` |
| 6 | `平均步数：96.95（总步数 1939）`、`每局耗时：平均 ~109 ms` |
| 7 | `对局数：3000`、`决策样本：275328`、`平均步数：91.78` |
| 8 | `对局：3000   决策：275328`、`结构校验通过。`；导出 `平均候选：23.24   最大候选：2014` |
| 9 | `合并完成`、`games: 5000`、`samples: 459895`、`avg_candidates: 23.18` |
| 10 | 逐轮 `val_acc` 上升，第 40 轮约 `0.728`、`训练完成` 并写出 `.pt` + `.json` |
| 11 | 对启发式：`胜率：51.50%`、`[46.61%, 56.36%]`；对随机：`胜率：91.25%`、`[88.07%, 93.64%]` |

注意：

- 第 2 / 7 步默认会**新建**一个带时间戳的 `games_*.jsonl`，不会覆盖已有数据。
  想复用到已有文件，加 `--out training\data\games_复现.jsonl`。
- 第 4 / 8 步不带参数时取 `training/data/` 下**最新**的 `games_*.jsonl`。
- 第 9 步的第二个 npz 文件名取决于第 7 步实际生成的时间戳，**以你机器上的文件名为准**。
- 第 5 / 11 步会在 `evaluation/` 下**新建** `head_to_head_<时间戳>.csv`，不覆盖旧文件。
- 第 1 步的测试数若与你看到的不同，说明代码又变了：**以你跑出来的为准**，并去更新 `docs/STATUS.md`。

---

## 九、路线图（阶段名照抄负责人路线文件，状态据实标注）

| 阶段 | 名称 | 状态 |
|---|---|---|
| 1 | 规则引擎与基础对局 | ✅ **完成**（规则定稿 + 370 个测试） |
| 2 | 随机与启发式策略 | ✅ **基本完成**（随机 + 启发式，启发式已接入级牌） |
| 3 | 对局数据采集与复盘 | ✅ **基本完成**（300 / 2000 / 3000 / 合并 5000 局数据集、结构校验、npz 导出、复盘脚本；缺人类对局数据） |
| 4 | 人类高手策略学习 | ❌ 未开始（缺人类对局数据与记录格式） |
| 5 | 神经网络初始训练 | ✅ **基本完成（行为克隆已追平老师）**：v7 验证一致率 0.728、对启发式 **51.50%**、对随机 **91.25%**。<br>⚠️ BC 的上限就是启发式，再堆数据只会向 50% 收敛；**下一步要离开 BC** |
| 6 | SDMC 深度强化学习 | ❌ 未开始，但**入口条件已满足**（BC 已追平老师）：自我对弈 + Monte Carlo 回报 + Soft Warm Start + Soft Action Sampling |
| 7 | 大规模训练与模型竞争（服务器） | ❌ 未开始（需多进程自我对弈、模型联赛） |
| 8 | 本地部署 | 🟠 **部分完成**（离线人机对战已可用：`interface/web_server.py` + 单页前端 + `start_gui.bat`，8 条端到端测试）；<br>还差：模型管理与联赛、对局回放界面、打包/安装包 |

---

## 十、接手须知（项目纪律，违反视为事故）

1. **规则以确认表为唯一依据。**
   想加「常见规则」之前，先去 `docs/RULES.md` 看它是不是「待确认」。
   没确认就写进引擎 = 埋雷。**不许拿「别的掼蛋程序都这样」当理由。**

2. **先测试，再改代码。**
   改规则的正确顺序：改确认表 → 改测试（让测试红）→ 改代码（让测试绿）→ 改文档。
   顺序颠倒等于没有验收依据。

3. **不许虚报结果。**
   - 每个胜率、性能数字都必须能指着一条命令重跑出来；
   - 必须写清条件（对手是谁、几局、有没有开级牌、种子范围）；
   - 「率先出完」不等于「升级赛获胜」，不许偷换；
   - 不许把随机策略的成绩说成 AI 水平；
   - **不许说「已复现论文」「达到论文水平」。**
   - **不许把行为克隆说成「AI 学会打掼蛋」或「超过老师」**：它只是模仿启发式，
     理论上限就是启发式本身。准确表述是：**行为克隆追平了启发式基线
     （对老师 51.50%、对随机 91.25%），仍不是强化学习产物。**
   - 报「动作一致率」时必须说明**有没有剔除「只有 1 个候选」的样本**（恒对，会把数字抬高；
     5000 局合并数据里这类样本占 40.1%）。
   - 报神经网络胜率时必须写清 `--level`、局数、checkpoint，**不许用 `level=None` 评估**（训练分布外）。
   - 负结果也是结果：`bc_v3/v4/v5` 是**验证过的失败尝试**，不许从文档里删掉或只挑好看的报。

4. **不许用改测试的方式让测试变绿。**
   测试失败先判断是「代码错」还是「测试错」，写进 `docs/STATUS.md`，由负责人拍板。
   删测试、改断言去迁就代码，一律视为作弊。

5. **一次只推进一个阶段。**
   不要同时改规则引擎、编码器、训练脚本。每完成一块就跑一次全量测试。

6. **面向非软件专业的负责人写东西。**
   给完整命令（可直接复制）、给预期输出、给出错时怎么查。
   不要给「你自己补两行代码」。

7. **不要删文件。**
   旧数据、旧 CSV、旧日志都不许删，但**必须在文档里标明「历史、非当前基线」**。

8. **不要把隐藏信息喂给模型。**
   编码器只允许读自己的手牌 + 公开信息（已出牌池、上一手、各家剩余张数）。
   把别家手牌编码进状态 = 数据泄漏，实验全部作废。

9. **不要用 PowerShell 改写含中文的源码/配置。**
   `Get-Content | Set-Content -Encoding utf8` 在 Windows PowerShell 5.1 上会**按 ANSI 读 UTF-8**，
   写回后中文全变乱码，且往往只在运行时报 `SyntaxError: unterminated string literal`。
   **2026-11-04 已经这样毁过一次 `tools/parallel_export.py`。**
   要改源码就用编辑器的「编辑文件」功能（按行替换），不要用 shell 命令。
   同理：`.ps1` / `.bat` **必须纯 ASCII**（含中文会解析失败）。

---

## 十一、常见报错怎么排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'numpy'` / `pytest` | 用成了 PATH 里的 python | 用 `& .\.venv\Scripts\python.exe -m pytest ...` |
| `ModuleNotFoundError: No module named 'game_engine'` | 不在仓库根目录 | 先 `cd` 到 `GuanDan-AI-Lab` 再跑 |
| 中文/牌面显示成乱码 | 控制台编码 | `$env:PYTHONIOENCODING='utf-8'` |
| 源码里中文变成 `娌℃湁` 这类乱码、报 `SyntaxError: unterminated string literal` | 被 PowerShell 的 `Get-Content\|Set-Content` 改写过（按 ANSI 读了 UTF-8） | 用编辑器重写该文件；以后不要用 shell 改源码 |
| `无法将“...”项识别为 cmdlet` 或 `Activate.ps1 无法加载` | PowerShell 执行策略 | 不要激活，直接用 `.\.venv\Scripts\python.exe`；或 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `pytest: error: unrecognized arguments: --cache-clear` | 项目禁用了 pytest cache（`pytest.ini`） | 去掉该参数；这是刻意配置，不是故障 |
| `main.py: error: unrecognized arguments: --games 20`（在 `collect` 子命令下） | 该缺陷已于 2026-11-02 修复；若仍出现，说明 `main.py` 被回退 | 兜底写法：`python -m training.collect_data --games 20` |
| `RuntimeError: 种子 xxx 的对局超过最大行动次数` | 回合逻辑或策略陷入死循环 | 记下种子，单独用 `main.py play --seed xxx --no-log` 复现；这是**真 bug**，要查 |
| `FileNotFoundError: ... training/data ... 请先采集` | 还没跑过采集 | 先 `python -m training.collect_data --games 20` |
| `ValueError: 第 N 行是旧格式（自带 state 字段）` | 用了 19 MB 的旧数据集 | 旧数据已作废，重新采集 |
| `ModuleNotFoundError: No module named 'torch'` | 没装 torch（或在错误的 Python 里装了） | 按 5.2 用 cu128 索引装；或先只跑不依赖 torch 的部分 |
| `torch.cuda.is_available()` 是 `False` | 装成了 CPU 版轮子 | 重装：`pip install torch --index-url https://download.pytorch.org/whl/cu128` |
| 训练时 CUDA out of memory | 候选宽度太大（最大 1601）+ batch 太大 | 降 `--batch-size`（如 32/16），或按候选数分桶；不要全局补边 |
| `FileNotFoundError: 找不到模型：models\...` | 路径写错或还没训练 | 用参考模型 `models\bc_v7_5000_40ep.pt`，或先跑 `training.train_bc` |
| 神经网络评估结果明显偏低 | 用了 `--level none`（训练分布外），或没写 `--checkpoint` 拿到了过拟合的 `bc_v3_40ep.pt` | 加 `--level 2`，并显式指定参考模型 |
| 测试数量与本文不同 | 代码在并行开发；或没装 torch（相关用例会被跳过） | 以你跑出来的为准，并更新 `docs/STATUS.md` |

---

## 十二、文档地图

| 你想知道 | 看哪里 |
|---|---|
| 项目是什么、怎么跑、规矩是什么 | 本文件 `README.md` |
| 某条规则到底怎么定的、依据是什么、哪些还没定 | [docs/RULES.md](docs/RULES.md) |
| 现在做到哪了、有多少测试、有什么坑、数字是多少 | [docs/STATUS.md](docs/STATUS.md) |
| 模块之间怎么调用、数据如何流动、接口契约 | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| 数据集 / npz / JSONL 的字段什么意思 | [docs/DATA_FORMAT.md](docs/DATA_FORMAT.md) |
| 测试怎么组织、新增一条规则测试怎么写 | [docs/TESTING.md](docs/TESTING.md) |
| 术语（牌型、id、缩写）对照 | [docs/GLOSSARY.md](docs/GLOSSARY.md) |
| 什么时候改了什么、旧 README 错在哪 | [CHANGELOG.md](CHANGELOG.md) |
| 训练产物（3 个模型的指标与用法） | [models/README.md](models/README.md) |
| 负责人的 8 阶段路线原文 | `新建 文本文档.txt` |
| 论文方法 | `issn1000-1239.202220697.pdf` |

---

*本次重写：2026-11-02。以代码与测试为唯一依据。*
*如果你的操作与本文不符，先怀疑本文过期，再怀疑代码——但**永远不要**在没跑测试的情况下改规则。*
