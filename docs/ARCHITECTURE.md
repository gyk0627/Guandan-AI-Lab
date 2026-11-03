# GuanDan AI Lab 架构说明

> 本文基于 2026-11-02 的代码实测。所有函数签名、返回值、异常信息都是从当时的源码里读出来的，
> 行为描述都用 `.venv` 里的解释器跑过一遍验证；没有经过实测的推测一律不写。

面向两类读者：

- **项目负责人**（非软件专业，但在意规则准确性）：第 1、3、4 节够用，重点是「不变量」和「使用陷阱」。
- **接手的技术人员**：第 2 节（模块职责）与第 5 节（接口契约）是干活时真正要查的表。

---

## 1. 一局牌在代码里怎么流动（文字版数据流图）

从发牌到数据集，全链路只有一条主干。箭头右侧的注释是**实际调用点**（文件名:函数名），
可以按图索骥去看代码。

```
                        ┌──────────────────────────────────────────┐
                        │ game_engine/cards.py::create_deck()      │
                        │ 两副牌 = 2 × (4 花色 × 13 点数 + 2 王)   │
                        │ = 108 张，牌面是 ("S","3") 元组 / "SJ"   │
                        └───────────────────┬──────────────────────┘
                                            │ shuffle(seed) 后 4×27 切分
                                            ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ GameState                       game_engine/game_state.py              │
   │   hands[4] / current_player / leader / last_play / last_player         │
   │   pass_count / finished_players / game_over / level / history          │
   │   构造入口：GameState.new_game(seed, first_player=0, level=None)        │
   └───────────────┬────────────────────────────────────────────────────────┘
                   │ 轮到我出牌时，问「我能出什么」
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ① GameState.get_legal_moves(player)      ← 唯一带「队友」判断的入口    │
   │     · game_over / 没轮到你 / 你已出完        → 返回 []                 │
   │     · 队友是上一手出牌者（不能压队友）        → 返回 []（只能过牌）     │
   │     · 其余情况：把 (手牌, last_play, level) 交给 ②                    │
   └───────────────┬────────────────────────────────────────────────────────┘
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ② legal_moves(hand, previous, level)     game_engine/legal_moves.py    │
   │     先 ③ 生成全部候选，再用 can_beat 过滤；**不处理队友**、不含过牌     │
   └───────────────┬────────────────────────────────────────────────────────┘
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ③ generate_candidates(hand, level)                                     │
   │     模板枚举（EXHAUSTIVE_PATTERNS / CANONICAL_PATTERNS）               │
   │     + 逢人配补牌（_generate_wildcard_candidates）                      │
   │     每个候选都过一遍 ④ 判定，判不出来就丢掉                            │
   └───────────────┬────────────────────────────────────────────────────────┘
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ④ analyze_cards(cards, level)            game_engine/patterns.py       │
   │     返回 {type, count, size, main_rank, main_value, cards, level}      │
   │     或 None（不合法）。含红桃级牌时先剥离万能牌再枚举补法               │
   └───────────────┬────────────────────────────────────────────────────────┘
                   │ 候选有了，判断「能不能压过桌面」
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ⑤ can_beat(candidate, previous, level)   game_engine/compare.py        │
   │     → compare_cards(...) → 炸弹阶梯（4炸<同花顺<5炸<…<8炸）→ 1/0/-1    │
   └───────────────┬────────────────────────────────────────────────────────┘
                   │ 合法候选列表交给人/策略
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ⑥ choose_move(hand, legal, rng, game_state, player, level)             │
   │     players/heuristic.py                                               │
   │     evaluate_move → hand_cost + move_cost → 取 lowest + 0.08 抖动窗    │
   │     level 缺省时从 game_state.level 兜底（这一行很关键，见 §4 陷阱 1） │
   └───────────────┬────────────────────────────────────────────────────────┘
                   │ 返回 一手牌 或 None(=过牌)
                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ ⑦ game.play(player, cards)  /  game.pass_turn(player)                  │
   │     play 会**再用 get_legal_moves 复核一遍**，不在候选里就 ValueError  │
   │     成功后：扣手牌、更新 last_play/last_player/leader、pass_count 清零 │
   │             history.append({player, action:"play", cards})             │
   │     pass_turn：pass_count += 1，够人数就清桌并把牌权交给 leader        │
   └───────────────┬────────────────────────────────────────────────────────┘
                   │
        ┌──────────┴───────────────────────────────┐
        │                                          │
        ▼                                          ▼
┌───────────────────────────────┐   ┌────────────────────────────────────────┐
│ 记录 A：调试日志              │   │ 记录 B：训练数据（主干）               │
│ replay/game_logger.py         │   │ training/collect_data.py               │
│ GameLogger.record_turn(...)   │   │ collect_one_game(seed, level, policy)  │
│ → replay/game_<时间>_<seed>.jsonl │   每步一条 decision、局末一条 game     │
│ （逐回合快照，人看用）        │   │ → training/data/games_<时间戳>.jsonl   │
└───────────────────────────────┘   │   + games_<时间戳>.manifest.json        │
                                    └──────────────────┬─────────────────────┘
                                                       │
                                                       ▼
                                    ┌────────────────────────────────────────┐
                                    │ 编码 + 导出                            │
                                    │ training/export_dataset.py::export()   │
                                    │   按 seed 重放整局 → 重算候选 → 逐项校验│
                                    │   encode_state(game, player)  → 198 维 │
                                    │   encode_action(cand, level)  → 65 维  │
                                    └──────────────────┬─────────────────────┘
                                                       ▼
                                    ┌────────────────────────────────────────┐
                                    │ training/data/games_<时间戳>.npz        │
                                    │   states / cand_flat / cand_offsets /  │
                                    │   y_index / hand_ranks / team_win /    │
                                    │   level_up / is_pass                   │
                                    │ + games_<时间戳>.meta.json              │
                                    └──────────────────┬─────────────────────┘
                                                       ▼
                                    ┌────────────────────────────────────────┐
                                    │ 训练 / 推理：**尚未实现**              │
                                    │ models/ 与 interface/ 目前是空目录     │
                                    └────────────────────────────────────────┘
```

