"""GuanDan Benchmark —— 唯一的性能测试入口。

以前测速脚本散在十几个文件里，命令、口径、报告格式都不一样。现在统一到这里：

    python -m tools.benchmark run --preset quick        # 20 秒，先看机器活着没
    python -m tools.benchmark run --preset standard     # 完整五项，约 3 分钟
    python -m tools.benchmark run --preset full         # 更大样本，给选型用
    python -m tools.benchmark compare A.json B.json     # 两台机器（或两次运行）对比
    python -m tools.benchmark scaling                   # 多进程扩展性
    python -m tools.benchmark roofline                  # 算力/带宽上限
    python -m tools.benchmark dataloading               # 组批是否能并行
    python -m tools.benchmark batch                     # batch 大小消融
    python -m tools.benchmark list                      # 看看有哪些东西

报告统一写成 `evaluation/bench_<预设>_<时间>.json`，字段：

    schema        固定 "gandan-benchmark/2"
    kind          suite / scaling / roofline / dataloading / batch
    preset        quick / standard / full / custom
    created, duration_seconds
    warmup        预热花了多久（口径一致，换机器才可比）
    host          机器与版本信息
    config        这次跑的参数（哪些模块、多少局、多少轮）
    modules       每个模块的原始数字
    resources     采样到的 CPU/GPU/显存/功耗/温度（任务管理器口径）

旧的 v1 报告（`evaluation/benchmark_v1_baseline.json`）没有 schema 字段，`compare` 也认。
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "evaluation"
DEFAULT_BASELINE = OUT_DIR / "benchmark_v1_baseline.json"
SCHEMA = "gandan-benchmark/2"

PRESETS = {
    "quick": {
        "modules": ["cpu", "inference"],
        "games": 20,
        "pipe_games": 4,
        "train_epochs": 1,
        "inference_min_seconds": 0.4,
        "note": "20 秒左右，确认机器活着、GPU 能用",
    },
    "standard": {
        "modules": ["cpu", "inference", "train", "export", "pipeline"],
        "games": 40,
        "pipe_games": 12,
        "train_epochs": 1,
        "inference_min_seconds": 1.0,
        "note": "完整五项，约 3 分钟，日常基准",
    },
    "full": {
        "modules": ["cpu", "inference", "train", "export", "pipeline"],
        "games": 100,
        "pipe_games": 30,
        "train_epochs": 2,
        "inference_min_seconds": 2.0,
        "note": "更大样本，约 10 分钟，给买机器/租机器用",
    },
}

DELEGATES = {
    "scaling": ("tools.scaling_test", "多进程扩展性：1/2/4/8/16 进程各跑一段，看拐点"),
    "roofline": ("tools.roofline_probe", "算力与带宽上限：GEMM TFLOPS、拷贝 GB/s、脊点"),
    "dataloading": ("tools.dataloading_test", "组批并行：同步 vs 预取，判断数据准备是否卡 GPU"),
    "batch": ("tools.batch_ablation", "batch 大小消融：吞吐与验证一致率的取舍"),
}


# ---------------------------------------------------------------- 小工具
def suite_module():
    """延迟导入（它一上来就 import torch，别让 list/compare 也等）。"""
    from tools import benchmark_suite

    return benchmark_suite


def warmup(seconds: float = 0.3) -> dict:
    """统一预热：把 CUDA 上下文、cublas 句柄、显存池先热起来。

    不预热的话第一次前向会慢几倍，两次运行谁"第一个跑"谁吃亏。
    """
    started = time.perf_counter()
    detail = {"cuda": False}
    try:
        import torch

        if torch.cuda.is_available():
            detail["cuda"] = True
            matrix = torch.randn(256, 256, device="cuda")
            torch.cuda.synchronize()
            for _ in range(3):
                matrix @ matrix
            torch.cuda.synchronize()
        else:
            matrix = torch.randn(64, 64)
            matrix @ matrix
    except Exception as exception:  # noqa: BLE001 - 预热失败不该挡住测试
        detail["error"] = f"{type(exception).__name__}: {exception}"

    elapsed = time.perf_counter() - started
    # 太快的机器也保证至少热一小会儿，口径一致
    while time.perf_counter() - started < seconds:
        time.sleep(0.02)

    detail["seconds"] = round(time.perf_counter() - started, 3)
    return detail


def flatten(value, prefix: str = "", out: dict | None = None, depth: int = 0) -> dict:
    """把嵌套报告拍平成 {'modules.cpu.games_per_second': 4.73, ...}。"""
    if out is None:
        out = {}

    if depth > 6:
        return out

    if isinstance(value, dict):
        for key, item in value.items():
            flatten(item, f"{prefix}.{key}" if prefix else str(key), out, depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value[:12]):
            flatten(item, f"{prefix}[{index}]", out, depth + 1)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        out[prefix] = value

    return out


# 单位可能出现在名字中间（ms_per_batch、bc_seconds_per_epoch、
# seconds_per_game_end_to_end），只看结尾后缀会把这类延迟指标错判成"仅参考"
LOWER_IS_BETTER = re.compile(r"(?:^|[._])(seconds|ms|mhz|mb|gb|w|c)(?:_per_|$)")


def direction(path: str) -> int:
    """1 = 越大越好，-1 = 越小越好，0 = 只展示（比如准确率）。"""
    key = path.rsplit(".", 1)[-1]

    # 先按单位 token 判"越小越好"：seconds_per_game_end_to_end 这类名字里
    # 同时有 _per_game，必须先命中单位，否则会被误判成"越大越好"
    if LOWER_IS_BETTER.search(key):
        return -1
    if key.endswith(("_per_second", "_per_game")):
        return 1
    if "acc" in key or "auc" in key:
        return 0
    return 0


def load_report(path) -> dict:
    """读 v1 或 v2 报告，统一成 {'modules': ..., 'resources': ..., 'host': ..., 'created': ...}。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    normalized = {
        "schema": data.get("schema", "gandan-benchmark/1"),
        "kind": data.get("kind", "suite"),
        "preset": data.get("preset"),
        "created": data.get("created") or data.get("started"),
        "host": data.get("host") or {},
        "modules": data.get("modules") or {},
        "resources": data.get("resources") or {},
        "metrics": data.get("metrics") or {},
    }
    return normalized


