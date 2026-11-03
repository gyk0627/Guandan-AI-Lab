# Git 使用说明（远程仓库与数据管理）

> 结论：**建议要远程仓库**（备份 + 云服务器 clone + 论文可复现性），但**必须是私有仓库**，
> 而且**只推 `release` 分支**。

---

## 一、为什么需要远程仓库

1. **备份**：本地只有一份，硬盘坏了就全没了。
2. **云服务器要用**：租到机器后要 `git clone` 代码上去跑。
3. **论文可复现性**：审稿人/合作者能拿到同一份代码。

---

## 二、当前仓库结构（重要）

```
GuanDan-AI-Lab/
├── .git/
├── main          ← 工作分支（干净历史，跟踪 origin/main，**日常就在这里提交和推送**）
└── main-archive  ← 旧开发档案（含 830MB 数据文件历史，**只留本地，不要推**）
```

为什么分两个分支：

- 开发过程中曾把 `training/data_selfplay/*.jsonl`（最大 615MB）提交进历史；
- GitHub / Gitee 的**单文件上限是 100MB**，直接推会被拒；
- 沙箱里 `git filter-branch` 无法运行（依赖 shell 管道），
  所以采用"孤儿分支"方案：`release` 只包含当前干净文件树，**不继承旧历史**。

---

## 三、创建远程仓库并推送

### 1. 在平台上新建**私有**仓库

**已创建并推送**：https://github.com/gyk0627/Guandan-AI-Lab （私有）
- 首次推送：`git push -u origin release:main`（已完成）
- `release` 分支已跟踪 `origin/main`

以后要换/加远程（例如国内用 Gitee 做镜像）：
- Gitee：https://gitee.com → 新建仓库 → **私有**
- GitHub：https://github.com → New repository → **Private**
- 不要勾选"初始化 README/.gitignore"，保持空仓库

### 2. 本地推送

```powershell
$git = 'D:\software\Git\cmd\git.exe'
cd C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab

# 远程已配置好；分支名已统一为 main，直接推即可
git push
```

之后日常提交：

```powershell
& $git add -A
& $git commit -m "说明"
& $git push
```

> 注意：当前工作分支是 `main`（干净历史）。**不要推 `main-archive`**——它带着 830MB 的历史。

---

## 四、数据怎么上云服务器（不进 Git）

代码进 Git，**数据不进**。1000 万局约 650GB，Git 装不下也不需要。

两种做法：

**A. 从本机传（适合已有数据的场景）**

```powershell
# 本机
scp training/data_selfplay/v3_selfplay_10k.jsonl user@<服务器>:~/GuanDan-AI-Lab/training/data_selfplay/
```

**B. 在服务器上重新生成（推荐，数据本来就是脚本产出的）**

```bash
cd GuanDan-AI-Lab && source .venv/bin/activate
python -m training.self_play --games 10000 --workers 32 --out training/data_selfplay/run1.jsonl
python -m training.export_dataset training/data_selfplay/run1.jsonl
```

服务器核多，重新生成往往比传 615MB 更快，而且能验证管线在 Linux 上正常。

---

## 五、安全提醒

- **必须私有**：仓库里有 5 个文档含本机绝对路径（`C:\Users\gyk\...`），
  以及尚未发表的实验数据与论文大纲。
- 仓库里的 `issn1000-1239.202220697.pdf` 是公开论文，无版权问题。
- 不要在仓库里放 API key / token（目前没有）。

---

## 六、如果以后想瘦身本地 main

```powershell
# 确认有备份后再删（备份已在工作区外：_gandan_old_history.bundle）
git branch -D main-archive
git gc --prune=now
```

删掉后本地就只剩 `release` 分支（3.46MB），历史会丢失但代码完整。
旧历史已打包在 `..\_gandan_old_history.bundle`（182MB）。

---

## 七、当前版本信息

| 项 | 值 |
|---|---|
| 用于推送的分支 | `main`（跟踪 origin/main） |
| 该分支体积 | 196 对象 / 3.46 MB（未压缩） |
| 被跟踪文件 | 180 个（代码、文档、PDF、小 meta） |
| 被忽略 | `training/data*`、`training/data_selfplay/*`、`models/*.pt`、`replay/*.jsonl`、`.venv`、`.test_tmp` |
| 测试 | `pytest tests -q` → 370 passed |
