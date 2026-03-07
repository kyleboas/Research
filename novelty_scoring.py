"""Novelty scoring for trend candidates.

Scores candidates by comparing them against the historical corpus of previously
seen tactical concepts. A candidate is scored higher when it is semantically
distant from what has been seen before but still supported by multiple sources.

Two complementary signals:
  1. Semantic novelty: cosine distance from nearest historical baseline embeddings
  2. Source diversity: how many independent sources mention the pattern
     (few sources = early/niche, many sources = already mainstream)

The ideal candidate for early tactical detection:
  - Semantically novel (high distance from historical baselines)
  - Supported by 2-5 independent, high-quality sources (not just one outlier)
  - Not yet broadly adopted (appears in specific teams/coaches, not everywhere)
"""

import logging
import math

import numpy as np

log = logging.getLogger("research")


def compute_novelty_score(conn, trend_text, trend_embedding, source_count=1):
    """Compute novelty score for a trend candidate.

    Args:
        conn: Database connection
        trend_text: The trend description text
        trend_embedding: Pre-computed embedding vector for the trend
        source_count: Number of independent sources supporting this trend

    Returns:
        float: Novelty score 0.0-1.0 where 1.0 = completely novel
    """
    if not trend_embedding:
        return 0.5  # neutral if we can't compute

    vec_literal = "[" + ",".join(str(v) for v in trend_embedding) + "]"

    # Find nearest historical baselines
    with conn.cursor() as cur:
        cur.execute(
            "SELECT concept, 1 - (embedding <=> %s::vector) AS similarity, "
            "occurrence_count, source_count "
            "FROM novelty_baselines "
            "ORDER BY embedding <=> %s::vector "
            "LIMIT 5",
            (vec_literal, vec_literal),
        )
        nearest = cur.fetchall()

    if not nearest:
        # No historical baselines at all — everything is novel
        return 0.95

    # Semantic novelty: inverse of max similarity to historical concepts
    max_similarity = max(row[1] for row in nearest)
    semantic_novelty = 1.0 - max(0.0, min(1.0, max_similarity))

    # Check if the closest match has been seen many times (well-established concept)
    closest = nearest[0]
    closest_occurrences = closest[2] or 1
    # High occurrence count of closest match → less novel (well-trodden territory)
    occurrence_penalty = min(0.3, math.log1p(closest_occurrences) * 0.05)

    # Source diversity signal
    # Sweet spot: 2-5 sources = early but supported. 1 source = outlier risk.
    # >10 sources = probably already mainstream.
    if source_count <= 1:
        diversity_bonus = -0.1  # single source = higher risk of noise
    elif source_count <= 5:
        diversity_bonus = 0.15  # sweet spot: early but corroborated
    elif source_count <= 10:
        diversity_bonus = 0.05  # getting mainstream
    else:
        diversity_bonus = -0.1  # widely covered = not novel

    novelty = max(0.0, min(1.0,
        semantic_novelty - occurrence_penalty + diversity_bonus
    ))

    log.info("Novelty score for '%s': %.3f (semantic=%.3f, occ_penalty=%.3f, "
             "diversity=%.3f, closest='%s' sim=%.3f seen=%d times)",
             trend_text[:60], novelty, semantic_novelty, occurrence_penalty,
             diversity_bonus, closest[0][:40] if closest[0] else "?",
             max_similarity, closest_occurrences)

    return round(novelty, 4)


def update_baseline(conn, trend_text, trend_embedding, source_count=1):
    """Add or update a concept in the novelty baseline corpus.

    Called after a trend candidate is processed (reported or evaluated),
    so future occurrences of similar concepts register as less novel.
    """
    if not trend_embedding:
        return

    vec_literal = "[" + ",".join(str(v) for v in trend_embedding) + "]"

    # Check if a similar concept already exists (cosine similarity > 0.85)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, concept, 1 - (embedding <=> %s::vector) AS similarity, "
            "occurrence_count, source_count "
            "FROM novelty_baselines "
            "WHERE 1 - (embedding <=> %s::vector) > 0.85 "
            "ORDER BY embedding <=> %s::vector "
            "LIMIT 1",
            (vec_literal, vec_literal, vec_literal),
        )
        existing = cur.fetchone()

    if existing:
        # Update existing baseline
        baseline_id = existing[0]
        new_occ = (existing[3] or 1) + 1
        new_src = max(existing[4] or 1, source_count)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE novelty_baselines SET "
                "occurrence_count = %s, source_count = %s, last_seen = NOW() "
                "WHERE id = %s",
                (new_occ, new_src, baseline_id),
            )
        conn.commit()
        log.debug("Updated novelty baseline #%d: '%s' (occurrences=%d)",
                  baseline_id, existing[1][:40], new_occ)
    else:
        # Insert new baseline
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO novelty_baselines (concept, embedding, source_count) "
                "VALUES (%s, %s::vector, %s)",
                (trend_text[:500], vec_literal, source_count),
            )
        conn.commit()
        log.debug("Added new novelty baseline: '%s'", trend_text[:60])


def score_tactical_pattern_novelty(conn, patterns, embed_fn):
    """Score novelty for a batch of tactical patterns.

    Takes extracted tactical patterns, embeds their action descriptions,
    and compares against the historical baseline to find genuinely new
    tactical behaviors.

    Args:
        conn: Database connection
        patterns: List of pattern dicts from tactical_extraction
        embed_fn: Function to compute embeddings (list[str] -> list[list[float]])

    Returns:
        List of (pattern, novelty_score) tuples, sorted by novelty descending
    """
    if not patterns:
        return []

    # Build concise descriptions for each pattern
    descriptions = []
    for p in patterns:
        desc = f"{p.get('actor', 'player')} {p['action']}"
        if p.get('zones'):
            desc += f" in {p['zones'][0]}"
        if p.get('phase'):
            desc += f" during {p['phase']}"
        descriptions.append(desc)

    # Batch embed
    vectors = embed_fn(descriptions)
    if not vectors:
        return [(p, 0.5) for p in patterns]

    # Score each pattern
    scored = []
    for pattern, desc, vec in zip(patterns, descriptions, vectors):
        novelty = compute_novelty_score(conn, desc, vec)
        scored.append((pattern, novelty))

    # Sort by novelty descending
    scored.sort(key=lambda x: -x[1])
    return scored
