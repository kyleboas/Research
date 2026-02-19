"""Prompt templates for multi-pass report generation."""

from __future__ import annotations

from typing import Final

CITATION_REQUIREMENTS: Final[str] = (
    "Citation requirements:\n"
    "- Every substantive claim must include at least one inline citation.\n"
    "- Citation format is [S<source_id>:C<chunk_id>] using numeric IDs from context.\n"
    "- Do not cite sources or chunks that are not present in the provided context packet.\n"
    "- If evidence is weak or missing, explicitly state uncertainty instead of fabricating."
)

STABLE_SYSTEM_PREFIX: Final[str] = (
    "You are an evidence-grounded research writing assistant.\n"
    "You must be faithful to provided evidence and avoid unsupported claims.\n"
    f"{CITATION_REQUIREMENTS}"
)


RESEARCH_USER_TEMPLATE: Final[str] = (
    "Task topic:\n{topic}\n\n"
    "You are planning retrieval for a report. Return a JSON object with key `queries` "
    "containing 4-8 focused retrieval queries that together cover: major developments, "
    "methods, risks/limitations, and practical implications. Keep each query concise."
)

DRAFT_USER_TEMPLATE: Final[str] = (
    "Task topic:\n{topic}\n\n"
    "Context packet (JSON):\n{context_packet}\n\n"
    "Write a markdown report draft with sections: Executive Summary, Key Findings, "
    "Evidence Notes, and Open Questions. Each finding must include inline citations "
    "using the required format."
)

CRITIQUE_USER_TEMPLATE: Final[str] = (
    "Task topic:\n{topic}\n\n"
    "Context packet (JSON):\n{context_packet}\n\n"
    "Draft markdown:\n{draft_markdown}\n\n"
    "Evaluate the draft using only provided context. Return markdown with sections: "
    "Grounding Assessment, Hallucination Risks, Missing Evidence, and Revision Deltas. "
    "Each issue should point to exact sentence snippets and impacted citations."
)

REVISION_USER_TEMPLATE: Final[str] = (
    "Task topic:\n{topic}\n\n"
    "Context packet (JSON):\n{context_packet}\n\n"
    "Draft markdown:\n{draft_markdown}\n\n"
    "Critique markdown:\n{critique_markdown}\n\n"
    "Produce a final revised markdown report that incorporates critique deltas, preserves "
    "grounded claims, removes unsupported statements, and keeps inline citations compliant."
)

LEAD_AGENT_SYSTEM: Final[str] = (
    "You are the lead research orchestrator. Your job is to break a topic into non-overlapping "
    "subagent tasks with clear boundaries so work is parallelisable and non-duplicative."
)

LEAD_AGENT_USER_TEMPLATE: Final[str] = (
    "Topic:\n{topic}\n\n"
    "Complexity hint (heuristic only; you may override): {complexity_hint}\n\n"
    "Canonical angles (choose the subset needed):\n"
    "1. Latest developments and announcements\n"
    "2. Technical methods and implementation details\n"
    "3. Limitations, risks, and failure modes\n"
    "4. Business, product, and ecosystem implications\n"
    "5. Quantitative benchmarks and key statistics\n"
    "6. Open questions and unresolved debates\n"
    "7. Background and prior work\n\n"
    "Scaling rules:\n"
    "- simple topics: 1 subagent\n"
    "- moderate topics: 2-4 subagents\n"
    "- complex topics: 5-7 subagents\n\n"
    "Assess actual complexity yourself and explain your decomposition reasoning.\n"
    "Return STRICT JSON with keys: `complexity` (simple|moderate|complex), `reasoning` (string), "
    "`task_descriptions` (array).\n"
    "Each item in `task_descriptions` must include exactly: `angle`, `angle_slug`, `objective`, "
    "`output_format`, `search_guidance` (initial broad query + suggested narrowing directions), "
    "and `task_boundaries` (explicitly out-of-scope work)."
)

SUBAGENT_SYSTEM: Final[str] = (
    "You are a focused research subagent. Stay strictly within your assigned task boundaries and "
    "summarise evidence with precise inline citations."
)

