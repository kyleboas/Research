# Football Research Pipeline

Automatic deep research system that ingests football content, detects novel tactical trends, and generates sourced reports.

## How it works

1. **Ingest** — Fetches RSS feeds and YouTube transcripts every 2 hours, stores full content in Supabase Postgres with vector embeddings.
2. **Detect** — Uses Claude to identify novel tactics being tried by players/teams before they become mainstream.
3. **Report** — Generates a deep research report sourced by ingested content, saved to `reports/`.

All API calls route through **Cloudflare AI Gateway** for observability and rate limiting.

## Setup

1. Run `sql/schema.sql` in your Supabase SQL editor (enable pgvector first).
2. Copy `env.example` to `.env` and fill in your keys.
3. `pip install -r requirements.txt`
4. `python main.py`

## Cron (every 2 hours)

```bash
0 */2 * * * cd /path/to/research && /path/to/python main.py >> logs/run.log 2>&1
```

## Feeds

Edit `feeds/rss.md` and `feeds/youtube.md` to add/remove sources.

## Files

```
main.py              # entire pipeline (~200 lines)
sql/schema.sql       # 3 tables: sources, chunks, reports
feeds/rss.md         # RSS feed list
feeds/youtube.md     # YouTube channel list
reports/             # generated reports (gitignored)
```
