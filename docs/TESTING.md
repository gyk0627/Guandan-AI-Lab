# GuanDan AI Lab 测试说明

> 本文基于 2026-11-02 的代码实测。用例数是当天在仓库目录实跑
> `pytest tests --collect-only -q` 逐文件数出来的；性能数字同样是在本机实测。

当前状态：**296 passed**（全量跑约 6 秒）。测试是这套引擎唯一可信的规则说明书 —— 想确认某条规则，
先看 `tests/` 里有没有用例，再信文档。

---

## 1. 测试分层

10 个测试文件、5 个层。分层的意义：**下层坏了，上层的失败都是噪声**，所以修 bug 从下往上查。

| 层 | 文件 | 用例数 | 守的是什么 |
|---|---|---|---|
| 规则层 | `tests/test_ranks.py` | 15 | 牌力唯一真理源：`2` 最小、A=14、级牌=15、王 16/17、9 种顺子窗口、`windows` 边界、`A2345` 不是窗口 |
| 规则层 | `tests/test_patterns.py` | 49 | 牌型识别：9 种合法牌型（参数化 21 条）+ 非法形态 17 条 + `main_value` 取值 + 级牌在顺子里按自然牌力 + 9 张同点数不是炸弹 |
| 规则层 | `tests/test_compare.py` | 18 | 大小比较：炸弹阶梯 9 组、`2` 的位置、三带二只看三张、同花顺平局、异型不能互压、非法输入抛 `ValueError` |
| 规则层 | `tests/test_legal_moves.py` | 18 | 候选生成：生成即合法、去重、连对最少 2 对、9 种顺子全生成、不含王、四王炸不出现、三带二不带单张、`legal_moves` 按上家过滤 |
| 规则层 | `tests/test_level.py` | 19 | 级牌全链路：`GameState.level` → `legal_moves` → `analyze_cards`/`compare_cards` → 启发式策略；漏传 level 的后果被钉死 |
| 规则层 | `tests/test_wildcards.py` | 52 | 逢人配：识别/拆分、能补成哪些牌型、多解取优先级最高、生成器覆盖、去重、生成结果可真正 `play`、性能回归 |
| 引擎层 | `tests/test_game_state.py` | 44 | 回合状态机：108 张守恒（20 个种子）、不能压队友、领出不能过牌、清桌后牌权归位、名次完整、跳过已出完的人、启发式自对弈能走完（10 个种子） |
| 表示层 | `tests/test_encoder.py` | 37 | 编码 v2：198/65 维与分段长度、**无信息泄漏**（20 个种子）、相对座位轮转、级牌 one-hot、过牌 flag 唯一、`pad_candidates` 的 mask、取值全在 [0,1]、确定性 |
| 数据层 | `tests/test_data_pipeline.py` | 19 | 序列化 round-trip、黑桃 J 不与小王撞车、升级换算、采集可复现、队友领出时候选只有过牌、导出维度与标签、**候选漂移必须报错**、补边与 `max_width` |
| 入口层 | `tests/test_cli.py` | 25 | 5 个子命令的 help/smoke、`collect` 参数按签名透传、成对评估写 4 行 CSV 且换座位、`--json` 摘要、超步数返回 1、Wilson 区间参考值、统计函数用假数据单测 |
| **合计** | 10 个文件 | **296** | 15+49+18+18+19+52+44+37+19+25 = 296 ✅ |

数用例数的命令（自己复核用）：

```powershell
$env:PYTHONIOENCODING='utf-8'
& .\.venv\Scripts\python.exe -m pytest tests --collect-only -q | Select-Object -Last 1
# 296 tests collected

# 逐文件数
foreach ($f in Get-ChildItem tests\test_*.py) {
    $c = (& .\.venv\Scripts\python.exe -m pytest $f.FullName --collect-only -q 2>&1 |
          Select-String -Pattern '::').Count
    "{0}: {1}" -f $f.Name, $c
}
```

---

## 2. 怎么跑

所有命令都在**仓库根目录**执行，解释器必须是仓库里的 `.venv`（不要用 PATH 里的 `python`）。

```powershell
# 0）建议每次开新终端先设这一行，否则中文输出可能乱码
$env:PYTHONIOENCODING='utf-8'

# 1）全量（约 6 秒）
& .\.venv\Scripts\python.exe -m pytest tests -q

# 2）单文件
& .\.venv\Scripts\python.exe -m pytest tests/test_wildcards.py -q

# 3）单个用例（-k 按名字模糊匹配）
& .\.venv\Scripts\python.exe -m pytest tests/test_level.py -k "wildcard" -v

# 4）某一个精确节点
& .\.venv\Scripts\python.exe -m pytest "tests/test_compare.py::test_bomb_ladder" -q

# 5）遇错即停（改代码时最常用）
& .\.venv\Scripts\python.exe -m pytest tests -q -x

# 6）带失败详情（不加 -q 就是默认的详细模式）
& .\.venv\Scripts\python.exe -m pytest tests -x

# 7）走统一入口（等价于 1），会打印实际执行的命令与工作目录
& .\.venv\Scripts\python.exe main.py test
```

