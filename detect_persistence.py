import hashlib
import logging
import re

from detect_policy import compute_final_score, score_breakdown

log = logging.getLogger("research")


def normalize_trend_text(trend: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (trend or "").lower()).split())


def trend_fingerprint(trend: str) -> str:
    normalized = normalize_trend_text(trend)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def upsert_trend_candidate(conn, candidate: dict, feedback_adjustment: int):
    fingerprint = trend_fingerprint(candidate["trend"])
    base_score = int(candidate["score"])
    novelty = candidate.get("novelty_score")
    source_diversity = candidate.get("source_diversity", len(candidate.get("sources") or []))
    sources = candidate.get("sources")
    
    # Compute score breakdown with source qualification
    breakdown = score_breakdown(
        base_score=base_score,
        novelty_score=novelty,
        feedback_adjustment=feedback_adjustment,
        source_diversity=source_diversity,
        sources=sources,
    )
    final_score = breakdown["final_score"]
    weak_signal = breakdown["weak_signal"]
    authority_classification = breakdown["authority_classification"]
    
    # Trajectory fields
    velocity = candidate.get("velocity_score")
    acceleration = candidate.get("acceleration_score")
    direction = candidate.get("trajectory_direction")
    early_trend = candidate.get("early_trend_score")
    trajectory_reasoning = candidate.get("trajectory_reasoning")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, status, feedback_adjustment, score, source_diversity FROM trend_candidates WHERE trend_fingerprint = %s LIMIT 1",
            (fingerprint,),
        )
        existing = cur.fetchone()
        if existing:
            candidate_id, existing_status, existing_feedback, existing_score, existing_source_diversity = existing
            stored_score = max(existing_score or 0, base_score)
            stored_diversity = max(existing_source_diversity or 0, source_diversity)
            stored_feedback = existing_feedback if existing_feedback not in (None, 0) else feedback_adjustment
            
            # Recompute with stored values
            breakdown = score_breakdown(
                base_score=stored_score,
                novelty_score=novelty,
                feedback_adjustment=stored_feedback,
                source_diversity=stored_diversity,
                sources=sources,
            )
            final_score = breakdown["final_score"]
            weak_signal = breakdown["weak_signal"]
            authority_classification = breakdown["authority_classification"]
            
            next_status = "reported" if existing_status == "reported" else "pending"
            cur.execute(
                """
                UPDATE trend_candidates
                SET trend = %s,
                    reasoning = %s,
                    score = %s,
                    feedback_adjustment = %s,
                    final_score = %s,
                    novelty_score = %s,
                    source_diversity = %s,
                    status = %s,
                    detected_at = NOW(),
                    velocity_score = %s,
                    acceleration_score = %s,
                    trajectory_direction = %s,
                    early_trend_score = %s,
                    trajectory_reasoning = %s,
                    weak_signal = %s,
                    authority_classification = %s
                WHERE id = %s
                RETURNING id, final_score
                """,
                (
                    candidate["trend"],
                    candidate.get("reasoning"),
                    stored_score,
                    stored_feedback,
                    final_score,
                    novelty,
                    stored_diversity,
                    next_status,
                    velocity,
                    acceleration,
                    direction,
                    early_trend,
                    trajectory_reasoning,
                    weak_signal,
                    authority_classification,
                    candidate_id,
                ),
            )
            row = cur.fetchone()
            return row[0], int(row[1] or final_score), stored_diversity, weak_signal, authority_classification

        # Insert new candidate
        cur.execute(
            """
            INSERT INTO trend_candidates
            (trend_fingerprint, trend, reasoning, score, feedback_adjustment, final_score, 
             novelty_score, source_diversity, velocity_score, acceleration_score, 
             trajectory_direction, early_trend_score, trajectory_reasoning, weak_signal, authority_classification)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, final_score
            """,
            (
                fingerprint,
                candidate["trend"],
                candidate.get("reasoning"),
                base_score,
                feedback_adjustment,
                final_score,
                novelty,
                source_diversity,
                velocity,
                acceleration,
                direction,
                early_trend,
                trajectory_reasoning,
                weak_signal,
                authority_classification,
            ),
        )
        row = cur.fetchone()
        return row[0], int(row[1] or final_score), source_diversity, weak_signal, authority_classification


def effective_source_diversity(stored_source_diversity: int | None, linked_source_count: int | None) -> int:
    return max(int(stored_source_diversity or 0), int(linked_source_count or 0))


