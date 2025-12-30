#!/bin/bash
# Wrapper script for running the artwork uploader locally
# Sets PYTHONPATH to include src/ directory

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Set PYTHONPATH to include src/
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

# Run the application with all passed arguments
python "${SCRIPT_DIR}/src/artwork_uploader.py" "$@"
