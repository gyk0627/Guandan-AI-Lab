"""统一性能测试入口（tools/benchmark.py）的测试。

只测不跑 GPU 的部分：预设表、报告拍平、对比判定、v1/v2 报告兼容。
真跑测试见 README「七、性能测试与硬件选型」。
"""

import json
from pathlib import Path

import pytest

from tools import benchmark

TMP = Path(__file__).resolve().parents[1] / ".test_tmp" / "benchmark_tests"


def write_report(name: str, payload: dict) -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    path = TMP / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_presets_are_increasing_in_work():
    assert set(benchmark.PRESETS) == {"quick", "standard", "full"}
    assert benchmark.PRESETS["quick"]["games"] < benchmark.PRESETS["standard"]["games"]
    assert benchmark.PRESETS["standard"]["games"] < benchmark.PRESETS["full"]["games"]
    # quick 必须够快：只跑 CPU 与推理，不碰训练
    assert benchmark.PRESETS["quick"]["modules"] == ["cpu", "inference"]
    for config in benchmark.PRESETS.values():
        assert config["modules"]
        assert config["games"] > 0
        assert config["note"]


def test_flatten_handles_dicts_and_lists():
    flat = benchmark.flatten({"a": {"b": 1.5, "c": [{"d": 2}, {"d": 3}]}, "e": "文字", "f": True})
    assert flat["a.b"] == 1.5
    assert flat["a.c[0].d"] == 2
    assert flat["a.c[1].d"] == 3
    assert "e" not in flat  # 字符串不是数字
    assert "f" not in flat  # 布尔不当数字


def test_direction_knows_which_way_is_better():
    assert benchmark.direction("cpu.games_per_second") == 1
    assert benchmark.direction("inference.rows[0].inferences_per_second") == 1
    assert benchmark.direction("cpu.decisions_per_second") == 1
    assert benchmark.direction("train.bc_best_val_acc") == 0


def test_direction_lower_is_better_metrics():
    """越小越好的真实指标（名字里单位在中间，如 ms_per_batch）。

    曾因 tools/benchmark.py 只按末段后缀判方向而失败（ms_per_batch、*_seconds_per_epoch
    被判"仅参考"），bench-verifier 改用 LOWER_IS_BETTER 正则后已修复，此测试转正。
    """
    assert benchmark.direction("inference.ms_per_batch") == -1
    assert benchmark.direction("inference.rows[0].ms_per_batch") == -1
    assert benchmark.direction("train.bc_seconds_per_epoch") == -1
    assert benchmark.direction("train.value_seconds_per_epoch") == -1
    assert benchmark.direction("pipeline.seconds_per_game_end_to_end") == -1


def test_compare_reports_flags_speedup_and_slowdown():
    current = {"modules": {"cpu": {"games_per_second": 9.46}}}
    baseline = {"modules": {"cpu": {"games_per_second": 4.73}}}
    rows = benchmark.compare_reports(current, baseline)
    assert len(rows) == 1
    assert rows[0]["verdict"] == "更快"
    assert rows[0]["multiple"] == pytest.approx(2.0, rel=1e-3)

    rows = benchmark.compare_reports(baseline, current)
    assert rows[0]["verdict"] == "变慢"

    # 差 5% 以内算持平，不当结论
    close = {"modules": {"cpu": {"games_per_second": 4.80}}}
    assert benchmark.compare_reports(close, baseline)[0]["verdict"] == "持平"


def test_compare_skips_measurement_overhead_fields():
    # 让唯一可比的性能指标也不同，这样 rows 非空：否则空列表会让断言空转通过
    current = {"modules": {"cpu": {"module_seconds": 1.0, "games_per_second": 12.0}}}
    baseline = {"modules": {"cpu": {"module_seconds": 5.0, "games_per_second": 10.0}}}
    rows = benchmark.compare_reports(current, baseline)
    assert [row["metric"] for row in rows] == ["cpu.games_per_second"]
    assert all("module_seconds" not in row["metric"] for row in rows)


def test_compare_command_writes_json():
    current_path = write_report("cmp_current.json", {
        "schema": "gandan-benchmark/2",
        "modules": {"cpu": {"games_per_second": 9.46}},
    })
    baseline_path = write_report("cmp_baseline.json", {
        "schema": "gandan-benchmark/2",
        "modules": {"cpu": {"games_per_second": 4.73}},
    })
    out_path = TMP / "cmp_out.json"
    assert benchmark.main(["compare", str(current_path), str(baseline_path), "--out", str(out_path)]) == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "gandan-benchmark/2"
    assert payload["kind"] == "compare"
    assert [row["verdict"] for row in payload["rows"]] == ["更快"]
    assert payload["rows"][0]["multiple"] == pytest.approx(2.0, rel=1e-3)


def test_load_report_accepts_v1_and_v2():
    v1 = write_report("v1.json", {
        "created": "2026-11-03 23:22:51",
        "host": {"host": "OLD-PC"},
        "modules": {"cpu": {"games_per_second": 4.73}},
        "resources": {"cpu_avg": 20.5},
    })
    loaded = benchmark.load_report(v1)
    assert loaded["schema"] == "gandan-benchmark/1"
    assert loaded["host"]["host"] == "OLD-PC"
    assert loaded["modules"]["cpu"]["games_per_second"] == 4.73

    v2 = write_report("v2.json", {
        "schema": "gandan-benchmark/2",
        "kind": "suite",
        "preset": "quick",
        "created": "2026-11-04 20:07:36",
        "host": {"host": "NEW-PC"},
        "modules": {"cpu": {"games_per_second": 5.72}},
        "resources": {},
    })
    loaded = benchmark.load_report(v2)
    assert loaded["schema"] == "gandan-benchmark/2"
    assert loaded["preset"] == "quick"
    assert loaded["modules"]["cpu"]["games_per_second"] == 5.72


def test_list_command_prints_presets(capsys):
    assert benchmark.main(["list"]) == 0
    output = capsys.readouterr().out
    for keyword in ("quick", "standard", "full", "compare", "roofline"):
        assert keyword in output


def test_custom_preset_needs_modules(capsys):
    assert benchmark.main(["run", "--preset", "custom"]) == 2
    assert "必须给 --modules" in capsys.readouterr().err
