from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "benchmark_uploads.py"
    spec = importlib.util.spec_from_file_location("benchmark_uploads", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["benchmark_uploads"] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark_module()


def test_percentile_95_uses_nearest_rank():
    assert benchmark.percentile_95([]) is None
    assert benchmark.percentile_95([0.1]) == 0.1
    assert benchmark.percentile_95([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 10


def test_status_code_counts_groups_errors_and_codes():
    attempts = [
        benchmark.UploadAttempt(0, 201, 0.1, True, "v1"),
        benchmark.UploadAttempt(1, 429, 0.2, False, None),
        benchmark.UploadAttempt(2, None, 0.3, False, None, "connection failed"),
        benchmark.UploadAttempt(3, 201, 0.1, True, "v2"),
    ]

    assert benchmark.status_code_counts(attempts) == {"201": 2, "429": 1, "error": 1}


def test_summarize_results_aggregates_upload_and_processing_outcomes():
    attempts = [
        benchmark.UploadAttempt(0, 201, 0.10, True, "v1"),
        benchmark.UploadAttempt(1, 503, 0.20, False, None),
        benchmark.UploadAttempt(2, 200, 0.30, True, "v1"),
    ]
    job_results = [
        benchmark.JobResult("v1", "COMPLETED", 1.5, False),
        benchmark.JobResult("v2", "FAILED", 2.0, False),
        benchmark.JobResult("v3", "PROCESSING", None, True),
    ]

    summary = benchmark.summarize_results(
        attempts=attempts,
        job_results=job_results,
        wall_clock_seconds=2.0,
        total_requested=3,
    )

    assert summary["total_attempted"] == 3
    assert summary["upload_success_count"] == 2
    assert summary["upload_rejection_count"] == 1
    assert summary["status_code_counts"] == {"200": 1, "201": 1, "503": 1}
    assert summary["completed_jobs"] == 1
    assert summary["failed_jobs"] == 1
    assert summary["timed_out_jobs"] == 1
    assert summary["average_processing_duration_seconds"] == 1.75
    assert summary["throughput_uploads_per_second"] == 1.5
