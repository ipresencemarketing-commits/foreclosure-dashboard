#!/bin/bash
# run_daily.sh — launchd entry point for the daily foreclosure pipeline
#
# This wrapper is called by launchd instead of update.sh directly.
# It handles output logging explicitly (launchd's StandardOutPath has
# compatibility issues on some macOS setups).

LOG="/Users/jarvis/Documents/Claude/Foreclosures/logs/last_run.log"

# Rotate: keep last run's log as .prev
[ -f "$LOG" ] && cp "$LOG" "${LOG}.prev"

# Run the pipeline, capturing both stdout and stderr to the log
exec > "$LOG" 2>&1

bash /Users/jarvis/Documents/Claude/Foreclosures/scripts/update.sh --no-push
