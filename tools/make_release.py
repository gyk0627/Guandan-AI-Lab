"""把当前构建好的 win64 包发到 GitHub Releases（发版用）。

为什么单独写一个脚本：这台机器上的 git 推送经常因网络抖动失败，而 GitHub 的
Release API 往往还能通（`api.github.com` / `uploads.github.com`）。发版时用它，
就不用开浏览器手动点。

用法（在仓库根目录、推送完代码之后）：

    python -m tools.make_release v1.1
    python -m tools.make_release v1.1 --asset dist/GuandanAI-win64.zip --dry-run

令牌来源，按顺序：
  1. 环境变量 `GITHUB_TOKEN`
  2. Windows 凭据管理器里 git 存的 github.com 账号（`git credential fill`）

要求：`dist/GuandanAI-win64.zip` 已存在（先跑 `python -m tools.package_exe`），
并且要发的 tag 已经推到远端——Release 指向的是远端提交，本地没推就点不进去。
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSET = "dist/GuandanAI-win64.zip"
CHANGELOG = "CHANGELOG.md"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"


def repository() -> str:
    """从 git remote 里读 owner/repo，读不到就用默认值。"""
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", out)
    return match.group(1) if match else "gyk0627/Guandan-AI-Lab"


def token_from_git() -> str:
    """从 git 的凭据存储里取 GitHub token（密码那一行）。"""
    request = "protocol=https\nhost=github.com\n\n"
    try:
        done = subprocess.run(
            ["git", "credential", "fill"],
            cwd=REPO_ROOT,
            input=request,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in done.stdout.splitlines():
        if line.startswith("password="):
            return line[len("password=") :].strip()
    return ""


def github_token() -> str:
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    return token or token_from_git()


def notes_for(version: str) -> str:
    """从 CHANGELOG 里摘出这一版的说明；没有就返回一句占位。"""
    path = REPO_ROOT / CHANGELOG
    if not path.exists():
        return f"v{version}"
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^## v{re.escape(version)}.*?$(.*?)(?=^---$|\Z)", re.M | re.S)
    match = pattern.search(text)
    if not match:
        return f"v{version}"
    body = match.group(1).strip()
    return body or f"v{version}"


def call(method: str, url: str, token: str, payload=None, raw: bytes = None, content_type=None):
    """发一个 JSON 或二进制请求，返回 (状态码, 解析后的值)。"""
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "gandan-make-release",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw is not None:
        data = raw
        headers["Content-Type"] = content_type or "application/octet-stream"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"message": body[:500]}
        return error.code, parsed


def existing_release(repo: str, tag: str, token: str):
    status, data = call("GET", f"{API}/repos/{repo}/releases/tags/{tag}", token)
    return data if status == 200 else None


def ensure_release(repo: str, tag: str, name: str, body: str, token: str):
    """没有就建，有就更新说明（不动已上传的附件）。"""
    payload = {
        "tag_name": tag,
        "name": name,
        "body": body,
        "draft": False,
        "prerelease": False,
    }
    status, data = call("POST", f"{API}/repos/{repo}/releases", token, payload=payload)
    if status in (200, 201):
        return data, "created"
    if status == 422:  # 已存在
        current = existing_release(repo, tag, token)
        if not current:
            raise SystemExit(f"发布 {tag} 创建失败：{data.get('message')}")
        status, updated = call(
            "PATCH", f"{API}/repos/{repo}/releases/{current['id']}", token, payload={"name": name, "body": body}
        )
        return (updated if status == 200 else current), "updated"
    raise SystemExit(f"发布 {tag} 创建失败：{status} {data.get('message')}")


def replace_asset(repo: str, release: dict, path: Path, token: str) -> dict:
    """同名附件先删再传，避免 422 already_exists。"""
    name = path.name
    for asset in release.get("assets", []):
        if asset["name"] == name:
            call("DELETE", f"{API}/repos/{repo}/releases/assets/{asset['id']}", token)
    url = f"{UPLOADS}/repos/{repo}/releases/{release['id']}/assets?name={urllib.parse.quote(name)}"
    status, data = call("POST", url, token, raw=path.read_bytes(), content_type="application/zip")
    if status not in (200, 201):
        raise SystemExit(f"上传附件失败：{status} {data.get('message')}")
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="把构建好的发布包发到 GitHub Releases")
    parser.add_argument("version", help="版本号，例如 1.1（不要带 v）")
    parser.add_argument("--asset", default=DEFAULT_ASSET, help=f"要上传的 zip（默认 {DEFAULT_ASSET}）")
    parser.add_argument("--name", default=None, help="Release 标题（默认 v<版本>）")
    parser.add_argument("--notes", default=None, help="Release 说明；默认从 CHANGELOG 摘")
    parser.add_argument("--dry-run", action="store_true", help="只打印要做什么，不发请求")
    args = parser.parse_args(argv)

    version = args.version.lstrip("v")
    tag = f"v{version}"
    name = args.name or f"v{version}"
    body = args.notes if args.notes is not None else notes_for(version)
    asset = (REPO_ROOT / args.asset).resolve()
    repo = repository()

    print(f"仓库：{repo}")
    print(f"版本：{tag}（{name}）")
    print(f"附件：{asset}（{asset.stat().st_size if asset.exists() else 0} 字节）")
    print(f"说明：{len(body)} 字符")

    if not asset.exists():
        raise SystemExit(f"找不到发布包：{asset}\n先跑 python -m tools.package_exe")
    if args.dry_run:
        print("（dry-run，不发送）")
        return 0

    token = github_token()
    if not token:
        raise SystemExit("拿不到 GitHub 令牌：请设置 GITHUB_TOKEN，或在凭据管理器里登录过 github.com")

    release, action = ensure_release(repo, tag, name, body, token)
    print(f"Release {action}：{release.get('html_url')}")
    asset_info = replace_asset(repo, release, asset, token)
    print(f"附件已上传：{asset_info.get('name')}（{asset_info.get('size')} 字节）")
    print(f"下载地址：{asset_info.get('browser_download_url')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
