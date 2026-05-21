#!/usr/bin/env python3
"""Measure cold start: container StartedAt → /health status ok."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

DEFAULT_IMAGE = "rag-naive"
CONTAINER_NAME = "rag-cold"
ENV_FILE = "boilerplate/.env"
HOST_PORT = 8000
HEALTH_URL = f"http://127.0.0.1:{HOST_PORT}/health"
POLL_INTERVAL_S = 0.05


def parse_docker_started_at(raw: str) -> float:
    """Parse Docker StartedAt; truncate nanoseconds for fromisoformat."""
    normalized = raw.strip().replace("Z", "+00:00")
    # e.g. 2026-05-21T16:31:50.401157917+00:00 → ...50.401157+00:00
    normalized = re.sub(r"(\.\d{6})\d+", r"\1", normalized)
    return datetime.fromisoformat(normalized).timestamp()


def main() -> int:
    image = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IMAGE

    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    cid = subprocess.check_output(
        [
            "docker",
            "run",
            "--rm",
            "-d",
            "-p",
            f"{HOST_PORT}:{HOST_PORT}",
            "--env-file",
            ENV_FILE,
            "--name",
            CONTAINER_NAME,
            image,
        ],
        text=True,
    ).strip()

    started_at = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.State.StartedAt}}", cid],
        text=True,
    ).strip()
    t0 = parse_docker_started_at(started_at)

    try:
        while True:
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=0.5) as resp:
                    if json.load(resp)["status"] == "ok":
                        break
            except Exception:
                pass
            time.sleep(POLL_INTERVAL_S)

        elapsed = time.time() - t0
        print(f"Cold start: {elapsed:.2f}s")
        return 0
    finally:
        subprocess.run(["docker", "stop", "-t", "2", cid], check=False)


if __name__ == "__main__":
    sys.exit(main())
