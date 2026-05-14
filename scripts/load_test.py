#!/usr/bin/env python3
"""Lightweight concurrent upload generator for throughput experiments (not a full benchmark suite)."""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import httpx


async def _upload_one(
    client: httpx.AsyncClient,
    url: str,
    file_path: Path,
    sem: asyncio.Semaphore,
) -> bool:
    async with sem:
        try:
            with file_path.open("rb") as fp:
                files = {"file": (file_path.name, fp, "application/octet-stream")}
                response = await client.post(url, files=files, timeout=httpx.Timeout(600.0))
            return response.status_code in (200, 201)
        except (httpx.HTTPError, OSError):
            return False


async def _run(args: argparse.Namespace) -> tuple[int, int, float]:
    upload_url = args.base_url.rstrip("/") + "/api/v1/videos/upload"
    sem = asyncio.Semaphore(args.concurrency)
    file_path = Path(args.file).expanduser().resolve()
    if not file_path.is_file():
        raise SystemExit(f"File not found: {file_path}")

    limits = httpx.Limits(max_connections=args.concurrency + 5, max_keepalive_connections=args.concurrency + 5)
    async with httpx.AsyncClient(limits=limits) as client:
        started = time.perf_counter()
        tasks = [_upload_one(client, upload_url, file_path, sem) for _ in range(args.requests)]
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - started

    successes = sum(1 for ok in results if ok)
    failures = len(results) - successes
    return successes, failures, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrent POST uploads to the video API.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API root URL.")
    parser.add_argument("--file", required=True, help="Video file path to upload repeatedly.")
    parser.add_argument("--requests", type=int, default=10, help="Total upload attempts.")
    parser.add_argument("--concurrency", type=int, default=3, help="Max in-flight uploads.")
    args = parser.parse_args()

    successes, failures, elapsed = asyncio.run(_run(args))
    total = successes + failures
    rps = total / elapsed if elapsed > 0 else 0.0

    print(f"total_requests:   {total}")
    print(f"success_count:    {successes}")
    print(f"failure_count:    {failures}")
    print(f"elapsed_seconds:  {elapsed:.3f}")
    print(f"requests_per_sec: {rps:.2f}")


if __name__ == "__main__":
    main()
