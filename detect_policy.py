from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_POLICY = {
    "novelty_center": 0.5,
    "novelty_weight": 30,
    "single_source_penalty": -12,
    "few_sources_bonus": 3,
    "several_sources_bonus": 2,
    "many_sources_penalty": -6,
    "few_sources_max": 4,
    "several_sources_max": 8,
    "report_min_score": 45,
    "report_min_sources": 2,
    # Trajectory-based early-trend detection
    "early_trend_min_score": 0.5,
    "early_trend_velocity_weight": 0.35,
    "early_trend_acceleration_weight": 0.25,
    "early_trend_novelty_weight": 0.4,
    "trajectory_velocity_threshold": 0.5,
    "trajectory_acceleration_threshold": 0.1,
    # Source qualification policy
    "weak_signal_penalty": -15,
    "high_authority_single_source_bonus": 10,
}

_POLICY_ENV_VAR = "DETECT_POLICY_PATH"
_DEFAULT_POLICY_PATH = Path(__file__).with_name("detect_policy_config.json")

# High-authority source patterns for context-check exceptions
HIGH_AUTHORITY_PATTERNS = [
    # Manager quotes
    "manager",
    "head coach",
    "manager quotes",
    "manager comments",
    "coach interview",
    "coach comments",
    # Official club statements
    "official statement",
    "club statement",
    "official announcement",
    "club announcement",
    "press release",
    # Verified club accounts (when source titles contain these)
    "verified twitter",
    "official twitter",
    "club twitter",
    "verified account",
]


def get_policy_path() -> Path:
    raw = (os.environ.get(_POLICY_ENV_VAR) or "").strip()
    return Path(raw) if raw else _DEFAULT_POLICY_PATH


def load_policy(overrides: dict | None = None) -> dict:
    policy = dict(DEFAULT_POLICY)
    policy_path = get_policy_path()

    try:
        loaded = json.loads(policy_path.read_text())
    except FileNotFoundError:
        loaded = {}
    except json.JSONDecodeError:
        loaded = {}

    for key, default_value in DEFAULT_POLICY.items():
        if key not in loaded:
            continue
        try:
            policy[key] = type(default_value)(loaded[key])
        except (TypeError, ValueError):
            continue

    if overrides:
        for key, value in overrides.items():
            if key in DEFAULT_POLICY and value is not None:
                policy[key] = type(DEFAULT_POLICY[key])(value)

    return policy


def save_policy(policy: dict, path: str | Path | None = None) -> Path:
    target = Path(path) if path else get_policy_path()
    merged = load_policy(policy)
    target.write_text(json.dumps(merged, indent=2) + "\n")
    return target


def clamp_score(value: int | float) -> int:
    return max(0, min(100, int(round(value))))


def novelty_adjustment(novelty_score: float | None, policy: dict | None = None) -> int:
    if novelty_score is None:
        return 0
    params = load_policy(policy)
    centered = float(novelty_score) - float(params["novelty_center"])
    return int(round(centered * float(params["novelty_weight"])))


def source_diversity_adjustment(source_diversity: int | None, policy: dict | None = None) -> int:
    params = load_policy(policy)
    count = int(source_diversity or 0)
    if count <= 1:
        return int(params["single_source_penalty"])
    if count <= int(params["few_sources_max"]):
        return int(params["few_sources_bonus"])
    if count <= int(params["several_sources_max"]):
        return int(params["several_sources_bonus"])
    return int(params["many_sources_penalty"])


def classify_source_authority(source_title: str) -> str:
    """Classify a source title as high-authority or standard.
    
    High-authority sources include:
    - Manager quotes / coach interviews
    - Official club statements / announcements
    - Verified club accounts
    """
    title_lower = (source_title or "").lower()
    for pattern in HIGH_AUTHORITY_PATTERNS:
        if pattern.lower() in title_lower:
            return "high_authority"
    return "standard"


