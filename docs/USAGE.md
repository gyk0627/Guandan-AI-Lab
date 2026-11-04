# 使用手册（USAGE）

本页是**可直接复制**的命令清单。规则本身见 [RULES.md](RULES.md)，实验编号与数字见 [EXPERIMENTS.md](EXPERIMENTS.md)。

Windows 环境约定：

- 一律用仓库自带的虚拟环境：`& .\.venv\Scripts\python.exe -X utf8 -m ...`，不要用 PATH 里的 `python`；
- 中文输出乱码时先设 `$env:PYTHONIOENCODING='utf-8'`；
- 所有命令都在仓库根目录（`GuanDan-AI-Lab\`）执行。

---

## 1. 环境

| 依赖 | 版本 | 是否必需 |
|---|---|---|
| Python | 3.13 | 必需 |
| numpy / pytest | 见 `requirements.txt` | 必需 |
| torch（CUDA 版） | 2.11.0+cu128 | 训练与神经网络对战才需要 |

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 可选：CUDA 版 torch（Blackwell 架构需要 cu128 及以上）
& .\.venv\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cu128 torch
```

不装 torch 时，依赖 torch 的测试会自动跳过，规则引擎、数据管线、对战界面照常可用。

## 2. 跑测试

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m pytest tests -q
```

约 30 秒、404 个用例。`pytest.ini` 禁用了缓存，所以 `--cache-clear` 这类参数会被拒绝。

## 3. 打一局

```powershell
# 启发式 AI 自我对弈，打印每一步
& .\.venv\Scripts\python.exe -X utf8 -m main play --seed 42

# 固定种子性能基准
& .\.venv\Scripts\python.exe -X utf8 -m main bench --games 20
```

## 4. 网页人机对战

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m interface.web_server --level 2
```

浏览器打开 `http://127.0.0.1:8765/`，你坐 0 号位（A 队）。

| 参数 | 说明 |
|---|---|
| `--level 2` | 本局打几（2 / 7 / A …） |
| `--port 8899` | 换端口 |
| `--no-neural` | 强制用启发式（不加载模型） |
| `--model models\xxx.pt` | 指定模型；省略时取 `models/` 下最新 |
| `--no-browser` | 不自动开浏览器 |

也可以双击 `interface\start_gui.bat`。每局都会写到 `replay/human_<时间戳>_<种子>.jsonl`。

### 免安装 exe

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m tools.package_exe
```

产物：`dist\GuandanAI\`（程序文件夹）、`dist\GuandanAI-win64.zip`（发布包，约 9.3 MB）。
exe 内是启发式 AI；神经网络策略需要 PyTorch，不打包。

**打包时决定「朋友怎么把记录给你」**

- 配好回传地址（推荐，朋友零操作）：

  ```powershell
  & .\.venv\Scripts\python.exe -X utf8 -m tools.package_exe `
      --upload-url http://你的电脑IP:8790/upload --token guandan-local
  ```

  发布包里会直接带 `upload.json`，朋友解压双击就能玩，每局打完自动上传，不用改任何文件。
  `--token` 省略时默认 `guandan-local`，要和接收端一致；地址必须以 `http://` 或 `https://` 开头。

- 不配地址（离线版）：

  ```powershell
  & .\.venv\Scripts\python.exe -X utf8 -m tools.package_exe
  ```

  包里只有 `upload.json.example`。朋友打完（打一半也行）点窗口右上角「导出对局」，
  最新一局的 `human_*.jsonl` 会存到他的「下载」文件夹，让他把这个文件发给你。

**接收方先开接收端**：双击仓库根目录的 `start_collector.bat`，它等价于：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m tools.collect_server --dir collected --port 8790 --token guandan-local
```

窗口保持开着（可以最小化，但别关），收到的文件存到 `collected\`。

打包版启动后会打开一个**内嵌 WebView2 的原生窗口**（`interface\window_host\GuandanWindow.exe`，
一个几十 KB 的 C# 外壳 + 三个 DLL，一起打进包里）。它不经过浏览器的启动策略，
所以即便 Windows 账户是管理员权限也不会白屏；关掉窗口进程就退出。
缺 WebView2 运行时时自动退回 Edge 应用模式，再不行退回默认浏览器。
参数：`--level`、`--port`、`--browser`（强制浏览器）、`--no-upload`。

改窗口外壳（一般不需要）：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m tools.build_window_host   # 从 NuGet 取 SDK 并重新编译
& .\.venv\Scripts\python.exe -X utf8 -m tools.package_exe          # 重新打发布包
```

