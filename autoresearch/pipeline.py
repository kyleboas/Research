#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
AUTORESEARCH_ROOT = ROOT / "autoresearch"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_conn import resolve_database_conninfo
from runtime_logging import finish_run, format_duration, start_run

STEPS = [
    (
        "ingest_policy_optimize",
        [sys.executable, str(AUTORESEARCH_ROOT / "ingest" / "optimize_ingest_policy.py"), "--apply"],
    ),
    (
        "detect_policy_eval",
        [sys.executable, str(AUTORESEARCH_ROOT / "detect" / "eval_detect.py")],
    ),
    (
        "detect_policy_optimize",
        [sys.executable, str(AUTORESEARCH_ROOT / "detect" / "optimize_detect_policy.py"), "--refresh-auto", "--apply"],
    ),
    (
        "report_policy_eval",
        [sys.executable, str(AUTORESEARCH_ROOT / "report" / "eval_report.py"), "--refresh-auto"],
    ),
    (
        "report_policy_optimize",
        [sys.executable, str(AUTORESEARCH_ROOT / "report" / "optimize_report_policy.py"), "--refresh-auto", "--apply"],
    ),
]


def extract_metric(text: str, pattern: str) -> str:
    match = re.search(pattern, text or "")
    return match.group(1).strip() if match else ""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def run_step(name: str, cmd: list[str], *, conn=None, parent_run=None) -> tuple[int, str, float]:
    started_at = _utc_now()
    step_run = None
    if conn is not None and parent_run is not None:
        step_run = start_run(
            conn,
            step=name,
            trigger_source="autoresearch_pipeline",
            parent_run_id=parent_run.run_id,
            started_at=started_at,
        )
        conn.commit()

    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    finished_at = _utc_now()
    duration_seconds = max(0.0, (finished_at - started_at).total_seconds())
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    print(f"## {name}")
    print(output.strip())
    print(f"{name}_duration_seconds={duration_seconds:.3f}")
    print(f"{name}_duration_human={format_duration(duration_seconds)}")

    if conn is not None and step_run is not None:
        finish_run(
            conn,
            run=step_run,
            status="success" if proc.returncode == 0 else "failed",
            finished_at=finished_at,
            exit_code=proc.returncode,
        )
        conn.commit()

    return proc.returncode, output, duration_seconds


def main():
    conninfo, _reason = resolve_database_conninfo()
    conn = psycopg.connect(conninfo) if conninfo else None
    overall_started_at = _utc_now()
    parent_run = None
    if conn is not None:
        parent_run = start_run(
            conn,
            step="autoresearch_hourly",
            trigger_source="autoresearch_pipeline",
            started_at=overall_started_at,
        )
        conn.commit()

    summaries = {}
    durations = {}
    try:
        for name, cmd in STEPS:
            code, output, duration_seconds = run_step(name, cmd, conn=conn, parent_run=parent_run)
            durations[name] = duration_seconds
            summaries[name] = output
            if code != 0:
                total_duration_seconds = max(0.0, (_utc_now() - overall_started_at).total_seconds())
                print(f"AUTORESEARCH_STATUS=failed")
                print(f"failed_step={name}")
                print("AUTORESEARCH_TOTAL_COST_USD=0.000000")
                print(f"AUTORESEARCH_TOTAL_DURATION_SECONDS={total_duration_seconds:.3f}")
                print(f"AUTORESEARCH_TOTAL_DURATION_HUMAN={format_duration(total_duration_seconds)}")
                if conn is not None and parent_run is not None:
                    finish_run(
                        conn,
                        run=parent_run,
                        status="failed",
                        finished_at=_utc_now(),
                        exit_code=code,
                        summary={
                            "failed_step": name,
                            "component_durations": durations,
                        },
                    )
                    conn.commit()
                raise SystemExit(code)

        total_duration_seconds = max(0.0, (_utc_now() - overall_started_at).total_seconds())
        summary = {
            "ingest_policy_delta": extract_metric(summaries.get("ingest_policy_optimize", ""), r"delta=(-?\d+\.\d+)") or "0.00",
            "detect_eval_score": extract_metric(summaries.get("detect_policy_eval", ""), r"FINAL_SCORE=(\d+\.\d+)") or "0.00",
            "detect_policy_delta": extract_metric(summaries.get("detect_policy_optimize", ""), r"delta=(-?\d+\.\d+)") or "0.00",
            "report_eval_score": extract_metric(summaries.get("report_policy_eval", ""), r"FINAL_SCORE=(\d+\.\d+)") or "0.00",
            "report_policy_delta": extract_metric(summaries.get("report_policy_optimize", ""), r"delta=(-?\d+\.\d+)") or "0.00",
            "report_policy_apply_decision": extract_metric(
                summaries.get("report_policy_optimize", ""),
                r"apply_decision=([a-z_]+)",
            )
            or "unknown",
            "component_durations": {step: round(seconds, 3) for step, seconds in durations.items()},
        }

        print("AUTORESEARCH_STATUS=success")
        print("AUTORESEARCH_TOTAL_COST_USD=0.000000")
        print(f"ingest_policy_delta={summary['ingest_policy_delta']}")
        print(f"detect_eval_score={summary['detect_eval_score']}")
        print(f"detect_policy_delta={summary['detect_policy_delta']}")
        print(f"report_eval_score={summary['report_eval_score']}")
        print(f"report_policy_delta={summary['report_policy_delta']}")
        print(f"report_policy_apply_decision={summary['report_policy_apply_decision']}")
        for step_name, duration_seconds in durations.items():
            print(f"{step_name}_duration_seconds={duration_seconds:.3f}")
        print(f"AUTORESEARCH_TOTAL_DURATION_SECONDS={total_duration_seconds:.3f}")
        print(f"AUTORESEARCH_TOTAL_DURATION_HUMAN={format_duration(total_duration_seconds)}")

        if conn is not None and parent_run is not None:
            finish_run(
                conn,
                run=parent_run,
                status="success",
                finished_at=_utc_now(),
                exit_code=0,
                summary=summary,
            )
            conn.commit()
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    main()
