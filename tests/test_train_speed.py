"""训练记速器的小测试：只测纯函数与参数解析，不跑真实训练。"""

from tools.train_speed import display_width, human_time, pad


def test_human_time_formats_seconds():
    assert human_time(0.5) == "0.5 秒"
    assert human_time(59) == "59.0 秒"


def test_human_time_formats_minutes():
    assert human_time(60) == "1.0 分钟"
    assert human_time(3599) == "60.0 分钟"


def test_human_time_formats_hours():
    assert human_time(3600) == "1.0 小时"
    assert human_time(7200) == "2.0 小时"


def test_display_width_counts_cjk_as_two():
    # 中文在终端占两格，否则表头会和数字错位
    assert display_width("任务") == 4
    assert display_width("abc") == 3
    assert display_width("步/秒") == 5


def test_pad_aligns_by_display_width():
    assert pad("任务", 10) == "任务" + " " * 6
    assert display_width(pad("任务", 10)) == 10
    assert display_width(pad("bc", 10)) == 10
    assert pad("64", 7, align="right") == "     64"

