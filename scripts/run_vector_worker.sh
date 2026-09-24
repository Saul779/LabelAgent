#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
poetry run python -m label_agent.main --mode vector_worker