def compare_reports(current: dict, baseline: dict) -> list:
    """逐项对比，只报两边都有的数字。"""
    current_flat = flatten({**current.get("modules", {}), **current.get("metrics", {})})
    baseline_flat = flatten({**baseline.get("modules", {}), **baseline.get("metrics", {})})
    rows = []

    for path in sorted(set(current_flat) & set(baseline_flat)):
        # 测多久、跑了多少量都不算性能指标：模块跑了几秒、样本/局/决策/推理个数
        # 都是测量过程，不是结果，放进来会把"机器快慢"和"跑了多少"混为一谈
        if path.rsplit(".", 1)[-1] in (
            "module_seconds", "seconds", "samples", "games", "decisions", "inferences",
        ):
            continue
        old, new = baseline_flat[path], current_flat[path]
        if not old or not new or old == new:
            continue
        ratio = new / old
        better = direction(path)
        if better == 1:
            verdict = "更快" if ratio >= 1.10 else ("变慢" if ratio <= 0.90 else "持平")
            multiple = ratio
        elif better == -1:
            verdict = "更快" if ratio <= 0.90 else ("变慢" if ratio >= 1.10 else "持平")
            multiple = 1 / ratio
        else:
            verdict, multiple = "仅参考", 1.0
        rows.append({
            "metric": path,
            "baseline": old,
            "current": new,
            "multiple": round(multiple, 3),
            "verdict": verdict,
        })

    rows.sort(key=lambda row: (row["verdict"] == "仅参考", -abs(row["multiple"] - 1)))
    return rows


def print_compare(rows, baseline_name: str, current_name: str) -> None:
    print("=" * 92)
    print(f"对比：{current_name}  vs  {baseline_name}")
    print("=" * 92)
    print(f"{'指标':<52}{'基线':>12}{'当前':>12}{'倍数':>9}  {'判定'}")
    print("-" * 92)
    shown = 0
    for row in rows:
        if row["verdict"] == "仅参考":
            continue
        print(f"{row['metric'][:50]:<52}{row['baseline']:>12.3f}{row['current']:>12.3f}"
              f"{row['multiple']:>8.2f}x  {row['verdict']}")
        shown += 1
    if not shown:
        print("（没有可比较的差异：两边数字相同，或模块/字段不同）")
    print("=" * 92)
    print("说明：倍数 > 1 表示当前更快；只有 ≥10% 的变化才判定为更快/变慢，")
    print("      机器温度、后台程序、跑的顺序都会带来这么大波动，别把 5% 当结论。")