> 关于这张图：纯文本方框，在等宽字体下中文按两列宽渲染，个别方框的右边框可能差一两个字符，
> 不影响内容。每个方框第一行是**调用点**（文件::函数），下面的缩进行是它内部做了什么。

一句话概括：**规则判定只有 `patterns.py` 一个地方，牌力只有 `ranks.py` 一个地方，
「能出什么」只有 `legal_moves.py` 一个地方，别在别处复制这些逻辑。**

---

## 2. 模块职责表

「依赖谁」只列仓库内部依赖（标准库、numpy 省略）。

| 文件 | 负责什么 | 依赖谁 | 被谁依赖 |
|---|---|---|---|
| `game_engine/ranks.py` | 点数、牌力的**唯一**来源；顺子/连对/飞机的连续窗口；`rank_of`/`suit_of`/`rank_value`/`windows` | 无 | `wildcards`、`patterns`、`compare`、`legal_moves`、`heuristic`、`state_encoder`、`serialize`、`collect_data` |
| `game_engine/wildcards.py` | 逢人配的纯函数工具：识别、拆分、缺口计算、`fill_splits`。**故意不导入 patterns/legal_moves**，避免循环导入 | `ranks` | `patterns`、`legal_moves` |
| `game_engine/patterns.py` | 牌型 id 常量、`PATTERN_TYPES`、`TYPE_PRIORITY`、`analyze_cards` 判定 | `ranks`、`wildcards` | `compare`、`legal_moves`、`heuristic`、`state_encoder` |
| `game_engine/compare.py` | 牌型大小比较、炸弹阶梯（`bomb_power`）、`compare_cards`、`can_beat` | `patterns` | `legal_moves` |
| `game_engine/legal_moves.py` | 候选生成 `generate_candidates`、过滤 `legal_moves`、模板表 | `ranks`、`wildcards`、`patterns`、`compare` | `game_state`、`export_dataset` |
| `game_engine/game_state.py` | 一局对局的状态机：发牌、轮转、出牌、过牌、名次、`history` | `cards`、`legal_moves` | `collect_data`、`export_dataset`、`head_to_head`、`benchmark`、`evaluate`、`compare_strategies`、`state_encoder`(仅 `__main__` 自检) |
| `game_engine/cards.py` | 造牌、洗牌、发牌、手牌点数统计 | 无 | `game_state`、测试 |
| `players/heuristic.py` | 启发式策略：`hand_cost`/`move_cost`/`evaluate_move`/`choose_move` | `patterns`、`ranks` | `main`、`collect_data`、`head_to_head`、`compare_strategies`、`auto_game_heuristic` |
| `training/state_encoder.py` | 状态 198 维 / 动作 65 维编码、`pad_candidates`、分段表 `STATE_SLICES`/`ACTION_SLICES` | `patterns`、`ranks` | `export_dataset`、测试、（将来的）模型 |
| `training/serialize.py` | 牌 ↔ 落盘文本（`S:3` / `SJ`），唯一允许的转换点 | `ranks` | `collect_data`、`export_dataset` |
| `training/collect_data.py` | 采数据：跑局、写 JSONL（decision + game）、写 manifest、可复现自检 | `game_state`、`ranks`、`heuristic`、`serialize` | `main`、测试 |
| `training/export_dataset.py` | 重放 JSONL → 校验 → 编码 → 写 npz + meta；`pad_candidates` | `game_state`、`legal_moves`、`serialize`、`state_encoder` | `main`(无)、测试 |
| `training/check_dataset.py` | **只查结构**的快速校验（不导入引擎；实测 27,794 行 0.28 秒） | 仅标准库 | `main`(无)、测试 |
| `evaluation/head_to_head.py` | 成对同种子 + 换座位评估、策略工厂、Wilson 区间、CSV 输出 | `game_state`、`heuristic` | `benchmark`、`main`、测试 |
| `evaluation/benchmark.py` | 固定种子跑 N 局，统计 ms/局与平均步数 | `head_to_head` | `main`、测试 |
| `evaluation/evaluate.py` | 旧脚本：随机策略批量对局 → CSV | `game_state` | 无（历史遗留） |
| `evaluation/compare_strategies.py` | 旧脚本：启发式 vs 随机 → CSV | `game_state`、`heuristic` | 无（历史遗留） |
| `evaluation/analyze_v2.py` | 旧脚本：读 `strategy_comparison_v2.csv` 做统计 | 仅标准库 | 无（历史遗留） |
| `replay/game_logger.py` | 逐回合调试日志（`event`/`turn`/`hand_before`…），与训练数据格式**不同** | 仅标准库 | `main`(play 子命令)、`auto_game_heuristic` |
| `replay/analyze_game.py`、`replay/inspect_log.py` | 读 `replay/game_*.jsonl` 打印摘要 | 仅标准库 | 无（需手动运行） |
| `main.py` | 命令行入口：play / bench / evaluate / collect / test | 上面各模块（**惰性导入**） | 用户、`tests/test_cli.py` |
| `models/`、`interface/` | **空目录**，预留给模型与交互界面 | — | — |

