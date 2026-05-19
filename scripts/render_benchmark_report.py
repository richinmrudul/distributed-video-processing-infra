#!/usr/bin/env python3
"""Render a small Markdown report from benchmark_uploads.py JSON output."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SENSITIVE_KEYS = ("admin_api_key", "api_key", "secret", "token", "password")


def _safe_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _safe_items(mapping: dict[str, Any]) -> list[tuple[str, Any]]:
    return [(key, value) for key, value in mapping.items() if not any(part in key.lower() for part in SENSITIVE_KEYS)]


def markdown_table(rows: list[tuple[str, Any]], *, key_header: str = "Field", value_header: str = "Value") -> str:
    lines = [f"| {key_header} | {value_header} |", "| --- | --- |"]
    for key, value in rows:
        lines.append(f"| `{key}` | {_safe_value(value)} |")
    return "\n".join(lines)


def render_report(data: dict[str, Any]) -> str:
    timestamp = data.get("timestamp", "unknown")
    config = data.get("config") or {}
    summary = data.get("summary") or {}
    metrics_snapshot = data.get("metrics_snapshot") or {}
    queue_health = metrics_snapshot.get("queue_health")
    metrics_lines = metrics_snapshot.get("metrics_lines") or []

    parts = [
        "# Benchmark Performance Report",
        "",
        f"Generated: `{timestamp}`",
        "",
        "## Benchmark Config",
        "",
        markdown_table(_safe_items(config)),
        "",
        "## Summary",
        "",
        markdown_table(_safe_items(summary)),
        "",
        "## Queue And Worker Snapshot",
        "",
    ]

    if isinstance(queue_health, dict):
        fields = [
            "redis_connected",
            "queue_name",
            "queued_jobs_count",
            "failed_jobs_count",
            "started_jobs_count",
            "finished_jobs_count",
            "active_jobs_count",
            "worker_count",
            "queue_pressure_level",
        ]
        parts.append(markdown_table([(field, queue_health.get(field)) for field in fields]))
    else:
        parts.append(_safe_value(queue_health or "unavailable"))

    parts.extend(
        [
            "",
            "## Selected Metrics",
            "",
        ]
    )
    if metrics_lines:
        parts.append("```text")
        parts.extend(_redact_line(line) for line in metrics_lines)
        parts.append("```")
    else:
        parts.append("No selected metrics were captured.")

    parts.extend(
        [
            "",
            "## Observability Links",
            "",
            "- Grafana: http://localhost:3000",
            "- Prometheus: http://localhost:9090",
            "- Jaeger: http://localhost:16686",
            "",
            "## Notes",
            "",
            "Results are local-machine dependent and are intended for development pressure testing, not formal production benchmarking.",
            "Rate limiting, admission control, worker count, video size, and host CPU can all change the numbers.",
            "",
        ]
    )
    return "\n".join(parts)


def _redact_line(line: str) -> str:
    lowered = line.lower()
    if any(part in lowered for part in SENSITIVE_KEYS):
        return "[redacted sensitive metric line]"
    return line


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a Markdown benchmark report from JSON results.")
    parser.add_argument("--input", required=True, help="Input JSON result path.")
    parser.add_argument("--output", required=True, help="Output Markdown report path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    data = json.loads(input_path.read_text(encoding="utf-8"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_report(data), encoding="utf-8")
    print(f"wrote_report: {output_path}")


if __name__ == "__main__":
    main()
