#!/bin/bash

# Get the directory of the currently executing script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the project root (parent of deploy/)
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || { echo "Failed to change directory to project root"; exit 1; }

# Define log directory and file
LOG_DIR="$PROJECT_ROOT/logs"

# Check and create logs directory
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi

LOG_FILE="$LOG_DIR/execution.log"

# Define the task execution logic
run_task() {
    # Check and activate virtual environment
    VENV_DIR="$PROJECT_ROOT/venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Error: Virtual environment not found at $VENV_DIR" >> "$LOG_FILE"
        exit 1
    fi
    
    source "$VENV_DIR/bin/activate"

    echo "========================================================" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task Started" >> "$LOG_FILE"

    # Run the Python script
    # The entry point is app/download_notion.py based on project structure
    python app/download_notion.py >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task Finished with exit code $EXIT_CODE" >> "$LOG_FILE"
    echo "========================================================" >> "$LOG_FILE"
}

# Use PID file for locking (works on both Linux and macOS without flock)
LOCK_FILE="$LOG_DIR/notion_dump.pid"

if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task skipped: Another instance is running (PID: $PID)." >> "$LOG_FILE"
        exit 1
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Warning: Found stale lock file (PID: $PID). Overwriting." >> "$LOG_FILE"
    fi
fi

# Write current PID to lock file
echo $$ > "$LOCK_FILE"

# Ensure lock file is removed on exit
trap 'rm -f "$LOCK_FILE"' EXIT

# Execute the task
run_task
