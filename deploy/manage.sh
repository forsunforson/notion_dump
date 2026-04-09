#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUN_TASK_SCRIPT="$SCRIPT_DIR/run_task.sh"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/execution.log"
LOGS_DIR="$PROJECT_ROOT/logs"

DEBUG_STATE_FILE_DEFAULT="$PROJECT_ROOT/logs/debug_state.json"
DEBUG_STATE_FILE="${LOCAL_DEBUG_STATE_PATH:-$DEBUG_STATE_FILE_DEFAULT}"
DEBUG_TOGGLE=""
for arg in "$@"; do
    case "$arg" in
        --debug-enable) DEBUG_TOGGLE="enable" ;;
        --debug-disable) DEBUG_TOGGLE="disable" ;;
    esac
done
if [ -n "$DEBUG_TOGGLE" ]; then
    mkdir -p "$(dirname "$DEBUG_STATE_FILE")"
    if [ "$DEBUG_TOGGLE" = "enable" ]; then
        ENABLED_VALUE="true"
    else
        ENABLED_VALUE="false"
    fi
    cat > "$DEBUG_STATE_FILE" <<EOF
{"enabled": $ENABLED_VALUE, "updated_at": "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"}
EOF
    echo "✅ Debug mode updated: $ENABLED_VALUE"
    echo "State file: $DEBUG_STATE_FILE"
    exit 0
fi

# Get current system timezone
if command -v timedatectl &> /dev/null; then
    USER_TZ=$(timedatectl show --property=Timezone --value)
else
    USER_TZ=$(cat /etc/timezone 2>/dev/null || date +%Z)
fi

select_timezone() {
    echo ""
    echo "🌍 Select Timezone"
    echo "=========================================="
    echo "Current system timezone: $USER_TZ"
    echo ""
    echo "Common timezones:"
    echo "  1. Asia/Shanghai (Beijing, Shanghai)"
    echo "  2. Asia/Hong_Kong"
    echo "  3. Asia/Tokyo"
    echo "  4. Asia/Singapore"
    echo "  5. America/New_York"
    echo "  6. America/Los_Angeles"
    echo "  7. Europe/London"
    echo "  8. Europe/Paris"
    echo "  9. Custom (enter manually)"
    echo "  0. Cancel"
    echo "=========================================="
    echo -n "Select option [0-9]: "
    read tz_choice
    
    local TARGET_TZ=""

    case $tz_choice in
        1) TARGET_TZ="Asia/Shanghai" ;;
        2) TARGET_TZ="Asia/Hong_Kong" ;;
        3) TARGET_TZ="Asia/Tokyo" ;;
        4) TARGET_TZ="Asia/Singapore" ;;
        5) TARGET_TZ="America/New_York" ;;
        6) TARGET_TZ="America/Los_Angeles" ;;
        7) TARGET_TZ="Europe/London" ;;
        8) TARGET_TZ="Europe/Paris" ;;
        9)
            echo ""
            echo "Enter timezone (e.g., Asia/Shanghai, America/Chicago)"
            echo "Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            echo -n "Timezone: "
            read custom_tz
            if [ -n "$custom_tz" ]; then
                TARGET_TZ="$custom_tz"
            else
                echo "❌ Invalid timezone."
                return
            fi
            ;;
        0) 
            echo "Cancelled."
            return
            ;;
        *)
            echo "❌ Invalid option."
            return
            ;;
    esac
    
    if [ -n "$TARGET_TZ" ]; then
        echo "🔧 Changing system timezone to: $TARGET_TZ ..."
        
        # Modify system timezone
        sudo timedatectl set-timezone "$TARGET_TZ"
        
        # Restart cron daemon
        if systemctl is-active --quiet cron; then
            sudo systemctl restart cron
        elif systemctl is-active --quiet crond; then
            sudo systemctl restart crond
        fi
        
        # Update USER_TZ variable
        USER_TZ="$TARGET_TZ"
        
        echo "✅ System timezone updated! Current server time:"
        date
    fi
}

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
    echo "   ChronoFold Manager (Deploy Tool)"
    echo "=========================================="
    echo "1. 🚀 Run Task Now"
    echo "2. 🤖 Manage Bot Service"
    echo "3. ⏰ Manage Cronjobs"
    echo "4. 👀 View Logs (tail -f)"
    echo "5. 🌍 Settings (Timezone: $USER_TZ)"
    echo "6. 💼 View Balance Sheet"
    echo "7. ❌ Exit"
    echo "=========================================="
    echo -n "Select an option [1-7]: "
}

show_bot_menu() {
    echo ""
    echo "=========================================="
    echo "   🤖 Manage Bot Service"
    echo "=========================================="
    echo "1. 🛠️  Install Bot Service (Systemd)"
    echo "2. 🔄 Restart Bot"
    echo "3. ❓ Check Status"
    echo "4. 👀 View Bot Logs"
    echo "5. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-5]: "
}

