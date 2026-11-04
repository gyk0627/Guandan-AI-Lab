"""重新编译内嵌窗口外壳（GuandanWindow.exe）。

平时不需要跑：编译好的 exe 和三个 DLL 已经放在 interface/window_host/ 里。
只有改了 GuandanWindow.cs 或者要升级 WebView2 SDK 时才需要。

做的事：
  1. 从 NuGet 下 Microsoft.Web.WebView2（版本见 SDK_VERSION）
  2. 取出 net462 的两个托管 DLL 和 x64 的 WebView2Loader.dll
  3. 用系统自带的 csc.exe 编译 GuandanWindow.cs

用法：
    python -m tools.build_window_host
    python -m tools.build_window_host --sdk 1.0.4314.35
"""

import argparse
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_DIR = REPO_ROOT / "interface" / "window_host"
SDK_VERSION = "1.0.4314.35"
WORK_DIR = REPO_ROOT / ".test_tmp" / "webview2"

CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")

FILES = {
    "lib/net462/Microsoft.Web.WebView2.Core.dll": "Microsoft.Web.WebView2.Core.dll",
    "lib/net462/Microsoft.Web.WebView2.WinForms.dll": "Microsoft.Web.WebView2.WinForms.dll",
    "runtimes/win-x64/native/WebView2Loader.dll": "WebView2Loader.dll",
}


def download_sdk(version: str) -> Path:
    archive = WORK_DIR / f"webview2-{version}.zip"
    if archive.exists():
        return archive
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    url = (
        "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/"
        f"{version}/microsoft.web.webview2.{version}.nupkg"
    )
    print(f"下载 WebView2 SDK {version} ……")
    with urllib.request.urlopen(url, timeout=120) as response:
        blob = response.read()
    archive.write_bytes(blob)
    return archive


def extract(archive: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(archive.read_bytes())) as package:
        for source, name in FILES.items():
            with package.open(source) as handle:
                (HOST_DIR / name).write_bytes(handle.read())
            print(f"  取出 {name}")


def compile_host() -> Path:
    if not CSC.exists():
        raise SystemExit(f"找不到 C# 编译器：{CSC}")
    output = HOST_DIR / "GuandanWindow.exe"
    command = [
        str(CSC),
        "/nologo",
        "/target:winexe",
        "/platform:x64",
        "/optimize+",
        f"/out:{output}",
        "/r:Microsoft.Web.WebView2.Core.dll",
        "/r:Microsoft.Web.WebView2.WinForms.dll",
        "/r:System.Windows.Forms.dll",
        "/r:System.Drawing.dll",
        "GuandanWindow.cs",
    ]
    print("编译窗口外壳 ……")
    result = subprocess.run(command, cwd=str(HOST_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(result.stdout + result.stderr)
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="重新编译内嵌窗口外壳")
    parser.add_argument("--sdk", default=SDK_VERSION, help=f"WebView2 SDK 版本（默认 {SDK_VERSION}）")
    parser.add_argument("--keep", action="store_true", help="保留下载的 nupkg")
    args = parser.parse_args(argv)

    HOST_DIR.mkdir(parents=True, exist_ok=True)
    archive = download_sdk(args.sdk)
    extract(archive)
    output = compile_host()
    if not args.keep:
        shutil.rmtree(WORK_DIR, ignore_errors=True)

    print(f"完成：{output} ({output.stat().st_size} 字节)")
    missing = [name for name in FILES.values() if not (HOST_DIR / name).exists()]
    if missing:
        raise SystemExit(f"缺少文件：{missing}")
    print("下一步：python -m tools.package_exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
