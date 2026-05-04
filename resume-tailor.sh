#!/bin/bash
# Wrapper script for resume-tailor
# Usage: ./resume-tailor.sh <command>

cd "$(dirname "$0")"
exec uv run python main.py "$@"