# ---------------------------------------------------------------- 子命令
def cmd_run(args) -> int:
    suite = suite_module()
    preset = args.preset

    if preset == "custom":
        if not args.modules:
            print("用了 --preset custom 就必须给 --modules，例如 --modules cpu,inference", file=sys.stderr)
            return 2
        config = {
            "modules": [part.strip() for part in args.modules.split(",") if part.strip()],
            "games": args.games or 40,
            "pipe_games": args.pipe_games or 12,
            "train_epochs": args.train_epochs or 1,
            "inference_min_seconds": 1.0,
        }
    else:
        config = dict(PRESETS[preset])
        config.pop("note", None)
        if args.modules:
            config["modules"] = [part.strip() for part in args.modules.split(",") if part.strip()]
    if args.games:
        config["games"] = args.games
    if args.pipe_games:
        config["pipe_games"] = args.pipe_games
    if args.train_epochs:
        config["train_epochs"] = args.train_epochs

    started = time.perf_counter()
    print("=" * 78)
    print("GuanDan Benchmark")
    print("=" * 78)
    print(f"预设：{preset}   模块：{', '.join(config['modules'])}")

    warm = warmup(args.warmup_seconds)
    print(f"预热：{warm['seconds']:.2f} 秒（CUDA {'可用' if warm['cuda'] else '不可用'}）")

    data_path = suite.latest_npz()
    result = {
        "schema": SCHEMA,
        "kind": "suite",
        "preset": preset,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "warmup": warm,
        "host": suite.host_info(),
        "config": config,
        "modules": {},
    }

    with suite.Sampler() as sampler, suite.EngineSampler(suite.TMP / "engine.csv") as engine_sampler:
        for name in config["modules"]:
            print(f"  [{name}] 运行中…", end="", flush=True)
            module_started = time.perf_counter()
            try:
                if name == "cpu":
                    data = suite.module_cpu(games=config["games"])
                elif name == "inference":
                    data = suite.module_inference(min_seconds=config["inference_min_seconds"])
                elif name == "train":
                    data = suite.module_train(epochs=config["train_epochs"], data_path=data_path)
                elif name == "export":
                    data = suite.module_export(games=config["games"])
                elif name == "pipeline":
                    data = suite.module_pipeline(games=config["pipe_games"])
                else:
                    data = {"error": f"未知模块 {name}"}
            except Exception as exception:  # noqa: BLE001 - 单模块失败不影响整体
                data = {"error": f"{type(exception).__name__}: {exception}"}
            data["module_seconds"] = round(time.perf_counter() - module_started, 2)
            result["modules"][name] = data
            print(f"\r  [{name}] 完成（{data['module_seconds']} 秒）")

    result["resources"] = getattr(sampler, "summary", {})
    result["resources"]["engine"] = getattr(engine_sampler, "summary", {})
    result["duration_seconds"] = round(time.perf_counter() - started, 2)

    suite.print_report(result)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out) if args.out else OUT_DIR / f"bench_{preset}_{stamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告：{out_path}")

    baseline = args.compare
    if baseline == "auto":
        baseline = DEFAULT_BASELINE if DEFAULT_BASELINE.exists() else None
    if baseline:
        try:
            baseline_report = load_report(baseline)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exception:
            # 报告已经写好了，基线读不了只影响对比，不该把整次运行搞崩
            print(f"基线报告读不了，跳过对比：{type(exception).__name__}: {exception}",
                  file=sys.stderr)
        else:
            rows = compare_reports({"modules": result["modules"], "metrics": {}}, baseline_report)
            print_compare(rows, Path(baseline).name, out_path.name)

    return 0


