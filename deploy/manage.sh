#!/bin/bash

# Get directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUN_TASK_SCRIPT="$SCRIPT_DIR/run_task.sh"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/execution.log"

# Ensure run_task.sh is executable
if [ -f "$RUN_TASK_SCRIPT" ]; then
    chmod +x "$RUN_TASK_SCRIPT"
else
    echo "❌ Error: run_task.sh not found at $RUN_TASK_SCRIPT"
    exit 1
fi

show_menu() {
    echo ""
    echo "=========================================="
    echo "   Notion Dump Manager (Deploy Tool)"
    echo "=========================================="
    echo "1. 🚀 Run Now (Immediate Execution)"
    echo "2. 📅 Schedule Daily (Setup Crontab)"
    echo "3. 🗑️  Unschedule (Remove from Crontab)"
    echo "4. 👀 View Logs (tail -f)"
    echo "5. ❌ Exit"
    echo "=========================================="
    echo -n "Select an option [1-5]: "
}

run_now() {
    echo ""
    echo "🚀 Starting task immediately..."
    echo "------------------------------------------"
    "$RUN_TASK_SCRIPT"
    echo "------------------------------------------"
    echo "✅ Task execution completed. Check output above or logs."
}

schedule_task() {
    echo ""
    echo "📅 Setting up daily schedule..."
    echo "⚠️  Current system time: $(date)"
    echo "   (Please note that GCP VMs often use UTC time by default)"
    
    echo ""
    read -p "Enter the hour to run (0-23): " hour
    
    # Validate input
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    
    # Construct cron job line
    # 0 $hour * * * /path/to/deploy/run_task.sh
    cron_job="0 $hour * * * $RUN_TASK_SCRIPT"
    
    # Update crontab safely
    # 1. List current crontab (ignore error if empty)
    # 2. Filter out existing lines containing our script path
    # 3. Append the new cron job
    # 4. Install the new crontab
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT"; echo "$cron_job") | crontab -
    
    echo "✅ Scheduled successfully: $cron_job"
    echo "   (Any existing tasks for this script were updated)"
}

unschedule_task() {
    echo ""
    echo "🗑️  Removing scheduled task..."
    
    # Check if there are any jobs containing our script
    if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT"; then
        # Filter out our script and reinstall crontab
        (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
        echo "✅ Task removed from schedule."
    else
        echo "ℹ️  No scheduled task found for this script."
    fi
}

view_logs() {
    echo ""
    echo "👀 Showing logs (Press Ctrl+C to stop)..."
    echo "File: $LOG_FILE"
    echo "------------------------------------------"
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo "⚠️  Log file not found at $LOG_FILE. Has the task run yet?"
    fi
}

# Main loop
while true; do
    show_menu
    read choice
    case $choice in
        1) run_now ;;
        2) schedule_task ;;
        3) unschedule_task ;;
        4) view_logs ;;
        5) echo "Bye! 👋"; exit 0 ;;
        *) echo "❌ Invalid option. Please try again." ;;
    esac
done
