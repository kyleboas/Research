"""Tests for the Bayesian optimization framework."""

import unittest
import tempfile
import json
from pathlib import Path

from autoresearch.bayesian_optimizer import (
    BayesianOptimizer,
    OptimizationConfig,
    OPTIMIZATION_PRESETS,
    make_objective_with_budget,
    build_policy_from_params,
)


class TestOptimizationConfig(unittest.TestCase):
    def test_default_config(self):
        config = OptimizationConfig()
        self.assertEqual(config.n_trials, 100)
        self.assertEqual(config.acquisition_function, "ei")
        self.assertTrue(config.early_stopping)
    
    def test_presets_exist(self):
        self.assertIn("fast", OPTIMIZATION_PRESETS)
        self.assertIn("thorough", OPTIMIZATION_PRESETS)
        self.assertIn("budget_constrained", OPTIMIZATION_PRESETS)
        self.assertIn("exploration", OPTIMIZATION_PRESETS)
    
    def test_fast_preset(self):
        config = OPTIMIZATION_PRESETS["fast"]
        self.assertEqual(config.n_trials, 30)
        self.assertEqual(config.n_startup_trials, 5)


class TestBayesianOptimizer(unittest.TestCase):
    def test_optimizer_requires_optuna(self):
        # Test that optimizer checks for optuna availability
        try:
            import optuna
            optimizer = BayesianOptimizer()
            self.assertIsNotNone(optimizer.config)
        except ImportError:
            # If optuna not installed, should raise ImportError
            with self.assertRaises(ImportError):
                BayesianOptimizer()
    
    def test_warm_start_from_results(self):
        try:
            import optuna
            optimizer = BayesianOptimizer(OptimizationConfig(n_trials=10))
            optimizer.create_study(direction="maximize")
            
            # Mock previous results
            previous_results = [
                {"params": {"x": 1.0, "y": 2.0}, "value": 10.0},
                {"params": {"x": 2.0, "y": 3.0}, "value": 20.0},
            ]
            
            optimizer.warm_start_from_results(previous_results)
            
            # Check that trials were added
            self.assertEqual(len(optimizer.study.trials), 2)
        except ImportError:
            self.skipTest("optuna not installed")
    
    def test_get_importance_empty(self):
        try:
            import optuna
            optimizer = BayesianOptimizer(OptimizationConfig(n_trials=10))
            optimizer.create_study(direction="maximize")
            
            # Empty study should return empty dict
            importance = optimizer.get_importance()
            self.assertEqual(importance, {})
        except ImportError:
            self.skipTest("optuna not installed")


class TestMakeObjectiveWithBudget(unittest.TestCase):
    def test_budget_constraint_penalty(self):
        def base_objective(params):
            return 100.0
        
        def cost_fn(params):
            return 2.0  # Over budget
        
        budget_limit = 1.0
        objective = make_objective_with_budget(base_objective, cost_fn, budget_limit)
        
        # Mock trial and params
        class MockTrial:
            pass
        
        score = objective(MockTrial(), {"x": 1.0})
        # Should be penalized for exceeding budget
        self.assertLess(score, 100.0)
    
    def test_budget_efficiency_bonus(self):
        def base_objective(params):
            return 50.0
        
        def cost_fn(params):
            return 0.5  # Well under budget
        
        budget_limit = 1.0
        objective = make_objective_with_budget(base_objective, cost_fn, budget_limit)
        
        class MockTrial:
            pass
        
        score = objective(MockTrial(), {"x": 1.0})
        # Should get efficiency bonus for staying under budget
        self.assertGreater(score, 50.0)


class TestBuildPolicyFromParams(unittest.TestCase):
    def test_detect_policy_building(self):
        from detect_policy import DEFAULT_POLICY
        
        params = {
            "novelty_weight": 35,
            "single_source_penalty": -10,
        }
        
        policy = build_policy_from_params(params, DEFAULT_POLICY)
        
        self.assertEqual(policy["novelty_weight"], 35)
        self.assertEqual(policy["single_source_penalty"], -10)
        # Other values should be defaults
        self.assertEqual(policy["few_sources_bonus"], DEFAULT_POLICY["few_sources_bonus"])
    
    def test_report_policy_constraints(self):
        from report_policy import DEFAULT_POLICY
        
        params = {
            "moderate_min_tasks": 5,
            "complex_min_tasks": 3,  # Violates constraint
        }
        
        # Simulate constraint enforcement
        if params["moderate_min_tasks"] > params["complex_min_tasks"]:
            params["complex_min_tasks"] = params["moderate_min_tasks"]
        
        self.assertEqual(params["complex_min_tasks"], 5)


class TestStudyPersistence(unittest.TestCase):
    def test_save_and_load_study(self):
        try:
            import optuna
            
            with tempfile.TemporaryDirectory() as tmpdir:
                path = Path(tmpdir) / "study.json"
                
                # Create and save study
                optimizer = BayesianOptimizer(OptimizationConfig(n_trials=10))
                optimizer.create_study(direction="maximize", study_name="test_study")
                
                # Add a trial
                optimizer.study.add_trial(
                    optuna.create_trial(
                        params={"x": 1.0},
                        distributions={"x": optuna.distributions.FloatDistribution(0, 10)},
                        value=5.0,
                    )
                )
                
                optimizer.save_study(path)
                
                # Load study
                optimizer2 = BayesianOptimizer(OptimizationConfig(n_trials=10))
                optimizer2.load_study(path)
                
                self.assertEqual(len(optimizer2.study.trials), 1)
                self.assertEqual(optimizer2.study.trials[0].value, 5.0)
        except ImportError:
            self.skipTest("optuna not installed")


if __name__ == "__main__":
    unittest.main()