`pytest.ini` 里已经写好默认值，所以不加参数也不会跑错目录：

```ini
[pytest]
testpaths = tests
addopts = -p no:cacheprovider
```

> `-p no:cacheprovider` 关掉了 pytest 的缓存插件，所以**不会生成 `.pytest_cache`**。
> 仓库根目录里遗留的 `pytest-cache-files-*` 目录是早期没加这个参数时留下的，可以不管。

---

## 3. 如何新增一条规则测试（红 → 绿 → 全绿）

流程固定四步，**不要先改代码再补测试**：

1. **写断言**：把「负责人确认的规则」翻译成一句 `assert`，跑一次，必须**红**。
2. **确认红的原因对**：是「规则没实现」，而不是「测试自己写错了变量名」。
3. **改代码**（只改规则层，通常是 `patterns.py` / `compare.py` / `legal_moves.py`）。
4. **跑全量**，必须 296 → 297 全绿；如果红了别的用例，说明新规则和已有规则冲突，停下来问。

### 具体例子：加一条「8 张炸弹最大」

规则：8 张同点数的炸弹是最大炸弹，能压 7 张炸弹和同花顺。现在的实现是靠 `power` 表
（`compare.bomb_power`），**实测值**是：

| 牌型 | `bomb_power` |
|---|---|
| 4 张炸弹 | 40 |
| 同花顺 | 45 |
| 5 张炸弹 | 50 |
| 6 张炸弹 | 60 |
| 7 张炸弹 | 70 |
| 8 张炸弹 | 80 |

第 1 步：在 `tests/test_compare.py` 末尾加（`bomb` 是该文件已有的辅助函数）：

```python
def test_eight_bomb_is_the_top():
    """8 张炸弹最大：压 7 炸、压同花顺、压 4 炸。"""
    from game_engine.compare import bomb_power
    from game_engine.patterns import analyze_cards

    eight = [("S", "3")] * 8            # 用具体牌面也行，纯点数字符串也行
    seven = ["3"] * 7
    flush = [("S", "3"), ("S", "4"), ("S", "5"), ("S", "6"), ("S", "7")]

    assert bomb_power(analyze_cards(eight)) == 80
    assert compare_cards(eight, seven) == 1
    assert compare_cards(eight, flush) == 1
    assert compare_cards(eight, ["A"] * 4) == 1
    # 9 张同点数不是炸弹（上限是 8）
    assert analyze_cards(["3"] * 9) is None
```

第 1 步的「红」长什么样 —— 故意写错方向就会立刻红（下面是**实测**输出，不是设想）：

```text
>>> assert compare_cards(bomb("3", 8), FLUSH) == -1
AssertionError: 写反了：8张炸弹小于同花顺
```

也就是说：只要规则被改坏（比如有人把 `BOMB_MAX` 从 8 改成 7，或者把 `count*10` 改成固定值），
这几行断言就会立刻红，而不是等训练出问题才发现。

第 3 步要改的地方（如果规则真的变了）：

| 改什么 | 在哪 | 连带要改的测试 |
|---|---|---|
| 炸弹张数上限 4~8 | `patterns.BOMB_MIN` / `BOMB_MAX`、`compare.BOMB_MIN` / `BOMB_MAX` | `test_patterns.py::test_valid_patterns` 参数表、`test_hundred_cards_bomb_is_invalid` |
| 炸弹强度公式 | `compare.bomb_power`（`count*10`）与 `FLUSH_STRAIGHT_POWER = 45` | `test_compare.py::test_bomb_ladder`（9 组参数化） |
| 生成器是否允许 9 张 | `legal_moves.MAX_BOMB`（值 8） | `test_legal_moves.py::test_bomb_candidates_present_for_four_of_a_kind` |

第 4 步：

```powershell
$env:PYTHONIOENCODING='utf-8'; & .\.venv\Scripts\python.exe -m pytest tests -q
# 297 passed
```

**做规则改动时的一条硬规矩**：只要 `patterns.py` / `compare.py` / `legal_moves.py` 的行为变了，
`training/data/` 里的旧数据就必须重采或至少重跑一次 `export_dataset` —— 它会用 `RuntimeError`
告诉你候选数量已经对不上了（见 `tests/test_data_pipeline.py::test_export_detects_candidate_drift`）。

