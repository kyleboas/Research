# Cost Model

This document defines deterministic cost formulas for per-run and monthly estimates.

## Variables
- `T_embed`: embedding stage tokens.
- `T_gen_in`: generation stage input tokens.
- `T_gen_out`: generation stage output tokens.
- `H_embed`: embedding cache hit ratio (`0.0` to `1.0`).
- `H_gen_in`: generation-input cache hit ratio (`0.0` to `1.0`).
- `H_gen_out`: generation-output cache hit ratio (`0.0` to `1.0`, usually `0` unless output reuse is explicitly billed as cacheable).
- `R_month`: runs per month.
- `M`: model multiplier (`1.0` Sonnet baseline, `5.0` Opus default).

Default rates used by the pipeline:
- Embedding: `C_embed = $0.02 / 1M tokens`
- Sonnet input: `C_sonnet_in = $3.00 / 1M tokens`
- Sonnet output: `C_sonnet_out = $15.00 / 1M tokens`
- Opus multiplier: `M_opus = 5.0`

## Per-stage formulas

### Ingestion
No model billing:

`Cost_ingestion = 0`

### Embedding

Cache-adjusted billable tokens:

`T_embed_billable = T_embed * (1 - H_embed)`

`Cost_embedding = (T_embed_billable / 1,000,000) * C_embed`

### Generation (Sonnet baseline)

Cache-adjusted billable tokens:

`T_gen_in_billable = T_gen_in * (1 - H_gen_in)`

`T_gen_out_billable = T_gen_out * (1 - H_gen_out)`

`Cost_generation_sonnet = (T_gen_in_billable / 1,000,000) * C_sonnet_in + (T_gen_out_billable / 1,000,000) * C_sonnet_out`

### Generation (Opus)

`Cost_generation_opus = Cost_generation_sonnet * M_opus`

### Verification + Delivery
Current implementation records token telemetry but assumes no external billed model calls:

`Cost_verification = 0`

`Cost_delivery = 0`

## Per-run formula

`Cost_run = Cost_ingestion + Cost_embedding + Cost_generation_{tier} + Cost_verification + Cost_delivery`

## Monthly formula

`Cost_month = R_month * Cost_run`

## Weekly vs multi-weekly examples
Assume one run uses:
- `T_embed = 2,000,000`
- `T_gen_in = 1,200,000`
- `T_gen_out = 220,000`

No-cache baseline (`H_embed = H_gen_in = H_gen_out = 0`):
- `Cost_embedding = (2,000,000 / 1,000,000) * 0.02 = $0.04`
- `Cost_generation_sonnet = (1,200,000 / 1,000,000) * 3 + (220,000 / 1,000,000) * 15 = $6.90`
- `Cost_run_sonnet = $6.94`
- `Cost_run_opus = $6.90 * 5 + $0.04 = $34.54`

Cache-aware example (`H_embed = 0.40`, `H_gen_in = 0.25`, `H_gen_out = 0`):
- `T_embed_billable = 2,000,000 * (1 - 0.40) = 1,200,000`
- `T_gen_in_billable = 1,200,000 * (1 - 0.25) = 900,000`
- `T_gen_out_billable = 220,000 * (1 - 0) = 220,000`
- `Cost_embedding = (1,200,000 / 1,000,000) * 0.02 = $0.024`
- `Cost_generation_sonnet = (900,000 / 1,000,000) * 3 + (220,000 / 1,000,000) * 15 = $6.00`
- `Cost_run_sonnet = $6.024`
- `Cost_run_opus = $6.00 * 5 + $0.024 = $30.024`

Run frequency scenarios:
- **Weekly (4 runs/month)**
  - Sonnet (no cache): `4 * 6.94 = $27.76/month`
  - Sonnet (cache-aware): `4 * 6.024 = $24.096/month`
  - Opus (no cache): `4 * 34.54 = $138.16/month`
  - Opus (cache-aware): `4 * 30.024 = $120.096/month`
- **Multi-weekly (12 runs/month, ~3x/week)**
  - Sonnet (no cache): `12 * 6.94 = $83.28/month`
  - Sonnet (cache-aware): `12 * 6.024 = $72.288/month`
  - Opus (no cache): `12 * 34.54 = $414.48/month`
  - Opus (cache-aware): `12 * 30.024 = $360.288/month`

## Pipeline telemetry mapping
`pipeline_runs.cost_estimate_json` stores:
- `stages.ingestion|embedding|generation|verification|delivery`
- each stage has `token_count` and `estimated_cost_usd`
- top-level rollups:
  - `total_token_count`
  - `total_estimated_cost_usd`
