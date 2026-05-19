#!/usr/bin/env python3
"""Local upload benchmark for the distributed video processing stack."""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

TERMINAL_STATUSES = {"COMPLETED", "FAILED"}
METRIC_PREFIXES = (
    "video_uploads_total",
    "video_upload_rejections_total",
    "video_upload_rate_limit_rejections_total",
    "upload_admission_queue_depth",
    "upload_admission_worker_count",
    "video_processing_jobs_total",
    "video_processing_duration_seconds",
    "queue_depth",
)


@dataclass(frozen=True)
class UploadAttempt:
    index: int
    status_code: int | None
    latency_seconds: float
    accepted: bool
    video_id: str | None
    error: str | None = None


@dataclass(frozen=True)
class JobResult:
    video_id: str
    status: str
    processing_duration_seconds: float | None
    timed_out: bool


def percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, int(0.95 * len(ordered) + 0.999999) - 1)
    return ordered[index]


def status_code_counts(attempts: list[UploadAttempt]) -> dict[str, int]:
    counts = Counter(str(attempt.status_code) if attempt.status_code is not None else "error" for attempt in attempts)
    return dict(sorted(counts.items()))


def summarize_results(
    *,
    attempts: list[UploadAttempt],
    job_results: list[JobResult],
    wall_clock_seconds: float,
    total_requested: int,
) -> dict[str, Any]:
    latencies = [attempt.latency_seconds for attempt in attempts if attempt.status_code is not None]
    processing_durations = [
        result.processing_duration_seconds
        for result in job_results
        if result.processing_duration_seconds is not None
    ]
    completed_jobs = sum(1 for result in job_results if result.status == "COMPLETED" and not result.timed_out)
    failed_jobs = sum(1 for result in job_results if result.status == "FAILED" and not result.timed_out)
    timed_out_jobs = sum(1 for result in job_results if result.timed_out)
    upload_success_count = sum(1 for attempt in attempts if attempt.accepted)

    return {
        "total_attempted": total_requested,
        "upload_success_count": upload_success_count,
        "upload_rejection_count": len(attempts) - upload_success_count,
        "status_code_counts": status_code_counts(attempts),
        "average_upload_latency_seconds": statistics.fmean(latencies) if latencies else None,
        "p95_upload_latency_seconds": percentile_95(latencies),
        "completed_jobs": completed_jobs,
        "failed_jobs": failed_jobs,
        "timed_out_jobs": timed_out_jobs,
        "average_processing_duration_seconds": statistics.fmean(processing_durations)
        if processing_durations
        else None,
        "p95_processing_duration_seconds": percentile_95(processing_durations),
        "total_wall_clock_seconds": wall_clock_seconds,
        "throughput_uploads_per_second": total_requested / wall_clock_seconds if wall_clock_seconds > 0 else 0.0,
    }


def resolve_video_path(video_path: str | None) -> Path:
    if video_path:
        path = Path(video_path).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"Video file not found: {path}")
        return path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("No --video-path provided and local ffmpeg was not found. Pass --video-path /path/to/test.mp4.")

    out = Path(tempfile.gettempdir()) / "distributed-video-benchmark.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:d=1",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return out


def idempotency_key_for(index: int, mode: str, run_id: str) -> str | None:
    if mode == "none":
        return None
    if mode == "unique":
        return f"benchmark-{run_id}-{index}"
    if mode == "repeated":
        return f"benchmark-{run_id}-repeated"
    raise ValueError(f"unsupported idempotency mode: {mode}")


def upload_one(base_url: str, video_path: Path, index: int, idempotency_key: str | None) -> UploadAttempt:
    headers = {}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    started = time.perf_counter()
    try:
        with video_path.open("rb") as fh:
            response = requests.post(
                f"{base_url}/api/v1/videos/upload",
                headers=headers,
                files={"file": (video_path.name, fh, "video/mp4")},
                timeout=30,
            )
        latency = time.perf_counter() - started
        video_id = None
        try:
            body = response.json()
            video_id = body.get("id") if isinstance(body, dict) else None
        except ValueError:
            pass
        return UploadAttempt(
            index=index,
            status_code=response.status_code,
            latency_seconds=latency,
            accepted=response.status_code in (200, 201),
            video_id=video_id,
        )
    except requests.RequestException as exc:
        latency = time.perf_counter() - started
        return UploadAttempt(index=index, status_code=None, latency_seconds=latency, accepted=False, video_id=None, error=str(exc))


def run_uploads(base_url: str, video_path: Path, uploads: int, concurrency: int, idempotency_mode: str) -> list[UploadAttempt]:
    run_id = uuid.uuid4().hex[:12]
    attempts: list[UploadAttempt] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
        futures = [
            executor.submit(upload_one, base_url, video_path, index, idempotency_key_for(index, idempotency_mode, run_id))
            for index in range(uploads)
        ]
        for future in as_completed(futures):
            attempts.append(future.result())
    return sorted(attempts, key=lambda attempt: attempt.index)