SUBAGENT_USER_TEMPLATE: Final[str] = (
    "Assigned angle: {angle}\n"
    "Objective: {objective}\n"
    "Search guidance: {search_guidance}\n"
    "Task boundaries (out of scope): {task_boundaries}\n\n"
    "Retrieved chunks for this search round (JSON):\n{chunks_json}\n\n"
    "Write a concise evidence-grounded summary for your angle using inline citations in the form "
    "[S<source_id>:C<chunk_id>]. Use evidence from all chunks collected across rounds."
)

SUBAGENT_EVAL_SYSTEM: Final[str] = (
    "You evaluate whether a subagent has enough evidence or must run another retrieval round."
)

SUBAGENT_EVAL_USER_TEMPLATE: Final[str] = (
    "Angle: {angle}\n"
    "Objective: {objective}\n"
    "Current round: {round_number}\n\n"
    "Chunks retrieved so far (JSON):\n{chunks_json}\n\n"
    "Return STRICT JSON with keys: `sufficient` (bool), `gaps` (list[str]), and `next_query` "
    "(string or null). If sufficient=true, set next_query to null."
)

SYNTHESIS_SYSTEM: Final[str] = (
    "You are a synthesis editor combining multiple subagent outputs into one coherent cited markdown report."
)

SYNTHESIS_USER_TEMPLATE: Final[str] = (
    "Topic: {topic}\n\n"
    "Subagent summaries (angle + summary):\n{subagent_summaries}\n\n"
    "Deduplicated chunks (JSON):\n{chunks_json}\n\n"
    "Failed angles (if any):\n{failed_angles}\n\n"
    "Produce markdown matching research.md style:\n"
    "- Descriptive H1 title\n"
    "- Numbered H2 sections with topic-specific angle headings\n"
    "- Optional H3 subsections\n"
    "- **Bold** key figures/statistics inline\n"
    "- Tables for structured comparisons when useful\n"
    "- `---` separators between major sections\n"
    "- Standalone `## Conclusion` section\n"
    "Explicitly acknowledge failed angles in relevant sections or conclusion. Keep citation format "
    "as [S<source_id>:C<chunk_id>]."
)

LLM_JUDGE_SYSTEM: Final[str] = (
    "You are an impartial report judge. Score quality using only the report text and source chunks provided."
)

LLM_JUDGE_USER_TEMPLATE: Final[str] = (
    "Final report markdown:\n{report_markdown}\n\n"
    "Source chunk texts (JSON):\n{chunks_json}\n\n"
    "Return STRICT JSON with keys: `factual_accuracy`, `citation_accuracy`, `completeness`, "
    "`source_quality`, `source_diversity` (all floats in [0.0, 1.0]), and `overall_pass` (bool)."
)


TREND_SYSTEM: Final[str] = (
    "You are a football research analyst specialising in identifying emerging tactical and strategic trends. "
    "Your task is to surface patterns that are gaining momentum across multiple sources — ideas being discussed "
    "by analysts, coaches, and reporters that signal a shift in how the game is evolving. "
    "Avoid obvious or already-mainstream topics. Focus on what is new and gaining traction."
)

TREND_USER_TEMPLATE: Final[str] = (
    "Here are titles and excerpts from recent football articles and transcripts:\n\n"
    "{sources_summary}\n\n"
    "Recent topic history to avoid repeating:\n"
    "{recent_topics_block}\n\n"
    "Source activity summary:\n"
    "{source_activity_summary}\n\n"
    "Identify 3-5 emerging football trend candidates and return them as a JSON array.\n"
    "Each array object must contain exactly these keys:\n"
    '- `rank` (int)\n'
    '- `topic` (10-20 word phrase)\n'
    '- `justification` (25 words max)\n'
    '- `source_count` (int)\n\n'
    "## Ranking criteria\n"
    "Rank candidates by weighing:\n"
    "1) Velocity: mentions accelerating in the last 2 days versus the prior 5 days.\n"
    "2) Cross-source convergence: appears across both [ARTICLE] and [TRANSCRIPT] sources.\n"
    "3) First-appearance recency: earliest appearance is within the last 48 hours.\n"
    "Rank lower any topic discussed at a flat rate across the whole window.\n\n"
    "Return only valid JSON; do not include markdown fences or additional prose."
)

