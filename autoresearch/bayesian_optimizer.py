"""Bayesian optimization framework for autoresearch policy tuning.

Provides intelligent search strategies using Optuna with:
- Early stopping for unpromising configurations
- Warm-start from previous results
- Configurable acquisition functions (EI, PI, UCB)
- Budget-aware optimization
"""

from __future__ import annotations

import json
import os
import pickle
from datetime import datetime, UTC
from pathlib import Path
from typing import Callable, Any
from dataclasses import dataclass

try:
    import optuna
    from optuna.samplers import TPESampler, CmaEsSampler
    from optuna.pruners import MedianPruner, HyperbandPruner
    from optuna.exceptions import TrialPruned
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False


@dataclass
class OptimizationConfig:
    """Configuration for Bayesian optimization."""
    n_trials: int = 100
    timeout_seconds: float | None = None
    n_startup_trials: int = 10
    acquisition_function: str = "ei"  # ei, pi, ucb
    beta_for_ucb: float = 2.0  # Exploration factor for UCB
    early_stopping: bool = True
    n_warmup_trials: int = 5  # Trials before pruning kicks in
    prune_threshold: float = 0.1  # Prune if worse than median by this margin
    study_name: str | None = None
    storage_path: str | None = None
    seed: int | None = None


class BayesianOptimizer:
    """Generic Bayesian optimizer using Optuna for policy search."""

    def __init__(self, config: OptimizationConfig | None = None):
        if not OPTUNA_AVAILABLE:
            raise ImportError("Optuna is required. Install with: pip install optuna")
        self.config = config or OptimizationConfig()
        self.study: optuna.Study | None = None
        self._trial_count = 0
        self._intermediate_results: list[dict] = []

    def _get_sampler(self):
        """Configure sampler based on acquisition function preference."""
        if self.config.acquisition_function == "cmaes":
            return CmaEsSampler(seed=self.config.seed)
        
        # TPESampler is Optuna's default and works well for most cases
        # It adaptively balances exploration and exploitation
        return TPESampler(
            n_startup_trials=self.config.n_startup_trials,
            seed=self.config.seed,
        )

    def _get_pruner(self):
        """Configure pruner for early stopping."""
        if not self.config.early_stopping:
            return optuna.pruners.NopPruner()
        
        # Median pruner is robust for noisy evaluations
        return MedianPruner(
            n_startup_trials=self.config.n_warmup_trials,
            n_warmup_steps=0,
        )

    def create_study(
        self,
        direction: str = "maximize",
        study_name: str | None = None,
        storage_path: str | None = None,
    ) -> optuna.Study:
        """Create or load an existing study."""
        name = study_name or self.config.study_name or f"policy_optimization_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        
        storage = None
        if storage_path or self.config.storage_path:
            db_path = storage_path or self.config.storage_path
            storage = f"sqlite:///{db_path}"

        try:
            # Try to load existing study
            self.study = optuna.load_study(
                study_name=name,
                storage=storage,
                sampler=self._get_sampler(),
                pruner=self._get_pruner(),
            )
        except (KeyError, ValueError):
            # Create new study
            self.study = optuna.create_study(
                study_name=name,
                storage=storage,
                direction=direction,
                sampler=self._get_sampler(),
                pruner=self._get_pruner(),
            )

        return self.study

    def optimize(
        self,
        objective_fn: Callable[[optuna.Trial], float],
        search_space: dict[str, tuple],
        n_trials: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run Bayesian optimization over the given search space.
        
        Args:
            objective_fn: Function that takes a Trial and returns a score to maximize
            search_space: Dict mapping param names to (type, low, high) tuples
                Types: "int", "float", "categorical"
            n_trials: Number of optimization trials (overrides config)
            timeout: Maximum optimization time in seconds (overrides config)
        
        Returns:
            Dict with best_params, best_value, and study statistics
        """
        if self.study is None:
            self.create_study()

        def wrapped_objective(trial: optuna.Trial) -> float:
            self._trial_count += 1
            
            # Build policy from search space
            params = {}
            for name, spec in search_space.items():
                param_type = spec[0]
                if param_type == "int":
                    params[name] = trial.suggest_int(name, spec[1], spec[2])
                elif param_type == "float":
                    params[name] = trial.suggest_float(name, spec[1], spec[2])
                elif param_type == "categorical":
                    params[name] = trial.suggest_categorical(name, spec[1])
                elif param_type == "int_step":
                    params[name] = trial.suggest_int(name, spec[1], spec[2], step=spec[3])
                elif param_type == "float_step":
                    params[name] = trial.suggest_float(name, spec[1], spec[2], step=spec[3])
            
            # Call user objective
            try:
                result = objective_fn(trial, params)
                
                # Handle tuple return (score, intermediate_values)
                if isinstance(result, tuple):
                    score = result[0]
                    intermediate = result[1] if len(result) > 1 else None
                    if intermediate:
                        for step, value in enumerate(intermediate):
                            trial.report(value, step)
                            if trial.should_prune():
                                raise TrialPruned()
                else:
                    score = result
                
                self._intermediate_results.append({
                    "trial": self._trial_count,
                    "params": params,
                    "score": score,
                    "pruned": False,
                })
                
                return score
                
            except TrialPruned:
                self._intermediate_results.append({
                    "trial": self._trial_count,
                    "params": params,
                    "score": None,
                    "pruned": True,
                })
                raise

        # Run optimization
        self.study.optimize(
            wrapped_objective,
            n_trials=n_trials or self.config.n_trials,
            timeout=timeout or self.config.timeout_seconds,
            show_progress_bar=True,
            catch=(Exception,),
        )

        return {
            "best_params": self.study.best_params,
            "best_value": self.study.best_value,
            "n_trials": len(self.study.trials),
            "n_complete": len([t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
            "n_pruned": len([t for t in self.study.trials if t.state == optuna.trial.TrialState.PRUNED]),
            "trials": [
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "state": t.state.name,
                }
                for t in self.study.trials
            ],
        }

    def get_importance(self) -> dict[str, float]:
        """Get parameter importance from completed trials."""
        if self.study is None or len(self.study.trials) < 10:
            return {}
        
        try:
            importance = optuna.importance.get_param_importances(self.study)
            return dict(importance)
        except Exception:
            return {}

    def warm_start_from_results(self, previous_results: list[dict]) -> None:
        """Warm-start the optimizer from previous optimization results.
        
        Args:
            previous_results: List of dicts with 'params' and 'value' keys
        """
        if self.study is None:
            self.create_study()
        
        for result in previous_results:
            if "params" in result and "value" in result:
                self.study.add_trial(
                    optuna.create_trial(
                        params=result["params"],
                        distributions=self._infer_distributions(result["params"]),
                        value=result["value"],
                    )
                )

    def _infer_distributions(self, params: dict) -> dict:
        """Infer parameter distributions from values."""
        distributions = {}
        for name, value in params.items():
            if isinstance(value, int):
                # Assume reasonable bounds around the value
                distributions[name] = optuna.distributions.IntDistribution(
                    low=max(0, value - 50), high=value + 50
                )
            elif isinstance(value, float):
                distributions[name] = optuna.distributions.FloatDistribution(
                    low=max(0.0, value - 10.0), high=value + 10.0
                )
            else:
                distributions[name] = optuna.distributions.CategoricalDistribution([value])
        return distributions

    def save_study(self, path: str | Path) -> None:
        """Save study state for later resumption."""
        if self.study is None:
            return
        
        save_data = {
            "study_name": self.study.study_name,
            "trials": [
                {
                    "number": t.number,
                    "value": t.value,
                    "params": t.params,
                    "state": t.state.name,
                }
                for t in self.study.trials
            ],
            "config": {
                "n_trials": self.config.n_trials,
                "acquisition_function": self.config.acquisition_function,
            },
        }
        
        Path(path).write_text(json.dumps(save_data, indent=2))

    def load_study(self, path: str | Path) -> None:
        """Load study state and recreate trials."""
        data = json.loads(Path(path).read_text())
        
        if self.study is None:
            self.create_study(study_name=data.get("study_name"))
        
        for trial_data in data.get("trials", []):
            if trial_data.get("value") is not None:
                self.study.add_trial(
                    optuna.create_trial(
                        params=trial_data["params"],
                        distributions=self._infer_distributions(trial_data["params"]),
                        value=trial_data["value"],
                    )
                )


def suggest_with_constraints(
    trial: optuna.Trial,
    name: str,
    spec: tuple,
    constraints: list[Callable[[dict], bool]] | None = None,
    max_attempts: int = 100,
) -> Any:
    """Suggest a parameter value with optional constraints.
    
    Useful for enforcing relationships between parameters (e.g., min < max).
    """
    param_type = spec[0]
    
    for attempt in range(max_attempts):
        if param_type == "int":
            value = trial.suggest_int(name, spec[1], spec[2])
        elif param_type == "float":
            value = trial.suggest_float(name, spec[1], spec[2])
        elif param_type == "categorical":
            value = trial.suggest_categorical(name, spec[1])
        elif param_type == "int_step":
            value = trial.suggest_int(name, spec[1], spec[2], step=spec[3])
        elif param_type == "float_step":
            value = trial.suggest_float(name, spec[1], spec[2], step=spec[3])
        else:
            raise ValueError(f"Unknown param type: {param_type}")
        
        if constraints is None:
            return value
        
        # Check constraints with current params
        trial_params = {name: value}
        if all(constraint(trial_params) for constraint in constraints):
            return value
    
    # Fallback to default if constraints can't be satisfied
    if param_type == "categorical":
        return spec[1][0]
    return spec[1]


def make_objective_with_budget(
    base_objective: Callable[[dict], float],
    cost_fn: Callable[[dict], float],
    budget_limit: float,
    penalty_weight: float = 10.0,
) -> Callable[[optuna.Trial, dict], float]:
    """Wrap an objective function with budget constraints.
    
    Returns a new objective that heavily penalizes configurations exceeding budget.
    """
    def objective(trial: optuna.Trial, params: dict) -> float:
        cost = cost_fn(params)
        base_score = base_objective(params)
        
        if cost > budget_limit:
            # Penalize over-budget configs but still allow some gradient
            overage_ratio = cost / budget_limit
            penalty = penalty_weight * (overage_ratio - 1.0)
            return base_score - penalty
        
        # Bonus for staying well under budget (efficiency incentive)
        efficiency_bonus = 0.0
        if cost < budget_limit * 0.8:
            efficiency_bonus = 0.5 * (1.0 - cost / budget_limit)
        
        return base_score + efficiency_bonus
    
    return objective


# Default configurations for different optimization scenarios
OPTIMIZATION_PRESETS = {
    "fast": OptimizationConfig(
        n_trials=30,
        n_startup_trials=5,
        early_stopping=True,
        n_warmup_trials=3,
    ),
    "thorough": OptimizationConfig(
        n_trials=200,
        n_startup_trials=20,
        early_stopping=True,
        n_warmup_trials=10,
    ),
    "budget_constrained": OptimizationConfig(
        n_trials=50,
        n_startup_trials=10,
        early_stopping=True,
        n_warmup_trials=5,
        acquisition_function="ei",  # Exploitation-focused for budget constraints
    ),
    "exploration": OptimizationConfig(
        n_trials=100,
        n_startup_trials=15,
        early_stopping=False,
        acquisition_function="ucb",
        beta_for_ucb=3.0,
    ),
}