补充事实：

- `training/`、`players/`、`evaluation/`、`replay/` 下**都没有 `__init__.py`**，靠 Python 3 的命名空间包机制导入，
  所以必须从仓库根目录运行（`main.py` 会自己把仓库根塞进 `sys.path`）。
- `check_dataset.py` 是唯一不依赖引擎的数据模块，这是它「快」的原因，也是它「查不出规则漂移」的原因。

---

## 3. 关键不变量（改代码时先看这里）

| # | 不变量 | 代码位置 | 谁在守它 |
|---|---|---|---|
| 1 | **108 张牌守恒**：任意时刻「四家剩余手牌 + 已打出的牌 = 108」 | `cards.create_deck()`（2×54）、`game_state.GameState.new_game` 按 27 切分 | `tests/test_game_state.py::test_card_conservation`（20 个种子逐回合断言）、`test_new_game_deals_108_cards`（与 `Counter(create_deck())` 全等） |
| 2 | **玩家 0/2 是 A 队，1/3 是 B 队**，队友 = `(player+2)%4`，出牌顺序 `0→1→2→3→0` | `GameState.teammate`、`collect_data.team_of`、`game_logger` 里的 `"A" if player in (0,2)` | `test_teammate`、`check_dataset`（队名与名次必须对得上） |
| 3 | **不能压队友的牌**：队友是上一手出牌者时，合法动作集为空，只能过牌 | `GameState.get_legal_moves` 里 `teammate(player) == last_player → return []` | `test_cannot_beat_partner`、`test_collect_keeps_pass_as_only_option_when_partner_leads` |
| 4 | **领出时不能过牌**：`last_play is None` 时 `pass_turn` 直接抛错 | `GameState.pass_turn` | `test_cannot_pass_when_leading`、`check_dataset`（`last_play is None` 时必须 `action_type == "play"`） |
| 5 | **`level` 必须贯穿所有分析调用**：级牌上浮到 15、红桃级牌变万能牌，都靠它 | `GameState.level` → `get_legal_moves` → `legal_moves` → `generate_candidates` / `analyze_cards` / `can_beat`；`choose_move` 从 `game_state.level` 兜底；`export` 用每条记录的 `level` | `test_level.py` 全文件（19 条）、`test_level_is_passed_to_legal_moves`、`test_game_state_passes_level_to_legal_moves` |
| 6 | **炸弹阶梯唯一**：4 炸(40) < 同花顺(45) < 5 炸(50) < 6 炸(60) < 7 炸(70) < 8 炸(80)；同张数炸弹比点数 | `compare.bomb_power` | `test_compare.py::test_bomb_ladder`（9 组参数化） |
| 7 | **四王炸不存在**，炸弹只有 4~8 张同点数；9 张同点数不是炸弹 | `patterns._analyze_normal` 的 `BOMB_MIN <= number <= BOMB_MAX` | `test_invalid_patterns`（`["SJ","SJ","BJ","BJ"]`、`["3"]*9`）、`test_four_jokers_never_played_together` |
| 8 | **一手牌只有一个解释**：多解时按 `TYPE_PRIORITY` 取最高（炸弹 > 同花顺 > 连续飞机 > 连对 > 顺子 > 三带二 > 三张 > 对子 > 单张） | `patterns.TYPE_PRIORITY`、`_analyze_with_wildcards` 末尾排序 | `test_wildcards.py` 多解用例 |
| 9 | **候选按牌组合去重**（先 `repr` 排序签名去重，再判定牌型），所以候选列表里没有重复的手牌组合 | `legal_moves.generate_candidates.add` | `test_generated_moves_are_unique`、`test_generated_wildcard_moves_are_unique` |
| 10 | **编码定长**：状态 198 维、动作 65 维，所有分量都在 [0,1]，纯函数（同输入同输出） | `state_encoder.STATE_DIM` / `ACTION_DIM` | `test_encoder.py::test_dimensions_are_stable`、`test_all_values_are_normalized`、`test_encoding_is_deterministic` |
| 11 | **过牌有独立 flag**：`encode_action(None)` 是「前 63 维全 0 + 最后 1 维 1」，与 padding 的全 0 向量严格可区分 | `state_encoder.encode_action` | `test_pass_flag_is_unique` |
| 12 | **名次是 0..3 的排列**，三人出完后第四名自动补进 `finished_players` | `GameState.play` 里的 `len(finished_players) == 3` 分支 | `test_game_ends_with_full_ranking`、`check_dataset` |
| 13 | **`history` 只追加**，`action` 只有 `"play"` / `"pass"` 两种值 | `GameState.play` / `pass_turn` | `test_play_removes_cards_and_tracks_history`、`state_encoder.encode_played_pool`（只统计 `play`） |