show_cron_menu() {
    echo ""
    echo "=========================================="
    echo "   ⏰ Manage Cronjobs"
    echo "=========================================="
    echo "1. 📅 Schedule Tasks (Crontab)"
    echo "2. 📋 View Current Schedule"
    echo "3. 🗑️  Remove Schedule"
    echo "4. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-4]: "
}

manage_bot_service() {
    while true; do
        show_bot_menu
        read choice
        
        case $choice in
            1) # Install
                echo "⚙️  开始自动配置 Telegram Bot 系统守护进程..." 
                
                # 自动获取当前绝对路径和当前用户 
                CURRENT_USER=$(whoami) 
                SERVICE_FILE="/etc/systemd/system/chronofold-bot.service" 
    
                echo "👤 运行用户: $CURRENT_USER" 
                echo "📂 项目路径: $PROJECT_ROOT" 
    
                # 使用 sudo 生成配置文件并写入系统目录 
                sudo bash -c "cat > $SERVICE_FILE" <<EOF 
[Unit] 
Description=ChronoFold Telegram Bot Agent 
After=network.target 

[Service] 
Type=simple 
User=$CURRENT_USER 
WorkingDirectory=$PROJECT_ROOT 
ExecStart=$PROJECT_ROOT/venv/bin/python main.py --job bot 
Restart=always 
RestartSec=10 
Environment="PATH=$PROJECT_ROOT/venv/bin" 

[Install] 
WantedBy=multi-user.target 
EOF
    
                echo "✅ 配置文件已生成: $SERVICE_FILE" 
                
                # 重新加载 Systemd，设置开机自启并立刻启动 
                sudo systemctl daemon-reload 
                sudo systemctl enable chronofold-bot 
                sudo systemctl restart chronofold-bot 
                
                echo "🚀 Bot 守护进程已启动并设置为开机自启！" 
                echo "🔍 你可以使用 'sudo systemctl status chronofold-bot' 查看运行状态" 
                ;;
            2) # Restart
                echo "🔄 Restarting Bot Service..."
                sudo systemctl restart chronofold-bot
                sudo systemctl status chronofold-bot --no-pager
                echo "✅ Bot restarted."
                ;;
            3) # Status
                echo "❓ Checking Bot Status..."
                sudo systemctl status chronofold-bot --no-pager
                ;;
            4) # Logs
                echo ""
                echo "👀 Showing Bot logs (Press Ctrl+C to stop)..."
                echo "Command: journalctl -u chronofold-bot -f"
                echo "------------------------------------------"
                sudo journalctl -u chronofold-bot -f
                ;;
            5) return ;;
            *) echo "❌ Invalid option." ;;
        esac
    done
}

manage_cronjobs() {
    while true; do
        show_cron_menu
        read choice

        case $choice in
            1) schedule_submenu ;;
            2) view_schedule ;;
            3) unschedule_task ;;
            4) return ;;
            *) echo "❌ Invalid option. Please try again." ;;
        esac
    done
}

show_run_menu() {
    echo ""
    echo "=========================================="
    echo "   🚀 Run Task Now"
    echo "=========================================="
    echo "1. 🔄 Sync (Data sync)"
    echo "2. 🌅 Morning Routine (Morning greeting)"
    echo "3. 📊 Weekly Review (Weekly summary)"
    echo "4. 🗓️ Monthly Review (Monthly review report)"
    echo "5. 🤖 Telegram Bot (Run in foreground)"
    echo "6. 💹 Portfolio Sync (Sync prices)"
    echo "7. 🗂️ Rebuild Index (notion_output/index.json)"
    echo "8. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select a task to run [1-8]: "
}

show_schedule_menu() {
    echo ""
    echo "=========================================="
    echo "   📅 Schedule Tasks"
    echo "=========================================="
    echo "1. 🔄 Setup Sync Task (Data sync)"
    echo "2. 🌅 Setup Morning Routine"
    echo "3. 📊 Setup Weekly Review"
    echo "4. 🗓️ Setup Monthly Review"
    echo "5. 💹 Setup Portfolio Sync"
    echo "6. ✨ Quick Setup (Recommended)"
    echo "7. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-7]: "
}

run_task_now() {
    local job_type="$1"
    local job_name="$2"
    shift 2
    echo ""
    echo "🚀 Starting $job_name..."
    echo "------------------------------------------"
    "$RUN_TASK_SCRIPT" --job "$job_type" --skip-backup "$@" --log-level DEBUG
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
            4) run_task_now "review" "Monthly Review" --type monthly ;;
            5) run_task_now "bot" "Telegram Bot" ;;
            6) run_task_now "portfolio" "Portfolio Sync" ;;
            7) run_task_now "index" "Index Rebuild" ;;
            8) return ;;
            *) echo "❌ Invalid option. Please try again." ;;
        esac
    done
}

