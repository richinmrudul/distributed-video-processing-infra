from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_scaling_report_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "scripts" / "render_scaling_report.py"
    spec = importlib.util.spec_from_file_location("render_scaling_report", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["render_scaling_report"] = module
    spec.loader.exec_module(module)
    return module


scaling_report = _load_scaling_report_module()


def _benchmark_result(worker_count=3, throughput=2.0, p95_processing=1.0, wall_clock=5.0):
    return {
        "timestamp": "2026-05-19T00:00:00+00:00",
        "config": {
            "uploads": 6,
            "concurrency": 2,
        },
        "summary": {
            "total_attempted": 6,
            "upload_success_count": 6,
            "upload_rejection_count": 0,
            "completed_jobs": 6,
            "failed_jobs": 0,
            "timed_out_jobs": 0,
            "throughput_uploads_per_second": throughput,
            "p95_upload_latency_seconds": 0.25,
            "average_processing_duration_seconds": 0.7,
            "p95_processing_duration_seconds": p95_processing,
            "total_wall_clock_seconds": wall_clock,
        },
        "metrics_snapshot": {
            "queue_health": {
                "worker_count": worker_count,
                "queue_pressure_level": "LOW",
            }
        },
    }


def test_extract_worker_count_from_queue_health():
    data = _benchmark_result(worker_count=5)

    assert scaling_report.extract_worker_count(data) == 5


def test_comparison_row_handles_missing_optional_fields_gracefully():
    data = {
        "config": {"uploads": 4},
        "summary": {"upload_success_count": 4},
        "metrics_snapshot": {"queue_health": "unavailable"},
    }

    row = scaling_report.comparison_row(data, "benchmark-results/scaling-workers-1.json")

    assert row["worker_count"] == 1
    assert row["uploads"] == 4
    assert row["concurrency"] is None
    assert row["queue_pressure_level"] is None


def test_builds_comparison_rows_and_identifies_best_throughput():
    rows = [
        scaling_report.comparison_row(_benchmark_result(worker_count=1, throughput=1.0)),
        scaling_report.comparison_row(_benchmark_result(worker_count=3, throughput=3.5)),
        scaling_report.comparison_row(_benchmark_result(worker_count=5, throughput=2.5)),
    ]

    best = scaling_report.best_by(rows, "throughput_uploads_per_second")

    assert best["worker_count"] == 3
    assert best["throughput_uploads_per_second"] == 3.5


def test_interpretation_identifies_lowest_duration_and_wall_clock():
    rows = [
        scaling_report.comparison_row(_benchmark_result(worker_count=1, p95_processing=1.5, wall_clock=9.0)),
        scaling_report.comparison_row(_benchmark_result(worker_count=3, p95_processing=0.8, wall_clock=4.0)),
    ]

    facts = scaling_report.interpretation(rows)

    assert facts["lowest_p95_processing_duration"]["worker_count"] == 3
    assert facts["lowest_wall_clock"]["worker_count"] == 3


def test_rendered_markdown_contains_key_sections():
    rows = [
        scaling_report.comparison_row(_benchmark_result(worker_count=1, throughput=1.0)),
        scaling_report.comparison_row(_benchmark_result(worker_count=3, throughput=2.0)),
    ]

    markdown = scaling_report.render_markdown(rows, "2026-05-19T00:00:00+00:00")

    assert "# Worker Scaling Benchmark Comparison" in markdown
    assert "## Scenario Table" in markdown
    assert "## Interpretation" in markdown
    assert "worker_count" in markdown
    assert "Fastest throughput scenario" in markdown