---

## 4. 使用陷阱（真实踩过，务必先读）

### 陷阱 1（最坑）：`analyze_cards(cards)` 漏传 `level`，含红桃级牌的牌会**静默返回 None**

看起来像「牌型非法」，实际是「你忘了告诉引擎本局打几」。因为 `level=None` 时，
红桃级牌只是普通一张牌，`split_wildcards` 返回空，`_analyze_normal` 按普通牌判定，往往就判不出来。

实测（2026-11-02，`.venv` 实跑）：

```text
analyze_cards([("H","2"), ("S","3")])        → None            ← 看起来「非法牌型」
analyze_cards([("H","2"), ("S","3")], "2")   → 对子 3          ← 真实结果（红桃2当逢人配）
analyze_cards([("H","2"), ("S","3"), ("D","3")])      → None
analyze_cards([("H","2"), ("S","3"), ("D","3")], "2") → 三张 3
```

同样的漏传会沿着链路放大（实测）：

```text
generate_candidates(hand)       → 3 个候选
generate_candidates(hand, "2")  → 5 个候选      # hand = [("H","2"),("S","3"),("D","4")]
legal_moves(hand, ["A"])        → []
legal_moves(hand, ["A"], "2")   → [("H","2")]   # 逢人配单张按级牌 15 算，能压 A
```

落到策略层更隐蔽——`move_cost` 把「判不出来的牌型」当成 1000 分惩罚：

```text
move_cost([("H","2"), ("S","3")])      == 1000.0    # 策略以为这是一手烂牌
move_cost([("H","2"), ("S","3")], "2") == 0.0       # 实际是普通对子
```

（`tests/test_level.py::test_heuristic_receives_level` 就是把这两个数字钉死的用例。）

**规矩：只要手里可能出现红桃级牌，`analyze_cards` / `compare_cards` / `can_beat` /
`generate_candidates` / `legal_moves` / `move_cost` / `encode_action` / `encode_pattern`
全部要显式传 `level`。** 唯一会帮你兜底的是 `choose_move`（从 `game_state.level` 读）和
`GameState.get_legal_moves`（用 `self.level`）。

### 陷阱 2：`encode_action` 漏 `level` 会产出「既不是过牌、也没有牌型」的向量

不报错、不抛异常，但 65 维向量是坏的。实测 `encode_action([("H","2"),("S","3")])`：

| 分段 | 结果 | 说明 |
|---|---|---|
| `cards`（54 维） | 两张牌各自 0.5 | 正常 |
| `pattern`（9 维） | **全 0** | 本该是「对子」那一维 1.0 |
| `count` | 0.0740… | 2/27，正常 |
| `is_pass` | 0.0 | 不是过牌 |

也就是说这一行既不像过牌（`is_pass=0`），也拿不到牌型信息。传 `level="2"` 后 `pattern` 的第 2 维才变成 1.0。
数据集里出现这种行，训练时网络学到的就是噪声。

### 陷阱 3：`GameState.get_legal_moves` 与 `legal_moves` **不是一回事**

| | `GameState.get_legal_moves(player)` | `legal_moves(hand, previous, level)` |
|---|---|---|
| 判「不能压队友」 | ✅ 会（队友是 last_player 时返回 `[]`） | ❌ 不会（照常返回能压的牌） |
| 判「是否轮到你 / 是否已出完 / 是否已结束」 | ✅ 会 | ❌ 不会 |
| 级牌来源 | `self.level` | 参数 `level` |
| 含过牌选项 | ❌ 不含 | ❌ 不含 |
| 用途 | 对局中唯一该用的入口 | 纯函数，给测试/导出重放用 |

**真实踩过的坑：导出/重放时绕过 `get_legal_moves`，直接用 `legal_moves` 重算候选，会产生候选数量错位。**
因为「队友是上一手出牌者」的那一步，采集时记录的是 `num_candidates = 1`（只有过牌），
而 `legal_moves` 会返回一堆能压队友的牌，于是 `selected_index` 全部错位、标签对不上。

现在的正确写法在 `training/export_dataset.py::build_candidates`：**先判队友**（返回 `[None]`），
再调用 `generate_candidates` / `legal_moves`，最后按需 `append(None)`。
`collect_data.py` 里也是同一套：`candidates = list(legal)`，`last_play is not None` 时再 `append(None)`。
这条一致性由 `export` 的校验兜住——候选数量不一致会直接 `RuntimeError`（见
`tests/test_data_pipeline.py::test_export_detects_candidate_drift`）。