schedule_sync_task() {
    echo ""
    echo "📅 Setting up Sync Task..."
    echo "⚠️  Current system time: $(date)"
    echo ""
    echo "This task will sync your Notion data and backup to cloud."
    echo ""
    read -p "Enter sync interval in hours (e.g., 4 for every 4 hours, 12 for every 12 hours): " interval
    
    if ! [[ "$interval" =~ ^[0-9]+$ ]] || [ "$interval" -lt 1 ] || [ "$interval" -gt 24 ]; then
        echo "❌ Invalid interval. Please enter a number between 1 and 24."
        return
    fi
    
    cron_job="0 */$interval * * * $RUN_TASK_SCRIPT --job sync >> $LOGS_DIR/cron_sync.log 2>&1"
    
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
    echo "Enter the time (e.g., 6 for 06:00, 7 for 07:00)"
    echo ""
    read -p "Enter hour to run (0-23): " hour
    
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    
    cron_job="0 $hour * * * $RUN_TASK_SCRIPT --job morning >> $LOGS_DIR/cron_morning.log 2>&1"
    
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job morning"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Morning routine scheduled successfully!"
    echo "   Schedule: Daily at $hour:00"
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
    read -p "Enter hour to run (0-23): " hour
    
    if ! [[ "$day" =~ ^[0-7]$ ]]; then
        echo "❌ Invalid day. Please enter a number between 0 and 7."
        return
    fi
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    
    cron_job="0 $hour * * $day $RUN_TASK_SCRIPT --job weekly >> $LOGS_DIR/cron_weekly.log 2>&1"
    
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job weekly"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Weekly review scheduled successfully!"
    echo "   Schedule: Weekly on day $day at $hour:00"
    echo "   Command: $cron_job"
}

schedule_monthly_task() {
    echo ""
    echo "📅 Setting up Monthly Review..."
    echo "⚠️  Current system time: $(date)"
    echo ""
    echo "This task will generate last-month review and save it into _reports/."
    echo ""
    read -p "Enter day of month to run (1-31): " day
    read -p "Enter hour to run (0-23): " hour
    read -p "Enter minute to run (0-59): " minute

    if ! [[ "$day" =~ ^[0-9]+$ ]] || [ "$day" -lt 1 ] || [ "$day" -gt 31 ]; then
        echo "❌ Invalid day. Please enter a number between 1 and 31."
        return
    fi
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    if ! [[ "$minute" =~ ^[0-9]+$ ]] || [ "$minute" -lt 0 ] || [ "$minute" -gt 59 ]; then
        echo "❌ Invalid minute. Please enter a number between 0 and 59."
        return
    fi

    cron_job="$minute $hour $day * * $RUN_TASK_SCRIPT --job review --type monthly >> $LOGS_DIR/cron_monthly.log 2>&1"

    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job review --type monthly"; echo "$cron_job") | crontab -

    echo ""
    echo "✅ Monthly review scheduled successfully!"
    echo "   Schedule: Monthly on day $day at $(printf '%02d:%02d' "$hour" "$minute")"
    echo "   Command: $cron_job"
    if [ "$day" -gt 28 ]; then
        echo ""
        echo "ℹ️  Note: Some months don't have day $day, cron will skip those months."
        echo "   If you want it to run every month, consider using day 28."
    fi
}

schedule_portfolio_task() {
    echo ""
    echo "📅 Setting up Portfolio Sync..."
    echo "⚠️  Current system time: $(date)"
    echo ""
    echo "This task will fetch market prices and write total_equity_value_cny to notion_output/metrics.jsonl."
    echo ""
    read -p "Enter hour to run (0-23): " hour
    read -p "Enter minute to run (0-59): " minute
    
    if ! [[ "$hour" =~ ^[0-9]+$ ]] || [ "$hour" -lt 0 ] || [ "$hour" -gt 23 ]; then
        echo "❌ Invalid hour. Please enter a number between 0 and 23."
        return
    fi
    if ! [[ "$minute" =~ ^[0-9]+$ ]] || [ "$minute" -lt 0 ] || [ "$minute" -gt 59 ]; then
        echo "❌ Invalid minute. Please enter a number between 0 and 59."
        return
    fi
    
    cron_job="$minute $hour * * * $RUN_TASK_SCRIPT --job portfolio >> $LOGS_DIR/cron_portfolio.log 2>&1"
    
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job portfolio"; echo "$cron_job") | crontab -
    
    echo ""
    echo "✅ Portfolio sync scheduled successfully!"
    echo "   Schedule: Daily at $(printf '%02d:%02d' "$hour" "$minute")"
    echo "   Command: $cron_job"
}

