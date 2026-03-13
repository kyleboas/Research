from __future__ import annotations

import json
from pathlib import Path

from detect_policy import compute_final_score, load_policy, passes_report_gate, score_breakdown


def load_fixture(path: str | Path):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list):
        raise ValueError("fixture must be a JSON array")
    return payload


def normalize_expected(value):
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"report_now", "report", "positive"}:
        return "report_now"
    if normalized in {"hold", "skip", "negative"}:
        return "hold"
    return None


def rank_items(items):
    return sorted(
        items,
        key=lambda item: (
            -item["final_score"],
            -int(item.get("source_diversity", 0)),
            str(item.get("trend", "")).lower(),
        ),
    )


def precision_at_k(items, k):
    ranked = items[:k]
    if not ranked:
        return 0.0
    hits = sum(1 for item in ranked if item["expected"] == "report_now")
    return hits / len(ranked)


def pairwise_accuracy(items):
    positives = [item for item in items if item["expected"] == "report_now"]
    negatives = [item for item in items if item["expected"] == "hold"]
    if not positives or not negatives:
        return 0.0
    total = len(positives) * len(negatives)
    wins = 0
    for pos in positives:
        for neg in negatives:
            if pos["final_score"] > neg["final_score"]:
                wins += 1
            elif pos["final_score"] == neg["final_score"] and pos["rank"] < neg["rank"]:
                wins += 1
    return wins / total


def gate_accuracy(items):
    if not items:
        return 0.0
    correct = 0
    for item in items:
        expected_gate = item["expected"] == "report_now"
        if item["passes_gate"] == expected_gate:
            correct += 1
    return correct / len(items)


def report_recall(items):
    positives = [item for item in items if item["expected"] == "report_now"]
    if not positives:
        return 0.0
    hits = sum(1 for item in positives if item["passes_gate"])
    return hits / len(positives)


def score_items(items, policy: dict | None = None):
    params = load_policy(policy)
    scored = []
    for item in items:
        breakdown = score_breakdown(
            base_score=item["base_score"],
            novelty_score=item.get("novelty_score"),
            feedback_adjustment=item.get("feedback_adjustment", 0),
            source_diversity=item.get("source_diversity", 0),
            policy=params,
        )
        expected = normalize_expected(item.get("expected"))
        scored.append(
            {
                **item,
                **breakdown,
                "expected": expected,
                "passes_gate": passes_report_gate(
                    final_score=breakdown["final_score"],
                    source_diversity=item.get("source_diversity", 0),
                    policy=params,
                ),
            }
        )

    ranked = rank_items(scored)
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index

    labeled_ranked = [item for item in ranked if item["expected"] in {"report_now", "hold"}]
    for index, item in enumerate(labeled_ranked, start=1):
        item["labeled_rank"] = index

    return ranked, labeled_ranked


def evaluate_items(items, policy: dict | None = None, top_k: int = 3):
    ranked, labeled_ranked = score_items(items, policy=policy)
    p_at_k = precision_at_k(labeled_ranked, top_k)
    pairwise = pairwise_accuracy(labeled_ranked)
    gate = gate_accuracy(labeled_ranked)
    recall = report_recall(labeled_ranked)
    final_score = round((0.4 * p_at_k + 0.25 * pairwise + 0.2 * gate + 0.15 * recall) * 100, 2)

    labeled_positive = sum(1 for item in labeled_ranked if item["expected"] == "report_now")
    labeled_negative = sum(1 for item in labeled_ranked if item["expected"] == "hold")

    return {
        "ranked": ranked,
        "labeled_ranked": labeled_ranked,
        "metrics": {
            "precision_at_k": p_at_k,
            "pairwise_accuracy": pairwise,
            "gate_accuracy": gate,
            "report_recall": recall,
            "final_score": final_score,
            "top_k": top_k,
            "total_items": len(ranked),
            "labeled_items": len(labeled_ranked),
            "unlabeled_items": len(ranked) - len(labeled_ranked),
            "labeled_positive": labeled_positive,
            "labeled_negative": labeled_negative,
        },
    }