### 陷阱 4：`get_legal_moves` 返回 `[]` 有两种含义，别用 `if not moves` 判断「能不能过牌」

`[]` 既可能是「没有能压过的牌」，也可能是「队友的牌不能压」。要不要过牌只看 `game.last_play` 是否为 `None`：

```python
moves = game.get_legal_moves(player)
if not moves:            # 错：领出时 moves 一定非空，但队友领出时也走这里
    game.pass_turn(player)   # 万一将来把「领出但无牌可出」的情形放进来，这里会抛错
```

正确姿势（`collect_data.py` / `head_to_head.py` / `main.py` 都用这个）：

```python
if game.last_play is None:
    game.play(player, selected)      # 领出必须出牌
else:
    game.pass_turn(player)           # 有桌面牌才可以过
```

### 陷阱 5：`play()` 会重新生成全部候选复核，手搓「合法牌型」也可能被拒

`GameState.play` 里除了检查「牌在手里」，还会 `get_legal_moves` 再比一遍
（`Counter(move) == Counter(cards)`）。所以：

- 直接构造一手规则上合法、但**当前不能压桌面**的牌 → `ValueError: 这手牌不符合当前出牌规则`。
- 想构造任意牌局做测试，别绕过 `play` 的校验，像 `tests/test_game_state.py::make_game` 那样
  **先 `new_game` 再覆盖 `hands`**（`__init__` 只在构造时校验 4×27）。

### 陷阱 6：候选集不是「全部合法牌型组合」——连对/飞机只取一个规范解

`legal_moves.py` 把模板分成两类：

- `EXHAUSTIVE_PATTERNS`：单张/对子/三张/炸弹/顺子/三带二，会枚举**不同花色的选法**（残局里保留哪张有意义）；
- `CANONICAL_PATTERNS`：连对/连续飞机只取 `available[:count]` 这一个规范解，
  否则组合数会爆炸（注释里举的例子：4 张同点 × 6 个连续点数 = 6^6 种花色排列）。

含义：**被评估的策略如果只能从候选里选，它就永远打不出「连对的另一种花色组合」**。
这不是 bug，是明确的取舍，已在 `docs/STATUS.md` 记录为限制。

### 陷阱 7：牌面文本必须带冒号（`"S:3"`），否则黑桃 J 会撞小王

内存里是 `("S","J")`，落盘是 `"S:J"`；小王是 `"SJ"`。拼接写法 `"S"+"J"` 会得到 `"SJ"`，
重放时被解析成小王，整局手牌错位。详见 [DATA_FORMAT.md](DATA_FORMAT.md) 的「牌文本格式」。
`serialize.text_to_card` 对不带冒号的普通牌会直接抛
`ValueError: 无法解析的牌：…（普通牌必须写成 S:3 这种带冒号的形式）`。

### 陷阱 8：`level` 传错/传漏会让「状态编码」和「动作编码」互相矛盾

`encode_state` 的级牌 one-hot 取自 `game.level`，动作的牌型 one-hot 取自你传进去的 `level`。
两者不一致时，同一个样本的状态说「打 2」，动作却按「无级牌」解释。
`export_dataset.export` 的做法是**两者都用 `record["level"]`**（`encode_state` 间接用同一个 `game` 对象）。

---

## 5. 接口契约表（核心）

约定：**牌** = `("S","3")` 元组或 `"SJ"` / `"BJ"` 字符串；`hand` = 牌的列表；
`level` = `"2".."A"` 之一或 `None`（`None` = 无级牌模式，此时没有逢人配、2 就是最小的 2）。

### 5.1 规则层（纯函数，不持有状态）

