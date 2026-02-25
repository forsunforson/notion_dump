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

show_main_menu() {
    echo ""
    echo "=========================================="
    echo "   Notion Dump Manager (Deploy Tool)"
    echo "=========================================="
    echo "1. 🚀 Run Task Now"
    echo "2. 📅 Schedule Tasks (Crontab)"
    echo "3. 📋 View Current Schedule"
    echo "4. 🗑️  Remove Schedule"
    echo "5. 👀 View Logs (tail -f)"
    echo "6. ❌ Exit"
    echo "=========================================="
    echo -n "Select an option [1-6]: "
}

show_run_menu() {
    echo ""
    echo "=========================================="
    echo "   🚀 Run Task Now"
    echo "=========================================="
    echo "1. 🔄 Sync (Data sync and backup)"
    echo "2. 🌅 Morning Routine (Morning greeting)"
    echo "3. 📊 Weekly Review (Weekly summary)"
    echo "4. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select a task to run [1-4]: "
}

show_schedule_menu() {
    echo ""
    echo "=========================================="
    echo "   📅 Schedule Tasks"
    echo "=========================================="
    echo "1. 🔄 Setup Sync Task (Data sync)"
    echo "2. 🌅 Setup Morning Routine"
    echo "3. 📊 Setup Weekly Review"
    echo "4. ✨ Quick Setup (Recommended)"
    echo "5. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-5]: "
}

run_task_now() {
    local job_type="$1"
    local job_name="$2"
    echo ""
    echo "🚀 Starting $job_name..."
    echo "------------------------------------------"
    "$RUN_TASK_SCRIPT" --job "$job_type"
    echo "------------------------------------------"
    echo "✅ $job_name completed. Check output above or logs."
}

run_now_submenu() {
    while true; do
        show_run_menu
        read choice
        case $choice in
            1) run_task_now "sync" "Sync Task" ;;
            2) run_task_now "morning" "Morning Routine" ;;
            3) run_task_now "weekly" "Weekly Review" ;;
            4) return ;;
            *) echo "❌ Invalid option. Please try again." ;;
        esac
    done
}

schedule_sync_task() {
    echo ""
    echo "📅 Setting up Sync Task..."
    echo "⚠️  Current system time: $(date)"
    echo "   (Note: GCP VMs often use UTC time by default)"
    echo ""
    echo "This task will sync your Notion data and backup to cloud."
    echo ""
    read -p "Enter sync interval in hours (e.g., 4 for every 4 hours, 12 for every 12 hours): " interval
    
    # Validate input
    if ! [[ "$interval" =~ ^[0-9]+$ ]] || [ "$interval" -lt 1 ] || [ "$interval" -gt 24 ]; then
        echo "❌ Invalid interval. Please enter a number between 1 and 24."
        return
    fi
    
    # Construct cron job line: 0 */interval * * * 
    cron_job="0 */$interval * * * $RUN_TASK_SCRIPT --job sync"
    
    # Remove existing sync jobs and add new one
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job sync"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Sync task scheduled successfully!"
    echo "   Schedule: Every $interval hour(s)"
    echo "   Command: $cron_job"
}

schedule_morning_task() {
    echo ""
    echo "📅 Setting up Morning Routine..."
    echo "⚠️  Current system time: $(date)"
    echo ""
    echo "This task will send a morning greeting to Telegram."
    echo ""
    echo "Time reference (Beijing Time -> UTC):"
    echo "  06:00 Beijing = 22:00 UTC (previous day)"
    echo "  07:00 Beijing = 23:00 UTC (previous day)"
    echo "  08:00 Beijing = 00:00 UTC"
    echo ""
    read -p "Enter UTC hour to run (0-23): " hour
    
    # Validate input
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    
    # Construct cron job line: 0 hour * * *
    cron_job="0 $hour * * * $RUN_TASK_SCRIPT --job morning"
    
    # Remove existing morning jobs and add new one
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job morning"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Morning routine scheduled successfully!"
    echo "   Schedule: Daily at UTC $hour:00"
    echo "   Command: $cron_job"
}

schedule_weekly_task() {
    echo ""
    echo "📅 Setting up Weekly Review..."
    echo "⚠️  Current system time: $(date)"
    echo ""
    echo "This task will send a weekly summary to Telegram."
    echo ""
    echo "Day of week (0-7, where 0 and 7 are Sunday):"
    echo "  0 or 7 = Sunday"
    echo "  1 = Monday, 2 = Tuesday, ..., 6 = Saturday"
    echo ""
    read -p "Enter day of week (0-7): " day
    read -p "Enter UTC hour to run (0-23): " hour
    
    # Validate input
    if ! [[ "$day" =~ ^[0-7]$ ]]; then
        echo "❌ Invalid day. Please enter a number between 0 and 7."
        return
    fi
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    
    # Construct cron job line: 0 hour * * day
    cron_job="0 $hour * * $day $RUN_TASK_SCRIPT --job weekly"
    
    # Remove existing weekly jobs and add new one
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job weekly"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Weekly review scheduled successfully!"
    echo "   Schedule: Weekly on day $day at UTC $hour:00"
    echo "   Command: $cron_job"
}

