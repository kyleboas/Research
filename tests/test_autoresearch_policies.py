import unittest

from autoresearch.ingest.optimize_ingest_policy import score_policy as score_ingest_policy
from autoresearch.report.optimize_report_policy import simulate_policy


class AutoresearchPolicyTests(unittest.TestCase):
    def test_ingest_policy_scoring_prefers_overlap_near_observed_lag(self):
        observations = {
            "rss_p90_lag_hours": 24.0,
            "youtube_p90_lag_hours": 24.0,
            "avg_daily_sources": 20.0,
            "sample_days": 14,
        }
        near_policy = {
            "rss_overlap_seconds": 24 * 60 * 60,
            "youtube_overlap_seconds": 24 * 60 * 60,
            "detect_min_new_sources": 2,
        }
        far_policy = {
            "rss_overlap_seconds": 72 * 60 * 60,
            "youtube_overlap_seconds": 6 * 60 * 60,
            "detect_min_new_sources": 8,
        }

        self.assertGreater(score_ingest_policy(near_policy, observations), score_ingest_policy(far_policy, observations))

    def test_report_policy_simulation_trades_cost_for_quality(self):
        items = [
            {
                "title": "Report A",
                "section_coverage": 0.70,
                "citation_validity": 0.95,
                "citation_density": 0.60,
                "source_diversity_score": 0.55,
                "sources_section_coverage": 0.70,
                "counterevidence_coverage": 0.40,
                "thoroughness": 0.55,
                "citation_count": 10,
                "invalid_citation_count": 0,
                "word_count": 1400,
            }
        ]
        base_policy = {
            "max_research_rounds": 2,
            "moderate_min_tasks": 3,
            "complex_min_tasks": 5,
            "subagent_search_limit": 24,
            "subagent_max_tokens": 7000,
            "synthesis_max_tokens": 16000,
            "revision_max_tokens": 16000,
            "optimize_topic_limit": 2,
            "max_report_llm_cost_usd": 1.0,
        }
        cheaper_policy = {
            **base_policy,
            "moderate_min_tasks": 2,
            "complex_min_tasks": 4,
            "subagent_search_limit": 16,
            "subagent_max_tokens": 5000,
            "synthesis_max_tokens": 12000,
            "revision_max_tokens": 12000,
        }
        stronger_policy = {
            **base_policy,
            "max_research_rounds": 3,
            "moderate_min_tasks": 4,
            "complex_min_tasks": 6,
            "subagent_search_limit": 30,
            "subagent_max_tokens": 8000,
            "synthesis_max_tokens": 18000,
            "revision_max_tokens": 18000,
        }

        cheaper = simulate_policy(items, base_policy=base_policy, candidate_policy=cheaper_policy)
        stronger = simulate_policy(items, base_policy=base_policy, candidate_policy=stronger_policy)

        self.assertLess(cheaper["estimated_cost_per_report"], stronger["estimated_cost_per_report"])
        self.assertLessEqual(cheaper["average_score"], stronger["average_score"])


if __name__ == "__main__":
    unittest.main()