---

## 4. 测试环境注意事项（真实坑）

### 坑 1：本机沙箱里系统 TEMP 不可写，**不要用 pytest 的 `tmp_path`**

用 `tmp_path` 的测试在本机会直接失败（`PermissionError`）。现有测试的做法是**在仓库内自建临时目录**，
用完 `shutil.rmtree(..., ignore_errors=True)` 清掉：

```python
# tests/test_data_pipeline.py 的写法
REPO_ROOT = Path(__file__).resolve().parent.parent

@pytest.fixture
def workdir():
    path = REPO_ROOT / ".test_tmp" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
```

`tests/test_cli.py` 同理，用的是仓库内的 `.tmp_eval/run_<uuid>/`。

**新写测试要建文件，请照抄这两种模式**（`.test_tmp/` 或 `.tmp_<用途>/`），不要用 `tmp_path` / `tempfile`。

### 坑 2：PowerShell 控制台可能把中文打成乱码

测试里大量断言中文（`type_label` 返回 `"对子"`、CLI 输出 `"第1名"`），乱码时看起来像断言失败。
开跑前设一次：

```powershell
$env:PYTHONIOENCODING='utf-8'
```

`main.py test` 会自己给子进程设这个环境变量，所以走 `main.py test` 不受影响。

### 坑 3：不要用「跑几局」来测统计逻辑

`tests/test_cli.py` 的原则写在文件头：**最多跑几局，慢的统计逻辑一律用假数据单测**。
`wilson_interval`、`summarize_records`、`summarize_durations` 全部是纯函数，
用 4 条假记录就能测完，不需要真的打 200 局。

### 坑 4：`_ = pytest.raises` 之外的失败都是真失败

`GameTooLongError`、`ValueError`、`RuntimeError` 都是**契约的一部分**（见
[ARCHITECTURE.md](ARCHITECTURE.md) §5）。测试里到处是 `with pytest.raises(...)`，
改代码时如果把异常改成「静默返回」，这些用例会红 —— 这是故意的，别去改测试迁就代码。

---

## 5. 两套校验脚本的定位差异

| | `training/check_dataset.py` | `training/export_dataset.py` |
|---|---|---|
| 查什么 | **结构**：字段齐全、类型对、`selected_index` 不越界、`action_type` 自洽、名次是排列、`team_rank` 对得上 | **语义**：按 seed 重放整局，重算候选、重算手牌、重算标签 |
| 是否导入引擎 | ❌ 完全不导入（只依赖标准库） | ✅ 会真跑 `GameState` / `generate_candidates` / `legal_moves` |
| 速度 | 快：27,794 行实测 **0.28 秒** | 慢（要重放 300 局） |
| 能抓什么 | 文件写坏了、字段被删了、标签越界 | **规则漂移**：引擎改了导致候选数量/手牌/动作不一致 |
| 抓不到什么 | 规则漂移（结构完全合法也可能语义错） | 文件里根本没写进去的东西 |
| 什么时候跑 | 采完立刻跑 | 导出前必跑（`export` 默认 `verify=True`） |

一句话：**`check_dataset` 保证「文件没坏」，`export_dataset` 保证「文件说得对」。**

---

## 6. 性能测试：阈值与实测

现有性能用例都在 `tests/test_wildcards.py` 末尾，阈值都留了 **2 倍余量**防机器抖动：

| 用例 | 阈值 | 实测（2026-11-02，本机） |
|---|---|---|
| `test_wildcard_generation_performance[heavy_wildcard_hand]` | `elapsed < 0.6s`（参考值 300ms） | **6.5 ms**，生成 832 个候选 |
| `test_wildcard_generation_performance[bomb_wildcard_hand]` | `elapsed < 0.6s` | **54.9 ms**，生成 2,766 个候选（含 2 张逢人配的极端炸弹手牌） |
| `test_full_game_with_level_performance` | `elapsed < 2.0s`（参考值 1s） | **108.3 ms**，111 步走完整局（seed=7，打 2，随机策略） |

`test_legal_moves.py::test_candidate_count_is_reasonable` 是一条**数量**护栏：

```python
game = GameState.new_game(seed=42)
assert 1 <= len(generate_candidates(game.hands[0])) <= 800
```

实测 seed=42、无级牌时是 **301** 个候选，离上限还有余量。

其余实测（本次用 `python -c` 跑，取 20 个种子）：

