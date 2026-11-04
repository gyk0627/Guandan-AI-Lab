"""保证双击脚本不会被 Windows 命令行解析坏。

教训（2026-11-04）：`interface/start_gui.bat` 当初被写成 **LF 换行 + UTF-8 中文**，
cmd.exe 对 LF 换行的批处理会逐字符错位解析，于是双击后报的是
`'?echo' 不是内部或外部命令`、`'C:\\...\\interface\\.."' 不是内部或外部命令` 这种莫名其妙的错。

所以这里钉死三条：
1. `.bat` 里**不允许出现非 ASCII 字节**（中文一律交给 Python 打印）；
2. `.bat` 必须用 **CRLF** 换行；
3. 脚本里引用的 `.venv\\Scripts\\python.exe` 必须真的存在（否则双击也是白报错）。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".venv", ".test_tmp", "__pycache__", ".git", "replay"}


def bat_files():
    return sorted(
        path
        for path in ROOT.rglob("*.bat")
        if not (SKIP_DIRS & set(path.relative_to(ROOT).parts[:-1]))
    )


def test_bat_files_are_pure_ascii():
    offenders = {}
    for path in bat_files():
        raw = path.read_bytes()
        bad = sum(1 for byte in raw if byte > 127)
        if bad:
            offenders[str(path.relative_to(ROOT))] = bad
    assert not offenders, f"这些 .bat 含非 ASCII 字节，cmd 会解析错：{offenders}"


def test_bat_files_use_crlf():
    offenders = []
    for path in bat_files():
        raw = path.read_bytes()
        # 去掉所有 CRLF 后不应再出现孤立的 LF
        if b"\n" in raw.replace(b"\r\n", b""):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"这些 .bat 用了 LF 换行，cmd 会逐字错位：{offenders}"


def test_bat_files_point_at_existing_python():
    expected = ROOT / ".venv" / "Scripts" / "python.exe"
    users = []
    for path in bat_files():
        text = path.read_bytes().decode("ascii", errors="replace")
        if ".venv\\Scripts\\python.exe" in text:
            users.append(str(path.relative_to(ROOT)))
    assert users, "没有任何 .bat 调用虚拟环境的 python，检查是否写错了路径"
    assert expected.is_file(), f"虚拟环境里的 python 不存在：{expected}"


def test_at_least_one_bat_exists():
    assert bat_files(), "仓库里一个 .bat 都没有，是不是被误删了"
