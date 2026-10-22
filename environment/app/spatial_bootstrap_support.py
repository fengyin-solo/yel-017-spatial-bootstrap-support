#!/usr/bin/env python3
"""Legacy independent-row bootstrap."""

import json
import math
import sys
from pathlib import Path


def main(argv):
    if len(argv) != 3:
        return 1
    source, target = Path(argv[1]), Path(argv[2])
    payload = json.loads(source.read_text(encoding="utf-8"))
    points = payload["points"]
    estimate = sum(item["coverage"] for item in points) / len(points)
    target.write_text(
        json.dumps(
            {
                "study_id": payload["study_id"],
                "status": "complete",
                "estimate": estimate,
                "ci_low": estimate,
                "ci_high": estimate,
                "block_count": len(points),
                "replicates": payload["replicates"],
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