`GuandanWindow.exe` 支持第三个参数传调试端口（`--remote-debugging-port`），
自动化测试用它拿到窗口里的页面；正常启动时传 `0` 表示不开。

### 收集别人的对局记录

按「朋友要不要动手」分两种方式：

**方式一：自动回传（推荐，朋友零操作）**

1. 接收方双击 `start_collector.bat`（端口 8790、口令 `guandan-local`、文件存 `collected\`），窗口别关。
2. 打包时带 `--upload-url http://接收端IP:8790/upload`，`--token` 与接收端一致
   （`start_collector.bat` 用的是 `guandan-local`）。
3. 把 zip 发给朋友：解压、双击、每局自动上传。断网会先存本地，下次启动按 sha256 去重补传；
   状态在 `upload_state.json`。

**方式二：朋友点「导出对局」发文件**

1. 打包时不带 `--upload-url`，发布包里只有 `upload.json.example`。
2. 朋友打完（打一半也行）点右上角「导出对局」，文件存到「下载」文件夹（文件名以 `human_` 开头）。
3. 朋友把文件发给你，直接放进 `collected\` 或另存即可。

接收端细节：

- 收到的文件按 `<sha16>_<原名>.jsonl` 存盘，并追加 `index.jsonl`；重复上传会被挡掉，
  `GET /api/stats` 能看已收多少局。
- 不想重新打包时，也可以手动在 exe 所在文件夹放 `upload.json`（内容格式）：

  ```json
  { "url": "http://接收端地址:8790/upload", "token": "同一串口令" }
  ```

  没有 `upload.json` 就完全离线。
- 公网部署时记得把 `--token` 换成自己的口令，并放到 Nginx / HTTPS 后面。

网页版同样支持「导出对局」：`GET /api/export` 把当前最新一局 `human_*.jsonl` 当附件返回
（优先正在打的这一局，打一半也能导）；还没有记录时返回 404「还没有可导出的对局记录」。

## 5. 数据管线

采集 → 结构校验 → 导出（重放校验）→ 合并。

```powershell
# 采集 300 局（约 1 分钟）
& .\.venv\Scripts\python.exe -X utf8 -m training.collect_data --games 300 --seed-start 1000

# 结构校验（不跑引擎，秒级）
& .\.venv\Scripts\python.exe -X utf8 -m training.check_dataset

# 单进程导出（会重放整局并逐条校验）
& .\.venv\Scripts\python.exe -X utf8 -m training.export_dataset

# 多进程并行导出（5000 局实测 6.2×）
& .\.venv\Scripts\python.exe -X utf8 -m tools.parallel_export --workers 8

# 合并多份 npz
& .\.venv\Scripts\python.exe -X utf8 -m training.merge_datasets --out training\data\merged.npz a.npz b.npz
```

采集参数：`--level-mode cycle|fixed|none`（级牌轮转 / 固定 / 无）、`--policy heuristic|random`、`--out`。

> 导出会逐条重算候选与标签，一旦与采集记录不一致就报错退出——这是刻意的，防止数据静默漂移。

## 6. 训练

### 行为克隆

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m training.train_bc `
    --data training\data\games_20261103_v3.npz `
    --epochs 40 --batch-size 64 --min-candidates 2
```

| 参数 | 说明 |
|---|---|
| `--loss ce\|group\|mixed` | 默认 `ce`（实测最好）；另两种是实验中的负结果 |
| `--min-candidates 2` | 剔除「只有一个候选」的样本（恒对，会抬高一致率） |
| `--prefetch 2` | 后台组批线程，实测约 +10% 吞吐 |
| `--monitor 路径` | 写进度快照，配合进度网页 |
| `--out 路径` | 模型输出；省略写到 `models/` |

