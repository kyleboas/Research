#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SKIP_PIP=false
SKIP_DB=false

for arg in "$@"; do
  case "$arg" in
    --skip-pip)
      SKIP_PIP=true
      ;;
    --skip-db)
      SKIP_DB=true
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/setup.sh [--skip-pip] [--skip-db]

Bootstraps local development:
  1. Creates .venv if missing
  2. Installs Python dependencies
  3. Creates .env from .env.example if missing
  4. Applies SQL migrations if POSTGRES_DSN + psql are available
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not installed." >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "[setup] Creating virtual environment in .venv"
  python3 -m venv .venv
else
  echo "[setup] Reusing existing virtual environment in .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate

if [ "$SKIP_PIP" = false ]; then
  echo "[setup] Installing Python dependencies"
  python -m pip install --upgrade pip
  pip install anthropic openai "psycopg[binary]" pytest
else
  echo "[setup] Skipping dependency installation (--skip-pip)"
fi

if [ ! -f ".env" ]; then
  if [ -f ".env.example" ]; then
    cp .env.example .env
    echo "[setup] Created .env from .env.example"
  else
    echo "[setup] .env.example not found; skipped .env creation"
  fi
else
  echo "[setup] Found existing .env; leaving as-is"
fi

if [ "$SKIP_DB" = false ] && [ -n "${POSTGRES_DSN:-}" ]; then
  if command -v psql >/dev/null 2>&1; then
    echo "[setup] Applying database SQL files"
    psql "$POSTGRES_DSN" -f sql/001_init.sql
    psql "$POSTGRES_DSN" -f sql/002_vector_indexes.sql
    psql "$POSTGRES_DSN" -f sql/003_hybrid_search.sql
  else
    echo "[setup] POSTGRES_DSN set but psql not found; skipping DB setup"
  fi
else
  if [ "$SKIP_DB" = true ]; then
    echo "[setup] Skipping DB setup (--skip-db)"
  else
    echo "[setup] POSTGRES_DSN is not set; skipping DB setup"
  fi
fi

echo
echo "Setup complete."
echo "Next steps:"
echo "  1) Fill in .env with your real credentials"
echo "  2) Activate env: source .venv/bin/activate"
echo "  3) Run tests: pytest -q"