def rescored_trend_candidate_values(
    *,
    base_score: int,
    feedback_adjustment: int,
    stored_source_diversity: int | None,
    linked_source_count: int | None,
    novelty_score: float | None,
    sources: list[dict] | None = None,
) -> tuple[int, int, bool, str | None]:
    source_diversity = effective_source_diversity(stored_source_diversity, linked_source_count)
    breakdown = score_breakdown(
        base_score=int(base_score),
        novelty_score=novelty_score,
        feedback_adjustment=int(feedback_adjustment or 0),
        source_diversity=source_diversity,
        sources=sources,
    )
    return source_diversity, breakdown["final_score"], breakdown["weak_signal"], breakdown["authority_classification"]


def parse_rescore_statuses(raw: str | None) -> list[str] | None:
    statuses = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return statuses or None


def persist_detect_candidates(conn, candidates: list[dict]) -> list[dict]:
    """Persist detected candidates and return list of result dicts with scores and weak_signal flags."""
    results: list[dict] = []
    with conn.cursor() as cur:
        for candidate in candidates:
            trend_candidate_id, final_score, source_diversity, weak_signal, authority_classification = upsert_trend_candidate(
                conn,
                candidate,
                int(candidate.get("feedback_adjustment", 0)),
            )
            # Store weak_signal info back on candidate for API response
            candidate["weak_signal"] = weak_signal
            candidate["authority_classification"] = authority_classification
            
            for source in candidate.get("sources") or []:
                cur.execute(
                    "INSERT INTO trend_candidate_sources (trend_candidate_id, source_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (trend_candidate_id, source["source_id"]),
                )
            results.append({
                "id": trend_candidate_id,
                "final_score": final_score,
                "source_diversity": source_diversity,
                "weak_signal": weak_signal,
                "authority_classification": authority_classification,
            })
    return results


def load_rescore_candidates(conn, *, limit: int = 0, statuses: list[str] | None = None):
    query = """
        SELECT
            tc.id,
            tc.trend,
            tc.score,
            tc.feedback_adjustment,
            COALESCE(tc.source_diversity, 0) AS stored_source_diversity,
            COUNT(tcs.source_id) AS linked_source_count,
            tc.novelty_score,
            COALESCE(tc.final_score, tc.score) AS existing_final_score,
            tc.status,
            tc.weak_signal,
            tc.authority_classification,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'source_id', s.id,
                        'title', s.title
                    ) ORDER BY s.id
                ) FILTER (WHERE s.id IS NOT NULL),
                '[]'::jsonb
            ) AS sources
        FROM trend_candidates tc
        LEFT JOIN trend_candidate_sources tcs ON tcs.trend_candidate_id = tc.id
        LEFT JOIN sources s ON s.id = tcs.source_id
    """
    params = []
    if statuses:
        placeholders = ",".join(["%s"] * len(statuses))
        query += f" WHERE tc.status IN ({placeholders})"
        params.extend(statuses)
    query += """
        GROUP BY tc.id
        ORDER BY tc.detected_at DESC, tc.id DESC
    """
    if limit and limit > 0:
        query += " LIMIT %s"
        params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def update_rescored_candidates(conn, updates: list[tuple]) -> int:
    changed = 0
    with conn.cursor() as cur:
        for (
            candidate_id,
            novelty_score,
            final_score,
            source_diversity,
            existing_novelty,
            existing_final_score,
            stored_source_diversity,
            status,
            weak_signal,
            authority_classification,
        ) in updates:
            cur.execute(
                """
                UPDATE trend_candidates
                SET novelty_score = %s,
                    final_score = %s,
                    source_diversity = %s,
                    weak_signal = %s,
                    authority_classification = %s
                WHERE id = %s
                """,
                (novelty_score, final_score, source_diversity, weak_signal, authority_classification, candidate_id),
            )
            if (
                existing_novelty is None
                or abs(float(existing_novelty) - float(novelty_score)) > 1e-6
                or int(existing_final_score) != int(final_score)
                or int(stored_source_diversity) != int(source_diversity)
            ):
                changed += 1
            log.debug(
                "Rescored trend_candidate id=%s status=%s final_score=%s novelty=%.4f source_diversity=%s weak_signal=%s",
                candidate_id,
                status,
                final_score,
                novelty_score,
                source_diversity,
                weak_signal,
            )
    return changed
