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

# Rclone Configuration
RCLONE_REMOTE="gdrive:notion-dump-backup"
BACKUP_FILES=(".notion-dump-state.json" "notion-dump-history.jsonl" ".env" "config/profile.yaml")
BACKUP_DIRS=("config/templates")

# Parse --job parameter for logging
JOB_TYPE="sync"
ARGS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --job)
            JOB_TYPE="$2"
            ARGS+=("$1" "$2")
            shift 2
            ;;
        --log-level)
            ARGS+=("$1" "$2")
            shift 2
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

# Define the task execution logic
run_task() {
    # 1. 自动更新代码库 (忽略本地任何临时代码修改，强制对齐线上)
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] 拉取最新项目代码..." >> "$LOG_FILE"
    git fetch origin main >> "$LOG_FILE" 2>&1
    git reset --hard origin/main >> "$LOG_FILE" 2>&1

    # 2. 检查并激活虚拟环境
    VENV_DIR="$PROJECT_ROOT/venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Error: Virtual environment not found at $VENV_DIR" >> "$LOG_FILE"
        exit 1
    fi
    
    source "$VENV_DIR/bin/activate"

    # (可选) 自动更新依赖
    pip install -r requirements.txt -q >> "$LOG_FILE" 2>&1

    echo "========================================================" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task Started (Job: $JOB_TYPE)" >> "$LOG_FILE"

    # 3. 执行核心程序
    # Support --job parameter passthrough to main.py
    python main.py "${ARGS[@]}" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?

    # --- Rclone Backup Step ---
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Backup] Starting Rclone sync..." >> "$LOG_FILE"

    if command -v rclone &> /dev/null; then
        # Sync State Files
        for file in "${BACKUP_FILES[@]}"; do
            if [ -f "$file" ]; then
                rclone copy "$file" "$RCLONE_REMOTE/state/" --quiet >> "$LOG_FILE" 2>&1
                if [ $? -ne 0 ]; then
                    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Error] Backup failed for file: $file" >> "$LOG_FILE"
                fi
            fi
        done

        # Sync Config Directories
        for dir in "${BACKUP_DIRS[@]}"; do
            if [ -d "$dir" ]; then
                rclone sync "$dir/" "$RCLONE_REMOTE/state/$dir/" --quiet >> "$LOG_FILE" 2>&1
                if [ $? -ne 0 ]; then
                    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Error] Backup failed for directory: $dir" >> "$LOG_FILE"
                fi
            fi
        done

        # Sync Output Data
        if [ -d "notion_output" ]; then
            rclone sync "notion_output/" "$RCLONE_REMOTE/data/" \
                --exclude ".git/**" --transfers 4 --quiet >> "$LOG_FILE" 2>&1
            if [ $? -ne 0 ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Error] Backup failed for notion_output/" >> "$LOG_FILE"
            fi
        fi

        # Sync Reports
        if [ -d "_reports" ]; then
            rclone sync "_reports/" "$RCLONE_REMOTE/reports/" \
                --transfers 4 --quiet >> "$LOG_FILE" 2>&1
            if [ $? -ne 0 ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Error] Backup failed for _reports/" >> "$LOG_FILE"
            fi
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Warning] rclone command not found. Skipping backup." >> "$LOG_FILE"
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Backup] Finished." >> "$LOG_FILE"
    # --------------------------

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
