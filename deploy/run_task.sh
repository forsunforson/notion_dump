#!/bin/bash

# Get the directory of the currently executing script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Navigate to the project root (parent of deploy/)
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT" || { echo "Failed to change directory to project root"; exit 1; }

if [ -f "$PROJECT_ROOT/.env" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ""|\#*) continue ;;
        esac
        if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
            k="${line%%=*}"
            v="${line#*=}"
            if [[ "$v" == \"*\" && "$v" == *\" ]]; then
                v="${v:1:${#v}-2}"
            elif [[ "$v" == \'*\' && "$v" == *\' ]]; then
                v="${v:1:${#v}-2}"
            fi
            export "$k=$v"
        fi
    done < "$PROJECT_ROOT/.env"
fi

# Define log directory and file
LOG_DIR="$PROJECT_ROOT/logs"

# Check and create logs directory
if [ ! -d "$LOG_DIR" ]; then
    mkdir -p "$LOG_DIR"
fi

LOG_FILE="$LOG_DIR/execution.log"

# Rclone Configuration
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive:chronofold-backup}"
BACKUP_FILES=(".chronofold-state.json" "chronofold-history.jsonl" ".notion-dump-state.json" "notion-dump-history.jsonl" ".env" "config/profile.yaml")
BACKUP_DIRS=("config/templates")
BOT_SERVICE_NAME="${CHRONOFOLD_BOT_SERVICE:-chronofold-bot}"

# Parse --job parameter for logging
JOB_TYPE="sync"
SKIP_BACKUP="${CHRONOFOLD_SKIP_BACKUP:-0}"
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
        --skip-backup)
            SKIP_BACKUP="1"
            shift
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

should_restart_bot_for_changed_files() {
    local changed_files="$1"
    if [ -z "$changed_files" ]; then
        return 1
    fi

    if echo "$changed_files" | grep -Eq '^(main\.py|requirements\.txt|app/|config/templates/)'; then
        return 0
    fi

    return 1
}

restart_bot_service_if_needed() {
    local changed_files="$1"

    if [ "$JOB_TYPE" = "bot" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] Skip bot auto-restart for bot job itself." >> "$LOG_FILE"
        return 0
    fi

    if ! should_restart_bot_for_changed_files "$changed_files"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] No bot-related code changes detected; skip bot restart." >> "$LOG_FILE"
        return 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] Bot-related code changes detected:" >> "$LOG_FILE"
    echo "$changed_files" | sed 's/^/[Deploy]   - /' >> "$LOG_FILE"

    if ! command -v systemctl >/dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] systemctl not found; skip bot restart." >> "$LOG_FILE"
        return 0
    fi

    if ! systemctl list-unit-files | grep -q "^${BOT_SERVICE_NAME}\.service"; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] ${BOT_SERVICE_NAME}.service not found; skip bot restart." >> "$LOG_FILE"
        return 0
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] Restarting ${BOT_SERVICE_NAME}.service..." >> "$LOG_FILE"

    if [ "$(id -u)" -eq 0 ]; then
        if systemctl restart "$BOT_SERVICE_NAME" >> "$LOG_FILE" 2>&1; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] ${BOT_SERVICE_NAME}.service restarted successfully." >> "$LOG_FILE"
            return 0
        fi
    elif command -v sudo >/dev/null 2>&1; then
        if sudo -n systemctl restart "$BOT_SERVICE_NAME" >> "$LOG_FILE" 2>&1; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] ${BOT_SERVICE_NAME}.service restarted successfully via sudo." >> "$LOG_FILE"
            return 0
        fi
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Warning] Failed to restart ${BOT_SERVICE_NAME}.service. If this runs under cron, configure passwordless sudo for systemctl restart." >> "$LOG_FILE"
    return 0
}

# Define the task execution logic
run_task() {
    local old_rev=""
    local new_rev=""
    local changed_files=""

    # 1. 自动更新代码库 (忽略本地任何临时代码修改，强制对齐线上)
    old_rev="$(git rev-parse HEAD 2>/dev/null || true)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] 拉取最新项目代码..." >> "$LOG_FILE"
    git fetch origin main >> "$LOG_FILE" 2>&1
    git reset --hard origin/main >> "$LOG_FILE" 2>&1
    new_rev="$(git rev-parse HEAD 2>/dev/null || true)"

    if [ -n "$old_rev" ] && [ -n "$new_rev" ] && [ "$old_rev" != "$new_rev" ]; then
        changed_files="$(git diff --name-only "$old_rev" "$new_rev")"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] Code updated: $old_rev -> $new_rev" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Deploy] No code revision change detected." >> "$LOG_FILE"
    fi

    # 2. 检查并激活虚拟环境
    VENV_DIR="$PROJECT_ROOT/venv"
    if [ ! -d "$VENV_DIR" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Error: Virtual environment not found at $VENV_DIR" >> "$LOG_FILE"
        exit 1
    fi
    
    source "$VENV_DIR/bin/activate"

    # (可选) 自动更新依赖
    pip install -r requirements.txt -q >> "$LOG_FILE" 2>&1

    restart_bot_service_if_needed "$changed_files"

    echo "========================================================" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task Started (Job: $JOB_TYPE)" >> "$LOG_FILE"

    # 3. 执行核心程序
    # Support --job parameter passthrough to main.py
    python main.py "${ARGS[@]}" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?

    # --- Rclone Backup Step ---
    if [ "$SKIP_BACKUP" = "1" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] [Backup] Skipped." >> "$LOG_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Task Finished with exit code $EXIT_CODE" >> "$LOG_FILE"
        echo "========================================================" >> "$LOG_FILE"
        return
    fi
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
LOCK_FILE="$LOG_DIR/chronofold.pid"

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
