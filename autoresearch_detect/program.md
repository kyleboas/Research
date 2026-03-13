# Detect Policy Tuning

This directory is a minimal `autoresearch`-style harness for the detect stage.

## Goal

Improve candidate ranking and report gating by changing the live detect policy:

- `../detect_policy.py`
- `../detect_policy_config.json`

Everything else in this directory is the fixed evaluator or frozen fixtures.

## Loop

1. Edit `../detect_policy.py` or tune `../detect_policy_config.json`
2. Run:

```bash
../.venv/bin/python eval_detect.py
```

3. Keep the change only if the printed `FINAL_SCORE=` goes up without obviously gaming the fixture

## Constraints

- Do not edit `eval_detect.py`
- Do not edit `fixtures/candidates.json`
- Do not edit labels inside the fixture to chase the metric
- Prefer small, interpretable scoring changes

## What the score rewards

- `report_now` items rank near the top
- `report_now` items pass the report gate
- `hold` items stay below the report gate

## Next step after the starter harness

Replace the synthetic fixture with a real labeled snapshot:

```bash
../.venv/bin/python export_candidates_snapshot.py --output fixtures/live_candidates.json
```

Or auto-label the obvious cases and search for better settings:

```bash
../.venv/bin/python optimize_detect_policy.py --refresh-auto --apply
```
