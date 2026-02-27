#!/bin/bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUN_TASK_SCRIPT="$SCRIPT_DIR/run_task.sh"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/execution.log"
LOGS_DIR="$PROJECT_ROOT/logs"

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
    echo "   Notion Dump Manager (Deploy Tool)"
    echo "=========================================="
    echo "1. 🚀 Run Task Now"
    echo "2. 🤖 Manage Bot Service"
    echo "3. 📅 Schedule Tasks (Crontab)"
    echo "4. 📋 View Current Schedule"
    echo "5. 🗑️  Remove Schedule"
    echo "6. 👀 View Logs (tail -f)"
    echo "7. 🌍 Settings (Timezone: $USER_TZ)"
    echo "8. ❌ Exit"
    echo "=========================================="
    echo -n "Select an option [1-8]: "
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

manage_bot_service() {
    while true; do
        show_bot_menu
        read choice
        
        case $choice in
            1) # Install
                echo "⚙️  开始自动配置 Telegram Bot 系统守护进程..." 
                
                # 自动获取当前绝对路径和当前用户 
                CURRENT_USER=$(whoami) 
                SERVICE_FILE="/etc/systemd/system/notion-bot.service" 
    
                echo "👤 运行用户: $CURRENT_USER" 
                echo "📂 项目路径: $PROJECT_ROOT" 
    
                # 使用 sudo 生成配置文件并写入系统目录 
                sudo bash -c "cat > $SERVICE_FILE" <<EOF 
[Unit] 
Description=Notion Dump Telegram Bot Agent 
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
                sudo systemctl enable notion-bot 
                sudo systemctl restart notion-bot 
                
                echo "🚀 Bot 守护进程已启动并设置为开机自启！" 
                echo "🔍 你可以使用 'sudo systemctl status notion-bot' 查看运行状态" 
                ;;
            2) # Restart
                echo "🔄 Restarting Bot Service..."
                sudo systemctl restart notion-bot
                sudo systemctl status notion-bot --no-pager
                echo "✅ Bot restarted."
                ;;
            3) # Status
                echo "❓ Checking Bot Status..."
                sudo systemctl status notion-bot --no-pager
                ;;
            4) # Logs
                echo ""
                echo "👀 Showing Bot logs (Press Ctrl+C to stop)..."
                echo "Command: journalctl -u notion-bot -f"
                echo "------------------------------------------"
                sudo journalctl -u notion-bot -f
                ;;
            5) return ;;
            *) echo "❌ Invalid option." ;;
        esac
    done
}

show_run_menu() {
    echo ""
    echo "=========================================="
    echo "   🚀 Run Task Now"
    echo "=========================================="
    echo "1. 🔄 Sync (Data sync and backup)"
    echo "2. 🌅 Morning Routine (Morning greeting)"
    echo "3. 📊 Weekly Review (Weekly summary)"
    echo "4. 🤖 Telegram Bot (Run in foreground)"
    echo "5. ◀️  Back to Main Menu"
    echo "=========================================="
    echo -n "Select a task to run [1-5]: "
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
    "$RUN_TASK_SCRIPT" --job "$job_type" --log-level DEBUG
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
            4) run_task_now "bot" "Telegram Bot" ;;
            5) return ;;
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

quick_setup() {
    echo ""
    echo "✨ Quick Setup - Recommended Configuration"
    echo "=========================================="
    echo "This will set up the following tasks:"
    echo ""
    echo "  1. 🔄 Sync: Every 4 hours"
    echo "  2. 🌅 Morning: Daily at 06:00 ($USER_TZ)"
    echo "  3. 📊 Weekly: Sunday at 20:00 ($USER_TZ)"
    echo ""
    read -p "Continue with quick setup? [y/N]: " confirm
    
    if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
        echo "Quick setup cancelled."
        return
    fi
    
    (crontab -l 2>/dev/null | grep -v "$RUN_TASK_SCRIPT") | crontab -
    
    CRON_JOB="0 */4 * * * $RUN_TASK_SCRIPT --job sync >> $LOGS_DIR/cron_sync.log 2>&1
0 6 * * * $RUN_TASK_SCRIPT --job morning >> $LOGS_DIR/cron_morning.log 2>&1
0 20 * * 0 $RUN_TASK_SCRIPT --job weekly >> $LOGS_DIR/cron_weekly.log 2>&1"
    
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    
    echo ""
    echo "✅ Quick setup completed!"
    echo ""
    echo "Scheduled tasks:"
    echo "  🔄 Sync: Every 4 hours"
    echo "  🌅 Morning: Daily at 06:00"
    echo "  📊 Weekly: Sunday at 20:00"
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
        2) manage_bot_service ;;
        3) schedule_submenu ;;
        4) view_schedule ;;
        5) unschedule_task ;;
        6) view_logs ;;
        7) select_timezone ;;
        8) echo "Bye! 👋"; exit 0 ;;
        *) echo "❌ Invalid option. Please try again." ;;
    esac
done
