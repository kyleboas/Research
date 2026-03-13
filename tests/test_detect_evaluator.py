import unittest

from autoresearch_detect.evaluator import evaluate_items


class DetectEvaluatorTests(unittest.TestCase):
    def test_evaluator_ignores_unlabeled_items_in_metrics(self):
        items = [
            {"id": "a", "trend": "A", "base_score": 60, "novelty_score": 0.8, "feedback_adjustment": 0, "source_diversity": 3, "expected": "report_now"},
            {"id": "b", "trend": "B", "base_score": 55, "novelty_score": 0.2, "feedback_adjustment": 0, "source_diversity": 4, "expected": "hold"},
            {"id": "c", "trend": "C", "base_score": 90, "novelty_score": 0.9, "feedback_adjustment": 0, "source_diversity": 1, "expected": None},
        ]

        result = evaluate_items(items)
        metrics = result["metrics"]

        self.assertEqual(metrics["total_items"], 3)
        self.assertEqual(metrics["labeled_items"], 2)
        self.assertEqual(metrics["unlabeled_items"], 1)
        self.assertEqual(metrics["labeled_positive"], 1)
        self.assertEqual(metrics["labeled_negative"], 1)


if __name__ == "__main__":
    unittest.main()