def is_weak_signal(source_diversity: int, sources: list[dict] | None = None) -> dict:
    """Determine if a trend is a weak signal based on source diversity and authority.
    
    Policy:
    - Single source with non-authority = weak signal (needs verification)
    - Single source with high-authority = NOT weak signal (context-check exception applies)
    - Multiple sources = NOT weak signal
    
    Returns dict with:
    - is_weak: bool - whether this is flagged as weak signal
    - reason: str - explanation for the classification
    - authority_classification: str - "high_authority" or "standard" (if single source)
    """
    count = int(source_diversity or 0)
    
    if count > 1:
        return {
            "is_weak": False,
            "reason": "multiple sources",
            "authority_classification": None,
        }
    
    # Single source case - check authority
    if sources and len(sources) > 0:
        source_title = sources[0].get("title", "")
    else:
        source_title = ""
    
    authority = classify_source_authority(source_title)
    
    if authority == "high_authority":
        return {
            "is_weak": False,
            "reason": "single high-authority source",
            "authority_classification": "high_authority",
        }
    else:
        return {
            "is_weak": True,
            "reason": "single non-authority source",
            "authority_classification": "standard",
        }


def authority_adjustment(
    source_diversity: int,
    sources: list[dict] | None,
    policy: dict | None = None,
) -> int:
    """Calculate adjustment based on source authority classification.
    
    - Single high-authority source: bonus
    - All other cases: no adjustment (handled by source_diversity_adjustment)
    """
    params = load_policy(policy)
    count = int(source_diversity or 0)
    
    if count != 1:
        return 0
    
    if sources and len(sources) > 0:
        source_title = sources[0].get("title", "")
    else:
        source_title = ""
    
    if classify_source_authority(source_title) == "high_authority":
        return int(params["high_authority_single_source_bonus"])
    return 0


def score_breakdown(
    *,
    base_score: int,
    novelty_score: float | None = None,
    feedback_adjustment: int = 0,
    source_diversity: int = 0,
    sources: list[dict] | None = None,
    policy: dict | None = None,
) -> dict:
    novelty_delta = novelty_adjustment(novelty_score, policy)
    diversity_delta = source_diversity_adjustment(source_diversity, policy)
    
    # Source qualification analysis
    weak_signal_check = is_weak_signal(source_diversity, sources)
    authority_delta = authority_adjustment(source_diversity, sources, policy)
    
    # Calculate weak signal penalty
    params = load_policy(policy)
    weak_signal_delta = int(params["weak_signal_penalty"]) if weak_signal_check["is_weak"] else 0
    
    total = clamp_score(
        int(base_score) 
        + int(feedback_adjustment) 
        + novelty_delta 
        + diversity_delta 
        + authority_delta 
        + weak_signal_delta
    )
    
    return {
        "base_score": int(base_score),
        "feedback_adjustment": int(feedback_adjustment),
        "novelty_adjustment": novelty_delta,
        "source_diversity_adjustment": diversity_delta,
        "authority_adjustment": authority_delta,
        "weak_signal_penalty": weak_signal_delta,
        "weak_signal": weak_signal_check["is_weak"],
        "weak_signal_reason": weak_signal_check["reason"],
        "authority_classification": weak_signal_check["authority_classification"],
        "final_score": total,
    }


def compute_final_score(
    *,
    base_score: int,
    novelty_score: float | None = None,
    feedback_adjustment: int = 0,
    source_diversity: int = 0,
    sources: list[dict] | None = None,
    policy: dict | None = None,
) -> int:
    return score_breakdown(
        base_score=base_score,
        novelty_score=novelty_score,
        feedback_adjustment=feedback_adjustment,
        source_diversity=source_diversity,
        sources=sources,
        policy=policy,
    )["final_score"]


def passes_report_gate(
    *,
    final_score: int,
    source_diversity: int,
    weak_signal: bool | None = None,
    min_score: int | None = None,
    min_sources: int | None = None,
    policy: dict | None = None,
) -> bool:
    params = load_policy(policy)
    effective_min_score = int(params["report_min_score"] if min_score is None else min_score)
    effective_min_sources = int(params["report_min_sources"] if min_sources is None else min_sources)
    
    # If explicitly marked as weak signal, require additional verification
    if weak_signal is True:
        # Weak signals need higher score to pass (adds 10-point buffer)
        effective_min_score += 10
    
    return int(final_score) >= effective_min_score and int(source_diversity) >= effective_min_sources
