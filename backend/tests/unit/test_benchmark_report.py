from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_report_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "render_benchmark_report.py"
    spec = importlib.util.spec_from_file_location("render_benchmark_report", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["render_benchmark_report"] = module
    spec.loader.exec_module(module)
    return module


report = _load_report_module()


def _sample_result():
    return {
        "timestamp": "2026-05-19T00:00:00+00:00",
        "config": {
            "base_url": "http://localhost:8000",
            "uploads": 5,
            "concurrency": 2,
            "poll": True,
            "poll_timeout": 120,
            "idempotency_mode": "none",
            "admin_api_key": "dev-admin-key",
        },
        "summary": {
            "total_attempted": 5,
            "upload_success_count": 5,
            "upload_rejection_count": 0,
            "status_code_counts": {"201": 5},
            "rejection_reason_counts": {},
            "average_upload_latency_seconds": 0.05,
            "p95_upload_latency_seconds": 0.09,
            "completed_jobs": 5,
            "failed_jobs": 0,
            "timed_out_jobs": 0,
            "average_processing_duration_seconds": 0.2,
            "p95_processing_duration_seconds": 0.3,
            "total_wall_clock_seconds": 1.0,
            "throughput_uploads_per_second": 5.0,
        },
        "metrics_snapshot": {
            "queue_health": {
                "redis_connected": True,
                "queue_name": "video-processing",
                "queued_jobs_count": 0,
                "failed_jobs_count": 0,
                "started_jobs_count": 0,
                "finished_jobs_count": 5,
                "active_jobs_count": 0,
                "worker_count": 3,
                "queue_pressure_level": "LOW",
            },
            "metrics_lines": ["video_uploads_total{status=\"queued\",storage_backend=\"object\"} 5.0"],
        },
    }


def test_render_report_contains_expected_sections_and_summary_fields():
    markdown = report.render_report(_sample_result())

    assert "# Benchmark Performance Report" in markdown
    assert "## Benchmark Config" in markdown
    assert "## Summary" in markdown
    assert "## Queue And Worker Snapshot" in markdown
    assert "`throughput_uploads_per_second`" in markdown
    assert "`worker_count`" in markdown


def test_render_report_does_not_render_accidental_admin_key():
    markdown = report.render_report(_sample_result())

    assert "admin_api_key" not in markdown
    assert "dev-admin-key" not in markdown


def test_render_report_redacts_sensitive_metric_lines():
    data = _sample_result()
    data["metrics_snapshot"]["metrics_lines"] = ["admin_api_key_leak dev-admin-key"]

    markdown = report.render_report(data)

    assert "admin_api_key_leak" not in markdown
    assert "dev-admin-key" not in markdown
    assert "[redacted sensitive metric line]" in markdown
