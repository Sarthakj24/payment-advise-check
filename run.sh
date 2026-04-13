#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Create venv if missing
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

PORT="${PORT:-8000}"
echo ""
echo "  ▶ Starting Payroll Calculator at http://127.0.0.1:${PORT}"
echo "  ▶ Demo login: admin / admin123"
echo ""

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --reload