### 训练进度网页

```powershell
# 边训边看（自动开浏览器）
& .\.venv\Scripts\python.exe -X utf8 -m tools.train_with_monitor --epochs 40

# 训练在别的窗口跑，只看进度
& .\.venv\Scripts\python.exe -X utf8 -m tools.train_monitor --open
```

也可以双击 `run_train_gui.bat`。原理：训练进程写 JSON 快照，网页每 0.8 秒读一次。

## 7. 评估

```powershell
# 神经网络 vs 随机（400 局，务必显式给 --level）
& .\.venv\Scripts\python.exe -X utf8 -m tools.eval_policies --a neural --b random `
    --games 200 --level 2 --checkpoint models\bc_games_20261103_v3.pt

# 神经网络 vs 启发式
& .\.venv\Scripts\python.exe -X utf8 -m tools.eval_policies --a neural --b heuristic `
    --games 200 --level 2 --checkpoint models\bc_games_20261103_v3.pt
```

`--games N` 是**组数**，每组两局（同种子换座位），所以 200 组 = 400 局。输出含 Wilson 置信区间。

## 8. 性能基准

```powershell
# 三档预设
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset quick      # 约 20 秒
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset standard   # 约 3 分钟
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark run --preset full       # 约 10 分钟

# 与历史基线对比（省略第二个文件时用仓库内 v1 基线）
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark compare evaluation\bench_quick_20261104_200736.json

# 列出预设、子命令与报告目录
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark list
```

**对比口径**：比值 ≥1.10 记「更快」、≤0.90 记「变慢」，其余记「持平」；纯测量耗时（`module_seconds` 等）不参与比较。
换机器请整份重跑，不要跨机器比绝对值。

委托子命令（延迟加载，参数原样透传）：

```powershell
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark scaling --help      # CPU 并行扩展性
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark roofline --help     # 算力/带宽 roofline
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark dataloading --help  # 组批并行
& .\.venv\Scripts\python.exe -X utf8 -m tools.benchmark batch --help        # batch 大小消融
```

## 9. 常见报错

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'numpy'` | 用了 PATH 里的 python | 用 `& .\.venv\Scripts\python.exe ...` |
| `ModuleNotFoundError: No module named 'game_engine'` | 不在仓库根目录 | 先 `cd` 到 `GuanDan-AI-Lab` |
| 中文输出乱码 | 控制台编码 | `$env:PYTHONIOENCODING='utf-8'` |
| 源码中文变成 `娌℃湁` 这类乱码 | 被 PowerShell 的 `Get-Content\|Set-Content` 按 ANSI 改写 | 用编辑器重写该文件，不要用 shell 改源码 |
| `pytest: error: unrecognized arguments: --cache-clear` | 项目刻意禁用缓存 | 去掉参数 |
| `ModuleNotFoundError: No module named 'torch'` | 没装 torch | 按第 1 节装，或只跑不依赖 torch 的部分 |
| `torch.cuda.is_available()` 为 `False` | 装成 CPU 版 | 用 cu128 索引重装 |
| CUDA out of memory | 候选宽度大 + batch 大 | 降 `--batch-size`，或按候选数分桶 |
| `FileNotFoundError: ... 请先采集` | 还没有数据 | 先跑 `training.collect_data` |
| 评估结果明显偏低 | 用了 `--level none`（训练分布外）或错了 checkpoint | 加 `--level 2` 并显式指定模型 |
| `RuntimeError: 种子 xxx 的对局超过最大行动次数` | 回合逻辑或策略死循环 | 用 `main play --seed xxx --no-log` 复现，这是真 bug |

## 10. 数据文件

| 路径 | 内容 |
|---|---|
| `training/data/games_*.jsonl` | 采集的原始对局（每行一条决策） |
| `training/data/*.npz` | 导出后的训练集（状态、候选、标签） |
| `replay/*.jsonl` | 对局日志（人机对战自动写入） |
| `evaluation/bench_*.json` | 基准报告（v2 格式） |

字段定义见 [DATA_FORMAT.md](DATA_FORMAT.md)。