def poll_job(base_url: str, video_id: str, timeout_seconds: int) -> JobResult:
    deadline = time.monotonic() + timeout_seconds
    last_status = "UNKNOWN"
    last_duration: float | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api/v1/videos/{video_id}/status", timeout=5)
            if response.status_code == 200:
                body = response.json()
                last_status = body.get("status", "UNKNOWN")
                last_duration = body.get("processing_duration_seconds")
                if last_status in TERMINAL_STATUSES:
                    return JobResult(video_id=video_id, status=last_status, processing_duration_seconds=last_duration, timed_out=False)
        except requests.RequestException:
            pass
        time.sleep(1)
    return JobResult(video_id=video_id, status=last_status, processing_duration_seconds=last_duration, timed_out=True)


def poll_jobs(base_url: str, attempts: list[UploadAttempt], timeout_seconds: int) -> list[JobResult]:
    video_ids = sorted({attempt.video_id for attempt in attempts if attempt.accepted and attempt.video_id})
    return [poll_job(base_url, video_id, timeout_seconds) for video_id in video_ids]


def fetch_metrics_snapshot(base_url: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"queue_health": None, "metrics_lines": []}
    try:
        response = requests.get(f"{base_url}/api/v1/queue/health", timeout=5)
        if response.status_code == 200:
            snapshot["queue_health"] = response.json()
    except requests.RequestException:
        snapshot["queue_health"] = "unavailable"

    try:
        response = requests.get(f"{base_url}/metrics", timeout=5)
        if response.status_code == 200:
            lines = []
            for line in response.text.splitlines():
                if line.startswith("#"):
                    continue
                if any(line.startswith(prefix) for prefix in METRIC_PREFIXES):
                    lines.append(line)
            snapshot["metrics_lines"] = lines
    except requests.RequestException:
        snapshot["metrics_lines"] = ["metrics unavailable"]
    return snapshot


def print_summary(summary: dict[str, Any], metrics_snapshot: dict[str, Any]) -> None:
    print()
    print("Benchmark summary")
    print(f"total_attempted:                    {summary['total_attempted']}")
    print(f"upload_success_count:               {summary['upload_success_count']}")
    print(f"upload_rejection_count:             {summary['upload_rejection_count']}")
    print(f"status_code_counts:                 {summary['status_code_counts']}")
    print(f"average_upload_latency_seconds:     {_format_optional_float(summary['average_upload_latency_seconds'])}")
    print(f"p95_upload_latency_seconds:         {_format_optional_float(summary['p95_upload_latency_seconds'])}")
    print(f"completed_jobs:                     {summary['completed_jobs']}")
    print(f"failed_jobs:                        {summary['failed_jobs']}")
    print(f"timed_out_jobs:                     {summary['timed_out_jobs']}")
    print(f"average_processing_duration_seconds:{_format_optional_float(summary['average_processing_duration_seconds'], leading_space=True)}")
    print(f"p95_processing_duration_seconds:    {_format_optional_float(summary['p95_processing_duration_seconds'])}")
    print(f"total_wall_clock_seconds:           {summary['total_wall_clock_seconds']:.3f}")
    print(f"throughput_uploads_per_second:      {summary['throughput_uploads_per_second']:.2f}")

    print()
    print("Metrics snapshot")
    queue_health = metrics_snapshot.get("queue_health")
    if isinstance(queue_health, dict):
        print(f"queue_health:                       {queue_health}")
    else:
        print(f"queue_health:                       {queue_health or 'unavailable'}")
    for line in metrics_snapshot.get("metrics_lines", []):
        print(line)


def _format_optional_float(value: float | None, *, leading_space: bool = False) -> str:
    formatted = "n/a" if value is None else f"{value:.3f}"
    return f" {formatted}" if leading_space else formatted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark repeated video uploads against the local API.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL.")
    parser.add_argument("--video-path", help="Video file path. If omitted, local ffmpeg is used to generate a tiny MP4.")
    parser.add_argument("--uploads", type=int, default=10, help="Total upload attempts.")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent uploads.")
    parser.add_argument("--poll", action=argparse.BooleanOptionalAction, default=True, help="Poll accepted jobs until terminal state.")
    parser.add_argument("--poll-timeout", type=int, default=120, help="Per-job status polling timeout in seconds.")
    parser.add_argument("--idempotency-mode", choices=("none", "unique", "repeated"), default="none")
    parser.add_argument("--admin-api-key", default="dev-admin-key", help="Admin API key for optional future checks.")
    parser.add_argument("--json-output", help="Write benchmark results JSON to this path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.uploads < 1:
        raise SystemExit("--uploads must be at least 1")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be at least 1")

    base_url = args.base_url.rstrip("/")
    video_path = resolve_video_path(args.video_path)

    started = time.perf_counter()
    attempts = run_uploads(base_url, video_path, args.uploads, args.concurrency, args.idempotency_mode)
    job_results = poll_jobs(base_url, attempts, args.poll_timeout) if args.poll else []
    wall_clock_seconds = time.perf_counter() - started

    summary = summarize_results(
        attempts=attempts,
        job_results=job_results,
        wall_clock_seconds=wall_clock_seconds,
        total_requested=args.uploads,
    )
    metrics_snapshot = fetch_metrics_snapshot(base_url)
    result = {
        "summary": summary,
        "attempts": [asdict(attempt) for attempt in attempts],
        "job_results": [asdict(result) for result in job_results],
        "metrics_snapshot": metrics_snapshot,
    }
    print_summary(summary, metrics_snapshot)

    if args.json_output:
        output_path = Path(args.json_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print()
        print(f"wrote_json_output:                  {output_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("benchmark interrupted")