quick_setup() {
    echo ""
    echo "✨ Quick Setup - Recommended Configuration"
    echo "=========================================="
    echo "This will set up the following tasks:"
    echo ""
    echo "  1. 🔄 Sync: Every 4 hours"
    echo "  2. 🌅 Morning: Daily at UTC 22:00 (Beijing 06:00)"
    echo "  3. 📊 Weekly: Sunday at UTC 12:00 (Beijing 20:00)"
    echo ""
    read -p "Continue with quick setup? [y/N]: " confirm
    
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Quick setup cancelled."
        return
    fi
    
    # Remove all existing jobs for this script
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
    
    # Add all three jobs
    (crontab -l 2>/dev/null; \
     echo "0 */4 * * * $RUN_TASK_SCRIPT --job sync"; \
     echo "0 22 * * * $RUN_TASK_SCRIPT --job morning"; \
     echo "0 12 * * 0 $RUN_TASK_SCRIPT --job weekly") | crontab -
    
    echo ""
    echo "✅ Quick setup completed!"
    echo ""
    echo "Scheduled tasks:"
    echo "  🔄 Sync: Every 4 hours"
    echo "  🌅 Morning: Daily at UTC 22:00 (Beijing 06:00)"
    echo "  📊 Weekly: Sunday at UTC 12:00 (Beijing 20:00)"
}

schedule_submenu() {
    while true; do
        show_schedule_menu
        read choice
        case $choice in
            1) schedule_sync_task ;;
            2) schedule_morning_task ;;
            3) schedule_weekly_task ;;
            4) quick_setup ;;
            5) return ;;
            *) echo "❌ Invalid option. Please try again." ;;
        esac
    done
}

view_schedule() {
    echo ""
    echo "📋 Current Crontab Schedule"
    echo "=========================================="
    
    local found=0
    
    if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT"; then
        echo "Tasks for Notion Dump:"
        echo ""
        crontab -l 2>/dev/null | grep "$RUN_TASK_SCRIPT" | while read line; do
            # Parse and display nicely
            if echo "$line" | grep -q "job sync"; then
                echo "  🔄 Sync: $line"
            elif echo "$line" | grep -q "job morning"; then
                echo "  🌅 Morning: $line"
            elif echo "$line" | grep -q "job weekly"; then
                echo "  📊 Weekly: $line"
            else
                echo "  ❓ Other: $line"
            fi
        done
        found=1
    fi
    
    if [ $found -eq 0 ]; then
        echo "ℹ️  No scheduled tasks found."
        echo "   Use 'Schedule Tasks' to set up automated runs."
    fi
    
    echo ""
}

unschedule_task() {
    echo ""
    echo "🗑️  Remove Scheduled Tasks"
    echo "=========================================="
    echo "1. Remove Sync Task"
    echo "2. Remove Morning Routine"
    echo "3. Remove Weekly Review"
    echo "4. Remove All Tasks"
    echo "5. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-5]: "
    read choice
    
    case $choice in
        1)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT --job sync"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job sync") | crontab -
                echo "✅ Sync task removed from schedule."
            else
                echo "ℹ️  No sync task found."
            fi
            ;;
        2)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT --job morning"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job morning") | crontab -
                echo "✅ Morning routine removed from schedule."
            else
                echo "ℹ️  No morning routine found."
            fi
            ;;
        3)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT --job weekly"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job weekly") | crontab -
                echo "✅ Weekly review removed from schedule."
            else
                echo "ℹ️  No weekly review found."
            fi
            ;;
        4)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
                echo "✅ All tasks removed from schedule."
            else
                echo "ℹ️  No scheduled tasks found."
            fi
            ;;
        5)
            return
            ;;
        *)
            echo "❌ Invalid option."
            ;;
    esac
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
    show_main_menu
    read choice
    case $choice in
        1) run_now_submenu ;;
        2) schedule_submenu ;;
        3) view_schedule ;;
        4) unschedule_task ;;
        5) view_logs ;;
        6) echo "Bye! 👋"; exit 0 ;;
        *) echo "❌ Invalid option. Please try again." ;;
    esac
done
