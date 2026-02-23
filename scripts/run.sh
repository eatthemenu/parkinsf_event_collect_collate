#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Activate virtual environment if not already active
if [ -z "${VIRTUAL_ENV:-}" ]; then
    source .venv/bin/activate
fi

exec python -m src.main "$@"
