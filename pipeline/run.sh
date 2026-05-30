#!/bin/bash
# Store Intelligence — Detection Pipeline Runner
# Usage: bash pipeline/run.sh [DATA_DIR]
#
# Processes all CCTV clips and emits structured events to the API.
# Requires: Python 3.11+, ultralytics, supervision

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DATA_DIR="${1:-$PROJECT_DIR/Dataset}"
MODEL="${2:-yolov8m.pt}"
API_URL="${3:-http://localhost:8000}"

echo "============================================================"
echo "  Store Intelligence — Detection Pipeline"
echo "============================================================"
echo "  Data:  $DATA_DIR"
echo "  Model: $MODEL"
echo "  API:   $API_URL"
echo "============================================================"

cd "$PROJECT_DIR"

# Step 1: Load POS data into the database
echo ""
echo "[1/3] Loading POS transaction data..."
python -m pipeline.load_pos

# Step 2: Run detection pipeline
echo ""
echo "[2/3] Running detection pipeline on CCTV clips..."
python -m pipeline.detect --data-dir "$DATA_DIR" --model "$MODEL" --api-url "$API_URL"

# Step 3: Summary
echo ""
echo "[3/3] Pipeline complete!"
echo "  Events written to: output/events.jsonl"
echo "  API endpoint: $API_URL"
echo "  Dashboard: $API_URL/dashboard"
echo "============================================================"
