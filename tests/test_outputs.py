"""Acceptance tests for the spatial block bootstrap."""

import json
import math
import os
import subprocess
import sys

import pytest


ENTRY = os.environ.get("SPATIAL_BOOTSTRAP_ENTRY", "/app/spatial_bootstrap_support.py")


def sample():
    points = []
    for index in range(12):
        points.append(
            {
                "plot_id": f"PLOT-{index:02d}",
                "x_km": float(index % 4),
                "y_km": float(index // 4) * 2.0,
                "weight": 1.0 + (index % 3),
                "coverage": 0.2 + index * 0.05,
            }
        )
    return {
        "study_id": "RIDGE-26",
        "points": points,
        "block_size_km": 2.0,
        "replicates": 200,
        "seed": 9147,
        "confidence_level": 0.9,
    }


def write(path, document, raw=None):
    if raw is None:
        raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_bytes(raw.encode("utf-8"))
    return path


def run(tmp_path, document, raw=None, name="result"):
    source = write(tmp_path / "survey.json", document, raw=raw)
    output = tmp_path / f"{name}.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, source, output


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_success_is_quiet(tmp_path):
    """题面：「完整结束后，两个标准流都为空。」"""
    result, _, output = run(tmp_path, sample())
    assert result.returncode == 0 and result.stdout == "" and result.stderr == "" and output.is_file()


def test_weighted_estimate_matches_manual_calculation(tmp_path):
    """题面：「点估计是权重加权的覆盖率」。"""
    payload = sample()
    weights = sum(item["weight"] for item in payload["points"])
    expected = sum(item["weight"] * item["coverage"] for item in payload["points"]) / weights
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 0 and read(output)["estimate"] == pytest.approx(expected)


def test_block_count_uses_grid_coordinates(tmp_path):
    """题面：「每个点属于块坐标 `(floor(x_km/block_size_km), floor(y_km/block_size_km))`。」"""
    payload = sample()
    keys = {
        (math.floor(item["x_km"] / 2.0), math.floor(item["y_km"] / 2.0))
        for item in payload["points"]
    }
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 0 and read(output)["block_count"] == len(keys)


def test_interval_brackets_estimate(tmp_path):
    """题面：「置信区间端点取 `(replicates-1)*p` 位置的线性插值」。"""
    result, _, output = run(tmp_path, sample())
    document = read(output)
    assert result.returncode == 0
    assert document["ci_low"] <= document["estimate"] <= document["ci_high"]


def test_repeat_is_byte_identical(tmp_path):
    """题面：「同输入重跑必须逐字节一致。」"""
    result, source, output = run(tmp_path, sample())
    first = output.read_bytes()
    second = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0 and second.returncode == 0 and output.read_bytes() == first


def test_top_keys_are_exact(tmp_path):
    """题面：「文件根对象含 `study_id`、`points`、`block_size_km`、`replicates`、`seed`、`confidence_level`。」"""
    payload = sample()
    payload["operator"] = "night"
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_point_keys_are_exact(tmp_path):
    """题面：「每条只有 `plot_id`、`x_km`、`y_km`、`weight`、`coverage`」。"""
    payload = sample()
    payload["points"][0]["zone"] = "north"
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_duplicate_json_key_is_refused(tmp_path):
    """题面：「联络单不合格就别生成报表」。"""
    raw = (
        '{"study_id":"A1","points":[],"block_size_km":2,"replicates":200,'
        '"seed":1,"confidence_level":0.9,"seed":2}'
    )
    result, _, output = run(tmp_path, None, raw=raw)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_fewer_than_twelve_points_are_refused(tmp_path):
    """题面：「`points` 有 12 到 120 条」。"""
    payload = sample()
    payload["points"] = payload["points"][:11]
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_duplicate_plot_id_is_refused(tmp_path):
    """题面：「`plot_id` 匹配 `[A-Z][A-Z0-9_-]{1,15}` 且不重复」。"""
    payload = sample()
    payload["points"][1]["plot_id"] = payload["points"][0]["plot_id"]
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_boolean_replicates_is_refused(tmp_path):
    """题面：「布尔值不能冒充数字。」"""
    payload = sample()
    payload["replicates"] = True
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_weight_range_is_enforced(tmp_path):
    """题面：「权重位于 `(0,100]`」。"""
    payload = sample()
    payload["points"][0]["weight"] = 0.0
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_confidence_bounds_are_enforced(tmp_path):
    """题面：「`confidence_level` 位于 0.8 到 0.99。」"""
    payload = sample()
    payload["confidence_level"] = 0.5
    result, _, output = run(tmp_path, payload)
    assert result.returncode == 1 and result.stderr == "运行拒收: BAD_INPUT\n" and not output.exists()


def test_compact_output_key_order(tmp_path):
    """题面：「交回的报表是一行紧凑 JSON，最后仅保留 LF。」"""
    result, _, output = run(tmp_path, sample())
    raw = output.read_bytes()
    document = json.loads(raw)
    assert result.returncode == 0
    assert list(document) == ["study_id", "status", "estimate", "ci_low", "ci_high", "block_count", "replicates"]
    assert b": " not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 1


def test_absent_parent_is_io_failure(tmp_path):
    """题面：「如果结果无处可写」。"""
    source = write(tmp_path / "survey.json", sample())
    output = tmp_path / "absent" / "result.json"
    result = subprocess.run(
        [sys.executable, ENTRY, str(source), str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1 and result.stderr == "运行拒收: IO_FAILURE\n" and not output.exists()
