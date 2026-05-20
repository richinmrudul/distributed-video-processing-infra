#!/usr/bin/env python3
"""Render a worker-scaling comparison report from benchmark JSON results."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCENARIO_FIELDS = (
    "worker_count",
    "uploads",
    "concurrency",
    "upload_success_count",
    "upload_rejection_count",
    "completed_jobs",
    "failed_jobs",
    "timed_out_jobs",
    "throughput_uploads_per_second",
    "p95_upload_latency_seconds",
    "average_processing_duration_seconds",
    "p95_processing_duration_seconds",
    "total_wall_clock_seconds",
    "queue_pressure_level",
)


def _safe_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_worker_count(data: dict[str, Any], source_path: str | None = None) -> int | None:
    summary = data.get("summary") or {}
    if isinstance(summary.get("worker_count"), int):
        return summary["worker_count"]

    metrics_snapshot = data.get("metrics_snapshot") or {}
    queue_health = metrics_snapshot.get("queue_health")
    if isinstance(queue_health, dict):
        worker_count = queue_health.get("worker_count")
        if isinstance(worker_count, int):
            return worker_count
        if isinstance(worker_count, str) and worker_count.isdigit():
            return int(worker_count)

    if source_path:
        match = re.search(r"workers-(\d+)", Path(source_path).name)
        if match:
            return int(match.group(1))
    return None


def queue_pressure_level(data: dict[str, Any]) -> str | None:
    queue_health = (data.get("metrics_snapshot") or {}).get("queue_health")
    if isinstance(queue_health, dict):
        value = queue_health.get("queue_pressure_level")
        return str(value) if value is not None else None
    return None


def comparison_row(data: dict[str, Any], source_path: str | None = None) -> dict[str, Any]:
    config = data.get("config") or {}
    summary = data.get("summary") or {}
    return {
        "worker_count": extract_worker_count(data, source_path),
        "uploads": config.get("uploads") or summary.get("total_attempted"),
        "concurrency": config.get("concurrency"),
        "upload_success_count": summary.get("upload_success_count"),
        "upload_rejection_count": summary.get("upload_rejection_count"),
        "completed_jobs": summary.get("completed_jobs"),
        "failed_jobs": summary.get("failed_jobs"),
        "timed_out_jobs": summary.get("timed_out_jobs"),
        "throughput_uploads_per_second": summary.get("throughput_uploads_per_second"),
        "p95_upload_latency_seconds": summary.get("p95_upload_latency_seconds"),
        "average_processing_duration_seconds": summary.get("average_processing_duration_seconds"),
        "p95_processing_duration_seconds": summary.get("p95_processing_duration_seconds"),
        "total_wall_clock_seconds": summary.get("total_wall_clock_seconds"),
        "queue_pressure_level": queue_pressure_level(data),
    }


def load_rows(input_paths: list[str]) -> list[dict[str, Any]]:
    rows = []
    for input_path in input_paths:
        path = Path(input_path).expanduser().resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        rows.append(comparison_row(data, str(path)))
    return sorted(rows, key=lambda row: row["worker_count"] if row["worker_count"] is not None else 10**9)


def best_by(rows: list[dict[str, Any]], field: str, *, lower_is_better: bool = False) -> dict[str, Any] | None:
    candidates = [row for row in rows if _to_float(row.get(field)) is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda row: _to_float(row[field]) or 0.0) if lower_is_better else max(candidates, key=lambda row: _to_float(row[field]) or 0.0)


def interpretation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fastest_throughput": best_by(rows, "throughput_uploads_per_second"),
        "lowest_p95_processing_duration": best_by(rows, "p95_processing_duration_seconds", lower_is_better=True),
        "lowest_wall_clock": best_by(rows, "total_wall_clock_seconds", lower_is_better=True),
    }


def markdown_table(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| " + " | ".join(SCENARIO_FIELDS) + " |",
        "| " + " | ".join("---" for _ in SCENARIO_FIELDS) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_safe_value(row.get(field)) for field in SCENARIO_FIELDS) + " |")
    return "\n".join(lines)


def _scenario_summary(row: dict[str, Any] | None, metric: str) -> str:
    if not row:
        return "n/a"
    return f"workers={_safe_value(row.get('worker_count'))}, {metric}={_safe_value(row.get(metric))}"


def render_markdown(rows: list[dict[str, Any]], timestamp: str | None = None) -> str:
    generated_at = timestamp or datetime.now(UTC).isoformat()
    facts = interpretation(rows)
    parts = [
        "# Worker Scaling Benchmark Comparison",
        "",
        f"Generated: `{generated_at}`",
        "",
        "## Scenario Table",
        "",
        markdown_table(rows),
        "",
        "## Interpretation",
        "",
        f"- Fastest throughput scenario: {_scenario_summary(facts['fastest_throughput'], 'throughput_uploads_per_second')}",
        f"- Lowest p95 processing duration scenario: {_scenario_summary(facts['lowest_p95_processing_duration'], 'p95_processing_duration_seconds')}",
        f"- Lowest wall-clock scenario: {_scenario_summary(facts['lowest_wall_clock'], 'total_wall_clock_seconds')}",
        "",
        "## Notes",
        "",
        "These results are local-machine dependent and are not production benchmark claims.",
        "Rate limiting, admission control, input video size, host CPU, Docker resource limits, and background load can all change the numbers.",
        "",
    ]
    return "\n".join(parts)


def comparison_payload(rows: list[dict[str, Any]], timestamp: str | None = None) -> dict[str, Any]:
    return {
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "scenarios": rows,
        "interpretation": interpretation(rows),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render worker-scaling benchmark comparison reports.")
    parser.add_argument("--inputs", nargs="+", required=True, help="Benchmark JSON result files.")
    parser.add_argument("--output-md", required=True, help="Output Markdown comparison report.")
    parser.add_argument("--output-json", help="Optional output JSON comparison summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_rows(args.inputs)
    timestamp = datetime.now(UTC).isoformat()

    output_md = Path(args.output_md).expanduser().resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(rows, timestamp), encoding="utf-8")
    print(f"wrote_scaling_report: {output_md}")

    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(comparison_payload(rows, timestamp), indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote_scaling_json:   {output_json}")


if __name__ == "__main__":
    main()
