"""「发送给作者」这条链的单元测试。

不联网：SMTP 用假的客户端替身，只验证「打包内容对不对、邮件字段全不全、失败会不会吞掉」。
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

from interface import mailer


def make_log(path: Path, turns: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"event": "game_start", "seed": 1, "level": "2"}) + "\n")
        for index in range(turns):
            handle.write(json.dumps({"event": "turn", "step": index}) + "\n")
    return path


def test_load_config_returns_empty_without_a_file(workdir):
    assert mailer.load_config(workdir / "missing.json") == {}


def test_load_config_requires_to_host_user_and_password(workdir):
    path = workdir / "mail.json"
    path.write_text(json.dumps({"to": "a@b.c", "host": "smtp.example.com"}), encoding="utf-8")
    assert mailer.load_config(path) == {}

    path.write_text(
        json.dumps(
            {
                "to": "a@b.c",
                "host": "smtp.example.com",
                "user": "a@b.c",
                "password": "token",
            }
        ),
        encoding="utf-8",
    )
    config = mailer.load_config(path)
    assert config["port"] == mailer.DEFAULT_PORT
    assert config["ssl"] is True
    assert config["from"] == "a@b.c"


def test_build_package_contains_records_and_readme(workdir):
    first = make_log(workdir / "human_1.jsonl")
    second = make_log(workdir / "human_2.jsonl", turns=5)

    payload, files = mailer.build_package([first, second], "device1234")

    assert len(files) == 2
    assert {item["name"] for item in files} == {"human_1.jsonl", "human_2.jsonl"}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert {"human_1.jsonl", "human_2.jsonl", "info.json", "说明.txt"} <= names
        meta = json.loads(archive.read("info.json").decode("utf-8"))
    assert meta["device"] == "device1234"
    assert len(meta["files"]) == 2


def test_build_package_refuses_when_nothing_exists(workdir):
    with pytest.raises(FileNotFoundError):
        mailer.build_package([workdir / "nope.jsonl"], "device1234")


def test_send_builds_a_message_with_a_zip_attachment(workdir, monkeypatch):
    log = make_log(workdir / "human_9.jsonl")
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None, context=None):
            sent["host"] = host
            sent["port"] = port

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, message):
            sent["message"] = message

        def quit(self):
            sent["quit"] = True

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)

    config = {
        "to": "author@example.com",
        "from": "sender@example.com",
        "host": "smtp.example.com",
        "port": 465,
        "user": "sender@example.com",
        "password": "token",
        "ssl": True,
        "timeout": 5.0,
    }
    result = mailer.send([log], config, "device1234")

    assert result["to"] == "author@example.com"
    assert result["files"] == 1
    assert sent["login"] == ("sender@example.com", "token")
    message = sent["message"]
    assert message["To"] == "author@example.com"
    assert "device1234" in message["Subject"]
    attachments = [part for part in message.walk() if part.get_filename()]
    assert attachments and attachments[0].get_filename().endswith(".zip")


def test_device_id_is_stable_across_calls(workdir):
    state = workdir / "mail_state.json"
    first = mailer.device_id(state)
    second = mailer.device_id(state)
    assert first == second
    assert len(first) == 16