| 函数 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `analyze_cards(cards, level=None)`<br>`patterns.py` | `cards`：牌列表（空列表也接受）<br>`level`：本局打几 | 合法 → `dict`：`type`（牌型 id）、`count`（张数）、`size`（不同点数个数）、`main_rank`、`main_value`、`cards`（原样复制）、`level`<br>非法/空 → `None` | **不抛**。未知点数（如 `"X"`）内部 `KeyError` 被吞掉后返回 `None` | 含红桃级牌时**必须**传 `level`（见 §4 陷阱 1）。一手牌多解时返回 `TYPE_PRIORITY` 最高的解释。结果里的 `main_value`：顺子族用自然牌力，其余用含级牌上浮的牌力 |
| `compare_cards(cards_a, cards_b, level=None)` | 两手牌 | `1` = A 压过 B；`0` = 同型同大小**或**牌型无法互相压制（异型/异张数）；`-1` = B 压过 A | `ValueError("存在无法识别的牌型")` —— 任一侧 `analyze_cards` 返回 `None` 就抛（含空列表） | 不要用它判断「是否合法」，它只回答「谁大」。设计上**故意**对非法输入抛错，避免静默当成「压不过」 |
| `can_beat(candidate, previous, level=None)` | 同上 | `bool`（`compare_cards(...) == 1`） | 同 `compare_cards` | 语义就是「candidate 能不能压 previous」。`previous` 必须是一手合法牌 |
| `generate_candidates(hand, level=None)` | `hand`：手里现有的牌（**不校验**是否真是一手牌） | `list[list[card]]`，每个元素是一手合法出牌；**不含空列表（不过牌）**；按牌组合去重 | 无（内部判定失败就丢弃） | 结果顺序稳定：`_group_hand` 按 `repr` 排序，实测**与 `hand` 的传入顺序无关**（同集合不同顺序 → 完全相同的列表）。不会生成「手里没有的牌」 |
| `legal_moves(hand, previous=None, level=None)` | `previous=None` 表示自由领出 | `list[list[card]]`；`previous` 非空时只保留 `can_beat` 为真的候选 | 透传 `can_beat` 的 `ValueError`（`previous` 非法时） | **不处理队友、不含过牌、不校验是否轮到你**（见 §4 陷阱 3） |
| `is_valid_play(cards, level=None)` / `is_bomb_like(info)` / `type_label(info)` / `is_sequence_type(type)` | — | `bool` / `bool` / 中文名（`None` → `"不合法"`）/ `bool` | 无 | 显示与分支判断用 |
| `rank_value(rank, level=None)` / `natural_value(rank)` | `rank`：`"2".."A"` / `"SJ"` / `"BJ"` | `int`（2..14 / 15 / 16 / 17） | `KeyError`（未知点数） | 级牌 = 15，小王 16，大王 17 |
| `windows(length)` | `length`：窗口长度 | `tuple[tuple[int, ...]]`；`length<1` 或 `>13` → `()` | 无 | `windows(5)` 就是 9 种顺子；A2345 **不**在内 |
| `split_wildcards(cards, level=None)` / `is_wildcard(card, level=None)` / `count_wildcards` / `fill_splits(available, need, wildcard_count)` / `window_deficit(...)` | — | `(wildcards, others)` / `bool` / `int` / `[(real_count, wild_count), ...]` / `int` | 无 | `level=None` 时 `is_wildcard` **永远 False** |

### 5.2 引擎层（`game_engine/game_state.py`）

| 方法 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `GameState.new_game(seed=None, first_player=0, level=None)` | `seed`：传给 `random.Random`，同 seed 同牌<br>`first_player`：首位出牌者，同时是 `leader`<br>`level`：本局级牌 | `GameState` | `ValueError("牌堆必须有108张牌")`（防御性，正常不会触发） | 内部 `create_deck()` + `shuffle` + 4×27 切分。`__init__` 还会校验 `len(hands)==4` 且**每人恰好 27 张**（`ValueError`），所以想构造小牌局必须像测试那样先 `new_game` 再覆盖 `hands` |
| `game.get_legal_moves(player=None)` | `player` 缺省 = `current_player` | `list[list[card]]`（**不含过牌**）；下列情况返回 `[]`：对局已结束 / `player != current_player` / `player` 已出完 / **队友是上一手出牌者** | 透传 `legal_moves` 的异常 | 对局中唯一该用的入口。返回 `[]` 有两种含义（见 §4 陷阱 4） |
| `game.play(player, cards)` | `cards`：要出的牌（不能空） | `True` | `ValueError` 六种：`"游戏已经结束"`、`"现在还没有轮到这名玩家"`、`"这名玩家已经出完牌"`、`"出牌不能为空"`、`"所选牌不属于当前玩家"`、`"这手牌不符合当前出牌规则"` | 副作用：扣手牌、`last_play/last_player/leader` 更新、`pass_count=0`、`history.append`、可能把人加进 `finished_players`、三人出完后自动补第四名并置 `game_over=True`、推进 `current_player` |
| `game.pass_turn(player)` | — | `True` | `ValueError`：`"游戏已经结束"`、`"现在还没有轮到这名玩家"`、`"领出阶段不能过牌"`、`"不能跳过自己的领出"` | 过牌人数够了就清桌（`last_play=None`、`last_player=None`、`pass_count=0`），牌权回到 `leader`（若 `leader` 已出完则顺延给下一个未出完的人） |
| `GameState.teammate(player)` | 静态方法 | `(player+2)%4` | 无 | 队伍划分的唯一实现点之一 |
| `game.next_player(player)` | — | 下一个未出完的玩家编号；找不到 → `None` | 无 | 内部用 |
| `game.show_status()` | — | `None`（打印） | 无 | 调试用，会 `print` 中文 |

### 5.3 策略层（`players/heuristic.py`）