def cmd_compare(args) -> int:
    current_path = Path(args.current)
    baseline_path = Path(args.baseline)

    for path in (current_path, baseline_path):
        if not path.exists():
            print(f"找不到报告文件：{path}", file=sys.stderr)
            print("用法：python -m tools.benchmark compare <当前报告.json> <基线报告.json>",
                  file=sys.stderr)
            return 2
        if path.is_dir():
            print(f"这是目录，不是报告文件：{path}", file=sys.stderr)
            return 2

    try:
        current = load_report(current_path)
        baseline = load_report(baseline_path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exception:
        print(f"报告不是合法的 JSON（{type(exception).__name__}: {exception}）", file=sys.stderr)
        return 2

    # 同一份文件（或两份内容完全相同的报告）没有什么可比的，给个明确提示而不是空表
    if current_path.resolve() == baseline_path.resolve() or current == baseline:
        print("=" * 92)
        print(f"两份报告内容相同：{current_path.name}")
        print("=" * 92)
        print("没有可比较的差异，判定全部为持平（如果要比，给两份不同的报告）。")
        return 0

    rows = compare_reports(current, baseline)
    print_compare(rows, Path(args.baseline).name, Path(args.current).name)
    if args.out:
        Path(args.out).write_text(
            json.dumps({"schema": SCHEMA, "kind": "compare", "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"对比结果：{args.out}")
    return 0


def cmd_delegate(command: str, rest: list) -> int:
    module_name, description = DELEGATES[command]
    print("=" * 78)
    print(f"{command}：{description}")
    print("=" * 78)
    module = __import__(module_name, fromlist=["main"])
    return module.main(rest) or 0


def cmd_list(args) -> int:
    print("预设：")
    for name, config in PRESETS.items():
        print(f"  {name:<10}{config['note']}（模块：{', '.join(config['modules'])}；"
              f"{config['games']} 局）")
    print(f"  {'custom':<10}自选模块（--preset custom 时必须再给 --modules，否则退出码 2）")
    print()
    print("子命令：")
    print(f"  {'run':<12}跑综合测试（--preset quick|standard|full，或 --modules 自定义）")
    print(f"  {'compare':<12}两份报告逐项对比（认 v1 / v2 两种格式）")
    for name, (_, description) in DELEGATES.items():
        print(f"  {name:<12}{description}")
    print(f"  {'list':<12}列出预设与子命令（就是本命令）")
    print()
    print(f"报告目录：{OUT_DIR}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # 委托子命令：参数原样交给各自脚本，这样 `scaling --help`、`batch --lr-scale`
    # 都按脚本自己的 argparse 解释；否则帮助会被本入口的 subparser 吃掉。
    if argv and argv[0] in DELEGATES:
        return cmd_delegate(argv[0], argv[1:])

    parser = argparse.ArgumentParser(
        description="GuanDan Benchmark：统一的性能测试入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python -m tools.benchmark run --preset quick --compare auto",
    )
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="跑综合测试")
    run_parser.add_argument("--preset", default="standard", choices=[*PRESETS, "custom"])
    run_parser.add_argument("--modules", default=None, help="覆盖预设，例如 cpu,inference")
    run_parser.add_argument("--games", type=int, default=None)
    run_parser.add_argument("--pipe-games", dest="pipe_games", type=int, default=None)
    run_parser.add_argument("--train-epochs", dest="train_epochs", type=int, default=None)
    run_parser.add_argument("--warmup-seconds", dest="warmup_seconds", type=float, default=0.3)
    run_parser.add_argument("--compare", default=None, help="给一个基线 JSON，或 auto")
    run_parser.add_argument("--out", default=None)

    compare_parser = sub.add_parser("compare", help="两份报告对比")
    compare_parser.add_argument("current", help="这次的报告")
    compare_parser.add_argument("baseline", help="基线报告")
    compare_parser.add_argument("--out", default=None)

    sub.add_parser("list", help="列出预设与子命令")

    for name in DELEGATES:
        delegate_parser = sub.add_parser(name, help=DELEGATES[name][1])
        delegate_parser.add_argument("rest", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    if args.command == "run":
        return cmd_run(args)
    if args.command == "compare":
        return cmd_compare(args)
    if args.command == "list":
        return cmd_list(args)
    return cmd_delegate(args.command, args.rest)


if __name__ == "__main__":
    raise SystemExit(main())
