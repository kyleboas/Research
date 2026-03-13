# Report Quality Evaluation

This directory is the Railway-safe foundation for a no-LLM `autoresearch` loop
for the report stage.

## Goal

Evaluate recently generated reports and tune future report policy using a
deterministic, repeatable harness that runs entirely from the repo plus
Postgres:

- export recent reports from the `reports` table
- validate the citation IDs they reference
- score them for structural completeness, citation health, source diversity,
  and overall thoroughness

## Why this differs from detect

The detect harness scores candidate ranking directly. Report policy tuning needs
to infer what settings are likely to improve future reports without regenerating
them inside the daily loop.

This directory does that by:

1. exporting recent report outcomes from Postgres
2. evaluating them deterministically
3. simulating candidate report policies against the stored metrics
4. applying only policies that beat the current baseline by a safe margin

## Current loop

1. Export recent reports from Postgres:

```bash
../../.venv/bin/python autoresearch/report/export_reports_snapshot.py --output autoresearch/report/fixtures/recent_reports.json
```

2. Evaluate them:

```bash
../../.venv/bin/python autoresearch/report/eval_report.py --fixture autoresearch/report/fixtures/recent_reports.json
```

Or do both in one command:

```bash
../../.venv/bin/python autoresearch/report/eval_report.py --refresh-auto
```

## Constraints

- Do not depend on local `report_runs/` surviving between Railway runs
- Treat the exported fixture as the frozen input for evaluation
- Keep scoring interpretable and deterministic

## Live loop

The repo now has a closed loop for report policy tuning:

1. `eval_report.py --refresh-auto`
   exports recent report outcomes and scores them deterministically.
2. `optimize_report_policy.py --refresh-auto --apply`
   simulates candidate policies over those stored metrics and applies the best
   one only when it clears the minimum improvement threshold.
3. Railway/dashboard can trigger report policy eval and optimize runs, and
   Discord receives summaries when those runs finish.

Every optimize run is also stored in Postgres (`report_policy_runs`)
so the tuning loop has a persistent history instead of relying only on logs or
TSV artifacts.

The optimizer is also budget-aware:

- `report_policy_config.json` includes `max_report_llm_cost_usd`
- candidate policies get an estimated per-report LLM cost
- the loop prefers the highest-quality candidate that stays within budget
- if none fit, it falls back to the best quality-per-dollar candidate

`benchmark_report.py` still exists as a manual LLM-backed benchmark, but it is
not part of the hourly no-LLM autoresearch pipeline.
