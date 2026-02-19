"""Lead-agent orchestration for multi-agent research planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
import re

from anthropic import Anthropic
from openai import OpenAI

from ..config import Settings
from .prompts import build_lead_agent_prompt

logger = logging.getLogger(__name__)

_REQUIRED_TASK_KEYS = {
    "angle",
    "angle_slug",
    "objective",
    "output_format",
    "search_guidance",
    "task_boundaries",
}


@dataclass(frozen=True)
class TaskDescription:
    angle: str
    angle_slug: str
    objective: str
    output_format: str
    search_guidance: str
    task_boundaries: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class LeadAgentResult:
    topic: str
    task_descriptions: list[TaskDescription]
    subagent_count: int
    complexity: str
    complexity_hint: str
    planning_reasoning: str

    def to_dict(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "task_descriptions": [item.to_dict() for item in self.task_descriptions],
            "subagent_count": self.subagent_count,
            "complexity": self.complexity,
            "complexity_hint": self.complexity_hint,
            "planning_reasoning": self.planning_reasoning,
        }


def _heuristic_complexity(topic: str) -> str:
    words = [word for word in topic.split() if word]
    lowered = topic.lower()
    if len(words) >= 10 or any(marker in lowered for marker in (" and ", " vs ", " across ")):
        return "complex"
    if len(words) <= 4:
        return "simple"
    return "moderate"


def _extract_text(response: object) -> str:
    content = getattr(response, "content", [])
    return "".join(block.text for block in content if getattr(block, "type", "") == "text").strip()


def _parse_task_descriptions(payload: object) -> list[TaskDescription]:
    if not isinstance(payload, list):
        raise ValueError("Lead agent response missing task_descriptions array")

    parsed: list[TaskDescription] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Task description at index {idx} must be an object")
        missing = sorted(_REQUIRED_TASK_KEYS - set(item.keys()))
        if missing:
            raise ValueError(f"Task description at index {idx} missing required keys: {', '.join(missing)}")

        angle_slug = str(item["angle_slug"]).strip().lower()
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", angle_slug):
            raise ValueError(f"Task description at index {idx} has invalid angle_slug '{angle_slug}'")

        parsed.append(
            TaskDescription(
                angle=str(item["angle"]).strip(),
                angle_slug=angle_slug,
                objective=str(item["objective"]).strip(),
                output_format=str(item["output_format"]).strip(),
                search_guidance=str(item["search_guidance"]).strip(),
                task_boundaries=str(item["task_boundaries"]).strip(),
            )
        )
    return parsed


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    return sum(left * right for left, right in zip(a, b, strict=False))


def _token_overlap_ratio(a: str, b: str) -> float:
    a_tokens = set(re.findall(r"\w+", a.lower()))
    b_tokens = set(re.findall(r"\w+", b.lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))


def _drop_duplicate_tasks(tasks: list[TaskDescription], settings: Settings) -> list[TaskDescription]:
    if len(tasks) < 2:
        return tasks

    combined_texts = [f"{task.objective}\n{task.task_boundaries}" for task in tasks]
    vectors: list[list[float]] | None = None

    try:
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.embeddings.create(model=settings.openai_embedding_model, input=combined_texts)
        vectors = [list(row.embedding) for row in response.data]
    except Exception as error:  # noqa: BLE001
        logger.warning("Lead agent duplicate guard embedding call failed; using token-overlap fallback: %s", error)

    kept_indices: list[int] = []
    for idx, task in enumerate(tasks):
        is_duplicate = False
        for kept_idx in kept_indices:
            if vectors and len(vectors) == len(tasks):
                similarity = _cosine_similarity(vectors[idx], vectors[kept_idx])
                if similarity > 0.85:
                    logger.warning(
                        "Dropping overlapping lead-agent task '%s' due to embedding similarity %.3f with '%s'",
                        task.angle_slug,
                        similarity,
                        tasks[kept_idx].angle_slug,
                    )
                    is_duplicate = True
                    break
            else:
                overlap = _token_overlap_ratio(combined_texts[idx], combined_texts[kept_idx])
                if overlap > 0.60:
                    logger.warning(
                        "Dropping overlapping lead-agent task '%s' due to token overlap %.3f with '%s'",
                        task.angle_slug,
                        overlap,
                        tasks[kept_idx].angle_slug,
                    )
                    is_duplicate = True
                    break

        if not is_duplicate:
            kept_indices.append(idx)

    return [tasks[idx] for idx in kept_indices]


def run_lead_agent(topic: str, settings: Settings) -> LeadAgentResult:
    complexity_hint = _heuristic_complexity(topic)
    system_prompt, user_prompt = build_lead_agent_prompt(topic, complexity_hint)

    client = Anthropic(api_key=settings.anthropic_api_key)
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            response = client.messages.create(
                model=settings.anthropic_lead_model_id,
                max_tokens=2200,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            payload = json.loads(_extract_text(response))

            if not isinstance(payload, dict):
                raise ValueError("Lead agent response must be a JSON object")

            complexity = str(payload["complexity"]).strip().lower()
            reasoning = str(payload["reasoning"]).strip()
            tasks = _parse_task_descriptions(payload.get("task_descriptions"))
            tasks = _drop_duplicate_tasks(tasks, settings)

            return LeadAgentResult(
                topic=topic,
                task_descriptions=tasks,
                subagent_count=len(tasks),
                complexity=complexity,
                complexity_hint=complexity_hint,
                planning_reasoning=reasoning,
            )
        except Exception as error:  # noqa: BLE001
            last_error = error
            logger.warning("Lead agent parse/validation failure on attempt %s/2: %s", attempt + 1, error)

    raise ValueError(f"Lead agent response was unparseable after retry: {last_error}")
