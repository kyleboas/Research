#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from db_conn import resolve_database_conninfo


def infer_expected(status: str | None, feedback_total: int, source_diversity: int) -> tuple[str | None, str]:
    normalized_status = (status or "").strip().lower()
    if normalized_status == "reported":
        return "report_now", "candidate_was_reported"
    if feedback_total <= -5:
        return "hold", "net_negative_feedback"
    if feedback_total >= 5 and int(source_diversity or 0) >= 2:
        return "report_now", "net_positive_feedback_with_support"
    if normalized_status == "needs_more_evidence" and int(source_diversity or 0) <= 1:
        return "hold", "single_source_needs_more_evidence"
    return None, ""


def export_snapshot(output_path: Path, limit: int, label_mode: str = "manual"):
    conninfo, reason = resolve_database_conninfo()
    if not conninfo:
        raise SystemExit(f"database_unavailable:{reason}")

    with psycopg.connect(conninfo) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    tc.id,
                    tc.trend,
                    tc.score,
                    tc.final_score,
                    tc.novelty_score,
                    tc.feedback_adjustment,
                    COALESCE(tc.source_diversity, 0),
                    tc.status,
                    tc.detected_at,
                    COALESCE(SUM(tf.feedback_value), 0) AS feedback_total,
                    COUNT(tf.id) FILTER (WHERE tf.feedback_value > 0) AS positive_feedback_count,
                    COUNT(tf.id) FILTER (WHERE tf.feedback_value < 0) AS negative_feedback_count,
                    COUNT(tcs.source_id) AS linked_source_count
                FROM trend_candidates tc
                LEFT JOIN trend_feedback tf ON tf.trend_candidate_id = tc.id
                LEFT JOIN trend_candidate_sources tcs ON tcs.trend_candidate_id = tc.id
                GROUP BY tc.id
                ORDER BY COALESCE(tc.final_score, tc.score) DESC, tc.detected_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    payload = []
    for row in rows:
        expected = None
        label_reason = ""
        if label_mode == "auto":
            expected, label_reason = infer_expected(row[7], row[9] or 0, row[6] or 0)

        payload.append(
            {
                "id": row[0],
                "trend": row[1],
                "base_score": row[2],
                "current_final_score": row[3],
                "novelty_score": row[4],
                "feedback_adjustment": row[5],
                "source_diversity": row[6],
                "status": row[7],
                "detected_at": row[8].isoformat() if row[8] else None,
                "feedback_total": row[9] or 0,
                "positive_feedback_count": row[10] or 0,
                "negative_feedback_count": row[11] or 0,
                "linked_source_count": row[12] or 0,
                "expected": expected,
                "label_reason": label_reason,
                "notes": "",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(output_path)


def main():
    parser = argparse.ArgumentParser(description="Export trend candidates for offline detect-policy labeling")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent / "fixtures" / "live_candidates.json"),
        help="Path to write the JSON snapshot",
    )
    parser.add_argument("--limit", type=int, default=100, help="Maximum number of candidates to export")
    parser.add_argument(
        "--label-mode",
        choices=["manual", "auto"],
        default="manual",
        help="manual leaves labels blank; auto infers obvious report_now/hold labels from status and feedback",
    )
    args = parser.parse_args()
    export_snapshot(Path(args.output), args.limit, label_mode=args.label_mode)


if __name__ == "__main__":
    main()
