import unittest
import json
import os
import tempfile
from pathlib import Path

from detect_policy import (
    DEFAULT_POLICY,
    compute_final_score,
    load_policy,
    novelty_adjustment,
    passes_report_gate,
    save_policy,
    source_diversity_adjustment,
    classify_source_authority,
    is_weak_signal,
    authority_adjustment,
    score_breakdown,
)


class DetectPolicyTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DETECT_POLICY_PATH", None)

    def test_novelty_adjustment_is_centered_on_half(self):
        self.assertEqual(novelty_adjustment(None), 0)
        self.assertEqual(novelty_adjustment(0.5), 0)
        self.assertGreater(novelty_adjustment(0.8), 0)
        self.assertLess(novelty_adjustment(0.2), 0)

    def test_source_diversity_penalizes_single_source_candidates(self):
        self.assertEqual(source_diversity_adjustment(1), -12)
        self.assertEqual(source_diversity_adjustment(3), 3)  # few_sources_bonus
        self.assertEqual(source_diversity_adjustment(6), 2)  # several_sources_bonus
        self.assertEqual(source_diversity_adjustment(12), -6)

    def test_compute_final_score_combines_all_signals(self):
        self.assertEqual(
            compute_final_score(
                base_score=50,
                novelty_score=0.7,  # (0.7 - 0.5) * 30 = +6
                feedback_adjustment=5,
                source_diversity=3,  # few_sources_bonus = +3
            ),
            64,  # 50 + 6 + 5 + 3 = 64
        )

    def test_report_gate_requires_score_and_source_support(self):
        self.assertTrue(
            passes_report_gate(final_score=67, source_diversity=3, min_score=40, min_sources=2)
        )
        self.assertFalse(
            passes_report_gate(final_score=67, source_diversity=1, min_score=40, min_sources=2)
        )
        self.assertFalse(
            passes_report_gate(final_score=35, source_diversity=3, min_score=40, min_sources=2)
        )

    def test_load_policy_reads_overrides_from_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.json"
            policy_path.write_text(json.dumps({"novelty_weight": 40, "report_min_score": 55}))
            os.environ["DETECT_POLICY_PATH"] = str(policy_path)

            policy = load_policy()

        self.assertEqual(policy["novelty_weight"], 40)
        self.assertEqual(policy["report_min_score"], 55)
        self.assertEqual(policy["report_min_sources"], DEFAULT_POLICY["report_min_sources"])

    def test_save_policy_writes_merged_policy_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.json"
            os.environ["DETECT_POLICY_PATH"] = str(policy_path)

            saved_path = save_policy({"single_source_penalty": -20})
            payload = json.loads(saved_path.read_text())

        self.assertEqual(payload["single_source_penalty"], -20)
        self.assertEqual(payload["few_sources_bonus"], DEFAULT_POLICY["few_sources_bonus"])

    def test_report_gate_uses_policy_defaults_when_not_explicitly_passed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            policy_path = Path(tmpdir) / "policy.json"
            policy_path.write_text(json.dumps({"report_min_score": 55, "report_min_sources": 3}))
            os.environ["DETECT_POLICY_PATH"] = str(policy_path)

            self.assertTrue(passes_report_gate(final_score=60, source_diversity=3))
            self.assertFalse(passes_report_gate(final_score=54, source_diversity=3))
            self.assertFalse(passes_report_gate(final_score=60, source_diversity=2))

    # ---- Source Qualification Policy Tests ----

    def test_classify_source_authority_identifies_high_authority(self):
        # Manager quotes
        self.assertEqual(classify_source_authority("Manager interview with Pep Guardiola"), "high_authority")
        self.assertEqual(classify_source_authority("Head coach comments"), "high_authority")
        self.assertEqual(classify_source_authority("Manager quotes from press conference"), "high_authority")
        self.assertEqual(classify_source_authority("Coach interview after match"), "high_authority")
        
        # Official statements
        self.assertEqual(classify_source_authority("Official club statement"), "high_authority")
        self.assertEqual(classify_source_authority("Club announcement"), "high_authority")
        self.assertEqual(classify_source_authority("Official announcement: New signing"), "high_authority")
        self.assertEqual(classify_source_authority("Press release from club"), "high_authority")
        
        # Verified accounts
        self.assertEqual(classify_source_authority("Official Twitter account"), "high_authority")
        self.assertEqual(classify_source_authority("Verified account @ManUtd"), "high_authority")
        self.assertEqual(classify_source_authority("Club Twitter update"), "high_authority")

    def test_classify_source_authority_identifies_standard(self):
        self.assertEqual(classify_source_authority("Random sports blog"), "standard")
        self.assertEqual(classify_source_authority("Transfer rumors website"), "standard")
        self.assertEqual(classify_source_authority("Fan forum discussion"), "standard")
        self.assertEqual(classify_source_authority(""), "standard")
        self.assertEqual(classify_source_authority("ESPN Article"), "standard")

    def test_is_weak_signal_single_non_authority(self):
        sources = [{"source_id": 1, "title": "Random blog post"}]
        result = is_weak_signal(1, sources)
        
        self.assertTrue(result["is_weak"])
        self.assertEqual(result["reason"], "single non-authority source")
        self.assertEqual(result["authority_classification"], "standard")

    def test_is_weak_signal_single_authority(self):
        sources = [{"source_id": 1, "title": "Manager interview with head coach"}]
        result = is_weak_signal(1, sources)
        
        self.assertFalse(result["is_weak"])
        self.assertEqual(result["reason"], "single high-authority source")
        self.assertEqual(result["authority_classification"], "high_authority")

    def test_is_weak_signal_multiple_sources(self):
        sources = [
            {"source_id": 1, "title": "Random blog post"},
            {"source_id": 2, "title": "Another blog"},
            {"source_id": 3, "title": "Third source"},
        ]
        result = is_weak_signal(3, sources)
        
        self.assertFalse(result["is_weak"])
        self.assertEqual(result["reason"], "multiple sources")
        self.assertIsNone(result["authority_classification"])

    def test_is_weak_signal_no_sources(self):
        # Single source but no source details provided
        result = is_weak_signal(1, None)
        
        self.assertTrue(result["is_weak"])
        self.assertEqual(result["reason"], "single non-authority source")
        self.assertEqual(result["authority_classification"], "standard")

    def test_authority_adjustment_single_high_authority(self):
        sources = [{"source_id": 1, "title": "Official club statement"}]
        adj = authority_adjustment(1, sources)
        
        self.assertEqual(adj, DEFAULT_POLICY["high_authority_single_source_bonus"])

    def test_authority_adjustment_single_standard(self):
        sources = [{"source_id": 1, "title": "Random blog post"}]
        adj = authority_adjustment(1, sources)
        
        self.assertEqual(adj, 0)

    def test_authority_adjustment_multiple_sources(self):
        sources = [
            {"source_id": 1, "title": "Official club statement"},
            {"source_id": 2, "title": "Another official statement"},
        ]
        adj = authority_adjustment(2, sources)
        
        # Authority adjustment only applies to single sources
        self.assertEqual(adj, 0)

    def test_authority_adjustment_no_sources(self):
        adj = authority_adjustment(1, None)
        
        # No sources means not high authority
        self.assertEqual(adj, 0)

    def test_score_breakdown_includes_weak_signal(self):
        sources = [{"source_id": 1, "title": "Random blog"}]
        breakdown = score_breakdown(
            base_score=60,
            source_diversity=1,
            sources=sources,
        )
        
        self.assertTrue(breakdown["weak_signal"])
        self.assertEqual(breakdown["weak_signal_reason"], "single non-authority source")
        self.assertEqual(breakdown["weak_signal_penalty"], DEFAULT_POLICY["weak_signal_penalty"])
        self.assertEqual(breakdown["authority_classification"], "standard")
        self.assertEqual(breakdown["authority_adjustment"], 0)

    def test_score_breakdown_high_authority_exception(self):
        sources = [{"source_id": 1, "title": "Manager interview"}]
        breakdown = score_breakdown(
            base_score=60,
            source_diversity=1,
            sources=sources,
        )
        
        self.assertFalse(breakdown["weak_signal"])
        self.assertEqual(breakdown["weak_signal_reason"], "single high-authority source")
        self.assertEqual(breakdown["weak_signal_penalty"], 0)
        self.assertEqual(breakdown["authority_classification"], "high_authority")
        self.assertEqual(breakdown["authority_adjustment"], DEFAULT_POLICY["high_authority_single_source_bonus"])

    def test_score_breakdown_multiple_sources_not_weak(self):
        sources = [
            {"source_id": 1, "title": "Random blog"},
            {"source_id": 2, "title": "Another blog"},
        ]
        breakdown = score_breakdown(
            base_score=60,
            source_diversity=2,
            sources=sources,
        )
        
        self.assertFalse(breakdown["weak_signal"])
        self.assertEqual(breakdown["weak_signal_reason"], "multiple sources")
        self.assertEqual(breakdown["weak_signal_penalty"], 0)

    def test_passes_report_gate_with_weak_signal(self):
        # Weak signals need higher score to pass (normal min is 45, weak needs 55)
        # Non-weak signal with score 50 should pass
        self.assertTrue(passes_report_gate(
            final_score=50,
            source_diversity=2,
            weak_signal=False,
            min_score=45,
            min_sources=2,
        ))
        
        # Weak signal with score 50 should fail (needs 55)
        self.assertFalse(passes_report_gate(
            final_score=50,
            source_diversity=1,
            weak_signal=True,
            min_score=45,
            min_sources=1,
        ))
        
        # Weak signal with high enough score should pass
        self.assertTrue(passes_report_gate(
            final_score=60,
            source_diversity=1,
            weak_signal=True,
            min_score=45,
            min_sources=1,
        ))

    def test_compute_final_score_with_sources(self):
        # Single non-authority source - weak signal penalty applies
        sources_weak = [{"source_id": 1, "title": "Random blog"}]
        score_weak = compute_final_score(
            base_score=60,
            source_diversity=1,
            sources=sources_weak,
        )
        # 60 - 12 (single source) - 15 (weak signal) = 33
        self.assertEqual(score_weak, 33)
        
        # Single high-authority source - bonus applies instead
        sources_authority = [{"source_id": 1, "title": "Manager interview"}]
        score_authority = compute_final_score(
            base_score=60,
            source_diversity=1,
            sources=sources_authority,
        )
        # 60 - 12 (single source) + 10 (authority bonus) = 58
        self.assertEqual(score_authority, 58)


if __name__ == "__main__":
    unittest.main()
