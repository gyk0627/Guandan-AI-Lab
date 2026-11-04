"""把网页版人机对战打包成 Windows 双击即用的 exe。

用法（在仓库根目录）：
    python -m tools.build_exe
    python -m tools.build_exe --name 掼蛋 --clean

产物：dist/GuandanAI.exe（单文件，约 10–20 MB）。
打包版用启发式策略，不需要 Python，也不需要 PyTorch；对局记录写到 exe 旁边的 replay/。
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "interface" / "app.py"
DATA_FILE = REPO_ROOT / "interface" / "index.html"
ICON_FILE = REPO_ROOT / "interface" / "guandan.ico"
HOST_DIR = REPO_ROOT / "interface" / "window_host"

# 内嵌窗口外壳：一个 C# 小程序 + WebView2 的托管 DLL + 加载器。
# 少了它们就只能退回「Edge 应用模式」，在管理员权限的机器上会白屏。
HOST_FILES = (
    "GuandanWindow.exe",
    "Microsoft.Web.WebView2.Core.dll",
    "Microsoft.Web.WebView2.WinForms.dll",
    "WebView2Loader.dll",
)

# 这些包很大，而且打包版用不到（启发式策略是纯 Python）。
EXCLUDES = [
    "torch",
    "torchvision",
    "torchaudio",
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
    "PIL",
    "IPython",
    "pytest",
    "tkinter",
    "sqlite3",
    "pydoc",
]


def build(name: str, clean: bool, one_file: bool, keep_work: bool) -> Path:
    if not ENTRY.exists():
        raise SystemExit(f"找不到入口文件：{ENTRY}")
    if not DATA_FILE.exists():
        raise SystemExit(f"找不到网页文件：{DATA_FILE}")

    dist_dir = REPO_ROOT / "dist"
    work_dir = REPO_ROOT / ".test_tmp" / "pyi_build"
    spec_dir = REPO_ROOT / ".test_tmp" / "pyi_spec"
    for directory in (work_dir, spec_dir):
        directory.mkdir(parents=True, exist_ok=True)

    separator = ";" if sys.platform.startswith("win") else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--log-level",
        "WARN",
        "--name",
        name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        "--paths",
        str(REPO_ROOT),
        "--add-data",
        f"{DATA_FILE}{separator}interface",
        "--onefile" if one_file else "--onedir",
        "--console",
    ]
    if clean:
        command.append("--clean")
    if ICON_FILE.exists():
        command.extend(["--icon", str(ICON_FILE)])
    for filename in HOST_FILES:
        path = HOST_DIR / filename
        if not path.exists():
            raise SystemExit(f"缺少窗口外壳文件：{path}（先跑 python -m tools.build_window_host）")
        command.extend(["--add-binary", f"{path}{separator}interface/window_host"])
    for module in EXCLUDES:
        command.extend(["--exclude-module", module])
    command.append(str(ENTRY))

    print("开始打包，大约需要 1–3 分钟……")
    print("命令：", " ".join(command[-6:]), "…")
    started = time.time()
    result = subprocess.run(command, cwd=str(REPO_ROOT))
    if result.returncode != 0:
        raise SystemExit(f"打包失败，退出码 {result.returncode}")

    if one_file:
        target = dist_dir / f"{name}.exe"
    else:
        target = dist_dir / name / f"{name}.exe"
    if not target.exists():
        raise SystemExit(f"打包结束但没找到产物：{target}")

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"完成，用时 {time.time() - started:.1f} 秒")
    print(f"产物：{target}  ({size_mb:.1f} MB)")
    if not keep_work:
        shutil.rmtree(work_dir, ignore_errors=True)
        shutil.rmtree(spec_dir, ignore_errors=True)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="打包掼蛋人机对战 exe")
    parser.add_argument("--name", default="GuandanAI", help="exe 文件名（不含扩展名）")
    parser.add_argument("--clean", action="store_true", help="清掉上次的中间文件再打包")
    parser.add_argument("--onedir", action="store_true", help="打包成文件夹（启动更快，体积更分散）")
    parser.add_argument("--keep-work", action="store_true", help="保留中间文件，方便排查")
    args = parser.parse_args(argv)

    target = build(
        name=args.name,
        clean=args.clean,
        one_file=not args.onedir,
        keep_work=args.keep_work,
    )
    print()
    print("双击就能玩：", target)
    print("第一次启动 Windows 可能弹安全提示，选“仍要运行”即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