TREND_REPROMPT_USER_TEMPLATE: Final[str] = (
    "The previous topic phrase was rejected for being too broad or malformed:\n"
    "\"{rejected_phrase}\"\n\n"
    "Provide one more specific replacement topic phrase in 10-20 words.\n"
    "Return plain text only."
)


def build_trend_prompt(
    *,
    sources_summary: str,
    recent_topics_block: str,
    source_activity_summary: str,
) -> tuple[str, str]:
    return TREND_SYSTEM, TREND_USER_TEMPLATE.format(
        sources_summary=sources_summary,
        recent_topics_block=recent_topics_block,
        source_activity_summary=source_activity_summary,
    )


def build_trend_reprompt(*, rejected_phrase: str) -> tuple[str, str]:
    return TREND_SYSTEM, TREND_REPROMPT_USER_TEMPLATE.format(rejected_phrase=rejected_phrase)


def build_research_prompt(topic: str) -> tuple[str, str]:
    return STABLE_SYSTEM_PREFIX, RESEARCH_USER_TEMPLATE.format(topic=topic)


def build_draft_prompt(*, topic: str, context_packet: str) -> tuple[str, str]:
    return STABLE_SYSTEM_PREFIX, DRAFT_USER_TEMPLATE.format(topic=topic, context_packet=context_packet)


def build_critique_prompt(*, topic: str, context_packet: str, draft_markdown: str) -> tuple[str, str]:
    return STABLE_SYSTEM_PREFIX, CRITIQUE_USER_TEMPLATE.format(
        topic=topic,
        context_packet=context_packet,
        draft_markdown=draft_markdown,
    )


def build_revision_prompt(
    *,
    topic: str,
    context_packet: str,
    draft_markdown: str,
    critique_markdown: str,
) -> tuple[str, str]:
    return STABLE_SYSTEM_PREFIX, REVISION_USER_TEMPLATE.format(
        topic=topic,
        context_packet=context_packet,
        draft_markdown=draft_markdown,
        critique_markdown=critique_markdown,
    )


def build_lead_agent_prompt(topic: str, complexity_hint: str) -> tuple[str, str]:
    return LEAD_AGENT_SYSTEM, LEAD_AGENT_USER_TEMPLATE.format(topic=topic, complexity_hint=complexity_hint)


def build_subagent_prompt(
    angle: str,
    objective: str,
    search_guidance: str,
    task_boundaries: str,
    chunks_json: str,
) -> tuple[str, str]:
    return SUBAGENT_SYSTEM, SUBAGENT_USER_TEMPLATE.format(
        angle=angle,
        objective=objective,
        search_guidance=search_guidance,
        task_boundaries=task_boundaries,
        chunks_json=chunks_json,
    )


def build_subagent_eval_prompt(
    angle: str,
    objective: str,
    chunks_json: str,
    round_number: int,
) -> tuple[str, str]:
    return SUBAGENT_EVAL_SYSTEM, SUBAGENT_EVAL_USER_TEMPLATE.format(
        angle=angle,
        objective=objective,
        chunks_json=chunks_json,
        round_number=round_number,
    )


def build_synthesis_prompt(
    topic: str,
    subagent_summaries: str,
    chunks_json: str,
    failed_angles: str,
) -> tuple[str, str]:
    return SYNTHESIS_SYSTEM, SYNTHESIS_USER_TEMPLATE.format(
        topic=topic,
        subagent_summaries=subagent_summaries,
        chunks_json=chunks_json,
        failed_angles=failed_angles,
    )


def build_llm_judge_prompt(report_markdown: str, chunks_json: str) -> tuple[str, str]:
    return LLM_JUDGE_SYSTEM, LLM_JUDGE_USER_TEMPLATE.format(
        report_markdown=report_markdown,
        chunks_json=chunks_json,
    )
