# Deployment Guide

This directory contains the deployment script for the Notion Dump project.

## 1. Permission Setup

Before running the script, ensure it has execution permissions. Run the following command from the project root:

```bash
chmod +x deploy/run_task.sh
```

## 2. Crontab Configuration

To schedule the task to run automatically (e.g., daily at 02:00 AM), you can use `crontab`.

1. Open the crontab editor:
   ```bash
   crontab -e
   ```

2. Add the following line to the end of the file:
   ```cron
   0 2 * * * /path/to/notion_dump/deploy/run_task.sh
   ```

   **Important**: Replace `/path/to/notion_dump` with the actual absolute path to your project directory.

   *Example:*
   If your project is at `/home/gcp_user/notion_dump`, the line would be:
   ```cron
   0 2 * * * /home/gcp_user/notion_dump/deploy/run_task.sh
   ```

## 3. Logs & Monitoring

The script automatically creates a `logs/` directory in the project root if it doesn't exist.

- **Log File**: `logs/execution.log`
- **Lock File**: `logs/notion_dump.pid` (contains the PID of the running process)

To view the execution logs in real-time or check recent activity:

```bash
# View the last 50 lines
tail -n 50 logs/execution.log

# Follow new log entries as they happen
tail -f logs/execution.log
```

## Script Details

- **Path Handling**: The script automatically resolves its location and switches to the project root directory.
- **Concurrency**: Uses a PID file mechanism to ensure only one instance runs at a time. It checks if the process ID in the lock file is still active.
- **Environment**: Automatically activates the `venv` in the project root before running the Python script.
- **Output**: Redirects both Standard Output (Stdout) and Standard Error (Stderr) to the log file with timestamps.