| 场景 | 平均 | 中位 | 最慢 |
|---|---|---|---|
| 27 张手牌生成候选，`level=None` | 1.6 ms | 1.5 ms | 2.4 ms |
| 27 张手牌生成候选，`level="2"`（含逢人配枚举） | 3.0 ms | 2.1 ms | 10.3 ms |
| 含 2 张逢人配的常规手牌 | — | — | 6.5 ms |
| 含 2 张逢人配的极端炸弹手牌 | — | — | 54.9 ms |
| 整局（打 2，随机策略） | — | — | 108.3 ms |

> ⚠️ 口径提醒：以前口头流传的「常规 ~7ms／极端 ~57ms／整局 ~110ms」里，
> **极端与整局与本次实测吻合（54.9 / 108.3）**，但「常规 ~7ms」比本次实测（1.6~3.0 ms）
> 高出一倍多 —— 大概是包含了首次调用的预热或不含 level 的手牌集合不同。
> **需要引用数字时请用本表的实测值，并注明是「27 张手牌、本机、warm」的口径。**

跑性能基准（不是测试，是打印统计）：

```powershell
$env:PYTHONIOENCODING='utf-8'; & .\.venv\Scripts\python.exe main.py bench --games 20
```

---

## 7. 差分 fuzz：抓「看起来对但边界错」

单元测试只能覆盖你**想到**的边界。牌型识别（尤其逢人配能变成任意牌）的真正风险是
「大部分情况对、个别组合错」，这类 bug 用断言列不出来，要用**对拍**（差分测试）。

### 做法

用两条完全独立的路径算同一个问题，比结果：

- **被测实现**：`analyze_cards(cards, level)` —— 剥离万能牌后用骨架枚举补法，快但绕。
- **暴力参考实现**：把所有逢人配**替换成每一张可能的真实牌**（4 花色 × 13 点数 = 52 种），
  对每种替换直接调用**不含万能牌的普通判定** `_analyze_normal`，再按
  `(TYPE_PRIORITY[type], main_value)` 取最大的一种。

两条路径的算法完全不同，只要有一致的输出，就基本排除了「骨架枚举漏了某个窗口」这类错误。

```python
import itertools, random
from game_engine.patterns import analyze_cards, _analyze_normal, TYPE_PRIORITY
from game_engine.ranks import NORMAL_RANKS, SUITS

LEVEL, WILD = "2", ("H", "2")
SUB = [(s, r) for s in SUITS for r in NORMAL_RANKS]      # 万能牌能变成的 52 种牌

def reference(cards):
    wild = [c for c in cards if c == WILD]
    rest = [c for c in cards if c != WILD]
    best = None
    for combo in itertools.product(SUB, repeat=len(wild)):
        info = _analyze_normal(rest + list(combo), LEVEL)
        if info is None:
            continue
        key = (TYPE_PRIORITY[info["type"]], info["main_value"])
        if best is None or key > best[0]:
            best = (key, info)
    return best[1] if best else None

# 随机牌堆里抽 1~2 张逢人配 + 3~8 张真实牌，逐组对拍
```

### 实测结果

- **1,300 组随机牌组合**（每组含 1~2 张逢人配，总张数 1~10），比对
  `(type, main_value)` 二元组：**0 处不一致**。
- **负向对照**（证明这套对拍真的会报错，不是「跑了个寂寞」）：同样的随机组合，
  把被测调用改成 `analyze_cards(cards)`（故意漏掉 `level`），200 组里报出 **85 处不一致**
  （42.5%）。所以「0 处不一致」是有效结论，不是对拍写坏了。

### 现状与建议

- 这套对拍**没有固化成仓库里的脚本**（本次是用 `python -c` 临时跑的）。
  建议以后加 `tests/test_patterns_fuzz.py`，用固定种子跑 200~300 组，
  这样既能在 CI 里跑得动，又能复现任何一次失败。
- 想扩到 `generate_candidates` 的对拍：参考实现用「手牌的全部子集 → `analyze_cards` 过滤」，
  但 27 张手牌的子集是 2^27，不可行；可行的折中是**小样本**（≤8 张手牌）时枚举全部子集。
  这条还没做，属于已知空白。

---

## 8. 一条命令确认「我没搞坏东西」

```powershell
$env:PYTHONIOENCODING='utf-8'
& .\.venv\Scripts\python.exe -m pytest tests -q; `
& .\.venv\Scripts\python.exe -m training.check_dataset; `
& .\.venv\Scripts\python.exe -m training.export_dataset --limit 5
```

三条依次是：单元测试（规则没坏）→ 数据结构（文件没坏）→ 重放语义（数据和引擎仍然对得上）。
`--limit 5` 让重放只跑 5 局，几十秒内出结果；正式数据请去掉 `--limit` 跑全量。
