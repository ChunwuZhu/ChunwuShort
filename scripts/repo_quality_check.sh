#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python_bin="${PYTHON:-/opt/miniconda3/bin/python3.13}"

"$python_bin" -m py_compile \
  main.py \
  bot/handlers.py \
  broker/moomoo.py \
  broker/moomoo_paper.py \
  scraper/fintel.py \
  scraper_service.py \
  utils/config.py \
  utils/db.py \
  earnings_options/*.py \
  llm/*.py \
  scripts/*.py

git diff --check

if git diff --cached --name-only | grep -Eq '(^|/)(\.env|.*\.session|.*\.log|fintel_profile/|qc/data/)'; then
  echo "Refusing to commit local secrets/runtime files." >&2
  exit 1
fi
