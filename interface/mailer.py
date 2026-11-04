"""把对局记录打包成一封邮件发给作者。

玩家机器上不需要装任何邮件客户端：把 SMTP 账号信息写进 exe 旁边的 `mail.json`，
游戏界面点「发送给作者」就通过 SMTP 直接把记录（zip 附件）发到指定邮箱。

    {
      "to": "author@example.com",
      "host": "smtp.qq.com",
      "port": 465,
      "user": "author@example.com",
      "password": "邮箱授权码（不是登录密码）",
      "ssl": true
    }

两点必须知道：
1. 打包时写进 `mail.json` 的密码**跟着 exe 一起发出去**，拿到包的人能解出来。
   所以务必用「专用邮箱 + 授权码」，不要用个人主邮箱的登录密码。
2. 发不出去不影响玩游戏：调用方负责把 zip 存到「下载」并告诉玩家。

没有 `mail.json` 时完全不联网（默认离线）。
"""

import hashlib
import io
import json
import smtplib
import ssl
import time
import uuid
import zipfile
from email.message import EmailMessage
from pathlib import Path

CONFIG_NAME = "mail.json"
STATE_NAME = "mail_state.json"
DEFAULT_PORT = 465
DEFAULT_TIMEOUT = 40.0


def load_config(path):
    """读邮件配置；缺字段或文件不存在都返回空 dict（视为没配置）。"""
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}

    if not isinstance(data, dict):
        return {}

    to = str(data.get("to") or "").strip()
    host = str(data.get("host") or "").strip()
    user = str(data.get("user") or "").strip()
    password = str(data.get("password") or "").strip()
    if not (to and host and user and password):
        return {}

    try:
        port = int(data.get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_PORT

    return {
        "to": to,
        "from": str(data.get("from") or user),
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "ssl": bool(data.get("ssl", True)),
        "timeout": float(data.get("timeout") or DEFAULT_TIMEOUT),
    }


def device_id(state_path):
    """稳定的匿名设备号，方便作者区分是谁发来的。"""
    state_path = Path(state_path)
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}
    device = str(state.get("device") or "")
    if not device:
        device = uuid.uuid4().hex[:16]
        state["device"] = device
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return device


def build_package(paths, device, note=None):
    """把若干对局记录打成一个 zip（内存里完成，不落临时文件）。"""
    paths = [Path(path) for path in paths if Path(path).exists()]
    if not paths:
        raise FileNotFoundError("没有可发送的对局记录")

    buffer = io.BytesIO()
    files = []
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in paths:
            body = path.read_bytes()
            archive.writestr(path.name, body)
            files.append({"name": path.name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})

        meta = {
            "device": device,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "files": files,
        }
        archive.writestr("info.json", json.dumps(meta, ensure_ascii=False, indent=2))
        archive.writestr(
            "说明.txt",
            "这是一份掼蛋人机对战的对局记录，由游戏里的「发送给作者」按钮自动打包发出。\n"
            "里面是每局操作的原始记录（jsonl），可以逐手复盘，不包含任何个人信息。\n"
            f"设备号：{device}\n",
        )
        if note:
            archive.writestr("备注.txt", note)
    return buffer.getvalue(), files


def send(paths, config, device, note=None):
    """通过 SMTP 把记录发出去；成功返回结果摘要，失败抛异常（由调用方兜底）。"""
    if not config:
        raise RuntimeError("没有配置收件邮箱")
    payload, files = build_package(paths, device, note)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    name = f"guandan_{device}_{stamp}.zip"

    message = EmailMessage()
    message["Subject"] = f"[掼蛋对局] {device} {files[0]['name']}"
    message["From"] = config["from"]
    message["To"] = config["to"]
    message.set_content(
        "你好，这是我在「掼蛋人机对战」里打完的对局记录，已经打包在附件里。\n\n"
        f"设备号：{device}\n"
        f"文件：{', '.join(item['name'] for item in files)}\n"
        "由游戏界面上的「发送给作者」按钮自动发出。\n"
    )
    message.add_attachment(payload, maintype="application", subtype="zip", filename=name)

    timeout = config["timeout"]
    if config["ssl"]:
        client = smtplib.SMTP_SSL(config["host"], config["port"], timeout=timeout, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(config["host"], config["port"], timeout=timeout)

    try:
        if not config["ssl"]:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        client.login(config["user"], config["password"])
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:  # noqa: BLE001 - 收尾失败不该盖住真正的错误
            pass

    return {"to": config["to"], "subject": message["Subject"], "zip_bytes": len(payload), "files": len(files)}
