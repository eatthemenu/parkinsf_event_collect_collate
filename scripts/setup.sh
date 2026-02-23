#!/usr/bin/env bash
set -euo pipefail

echo "=== Event Aggregator Setup ==="

# System packages
echo "[1/5] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git

# Python virtual environment
echo "[2/5] Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Python dependencies
echo "[3/5] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Playwright Chromium
echo "[4/5] Installing Playwright Chromium..."
playwright install chromium
playwright install-deps chromium

# Environment file
echo "[5/5] Configuring environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    echo "  Created .env from .env.example — edit it and add your API keys."
else
    echo "  .env already exists, skipping."
fi

# Output directories (gitignored)
mkdir -p logs data/screenshots data/ai_responses

echo ""
echo "=== Setup complete ==="
echo "Edit .env with your API keys, then run:"
echo "  bash scripts/run.sh --input data/event_source_sample.csv --output data/output.csv"
