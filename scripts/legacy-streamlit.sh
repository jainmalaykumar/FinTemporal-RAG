#!/usr/bin/env bash
# Runs the deprecated Streamlit UI (app.py) — kept as a fallback only.
# See README.md for why / when to retire this.
set -e
cd "$(dirname "$0")/.."

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate ChatBot

streamlit run app.py
