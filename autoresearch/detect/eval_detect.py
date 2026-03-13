#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from autoresearch.detect.evaluator import evaluate_items, load_fixture
from detect_policy import get_policy_path, load_policy

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "candidates.json"


def main():
    parser = argparse.ArgumentParser(description="Evaluate detect policy against a labeled fixture")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="Path to fixture JSON")
    parser.add_argument("--top-k", type=int, default=3, help="Precision cutoff for top-ranked items")
    args = parser.parse_args()

    items = load_fixture(args.fixture)
    policy = load_policy()
    result = evaluate_items(items, policy=policy, top_k=args.top_k)
    metrics = result["metrics"]

    print(f"fixture={Path(args.fixture).resolve()}")
    print(f"policy={get_policy_path().resolve()}")
    print(
        "labels="
        f"{metrics['labeled_items']}/{metrics['total_items']} "
        f"(positives={metrics['labeled_positive']}, negatives={metrics['labeled_negative']}, "
        f"unlabeled={metrics['unlabeled_items']})"
    )
    print(f"precision_at_{metrics['top_k']}={metrics['precision_at_k']:.4f}")
    print(f"pairwise_accuracy={metrics['pairwise_accuracy']:.4f}")
    print(f"gate_accuracy={metrics['gate_accuracy']:.4f}")
    print(f"report_recall={metrics['report_recall']:.4f}")
    print("top_ranked:")
    for item in result["ranked"][: args.top_k]:
        print(
            f"- rank={item['rank']} id={item['id']} final_score={item['final_score']} "
            f"expected={item.get('expected')} gate={item['passes_gate']} trend={item['trend']}"
        )
    print(f"FINAL_SCORE={metrics['final_score']:.2f}")


if __name__ == "__main__":
    main()