| 函数 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `choose_move(hand, legal_moves, rng=None, game_state=None, player=None, level=None)` | `hand`：当前手牌<br>`legal_moves`：**候选列表**（通常来自 `get_legal_moves`）<br>`rng`：`random.Random`，缺省新建（**不可复现**）<br>`game_state` + `player`：给了才会考虑队友/对手张数/是否值得过牌<br>`level`：缺省时从 `game_state.level` 兜底 | 一手牌（`list[card]`） 或 `None`（过牌） | 不抛（内部 `analyze_cards` 判不出来就当 1000 分惩罚） | `legal_moves` 为空 → 直接返回 `None`。**返回值一定来自 `legal_moves` 里的一手**（除 `None`）。注意 `player` 与 `game_state` **两个都给**才会启用对局感知；只给一个等同于朴素模式。`rng` 只用于在「最优分 +0.08 抖动窗」内随机挑一手，所以同 `rng` 同输入可复现 |
| `evaluate_move(hand, move, level=None)` | `move` 必须在 `hand` 里 | `float`，**越低越好** | 不抛（`move` 里有牌不在手上 → 返回 `10000.0`） | `= hand_cost(remaining) + move_cost(move) - len(move)*0.025` |
| `hand_cost(hand, level=None)` | — | `float`，越低越好 | 无 | 按点数分组累加：单张 1.30（再减 `value*0.015`）、对子 0.62、三张 0.28、≥4 张 0.12。级牌按 15 计 |
| `move_cost(move, level=None)` | — | `float`：炸弹 2.8、同花顺 2.0、其余 0.0、**判不出牌型 1000.0** | 无 | 就是 §4 陷阱 1 里那个 1000 |

### 5.4 编码层（`training/state_encoder.py`）

| 函数 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `encode_state(game, player=None)` | `game`：`GameState`；`player`：观测者，缺省 `game.current_player` | `list[float]`，长度 **198**，全部分量在 [0,1] | `ValueError("玩家编号必须是0、1、2或3")`；级牌非法 → `ValueError("无法识别的级牌：…")`；牌点/花色无法识别 → `ValueError` | 只读 `game.hands[player]` 与公开信息（`history`、`last_play`、`last_player`、`pass_count`、各家**张数**）。**绝不读别家具体牌面**（`test_no_information_leak_from_other_hands` 20 个种子守着）。假定观测者就是行动者，没有单独编码「自己相对座位」 |
| `encode_action(action, level=None)` | `action`：一手牌；`None`/`[]` → 过牌 | `list[float]`，长度 **65**，全部分量在 [0,1] | 同上的 `ValueError` | 过牌 = 前 63 维全 0 + `is_pass=1`；出牌 = `cards(54) + pattern(9) + count(1) + is_pass(0)`。**`level` 影响 `pattern` 段**（§4 陷阱 2） |
| `encode_cards(cards)` | 任意牌列表 | 54 维，每槽位 = 该花色点数张数 / 2（截断到 [0,1]） | `ValueError`（未知点/花色） | 兼容 `"3"` 这种无花色点数写法（记到黑桃槽），**正式对局不要用** |
| `encode_played_pool(game)` | — | 54 维 | `ValueError` | 只统计 `history` 里 `action == "play"` 的记录 |
| `encode_level(level)` | — | 14 维 one-hot（13 点数 + 「无级牌」） | `ValueError("无法识别的级牌：…")` | — |
| `encode_pattern(cards, level=None)` | — | 9 维 one-hot；空牌或判不出 → **全 0** | 无（内部吞掉） | 全 0 也可能意味着「漏传 level」 |
| `encode_legal_actions(legal_moves, level=None)` | — | `list[list[float]]` | 同上 | 逐个调 `encode_action` |
| `pad_candidates(vectors, dim=None)` | `vectors`：可变长向量序列，元素可为 `None`（占位） | `(matrix, mask)`；`mask=1` 真实、`0` 占位 | `ValueError("dim 必须是正整数")`；向量比 `dim` 长 → `ValueError` | `dim=None` 时取本批实际最大长度（不是全局最大，见 [DATA_FORMAT.md](DATA_FORMAT.md) 补边警告） |

### 5.5 数据层（`training/`）