quick_setup() {
    echo ""
    echo "✨ Quick Setup - Recommended Configuration"
    echo "=========================================="
    echo "This will set up the following tasks:"
    echo ""
    echo "  1. 🔄 Sync: Every 4 hours"
    echo "  2. 🌅 Morning: Daily at 06:00 ($USER_TZ)"
    echo "  3. 📊 Weekly: Sunday at 20:00 ($USER_TZ)"
    echo "  4. 💹 Portfolio: Daily at 18:00 ($USER_TZ)"
    echo ""
    read -p "Continue with quick setup? [y/N]: " confirm
    
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Quick setup cancelled."
        return
    fi
    
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
    
    CRON_JOB="0 */4 * * * $RUN_TASK_SCRIPT --job sync >> $LOGS_DIR/cron_sync.log 2>&1
0 6 * * * $RUN_TASK_SCRIPT --job morning >> $LOGS_DIR/cron_morning.log 2>&1
0 20 * * 0 $RUN_TASK_SCRIPT --job weekly >> $LOGS_DIR/cron_weekly.log 2>&1
0 18 * * * $RUN_TASK_SCRIPT --job portfolio >> $LOGS_DIR/cron_portfolio.log 2>&1"
    
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    
    echo ""
    echo "✅ Quick setup completed!"
    echo ""
    echo "Scheduled tasks:"
    echo "  🔄 Sync: Every 4 hours"
    echo "  🌅 Morning: Daily at 06:00"
    echo "  📊 Weekly: Sunday at 20:00"
    echo "  💹 Portfolio: Daily at 18:00"
}

schedule_submenu() {
    while true; do
        show_schedule_menu
        read choice
        case $choice in
            1) schedule_sync_task ;;
            2) schedule_morning_task ;;
            3) schedule_weekly_task ;;
            4) schedule_monthly_task ;;
            5) schedule_portfolio_task ;;
            6) quick_setup ;;
            7) return ;;
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
        echo "Tasks for ChronoFold:"
        echo ""
        crontab -l 2>/dev/null | grep "$RUN_TASK_SCRIPT" | while read line; do
            # Parse and display nicely
            if echo "$line" | grep -q "job sync"; then
                echo "  🔄 Sync: $line"
            elif echo "$line" | grep -q "job morning"; then
                echo "  🌅 Morning: $line"
            elif echo "$line" | grep -q "job weekly"; then
                echo "  📊 Weekly: $line"
            elif echo "$line" | grep -q "job review" && echo "$line" | grep -q "type monthly"; then
                echo "  🗓️ Monthly: $line"
            elif echo "$line" | grep -q "job portfolio"; then
                echo "  💹 Portfolio: $line"
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
    echo "4. Remove Monthly Review"
    echo "5. Remove Portfolio Sync"
    echo "6. Remove All Tasks"
    echo "7. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select an option [1-7]: "
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
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT --job review --type monthly"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job review --type monthly") | crontab -
                echo "✅ Monthly review removed from schedule."
            else
                echo "ℹ️  No monthly review found."
            fi
            ;;
        5)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT --job portfolio"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT --job portfolio") | crontab -
                echo "✅ Portfolio sync removed from schedule."
            else
                echo "ℹ️  No portfolio sync found."
            fi
            ;;
        6)
            if crontab -l 2>/dev/null | grep -q "$RUN_TASK_SCRIPT"; then
                (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
                echo "✅ All tasks removed from schedule."
            else
                echo "ℹ️  No scheduled tasks found."
            fi
            ;;
        7)
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

view_balance_sheet() {
    echo ""
    echo "💼 Balance Sheet (from config/profile.yaml)"
    echo "=========================================="

    local profile_path="$PROJECT_ROOT/config/profile.yaml"
    if [ ! -f "$profile_path" ]; then
        echo "❌ profile.yaml not found: $profile_path"
        return
    fi

    local py=""
    local candidates=(
        "$PROJECT_ROOT/venv/bin/python"
        "$PROJECT_ROOT/.venv/bin/python"
        "$(command -v python3)"
    )
    for c in "${candidates[@]}"; do
        if [ -n "$c" ] && [ -x "$c" ]; then
            py="$c"
            break
        fi
    done
    if [ -z "$py" ]; then
        echo "❌ python3 not found."
        return
    fi

    "$py" -m app.cli.balance_sheet --profile-path "$profile_path"
    echo "=========================================="
}

# Main loop
while true; do
    show_main_menu
    read choice
    case $choice in
        1) run_now_submenu ;;
        2) manage_bot_service ;;
        3) manage_cronjobs ;;
        4) view_logs ;;
        5) select_timezone ;;
        6) view_balance_sheet ;;
        7) echo "Bye! 👋"; exit 0 ;;
        *) echo "❌ Invalid option. Please try again." ;;
    esac
done
