#!/usr/bin/env python3
"""Weighted mean with deterministic spatial block bootstrap."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path


TOP = {"study_id", "points", "block_size_km", "replicates", "seed", "confidence_level"}
POINT = {"plot_id", "x_km", "y_km", "weight", "coverage"}
PLOT_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,15}$")


class Refusal(Exception):
    def __init__(self, kind):
        self.kind = kind


def fail(kind):
    sys.stderr.write(f"运行拒收: {kind}\n")
    raise SystemExit(1)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def integer(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal("BAD_INPUT")
        result[key] = value
    return result


def validate(payload):
    if not isinstance(payload, dict) or set(payload) != TOP:
        raise Refusal("BAD_INPUT")
    study_id = payload["study_id"]
    if (
        not isinstance(study_id, str)
        or not 2 <= len(study_id) <= 48
        or study_id != study_id.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in study_id)
    ):
        raise Refusal("BAD_INPUT")
    points = payload["points"]
    if not isinstance(points, list) or not 12 <= len(points) <= 120:
        raise Refusal("BAD_INPUT")
    seen = set()
    cleaned = []
    for point in points:
        if not isinstance(point, dict) or set(point) != POINT:
            raise Refusal("BAD_INPUT")
        plot_id = point["plot_id"]
        if not isinstance(plot_id, str) or not PLOT_PATTERN.fullmatch(plot_id) or plot_id in seen:
            raise Refusal("BAD_INPUT")
        seen.add(plot_id)
        if any(not finite(point[key]) for key in ("x_km", "y_km", "weight", "coverage")):
            raise Refusal("BAD_INPUT")
        if not 0 < point["weight"] <= 100 or not 0 <= point["coverage"] <= 1:
            raise Refusal("BAD_INPUT")
        cleaned.append(
            {
                "plot_id": plot_id,
                "x_km": float(point["x_km"]),
                "y_km": float(point["y_km"]),
                "weight": float(point["weight"]),
                "coverage": float(point["coverage"]),
            }
        )
    block_size = payload["block_size_km"]
    if not finite(block_size) or not 0 < block_size <= 10000:
        raise Refusal("BAD_INPUT")
    replicates = payload["replicates"]
    if not integer(replicates, 50, 2000):
        raise Refusal("BAD_INPUT")
    seed = payload["seed"]
    if not integer(seed, 0, 4294967295):
        raise Refusal("BAD_INPUT")
    confidence = payload["confidence_level"]
    if not finite(confidence) or not 0.8 <= confidence <= 0.99:
        raise Refusal("BAD_INPUT")
    return study_id, cleaned, float(block_size), replicates, seed, float(confidence)


def weighted_mean(points):
    denominator = sum(point["weight"] for point in points)
    return sum(point["weight"] * point["coverage"] for point in points) / denominator


def quantile(sorted_values, probability):
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def bootstrap(study_id, points, block_size, replicates, seed, confidence):
    blocks = {}
    for point in points:
        key = (math.floor(point["x_km"] / block_size), math.floor(point["y_km"] / block_size))
        blocks.setdefault(key, []).append(point)
    ordered = [blocks[key] for key in sorted(blocks)]
    values = []
    state = seed
    for _ in range(replicates):
        sample = []
        for _ in range(len(ordered)):
            state = (1664525 * state + 1013904223) % 4294967296
            sample.extend(ordered[state % len(ordered)])
        values.append(weighted_mean(sample))
    values.sort()
    tail = (1.0 - confidence) / 2.0
    return {
        "study_id": study_id,
        "status": "complete",
        "estimate": weighted_mean(points),
        "ci_low": quantile(values, tail),
        "ci_high": quantile(values, 1.0 - tail),
        "block_count": len(ordered),
        "replicates": replicates,
    }


def publish(target, payload):
    if not target.parent.is_dir() or target.is_dir() or not os.access(target.parent, os.W_OK):
        raise Refusal("IO_FAILURE")
    old = target.read_bytes() if target.exists() else None
    stage = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=".spatial-", dir=target.parent)
        stage = Path(name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, target)
        stage = None
    except OSError:
        if old is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(old)
        raise Refusal("IO_FAILURE")
    finally:
        if stage is not None:
            stage.unlink(missing_ok=True)


def main(argv):
    if len(argv) != 3:
        fail("BAD_INPUT")
    source, target = Path(argv[1]), Path(argv[2])
    try:
        payload = json.loads(source.read_text(encoding="utf-8"), object_pairs_hook=strict_pairs)
        result = bootstrap(*validate(payload))
        encoded = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        publish(target, encoded)
        return 0
    except Refusal as exc:
        fail(exc.kind)
    except (OSError, UnicodeError, ValueError):
        fail("BAD_INPUT")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