| 函数 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `collect_one_game(seed, level=None, policy="heuristic")` | `seed`：发牌与 `rng` 都用它（`rng = Random(seed+1000)`）<br>`level`：本局级牌<br>`policy`：`"heuristic"` / `"random"` | `(decisions, summary)`：`decisions` 是长度 = 步数的 `dict` 列表；`summary` 是一条 game 记录 | `RuntimeError`：超过 `MAX_STEPS=2000` 步；或策略给出了不在候选里的动作 | **确定性**：同 `seed` + 同 `level` + 同 `policy` → 逐字节相同的记录（`verify_reproducible` 自检、`test_collect_one_game_is_deterministic`）。候选顺序固定为「全部合法出牌，最后才是过牌」 |
| `dump_game(decisions, summary)` | — | `list[str]`，每行一个 JSON（`ensure_ascii=False, sort_keys=True`，**无时间戳**） | 无 | 可复现的前提：不写时间戳 |
| `collect_dataset(num_games=100, start_seed=1000, level_mode="cycle", fixed_level=None, policy="heuristic", output_path=None)` | `level_mode`：`cycle`（2..A 轮转）/ `fixed` / `none` | `(output_path, manifest)` | 目录不可写时 `OSError` | 写 `games_<YYYYmmdd_HHMMSS>.jsonl` + 同名 `.manifest.json` |
| `upgrade_amount(ranking, team)` | `ranking`：4 人名次列表 | `3`/`2`/`1`/`0` | 该队没进前两名 → `0`（`positions[0] != 1` 短路） | 第一&第二升 3、第一&第三升 2、第一&第四升 1 |
| `export(path, out_path=None, limit=None, verify=True)` | `path`：JSONL；`limit`：只导前 N 局（按 seed 排序取）<br>`verify=False` 跳过一致性校验 | `(out_path, meta)` | `ValueError`：旧格式记录带 `state` 字段<br>`RuntimeError`：重放当前玩家不符 / 对局已结束 / 手牌不一致 / **候选数量不一致** / `selected_index` 越界 / 候选与动作不符 / 状态或动作维度异常 | 按 `seed` + `level` 重放整局。**`verify=True` 时任何规则或生成器改动都会立刻炸**——这是抓「规则漂移」的唯一手段 |
| `pad_candidates(cand_flat, cand_offsets, max_width=None)`（export 版） | `cand_offsets`：长度 N+1 | `(padded (N,W,65), mask (N,W))` | 无 | 返回的 `mask` 是 `float32`。`max_width` 缺省取**整份数据**的最大候选数（危险，见 DATA_FORMAT） |
| `check_file(path)` / `report(result)` | — | `dict`（`file/games/decisions/errors/stats`）/ 退出码 `0`/`1` | `OSError`（文件不存在） | **只查结构**，不导入引擎 |
| `verify_reproducible(seed, level, policy)` | — | `True` | `RuntimeError("数据采集不可复现：两次运行结果不同")` | `--check` 走这里 |

### 5.6 评估层（`evaluation/head_to_head.py`）

| 函数 | 参数 | 返回 | 抛什么异常 | 前置条件 / 备注 |
|---|---|---|---|---|
| `play_one_game(seed, strategy_a, strategy_b, a_team="A", first_player=0, level=None, max_steps=2000)` | 策略可以是注册名 / 工厂 / 带 `choose` 的对象 | `dict`：`seed/a_team/winner_team/a_won/steps/seconds/first_player/ranking` | `ValueError`（`a_team` 非法、`first_player` 非法）；`GameTooLongError`（超步数）；`RuntimeError`（领出阶段策略返回了 `None`） | 每个座位独立 `rng = Random(seed*100+player)`，整局可复现 |
| `run_head_to_head(...)` | 见 `--help` | `dict` 摘要（含 `win_rate`、`wilson_low/high`、`by_team`、`pair_outcomes`、`csv_path`） | `ValueError`（`games<1`、`max_steps<1`）；`GameTooLongError` | 同一 seed 打两局（策略 A 换坐 A/B 队），抵消先手与座位偏差；CSV 写 `utf-8-sig` |
| `wilson_interval(successes, total, z=1.959963984540054)` | — | `(low, high)`，裁剪到 [0,1]；`total==0` → `(0.0, 1.0)` | `ValueError`（负数 / `successes>total`） | 不依赖 scipy |
| `summarize_records(records)` | — | `dict` | `ValueError("没有对局记录，无法统计")` | 纯函数，可用假数据单测 |
| `create_policy(strategy, seed=0)` | 注册名 / 工厂 / 已构造对象 | 策略对象（必有 `choose(game, player, legal_moves)`） | `ValueError`（未知名字）；`TypeError`（类型不对 / 工厂返回的对象没有 `choose`） | 已注册：`"random"`、`"heuristic"` |

---

## 6. 已知限制（写在这里，避免以后被当成 bug 讨论）

| 限制 | 现状 | 依据 |
|---|---|---|
| 没有「升级赛」流程 | 只在数据标签里出现（`upgrade_amount`），引擎不发牌进阶 | `collect_data.py` 注释、`CHANGELOG.md` 第 201 行 |
| 没有接风 / 进贡 / 抗贡 | 未实现（见 [GLOSSARY.md](GLOSSARY.md)） | 全仓无对应代码 |
| 候选集不含连对/飞机的花色变体 | 只取一个规范解（§4 陷阱 6） | `legal_moves.py` 模块注释、`docs/STATUS.md` 4.5 |
| 领出者已出完时的接续规则 | 代码里写的是「顺延给下一个未出完的人」，注释标注**待按纸质规则确认** | `game_state.pass_turn` 内注释 |
| 一手牌多解时的取舍 | 按 `TYPE_PRIORITY` 取最高，注释标注**待项目负责人确认** | `patterns.py` 注释 |
| 级牌在顺子/连对/连续飞机里按自然牌力 | 已实现，但确认表里没有这句话，标注「细则待追认」 | `CHANGELOG.md` 第 71 行、`docs/RULES.md` Q2 |
| 模型 / 训练 / 交互界面 | `models/`、`interface/` 是空目录，**没有已训练模型** | 目录实测 |
| `play_one_game` 与 `collect_one_game` 的步数上限都是 2000 | 正常一局约 90~120 步，触发上限说明策略死循环 | `MAX_STEPS` / `DEFAULT_MAX_STEPS` |
